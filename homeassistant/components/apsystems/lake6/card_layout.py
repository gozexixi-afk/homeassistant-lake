"""Content of the dashboard the Lake_6 integration ships with.

The layout is kept free of Home Assistant imports so the very same rows can be
rendered by tooling outside the app, e.g. when refreshing a panel that already
exists. An entity row is a `(unique_id_suffix, display name)` tuple.

The view is split into three columns, widest screen first: readings and the
time-of-use help on the left, the settings that get touched on the middle, the
totals and the alarms on the right.
"""

from typing import Any

DASHBOARD_TITLE = "Lake 控制"
DASHBOARD_ICON = "mdi:battery-sync-outline"
VIEW_TITLE = "控制"
VIEW_PATH = "control"

COMMON_TITLE = "常用数据"
TOU_HELP_TITLE = "分时计划格式"
MODE_TITLE = "工作模式"
CONFIG_TITLE = "可选配置"
MANUAL_TITLE = "即时手动控制"
STATS_TITLE = "统计数据"
ALARM_TITLE = "告警"
NO_ALARM_LABEL = "当前无告警"

# (后缀, 显示名) 常显；第三个元素写 "available" 表示该实体可用时才出现，
# 写成 ("后缀", "状态") 则表示另一个实体处于该状态时才出现
VISIBLE_WHEN_AVAILABLE = "available"
RowSpec = tuple[str, str] | tuple[str, str, str | tuple[str, str]]

# 首屏只看这几项：电量、充放电、状态、两侧功率
COMMON_ROWS: tuple[tuple[str, str], ...] = (
    ("_battery_soc", "电池电量"),
    ("_battery_power", "电池充放电功率"),
    ("_battery_status", "电池状态"),
    ("_grid_power", "电网功率"),
    ("_offgrid_power", "离网侧功率"),
)

MODE_ROWS: tuple[RowSpec, ...] = (
    ("_operating_mode", "工作模式"),
    # 分时规则只在分时控制下有意义（值见 const.LAKE6_MODE_STATE_TIME_OF_USE）
    ("_tou_plan", "分时计划", ("_operating_mode", "time_of_use")),
)

CONFIG_ROWS: tuple[tuple[str, str], ...] = (
    ("_depth_of_discharge", "备电SOC"),
    ("_eco_mode", "智能节电"),
)

MANUAL_ROWS: tuple[RowSpec, ...] = (
    ("_manual_control_mode", "即时控制"),
    # 功率只在充电/放电时可编辑，待机与中断清空后不可用（见 number.py），
    # 下发/中断按钮跟随设备运行状态（见 button.py）；
    # 面板只跟着可用性显隐，不再重复判定一次
    ("_manual_control_power", "即时控制功率", VISIBLE_WHEN_AVAILABLE),
    ("_manual_control_duration", "即时控制时长"),
    ("_manual_control_apply", "下发即时控制", VISIBLE_WHEN_AVAILABLE),
    ("_manual_control_interrupt", "中断即时控制", VISIBLE_WHEN_AVAILABLE),
)

# 累计量只在看账时用
STATS_ROWS: tuple[tuple[str, str], ...] = (
    ("_battery_charge_energy", "电池累计充电量"),
    ("_battery_discharge_energy", "电池累计放电量"),
    ("_grid_import_energy", "并网侧累计输入电量"),
    ("_grid_export_energy", "并网侧累计输出电量"),
    ("_offgrid_import_energy", "离网侧累计输入电量"),
    ("_offgrid_export_energy", "离网侧累计输出电量"),
)

# 顺序按排障习惯排：电池 → 电网/离网 → 设备
ALARM_ROWS: tuple[tuple[str, str], ...] = (
    ("_battery_under_temperature", "电池低温"),
    ("_battery_over_temperature", "电池高温"),
    ("_battery_over_voltage", "电池过压"),
    ("_battery_under_voltage", "电池欠压"),
    ("_battery_over_current", "电池过流"),
    ("_battery_communication_error", "电池通信异常"),
    ("_battery_internal_error", "电池内部故障"),
    ("_battery_shutdown", "电池关机"),
    ("_battery_calibration", "电池容量校准"),
    ("_grid_anomaly", "电网异常"),
    ("_offgrid_over_current", "离网侧过流"),
    ("_offgrid_short_circuit", "离网侧短路"),
    ("_device_temperature_protection", "设备温度保护"),
    ("_device_system_error", "设备系统故障"),
)

