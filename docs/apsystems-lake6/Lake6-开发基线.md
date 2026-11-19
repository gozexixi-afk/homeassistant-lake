# Lake_6 开发基线（实体映射与架构决策）

- 基线代码：Home Assistant Core `2026.11.0`，Python 3.14
- 关联文档：`HA集成开发规则清单.md`（通用 HA 规则）、`lake6-openapi.json`（接口契约）
- 本文档性质：**Lake_6 的具体设计基线**。开发时若记忆与本文档不一致，**以本文档为准**；本文档未覆盖的通用 HA 规则，以《HA集成开发规则清单》为准
- 状态标记约定：`[定死]` 已确认不可变更 ｜ `[待确认]` 等产品/实测输入 ｜ `[未开始]` 尚未设计

---

## 0. 总原则（先读这一节，防止后续跑偏）

1. **EZ1 行为零变化**：不修改任何 EZ1 已有的实体 key、unique_id、取值逻辑、刷新间隔。
2. **契约以 openapi 为准**：实体只映射 `lake6-openapi.json` 中已定义的字段。实测多出的字段不消费。
3. **未知不等于可猜**：任何文档未定义的字段语义、单位、符号方向，一律标 `[待确认]`，不得凭合理性推断写进代码。
4. **转换只在 client 层做一次**：实体层永远看不到原始字符串。
5. **本文档与代码冲突时**：若代码尚无 Lake 实现，改代码；若代码已实现且与本文档冲突，视为缺陷。

### 0.1 与《HA集成开发规则清单》的差异声明

下表列出 Lake 基线与规则清单**字面表述不同**之处，均为有意决定。后续开发若发现"按清单该这么做、按本文档该那样做"，一律以本表为准，不要当成违规：

| 规则清单条目 | 清单字面要求 | 本基线做法 | 理由 |
|---|---|---|---|
| 第 1 条 | `requirements` 须为可 PyPI 安装的包；仓库内自研客户端属"已知偏离"，需在交付说明写明理由 | Lake client 放进 `lake6/client.py`，**不新增任何依赖** | 复用 `homeassistant.helpers.aiohttp_client` 与标准库，无需第三方包；交付说明中写明该偏离 |
| 第 13 条 | 诊断类数据标 `DIAGNOSTIC`，含"设备温度" | `device_temperature`（设备自身温度）标 `DIAGNOSTIC`；`battery_temperature`（电池温度）**不标** | 电池温度直接影响可充放区间与备电可用性，属主数据；清单未列出电池温度 |
| 第 27 条 | 现有 `entity.py` 写死 `model="EZ1-M"`，必须改为按设备类型传入 | **不改** EZ1 的 `entity.py`；Lake 在 `lake6/entity.py` 独立组装 `DeviceInfo` | 改 EZ1 的 `entity.py` 违反"EZ1 零变化"，且 `EZ1-M` 对 EZ1 本就是正确值。清单目标（Lake 显示 LAKE）已在 Lake 侧达成，详见 §3.5 |
| 第 69 条 | Lake 写操作后调用 `coordinator.async_request_refresh()` | 收敛为 `await coordinator.async_set_modes(**changes)` | `async_request_refresh()` 受防抖窗口约束、不会立即执行；而单独调 `async_refresh()` 又会被 `/modes` 的 300 秒节流挡住，详见 §8.1 |
| 第 3 条 | 复用 HA 共享 aiohttp session | Lake client **必须**注入 `async_get_clientsession(hass)` | 现有 EZ1 的 `__init__.py` 未注入 session，属历史写法，Lake 不得照抄 |

除上表外，其余条款（全异步 IO、平台层不发网络请求、`unique_id` 用设备真实 ID、`_abort_if_unique_id_configured`、异常携带 `translation_domain`、EZ1 快照零 diff、strict typing）**全部继承，不得放宽**。

---

## 1. 范围

### 1.1 本轮覆盖的端点

| 端点 | 方法 | 用途 | 状态 |
|---|---|---|---|
| `/devices` | GET | 设备基本信息 | `[定死]` |
| `/energies` | GET | 能量与功率 | `[定死]` |
| `/alarms` | GET | 14 个告警标志位 | `[定死]` |
| `/modes` | GET / POST | 工作模式配置 | `[定死]` |
| `/control-panels` | GET / POST | 一次性即时手动控制（充/放/待机 + 时长） | `[定死]`（2026-11-13 纳入） |

### 1.2 明确不做的事

- 不做自动型号探测（用户显式选 `device_type`）。
- 不新增独立集成（`DOMAIN` 不变，见 §3）。
- 不修改 ConfigFlow `VERSION`，不写 migration；老条目缺少 `device_type` 字段时按 `"ez1"` 处理（规则清单第 20 条）。
- 不做 `time_cfg` 的编辑界面：分时策略由只读 `sensor.tou_schedule` 展开（C10），写入路径本轮未实现。

---

## 2. 架构决策

### 2.1 [定死] 决策 A：Lake 使用独立的 coordinator 类

EZ1 的 `coordinator.py` 中 `ApSystemsSensorData` 只有两个字段（`output_data` / `alarm_info`），其 9 个 `value_fn` 直接访问 `c.p1` 等属性。Lake 需要 4 个数据来源，字段名完全不同。

**若复用同一个类**，EZ1 全部取值函数需改为兼容联合类型 → 违反"EZ1 零变化"。

**结论**：`coordinator.py` 一行不动，Lake 新建 `lake6/coordinator.py`。

> "复用同一模式"指复用 **DataUpdateCoordinator + 构造注入 client + `async_config_entry_first_refresh()`** 这套写法，不是复用同一个类。

### 2.2 [定死] 决策 B：平台入口用 `isinstance` 分派

HA 的机制决定了"一条 entry → 一个 domain → 固定的平台文件"，Lake 的实体必须经由现有的 `sensor.py` / `binary_sensor.py` / `number.py` / `switch.py` 注册。

**统一写法**（四个文件相同结构，EZ1 的类与描述表完全不动）：

```python
async def async_setup_entry(hass, config_entry, add_entities):
    config = config_entry.runtime_data
    if isinstance(config, Lake6RuntimeData):      # Lake 分支
        lake6_sensor.async_setup_entities(config, add_entities)
        return
    # ↓ 以下为 EZ1 原逻辑，一字不改
    add_entities(ApSystemsSensorWithDescription(data=config, entity_description=desc) for desc in SENSORS)
```

**为什么用 `isinstance` 而不是读 `entry.data["device_type"]`**：`isinstance` 提供类型窄化，mypy strict 在该分支后会把 `config` 收窄为 `ApSystemsData`，EZ1 侧无需任何 `cast` 或类型忽略。

**例外：`__init__.py` 用 `entry.data` 判型**。那里的两个判断点都拿不到可靠的 `runtime_data`：

| 位置 | 判据 | 原因 |
|---|---|---|
| `async_setup_entry` | `entry.data.get(CONF_DEVICE_TYPE)` | 此时 `runtime_data` 还不存在，类型正是由这次判断决定的 |
| `async_unload_entry` | 同上 | 条目卸载时 HA 会先 `delattr(entry, "runtime_data")`（`config_entries.py:1180`），不能再当作稳定事实 |
| 4 个平台的 `async_setup_entry` | `isinstance` | 此时 `runtime_data` 必然已由 `__init__.py` 赋值，且需要类型窄化 |

### 2.3 [定死] 决策 B2：两套 PLATFORMS

```python
EZ1_PLATFORMS   = [Platform.BINARY_SENSOR, Platform.NUMBER, Platform.SENSOR, Platform.SWITCH]
LAKE6_PLATFORMS = [Platform.BINARY_SENSOR, Platform.NUMBER, Platform.SELECT, Platform.SENSOR, Platform.SWITCH]
```

- `async_setup_entry` 与 `async_unload_entry` **必须使用同一个列表**，否则卸载时 `select` 平台残留。
- `select` 平台仅 Lake 使用，实际不会被 EZ1 条目转发；`apsystems/select.py` 仍保留一句 `isinstance` 守卫，万一以后有人把 `SELECT` 加进 `EZ1_PLATFORMS`，是静默不加实体而不是 `AttributeError`。

### 2.4 [定死] 决策 C：类型转换集中在 client 层

设备返回的**所有**业务数值均为字符串（`"21.0"`、`"2500"`），唯一例外是 `rssi`（实测为数字）。

**铁律**：client 出口的数据已是 `float | int | bool | 语义字符串 | None`，实体层永不出现 `float(...)`。

**容错粒度是单字段，不是整条请求**：

| 场景 | 处理 | 影响面 |
|---|---|---|
| 网络失败 / 超时 | 抛异常 → `UpdateFailed` | 全部实体不可用 |
| `code != 200` | 抛 `Lake6ApiError` → `UpdateFailed` | 全部实体不可用 |
| 单字段为 `""` / 无法转换 | 该字段为 `None` | 仅该字段对应实体 unknown |

**所有数值转换函数的入参类型必须声明为 `str | int | float | None`**，先判类型再转换，禁止直接调用字符串方法（`rssi` 为 int，调用 `.strip()` 会导致整个 `/devices` 解析失败、集成加载失败）。

---

## 3. [定死] DOMAIN 与命名规范

### 3.1 DOMAIN 不变

`DOMAIN = "apsystems"`，Lake **不新增集成**。

