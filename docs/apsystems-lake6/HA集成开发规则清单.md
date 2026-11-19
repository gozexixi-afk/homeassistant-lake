# HA 集成开发规则清单（apsystems 加 Lake_6 专用）

- 适用代码基线：Home Assistant Core `2026.11.0`（仓库 HEAD `74cf5a49`），Python 3.14
- 目标：在现有 `apsystems` 集成内新增 Lake_6 支持，**EZ1 行为零变化**
- 用法：写代码前扫一遍，提交/验收前逐条打勾

---

## 一、硬性规则（违反会被 CI 或评审拦下）

| # | 官方规则 | 本项目落点 | 怎么检查 |
|---|---|---|---|
| 1 | 只能通过 `manifest.json` 声明集成；`requirements` 必须是可从 PyPI 安装的包，且**固定版本** | Lake_6 客户端若为仓库内自研，则不加 requirements。这是与官方惯例的**已知偏离**，需在交付说明中单独写明理由 | 检查 `manifest.json` diff 只有必要字段变化 |
| 2 | 所有 IO 必须 async，禁止在事件循环里做阻塞调用 | Lake 的 HTTP 全部走 aiohttp 异步客户端；解析放在协程内（响应体很小，无需 executor） | 搜索新代码里有无 `requests` / `urllib` / `time.sleep` |
| 3 | 复用 HA 共享 aiohttp session：`async_get_clientsession(hass)` | EZ1 的 config_flow 已这样写，Lake 客户端构造时注入同一个 session | 新代码不得出现 `aiohttp.ClientSession()` |
| 4 | 平台文件（sensor/number/switch/binary_sensor）**不得发起网络请求** | Lake 的所有请求收敛在 coordinator；实体只读 `coordinator.data` | 平台文件里只允许出现 `coordinator.data` 与写方法调用 |
| 5 | 每条配置条目必须用设备真实 ID 作 `unique_id`，并 `_abort_if_unique_id_configured()` | EZ1 用 `E07...`，Lake_6 用 `D00...`，天然不冲突 | 同型号同 IP 无法重复添加 |
| 6 | 新集成禁止 YAML 配置，必须 config_flow | 只改 flow，不新增 YAML 平台 | — |
| 7 | 用 `DataUpdateCoordinator` 轮询数据；首次刷新用 `async_config_entry_first_refresh()` | Lake 复用同一模式，保证失败时条目进入 `SETUP_RETRY` 并自动退避重试 | 拔网线后条目状态应为重试而非崩溃 |
| 8 | 实体名必须走翻译：`_attr_has_entity_name = True` + `_attr_translation_key` + `strings.json` | Lake 的每个实体 key 都要在 `strings.json` 的 `entity.<platform>` 下声明 | `strings.json` 与代码里的 translation_key 一一对齐 |
| 9 | 修改 `strings.json` 后必须重新生成翻译文件 | Core 环境：`python3 -m script.translations develop --integration apsystems`；自定义集成需手工维护 `translations/en.json` | 若走 custom_components 路线，**必须**提交 `translations/en.json`，否则实体名显示为裸 key |
| 10 | `unique_id` 一经发布不可更改 | Lake 的实体 key 在设计阶段一次定死（写进设计文档后再动手） | 代码评审时比对设计文档 |
| 11 | 实体 `unique_id` 全局唯一，建议 `<device_id>_<key>` | 沿用 EZ1 的拼法，Lake key 加前缀避免撞车（如 `lake_` 或语义化命名） | 实体注册表无重复 |
| 12 | 单位与状态类必须合规 | 功率 `SensorDeviceClass.POWER` + `MEASUREMENT`；电量 `ENERGY` + `TOTAL_INCREASING`；SOC 用 `BATTERY`；温度用 `TEMPERATURE` | 历史统计图表能正常生成、不出现"单位不符"告警 |
| 13 | 诊断类数据必须标 `EntityCategory.DIAGNOSTIC` | 告警位、RSSI、固件版本、设备温度 | 设备页能正确分组 |
| 14 | 异常必须映射成 `UpdateFailed`，并携带 `translation_domain` + `translation_key` | 复用 EZ1 的写法；Lake 的 `code != 200` 需映射为带翻译的错误 | 断连、设备返回错误码两种场景都能看到可读报错 |
| 15 | 设备信息统一走 `DeviceInfo` + `identifiers={(DOMAIN, device_id)}`，`model` 必须真实 | **现有 `entity.py` 写死 `model="EZ1-M"`，必须改为按设备类型传入** | Lake 设备页显示 Lake_6，EZ1 仍显示 EZ1-M |
| 16 | 严格类型检查：本项目 `.strict-typing` 已包含 `homeassistant.components.apsystems.*` | 新增代码必须能过 mypy strict：函数签名全注解、禁止裸 `Any`、返回值类型明确 | `uv run --no-sync mypy homeassistant/components/apsystems` |
| 17 | 代码风格走 Ruff（core 配置） | 遵循仓库 `pyproject.toml`，不新增被忽略规则 | `uv run --no-sync ruff check homeassistant/components/apsystems` |
| 18 | 测试要求：`MockConfigEntry` + syrupy 快照；测试函数参数必须有类型注解 | Lake 新增独立 fixture 与快照；**EZ1 现有 4 份 `.ambr` 不得产生任何 diff** | `git diff tests/components/apsystems` 中 `.ambr` 为空 |
| 19 | 敏感操作（改配置/有安全影响）在 Core 中需 admin 权限 | 本次只涉及实体写操作，无需注册 service，不触发该规则 | — |
| 20 | 集成支持的设备族差异过大时应保证老设备行为向后兼容 | 老条目 `entry.data` 中没有 `device_type` 字段，读取时必须 `default="ez1"`，**不升级 ConfigFlow `VERSION`、不写 migration** | 用真实 EZ1 老条目升级后功能与实体 ID 完全不变 |

