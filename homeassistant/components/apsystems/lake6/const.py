"""Constants for the APsystems Lake_6 local API client.

本文件是 Lake_6 的唯一常量来源，对应 docs/apsystems-lake6/ 下的开发基线：
- 端点与超时      → §4.3
- 业务返回码      → §9
- 枚举语义串      → §6
- number 取值范围 → §5.4、坑点 P8
- 字段名映射      → §5、坑点 P2

常量统一以 LAKE6_ 为前缀，避免与父包内 EZ1 的常量（DEFAULT_PORT 等）混淆。
约束：本文件只放常量，不得出现任何 IO 或运行时状态。
"""

from typing import Final

# --- 连接参数（§4.3）------------------------------------------------------
# Lake_6 默认端口 80，与 EZ1 的 8050 不同
LAKE6_DEFAULT_PORT: Final = 80

# 一次 HTTP 请求的超时。单次刷新可能串行请求多个端点，
# 最坏耗时约为「超时 x 请求数」；10 秒是"设备离线时尽快置为不可用"
# 与"不拖垮一次刷新"之间的折中，不宜再放大
LAKE6_REQUEST_TIMEOUT: Final = 10

# --- 端点（§4.3）----------------------------------------------------------
LAKE6_ENDPOINT_DEVICES: Final = "/devices"
LAKE6_ENDPOINT_ENERGIES: Final = "/energies"
LAKE6_ENDPOINT_ALARMS: Final = "/alarms"
LAKE6_ENDPOINT_MODES: Final = "/modes"
LAKE6_ENDPOINT_CONTROL_PANELS: Final = "/control-panels"

# --- 刷新策略（§7）--------------------------------------------------------
# /energies 与 /alarms 同频，一轮连续发 2 个请求。
# 12 秒是 EZ1（逆变器，功率秒级突变）的值；Lake 是储能、数值分钟级变化，
# 取 60 秒与 apsystems-storage 默认值一致，recorder 写入量降至 1/5
LAKE6_UPDATE_INTERVAL: Final = 60

# /modes 极少变化，在 _async_update_data 内按时间戳节流；
# 写操作后由脏标记强制拉取，避免界面滞回 5 分钟（§8.1）
LAKE6_MODES_UPDATE_INTERVAL: Final = 300

# /control-panels 同样极少变化（只在一次任务执行期间有值），与 /modes 同拍，
# 额外开销仅 12 次/小时
LAKE6_CONTROL_PANEL_UPDATE_INTERVAL: Final = 300

# --- 业务返回码（§9）------------------------------------------------------
# code 与 HTTP 状态码无关，成功判定只看 code == 200；
# 其余一律视为失败，原始 code 原样写入日志。故只需一个成功码常量。
LAKE6_CODE_SUCCESS: Final = 200

# /control-panels 的信封实测不带 code（GET 缺、POST 带），
# 缺 code 时只能回退到 message 判定；其余端点缺 code 仍按失败处理
LAKE6_MESSAGE_SUCCESS: Final = "SUCCESS"

# 仅用于日志，不参与实体状态（用户可见文案走 strings.json）
LAKE6_CODE_DESCRIPTIONS: Final[dict[int, str]] = {
    1001: "data length error",
    1002: "data format error",
    1003: "internal error",
    # 1004 未出现在 V1.5.2 文档的返回码表中，保留仅供早期固件的日志可读性
    1004: "internal error",
    2001: "internal communication error",
}

# --- 枚举语义串（§6）------------------------------------------------------
# 设备码 -> 实体 state。不直接把 "1"/"2" 暴露给实体，
# 以便固件调整枚举值时只需改这张表
LAKE6_BATTERY_STATUS_TO_STATE: Final[dict[str, str]] = {
    "1": "idle",
    "2": "charging",
    "3": "discharging",
    "4": "fault",
    "5": "shutdown",
    "6": "no_communication",
    "7": "heating",
}

LAKE6_OPERATING_MODE_TO_STATE: Final[dict[str, str]] = {
    "1": "ai",
    "2": "self_consumption",
    "3": "time_of_use",
    "4": "backup",
}

