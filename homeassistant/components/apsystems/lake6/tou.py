"""分时计划的文本承载：格式化、解析与整体写回。

整份 `time_cfg` 放进一个 text 实体，一行写完：

    09:00-09:10|discharge|200|1234567|1;10:00-10:10|self|-|1234567|1

两条硬约束决定了这个形状：
- HA 的 text 实体是单行 ``<input>``，换行符输入不进去，所以规则之间用 ``;``
- 实体 state 上限 255 字符，所以条数有硬上限（见 const.LAKE6_TOU_TEXT_MAX_RULES）

本模块只做纯函数的格式转换，不依赖 HA 实体；校验失败一律抛 ValueError，
由 text 平台翻译成 ServiceValidationError。
"""

import copy
from dataclasses import dataclass
from typing import Any

from .client import Lake6TouRule
from .const import (
    LAKE6_TOU_POWER_MAX,
    LAKE6_TOU_POWER_MIN,
    LAKE6_TOU_STATE_TO_TEXT_FUNCTION,
    LAKE6_TOU_TEXT_FIELD_SEPARATOR,
    LAKE6_TOU_TEXT_FUNCTION_SELF,
    LAKE6_TOU_TEXT_FUNCTION_TO_CODE,
    LAKE6_TOU_TEXT_MAX_RULES,
    LAKE6_TOU_TEXT_POWER_PLACEHOLDER,
    LAKE6_TOU_TEXT_RULE_SEPARATOR,
    LAKE6_TOU_TEXT_WEEKDAY_LIST_SEPARATOR,
    LAKE6_TOU_TEXT_WEEKDAY_RANGE_SEPARATOR,
)
from .coordinator import Lake6Coordinator

_FALSE_FLAGS = frozenset({"0", "off", "false", "no"})
_TRUE_FLAGS = frozenset({"1", "on", "true", "yes"})


@dataclass(frozen=True, kw_only=True)
class Lake6TouPlanRow:
    """Text 里的一行，对应设备上的一条规则。

    `function` 存的是文本缩写（`charge` / `discharge` / `self`），不是设备码：
    它同时是格式化时的输出，避免两套表示来回转换。
    """

    enabled: bool
    weekdays: list[int]
    start: str
    end: str
    function: str
    # self 不使用功率，此时为 None
    power: int | None
    # self 行里填了功率，已被忽略；由 text 平台拿去提示用户
    power_ignored: bool = False


def format_weekdays(weekdays: list[int]) -> str:
    """把星期列表压成紧凑写法：`12345` 表示周一至周五。"""
    return "".join(str(day) for day in sorted(set(weekdays)))


def parse_weekdays(value: str) -> list[int]:
    """解析星期字段，返回排序去重的列表。

    接受紧凑写法 ``12345``、区间 ``1-5`` 与列举 ``1,3,5``，三者可混用。

    Raises:
        ValueError: 片段不是 1~7 的单个数字，或区间端点顺序颠倒。
    """
    days: set[int] = set()
    for chunk in value.replace(" ", "").split(LAKE6_TOU_TEXT_WEEKDAY_LIST_SEPARATOR):
        if not chunk:
            continue
        head, separator, tail = chunk.partition(
            LAKE6_TOU_TEXT_WEEKDAY_RANGE_SEPARATOR
        )
        if separator:
            first = _weekday_number(head)
            last = _weekday_number(tail)
            if first > last:
                raise ValueError(f"weekday range out of order {chunk!r}")
            days.update(range(first, last + 1))
        else:
            days.update(_weekday_number(char) for char in chunk)
    return sorted(days)


def render_plan(rules: list[Lake6TouRule]) -> str | None:
    """把设备返回的规则表渲染成文本。

    只要有任意一条无法完整表达（缺时刻、功能码未知、功率越界）就返回 None：
    少显示一条的计划一旦被用户原样提交，就会把设备上那条静默删掉。
    """
    rows = [_format_rule(rule) for rule in rules]
    if any(row is None for row in rows):
        return None
    return LAKE6_TOU_TEXT_RULE_SEPARATOR.join(
        row for row in rows if row is not None
    )


