"""Coordinator for the APsystems Lake_6 local API."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any, override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from ..const import DOMAIN
from .client import (
    Lake6Alarms,
    Lake6ApiClient,
    Lake6ApiError,
    Lake6ControlPanel,
    Lake6Device,
    Lake6Energies,
    Lake6Modes,
)
from .const import (
    LAKE6_CONTROL_PANEL_MODE_ACTIVE,
    LAKE6_CONTROL_PANEL_MODE_IDLE,
    LAKE6_CONTROL_PANEL_SETTLE,
    LAKE6_CONTROL_PANEL_START_BACKDATES,
    LAKE6_CONTROL_PANEL_TIME_FORMATS,
    LAKE6_CONTROL_PANEL_UPDATE_INTERVAL,
    LAKE6_MANUAL_MODE_STANDBY,
    LAKE6_MANUAL_MODE_TO_POWER_SIGN,
    LAKE6_MANUAL_POWER_STANDBY,
    LAKE6_MODES_UPDATE_INTERVAL,
    LAKE6_UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class Lake6ManualControl:
    """Pending manual control request, one field per config entity.

    The device clears `MI1` as soon as the one-time run finishes. A rejected
    request keeps the staged values so it can be retried as typed, but a run
    that ended on its own drops them (`finish_run`), so the UI returns to a
    blank form instead of looking like a pending request. An interrupt drops
    them the same way, via `reset`.
    """

    mode: str | None = None
    power: int | None = None
    duration: int | None = None
    # 下发那一刻的暂存快照：跑完自然结束时只有 staged 值没被改动过才清空，
    # 免得把运行期间新填的请求一起抹掉
    _sent: tuple[str | None, int | None, int | None] | None = None
    # 最近一次下发的结果。设备跑完就清空 MI1，这层记录是回看「上次到底发了什么」
    # 的唯一入口，因此只由下发动作写，编辑实体时不清空
    last_sent_at: datetime | None = None
    last_error: str | None = None

    @property
    def signed_power(self) -> int | None:
        """Return what `MI1.power` should carry, sign included.

        Positive discharges, negative charges and zero means standby (§4.7).
        Standby needs no power entity value, since it always sends zero.
        """
        if self.mode is None:
            return None
        if self.mode == LAKE6_MANUAL_MODE_STANDBY:
            return LAKE6_MANUAL_POWER_STANDBY
        if self.power is None:
            return None
        return LAKE6_MANUAL_MODE_TO_POWER_SIGN[self.mode] * self.power

    def reset(self) -> None:
        """Drop the staged request; `last_sent_at` keeps its history value."""
        self.mode = None
        self.power = None
        self.duration = None
        self._sent = None

    def mark_sent(self) -> None:
        """Snapshot the staged values that started the running window."""
        self._sent = (self.mode, self.power, self.duration)

    def finish_run(self) -> None:
        """Drop the staged request after the window ended on its own.

        Only when the staged values are still the ones that were sent:
        re-staging while the run lasted must survive the cleanup.
        """
        if self._sent is not None and (self.mode, self.power, self.duration) == self._sent:
            self.reset()


@dataclass
class Lake6Data:
    """Complete snapshot produced by one refresh."""

    energies: Lake6Energies
    alarms: Lake6Alarms
    modes: Lake6Modes
    control_panel: Lake6ControlPanel


@dataclass
class Lake6RuntimeData:
    """Runtime objects stored on the config entry."""

    coordinator: Lake6Coordinator
    device_id: str
    device: Lake6Device


type Lake6ConfigEntry = ConfigEntry[Lake6RuntimeData]


class Lake6Coordinator(DataUpdateCoordinator[Lake6Data]):
    """Poll the Lake_6 endpoints on the schedule defined in §7."""

    config_entry: Lake6ConfigEntry

    device: Lake6Device

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: Lake6ConfigEntry,
        client: Lake6ApiClient,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name="APsystems Lake_6",
            update_interval=timedelta(seconds=LAKE6_UPDATE_INTERVAL),
            # Lake6Data 字段全是 frozen dataclass，__eq__ 可靠；
            # 数据没变时不触发 async_update_listeners，实体 state 不重写、recorder 不写库
            always_update=False,
        )
        self.client = client
        self._modes: Lake6Modes | None = None
        self._modes_updated_at: float | None = None
        self._modes_dirty = False
        self._control_panel: Lake6ControlPanel | None = None
        self._control_panel_updated_at: float | None = None
        self.manual_control = Lake6ManualControl()

    @override
    async def _async_setup(self) -> None:
        """Fetch the static device identity once."""
        # /devices 只在首次刷新请求，之后由 Lake6RuntimeData 持有
        try:
            self.device = await self.client.async_get_device()
        except Lake6ApiError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="lake6_api_error"
            ) from err

    @override
    async def _async_update_data(self) -> Lake6Data:
        """Fetch every polled endpoint for one refresh cycle."""
        # /energies 与 /alarms 同频、串行请求；任一失败本轮整体失败（§2.4）
        try:
            energies = await self.client.async_get_energies()
            alarms = await self.client.async_get_alarms()
            modes = await self._async_poll_modes()
            control_panel = await self._async_poll_control_panel()
        except Lake6ApiError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="lake6_api_error"
            ) from err
        return Lake6Data(
            energies=energies,
            alarms=alarms,
            modes=modes,
            control_panel=control_panel,
        )

    async def async_set_modes(self, **changes: Any) -> None:
        """Write /modes and re-read only that endpoint."""
        await self.client.async_set_modes(**changes)
        # 只回读 /modes：走全量 async_refresh() 会连 /energies 与 /alarms 一起拉，
        # 连点几下就是一个 POST 加三个 GET，设备直接被刷到超时
        self._modes = await self.client.async_get_modes()
        self._modes_updated_at = monotonic()
        self._modes_dirty = False
        self.async_set_updated_data(
            Lake6Data(
                energies=self.data.energies,
                alarms=self.data.alarms,
                modes=self._modes,
                control_panel=self.data.control_panel,
            )
        )

    async def async_set_manual_control(
        self,
        *,
        mode: str | None = None,
        power: int | None = None,
        duration: int | None = None,
    ) -> None:
        """Stage the changed fields without touching the device.

        The three entities can be filled in any order and any number of times;
        nothing is sent until `async_apply_manual_control` runs, so a half-typed
        request can never restart the window by accident.
        """
        control = self.manual_control
        if mode is not None:
            control.mode = mode
        if power is not None:
            control.power = power
        if duration is not None:
            control.duration = duration
        control.last_error = None
        self.async_update_listeners()

    async def async_apply_manual_control(self) -> None:
        """Send the staged request (§4.7), started by the button.

        Raises:
            ServiceValidationError: the staged request is incomplete, or the
                device answered the POST without entering the one-time run.
        """
        control = self.manual_control
        signed_power = control.signed_power
        missing = [
            name
            for name, value in (
                ("mode", control.mode),
                ("power", signed_power),
                ("duration", control.duration),
            )
            if value is None
        ]
        if missing or signed_power is None or control.duration is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="manual_control_incomplete",
                translation_placeholders={"fields": ", ".join(missing)},
            )
        try:
            await self._async_send_manual_control(
                power=signed_power, duration=control.duration
            )
        except Lake6ApiError as err:
            control.last_error = str(err)
            raise

    async def _async_send_manual_control(self, *, power: int, duration: int) -> None:
        """Post a window that already started and verify the device took it.

        A well-formed request is dropped in silence in two cases: the timestamp
        width is not the one the firmware echoes, or the start is not behind the
        device's own clock. The window therefore begins
        `LAKE6_CONTROL_PANEL_START_BACKDATES` seconds ago while still ending
        `duration` minutes from now, so the run keeps its full length.
        """
        # 设备按 UTC 解释 MI1.time，写本地时间的窗口会被 200 静默丢弃
        now = dt_util.now(UTC)
        end = now + timedelta(minutes=duration)
        panel = Lake6ControlPanel(active=False, windows=[])
        for backdate in LAKE6_CONTROL_PANEL_START_BACKDATES:
            start = now - timedelta(seconds=backdate)
            for time_format in self._control_panel_time_formats():
                await self.client.async_set_control_panel(
                    {
                        "mode": LAKE6_CONTROL_PANEL_MODE_ACTIVE,
                        "MI1": {
                            "time": [
                                f"{start.strftime(time_format)}"
                                f"{end.strftime(time_format)}"
                            ],
                            "power": [str(power)],
                        },
                    }
                )
                # POST 返回成功只代表报文格式合法；必须回读确认设备真进入了单次执行（C11）
                await asyncio.sleep(LAKE6_CONTROL_PANEL_SETTLE)
                panel = await self.client.async_get_control_panel()
                if panel.active:
                    break
                _LOGGER.debug(
                    "Lake_6 ignored %s with a start %s s back, trying the next one",
                    time_format,
                    backdate,
                )
            if panel.active:
                break
        self._control_panel = panel
        self._control_panel_updated_at = monotonic()
        if panel.active:
            self.manual_control.mark_sent()
        self.manual_control.last_sent_at = now
        self.manual_control.last_error = None if panel.active else "device_not_running"
        self.async_set_updated_data(
            Lake6Data(
                energies=self.data.energies,
                alarms=self.data.alarms,
                modes=self.data.modes,
                control_panel=panel,
            )
        )
        if not panel.active:
            _LOGGER.warning(
                "Lake_6 did not take the manual control request: %s W for %s min",
                power,
                duration,
            )
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="manual_control_not_applied",
            )

    async def async_interrupt_manual_control(self) -> None:
        """Clear the one-time run so the long-term mode takes over again.

        `mode="0"` takes an empty `MI1` (§4.7). The device answers a
        well-formed POST even when nothing changes, so the read-back decides
        whether the window really stopped.

        Raises:
            ServiceValidationError: the device still reports a running window.
        """
        await self.client.async_set_control_panel(
            {"mode": LAKE6_CONTROL_PANEL_MODE_IDLE, "MI1": {}}
        )
        await asyncio.sleep(LAKE6_CONTROL_PANEL_SETTLE)
        panel = await self.client.async_get_control_panel()
        self._control_panel = panel
        self._control_panel_updated_at = monotonic()
        if not panel.active:
            # 中断等于撤回这次请求，待下发的三个字段一并清空，
            # 免得旧值留在框里被下一次下发带走
            self.manual_control.reset()
        self.manual_control.last_error = (
            None if not panel.active else "device_still_running"
        )
        self.async_set_updated_data(
            Lake6Data(
                energies=self.data.energies,
                alarms=self.data.alarms,
                modes=self.data.modes,
                control_panel=panel,
            )
        )
        if panel.active:
            _LOGGER.warning("Lake_6 kept the manual control window after a stop")
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="manual_control_still_running",
            )

    def _control_panel_time_formats(self) -> list[str]:
        """Order the timestamp layouts by the one the device last echoed."""
        formats = list(LAKE6_CONTROL_PANEL_TIME_FORMATS)
        width = self._control_panel.timestamp_width if self._control_panel else None
        if width is not None and len(formats) > 1:
            # 按实际长度排序，不依赖常量表里的先后
            formats.sort(
                key=lambda fmt: len(datetime(2000, 1, 1).strftime(fmt)) != width
            )
        return formats

    async def _async_poll_control_panel(self) -> Lake6ControlPanel:
        """Return the one-time run snapshot, throttled like `/modes`.
    
        The throttle is lifted while a window runs so the interrupt button
        greys out as soon as the device drops it; that same read is where a
        window ending on its own is noticed, and a finished run clears the
        staged request like an interrupt does.
        """
        now = monotonic()
        if (
            self._control_panel is not None
            and self._control_panel_updated_at is not None
            # 单次任务期间不节流：窗口只有几分钟，跑完要尽快让中断按钮变灰
            and not self._control_panel.active
            and now - self._control_panel_updated_at
            < LAKE6_CONTROL_PANEL_UPDATE_INTERVAL
        ):
            return self._control_panel
        was_active = self._control_panel.active if self._control_panel else False
        panel = await self.client.async_get_control_panel()
        self._control_panel = panel
        self._control_panel_updated_at = now
        if was_active and not panel.active:
            self.manual_control.finish_run()
        return panel

    async def _async_poll_modes(self) -> Lake6Modes:
        """Return the mode snapshot, honouring the 5-minute throttle."""
        now = monotonic()
        if (
            not self._modes_dirty
            and self._modes is not None
            and self._modes_updated_at is not None
            and now - self._modes_updated_at < LAKE6_MODES_UPDATE_INTERVAL
        ):
            return self._modes

        # 失败时不更新时间戳也不清脏标记，下一轮自动重试
        modes = await self.client.async_get_modes()
        self._modes = modes
        self._modes_updated_at = now
        self._modes_dirty = False
        return modes