设备注册表主键为 `(DOMAIN, device_id)` 二元组：

- EZ1：`("apsystems", "E070000...")`
- Lake：`("apsystems", "D09001000127")`

集成名相同、设备 ID 不同 → 两台设备在注册表中互相独立。`DOMAIN` 区分"哪个集成"，`device_id` 区分"哪台设备"。

> 若为此新建 DOMAIN，则等同新集成，`PLATFORMS` / `strings.json` / `translations` 全部需要重建，且"在现有集成内新增"的前提不成立。

### 3.2 translation_key 命名

- `translation_key` 与实体 `key` **完全相同**（沿用 EZ1 习惯）。
- 全部为 `snake_case` 小写，不带型号前缀（`device_id` 已保证 unique_id 唯一）。
- 已核对：Lake 的 38 个 key 与 EZ1 现有 15 个 key 无任何重复。

### 3.3 unique_id 生成规则

```python
f"{device_id}_{entity_description.key}"
```

- `device_id` = `entry.unique_id` = `/devices` 返回的 `dev_id`
- 一旦发布不可更改（历史记录、仪表盘、用户自定义名均绑定其上）

### 3.4 文件结构

```
homeassistant/components/apsystems/
├── __init__.py          改：按类型造 client/coordinator，选 PLATFORMS
├── coordinator.py       ✅ 不动（EZ1 专用）
├── entity.py            ✅ 不动（EZ1 专用）
├── config_flow.py       改：新增 device_type、两代各自的探测逻辑（M5，[完成]）
├── sensor.py            改：仅入口加 isinstance 分派
├── binary_sensor.py     改：同上
├── number.py            改：同上
├── switch.py            改：同上
├── select.py            新增：仅 Lake 使用
├── strings.json         改：新增 Lake 的 translation_key
├── manifest.json        ✅ 不动（Lake client 为集成内自研，不新增 requirements，理由见 §0.1）
└── lake6/
    ├── __init__.py      导出
    ├── const.py         Lake 常量：端口/端点/枚举映射/取值范围
    ├── client.py        协议层（M2）
    ├── entity.py        Lake 基础实体（DeviceInfo 组装）
    ├── coordinator.py   Lake6Coordinator + Lake6Data + Lake6RuntimeData
    ├── sensor.py        15 个
    ├── binary_sensor.py 14 个
    ├── number.py        3 个
    ├── select.py        1 个
    └── switch.py        2 个
```

### 3.5 [定死] `model` 的处理方式（解决规则清单第 27 条）

规则清单要求"`entity.py` 写死 `model="EZ1-M"` 必须改为按设备类型传入"。但修改 EZ1 的 `entity.py` 违反"EZ1 零变化"。

**结论**：EZ1 的 `entity.py` 保持不动（EZ1 型号确实是 `EZ1-M`，写死值正确）；Lake 在 `lake6/entity.py` 中独立组装：

```python
DeviceInfo(
    identifiers={(DOMAIN, device.dev_id)},
    manufacturer="APsystems",
    model=device.device_type,             # 取自 /devices 的 type 字段，如 "LAKE"
    serial_number=device.dev_id,
    sw_version=device.sw_version,         # client 层已归一：空串 → None
)
```

**2026.11 的 `DeviceInfo` 已从 `TypedDict` 改为 dataclass**（`device_registry.py:280-300`），字段默认值是 `UNDEFINED`：

| 传法 | 设备注册表行为 |
|---|---|
| 不传某个字段 | 值为 `UNDEFINED` → **不改动**已有值 |
| 显式传 `None` | **清空**该字段 |

这里选 `None` 而不是省略，是为了让「固件升级后 `dev_ver` 变空」也能反映到界面上；值为 `None` 时设备页不渲染「固件」行，正是 P1 要求的效果。

规则清单第 27 条的目标（Lake 显示 Lake_6）由此达成，EZ1 显示值不变。

---

## 4. [定死] 数据契约

### 4.1 client 层出口类型

```python
# 四个类一律 @dataclass(frozen=True, kw_only=True)：
#   快照不可变；同类型字段（尤其 14 个 bool）必须写名字，防止位置错位

@dataclass(frozen=True, kw_only=True)
class Lake6Device:            # GET /devices，仅在首次刷新拉取一次
    dev_id: str
    device_type: str          # 原始字段 type，改名避免与内置 type 冲突
    sw_version: str | None    # 已解析：空字符串 → None（P1）
    battery_capacity: float | None   # 原始字段 bat_cap，单位 kWh（C3）
    rssi: int | None          # 实测为 number，非 string（P6）

@dataclass(frozen=True, kw_only=True)
class Lake6Energies:          # GET /energies，12 个数值 + bat_status 语义串
    battery_soc: float | None
    ...                       # 13 个字段，与 LAKE6_ENERGY_FIELD_TO_ATTR 的属性名列一致

@dataclass(frozen=True, kw_only=True)
class Lake6Alarms:            # GET /alarms，14 个字段转为 bool
    battery_over_temperature: bool | None
    ...                       # 与 LAKE6_ALARM_FIELD_TO_ATTR 的属性名列一致

@dataclass(frozen=True, kw_only=True)
class Lake6Modes:             # GET /modes
    operating_mode: str | None
    eco: bool | None
    offgrid_on: bool | None
    depth_of_discharge: int | None
    time_cfg: Lake6TimeCfg    # 原值保留，供回写与排障
    tou_rules: Lake6TouRules  # 结构化视图（C10）
```

**字段命名约定**：dataclass 字段名 = 实体 key，**不带单位后缀**（单位写在行内注释），
这样实体层可以直接 `value_fn=lambda d: d.battery_capacity`，不需要在映射表里登记额外别名。
`Lake6TimeCfg` 定义为 `type Lake6TimeCfg = list[dict[str, Any]]`。

**`Lake6Energies` 与 `Lake6Alarms` 必须独立成类，永不合并为同一个 dict**（原因见 §10 坑点 P2）。

### 4.2 coordinator 层

```python
@dataclass
class Lake6Data:              # 每次刷新的完整快照
    energies: Lake6Energies
    alarms: Lake6Alarms
    modes: Lake6Modes

@dataclass
class Lake6RuntimeData:       # 挂到 entry.runtime_data 的容器
    coordinator: Lake6Coordinator
    device_id: str
    device: Lake6Device       # 静态信息，来自 _async_setup

type Lake6ConfigEntry = ConfigEntry[Lake6RuntimeData]
```

与 EZ1 的差异：EZ1 的 `device_version` / `battery_system` 是 coordinator 上的散字段；Lake 收敛进 `device` 对象，避免出现 `coordinator.api.max_power` 这类"隔着管家翻口袋"的写法。

**`always_update=False`**：`DataUpdateCoordinator` 默认每次刷新都调 `async_update_listeners()`（ `update_coordinator.py:608-613` ），即使数据一模一样。`Lake6Data` 的 3 个字段全是 frozen dataclass，`__eq__` 可靠；关掉后「数据未变 → 不通知 → 实体不重写 state → recorder 不写库」，这是把 60 秒轮询的写库量再压一档的关键。

### 4.3 client 方法签名

```python
class Lake6ApiClient:
    async def async_get(self, endpoint: str) -> dict[str, Any]      # 通用 GET，返回 data 对象
    async def async_post(self, endpoint: str, payload: dict[str, Any]) -> None
    async def async_get_device(self) -> Lake6Device
    async def async_get_energies(self) -> Lake6Energies
    async def async_get_alarms(self) -> Lake6Alarms
    async def async_get_modes(self) -> Lake6Modes
    async def async_set_modes(self, **changes: str) -> None   # 仅传变更字段，未变更字段一律省略
```

连接参数（集中于 `lake6/const.py`）：

| 参数 | 值 | 说明 |
|---|---|---|
| 端口 | `80` | 与 EZ1 的 8050 不同 |
| 单请求超时 | `10` 秒 | 单次刷新可能串行请求多个端点，最坏耗时约为「超时 × 请求数」；该值是"设备离线时尽快置为不可用"与"不拖垮一次刷新"的折中，不宜再放大 |
| 端点 | `/devices`、`/energies`、`/alarms`、`/modes` | `/control-panels` 本轮不使用 |

**常量命名约定**：`lake6/const.py` 内所有常量统一以 `LAKE6_` 为前缀，避免与集成内 EZ1 的同名常量（`DEFAULT_PORT` 等）混淆。

---

## 5. [定死] 端点 → 实体完整映射（共 38 个实体）

> 每一行对应 `lake6-openapi.json` 中一个已定义字段。标注"不是实体"的字段同样列出，用于核对契约无遗漏。

### 5.1 `/devices` → `DeviceInfo` schema（响应 9 个 key，文档定义 7 个）