# 写回时需要反向映射（state -> 设备码）
LAKE6_OPERATING_MODE_FROM_STATE: Final[dict[str, str]] = {
    state: code for code, state in LAKE6_OPERATING_MODE_TO_STATE.items()
}

# 禁止下发的 mode（§8.2：AI 模式只能通过 App 开启）
LAKE6_MODE_STATE_AI: Final = "ai"

# time_cfg 仅在分时电价模式下生效（C10）；实体可用性也按此判定
LAKE6_MODE_STATE_TIME_OF_USE: Final = "time_of_use"

# time_cfg[].TM[].F -> 语义串。固件新增功能码时只得到 None，不中断整表解析
LAKE6_TOU_FUNCTION_TO_STATE: Final[dict[str, str]] = {
    "1": "charge",
    "2": "discharge",
    "3": "self_consumption",
}

# 写回用的反向映射；必须与上面的表成对维护
LAKE6_TOU_FUNCTION_FROM_STATE: Final[dict[str, str]] = {
    state: code for code, state in LAKE6_TOU_FUNCTION_TO_STATE.items()
}

# F="3" 表示自发自用，此时功率不适用
LAKE6_TOU_STATE_SELF_CONSUMPTION: Final = "self_consumption"

# 产品允许 1~24 条规则（W 是 1~7 的任意子集，每条 TM 恒为 1 段）。
# 整份计划由一个 text 实体承载，不按条数建实体；界面侧实际可编辑
# 的条数受 state 长度约束，见 LAKE6_TOU_TEXT_MAX_RULES。
LAKE6_TOU_MAX_RULES: Final = 24

# TM[].FI.P：charge / discharge 均为 0~2500W；F=3 时该值不适用
LAKE6_TOU_POWER_MIN: Final = 0
LAKE6_TOU_POWER_MAX: Final = 2500


# --- 分时计划的文本承载 ---------------------------------------------------
# 整份 time_cfg 压进一个 text 实体，一行写完：
#
#   09:00-09:10|discharge|200|1234567|1;10:00-10:10|self|-|1234567|1
#
# 字段顺序恒为 time | function | power | weekdays | enabled。
# HA 的 text 实体是单行 <input>，换行符贴不进去，所以规则之间用 ";" 而不是换行。
LAKE6_TOU_TEXT_MAX_LENGTH: Final = 255
LAKE6_TOU_TEXT_FIELD_SEPARATOR: Final = "|"
LAKE6_TOU_TEXT_RULE_SEPARATOR: Final = ";"

# 单条规则的最长写法 "00:00-23:59|discharge|2500|1234567|1" 共 36 字符；
# 加上分隔符后按 37 字符一条算，(255 + 1) // 37 = 6
LAKE6_TOU_TEXT_ROW_MAX_LENGTH: Final = 36
LAKE6_TOU_TEXT_MAX_RULES: Final = (LAKE6_TOU_TEXT_MAX_LENGTH + 1) // (
    LAKE6_TOU_TEXT_ROW_MAX_LENGTH + 1
)

# 文本里自发自用的缩写；255 字符的预算很紧，每条规则省下的字符
# 直接换成能多写几条
LAKE6_TOU_TEXT_FUNCTION_SELF: Final = "self"

# 文本里的功能缩写 -> 设备码
LAKE6_TOU_TEXT_FUNCTION_TO_CODE: Final[dict[str, str]] = {
    "charge": "1",
    "discharge": "2",
    "self": "3",
}

# 解码后的 state -> 文本里的缩写。缺键说明固件返回了未知功能码
LAKE6_TOU_STATE_TO_TEXT_FUNCTION: Final[dict[str, str]] = {
    "charge": "charge",
    "discharge": "discharge",
    "self_consumption": "self",
}

# 自发自用不使用功率，文本里用 "-" 占位以保持字段数固定
LAKE6_TOU_TEXT_POWER_PLACEHOLDER: Final = "-"

