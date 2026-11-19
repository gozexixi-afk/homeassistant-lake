"""Lake_6 local API: parsed data objects and the HTTP transport.

数据类（Lake6Device / Lake6Energies / Lake6Alarms / Lake6Modes）是 client 层的
出口类型，位于 client 与 coordinator 之间：
- 字段名与 lake6/const.py 中映射表的「属性名」列严格一致，
  同时也是对应实体的 key，便于实体层直接 `lambda d: d.xxx`
- 所有数值在 client 层内完成字符串到 float/int/bool 的转换，
  单字段解析失败时为 None，不影响同一条响应中的其它字段
- 一律 frozen + kw_only：快照不可变，且同类型字段（如 14 个 bool）
  必须写名字，防止位置错位

Lake6ApiClient 负责 HTTP 传输与业务返回码校验，parse_* 负责把 `data` 对象
转成上面的数据类；两层都只依赖 const.py，不感知 HA 实体。
"""

import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from typing import Any, Final, Literal

import aiohttp

from .const import (
    LAKE6_BATTERY_STATUS_TO_STATE,
    LAKE6_CODE_DESCRIPTIONS,
    LAKE6_CODE_SUCCESS,
    LAKE6_CONTROL_PANEL_MODE_ACTIVE,
    LAKE6_CONTROL_PANEL_TIME_FORMATS,
    LAKE6_DEFAULT_PORT,
    LAKE6_ENDPOINT_ALARMS,
    LAKE6_ENDPOINT_CONTROL_PANELS,
    LAKE6_ENDPOINT_DEVICES,
    LAKE6_ENDPOINT_ENERGIES,
    LAKE6_ENDPOINT_MODES,
    LAKE6_MESSAGE_SUCCESS,
    LAKE6_OPERATING_MODE_TO_STATE,
    LAKE6_REQUEST_TIMEOUT,
    LAKE6_TOU_FUNCTION_TO_STATE,
)

_LOGGER = logging.getLogger(__name__)

# /modes 的 time_cfg 原始嵌套数组，保留以便回写与排障；解析视图见 Lake6TouRule
type Lake6TimeCfg = list[dict[str, Any]]

# 每个格式串对应的单侧时间戳长度（12 位到分钟、14 位到秒）
_TIMESTAMP_WIDTHS: Final[tuple[tuple[str, int], ...]] = tuple(
    (fmt, len(datetime(2000, 1, 1, 0, 0, 0).strftime(fmt)))
    for fmt in LAKE6_CONTROL_PANEL_TIME_FORMATS
)


@dataclass(frozen=True, kw_only=True)
class Lake6TouRule:
    """A decoded `time_cfg` entry, i.e. one row in the product UI.

    The product keeps exactly one `TM` entry per row, so the slot is flattened
    onto the rule. Any extra `TM` entries the firmware might start sending are
    still preserved verbatim in `Lake6Modes.time_cfg`, which is what write-back
    starts from.
    """

    enabled: bool
    weekdays: list[int]
    # 原始 T 的前四位 / 后四位，已解码为 HH:MM；不可解析时为 None
    start: str | None
    end: str | None
    function: str | None
    power: int | None


type Lake6TouRules = list[Lake6TouRule]


@dataclass(frozen=True, kw_only=True)
class Lake6Device:
    """Parsed `GET /devices` response, fetched once during first refresh.

    Only the fields consumed by HA are kept.
    `bat_manuf` / `bat_model` are returned by the device but not defined in the
    OpenAPI contract, so they are intentionally not consumed (baseline C8).
    """

    dev_id: str
    # 原始字段 type；改名以避免与内置 type 冲突
    device_type: str
    # 原始字段 dev_ver 已解析：空字符串 -> None（坑点 P1）
    sw_version: str | None
    # 原始字段 bat_cap，单位 kWh（待确认 C3）
    battery_capacity: float | None
    # 原始字段 rssi，dBm；实测为 number，非 string（坑点 P6）
    rssi: int | None