| openapi 字段 | 文档类型 | 实测 | 归宿 | 说明 |
|---|---|---|---|---|
| `dev_id` | string | `D09001000127` | **不是实体** → `unique_id` / `serial_number` | |
| `type` | string | `LAKE` | **不是实体** → `DeviceInfo.model` | 必须用真实值 |
| `dev_ver` | string | `""` | **不是实体** → `DeviceInfo.sw_version` | 空 → `None`，见 P1 |
| `bat_cap` | string | `6.02` | `sensor.battery_capacity` | kWh，`ENERGY_STORAGE` / `MEASUREMENT`，DIAGNOSTIC，精度 2 |
| `ssid` | string | `APsystems-EMA2` | **不做实体** | 诊断价值低 |
| `ip` | string | `192.168.1.139` | **不做实体** | 即用户填写的地址 |
| `rssi` | string | `-41`（实为 number） | `sensor.wifi_signal` | dBm，`SIGNAL_STRENGTH` / `MEASUREMENT`，DIAGNOSTIC，整数不设精度，见 P6 |
| `bat_manuf`（文档无） | — | `9` | **不消费** | C8 已关闭：后续软件会屏蔽该字段；只上报代号、用户无法解析，且 Lake_6 固定电池型号 |
| `bat_model`（文档无） | — | `6` | **不消费** | 同上，C8 已关闭 |

**2 个 sensor。**

### 5.2 `/energies` → `Energies` schema（13 个字段，全部映射）

| 字段 | 实测 | key | 单位 | device_class | state_class | 精度 | category |
|---|---|---|---|---|---|---|---|
| `bat_soc` | `21.0` | `battery_soc` | % | `BATTERY` | `MEASUREMENT` | 1 | — |
| `bat_temp` | `18.4` | `battery_temperature` | °C | `TEMPERATURE` | `MEASUREMENT` | 1 | — |
| `dev_temp` | `27.4` | `device_temperature` | °C | `TEMPERATURE` | `MEASUREMENT` | 1 | `DIAGNOSTIC` |
| `bat_power` | `486` | `battery_power` | W | `POWER` | `MEASUREMENT` | 不设（整数） | — |
| `ongrid_power` | `527` | `grid_power` | W | `POWER` | `MEASUREMENT` | 不设（整数） | — |
| `offgrid_power` | `0` | `offgrid_power` | W | `POWER` | `MEASUREMENT` | 不设（整数） | — |
| `bat_impE` | `56.9117` | `battery_charge_energy` | kWh | `ENERGY` | `TOTAL_INCREASING` | 4 | — |
| `bat_expE` | `56.0467` | `battery_discharge_energy` | kWh | `ENERGY` | `TOTAL_INCREASING` | 4 | — |
| `ongrid_impE` | `63.9278` | `grid_import_energy` | kWh | `ENERGY` | `TOTAL_INCREASING` | 4 | — |
| `ongrid_expE` | `37.5053` | `grid_export_energy` | kWh | `ENERGY` | `TOTAL_INCREASING` | 4 | — |
| `offgrid_impE` | `0.4773` | `offgrid_import_energy` | kWh | `ENERGY` | `TOTAL_INCREASING` | 4 | — |
| `offgrid_expE` | `6.1574` | `offgrid_export_energy` | kWh | `ENERGY` | `TOTAL_INCREASING` | 4 | — |
| `bat_status` | `"1"` | `battery_status` | — | `ENUM` | **禁止设置** | — | — |

**13 个 sensor**（12 个数值 + 1 个 ENUM）。

- 类型分派：3 个功率字段（`bat_power` / `ongrid_power` / `offgrid_power`）走 **`_to_int`**（实测为纯整数字符串，如 `486`）；其余 9 个数值走 **`_to_float`**（实测带小数，如 `30.0` / `57.28800`）。依据见 §11 D6。
- 精度不做四舍五入，交给 HA 的显示精度设置（`suggested_display_precision`，取值见上表）。
- `bat_power` 符号方向未知，见 C4。在 client 字段上留 `# TODO 符号方向待实测`。
- `bat_status` 为 ENUM，`options` 见 §6.1；state 必须严格命中 `options`，`None` 是唯一合法例外。

### 5.3 `/alarms` → `Alarms` schema（14 个字段，全部映射）

全部：`device_class = PROBLEM`、`entity_category = DIAGNOSTIC`、`"1" → True`、`"0" → False`。

| 字段 | key | 文案（英文） |
|---|---|---|
| `bat_overtemp` | `battery_over_temperature` | Battery over-temperature |
| `bat_undertemp` | `battery_under_temperature` | Battery under-temperature |
| `bat_comm_err` | `battery_communication_error` | Battery communication error |
| `bat_overvolt` | `battery_over_voltage` | Battery over-voltage |
| `bat_undervolt` | `battery_under_voltage` | Battery under-voltage |
| `bat_overcur` | `battery_over_current` | Battery over-current |
| `bat_ie` | `battery_internal_error` | Battery internal error |
| **`dev_temp`** | **`device_temperature_protection`** | **Device temperature protection**（必须改名，见 P2） |
| `dev_sys_err` | `device_system_error` | Device system error |
| `bat_shutdown` | `battery_shutdown` | Battery shutdown |
| `grid_anomaly` | `grid_anomaly` | Grid anomaly |
| `offgrid_overcur` | `offgrid_over_current` | Off-grid over-current |
| `offgrid_shortcir` | `offgrid_short_circuit` | Off-grid short circuit |
| `bat_cal` | `battery_calibration` | Battery calibration |

**14 个 binary_sensor。**

**为什么不像 apsystems-storage 那样靠 endpoint 去重**（结构决策，非偏好）：

| 维度 | apsystems-storage | 本集成 |
|---|---|---|
| 数据形状 | 原始 dict 透传，无中间类型 | client 层产出 frozen dataclass |
| 实体 key | 两处都是 `data.dev_temp` | `device_temperature` / `device_temperature_protection` |
| 冲突解法 | `unique_id` 拼 endpoint 与 json_key | key 本身唯一，`unique_id` 只用 `{dev_id}_{key}` |
| `unique_id` 前缀 | `{DOMAIN}_{entry_id}` | `{dev_id}` |
| 告警平台 | **sensor**，`device_class=None`，显示 `"0"`/`"1"` | **binary_sensor** + `PROBLEM` |

它保留原始 JSON 键，所以不得不拼 endpoint 才能避免 unique_id 冲突；本集成在 client 层已完成解析，改名零运行时成本，还能拿到类型检查与自动补全。

`unique_id` 前缀用 `dev_id` 而不是 `entry_id`：用户删条目重新添加后 `entry_id` 会变，`dev_id` 不变，历史记录不会断。

### 5.4 `/modes` → `Modes` schema（7 个字段，全部有归宿）

| 字段 | 实测 | 实体 | key | 范围 / 选项 |
|---|---|---|---|---|
| `mode` | `"2"` | **select** | `operating_mode` | 见 §6.2 |
| `eco` | `"0"` | **switch** | `eco_mode` | 0/1 |
| `offgrid_on` | `"1"` | **switch** | `offgrid_output_enabled` | 0/1 |
| `dod` | `"20"` | **number** (%) | `depth_of_discharge` | **15–90**，step 1，BOX。语义 = 产品的 `backupSoc`（备电放电 SOC 下限），显示名用 **Backup SOC** |
| `backup_charP` | `"2500"`（老固件） | **不做实体** | — | **V1.5.2 已删除该参数**；老固件仍返回，但**一律忽略**：不解析、不建实体、不回写（C9-b） |
| `power_limit` | **V1.5.1 已删除** | **不做实体** | — | 官方废弃、实测从不返回；2026-11-11 起整体移除：`Lake6Modes` 不再解析该字段，不建实体、不写入（C1） |
| `time_cfg` | 嵌套数组（实测 3 条） | **sensor**（只读） | `tou_schedule` | 展开为结构化只读视图，见下方说明（C10）。`entity_category = DIAGNOSTIC`，仅在 `mode="3"` 时可用 |

**4 个可写实体**（1 select + 2 switch + 1 number），全部 `entity_category = EntityCategory.CONFIG`：
它们是可写参数而非实时测量，HA 会在设备页“配置”区展示；设为 `None` 会混进主数据区，设为 `DIAGNOSTIC` 又会被当作故障信息折叠。

**`time_cfg` 展开规则**（C10）：

| 原始字段 | 解码后 | 规则 |
|---|---|---|
| `E` | `enabled: bool` | 只有 `"0"` 为 `False`；**字段缺失按启用处理** |
| `W` | `weekdays: list[int]` | 保留 1–7 原值，**不得转成 Python 的 0–6 weekday**；非整数或越界项丢弃 |
| `TM[].T` | `start` / `end`（`HH:MM`） | 必须 8 位纯数字，否则整个 slot 丢弃（`T` 是解析锚点） |
| `TM[].F` | `function` | `"1"→charge`、`"2"→discharge`、`"3"→self_consumption`；未知码 → `None`，slot 保留 |
| `TM[].FI.P` | `power: int \| None` | `F="3"` 时 `FI` 为空对象，自然得到 `None` |
| `TM[].FI.GC` / `GD` | **不解析** | 固件强制为 1，实测可能整体缺失 |

- 实体：只读 `sensor.tou_schedule`，state = 启用规则条数，attributes = `{"rule_count": n, "rules": [...]}`。
- **可用性绑定 `mode == "3"`**。不可把该逻辑挂到 `select.operating_mode` 上——select 一旦不可用，
  用户就无法从 mode 2/4 切回 mode 3，形成死锁。