# weekdays 的紧凑写法："12345" 等价于 [1,2,3,4,5]。
# 解析同时接受 "1-5" 与 "1,3,5"，但回显一律用紧凑写法
LAKE6_TOU_TEXT_WEEKDAY_RANGE_SEPARATOR: Final = "-"
LAKE6_TOU_TEXT_WEEKDAY_LIST_SEPARATOR: Final = ","


# --- number 取值范围（§5.4，坑点 P8）--------------------------------------
# Lake 的 /devices 不返回 maxPower/minPower（与 EZ1 不同），无法由设备上报，
# 所以范围只能硬编码于此，禁止散落到实体实现中。
#
# dod（2026-11-12 定稿：上界 90，以官方文档 V1.5.2 的 15~90 为准）：
#   语义 = 产品所称的 backupSoc，即备电模式下电池允许放电到的 SOC 下限。
#   dod=15 放得最狠，dod=90 等于几乎不放电，数值越大越保守。
#   注意：与 "Depth of Discharge"（放电深度）的常见定义方向相反，
#   实体显示名应用 "Backup SOC"，不要用 "Depth of Discharge"。
#
# backup_charP（文档 V1.5.2 已删除该参数）：老固件仍返回，但按决策忽略 ——
#   不解析、不建实体、不回写（C9-b）。
LAKE6_DEPTH_OF_DISCHARGE_MIN: Final = 15
LAKE6_DEPTH_OF_DISCHARGE_MAX: Final = 90
LAKE6_DEPTH_OF_DISCHARGE_STEP: Final = 1


# --- 字段名映射（§5）------------------------------------------------------
# 原始 JSON 字段名 -> Lake6Energies 属性名（同时是实体 key）
LAKE6_ENERGY_FIELD_TO_ATTR: Final[dict[str, str]] = {
    "bat_soc": "battery_soc",
    "bat_temp": "battery_temperature",
    "dev_temp": "device_temperature",
    "bat_impE": "battery_charge_energy",
    "bat_expE": "battery_discharge_energy",
    "ongrid_expE": "grid_export_energy",
    "ongrid_impE": "grid_import_energy",
    "offgrid_expE": "offgrid_export_energy",
    "offgrid_impE": "offgrid_import_energy",
    "bat_power": "battery_power",
    "ongrid_power": "grid_power",
    "offgrid_power": "offgrid_power",
}

# 原始 JSON 字段名 -> Lake6Alarms 属性名（同时是实体 key）
# 注意 dev_temp：在 /energies 是温度数值，在 /alarms 是温度保护告警位，
# 必须改名为 device_temperature_protection，禁止与
# LAKE6_ENERGY_FIELD_TO_ATTR 混用（坑点 P2）
LAKE6_ALARM_FIELD_TO_ATTR: Final[dict[str, str]] = {
    "bat_overtemp": "battery_over_temperature",
    "bat_undertemp": "battery_under_temperature",
    "bat_comm_err": "battery_communication_error",
    "bat_overvolt": "battery_over_voltage",
    "bat_undervolt": "battery_under_voltage",
    "bat_overcur": "battery_over_current",
    "bat_ie": "battery_internal_error",
    "dev_temp": "device_temperature_protection",
    "dev_sys_err": "device_system_error",
    "bat_shutdown": "battery_shutdown",
    "grid_anomaly": "grid_anomaly",
    "offgrid_overcur": "offgrid_over_current",
    "offgrid_shortcir": "offgrid_short_circuit",
    "bat_cal": "battery_calibration",
}

# 原始 JSON 字段名 -> Lake6Modes 属性名（同时是实体 key）
LAKE6_MODE_FIELD_TO_ATTR: Final[dict[str, str]] = {
    "mode": "operating_mode",
    "eco": "eco",
    "offgrid_on": "offgrid_on",
    "dod": "depth_of_discharge",  # 语义实为 backupSoc（备电放电 SOC 下限），见 number 区块注释
}

# 写回时的反向映射（属性名 -> 原始 JSON 字段名），供 async_set_modes 使用
LAKE6_MODE_ATTR_TO_FIELD: Final[dict[str, str]] = {
    attr: field for field, attr in LAKE6_MODE_FIELD_TO_ATTR.items()
}