---

## 二、本项目已确认的设计基线（方案 A）

### 2.1 配置流程：用户显式选择设备类型

- `config_flow` 的 user 表单新增字段：设备类型（`ez1` / `lake6`），必填，默认 `ez1`
- 端口默认值跟随类型：EZ1 → `8050`，Lake_6 → `80`；用户仍可手动覆盖
- 表单文案需按类型动态调整，删除"默认 8050 适用于大多数场景"这类只对 EZ1 成立的说法
- 校验方式：用对应类型的客户端读取设备 ID
  - `ez1`：`getDeviceInfo.deviceId`
  - `lake6`：`GET /devices` 的 `dev_id`
- 唯一 ID 直接使用设备 ID，天然区分两代产品
- 老条目兼容：读取时 `device_type = data.get("device_type", "ez1")`，`VERSION` 保持 `1`

### 2.2 为什么不做自动探测（本轮）

- 端口不同（80 / 8050），探测需多轮超时，最坏 16s 才失败
- EZ1 本地服务对未知路径的响应行为不确定，可能挂住而非快速 404
- 失败归因模糊：无法区分"网络不通"与"型号不支持"，不利于验收演示
- 测试组合从 4 种（2 类型 × 成功/失败）膨胀到 8 种以上

后续可作为纯增量功能叠加：`device_type` 改为可选，留空时走探测。

---

## 三、提交 / 验收前自检清单

代码层面：

- [ ] EZ1 相关文件（coordinator/sensor/binary_sensor/number/switch）除"按类型分支"外无逻辑改动
- [ ] `entity.py` 的 `model` 不再写死，EZ1 显示值不变
- [ ] 老配置条目无需 migration，`VERSION` 未变
- [ ] 所有新实体都有 `translation_key`，且 `strings.json` 已同步
- [ ] `translations/en.json` 已生成（自定义集成路线）
- [ ] Lake 写操作后 `coordinator.async_request_refresh()`，避免实体值滞后 12 秒
- [ ] 异常路径：断网、错误码、字段缺失三种情况都有可读日志

验证层面：

- [ ] `uv run --no-sync pytest tests/components/apsystems` 全绿
- [ ] EZ1 的 4 份 `.ambr` 快照零 diff
- [ ] 新增 Lake 的配置流 / 实体快照测试
- [ ] `uv run --no-sync mypy homeassistant/components/apsystems` 通过
- [ ] `uv run --no-sync ruff check homeassistant/components/apsystems` 通过

验收证据（给领导看的三件事）：

- [ ] **不破坏**：EZ1 老条目升级前后截图对比 + 快照零 diff + 测试全绿
- [ ] **读可用**：HA 实体值 与 局域网 `curl http://<ip>/devices|/energies|/alarms` 返回逐字段对照
- [ ] **写可用**：在 HA 改 `dod` / `mode` / `power_limit`，再 `curl GET /modes` 回读确认设备侧已变更

---

## 四、官方文档索引

- 集成清单与 manifest：`developers.home-assistant.io/docs/creating_integration_manifest`
- 配置流：`.../config_flow_index`、`.../config_entries_index`
- 数据获取（coordinator）：`.../integration_fetching_data`
- 实体平台：`.../creating_platform_index`、`.../entity_registry_index`
- 实体命名与翻译：`.../entity_translations`、`.../internationalization`
- 质量量表：`.../core/integration-quality-scale/rules`（Bronze → Platinum）
- 测试：`.../development_testing`、`.../creating_integration_tests`