- `time_cfg` 原值仍保存在 `Lake6Modes.time_cfg`，结构化结果在 `Lake6Modes.tou_rules`。
- 容错遵循 P2 的爆炸半径原则：**坏一条规则只丢这一条，坏一个时段只丢这个时段**。
- number 的上下限为**硬编码常量**（放 `lake6/const.py`），因为 Lake 的 `/devices` 不返回 `maxPower`/`minPower`（与 EZ1 不同）。
- **`dod` 的命名陷阱**：设备字段叫 `dod`（Depth of Discharge），产品语义却是 `backupSoc` ——
  表示“备电模式下允许放电到的 SOC 下限”。`dod=15` 放得最狠，`dod=90` 等于几乎不放电，**数值越大越保守**。
  这与 DoD 的常规定义（放电深度越大 → SOC 越低）方向相反，所以显示名必须用 **Backup SOC**，
  而代码 key 保留 `depth_of_discharge` 以便与 openapi 字段名逐一对应。
  上界取 **90**（2026-11-12 按官方文档 V1.5.2 定稿，此前“产品口头确认 100”作废）。
- `backup_charP` 随 V1.5.2 废弃一并忽略：不解析、不建实体、不回写，也不再需要范围常量（C9-b 已结案）。

**写回字段映射**：4 个实体里有 2 个的实体 key 与 `POST /modes` 字段不同名，统一查常量表而不是手写字符串：

| 实体 key | `POST /modes` 字段 | 查哪张表 |
|---|---|---|
| `operating_mode` | `mode` | `LAKE6_MODE_ATTR_TO_FIELD` |
| `depth_of_discharge` | `dod` | `LAKE6_MODE_ATTR_TO_FIELD` |
| `eco_mode` | `eco` | `LAKE6_SWITCH_ENTITY_TO_FIELD` |
| `offgrid_output_enabled` | `offgrid_on` | `LAKE6_SWITCH_ENTITY_TO_FIELD` |

后两个单独一张表，是因为 `LAKE6_MODE_ATTR_TO_FIELD` 的键是 `Lake6Modes` 属性名（`eco` / `offgrid_on`），而实体 key 用的是产品语义名（`eco_mode` / `offgrid_output_enabled`）。

### 5.5 汇总（总计 38）

| 平台 | 数量 | 文件 |
|---|---|---|
| sensor | **16** | `lake6/sensor.py` |
| binary_sensor | 14 | `lake6/binary_sensor.py` |
| number | 3 | `lake6/number.py` |
| select | 2 | `lake6/select.py` |
| switch | 2 | `lake6/switch.py` |
| text | 1 | `lake6/text.py` |
| **合计** | **38** | |

按 `entity_category` 分布：**12 主数据 + 17 诊断 + 9 配置**。

| category | 数量 | 实体 |
|---|---|---|
| `None`（主数据） | 12 | `battery_soc`、`battery_temperature`、`battery_status`、3 个功率、6 个电量 |
| `DIAGNOSTIC`（诊断） | 17 | `battery_capacity`、`device_temperature`、`wifi_signal` + 14 个告警 |
| `CONFIG`（配置） | 9 | `operating_mode`、`manual_control_mode`、`depth_of_discharge`、`manual_control_power`、`manual_control_duration`、`eco_mode`、`offgrid_output_enabled`、`tou_plan`、`tou_schedule_format` |

### 5.6 `/control-panels` → 一次性即时手动控制（3 个可写实体）

**原则：接口字段不建实体，只做下发通道。** `control-panels` 的语义是"一次性任务"，不是可镜像的配置状态：

| 原始字段 | 实测 | 归宿 | 说明 |
|---|---|---|---|
| `mode` | `"0"` / `"1"` | 不做实体 | 运行状态而非配置：`"1"` 只在一次任务执行期间存在，执行完设备自动清空 `MI1` 并恢复原 mode 1~4。仅作为 `select.manual_control_mode` 的 `device_running` 属性暴露 |
| `MI1.time` | `"2026111302395620261113031156"`（**28 位，带秒**） | 不做实体 | 文档给 24 位（到分钟），实测回显 28 位；**写回固定 24 位，解析两者都认** |
| `MI1.power` | `"2000"` | 不做实体 | 与 `time` 按下标一一配对（平行数组）；**正 = 放电、负 = 充电、0 = 待机** |

三个可写实体把**一个请求拆成三个输入框**，三项都填好才下发（`coordinator.async_set_manual_control()`）：

| 实体 | 平台 | 取值 | 说明 |
|---|---|---|---|
| `manual_control_mode` | select | `charge` / `discharge` / `standby` | 只暂存，单独改不会发请求 |
| `manual_control_power` | number (W) | **20–2500**，step 1，BOX | 范围来自产品侧确认（文档未给）；`standby` 或未选模式时不可用 |
| `manual_control_duration` | number (min) | 1–1440，step 1，BOX | 本集成侧换算成 `now + duration` 的绝对结束时刻，协议无该字段；上限 1440 不是设备约束 |

下发与校验规则：

1. 请求体恒为 `{"mode": "1", "MI1": {"time": [24 位起止], "power": [带符号瓦数]}}`；待机时 `power` 为 `"0"`。
2. **POST 之后必须 `GET /control-panels` 回读**：返回 `mode != "1"` 说明设备没采纳（POST 的 200 只代表报文合法），记 `warning`，不抛异常。
3. **三个值只存在 coordinator 内存里**，不镜像设备：设备在任务结束后会清空 `MI1`，镜像它会让三项一起变 `unknown`，用户每次都得重填；重载/重启后三项为空属预期。
4. `/control-panels` 的**响应信封可能不带 `code`**（实测 GET 缺、POST 带）：该端点在 `_raise_for_code` 走 `code_optional=True`，缺 `code` 时回退到 `message == "SUCCESS"`；其余端点缺 `code` 仍按失败处理。

---

## 6. [定死] 枚举与语义串映射

**原则**：client 层负责"设备码 → 稳定语义串"，UI 层负责"语义串 → 中文"。设备固件调整枚举值时不牵动实体与自动化。

### 6.1 `bat_status`（ENUM sensor）

| 设备值 | options 值 | 中文 |
|---|---|---|
| `"1"` | `idle` | 空闲 |
| `"2"` | `charging` | 充电中 |
| `"3"` | `discharging` | 放电中 |
| `"4"` | `fault` | 故障 |
| `"5"` | `shutdown` | 关机 |
| `"6"` | `no_communication` | 通信中断 |
| `"7"` | `heating` | 加热中 |

`strings.json` 路径：`entity.sensor.battery_status.state.<option>`

### 6.2 `operating_mode`（select）

| 设备值 | options 值 | 中文 | 可否下发 |
|---|---|---|---|
| `"1"` | `ai` | AI 模式 | **禁止**（见 §8.2） |
| `"2"` | `self_consumption` | 自消耗模式 | 可 |
| `"3"` | `time_of_use` | 分时电价模式 | 可 |
| `"4"` | `backup` | 备电模式 | 可 |

- `options` **必须包含 `ai`**，否则设备处于 AI 模式时 `current_option` 的值不在 `options` 中，前端无法正确显示当前状态，且"从 AI 切走"这个需求无法成立。
- select 必须同时维护正向（`"1"→"ai"`）与反向（`"ai"→"1"`）映射，反向映射用于写回。
- `strings.json` 路径：`entity.select.operating_mode.state.<option>`
- `select` **不再暴露** `time_cfg` 属性：该数据已迁到只读 `sensor.tou_schedule`（C10）。
  select 必须保持常驻可用，否则切到 mode 2/4 后无法再切回 mode 3。

### 6.3 布尔类字段

| 字段 | 设备值 → 类型 | 写回时 |
|---|---|---|
| `eco` | `"0"→False`，`"1"→True` | `True→"1"`，`False→"0"` |
| `offgrid_on` | 同上 | 同上 |
| 全部 14 个告警位 | `"0"→False`，`"1"→True` | 只读，不写 |

---

## 7. [定死] 刷新策略

EZ1 是 `update_interval=12s` + 每次 2 个请求（600 次/小时）。但 EZ1 是**逆变器**，功率受云遮挡影响是秒级突变，12 秒有实际意义；Lake 是**储能**，功率与 SOC 都是分钟级变化，照搬 12 秒收益很小，却会让 13 个数值实体每天写入约 5 倍的 recorder 数据。

对照组是同型号设备的三方实现 apsystems-storage：`update_interval=60s`，每轮 4 个端点，其 `const.py` 注释明确写「60 seconds keeps the load at four requests per minute while still being responsive enough for the energy dashboard」。

| 端点 | 频率 | 实现 |
|---|---|---|
| `/devices` | 1 次 | `_async_setup()` 拉一次，之后走缓存 |
| `/energies` | 60 秒 | 跟随 `update_interval` |
| `/alarms` | 60 秒 | 跟随 `update_interval`，与 `/energies` 同一轮连续请求 |
| `/modes` | 300 秒 | `_async_update_data` 内时间戳节流 + 写操作后仅回读 `/modes` |
| `/control-panels` | 300 秒 | 同一轮内独立时间戳节流 + 下发后立即回读一次 |

**60 秒一轮 2 个请求 + 300 秒一轮 2 个请求 = 144 次/小时**，仍低于 apsystems-storage 默认的 240 次/小时（4 端点 × 60 秒）。

`/energies` 与 `/alarms` 同频，因此 `_async_update_data` 只需为 `/modes` 维护一个时间戳，不必为 `/alarms` 做独立节流。

**代价与补偿**：`/modes` 最多滞后 5 分钟，因此 §8 的 5 个可写实体**必须在写成功后立即回读 `GET /modes`**，不得依赖下次轮询；但回读只打 1 个请求，不走全量 `async_refresh()`（原因见 §8.1 第 4 条）。

