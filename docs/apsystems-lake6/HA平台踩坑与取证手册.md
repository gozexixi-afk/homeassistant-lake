# HA 平台踩坑与取证手册

- 用途：答辩速查 + 日常排障。每条坑固定三列：**现象 → 根因 → 正确做法**，编号「坑 N-M」便于口头引用与定位
- 适用基线：Home Assistant Core `2026.11`（仓库 HEAD `74cf5a49`），HAOS 容器内 Core 监听 **80** 端口
- 收录范围：仅收 **HA 平台自身行为**导致的坑；设备侧问题（如 EZ1 `status` 语义反转）不在此列
- 总纲：平台上"看起来不对"的现象，多数不是功能坏了，而是**取证方式错了**——读磁盘快照代替运行时视图、用命名子串代替注册表归属、用 HTTP 200 代替业务码、用单次检查代替分轮复查。下结论前先确认读的是不是权威数据源

---

## 速查索引（答辩定位用）

| 编号 | 一句话概括 | 定位关键词 |
|---|---|---|
| 坑 1-1 | 删实体后读注册表文件仍见旧行 | entity_registry 落盘延迟 |
| 坑 1-2 | 重启后立刻校验面板文件"消失" | 重启窗口期 |
| 坑 1-3 | restore_state 无记录 ≠ 没数据 | 陈旧快照 |
| 坑 1-4 | 读 config_entries 文件拿 state 恒 None | 静态字段 |
| 坑 1-5 | SQL 直读 recorder 得出错误结论 | attributes 去重 |
| 坑 2-1 | state 超 255 回退 unknown（静默） | MAX_LENGTH_STATE_STATE |
| 坑 2-2 | text 实体超长未注册，拖崩引用它的按钮 | 跨实体连锁 |
| 坑 3-1 | supported_features=0 不代表不可写 | 平台基类契约 |
| 坑 3-2 | entity_id 前缀/后缀过滤都会漏算 | slugify 拼音 |
| 坑 3-3 | 设备页排序由前端按显示名决定 | entity_category |
| 坑 4-1 | /auth/token 只收表单编码 | 400 误读 |
| 坑 4-2 | client_id 必须与 Host 一致 | indieauth |
| 坑 4-3 | config flow 入口已迁 REST | unknown_command |
| 坑 4-4 | custom_components 下备份目录被当集成 | loader domain |
| 坑 4-5 | docker logs 重启后查不到旧日志 | 容器切换 |
| 坑 4-6 | 实体/设备归属判定用错字段 | config_entry_id |
| 坑 5-1 | 属性变了自动化不触发 | state_changed 语义 |
| 坑 5-2 | 写后回读旧值：两层节流叠加 | debouncer + 缓存 |
| 坑 5-3 | 乐观更新绕过 coordinator 留假值 | 值不一致 |
| 坑 5-4 | 重构后脏标记无人置位的死分支 | 节流残留 |
| 坑 6-1 | 本机 Python 3.13 解析 HA 源码报错 | PEP 758 / 649 |

---

## 一、.storage 落盘时序类：磁盘快照 ≠ 运行态

共同特征：直接读 `.storage/` 下的 JSON 文件做判定，而 HA 注册表/存储落盘有延迟，导致系统性误判。