@dataclass(frozen=True, kw_only=True)
class Lake6Energies:
    """Parsed `GET /energies` response.

    Field names equal the entity keys in `LAKE6_ENERGY_FIELD_TO_ATTR`.
    """

    # bat_soc，单位 %
    battery_soc: float | None
    # bat_temp，单位 °C
    battery_temperature: float | None
    # dev_temp，单位 °C；注意与 /alarms 的同名字段含义不同（坑点 P2）
    device_temperature: float | None

    # bat_impE，电池累计充电量，kWh
    battery_charge_energy: float | None
    # bat_expE，电池累计放电量，kWh
    battery_discharge_energy: float | None
    # ongrid_expE，并网侧累计输出电量，kWh
    grid_export_energy: float | None
    # ongrid_impE，并网侧累计输入电量，kWh
    grid_import_energy: float | None
    # offgrid_expE，离网侧累计输出电量，kWh
    offgrid_export_energy: float | None
    # offgrid_impE，离网侧累计输入电量，kWh
    offgrid_import_energy: float | None

    # bat_power，单位 W；符号方向未定义，待实测（C4）
    # 设备按字段分区格式化：功率输出纯整数（如 "486"），故用 int（D6）
    battery_power: int | None
    # ongrid_power，单位 W
    grid_power: int | None
    # offgrid_power，单位 W
    offgrid_power: int | None

    # bat_status，已按 LAKE6_BATTERY_STATUS_TO_STATE 转为语义串
    battery_status: str | None


@dataclass(frozen=True, kw_only=True)
class Lake6Alarms:
    """Parsed `GET /alarms` response.

    Field names equal the entity keys in `LAKE6_ALARM_FIELD_TO_ATTR`.
    Each raw value is "0" (normal) or "1" (fault), converted to bool.

    注意 device_temperature_protection 对应的原始字段也是 dev_temp，
    但它与 Lake6Energies.device_temperature（温度数值）是两个不同的东西。
    """

    battery_over_temperature: bool | None  # bat_overtemp
    battery_under_temperature: bool | None  # bat_undertemp
    battery_communication_error: bool | None  # bat_comm_err
    battery_over_voltage: bool | None  # bat_overvolt
    battery_under_voltage: bool | None  # bat_undervolt
    battery_over_current: bool | None  # bat_overcur
    battery_internal_error: bool | None  # bat_ie
    device_temperature_protection: bool | None  # dev_temp（告警位，非温度值）
    device_system_error: bool | None  # dev_sys_err
    battery_shutdown: bool | None  # bat_shutdown
    grid_anomaly: bool | None  # grid_anomaly
    offgrid_over_current: bool | None  # offgrid_overcur
    offgrid_short_circuit: bool | None  # offgrid_shortcir
    battery_calibration: bool | None  # bat_cal


@dataclass(frozen=True, kw_only=True)
class Lake6Modes:
    """Parsed `GET /modes` response.

    Field names equal the entity keys in `LAKE6_MODE_FIELD_TO_ATTR`.
    范围由实体 min/max 约束，client 层只做类型转换，
    写回成败交由设备返回的 code 决定。
    """

    # mode，已按 LAKE6_OPERATING_MODE_TO_STATE 转为语义串
    operating_mode: str | None
    # eco，0/1 转 bool
    eco: bool | None
    # offgrid_on，0/1 转 bool
    offgrid_on: bool | None

    # dod，单位 %；产品语义为 backupSoc（备电放电 SOC 下限），数值越大越保守
    depth_of_discharge: int | None

    # 原值保留，供回写与排障；结构化视图见 tou_rules
    time_cfg: Lake6TimeCfg

    # 结构化视图，供 sensor 展示；与 time_cfg 同源
    tou_rules: Lake6TouRules


@dataclass(frozen=True, kw_only=True)
class Lake6ControlPanelWindow:
    """One decoded `MI1` pair: a wall-clock slot with its signed power.

    `power` keeps the raw sign: positive discharges, negative charges and zero
    means standby (§4.7). The device reports local wall-clock time, so the two
    timestamps are naive datetimes on purpose.
    """

    start: datetime
    end: datetime
    power: int


type Lake6ControlPanelWindows = list[Lake6ControlPanelWindow]