---

## 8. [定死] 写操作规范

### 8.1 通用规则

1. `POST /modes` 所有字段均可选，**只传变更字段**，未变更字段一律省略。
2. **不得回传 `time_cfg`**（避免破坏设备侧未定义字段，见 P5）。
3. 写操作**统一走 `await self.coordinator.async_set_modes(**changes)`**：内部 POST → **只回读 `GET /modes`** → `async_set_updated_data()` 通知所有监听器。
4. **写后禁止调用 `async_refresh()`**：它会把 `/energies` 与 `/alarms` 一起拉，一次写入变成 1 个 POST + 3 个 GET；数值框连点几下就能把设备刷到 `POST /modes timed out`（坑点 P9）。
5. 写失败：异常原样向外抛，界面在下一轮回读后回到设备真实值。
6. 禁止只用 `coordinator.async_request_refresh()`：它受防抖窗口约束，不会立刻执行，会导致界面滞后。

### 8.3 [定死] 写后不做值比对（2026-11-11 撤销）

原先可写实体在 `async_set_*` 之后会调 `Lake6Entity._raise_if_not_applied()` 并抛 `write_not_applied`，现已整体删除。原因是实测反馈：数值框连点时每次都弹「设备未保留新值（期望 2499，实际 2496）」，提示量远超它能提供的价值。

现在的行为：

| 情况 | 表现 |
|---|---|
| 设备采纳了值 | 回读值 = 期望值，界面正常 |
| 设备没采纳 | 回读值 ≠ 期望值，界面**静默弹回真实值**，不报错、不弹窗 |
| 回读本身失败 | 异常从 `async_set_modes` 抛出，HA 记日志；下一轮轮询恢复后实体回到真实值 |

关键点：**回读仍然保留**，所以用户不会看到假值——被撤销的只是“不一致就报错”这一层。

> **不再手写乐观更新**：实体是 `CoordinatorEntity`，`native_value` 读自 `coordinator.data`；`async_refresh()` 成功后 `DataUpdateCoordinator` 会自动调用 `async_update_listeners()`，进而触发每个实体的 `_handle_coordinator_update()` 与 `async_write_ha_state()`。手动设 `_attr_native_value` 再 `async_write_ha_state()` 既冗余，又会在 POST 成功但回读失败时留下一个假显示值。
>
> **置脏必须在 POST 之前**：`async_refresh()` 会同步进入 `_async_update_data`，晚置位就会被 300 秒节流挡住、返回旧快照并把界面的新值顶回去。

> 对照：EZ1 的 `number.py` / `switch.py` 写法不合规（不刷新、非 CoordinatorEntity、自己直连 api）。Lake 不得照抄。

### 8.2 AI 模式拦截

行为矩阵：

| 设备当前 | 用户选择 | 结果 |
|---|---|---|
| AI | 自消耗 / 分时 / 备电 | 允许，下发并刷新 |
| 非 AI | 自消耗 / 分时 / 备电 | 允许，下发并刷新 |
| 任意 | **AI** | **拦截，弹提示，状态不变** |
| AI | AI（重选当前值） | 同样拦截，不做特判 |

实现要点：

```python
async def async_select_option(self, option: str) -> None:
    if option == MODE_AI:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="ai_mode_set_in_app",
        )
    await self.coordinator.async_set_modes(
        mode=LAKE6_OPERATING_MODE_FROM_STATE[option]
    )
```

- 使用 `ServiceValidationError`（`HomeAssistantError` 子类），前端显示可读提示且**不写 ERROR 日志**。不得用 `HomeAssistantError` 父类。
- 提示文案走 `strings.json` 的 `exceptions.ai_mode_set_in_app.message`，内容待定（C2）。
- 待实测：从 AI 切到 `mode=2` 是否在设备侧真正生效（C5）。若未生效，写后校验会报 `write_not_applied`，用户能看到真实原因而不是“界面自己弹回去”。

---

## 9. [定死] 错误码映射

`code` 是业务码，与 HTTP 状态码无关。判定成功**只看 `code == 200`**。

| code | 文档含义 | client 行为 |
|---|---|---|
| 200 | 成功 | 正常返回 |
| 1001 | 数据长度错误 | 抛 `Lake6ApiError(code, message)` |
| 1002 | 数据格式错误 | 抛 `Lake6ApiError` |
| 1003 | 内部错误 | 抛 `Lake6ApiError` |
| 1004 | **V1.5.2 文档未定义** | `const.py` 保留描述仅供早期固件日志可读，行为同“其它” |
| 2001 | 内部通信错误 | 抛 `Lake6ApiError` |
| 其它 | 未定义 | 一律按失败处理，原值写入日志 |

coordinator 统一转换为：

```python
UpdateFailed(translation_domain=DOMAIN, translation_key="lake6_api_error")
```

`strings.json` 需新增 `exceptions.lake6_api_error.message`。

**上述为默认行为，最终文案与重试策略待 C7 确认。**

---

## 10. 已知坑点（来自实测与文档对比）

| # | 坑 | 后果 | 处理 |
|---|---|---|---|
| P1 | `dev_ver` 实测为 `""` | 直接 `split(" ")` 会得到 `sw_version=""`，设备页显示空白 | `[定死]` 空/空白 → `None`；Lake 独立实现 `parse_sw_version`，不改 EZ1 |
| P2 | `dev_temp` 在 `/energies` 是温度值 `"27.4"`，在 `/alarms` 是告警标志位 `"0"` | **合并 dict 时后者覆盖前者，温度永远显示 0，且不报错不崩溃** | `[定死]` 两端点独立成类，永不合并；告警侧 key 改名 `device_temperature_protection` |
| P3 | `power_limit` 在文档 V1.5.1 中已被官方删除，实测也从未返回 | 保留实体会得到一个永远 `unknown` 的孤儿实体 | `[定死]` 2026-11-11 起**整体移除**：`Lake6Modes` 不再解析该字段，`const.py` / `number.py` / 三份翻译同步删除（C1 已结案） |
| P4 | `mode=1`（AI）本地下发不生效 | 用户以为设置成功 | `[定死]` 按 §8.2 拦截 |
| P5 | `time_cfg[].FI` 实测含 `GC` / `GD`；V1.5.2 已补定义，且注明**固件强制为 1、配置值无效** | 若回传会丢字段或改坏设备配置 | `[定死]` 只存不回传；写操作只传变更字段（D4 已结案）。解析时 `GC`/`GD` 一律跳过，不进入结构化视图 |
| P6 | `rssi` 文档为 string，实测为 number | 调用 `.strip()` 会抛 `AttributeError` → **整个集成加载失败** | `[定死]` 所有数值转换入参声明为 `str \| int \| float \| None`，先判类型 |
| P7 | ENUM sensor 的 state 必须严格命中 `options` | 大小写/下划线不一致 → 实体 unknown，仅日志有告警 | `[定死]` 固定全小写下划线，`None` 为唯一例外 |
| P8 | number 的上下限无设备上报来源 | 若硬编码错误，用户无法设置合法值 | `[定死]` 常量集中于 `lake6/const.py`；`backup_charP` 与 `power_limit` 均已随官方废弃移除，**现在只剩 `dod` 一个范围**（C9 已结案） |
| P9 | 写操作后若走全量 `async_refresh()`，会连带 `/energies` + `/alarms` 两个额外 GET | 数值框连点 → 每次 1 POST + 3 GET，设备 `POST /modes` 超时，界面连续弹“无法执行动作” | `[定死]` `async_set_modes` POST 成功后只回读 `GET /modes` 再 `async_set_updated_data()`（§8.1 第 4 条） |

---

## 11. 文档 vs 实测差异清单（反馈依据）

| # | 位置 | 文档 | 实测 | 影响级别 | 处理 |
|---|---|---|---|---|---|
| D1 | `/devices` `rssi` | `string` | `number` | **高**（会导致集成加载失败） | 代码双兼容；文档建议修正 |
| D2 | `/devices` | 无 `bat_manuf` / `bat_model` | 有，且另有 `ip` / `ssid` | 无（不消费） | **C8 已关闭**：后续软件会屏蔽这两个字段 |
| D3 | `/modes` `power_limit` | **V1.5.1 已删除该参数**（旧版示例中有） | 缺失 | 中（实体 unknown） | **C1 已结案**：官方废弃，非固件缺陷；2026-11-11 起实体整体移除，不再解析该字段 |
| D4 | `/modes` `time_cfg[].FI` | V1.5.2 起含 `P` / `GC` / `GD` | 2026-11-12 复测：3 条规则的 `FI` 只有 `P`，`F="3"` 时为空对象 `{}`，未见 `GC`/`GD` | 低（不回传） | **已结案**：`GC` = 允许电网充电、`GD` = 允许电池上网，**固件强制为 1、配置值无效**；实测缺失属正常，解析层按可缺省处理 |
| D5 | `/energies` 键名 | 注明"疑似尾部空格" | 实测无空格 | 无 | 文档建议删除该警告 |
| D6 | `/energies` 数值格式 | 未说明 | 设备按字段分区格式化：功率为**纯整数**（`"486"`）、SOC 1 位小数（`"30.0"`）、电量 4~5 位小数（`"57.28800"`） | 中（决定用 `_to_int` 还是 `_to_float`） | 3 个功率走 `_to_int`，其余 9 个走 `_to_float` |
| D7 | 端点清单 | V1.5.2 起共 5 个（新增 `/control-panels`，含 GET/POST 两节） | 存在且可用；2026-11-13 实测 `mode="1"` + 28 位 `time` | 中（可能漏实体） | **已纳入**（C11 结案）：一次性任务，建模为 3 个配置实体（§5.6） |
| D8 | `/modes` `backup_charP` | **V1.5.2 已删除该参数** | 老固件仍返回 `"2500"` | 中（新老固件不一致） | **C9-b 已结案**：官方废弃；**忽略该字段**——不解析、不建实体、不回写 |