def parse_plan(value: str) -> list[Lake6TouPlanRow]:
    """把文本解析成规则列表。

    Raises:
        ValueError: 格式不对、字段数不符，或条数超过文本上限。
    """
    chunks = [
        chunk.strip()
        for chunk in value.split(LAKE6_TOU_TEXT_RULE_SEPARATOR)
    ]
    chunks = [chunk for chunk in chunks if chunk]
    if not chunks:
        raise ValueError("plan is empty")
    if len(chunks) > LAKE6_TOU_TEXT_MAX_RULES:
        raise ValueError(f"at most {LAKE6_TOU_TEXT_MAX_RULES} rules")
    return [_parse_row(chunk) for chunk in chunks]


def build_payload(
    raw: list[dict[str, Any]],
    rows: list[Lake6TouPlanRow],
) -> list[dict[str, Any]]:
    """把解析出的规则合并进原始 `time_cfg`。

    逐条复用原始 dict，保住 `GC` / `GD` 等本集成不解析的键；条数增加时新建
    空 dict（新条目不带 `GC` / `GD`，符合决策 P5「只存不回传」）。
    设备整体替换 `time_cfg`，所以每次都发完整数组。
    """
    payload: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        entry = copy.deepcopy(raw[index]) if index < len(raw) else {}
        _apply_row(entry, row)
        payload.append(entry)
    return payload


async def async_write_tou_plan(
    coordinator: Lake6Coordinator,
    rows: list[Lake6TouPlanRow],
) -> None:
    """下发整份分时计划。"""
    payload = build_payload(coordinator.data.modes.time_cfg, rows)
    await coordinator.async_set_modes(time_cfg=payload)


def _weekday_number(text: str) -> int:
    """把单个星期字符转成 1~7 的整数。

    Raises:
        ValueError: 不是单个 1~7 的数字。
    """
    if len(text) != 1 or not text.isdigit():
        raise ValueError(f"invalid weekday {text!r}")
    day = int(text)
    if not 1 <= day <= 7:
        raise ValueError(f"invalid weekday {text!r}")
    return day


def _parse_hhmm(value: str) -> str:
    """校验并归一化一个 `HH:MM` 时刻。

    Raises:
        ValueError: 不是 `HH:MM`，或小时/分钟越界。
    """
    hours_text, separator, minutes_text = value.strip().partition(":")
    if not separator or not hours_text.isdigit() or not minutes_text.isdigit():
        raise ValueError(f"invalid time {value!r}")
    hours, minutes = int(hours_text), int(minutes_text)
    if hours > 23 or minutes > 59:
        raise ValueError(f"invalid time {value!r}")
    return f"{hours:02d}:{minutes:02d}"


def _parse_time_range(value: str) -> tuple[str, str]:
    """把 `HH:MM-HH:MM` 拆成起止时刻。

    协议不允许跨天，结束早于或等于开始都视为无效。

    Raises:
        ValueError: 缺少分隔符、时刻非法，或时段长度为零/为负。
    """
    start_text, separator, end_text = value.partition("-")
    if not separator:
        raise ValueError(f"invalid time range {value!r}")
    start = _parse_hhmm(start_text)
    end = _parse_hhmm(end_text)
    if start >= end:
        raise ValueError(f"invalid time range {value!r}")
    return start, end


def _parse_power(value: str, function: str) -> tuple[int | None, bool]:
    """解析功率字段，返回（功率, 是否丢弃了用户填的值）。

    self（自发自用）在设备上不带功率（F=3 时 `FI` 是空对象），所以这一行的
    功率填什么都只是误输，不能因此把整份计划判为非法：丢弃后照常下发，由
    返回值第二项让调用方决定要不要提示。

    Raises:
        ValueError: 非 self 行的功率不是整数，或越出 0~2500W。
    """
    if function == LAKE6_TOU_TEXT_FUNCTION_SELF:
        return None, value not in ("", LAKE6_TOU_TEXT_POWER_PLACEHOLDER)
    if not value.isdigit():
        raise ValueError(f"invalid power {value!r}")
    power = int(value)
    if not LAKE6_TOU_POWER_MIN <= power <= LAKE6_TOU_POWER_MAX:
        raise ValueError(f"invalid power {value!r}")
    return power, False


