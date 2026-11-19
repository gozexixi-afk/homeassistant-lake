"""Switch platform for the APsystems Lake_6 integration."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, override

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import LAKE6_SWITCH_ENTITY_TO_FIELD
from .coordinator import Lake6ConfigEntry, Lake6Coordinator, Lake6Data
from .entity import Lake6Entity


@dataclass(frozen=True, kw_only=True)
class Lake6SwitchEntityDescription(SwitchEntityDescription):
    """Describes a Lake_6 boolean flag on `/modes`."""

    value_fn: Callable[[Lake6Data], bool | None]


SWITCHES: tuple[Lake6SwitchEntityDescription, ...] = (
    # 实体 key 用 eco_mode / offgrid_output_enabled，与设备字段 eco / offgrid_on
    # 不同名；写回时靠 LAKE6_SWITCH_ENTITY_TO_FIELD 反查
    Lake6SwitchEntityDescription(
        key="eco_mode",
        translation_key="eco_mode",
        value_fn=lambda d: d.modes.eco,
    ),
    Lake6SwitchEntityDescription(
        key="offgrid_output_enabled",
        translation_key="offgrid_output_enabled",
        value_fn=lambda d: d.modes.offgrid_on,
        # 离网输出还没有对应的产品功能（App 未实现，协议里的 offgrid_on 可能
        # 下线），先默认隐藏；需要时可在实体设置里手动启用
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: Lake6ConfigEntry,
    add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Lake_6 switch platform."""
    coordinator = config_entry.runtime_data.coordinator
    add_entities(
        Lake6SwitchEntity(coordinator, description) for description in SWITCHES
    )


class Lake6SwitchEntity(Lake6Entity, SwitchEntity):
    """A writable boolean flag backed by one `/modes` field."""

    entity_description: Lake6SwitchEntityDescription

    def __init__(
        self,
        coordinator: Lake6Coordinator,
        entity_description: Lake6SwitchEntityDescription,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._attr_unique_id = f"{self.device_id}_{entity_description.key}"

    @property
    @override
    def is_on(self) -> bool | None:
        """Return the flag reported by `/modes`."""
        return self.entity_description.value_fn(self.coordinator.data)

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the flag on."""
        await self._async_write("1")

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the flag off."""
        await self._async_write("0")

    async def _async_write(self, value: str) -> None:
        """Write one flag."""
        field = LAKE6_SWITCH_ENTITY_TO_FIELD[self.entity_description.key]
        await self.coordinator.async_set_modes(**{field: value})
