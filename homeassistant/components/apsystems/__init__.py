"""The APsystems local API integration."""

import re

from APsystemsEZ1 import APsystemsEZ1M

from homeassistant.const import CONF_IP_ADDRESS, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_DEVICE_TYPE, DEFAULT_PORT, DEVICE_TYPE_LAKE6, DOMAIN
from .coordinator import ApSystemsConfigEntry, ApSystemsData, ApSystemsDataCoordinator
from .lake6.client import Lake6ApiClient
from .lake6.const import LAKE6_DEFAULT_PORT
from .lake6.coordinator import Lake6Coordinator, Lake6RuntimeData
from .lake6.dashboard import async_provision_dashboard, async_remove_dashboard

# 分时计划已改为单个 text 实体承载；这些 unique_id 是旧版逐规则实体留下的
# 旧命名是 {device_id}_tou_{n}_tou_{kind}，即规则序号后面还跟着实体 key
_RETIRED_TOU_ENTITY = re.compile(
    r"_tou_(?:\d+_tou_(?:power|function|enabled|weekdays|start|end)|schedule)$"
)

# 分时计划格式提示实体已彻底下线：它曾先后落在 button 与 sensor 两个域，
# 注册表按域区分条目，这两类旧行都不会被自动回收，只能显式删掉
_TOU_FORMAT_SUFFIX = "_tou_schedule_format"

# 离网输出（`/modes` 的 offgrid_on）还没有对应的产品功能，实体默认隐藏；
# `entity_registry_enabled_default` 只作用于新建的行，旧条目靠下面的清理隐藏
_HIDDEN_ENTITY_SUFFIXES = ("_offgrid_output_enabled",)

# EZ1 没有 select / text 平台。两份列表分开维护，避免给 EZ1 多加载空平台
EZ1_PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]

LAKE6_PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TEXT,
]


async def async_setup_entry(hass: HomeAssistant, entry: ApSystemsConfigEntry) -> None:
    """Set up this integration using UI."""
    if entry.data.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_LAKE6:
        runtime = entry.runtime_data = await _async_setup_lake6(hass, entry)
        platforms = LAKE6_PLATFORMS
        await _async_drop_retired_tou_entities(hass, entry)
        await _async_disable_hidden_entities(hass, entry)
    else:
        runtime = entry.runtime_data = await _async_setup_ez1(hass, entry)
        platforms = EZ1_PLATFORMS
    await hass.config_entries.async_forward_entry_setups(entry, platforms)
    if isinstance(runtime, Lake6RuntimeData):
        # 实体已注册，才能把真实 entity_id 写进集成自带的面板
        await async_provision_dashboard(hass, entry, runtime.device_id)


async def async_unload_entry(hass: HomeAssistant, entry: ApSystemsConfigEntry) -> None:
    """Unload a config entry."""
    # 按条目数据判型，不读 runtime_data：配置条目卸载时 HA 会先
    # delattr(runtime_data)，那份数据不能当作稳定事实
    platforms = (
        LAKE6_PLATFORMS
        if entry.data.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_LAKE6
        else EZ1_PLATFORMS
    )
    await hass.config_entries.async_unload_platforms_or_raise(entry, platforms)


async def async_remove_entry(
    hass: HomeAssistant, entry: ApSystemsConfigEntry
) -> None:
    """Drop the bundled dashboard once the last Lake_6 device is gone.

    Home Assistant unregisters the entry before calling this hook, so whatever
    is still listed is a device that keeps the dashboard populated.
    """
    if any(
        other.data.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_LAKE6
        for other in hass.config_entries.async_entries(DOMAIN)
    ):
        return
    await async_remove_dashboard(hass)


async def _async_setup_ez1(
    hass: HomeAssistant, entry: ApSystemsConfigEntry
) -> ApSystemsData:
    """Build the EZ1 client and coordinator."""
    api = APsystemsEZ1M(
        ip_address=entry.data[CONF_IP_ADDRESS],
        port=entry.data.get(CONF_PORT, DEFAULT_PORT),
        timeout=8,
        enable_debounce=True,
    )
    coordinator = ApSystemsDataCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    assert entry.unique_id
    return ApSystemsData(coordinator=coordinator, device_id=entry.unique_id)


async def _async_setup_lake6(
    hass: HomeAssistant, entry: ApSystemsConfigEntry
) -> Lake6RuntimeData:
    """Build the Lake_6 client and coordinator."""
    client = Lake6ApiClient(
        host=entry.data[CONF_IP_ADDRESS],
        session=async_get_clientsession(hass),
        port=entry.data.get(CONF_PORT, LAKE6_DEFAULT_PORT),
    )
    coordinator = Lake6Coordinator(hass, entry, client)
    # 首次刷新失败会转成 ConfigEntryNotReady，条目自动进入重试（§10 P7）
    await coordinator.async_config_entry_first_refresh()
    return Lake6RuntimeData(
        coordinator=coordinator,
        device_id=coordinator.device.dev_id,
        device=coordinator.device,
    )


async def _async_disable_hidden_entities(
    hass: HomeAssistant,
    entry: ApSystemsConfigEntry,
) -> None:
    """Hide entities whose device field has no product feature yet."""
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if not (entity.unique_id or "").endswith(_HIDDEN_ENTITY_SUFFIXES):
            continue
        if entity.disabled_by is not None:
            continue
        registry.async_update_entity(
            entity.entity_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION
        )


async def _async_drop_retired_tou_entities(
    hass: HomeAssistant,
    entry: ApSystemsConfigEntry,
) -> None:
    """Drop registry rows left behind by earlier TOU entity layouts.

    The schedule is one text entity now, so a device that ever loaded the
    previous per-rule design would otherwise keep 19 unavailable rows forever.
    The format sheet is gone entirely, so its row has to go too.
    """
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        unique_id = entity.unique_id or ""
        if unique_id.endswith(_TOU_FORMAT_SUFFIX) or _RETIRED_TOU_ENTITY.search(
            unique_id
        ):
            registry.async_remove(entity.entity_id)