def _parse_enabled(value: str) -> bool:
    """解析启用标志，除 1/0 外兼容 on/off、true/false、yes/no。

    Raises:
        ValueError: 无法识别的布尔写法。
    """
    normalized = value.strip().lower()
    if normalized in _TRUE_FLAGS:
        return True
    if normalized in _FALSE_FLAGS:
        return False
    raise ValueError(f"invalid enabled flag {value!r}")


def _parse_row(chunk: str) -> Lake6TouPlanRow:
    """解析一行，即一条规则。

    Raises:
        ValueError: 字段数不是 5，或任一字段非法。
    """
    fields = [field.strip() for field in chunk.split(LAKE6_TOU_TEXT_FIELD_SEPARATOR)]
    if len(fields) != 5:
        raise ValueError(f"a rule needs 5 fields, got {len(fields)}: {chunk!r}")
    start, end = _parse_time_range(fields[0])
    function = fields[1].lower()
    if function not in LAKE6_TOU_TEXT_FUNCTION_TO_CODE:
        raise ValueError(f"unknown function {fields[1]!r}")
    power, power_ignored = _parse_power(fields[2], function)
    return Lake6TouPlanRow(
        enabled=_parse_enabled(fields[4]),
        weekdays=parse_weekdays(fields[3]),
        start=start,
        end=end,
        function=function,
        power=power,
        power_ignored=power_ignored,
    )


def _format_rule(rule: Lake6TouRule) -> str | None:
    """渲染一条规则，字段不全时返回 None。"""
    if rule.start is None or rule.end is None or rule.start >= rule.end:
        return None
    function = LAKE6_TOU_STATE_TO_TEXT_FUNCTION.get(rule.function or "")
    if function is None:
        return None
    if function == LAKE6_TOU_TEXT_FUNCTION_SELF:
        power = LAKE6_TOU_TEXT_POWER_PLACEHOLDER
    elif (
        rule.power is None
        or not LAKE6_TOU_POWER_MIN <= rule.power <= LAKE6_TOU_POWER_MAX
    ):
        return None
    else:
        power = str(rule.power)
    return LAKE6_TOU_TEXT_FIELD_SEPARATOR.join(
        (
            f"{rule.start}-{rule.end}",
            function,
            power,
            format_weekdays(rule.weekdays),
            "1" if rule.enabled else "0",
        )
    )


def _apply_row(entry: dict[str, Any], row: Lake6TouPlanRow) -> None:
    """就地把一条规则写进 `time_cfg` 的一个条目。"""
    entry["E"] = "1" if row.enabled else "0"
    entry["W"] = row.weekdays

    slot: dict[str, Any] = {}
    raw_slots = entry.get("TM")
    if isinstance(raw_slots, list) and raw_slots and isinstance(raw_slots[0], dict):
        # 复用原对象，保住 GC / GD 等本集成不解析的键
        slot = raw_slots[0]
    slot["T"] = f"{row.start.replace(':', '')}{row.end.replace(':', '')}"
    slot["F"] = LAKE6_TOU_TEXT_FUNCTION_TO_CODE[row.function]
    if row.function == LAKE6_TOU_TEXT_FUNCTION_SELF:
        # F=3 时设备不使用功率，实测下发的是空对象
        slot["FI"] = {}
    else:
        params = slot.get("FI")
        if not isinstance(params, dict):
            params = {}
        params["P"] = str(row.power)
        slot["FI"] = params
    # 每条规则恒为一段；原数据若意外带多段，以重写的这一段为准
    entry["TM"] = [slot]