@dataclass(frozen=True, kw_only=True)
class Lake6ControlPanel:
    """Parsed `GET /control-panels` response.

    `mode` is the run state, not a setting: `"1"` only exists while a one-time
    run is in progress, after which the device clears `MI1` and restores the
    long-term mode.
    """

    active: bool
    windows: Lake6ControlPanelWindows
    # 回显 `MI1.time` 的单侧宽度（24 位写法为 12，28 位为 14）。
    # 下发时必须按它选格式，否则设备静默忽略；idle 时 MI1 为空，这里为 None
    timestamp_width: int | None = None


def _to_float(value: object) -> float | None:
    """Convert a raw JSON value to float, or None when not convertible.

    The parameter is typed as object on purpose: the device does not stick to
    the documented string format (`rssi` is a JSON number, see P6). Accepting
    only str would raise AttributeError and break the whole setup call.

    NaN and infinity are rejected: HA rejects non-finite sensor values.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, str):
        try:
            result = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return result if math.isfinite(result) else None


def _to_int(value: object) -> int | None:
    """Convert a raw JSON value to int, or None when not convertible.

    String input goes through float first so that "20.0" is accepted.
    Fractional values are truncated, matching how the device rounds dod.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if math.isfinite(value) else None
    if isinstance(value, str):
        try:
            parsed = float(value.strip())
        except ValueError:
            return None
        return int(parsed) if math.isfinite(parsed) else None
    return None


def _to_bool(value: object) -> bool | None:
    """Convert 0/1 (int or str) to bool, or None for anything else.

    The raw alarm fields are documented as "0"/"1" strings, but ints are
    accepted too since the device is not consistent about quoting.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value == 0:
            return False
        if value == 1:
            return True
        return None
    if isinstance(value, str):
        normalized = value.strip()
        if normalized == "0":
            return False
        if normalized == "1":
            return True
    return None


def _to_enum_state(value: object, mapping: Mapping[str, str]) -> str | None:
    """Map a raw numeric code to its semantic state string.

    Unknown codes yield None rather than raising: a firmware adding a new
    mode must not break the entities that still work.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        key = str(value)
    elif isinstance(value, str):
        key = value.strip()
    else:
        return None
    return mapping.get(key)


def _parse_sw_version(value: object) -> str | None:
    """Normalize the firmware version, mapping empty values to None (P1)."""
    if not isinstance(value, str):
        return None
    version = value.strip()
    return version or None