**集成侧一律做兼容，不依赖公司修改文档。D1 / D6 建议反馈（D3 / D4 / D7 / D8 已在新版文档中解决）；D2 已由产品答复会屏蔽字段，无需再反馈。**

---

## 12. 待确认清单

| # | 项 | 类型 | 确认前默认 | 影响 |
|---|---|---|---|---|
| C1 | ~~`power_limit` 实测缺失的原因~~ **已结案** | 文档（V1.5.1） | **官方已删除该参数**，非固件缺陷；2026-11-11 起从集成中移除该实体（不解析、不建实体、不写入） | 无 |
| C2 | AI 模式拦截提示的最终文案（中 / 英） | 产品 | 占位文案 | 仅文案 |
| C3 | `bat_cap` 单位是否确为 kWh | 产品 | 按 kWh 处理 | 单位显示 |
| C4 | `bat_power` 符号方向（正 = 充电还是放电） | 实测 | 按原值输出 | 充放电统计方向 |
| C5 | 从 AI 切到其它模式是否在设备侧生效 | 实测 | 视为生效 | 功能正确性 |
| C6 | 累计量是否因固件升级归零 | 实测 | `TOTAL_INCREASING` 自动处理 | 统计曲线 |
| C7 | 错误码语义（4 个子问题：2001 是否可重试、是否存在未列出码、`message` 是否可读、写失败是否可能部分生效） | 产品 | §9 默认行为 | 文案与重试策略。**第 1 问（1003/1004 是否区分）已结案**：V1.5.2 只定义了 1001/1002/1003/2001，无 1004 |
| C8 | ~~`bat_manuf` / `bat_model` 含义~~ **已关闭** | 产品（已答复 RVIER-6-398） | **不消费** | 无。产品答复：后续软件会屏蔽该字段；只上报代号、用户无法解析，且 Lake_6 固定电池型号 |
| C9-a | `dod` 可设范围 | **已定**（官方文档 V1.5.2） | **15–90**，已写入 `const.py`；此前“产品口头确认 100”作废，以文档为准 | 无 |
| C9-b | ~~`backup_charP` 可设范围~~ **已结案** | 文档（V1.5.2）+ 用户决策 | **不做实体**：官方已删除该参数，老固件虽仍返回但一律忽略（不解析、不建实体、不回写）。范围问题随之消失，无需常量 | 无 |
| C10 | ~~`time_cfg` 的处理方式~~ **已定（2026-11-12 改版）** | 架构 | **展开为只读 `sensor.tou_schedule`**：`client` 层解码为 `Lake6TouRule` / `Lake6TouSlot`，state = 启用条数，attributes = 结构化 `rules`；`available` 绑定 `mode == "3"`。原值仍保留在 `Lake6Modes.time_cfg` | 旧方案（`select` 属性透出原始数组）已废弃：属性无法按 mode 门控，且嵌套数组在自动化里取值路径过深。`text` 实体仍不可行——state 超 255 字符回退 `unknown`（`core.py:2567`），3 条规则拼接已接近上限 |
| C11 | ~~`/control-panels` 是否纳入~~ **已定（2026-11-13 纳入）** | 架构 + 用户 | **纳入**，建模为 3 个配置实体（模式 / 功率 / 时长），三项都填好才下发；接口字段不建实体，`mode` 只作为属性暴露（§5.6） | 设备侧是一次性任务，执行完自动清空并恢复原 mode，因此**不能镜像到实体**：镜像会让三项一起变 `unknown`。实测补充：GET 信封缺 `code`（需 `code_optional` 回退 `message`），`MI1.time` 回显 28 位（文档 24 位） |

**C2 / C7 不阻塞 M2**：client 先按默认行为实现，确认后只改 `const.py` 映射表与 `strings.json`，不动架构。**C9 已全部结案**（C9-a 定范围、C9-b 不做实体），M4 的 number 范围阻塞已解除。

---

## 13. 里程碑

| 阶段 | 内容 | 状态 |
|---|---|---|
| M1 | 端点 → 实体映射与架构决策（本文档） | `[完成]`（除 C2/C7 待确认） |
| M2 | `lake6/client.py`：URL 拼接、`code` 校验、类型转换、单字段容错、错误码映射 | `[完成]`（数据类 / 转换函数 / `parse_*` / `Lake6ApiClient` 均已就位） |
| M3 | `lake6/coordinator.py`：`Lake6Coordinator` + 两级轮询（60 秒 / 300 秒）+ 数据契约 | `[完成]` |
| M4 | 5 个平台文件 + 实体实现（34 个）+ 分派接线 | `[完成]`（4a 基类 + 4b 15 sensor + 4c 14 binary_sensor + 4d 5 可写实体 + 4e `__init__.py` / `select.py` 接线） |
| M5 | `config_flow` 增加 `device_type`、端口默认值、`unique_id` 取 `dev_id` | `[完成]`（下拉选型号 + 两代各自探测 + EZ1 title 与 unique_id 不变） |
| M6 | `strings.json` + `translations/en.json` + `translations/zh-Hans.json`（快照测试不纳入本地部署范围） | `[完成]`（en 的 72 个叶子 key 与 strings 同构；zh-Hans 覆盖 Lake6 34 个实体 + EZ1 15 个实体 + 11 个 state + 3 条异常） |

---

## 14. M4 验收单（35 项）

配置条目验收：

- [ ] 新增 Lake 条目后，`entry.unique_id == dev_id`
- [ ] 设备页显示 `model = LAKE`、`sw_version` 为"未知"（当前固件 `dev_ver` 为空）
- [ ] 老 EZ1 条目重载后，实体 ID、unique_id、显示值、刷新间隔全部不变
- [ ] EZ1 的 4 份 `.ambr` 快照零 diff

sensor（16）：

- [ ] `battery_soc` / `battery_temperature` / `device_temperature`
- [ ] `battery_power` / `grid_power` / `offgrid_power`
- [ ] `battery_charge_energy` / `battery_discharge_energy`
- [ ] `grid_import_energy` / `grid_export_energy`
- [ ] `offgrid_import_energy` / `offgrid_export_energy`
- [ ] `battery_status`（7 个状态均能正确显示中文）
- [ ] `battery_capacity` / `wifi_signal`
- [ ] `tou_schedule` 在 `mode=3` 时可用，state = 启用条数，attributes 的 `rules` 条数与设备 `time_cfg` 长度一致
- [ ] 切到 mode=2 后 `tou_schedule` 变 `unavailable`，切回 mode=3 自动恢复（C10 回归）

binary_sensor（14）：

- [ ] 14 个告警实体全部创建，`entity_category = DIAGNOSTIC`
- [ ] 触发任一告警（可用 mock）后对应实体变为 `on`
- [ ] `device_temperature_protection` 与 `device_temperature` 取值互不影响（P2 回归）

number（1）：

- [ ] `depth_of_discharge` 范围为 **15–90**（C9-a 已定），显示名为 **Backup SOC**；写入后界面立即更新且 `curl GET /modes` 回读一致
- [ ] 实体列表中**不再出现** `backup_charge_power`，即使老固件仍返回 `backup_charP`（C9-b 回归）
- [ ] 实体列表中**不再出现** `power_limit`（P3 回归）

select（1）：

- [ ] `operating_mode` 当前值为 AI 时正确显示"AI 模式"
- [ ] AI → 自消耗：下发成功，界面更新
- [ ] 自消耗 → AI：被拦截，弹出可读提示，状态不变

switch（2）：

- [ ] `eco_mode` 开关后 `curl GET /modes` 回读一致
- [ ] `offgrid_output_enabled` 同上

异常与边界：

- [ ] 断网时条目进入重试而非崩溃
- [ ] 设备返回 `code != 200` 时显示可读错误，日志含原始 code
- [ ] `rssi` 返回字符串 `"-43"` 与数字 `-43` 两种形态均能正常解析（P6 回归）
- [ ] 单字段为 `""` 时仅该实体 unknown，其余实体正常

---

## 15. 变更记录