| 编号 | 现象 | 根因 | 正确做法 |
|---|---|---|---|
| 坑 1-1 | 删除条目/实体后 8 秒内读 `.storage/core.entity_registry`，全部旧行（实测 39 行）仍在 | 注册表落盘有延迟；`async_remove` 进程内已生效但文件还是上一版 | 分两轮复查：短延时看可见效果，长延时（或不重启的二次查询）再看注册表文件；两次不一致**以第二次为准** |
| 坑 1-2 | `ha core restart` 后立刻查 `.storage/lovelace.*`：文件消失、面板路由 404；几十秒后又出现且内容正常 | Core 启动阶段 LovelaceStorage 会重新落盘（先消失再写出）；storage 面板注册晚于"首页 200"这个可用判定 | 不以"文件在不在/路由 200"单点判定；等启动完成（轮询到内容可解析）再验收，且比对**配置内容**而非文件存在性；窗口期看到文件消失先复检一次，勿急着回滚 |
| 坑 1-3 | `core.restore_state` 里大量实体无状态记录 | 该文件是宿主重启时刻写的陈旧快照 | 不可用于判断集成是否在采集实时数据 |
| 坑 1-4 | 读 `.storage/core.config_entries` 取 `entry["state"]` 恒为 None，把正常条目误判异常 | 文件只存 `ConfigEntry.as_dict()` 静态字段（data/options/unique_id 等），**不含运行时 state** | 条目是 loaded / setup_retry / setup_error，只能 `GET /api/config/config_entries/entry` 读 |
| 坑 1-5 | SQL 直读 recorder：`states.state` 类型不可信；`unit_of_measurement=None` 假象 | ① state 列声明 TEXT，float/int 都以文本落盘；② 相同 attributes 后续行写 NULL（去重，完整属性只在 `state_attributes` 表一份） | 判类型读集成源码或看 statistics 能否算 mean；查属性要 `JOIN state_attributes`（向前回溯最近非 NULL 行）；判单位/state_class 是否生效的权威来源是 **`statistics_meta` 表**（unit_of_measurement、has_mean、has_sum） |

---

## 二、state 长度 255：双层卡点与跨实体连锁

本组是被坑最深的一组，且是跨实体连锁故障。

| 编号 | 现象 | 根因 | 正确做法 |
|---|---|---|---|
| 坑 2-1 | 把长 JSON 塞进 state，界面显示 unknown，日志仅一条 ERROR | `core.py` 的 `validate_state()`：state 超 `MAX_LENGTH_STATE_STATE = 255`（const.py）**整体回退 STATE_UNKNOWN**，不是截断 | 长结构化数据放 `extra_state_attributes`（不受限）；若必须用 text/sensor 展示长 JSON，需另存原始对象供写入路径绕过 state 上限。估算：分时配置单条约 50 字符，4 条逼近上限、5 条必 unknown |
| 坑 2-2 | 按 Confirm 按钮界面报 `'NoneType' object has no attribute 'loop'`，极易误读为"设备配置没写进去" | text 实体超长在 `async_add_entities` 阶段抛 ValueError（maximum length 255），实体**从未进入状态机**，`self.hass` 恒 None；但对象仍被 coordinator 的 staged 引用表持有。按钮 `async_press` 先 POST 成功（设备侧**已写入**），收尾 `schedule_update_ha_state()` 访问 None.hass 才崩。`if entity is not None` 判不出"未注册" | ①根修：TextEntity 子类设 `_attr_native_max_length`（如 4096）；②兜底：`clear_pending_data()` 里 `schedule_update_ha_state()` 包 `if self.hass is not None`。评审自定义集成时，凡被其它实体长期引用的实体，创建失败即崩溃引爆点 |

双层卡点链路（只放开一层都不够）：

- **服务层**：TextEntity 的 `native_max` 默认 255，服务调用时拦输入
- **状态机层**：`validate_state()` 超长抛 `InvalidStateError`，写状态处降级 unknown
- 项目落点：`lake6/const.py` 的 `LAKE6_TOU_TEXT_MAX_LENGTH = 255` 即取平台值，并按 `(255+1)//(每行最大长度+1)` 反算可容纳规则条数上限
- 注意 `_attr_native_max` 与 `_attr_native_max_length` 是 TextEntity 的**两个不同属性**，排查上限先看代码用的是哪个

---

## 三、平台契约认知类：registry 快照和命名都靠不住