def _to_time_cfg(value: object) -> Lake6TimeCfg:
    """Return the raw time_cfg entries, dropping anything that is not an object."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _to_hhmm(fragment: str) -> str | None:
    """Decode a 4-digit `HHMM` fragment into `HH:MM`."""
    if len(fragment) != 4 or not fragment.isdigit():
        return None
    hours, minutes = int(fragment[:2]), int(fragment[2:])
    if hours > 23 or minutes > 59:
        return None
    return f"{hours:02d}:{minutes:02d}"


def _parse_tou_rule(item: object) -> Lake6TouRule | None:
    """Decode one `time_cfg` entry.

    `E` defaults to enabled when absent, and the firmware keeps `TM` populated
    for disabled rules, so disabled rows are parsed as usual.
    """
    if not isinstance(item, dict):
        return None
    raw_weekdays = item.get("W")
    weekdays = (
        sorted({day for day in raw_weekdays if isinstance(day, int) and 1 <= day <= 7})
        if isinstance(raw_weekdays, list)
        else []
    )
    raw_slots = item.get("TM")
    slot = raw_slots[0] if isinstance(raw_slots, list) and raw_slots else None
    start = end = None
    function = None
    power = None
    if isinstance(slot, dict):
        raw_time = slot.get("T")
        if isinstance(raw_time, str) and len(raw_time) == 8 and raw_time.isdigit():
            start = _to_hhmm(raw_time[:4])
            end = _to_hhmm(raw_time[4:])
        function = LAKE6_TOU_FUNCTION_TO_STATE.get(str(slot.get("F")))
        params = slot.get("FI")
        power = _to_int(params.get("P")) if isinstance(params, Mapping) else None
    return Lake6TouRule(
        enabled=str(item.get("E", "1")) != "0",
        weekdays=weekdays,
        start=start,
        end=end,
        function=function,
        power=power,
    )


def _to_tou_rules(value: object) -> Lake6TouRules:
    """Return the decoded schedule, dropping entries that are not objects."""
    if not isinstance(value, list):
        return []
    return [rule for rule in map(_parse_tou_rule, value) if rule is not None]


def parse_device(raw: Mapping[str, Any]) -> Lake6Device:
    """Parse a `GET /devices` payload.

    Raises:
        ValueError: When `dev_id` is missing or blank. It feeds the unique id
            and the registry serial number, so a device without it cannot be
            represented.
    """
    dev_id = raw.get("dev_id")
    if not isinstance(dev_id, str) or not dev_id.strip():
        raise ValueError("GET /devices response has no usable dev_id")

    device_type = raw.get("type")
    return Lake6Device(
        dev_id=dev_id.strip(),
        device_type=device_type.strip() if isinstance(device_type, str) else "",
        sw_version=_parse_sw_version(raw.get("dev_ver")),
        battery_capacity=_to_float(raw.get("bat_cap")),
        rssi=_to_int(raw.get("rssi")),
    )


def parse_energies(raw: Mapping[str, Any]) -> Lake6Energies:
    """Parse a `GET /energies` payload.

    The three power fields go through `_to_int` because the device formats them
    as plain integers ("486"), unlike the one-decimal SOC ("30.0") and the
    four-to-five decimal energies ("57.28800"), see D6.
    """
    return Lake6Energies(
        battery_soc=_to_float(raw.get("bat_soc")),
        battery_temperature=_to_float(raw.get("bat_temp")),
        device_temperature=_to_float(raw.get("dev_temp")),
        battery_charge_energy=_to_float(raw.get("bat_impE")),
        battery_discharge_energy=_to_float(raw.get("bat_expE")),
        grid_export_energy=_to_float(raw.get("ongrid_expE")),
        grid_import_energy=_to_float(raw.get("ongrid_impE")),
        offgrid_export_energy=_to_float(raw.get("offgrid_expE")),
        offgrid_import_energy=_to_float(raw.get("offgrid_impE")),
        battery_power=_to_int(raw.get("bat_power")),
        grid_power=_to_int(raw.get("ongrid_power")),
        offgrid_power=_to_int(raw.get("offgrid_power")),
        battery_status=_to_enum_state(
            raw.get("bat_status"), LAKE6_BATTERY_STATUS_TO_STATE
        ),
    )


def parse_alarms(raw: Mapping[str, Any]) -> Lake6Alarms:
    """Parse a `GET /alarms` payload.

    Every field is a "0"/"1" string; "1" means the fault is active.
    """
    return Lake6Alarms(
        battery_over_temperature=_to_bool(raw.get("bat_overtemp")),
        battery_under_temperature=_to_bool(raw.get("bat_undertemp")),
        battery_communication_error=_to_bool(raw.get("bat_comm_err")),
        battery_over_voltage=_to_bool(raw.get("bat_overvolt")),
        battery_under_voltage=_to_bool(raw.get("bat_undervolt")),
        battery_over_current=_to_bool(raw.get("bat_overcur")),
        battery_internal_error=_to_bool(raw.get("bat_ie")),
        device_temperature_protection=_to_bool(raw.get("dev_temp")),
        device_system_error=_to_bool(raw.get("dev_sys_err")),
        battery_shutdown=_to_bool(raw.get("bat_shutdown")),
        grid_anomaly=_to_bool(raw.get("grid_anomaly")),
        offgrid_over_current=_to_bool(raw.get("offgrid_overcur")),
        offgrid_short_circuit=_to_bool(raw.get("offgrid_shortcir")),
        battery_calibration=_to_bool(raw.get("bat_cal")),
    )


def parse_modes(raw: Mapping[str, Any]) -> Lake6Modes:
    """Parse a `GET /modes` payload.

    `backup_charP` was dropped in API V1.5.2. Older firmware still returns it,
    but it is ignored on purpose: no field, no entity, no round-trip (C9-b).
    """
    return Lake6Modes(
        operating_mode=_to_enum_state(
            raw.get("mode"), LAKE6_OPERATING_MODE_TO_STATE
        ),
        eco=_to_bool(raw.get("eco")),
        offgrid_on=_to_bool(raw.get("offgrid_on")),
        depth_of_discharge=_to_int(raw.get("dod")),
        time_cfg=_to_time_cfg(raw.get("time_cfg")),
        tou_rules=_to_tou_rules(raw.get("time_cfg")),
    )


def _parse_control_panel_span(
    value: object,
) -> tuple[datetime, datetime, int] | None:
    """Decode one `YYYYMMDDHHMM(SS)`x2 `MI1.time` entry.

    The manual documents 24 characters (up to the minute) while the device
    echoes 28 (with seconds), so both widths are accepted. Anything else is
    dropped rather than raising: one malformed row must not hide the others.

    Returns:
        The window plus the width of one timestamp, so the caller can mirror
        the device's own format on the next write.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    for fmt, width in _TIMESTAMP_WIDTHS:
        if len(text) != width * 2:
            continue
        try:
            return (
                datetime.strptime(text[:width], fmt),
                datetime.strptime(text[width:], fmt),
                width,
            )
        except ValueError:
            continue
    return None