# switch 的实体 key 与 /modes 字段名不同名（eco_mode -> eco，
# offgrid_output_enabled -> offgrid_on），无法用上面的反向映射，单独登记
LAKE6_SWITCH_ENTITY_TO_FIELD: Final[dict[str, str]] = {
    "eco_mode": "eco",
    "offgrid_output_enabled": "offgrid_on",
}


# --- 即时手动控制（§4.6、§4.7 /control-panels）----------------------------
# control-panels.mode 是运行状态而非长期配置："1" 只在单次任务执行期间存在，
# 执行完设备自动清空 MI1 并恢复原 mode 1~4
LAKE6_CONTROL_PANEL_MODE_IDLE: Final = "0"
LAKE6_CONTROL_PANEL_MODE_ACTIVE: Final = "1"

# MI1.time 是「开始+结束」首尾相接的挂钟时间，设备按 UTC 解释：
# 本地时间（UTC+8）的窗口同样返回 code 200，但 mode 不变、MI1 被清空。
# 宽度只认 28 位，24 位（文档写法）表现一样；因此 28 位排首位，
# 24 位只留给可能存在的旧固件兜底（见 coordinator._control_panel_time_formats）
LAKE6_CONTROL_PANEL_TIME_FORMATS: Final = ("%Y%m%d%H%M%S", "%Y%m%d%H%M")

# POST 之后等一拍再回读：设备把 mode 置为 "1" 不是同步完成的，
# 立刻读会把自己刚写进去的任务当成没生效
LAKE6_CONTROL_PANEL_SETTLE: Final = 1

# 实测（2026-11-13）：起点只要不早于设备自己的 RTC，哪怕只晚 1 秒也返回 code 200
# 却把 mode 留在 "0"；把起点放到 2~10 秒之前则每次都被接受，窗口只有 60 秒也成立，
# 与功率大小无关。因此窗口从「现在 - 10 秒」起算、结束仍取「现在 + 时长」，
# 实际执行长度不缩水；更早的起点只在设备 RTC 明显超前时兜底
LAKE6_CONTROL_PANEL_START_BACKDATES: Final = (10, 60, 300)

# 三个 UI 选项 -> MI1.power 的符号。协议与常识相反：正=放电、负=充电、0=待机
LAKE6_MANUAL_MODE_TO_POWER_SIGN: Final[dict[str, int]] = {
    "charge": -1,
    "discharge": 1,
    "standby": 0,
}

# options 顺序即 dict 顺序：充电、放电、待机
LAKE6_MANUAL_MODES: Final = tuple(LAKE6_MANUAL_MODE_TO_POWER_SIGN)

LAKE6_MANUAL_MODE_STANDBY: Final = "standby"

# 只有这两个模式会用到功率；待机恒下发 0。
# 功率实体的可用性就按此表判定：未选模式或中断清空后不显示功率框
LAKE6_MANUAL_POWER_MODES: Final = ("charge", "discharge")

# 待机恒下发 power "0"，此时功率配置项不参与下发
LAKE6_MANUAL_POWER_STANDBY: Final = 0

# 功率范围由用户确认（2026-11-13）：20~2500W。
# 注意：V1.4 文档未给 /control-panels 的功率范围，此值来自产品侧确认，
# 不得与 TOU 的 LAKE6_TOU_POWER_MAX 混用
LAKE6_MANUAL_POWER_MIN: Final = 20
LAKE6_MANUAL_POWER_MAX: Final = 2500
LAKE6_MANUAL_POWER_STEP: Final = 1

# 时长只在本集成侧换算成绝对结束时刻，协议没有该字段；
# 上限 1440 分钟（24 小时）是本集成的输入上限，不是设备约束
LAKE6_MANUAL_DURATION_MIN: Final = 1
LAKE6_MANUAL_DURATION_MAX: Final = 1440
LAKE6_MANUAL_DURATION_STEP: Final = 1