| 日期 | 变更 | 原因 |
|---|---|---|
| 2026-11-10 | 初版：M1 定稿 | Lake_6 接入设计基线 |
| 2026-11-10 | 修正 sensor 数量 14 → 15（总数 34 → 35） | 上一轮汇总漏计 `bat_status` |
| 2026-11-10 | 撤回 `dod` / `backup_charP` 的范围推断，从 `const.py` 删除；仅保留 `power_limit` 的 0–2500（有 openapi 原文） | 范围须以实测为准，不得预先填推断值；C9 升级为 M4 硬阻塞项 |
| 2026-11-10 | 新增 C10：`time_cfg` 处理方式待定，本轮只原样保存；M6 增加“行内注释转英文”任务 | `time_cfg` 实测结构与 openapi 模型不一致；HA core 评审不接受中文注释 |
| 2026-11-11 | 产品答复并定稿 5 项：C8 关闭；C9-a `dod` = 15–100 且语义为 backupSoc；6 个可写实体改 `EntityCategory.CONFIG`（分类变为 12/17/6）；`dev_id` 写入 `serial_number`；`/control-panels` 接口可用但本轮不纳入（C11） | 产物 E1 与 apsystems-storage 参考实现对比：第三方 `dod` 写 15–100（与 openapi 的 90 冲突），产品确认取 100 |
| 2026-11-11 | 新增 D6（设备按字段分区格式化：功率纯整数）、D7（`/control-panels` 端点存在），D3 升级为 3 次独立证据 | 依据 4 张新实测截图 + apsystems-storage 源码 |
| 2026-11-11 | 文档升级至 V1.5.2，定稿 4 项：C1 结案（V1.5.1 删除 `power_limit`）、C9-b 结案（V1.5.2 删除 `backup_charP`，实体保留作兜底）、D4 结案（`GC`/`GD` 已定义且固件强制为 1）、C10 定稿（`time_cfg` 挂 `select.operating_mode` 的 `extra_state_attributes`）；C11 维持不纳入；新增 D8 | `power_limit` / `backup_charP` 保留为对老固件的兼容兜底，实体总数仍为 35；独立 `text` 实体会因 state 超 255 字符被置为 `unknown`，必须走属性通道 |
| 2026-11-11 | C9-b 定稿：`backup_charP` 范围 0–2500（来源为第三方实现）；`power_limit` 设 `entity_registry_enabled_default=False` | 官方已删除两个参数、取不到官方范围；永久 `unknown` 的实体默认不显示更干净 |
| 2026-11-11 | §7 刷新策略从「12/60/300 三级」改为「60/60 + 300 两级」：`/energies` 与 `/alarms` 同频 60 秒，`/modes` 仍 300 秒节流；请求量 372 → 132 次/小时 | 与同型号三方实现 apsystems-storage（60 秒 × 4 端点 = 240 次/小时）对照：Lake 是储能、数值分钟级变化，12 秒（继承自逆变器 EZ1）收益很小，却使 13 个数值实体的 recorder 写入量多 5 倍 |
| 2026-11-11 | M3 定稿：`Lake6ApiClient` 全面改用 `async_` 前缀并补 5 个语义方法；写操作收敛为 `coordinator.async_set_modes()`；§8.1 取消手写乐观更新；coordinator 关 `always_update` | 节流引入后，实体直接调 client 再 `async_refresh()` 会被 300 秒窗口挡住、拿到旧快照；置脏与刷新必须绑定在 coordinator 内才能保证顺序；`always_update=False` 让数据未变时不触发 state 重写 |
| 2026-11-11 | M4-4a 完成：新增 `lake6/entity.py`（`Lake6Entity`）；§3.5 示例改为 `device.device_type` / `device.sw_version` | 2026.11 的 `DeviceInfo` 已由 `TypedDict` 改为 dataclass、字段默认 `UNDEFINED`；`parse_sw_version` 已在 M2 移入 client 层，实体层不再重复解析 |
| 2026-11-11 | M4-4b 完成：新增 `lake6/sensor.py`（15 个）；§5.1 / §5.2 表格补 precision 与 state_class 列 | `value_fn` 收 `Lake6Coordinator` 而非 `Lake6Data`：`battery_capacity` / `wifi_signal` 取自 `coordinator.device`，不随每轮刷新；`battery_status.options` 直接由 `LAKE6_BATTERY_STATUS_TO_STATE` 派生，固件新增状态时只改一处 |
| 2026-11-11 | M4-4c 完成：新增 `lake6/binary_sensor.py`（14 个告警） | 描述子字段名沿用 EZ1 的 `is_on`；签名用 `Callable[[Lake6Data], bool | None]` 而非传 coordinator（14 个全读 `/alarms`，无 `/devices` 特例）；`device_temperature_protection` 单独加注释防 P2 回退 |
| 2026-11-11 | 核对 apsystems-storage 的 `dev_temp` 处理：确认其靠 endpoint 拼 unique_id 去重、告警走 sensor 平台；本集成维持「解析层改名 + key 唯一」 | 它是 dict 透传，没有中间类型可改名，属不得已；本集成在 client 层已完成解析，改名可获得类型检查且零运行时成本；`unique_id` 用 `dev_id` 前缀而非 `entry_id`，避免重添加条目后历史记录丢失 |
| 2026-11-11 | M4-4d 完成：新增 `number.py`（2）/ `select.py`（1）/ `switch.py`（2）；const 新增 `LAKE6_SWITCH_ENTITY_TO_FIELD` | switch 的实体 key（`eco_mode` / `offgrid_output_enabled`）与 `/modes` 字段名（`eco` / `offgrid_on`）不同名，无法用 `LAKE6_MODE_ATTR_TO_FIELD` 反查，故单列一张表；number 的浮点输入必须 `int()` 后再转 `str`，不能把 `"35.0"` 发给设备 |
| 2026-11-11 | 新增 §8.3 写后校验：`Lake6Entity._raise_if_not_applied()`，6 个可写实体写入后比对回读值，不一致抛 `write_not_applied`（**已于同日撤销**，见文末） | `code=200` 只证明请求被接收，不证明值被采纳；设备静默忽略时界面会自己弹回，用户分不清是自己没点到还是设备不认。回读失败时不报错，避免“实体已不可用 + 又说没生效”的双重误导 |
| 2026-11-11 | M4-4e 完成（M4 收尾）：`__init__.py` 按 `device_type` 造 client/coordinator 并选平台清单；新增 `apsystems/select.py`；4 个平台入口加 `isinstance` 分派；`const.py` 新增 `CONF_DEVICE_TYPE` / `DEVICE_TYPE_EZ1` / `DEVICE_TYPE_LAKE6` | 39 项接线校验全过：EZ1 条目仍产出 9/4/1/1 个实体且类归属不变，Lake6 条目产出 15/14/3/2/1；Lake6 走 80 端口与 HA 共享 session |
| 2026-11-11 | §2.3 清单命名从 `PLATFORMS_EZ1` / `PLATFORMS_LAKE6` 改为 `EZ1_PLATFORMS` / `LAKE6_PLATFORMS`；§2.2 补「`__init__.py` 用 `entry.data` 判型」对照表 | `async_unload_entry` 不能读 `runtime_data`：HA 卸载时会先 `delattr`（`config_entries.py:1180`）；命名调整后与既有测试的 patch 目标一致 |
| 2026-11-11 | 既有测试 4 处 `patch("...apsystems.PLATFORMS")` 改为 `EZ1_PLATFORMS` | 旧的单一 `PLATFORMS` 已拆成两份，不改会 `AttributeError`；这 4 个测试本来测的就是 EZ1 路径，改名后语义更准 |
| 2026-11-11 | M5 完成：`config_flow` 单步表单加 `device_type` 下拉（默认 `ez1`），按型号分别探测；Lake6 的 `unique_id` 取 `dev_id`、title 取固件 `type`；`strings.json` 补 `config.step.user` 与顶层 `selector` 段 | 选两步流程会让 EZ1 用户多一次点击，故合并为一步；`device_type` 用 `entry.data` 缺失兼容（`.get(..., DEVICE_TYPE_EZ1)`）：HA 的 `async_configure` 不会用 schema 二次校验输入，老测试与老条目都可能没有这个键 |
| 2026-11-11 | 删除 `Lake6ApiClient.async_test_connection()`，config_flow 直接调 `async_get_device()`（§4.3 同步） | 它只转发不加工，而 config_flow 需要拿 `dev_id` 与固件 `type`；为拿返回值再包一层返回值的包装函数没有价值 |
| 2026-11-11 | `lake6/client.py` 的 `async_test_connection` 删除后，现有 `test_config_flow.py` 5 个用例无需修改 | `_async_probe` 对缺失 `device_type` 的输入按 EZ1 处理，且 `async_create_entry(data=user_input)` 不会补写该键，`result["data"]` 与原断言一致 |
| 2026-11-11 | M6 第一部分完成：`strings.json` 补齐 35 个 Lake6 实体名、`sensor.battery_status` 7 个 state、`select.operating_mode` 4 个 state；`entity` 各段按 key 字母序合并 EZ1 与 Lake6 | 50 个实体 key 与代码双向对齐（EZ1 15 + Lake6 35），数量逐平台相等；`depth_of_discharge` 的显示名按 §5.4 用 **Backup SOC**，不用 Depth of Discharge |
| 2026-11-11 | M6 发现补漏：`exceptions` 需要 **3** 条新文案而非 2 条——`lake6_api_error` 此前未登记 | `lake6/coordinator.py` 两处 `UpdateFailed` 都引用 `translation_key="lake6_api_error"`，缺翻译时更新失败的日志与界面会直接显示 key 本身 |
| 2026-11-11 | M6 第二部分完成：集成内 13 个 `.py` 的 130 行中文注释全部转为英文（`lake6/const.py` 54 行、`lake6/client.py` 41 行为大头） | 校验结果：0 行含中文、13 文件 `ast.parse` 全过、无行超 88 字符；翻译保留「为什么」而非只说「做什么」，如 `dod` 单位陷阱、`dev_temp` 同名异义、置脏必须在 POST 之前 |
| 2026-11-11 | 行内注释保留 `§n` 章节引用与 `°C` 符号，不改写为 ASCII | `homeassistant/util/unit_conversion.py` 的注释与 docstring 已大量使用 `°C` 且 ruff 通过，说明 `RUF002`/`RUF003` 只针对 confusable 字母；`§n` 是追溯基线的唯一线索，改写为文字会丢失信息 |
| 2026-11-11 | **撤销「行内注释转英文」任务**：13 个 `.py` 的 130 行注释已全部还原为中文；§13 的 M6 范围收窄为「本地部署」 | 交付目标变更为「在本地 VirtualBox 的 HAOS 里装成 custom integration 使用」，不走 HA core PR；注释不进入字节码、不影响运行时，中文注释可维护性更高 |
| 2026-11-11 | 发现本地部署阻塞项 1：`manifest.json` 缺 `version` 字段，安装到 `custom_components/` 后会被 HA 直接拒绝加载 | `loader.py:835` 对 `integration.version is None` 的 custom integration 打 error 并 block；core 内的集成不需要该字段，所以当前 manifest 是沿用 core 的写法 |
| 2026-11-11 | 发现本地部署阻塞项 2：`translations/en.json` 缺失时 35 个实体名会全部退化成 `Power` / `Power_2` 之类 | `helpers/translation.py:101` 运行时只读 `translations/<lang>.json`，从不读 `strings.json`；`strings.json` 只是开发期源文件，必须展开 4 个 `[%key:common::...%]` 引用后才等于 `en.json` |
| 2026-11-11 | M6 完成：手工生成 `homeassistant/components/apsystems/translations/en.json`（222 行，展开 4 个 common 引用） | 本机无 HA 依赖、跑不了 `script.translations develop`，故按 `strings.json` 逐字录制；校验结果：74 个叶子 key 与 `strings.json` 同构、无残留 `[%key:`、仅 4 处值不同。注意 `.gitignore:12` 忽略了 `components/*/translations`，传虚拟机时需手动拷目录 |
| 2026-11-11 | 本地部署最小修改：`manifest.json` 末尾加 `"version": "0.1.0"` | `loader.py:835` 对 custom integration 的 `version` 做硬校验，缺失时直接 block；core 内置集成不需要该字段，所以原 manifest 沿用 core 写法 |
| 2026-11-11 | 新增 `translations/zh-Hans.json`（174 行），只翻译 Lake6 部分 | `_build_category_cache` 按 key 合并（`component_cache.update(flat)`），故只需写要覆盖的 key，其余 fallback 到 en；当时刻意不写 EZ1 独有的 key。`wifi_signal` 仅 Lake6 使用（EZ1 的 9 个 sensor 里没有它），不存在共用问题；后续已补齐 EZ1 全部 15 个实体 |
| 2026-11-11 | 撤销 §8.3 写后值比对：`_raise_if_not_applied` 从 `lake6/entity.py` 删除，`number` / `select` / `switch` 三处调用点同步移除，`write_not_applied` 文案从 `strings.json` / `en.json` / `zh-Hans.json` 删除 | 用户实测反馈：数值框连点会连续弹「设备未保留新值（期望 2499，实际 2496）」。回读仍保留，界面静默弹回设备真实值，不会留下假值 |
| 2026-11-11 | `async_set_modes` 改为只回读 `GET /modes` + `async_set_updated_data()`，不再调 `async_refresh()` | 全量刷新会连带 `/energies` 与 `/alarms`，一次写入从 1 POST + 1 GET 变 1 POST + 3 GET；连续写入直接把设备刷到 `POST /modes timed out`（新增坑点 P9） |
| 2026-11-11 | 整体移除 `power_limit` 实体：实体描述子、`LAKE6_POWER_LIMIT_*` 常量、字段映射、`Lake6Modes.power_limit`、三份翻译同步删除；Lake6 实体总数 35 → 34 | 该参数 V1.5.1 起官方删除、实测从不返回，保留只能得到一个永远 `unknown` 的孤儿实体；用户确认删除 |
| 2026-11-11 | `translations/zh-Hans.json` 补齐 EZ1 的 15 个实体名与 `inverter_error` | 之前只翻 Lake6，EZ1 在中文界面下仍是英文名；`_build_category_cache` 按 key 合并，现三份 JSON 叶子 key 均为 72 |
| 2026-11-11 | 新增 `homeassistant/components/apsystems/icons.json`：Lake6 的 34 个实体按平台 + `translation_key` 登记默认图标，取值参照 apsystems_storage 的同名字段 | apsystems_storage 的图标并未写在实体描述子里（其 `SensorEntityDescription` 未传 `icon`），而是走 HA 的图标翻译机制 `icons.json`（其 `quality_scale.yaml` 将 `icon-translations` 标为 done）；本集成只登记 Lake6 的 key，EZ1 一条不写，故 EZ1 界面零变化。校验：34 = 15 sensor + 14 binary_sensor + 2 number + 1 select + 2 switch，与代码逐一吻合、0 碰撞 |
| 2026-11-11 | 同步 `设备页与实体定位指南.md`：实体总数 35 → 34、配置区 6 → 5、删除 `power_limit` 所在行，新增 §2.4「图标从哪来」 | 删除 `power_limit` 后指南里的三处计数与布局示意均已失效；§2.4 记录图标三级优先级（实体 `icon` > `icons.json` > `device_class` 默认），并注明改完需重载 + Ctrl+F5 |
| 2026-11-11 | Lake6 的 34 个英文实体名参照 apsystems_storage 重写：改为首字母大写的命名法，并采用它的措辞（`State of charge` → **Battery SOC**、`Grid power` → **On-grid Power**、`Grid exported energy` → **On-grid Accumulated Output Energy**、`Battery over-voltage` → **Battery Overvoltage** 等）；`select.operating_mode` 的 4 个 state 同步改为 `AI Mode` / `Self-consumption Mode` / `Time-of-Use Mode` / `Backup Mode`。`strings.json` 与 `translations/en.json` 同步改，EZ1 的 15 个名字逐字未动 | 用户要求英文界面与 apsystems_storage 观感一致。改的是 `entity.<platform>.<key>.name`，不含 `key`/`unique_id`，因此已有实体的 `entity_id` 不变（slug 不含大小写）；三份 JSON 叶子 key 仍为 72 |
| 2026-11-11 | `depth_of_discharge` 的英文名**不跟随** apsystems_storage，仍为 **Backup SOC** | 它的 `dod` 字段存的是「备电保留的 SOC 下限」（数值越大越保守），而 Depth of Discharge 的常规定义是 `100% - SOC`，直接照抄会让数值含义反向（§5.4）。这是唯一一条为了语义正确而放弃对齐的命名 |
| 2026-11-12 | `backup_charP` 从「保留兜底实体」改为**彻底忽略**：`Lake6Modes.backup_charge_power`、`LAKE6_BACKUP_CHARGE_POWER_*` 常量、字段映射、`number` 描述子、`strings.json` / `icons.json` 条目全部删除；实体总数 34 → 33 | 实测确认设备仍返回 `"2500"`（固件停在 V1.5.1 水平），但协议已废弃，保留只会得到一个永远 `unknown` 的实体；不解析即天然容忍 |
| 2026-11-12 | `dod` 上限 100 → **90**（`LAKE6_DEPTH_OF_DISCHARGE_MAX`），C9-a 依据改为官方文档 V1.5.2，此前“产品口头确认 100”作废 | 实测 `dod="83"` 落在两个区间内，无法区分；文档是唯一有出处的依据 |
| 2026-11-12 | C10 改版：`time_cfg` 从「挂 `select.operating_mode` 的属性」改为**只读 `sensor.tou_schedule`**；`client` 层新增 `Lake6TouRule` / `Lake6TouSlot` 解码 `E` / `W` / `TM[].T` / `TM[].F` / `TM[].FI.P`；`available` 绑定 `mode == "3"`；实体总数 33 → 34（sensor 15 → 16，诊断区 17 → 18） | 实测 3 条规则：`FI` 只有 `P`（无 `GC`/`GD`）、`F="3"` 时 `FI` 为空对象、`E="0"` 的行仍保留完整 `TM`。门控不能挂 select：select 一旦不可用就无法切回 mode 3。`text` 实体仍不可行，3 条规则拼接已逼近 255 字符 |
| 2026-11-13 | C11 结案：`/control-panels` 纳入（§5.6）；新增 `select.manual_control_mode` + `number.manual_control_power` + `number.manual_control_duration`，实体总数 35 → 38；`client` 新增 `Lake6ControlPanel` / `Lake6ControlPanelWindow` 与 `async_get_control_panel` / `async_set_control_panel`；`coordinator` 新增 `Lake6ManualControl` 暂存态与 `_async_send_manual_control`；`/control-panels` 以 300 秒节流加入轮询（请求量 132 → 144 次/小时） | 用户要求“即时手动控制”：三选一模式 + 功率（20–2500W，产品侧确认）+ 时长（分钟），**三项都齐了才 POST**，避免半填状态下反复重启时间窗。接口层有三个坑：① 信封可能缺 `code`，`code_optional=True` 时回退 `message == SUCCESS`；② `MI1.time` 实测 28 位（带秒），文档 24 位，解析两者都认、写回固定 24 位；③ `time` 与 `power` 是平行数组，截断或错位会把功率挂到错误时段 |