def parse_control_panel(raw: Mapping[str, Any]) -> Lake6ControlPanel:
    """Parse a `GET /control-panels` payload.

    `MI1.time` and `MI1.power` are parallel arrays paired by index, so an entry
    is only kept when both halves are usable; a power without its slot (or the
    reverse) would silently shift every following pair onto the wrong window.

    `time` is still read when `mode` is "0": the device keeps the previous
    `MI1` after a stop, and its width is the only hint for which timestamp
    layout a request has to use. Those leftovers are not reported as windows,
    since nothing will execute them.
    """
    active = str(raw.get("mode", "")).strip() == LAKE6_CONTROL_PANEL_MODE_ACTIVE
    windows: list[Lake6ControlPanelWindow] = []
    widths: set[int] = set()
    params = raw.get("MI1")
    if isinstance(params, Mapping):
        raw_times = params.get("time")
        raw_powers = params.get("power")
        if isinstance(raw_times, list) and isinstance(raw_powers, list):
            for raw_time, raw_power in zip(raw_times, raw_powers, strict=False):
                span = _parse_control_panel_span(raw_time)
                power = _to_int(raw_power)
                if span is None or power is None:
                    continue
                widths.add(span[2])
                if active:
                    windows.append(
                        Lake6ControlPanelWindow(
                            start=span[0], end=span[1], power=power
                        )
                    )
    return Lake6ControlPanel(
        active=active,
        windows=windows,
        # 同一台设备不会混用两种宽度；混用说明回显异常，宁可不猜
        timestamp_width=next(iter(widths)) if len(widths) == 1 else None,
    )


class Lake6ApiError(Exception):
    """Raised when a Lake_6 request fails or the device reports an error code.

    `code` is the business code taken from the response body, or None when the
    failure happened below the API layer (network, HTTP status, malformed JSON).
    """

    def __init__(self, message: str, code: int | None = None) -> None:
        """Initialize the error."""
        self.code = code
        self.message = message
        super().__init__(f"code {code}: {message}" if code is not None else message)