| 编号 | 现象 | 根因 | 正确做法 |
|---|---|---|---|
| 坑 3-1 | number/select/text/time 实体 registry 里 `supported_features = 0`，误判"不可写"去加 EntityFeature | 这些平台基类已**不再使用** supported_features 标志位（TimeEntity 只定义 native_value + async_set_value） | 不靠 registry 判断可写性；核实平台契约读容器内 `/usr/src/homeassistant/homeassistant/components/<platform>/entity.py`，supported_features 只对 cover/climate/vacuum 等有标志的平台有意义 |
| 坑 3-2 | 按 entity_id 前缀过滤集成实体得到 0 个，误判"条目 setup 失败"；按后缀（`*_today_production`）定位也失败 | ①Lake_6 实体是 `sensor.lake_*`，不含 "apsystems"；②中文界面 entity_id 由翻译名 slugify 成拼音（`sensor.ban_gong_shi_...`），受语言与重名计数影响 | 锚定注册表 `unique_id = f"{device_id}_{description_key}"` 的后缀（device_id 前缀重建后不变，entity_id 可能整体改名）；断言失败首轮先打印 key→entity_id→state 对照表 |
| 坑 3-3 | 调整设备页实体顺序无效 | 官方设备页：板块归属由 `entity_category` 决定（diagnostic→诊断、config→配置、无→控制，板块顺序前端硬编码）；板块内按**本地化显示名拼音排序**，与注册表行序、创建顺序、unique_id、entity_id 全无关，且改翻译名立即改变排列 | 想完全自控顺序只能用自带 Lovelace entities 卡（顺序由数组决定）；`device_class=battery` 实体提升到标题栏电池徽标不占瓦片 |
| 坑 3-4 | 凭旧文档/推断判断平台行为出错 | 平台行为随版本迁移（如 TimeEntity 搬家、config flow 迁 REST） | 一律以容器内 `/usr/src/homeassistant/` 实读源码为准 |

---

## 四、容器内脚本化通道类：认证与调用细节

HAOS 容器内做条目级自动化验证时的静默误判（均实测）。

| 编号 | 现象 | 根因 | 正确做法 |
|---|---|---|---|
| 坑 4-1 | 用 JSON body 调 `/auth/token` 返回 400 `unsupported_grant_type`，误读为"token 失效" | 该端点只接受 `application/x-www-form-urlencoded` | urlencode 后 POST；client_id 取 refresh_token 记录里的原值 |
| 坑 4-2 | 换 token 返回 400 `invalid_request` | indieauth 校验 client_id 必须与请求 Host 一致 | 挑 client_id 与本机地址相同的记录，用 `http://192.168.1.113` 这类主机名发起；写死 127.0.0.1 被挡。`.storage/auth` 里 JWT 字段名是 `token` 不是 `refresh_token` |
| 坑 4-3 | websocket 发 `config_entries/flow` 返回 `unknown_command` | 本版本交互入口已从 websocket 迁到 HTTP REST，websocket 只剩 progress/subscribe | 程序化加集成：POST `/api/config/config_entries/flow`（handler 拿 flow_id）→ POST `.../flow/{flow_id}`（schema 字段），成功为 `create_entry` |
| 坑 4-4 | 真正的 config_flow 返回 404 `Invalid handler specified`，日志报 No module named 'custom_components.apsystems_storage.bak-...' | `custom_components` 下备份目录带点号（如 `apsystems_storage.bak-20261113`）被 loader 当集成 domain | 备份目录移出 `custom_components`（放 /config 根目录）后重启 |
| 坑 4-5 | restart 后排查面板创建日志查不到 | `ha core restart` 后 docker logs 换成新容器日志 | 排查日志在重启**前**抓 |
| 坑 4-6 | 审计残留：设备注册表条目 `config_entries` 为空判成"孤儿设备"，逐删全 404（假阳性）；按 entity_id 前缀统计整批漏算 | 设备注册表该字段为空不代表脱离条目；命名不含域名 | 判残留用**实体注册表**的 `config_entry_id` 是否落在存活 entry 集合内；判归属一律按 `platform`/`config_entry_id`，用 `/api/states` 交叉验证。另：Core 监听容器内 **80** 端口而非 8123 |

删除条目的正确通道与取证节奏：

- 建条目走配置流接口，**不要**直接编辑 `core.config_entries`（启动期初始化组件抢在自定义组件前崩溃，整份文件判非法）
- 删条目 `DELETE /api/config/config_entries/entry/{entry_id}`（需 admin），触发 `async_remove_entry` 钩子；钩子内 `async_entries(domain)` 只剩其它条目，可直接作判据
- 正向证据在删除**之前**取齐；先排除"需重启才生效"的干扰——效果只在重启后出现说明即时路径未通
- 收尾重建条目并重启复核跨重启一致性，清理临时脚本与备份目录