TOU_HELP_TEXT = """**格式：** `时间|功能|功率(W)|星期(1–7)|启用(1/0)`

`charge` 充电 · `discharge` 放电 · `self` 自用（功率填 `-`）

**例：** `09:00-09:10|discharge|200|1234567|1`

最多 6 条，用 `;` 分隔；仅「分时控制」模式生效。"""


def build_config(device_id: str, entity_ids: dict[str, str]) -> dict[str, Any] | None:
    """Return the dashboard configuration, or None while entities are missing.

    Alarm rows are shown only while the alarm is on; a single "no alarm" row
    takes their place when every bit is off, so the panel stays short.
    """
    common_rows = _rows(COMMON_ROWS, device_id, entity_ids)
    mode_rows = _rows(MODE_ROWS, device_id, entity_ids)
    config_rows = _rows(CONFIG_ROWS, device_id, entity_ids)
    manual_rows = _rows(MANUAL_ROWS, device_id, entity_ids)
    stats_rows = _rows(STATS_ROWS, device_id, entity_ids)
    alarm_rows = _alarm_rows(device_id, entity_ids)
    if None in (
        common_rows,
        mode_rows,
        config_rows,
        manual_rows,
        stats_rows,
        alarm_rows,
    ):
        return None

    cards: list[dict[str, Any]] = [
        _column(
            [
                _card(COMMON_TITLE, common_rows),
                {"type": "markdown", "title": TOU_HELP_TITLE, "content": TOU_HELP_TEXT},
            ]
        ),
        _column(
            [
                _card(MODE_TITLE, mode_rows),
                _card(CONFIG_TITLE, config_rows),
                _card(MANUAL_TITLE, manual_rows),
            ]
        ),
        _column(
            [
                _card(STATS_TITLE, stats_rows),
                _card(ALARM_TITLE, alarm_rows),
            ]
        ),
    ]
    return {
        "title": DASHBOARD_TITLE,
        "views": [
            {
                "title": VIEW_TITLE,
                "path": VIEW_PATH,
                "icon": DASHBOARD_ICON,
                "cards": cards,
            }
        ],
    }


def _column(cards: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "vertical-stack", "cards": cards}


def _card(title: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "entities",
        "title": title,
        "state_color": True,
        # 右上角的总开关对这几个实体没有意义，卡片只做单项操作
        "show_header_toggle": False,
        "entities": rows,
    }


def _section(label: str) -> dict[str, str]:
    return {"type": "section", "label": label}


def _rows(
    spec: tuple[RowSpec, ...], device_id: str, entity_ids: dict[str, str]
) -> list[dict[str, Any]] | None:
    rows: list[dict[str, Any]] = []
    for item in spec:
        suffix, name = item[0], item[1]
        visibility = item[2] if len(item) > 2 else None
        entity_id = entity_ids.get(f"{device_id}{suffix}")
        if entity_id is None:
            return None
        row = {"entity": entity_id, "name": name}
        if visibility is None:
            rows.append(row)
        elif visibility == VISIBLE_WHEN_AVAILABLE:
            rows.append(
                _conditional_row(
                    row,
                    {"condition": "state", "entity": entity_id, "state_not": "unavailable"},
                )
            )
        else:
            gate_suffix, gate_state = visibility
            gate_id = entity_ids.get(f"{device_id}{gate_suffix}")
            if gate_id is None:
                return None
            rows.append(
                _conditional_row(
                    row,
                    {"condition": "state", "entity": gate_id, "state": gate_state},
                )
            )
    return rows


def _conditional_row(
    row: dict[str, Any], condition: dict[str, Any]
) -> dict[str, Any]:
    return {"type": "conditional", "conditions": [condition], "row": row}


def _alarm_rows(
    device_id: str, entity_ids: dict[str, str]
) -> list[dict[str, Any]] | None:
    rows: list[dict[str, Any]] = []
    alarm_ids: list[str] = []
    for suffix, name in ALARM_ROWS:
        entity_id = entity_ids.get(f"{device_id}{suffix}")
        if entity_id is None:
            return None
        alarm_ids.append(entity_id)
        rows.append(
            {
                "type": "conditional",
                "conditions": [
                    {"condition": "state", "entity": entity_id, "state": "on"}
                ],
                "row": {"entity": entity_id, "name": name},
            }
        )
    rows.append(
        {
            "type": "conditional",
            "conditions": [
                {"condition": "state", "entity": entity_id, "state": "off"}
                for entity_id in alarm_ids
            ],
            "row": _section(NO_ALARM_LABEL),
        }
    )
    return rows