class Lake6ApiClient:
    """HTTP client for the Lake_6 local API.

    Every endpoint answers with `{"data": {...}, "code": 200, ...}`, so success
    is decided by the business code rather than by the HTTP status alone (§9).
    """

    def __init__(
        self,
        host: str,
        session: aiohttp.ClientSession,
        port: int = LAKE6_DEFAULT_PORT,
        timeout: int = LAKE6_REQUEST_TIMEOUT,
    ) -> None:
        """Initialize the client."""
        self._base_url = f"http://{host}:{port}"
        self._session = session
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def async_get(
        self, endpoint: str, *, code_optional: bool = False
    ) -> dict[str, Any]:
        """Fetch one endpoint and return its `data` object."""
        body = await self._async_request("GET", endpoint, code_optional=code_optional)
        data = body.get("data")
        if not isinstance(data, dict):
            raise Lake6ApiError(f"GET {endpoint} returned no data object")
        return data

    async def async_get_device(self) -> Lake6Device:
        """Return the static device identity (§5.1)."""
        data = await self.async_get(LAKE6_ENDPOINT_DEVICES)
        try:
            return parse_device(data)
        except ValueError as err:
            raise Lake6ApiError(str(err)) from err

    async def async_get_energies(self) -> Lake6Energies:
        """Return the live energy and power snapshot (§5.2)."""
        data = await self.async_get(LAKE6_ENDPOINT_ENERGIES)
        return parse_energies(data)

    async def async_get_alarms(self) -> Lake6Alarms:
        """Return the alarm bitfield snapshot (§5.3)."""
        data = await self.async_get(LAKE6_ENDPOINT_ALARMS)
        return parse_alarms(data)

    async def async_get_modes(self) -> Lake6Modes:
        """Return the current mode configuration (§5.4)."""
        data = await self.async_get(LAKE6_ENDPOINT_MODES)
        return parse_modes(data)

    async def async_get_control_panel(self) -> Lake6ControlPanel:
        """Return the one-time manual control state (§4.6).

        This endpoint's envelope may omit `code`, so the business check falls
        back to `message` here only.
        """
        data = await self.async_get(
            LAKE6_ENDPOINT_CONTROL_PANELS, code_optional=True
        )
        return parse_control_panel(data)

    async def async_set_modes(self, **changes: Any) -> None:
        """Write the changed mode fields only (§8.1).

        Every scalar field is a string; `time_cfg` is the single exception and
        carries the complete rule list, because the device replaces the whole
        array rather than merging it.
        """
        await self.async_post(LAKE6_ENDPOINT_MODES, changes)

    async def async_set_control_panel(self, payload: dict[str, Any]) -> None:
        """Send a one-time manual control request (§4.7).

        The payload always carries the complete `MI1` object: the device
        replaces the configuration rather than merging it, and `mode="1"`
        requires `MI1` while `mode="0"` takes an empty object.
        """
        await self.async_post(
            LAKE6_ENDPOINT_CONTROL_PANELS, payload, code_optional=True
        )

    async def async_post(
        self, endpoint: str, payload: dict[str, Any], *, code_optional: bool = False
    ) -> None:
        """Post a payload and return once the device accepts it.

        Callers send only the fields they change: the device keeps the current
        value of every omitted field (§8.1).
        """
        await self._async_request(
            "POST", endpoint, payload, code_optional=code_optional
        )

    async def _async_request(
        self,
        method: Literal["GET", "POST"],
        endpoint: str,
        payload: dict[str, Any] | None = None,
        *,
        code_optional: bool = False,
    ) -> dict[str, Any]:
        """Perform one request and validate the transport and business layers."""
        body: object = None
        try:
            async with self._session.request(
                method,
                f"{self._base_url}{endpoint}",
                json=payload,
                timeout=self._timeout,
            ) as response:
                if response.status != HTTPStatus.OK:
                    raise Lake6ApiError(
                        f"{method} {endpoint} returned HTTP {response.status}"
                    )
                try:
                    body = await response.json(content_type=None)
                except ValueError as err:
                    raise Lake6ApiError(
                        f"{method} {endpoint} returned invalid JSON"
                    ) from err
        except TimeoutError as err:
            raise Lake6ApiError(f"{method} {endpoint} timed out") from err
        except aiohttp.ClientError as err:
            raise Lake6ApiError(f"{method} {endpoint} failed: {err}") from err

        if not isinstance(body, dict):
            raise Lake6ApiError(f"{method} {endpoint} returned a non-object body")

        self._raise_for_code(endpoint, body, code_optional)
        _LOGGER.debug("%s %s succeeded", method, endpoint)
        return body

    @staticmethod
    def _raise_for_code(
        endpoint: str, body: dict[str, Any], code_optional: bool
    ) -> None:
        """Convert a non-success business code into Lake6ApiError (§9).

        `/control-panels` is the one endpoint whose envelope may omit `code`
        (the real GET response only carries `message`). There the message is
        the only signal left; every other endpoint keeps failing on a missing
        code so a broken body is never mistaken for success.
        """
        code = body.get("code")
        if code is None and code_optional:
            message = body.get("message")
            if message == LAKE6_MESSAGE_SUCCESS:
                return
            raise Lake6ApiError(f"{endpoint} reported {message!r}")
        if not isinstance(code, int):
            raise Lake6ApiError(f"{endpoint} response has no numeric code")
        if code == LAKE6_CODE_SUCCESS:
            return
        description = LAKE6_CODE_DESCRIPTIONS.get(code, "unknown code")
        raise Lake6ApiError(f"{endpoint}: {description}", code)