---

## 五、联动机制类：事件与刷新路径

| 编号 | 现象 | 根因 | 正确做法 |
|---|---|---|---|
| 坑 5-1 | 设备属性变了但自动化不触发 | `StateMachine.async_set()` 写入后只在 **state 字符串实际变化**时发 `EVENT_STATE_CHANGED`，仅改 attributes 不发事件 | 按属性联动必须把它提升为独立实体，或用 attribute 触发器；`unavailable`/`unknown` 也是合法 state，会命中 state 触发器 |
| 坑 5-2 | 写后 async_request_refresh "不奏效"，界面值回弹 | 两层节流叠加：coordinator debouncer（10s 冷却，IMMEDIATE）+ `/modes` 的 5 分钟缓存。防抖到期**确实执行了**，但拿回的还是旧快照；且全量 refresh 一次写入 = 1 POST + 3 GET，连点会把设备刷超时 | 写后单独 GET `/modes` + `coordinator.async_set_updated_data()`，靠 `always_update=False` 让 CoordinatorEntity 驱动回落 |
| 坑 5-3 | 界面值与设备实际值不一致 | 手写 `_attr_native_value` + `async_write_ha_state` 绕过 coordinator 的乐观更新留下假值 | 写路径统一经 coordinator，回读权威数据 |
| 坑 5-4 | 轮询节流逻辑永不生效 | 重构写后刷新时删掉了置脏链路，`_modes_dirty` 无人置位，形成死分支 | 审查轮询/缓存代码时专门查"每个标记变量还有没有写入方"；文档机制描述要与代码实际行为核对 |

联动机制的两个结构性事实（设计实体时就要遵守）：

- 脚本与自动化共用同一引擎，`SCRIPT_ACTION_*` 是硬编码常量表（helpers/config_validation.py，14 种），集成不可扩展
- 服务调用经 target 五种寻址（entity/device/area/floor/label）展开；集成侧只有"标准实体 + 约定命名方法"（async_turn_on / async_set_native_value 等）能被服务注册表匹配——新增能力优先暴露为标准实体而非自定义设备动作；协调器轮询间隔 = 联动最坏延迟

---

## 六、开发环境类：本机解释器版本

| 编号 | 现象 | 根因 | 正确做法 |
|---|---|---|---|
| 坑 6-1 | 本机 Python 3.13 对 `homeassistant/` 源码 `ast.parse`/`importlib` 报 `SyntaxError: multiple exception types must be parenthesized`，或 `NameError: 引用后定义的名字` | HA core 最低 Python 3.14：PEP 758 允许 `except A, B:` 无括号；PEP 649 注解懒求值可引用后定义名字。3.13 两者都不支持且注解立即求值 | 临时验证脚本：① `ast.parse` 前正则预处理 `^(\s*)except\s+([\w.]+(?:\s*,\s*[\w.]+)+)\s*:` → 加括号；② exec 集成模块前在源码头部前置 `from __future__ import annotations`。这段 shim **只在临时脚本里用，绝不进仓库** |

---

## 附：答辩引用速答

| 被问到 | 引哪条 |
|---|---|
| "你怎么确认实体真的删干净了？" | 坑 1-1 + 坑 4-6：注册表文件有落盘延迟，分两轮复查，以 config_entry_id 归属为准 |
| "界面上 unknown / 报错，是不是集成有 bug？" | 先分诊：坑 2-1（state 超限静默回退）还是坑 2-2（text 实体未注册的连锁崩溃）；设备侧可能已写入成功 |
| "为什么在 HA 里改了值又弹回去？" | 坑 5-2：两层节流，debouncer 执行了但 5 分钟缓存拿回旧值；修法是写后单独回读 + set_updated_data |
| "自动化为什么没触发？" | 坑 5-1：state 字符串没变不发事件，属性联动要提升为独立实体 |
| "容器里脚本调 API 为什么 400？" | 坑 4-1/4-2：表单编码 + client_id 对齐 Host |
| "本机跑校验为什么语法报错？" | 坑 6-1：HA 要 3.14，3.13 需 shim |
