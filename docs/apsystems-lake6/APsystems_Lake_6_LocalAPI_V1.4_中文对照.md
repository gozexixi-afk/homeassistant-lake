# APsystems Lake_6 LOCALAPI 用户手册（V1.4 中英对照 · V1.5.2 变更标注）

**原文标题**：APsystems Lake_6 LOCALAPI User Manual
**译文基线版本**：V1.4（2026/05/29）
**变更对照版本**：V1.5.2（2026/11/11）

> **阅读说明**
> 本文档按原文顺序逐节翻译。表格中同时保留英文字段原文与中文释义，便于对照查证；JSON 示例保持原文格式不做改动，可直接复制到 Apifox / Postman 调试。
> 原文中的疑点以 `译者注` 标注 —— 这些是翻译核对时发现的文档问题，**不一定是设备实际行为**，联调时需以实测为准。

> **V1.5.2 变更标注约定**
> 已逐节比对 V1.4 与 V1.5.2 原文，差异就地标注，标记含义：
> - 🗑️ **`[V1.5.1 删除]` / `[V1.5.2 删除]`** —— 新版已移除，原文以删除线保留，便于回溯旧固件行为
> - ➕ **`[V1.5.2 新增]`** —— 新版才出现的字段定义
> - ✏️ **`[V1.5.2 修改]`** —— 字段类型、格式或取值范围发生变化
> - ⚠️ **`[未声明变更]`** —— 原文实际已变，但版本记录里没写
>
> 全部变更汇总见文末 **附录 C**。

---

## 快速索引

| 编号 | 原文标题 | 中文 | 方法 | 路径 |
|---|---|---|---|---|
| 4.1 | Retrieving Basic Device Information | 获取设备基本信息 | GET | `/devices` |
| 4.2 | Retrieving Device Alarm Information | 获取设备告警信息 | GET | `/alarms` |
| 4.3 | Retrieving Device Energy Information | 获取设备能量信息 | GET | `/energies` |
| 4.4 | Retrieving Device Mode Configuration | 查询设备模式配置 | GET | `/modes` |
| 4.5 | Setting Device Mode Configuration | 设置设备模式配置 | POST | `/modes` |
| 4.6 | Retrieving Control Panel Configuration | 查询控制面板配置 | GET | `/control-panels` |
| 4.7 | Setting Control Panel Configuration | 设置控制面板配置 | POST | `/control-panels` |

**基址（Base URL）**：`http://{ip}:{port}`，`{port}` 默认 **80**

---

## 版本记录 / Version List

| 版本 / Version | 作者 / Author | 日期 / Date | 说明 / Description |
|---|---|---|---|
| V1.0 | APsystems | 2026/02/03 | 原文未填写 |
| V1.1 | APsystems | 2026/03/16 | 原文未填写 |
| V1.2 | APsystems | 2026/04/28 | 原文未填写 |
| V1.3 | APsystems | 2026/05/15 | 原文未填写 |
| V1.4 | APsystems | 2026/05/29 | 原文未填写 |
| V1.5 | APsystems | 2026/06/12 | 原文未填写 |
| **V1.5.1** | APsystems | 2026/08/31 | 🗑️ **Delete the `power_limit` parameter from the modes endpoint**<br>从 `/modes` 端点删除 `power_limit` 参数 |
| **V1.5.2** | APsystems | 2026/11/11 | 🗑️ **Delete the `backup_charP` parameter from the modes endpoint.**<br>➕ **Add descriptions for `GC` and `GD` to the modes endpoint.**<br>从 `/modes` 端点删除 `backup_charP` 参数；为 `/modes` 的 `GC`、`GD` 补充说明 |

> 译者注：
> 1. V1.0~V1.5 的 Description 列全为空，无法追溯变更。**V1.5.1 起官方开始填写变更说明**，但**仍不完整** —— 逐节比对后至少还有 4 处实际变更未在版本记录中声明，全部列在附录 C 的 `[未声明变更]` 条目下。
> 2. 本文基线仍是 V1.4，V1.5.2 的差异以标记叠加在原位、不做重排，便于看清「删了什么、改了什么」。

---

## 目录 / Table of Contents

| 章节 | 原文 | 中文 |
|---|---|---|
| 1 | Overview | 概述 |
| 2 | Communication Methods | 通信方式 |
| 3 | Data Format | 数据格式 |
| 4 | Related Interfaces | 相关接口 |
| 4.1 | Retrieving Basic Device Information(GET /devices) | 获取设备基本信息 |
| 4.2 | Retrieving Device Alarm Information(GET /alarms) | 获取设备告警信息 |
| 4.3 | Retrieving Device Energy Information(GET /energies) | 获取设备能量信息 |
| 4.4 | Retrieving DeviceMode Configuration(GET /modes) | 查询设备模式配置 |
| 4.5 | Setting Device Mode Configuration(POST /modes) | 设置设备模式配置 |
| 4.6 | Retrieving Control Panel Configuration(GET /control-panels) | 查询控制面板配置 |
| 4.7 | Setting Control Panel Configuration(POST /control-panels) | 设置控制面板配置 |

---

## 1. 概述 / Overview

> **原文**
> This document specifies the HTTP communication interface protocol for Lake_6.

**译文**：本文档规定了 Lake_6 的 HTTP 通信接口协议。

---

## 2. 通信方式 / Communication Methods

> **原文**
> Communication is based on the HTTP protocol:
> - The Lake_6 acts as an HTTP server.
> - The Lake_6 provides HTTP endpoints, which clients can actively request to retrieve or configure data.

**译文**：通信基于 HTTP 协议：

- Lake_6 作为 **HTTP 服务器** 运行。
- Lake_6 提供 HTTP 接口端点（endpoint），客户端可主动发起请求，以**读取**或**配置**数据。

> 译者注：即设备是被动方，所有交互都由客户端（如 Home Assistant、Apifox）主动发起，设备不会主动推送数据，实时性依赖客户端轮询。

---

## 3. 数据格式 / Data Format

### 3.1 请求数据 / Request Data

> **原文**
> Request Data: （附图为空白示意图，无可提取文本）

**译文**：请求数据：POST 接口使用 JSON 格式放在 HTTP 请求体中；GET 接口无请求体。

> 译者注：原文此处是一张图片，PDF 文本层无内容。由 4.5 / 4.7 两节可确认：写入类接口的请求体格式为 JSON。

### 3.2 响应数据 / Response Data

原文格式示例（保持原样）：

```json
{
    "data": {},
    "deviceId": "D00000000000",
    "code": 200,
    "message": "SUCCESS"
}
```

**字段对照**：

| 字段 / Field | 类型 / Type | 原文说明 | 中文释义 |
|---|---|---|---|
| `data` | JSON Object | Device returns valid data. | 设备返回的有效业务数据 |
| `deviceId` | string | Unique identifier assigned to the device. | 分配给设备的唯一标识 |
| `code` | number | Return Code. | 返回码（业务码） |
| `message` | string | SUCCESS or FAILED. | 成功或失败标识 |

**返回码 / Return Code**：

| code | 原文 | 中文 |
|---|---|---|
| 200 | Success | 成功 |
| 1001 | Data length error | 数据长度错误 |
| 1002 | Data format error | 数据格式错误 |
| 1003 | Internal error | 内部错误 |
| ~~1004~~ | ~~Internal error~~ | ~~内部错误~~ 🗑️ **`[V1.5.2 删除]`** |
| 2001 | Internal communication error | 内部通信错误 |

> 译者注（重要）：
> 1. `code` 是**业务返回码**，与 HTTP 状态码无关。设备可能返回 HTTP 200 而 `code` 为 1002，因此校验成功必须判断 `code == 200`，不能只看 HTTP 状态。
> 2. 原文中 1003 与 1004 的描述完全相同（均为 Internal error），疑似笔误，实际区分需实测。
> 3. 与同厂 EZ1 系列的信封 `{data, message, deviceId}` 相比，Lake_6 **新增了 `code` 字段**，两者结构不兼容。
> 4. ⚠️ **`[未声明变更]`** V1.5.2 的返回码表**只剩 5 个码，`1004` 已被移除**，但版本记录完全没有提及。原先「1003 与 1004 描述完全相同是否为笔误」的疑问由此有了新解释：官方直接把重复项删了。但**实现层不必随之删除 `1004`**：旧固件未升级前仍可能返回该码，保留映射只影响日志可读性，不影响成功判定（成功只看 `code == 200`）。文档口径为 5 个：200 / 1001 / 1002 / 1003 / 2001。

---

## 4. 相关接口 / Related Interfaces

### 4.1 获取设备基本信息 / Retrieving Basic Device Information（GET /devices）

| 项目 | 原文 | 译文 |
|---|---|---|
| API Endpoint | `GET http://{ip}:{port}/devices` | 接口地址：`GET http://{ip}:{port}/devices` |
| Request Method | GET | 请求方法：GET |
| Path | `/devices` | 路径：`/devices` |
| `{ip}` | IP address of the devices | 设备 IP 地址 |
| `{port}` | Service listening port (default is 80) | 服务监听端口（默认 80） |
| Example Request | `GET http://192.168.1.100:80/devices` | 示例请求 |

**示例响应 / Example Response Body（保持原样）**：

```json
{
    "data": {
        "dev_id": "D00000000000",
        "type": "EZHI SERIES",
        "dev_ver": "VERSION V1.0",
        "bat_cap": "0.00",
        "ssid": "MYSSID",
        "ip": "192.168.1.2",
        "rssi": -50
    },
    "deviceId": "D00000000000",
    "code": 200,
    "message": "SUCCESS"
}
```

**字段说明 / Field Description**：

| 字段 / Field | 类型 / Type | 原文说明 | 中文释义 |
|---|---|---|---|
| `dev_id` | string | Unique identifier assigned to the device. | 设备唯一标识（应与信封中的 `deviceId` 一致） |
| `type` | string | Device type. | 设备类型 / 型号，如 `EZHI SERIES` |
| `dev_ver` | string | Firmware version running on the device. | 设备当前运行的固件版本 |
| `bat_cap` | string | Battery Capacity. | 电池容量 |
| `ssid` | string | Name of the Wi-Fi network to which the device is currently connected. | 设备当前连接的 Wi-Fi 网络名称 |
| `ip` | string | IPv4 address assigned to the device on the local network. | 设备在局域网中被分配的 IPv4 地址 |
| `rssi` | **number** ✏️ | Received Signal Strength Indicator in dBm. | 接收信号强度指示值（RSSI），单位 dBm |

> 译者注：
> 1. ✏️ **`[V1.5.2 修改]`** `rssi` 的类型**由 `string` 改为 `number`**，示例值 `-50` 终于与类型自洽 —— 这处长期存在的文档矛盾已被官方修正。<br>**但解析层仍必须同时兼容 string / number**：V1.4 及更早的固件按 string 输出，旧设备升级前依旧会走另一条分支，直接改强类型仍会打死老设备。
> 2. `dev_ver` 的格式为「前缀 + 空格 + 版本号」（如 `VERSION V1.0`），提取纯版本号应按下标取最后一段。
> 3. `bat_cap` 原文未标注单位。

---

### 4.2 获取设备告警信息 / Retrieving Device Alarm Information（GET /alarms）

| 项目 | 原文 | 译文 |
|---|---|---|
| API Endpoint | `GET http://{ip}:{port}/alarms` | 接口地址 |
| Request Method | GET | 请求方法：GET |
| Path | `/alarms` | 路径：`/alarms` |
| `{port}` | Service listening port (default is 80) | 服务监听端口（默认 80） |
| Example Request | `GET http://192.168.1.100:80/alarms` | 示例请求 |

**示例响应 / Example Response Body**：

```json
{
    "data": {
        "bat_overtemp": "0",
        "bat_undertemp": "0",
        "bat_comm_err": "0",
        "bat_overvolt": "0",
        "bat_undervolt": "0",
        "bat_overcur": "0",
        "bat_ie": "0",
        "dev_temp": "0",
        "dev_sys_err": "0",
        "bat_shutdown": "0",
        "grid_anomaly": "0",
        "offgrid_overcur": "0",
        "offgrid_shortcir": "0",
        "bat_cal": "0"
    },
    "deviceId": "D00000000000",
    "code": 200,
    "message": "SUCCESS"
}
```

> 译者注：原文示例中 `"bat_cal": "0",` 后带一个**多余逗号**，属于非法 JSON，直接复制会解析失败。上方已移除该逗号，仅此一处改动。

**通用规则 / General Rules**：

| 原文 | 中文 |
|---|---|
| All returned fields are of type string. | 所有返回字段均为 string 类型。 |
| "0" indicates normal status. | `"0"` 表示正常状态。 |
| "1" indicates abnormal status. | `"1"` 表示异常状态。 |

**字段说明 / Field Description**（共 14 项，取值均为 `"0"` / `"1"`）：

| 字段 / Field | 类型 / Type | 原文说明 | 中文释义 |
|---|---|---|---|
| `bat_overtemp` | string | Battery High Temperature Alarm. | 电池高温告警 |
| `bat_undertemp` | string | Battery Low Temperature Alarm. | 电池低温告警 |
| `bat_comm_err` | string | Battery Communication Error Alarm. | 电池通信错误告警 |
| `bat_overvolt` | string | Battery Overvoltage Alarm. | 电池过压告警 |
| `bat_undervolt` | string | Battery Undervoltage Alarm. | 电池欠压告警 |
| `bat_overcur` | string | Battery Overcurrent Alarm. | 电池过流告警 |
| `bat_ie` | string | Battery Internal Error Alarm. | 电池内部错误告警 |
| `dev_temp` | string | Device Temperature Protection Alarm. | 设备温度保护告警 |
| `dev_sys_err` | string | Device System Error Alarm. | 设备系统错误告警 |
| `bat_shutdown` | string | Battery Shutdown Alarm. | 电池关机告警 |
| `grid_anomaly` | string | Grid Abnormal Alarm. | 电网异常告警 |
| `offgrid_overcur` | string | Off-grid Side Overcurrent Alarm. | 离网侧过流告警 |
| `offgrid_shortcir` | string | Off-grid Side Short Circuit Alarm. | 离网侧短路告警 |
| `bat_cal` | string | Battery Capacity Calibration. | 电池容量校准 |

> 译者注：`dev_temp` 在本接口中是**告警标志位**（0/1），但在 4.3 `/energies` 中表示**实际温度数值**（°C），同名不同义，映射实体时切勿混用。

---

### 4.3 获取设备能量信息 / Retrieving Device Energy Information（GET /energies）

| 项目 | 原文 | 译文 |
|---|---|---|
| API Endpoint | `GET http://{ip}:{port}/energies` | 接口地址 |
| Request Method | GET | 请求方法：GET |
| Path | `/energies` | 路径：`/energies` |
| `{port}` | Service listening port (default is 80) | 服务监听端口（默认 80） |
| Example Request | `GET http://192.168.1.100:80/energies` | 示例请求 |

**示例响应 / Example Response Body**：

```json
{
    "data": {
        "bat_soc": "0.0",
        "bat_temp": "0.0",
        "dev_temp": "0.0",
        "bat_impE": "0.0000",
        "bat_expE": "0.0000",
        "ongrid_expE": "0.0000",
        "ongrid_impE": "0.0000",
        "offgrid_expE": "0.0000",
        "offgrid_impE": "0.0000",
        "bat_power": "0",
        "ongrid_power": "0",
        "offgrid_power": "0",
        "bat_status": "1"
    },
    "deviceId": "D00000000000",
    "code": 200,
    "message": "SUCCESS"
}
```

> 译者注（重要）：
> 1. 原文示例中 `ongrid_impE`、`offgrid_expE`、`offgrid_impE` 三个键名**末尾带空格**（`"ongrid_impE "`）。若为真实报文而非排版错误，按无空格键名取值将永远取不到。上方为便于使用已去掉空格，**实测时请打印原始 JSON 的 `keys()` 确认**。
> 2. 原文示例中 `"bat_status": "1",` 后带**多余逗号**，属非法 JSON，已移除。

**字段说明 / Field Description**：

| 字段 / Field | 类型 / Type | 原文说明 | 中文释义 |
|---|---|---|---|
| `bat_soc` | string | Battery Status of Charge. Unit: %. | 电池荷电状态（SOC），单位 % |
| `bat_temp` | string | Battery Temperature. Unit: °C. | 电池温度，单位 °C |
| `dev_temp` | string | Device Temperature. Unit: °C. | 设备温度，单位 °C |
| `bat_impE` | string | Battery Accumulated Charge Energy. Unit: kWh. | 电池累计充电电量，单位 kWh |
| `bat_expE` | string | Battery Accumulated Discharge Energy. Unit: kWh. | 电池累计放电电量，单位 kWh |
| `ongrid_expE` | string | On-grid Side Accumulated Output Energy. Unit: kWh. | 并网侧累计输出电量，单位 kWh |
| `ongrid_impE` | string | On-grid Side Accumulated Input Energy. Unit: kWh. | 并网侧累计输入电量，单位 kWh |
| `offgrid_expE` | string | Off-grid Side Accumulated Output Energy. Unit: kWh. | 离网侧累计输出电量，单位 kWh |
| `offgrid_impE` | string | Off-grid Side Accumulated Input Energy. Unit: kWh. | 离网侧累计输入电量，单位 kWh |
| `bat_power` | string | Battery Side Power. Unit: W. | 电池侧功率，单位 W |
| `ongrid_power` | string | On-grid Side Power. Unit: W. | 并网侧功率，单位 W |
| `offgrid_power` | string | Off-grid Side Power. Unit: W. | 离网侧功率，单位 W |
| `bat_status` | string | Battery Status. | 电池状态，取值见下表 |

**`bat_status` 枚举 / Battery Status Enum**：

| 值 | 原文 | 中文 |
|---|---|---|
| `"1"` | IDLE | 空闲 |
| `"2"` | CHARGING | 充电中 |
| `"3"` | DISCHARGING | 放电中 |
| `"4"` | FAULT | 故障 |
| `"5"` | SHUTDOWN | 关机 |
| `"6"` | NO COMMUNICATION | 无通信 |
| `"7"` | HEATING | 加热中 |

> 译者注：本接口混装了**瞬时量**（`*_power`，单位 W）与**累计量**（`*_impE` / `*_expE`，单位 kWh）两类语义，做数据采集接入时需分别对待：功率类为瞬时测量值，电量类为单调递增的累计值。

---

### 4.4 查询设备模式配置 / Retrieving Device Mode Configuration（GET /modes）

| 项目 | 原文 | 译文 |
|---|---|---|
| API Endpoint | `GET http://{ipAddr}:{port}/modes` | 接口地址 |
| Request Method | GET | 请求方法：GET |
| Path | `/modes` | 路径：`/modes` |
| `{ip}` | IP address of the device | 设备 IP 地址 |
| `{port}` | Service listening port (default is 80) | 服务监听端口（默认 80） |
| Example Request | `GET http://192.168.1.100:80/modes` | 示例请求 |

**示例响应 / Example Response Body（保持原样）**：

```json
{
    "data": {
        "mode": "0",
        "eco": "0",
        "offgrid_on": "0",
        "time_cfg": [],
        "dod": "0"
    },
    "deviceId": "D00000000000",
    "code": 200,
    "message": "SUCCESS"
}
```

> 🗑️ **V1.5.1 / V1.5.2 删除字段（本节）** —— 上方示例已按 V1.5.2 移除以下两行，V1.4 原文中它们确实存在：
>
> | 被删字段 | V1.4 原值 | 删除版本 |
> |---|---|---|
> | `"power_limit": "0",` | 并网侧输出功率上限，单位 W | **V1.5.1** |
> | `"backup_charP": "0",` | 备电模式充电功率，单位 W | **V1.5.2** |
>
> **影响**：这两项已从 `/modes` 协议中彻底移除，不应再作为可读/可写实体暴露。若固件仍下发它们，属**未定义字段**，解析时忽略即可，**切勿据此建立实体** —— 否则一旦固件彻底移除，实体将永久 `unknown`。

**字段说明 / Field Description**：

| 字段 / Field | 类型 / Type | 原文说明 | 中文释义 |
|---|---|---|---|
| `mode` | string | Device Operating Mode. | 设备运行模式，取值见下表 |
| `eco` | string | Economy Mode. "0": Disable; "1": Enable; | 经济模式：`"0"` 禁用，`"1"` 启用 |
| `offgrid_on` | string | Off-grid Power Switch. (Takes effect only in off-grid status; remains constantly enabled in grid-tied mode) "0": Turn off; "1": Turn on; | 离网输出开关：`"0"` 关闭，`"1"` 开启。<br>仅在**离网状态**下生效；并网模式下该开关始终保持开启 |
| ~~`power_limit`~~ | ~~string~~ | ~~On-grid Side Output Power Limit. Unit: W.~~ | ~~并网侧输出功率上限，单位 W~~ 🗑️ **`[V1.5.1 删除]`** |
| `time_cfg` | JSON List | Time-of-Use Mode Configuration. This setting only takes effect in Mode 3. | 分时电价模式配置。<br>**仅在 mode=3 时生效** |
| ~~`backup_charP`~~ | ~~string~~ | ~~Charge power in backup mode. Unit: W.~~ | ~~备电模式下的充电功率，单位 W~~ 🗑️ **`[V1.5.2 删除]`** |
| `dod` | string | Depth of Discharge. Unit: %. | 放电深度（DOD），单位 % |

**`mode` 枚举 / Operating Mode**：

| 值 | 原文 | 中文 |
|---|---|---|
| `"1"` | AI Mode; This configuration does not take effect here. Please proceed to the app for relevant settings. | AI 模式。**该配置在此处不生效**，需到 App 中进行相关设置 |
| `"2"` | Self-consumption Mode (Default) | 自消耗模式（默认） |
| `"3"` | Time-of-Use Mode | 分时电价模式（TOU） |
| `"4"` | Backup Mode | 备电模式 |

> 译者注：`dod` 不要按字面译成“放电深度”，也不要用它建显示名。实测与产品侧确认，该值的语义是**备电模式下电池允许放电到的 SOC 下限**（产品称 backupSoc），**数值越大越保守**，与通常意义的“Depth of Discharge”方向相反。实体显示名用 Backup SOC，否则会出现“文档叫放电深度、界面叫备电 SOC”的对不上。

---

### 4.5 设置设备模式配置 / Setting Device Mode Configuration（POST /modes）

| 项目 | 原文 | 译文 |
|---|---|---|
| API Endpoint | `POST http://{ip}:{port}/modes` | 接口地址 |
| Request Method | POST | 请求方法：POST |
| Path | `/modes` | 路径：`/modes` |
| `{port}` | Service listening port (default is 80) | 服务监听端口（默认 80） |

**数据要求 / Data Requirements**：

| 原文 | 中文 |
|---|---|
| Location: HTTP POST request body; | 位置：HTTP POST 请求体 |
| Format: JSON; | 格式：JSON |

**参数说明 / Parameters Description**：

| 参数 / Parameter | 类型 / Type | 原文说明 | 中文释义 |
|---|---|---|---|
| `mode` | string | Device Operating Mode.<br>"1": AI Mode (This configuration does not take effect here. Please proceed to the app for relevant settings.);<br>"2": Self-consumption Mode;<br>"3": Time-of-Use Mode;<br>"4": Backup Mode;<br>(Optional if unchanged.) | 设备运行模式。<br>`"1"` AI 模式（此处不生效，需到 App 设置）；`"2"` 自消耗模式；`"3"` 分时电价模式；`"4"` 备电模式。<br>**不修改时可省略** |
| `eco` | string | Economy Mode.<br>"0": Disable; "1": Enable;<br>(Optional if unchanged.) | 经济模式：`"0"` 禁用，`"1"` 启用。<br>不修改时可省略 |
| `offgrid_on` | string | Off-grid Power Switch.<br>"0": Turn off; "1": Turn on;<br>(Takes effect only in off-grid status; remains constantly enabled in grid-tied mode)<br>(Optional if unchanged.) | 离网输出开关：`"0"` 关闭，`"1"` 开启。<br>仅在离网状态下生效，并网模式恒开。<br>不修改时可省略 |
| ~~`power_limit`~~ | ~~string~~ | ~~On-grid Side Output Power Limit. Unit: W.<br>The setting range is from 0 to 2500W.<br>(Optional if unchanged.)~~ | ~~并网侧输出功率上限，单位 W。<br>**设置范围：0 ~ 2500W**。<br>不修改时可省略~~ 🗑️ **`[V1.5.1 删除]`** |
| `time_cfg` | JSON Array | Refer to time_cfg for details.<br>This setting only takes effect in Mode 3.<br>(Optional if unchanged.) | 分时配置，结构见下方 time_cfg。<br>仅在 mode=3 时生效。<br>不修改时可省略 |
| ~~`backup_charP`~~ | ~~string~~ | ~~Charge power in backup mode. Unit: W.<br>Effective only in backup mode.~~ | ~~备电模式充电功率，单位 W。<br>仅在备电模式下有效~~ 🗑️ **`[V1.5.2 删除]`** |
| `dod` | string | Depth of Discharge. Unit: %.<br>The setting range is from 15 to 90%.<br>(Optional if unchanged.) | 放电深度，单位 %。<br>**设置范围：15 ~ 90%**。<br>不修改时可省略 |

**`time_cfg` 结构**（仅在 mode=3「分时电价模式」下生效）：

| 参数 | 类型 | 原文说明 | 中文释义 |
|---|---|---|---|
| `E` | string | Enable Time-of-Use Control.<br>"0": DISABLE; "1": ENABLE; | 是否启用分时控制：`"0"` 禁用，`"1"` 启用 |
| `W` | JSON_Array | Effective days of the week.<br>Numbers represent enabled days of the week.<br>For example, `[1,2,3,4,5,6,7]` represents Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, and Sunday. | 生效星期。<br>数字表示周几，如 `[1,2,3,4,5,6,7]` 表示周一到周日 |
| `TM` | JSON_Array | Refer to TM for details. | 时间段列表，结构见下方 TM |

**`TM` 结构**：

| 参数 | 类型 | 原文说明 | 中文释义 |
|---|---|---|---|
| `T` | string | Time slot.<br>Format: HHMMHHMM (24-hour format).<br>Start time and end time must be within the same day (no cross-day). | 时间段。<br>格式 `HHMMHHMM`（24 小时制）。<br>**起止时间必须在同一天内，不可跨天** |
| `F` | string | Execution Function.<br>"1": CHARGE;<br>"2": DISCHARGE;<br>"3": Self-consumption Mode (same as mode 2); | 执行功能：<br>`"1"` 充电；`"2"` 放电；`"3"` 自消耗模式（等同 mode 2） |
| `FI` | JSON_Object | Execution Parameter Configuration.<br>Refer to FI for details. | 执行参数配置，结构见下方 FI |

**`FI` 结构**：

| 参数 | 类型 | 原文说明 | 中文释义 |
|---|---|---|---|
| `P` | string | Charge/Discharge Power.<br>TM-F="1": Charge power (Range: 0-2500W).<br>TM-F="2": Discharge power (Range: 0-2500W). If power_limit is less than 2500W, the actual effective discharge power will be limited to power_limit.<br>TM-F="3": Power value is not applicable. | 充电/放电功率（字符串）。<br>当 `F="1"`：充电功率（范围 0-2500W）。<br>当 `F="2"`：放电功率（范围 0-2500W）；**若 `power_limit` 小于 2500W，实际放电功率会被限制到 `power_limit`**。<br>当 `F="3"`：该功率值不适用 |
| `GC` | number | ➕ **`[V1.5.2 新增]`** Grid Charge Permit (applicable only when F = 1).<br>Specifies whether charging from the grid is allowed during the charging time window.<br>0 = PV charging only; grid charging is not allowed<br>1 = Grid charging is allowed<br>**Note: This field is forced to 1 in firmware; the configured value has no effect.** | 电网充电许可（**仅 `F="1"` 时适用**）。<br>指定充电时段内是否允许从电网充电：<br>`0` = 仅光伏充电，不允许电网充电；<br>`1` = 允许电网充电。<br>**注意：固件中强制为 1，配置值无效。** |
| `GD` | number | ➕ **`[V1.5.2 新增]`** Battery-to-Grid Discharge Permit (applicable only when F = 2).<br>Specifies whether discharging the battery to the grid is allowed during the discharge time window.<br>0 = Battery discharge to the grid is not allowed<br>1 = Battery discharge to the grid is allowed<br>**Note: This field is forced to 1 in firmware; the configured value has no effect.** | 电池向电网放电许可（**仅 `F="2"` 时适用**）。<br>指定放电时段内是否允许电池向电网放电：<br>`0` = 不允许电池向电网放电；<br>`1` = 允许电池向电网放电。<br>**注意：固件中强制为 1，配置值无效。** |

> ➕ **`[V1.5.2 新增]`**：`GC` / `GD` 是本次新增定义的字段，V1.4 原文完全没有。
>
> **这两个字段解释了长期存在的疑点**：实测 `time_cfg[].FI` 中多出一个文档未定义的 `GC: 1`，曾被视为「固件多写了未定义字段」。现在官方确认：`GC` / `GD` 是**真实存在的协议字段**，只是 V1.4 漏写了定义。
>
> ⚠️ **且官方明确声明：两者在固件中被强制为 `1`，写入值不生效**。这意味着：
> 1. **不应将它们暴露为可配置实体**，否则会做出一个「能改但改了没用」的无效控件；
> 2. 回传 `time_cfg` 时携带它们**无害但也无用**，因为设备会忽略；
> 3. 读取时必须**容忍其存在**（类型为 `number`，不是 `string`），不可因多出未知键而报错。
>
> ⚠️ **残留矛盾**：V1.5.2 虽已删除 `power_limit`，但上方 `P` 的描述中**依旧引用 `power_limit`**（“若 power_limit 小于 2500W…”）。这是文档内部遗留未清理的表述，当前协议下 `power_limit` 已不存在，该限制条件应视为**失效**，需实测确认放电功率是否仍存在上限。

#### 设置示例 / Setting Device Mode Example

**① 设为自消耗模式 / Set the device mode to 2 (Self-consumption Mode)**

```json
{
"mode": "2",
"eco": "0",
"offgrid_on": "0",
"dod": "20"
}
```

| 原文 | 中文 |
|---|---|
| Set the device mode to 2 (Self-consumption Mode). | 将设备模式设为 2（自消耗模式） |
| Disable Economy Mode. | 关闭经济模式 |
| Turn off the off-grid power switch. | 关闭离网输出开关 |
| Set the Depth of Discharge to 20%. | 将放电深度设为 20% |

**② 设为分时电价模式 / Set the device mode to 3 (Time-of-Use Mode)**

```json
{
"mode": "3",
"time_cfg": [
{
   "E": "1",
   "W": [1,2],
   "TM": [
      {
        "F": "1",
        "T": "12001300",
        "FI": {
          "P": "100"
        }
      }
   ]
}
]
}
```

| 原文 | 中文 |
|---|---|
| Set the device mode to 3 (Time-of-Use Mode). | 将设备模式设为 3（分时电价模式） |
| Enable the time policy to charge the device at 100W from 12:00 to 13:00 on Mondays and Tuesdays. | 启用分时策略：每周一、周二 12:00 至 13:00 以 100W 功率为设备充电 |

**③ 设为备电模式 / Set the device mode to 4 (Backup Mode)**

```json
{
"mode": "4"
}
```

| 原文 | 中文 |
|---|---|
| Set the device mode to 4 (Backup Mode). | 将设备模式设为 4（备电模式） |
| ~~Set the charge power to 2500W in backup mode.~~ | ~~将备电模式充电功率设为 2500W~~ 🗑️ **`[V1.5.2 删除]`** |

> 🗑️ **`[V1.5.2 删除]`**：V1.4 本示例为 `{"mode": "4", "backup_charP": "2500"}`，V1.5.2 已去掉 `backup_charP`，**备电模式下已无法通过本地 API 指定充电功率**。
> 若仍需配置该值，只能去 App 侧操作 —— 这与 4.4 `mode=1`（AI 模式）需回 App 设置属于同类限制。

> 译者注：
> 1. `T` 是 8 位纯数字 `HHMMHHMM`，如 `"12001300"` 表示 12:00→13:00，**不含日期、不可跨天**（`"23000100"` 属于非法输入）。
> 2. 所有功率、开关、放电深度字段均为 **string**，传入数字可能触发 `code=1002`（数据格式错误）。
> 3. `mode="1"`（AI 模式）在本接口下发**不生效**，不应作为可写选项暴露给用户。

---

### 4.6 查询控制面板配置 / Retrieving Control Panel Configuration（GET /control-panels）

| 项目 | 原文 | 译文 |
|---|---|---|
| API Endpoint | `GET http://{ipAddr}:{port}/control-panels` | 接口地址 |
| Request Method | GET | 请求方法：GET |
| Path | `/control-panels` | 路径：`/control-panels` |
| `{ip}` | IP address of the device | 设备 IP 地址 |
| `{port}` | Service listening port (default is 80) | 服务监听端口（默认 80） |
| Example Request | `GET http://192.168.1.100:80/control-panels` | 示例请求 |

**示例响应 / Example Response Body**：

```json
{
    "data": {
        "mode": "0",
        "MI1": {}
    },
    "deviceId": "D00000000000",
    "code": 200,
    "message": "SUCCESS"
}
```

**字段说明 / Field Description**：

| 字段 / Field | 类型 / Type | 原文说明 | 中文释义 |
|---|---|---|---|
| `mode` | string | Control Panel Operating Status.<br>"0": Configuration Cleared / No Configuration;<br>"1": Single Configuration; Single run in progress, automatically clears configuration upon completion. This mode has the highest priority, overrides other modes, and restores them upon completion. | 控制面板运行状态。<br>`"0"` 配置已清除 / 无配置；<br>`"1"` 单次配置：一次性任务执行中，完成后**自动清除配置**。<br>**该模式优先级最高**，执行期间会覆盖其他模式，完成后自动恢复 |
| `MI1` | JSON Object | Control Panel Operating Configuration. | 控制面板运行配置，结构见 4.7 |

---

### 4.7 设置控制面板配置 / Setting Control Panel Configuration（POST /control-panels）

| 项目 | 原文 | 译文 |
|---|---|---|
| API Endpoint | `POST http://{ip}:{port}/control-panels` | 接口地址 |
| Request Method | POST | 请求方法：POST |
| Path | `/control-panels` | 路径：`/control-panels` |
| `{port}` | Service listening port (default is 80) | 服务监听端口（默认 80） |

**数据要求 / Data Requirements**：

| 原文 | 中文 |
|---|---|
| Location: HTTP POST request body; | 位置：HTTP POST 请求体 |
| Format: JSON; | 格式：JSON |

**参数说明 / Parameters Description**：

| 参数 | 类型 | 原文说明 | 中文释义 |
|---|---|---|---|
| `mode` | string | Control Panel Operating Status.<br>"0": Configuration Cleared / No Configuration;<br>"1": Single Configuration; | 控制面板运行状态：<br>`"0"` 清除配置 / 无配置；<br>`"1"` 下发单次配置 |
| `MI1` | JSON Object | Refer to MI1 for details. | 运行配置详情，结构见下方 MI1 |

**`MI1` 结构**：

| 参数 | 类型 | 原文说明 | 中文释义 |
|---|---|---|---|
| `time` | JSON Array | ✏️ **`[V1.5.2 修改]`** Time slot.<br>Format: **YYYYMMDDHHMMSSYYYYMMDDHHMMSS** (24-hour format).<br>For Example, `["2026010110000020260101150000"]` represents a start time of January 1, 2026 at 10:00:00 and an end time of January 1, 2026 at 15:00:00. | 时间段，**字符串数组**。<br>格式：**`YYYYMMDDHHMMSSYYYYMMDDHHMMSS`**（带**秒**，起止各 14 位，共 **28 位**，首尾相接、无分隔符）。<br>示例 `["2026010110000020260101150000"]` 表示 2026-01-01 10:00:00 至 15:00:00 |
| `power` | JSON Array | Power array.<br>Operating power for the corresponding time slot.<br>Positive values indicate discharging. Negative values indicate charging. 0 indicates standby. Unit: W.<br>For example, `["-200"]` represents the device charges at 200W during the corresponding time slot. | 功率数组，与 `time` **按下标一一对应**。<br>**正值 = 放电，负值 = 充电，0 = 待机**，单位 W。<br>示例 `["-200"]` 表示设备在对应时段以 200W 充电 |

#### 设置示例 / Set Control Panel Example

```json
{
    "mode": "1",
    "MI1": {
        "time": [
            "2026010110000020260101150000",
            "2026010210000020260102150000"
        ],
        "power": [
            "500",
            "-200"
        ]
    }
}
```

> ✏️ **`[V1.5.2 修改] · ⚠️ `[未声明变更]`**：`MI1.time` 的时间串格式**从 24 位（`YYYYMMDDHHMM` ×2）改为 28 位（`YYYYMMDDHHMMSS` ×2），增加了「秒」**。
>
> | | V1.4 示例 | V1.5.2 示例 |
> |---|---|---|
> | 值 | `202601011000202601011500` | `2026010110000020260101150000` |
> | 位数 | 24 | **28** |
> | 含义 | 2026-01-01 10:00 → 15:00 | 2026-01-01 **10:00:00** → **15:00:00** |
> | 拆分 | `YYYYMMDDHHMM` + `YYYYMMDDHHMM` | `YYYYMMDDHHMM`**`SS`** + `YYYYMMDDHHMM`**`SS`** |
>
> ⚠️ **这处变更版本记录里根本没提**，却是一个**破坏性变更**。实测结果比“报错”更难处理：位数不符时设备**仍返回 `code=200`，但把 `MI1` 清空、`mode` 留在 `"0"`**——不报错，而是静默丢弃。因此不能靠返回码判断成败，必须在 POST 后回读 `mode` 确认（见本节末“实测补充”）。
>
> 注意：V1.5.2 把旧示例的 `20260101100020...`（末尾 `20`）改成了 `20260101100000...`（末尾 `0000`），说明旧示例本身就不是合法时间串（`10:00 20 秒`无法成立），新格式才让它自洽。

| 原文 | 中文 |
|---|---|
| Enable a one-time operation: discharge at 500W from 10:00 to 15:00 on Jan 1, 2026, and charge at 200W from 10:00 to 15:00 on Jan 2, 2026. | 启用一次性操作：2026 年 1 月 1 日 10:00-15:00 以 500W 放电；2026 年 1 月 2 日 10:00-15:00 以 200W 充电 |

> 译者注：
> 1. 原文写 `(24-hour format)` 指的是**24 小时制**，而格式串 `YYYYMMDDHHMMYYYYMMDDHHMM` 恰好也是 **24 位字符**，两者容易混淆，注意区分。
> 2. `time` 与 `power` 是**两个平行数组**，必须等长且下标对应。长度不一致会导致时间窗与功率错配。
> 3. `power` 的正负号语义与常识相反（**负数为充电**），是最容易写反的地方。
> 4. 本接口下发的是**一次性任务**，优先级最高，会临时覆盖 `/modes` 的长期策略，执行完自动恢复。
> 5. `mode="1"` 时 `MI1` 必填；`mode="0"` 时 `MI1` 传空对象即可。

#### 实测补充（文档未载，需以实机为准）

| # | 结论 | 依据与影响 |
|---|---|---|
| 1 | **GET `/control-panels` 的响应信封缺 `code`**（3.2 把它列为通用字段，4.6 示例里也带了 `code`，但实际响应没有） | 与接口负责人确认“只有该端点没有”。判定成功只能回退 `message == "SUCCESS"`；其余四个端点缺 `code` 必须按失败处理，避免残缺响应被当成成功 |
| 2 | **`MI1.time` 按 UTC 解释** | 写本地时间（UTC+8）同样返回 `code=200`，但 `mode` 不变、`MI1` 被清空。下发前必须先把起止时刻转 UTC |
| 3 | **起点必须早于设备自己的 RTC** | 起点等于或晚于设备时钟（哪怕只晚 1 秒），返回 200 后静默丢弃。实测把起点回退 10 秒即稳定生效；结束时刻仍取“现在 + 时长”，实际执行长度不缩水 |
| 4 | 下发后需停一拍再回读（约 1 秒） | 设备把 `mode` 置 `"1"` 不是同步完成的，立刻回读会把刚写入的任务当成没生效 |
| 5 | 单条规则实测只有一个时段 | 文档未声明能否多段；实测每条 `TM` 恒为一段，多个时段拆成多条规则 |

---

## 附录 A：原文疑点汇总

以下为翻译核对时发现的原文问题，**均需以设备实测为准**：

| # | 位置 | 问题 | 影响 | 建议处理 |
|---|---|---|---|---|
| 1 | 4.2 示例 | `"bat_cal": "0",` 后有多余逗号 | 非法 JSON，复制即解析失败 | 已在本译文中移除 |
| 2 | 4.3 示例 | `ongrid_impE ` / `offgrid_expE ` / `offgrid_impE ` 键名末尾带空格 | 若为真实报文，按无空格键名取值永远失败 | 实测打印 `keys()` 确认 |
| 3 | 4.3 示例 | `"bat_status": "1",` 后有多余逗号 | 非法 JSON | 已在本译文中移除 |
| 4 | 4.1 字段 | ~~`rssi` 标为 string，示例值为数字 `-50`~~ | 类型矛盾，强类型解析会失败 | ✅ **V1.5.2 已修正**：类型改为 `number`。但**兼容代码仍需保留**（旧固件按 string 输出） |
| 5 | 3.2 返回码 | ~~1003 与 1004 描述完全相同（Internal error）~~ | 无法区分两种内部错误 | ✅ **V1.5.2 已处置**：直接删除 `1004`，返回码只剩 5 个 —— 见 C.2 #4 |
| 6 | 3.1 请求数据 | 该节为图片，PDF 无文本层 | 无法获得原始说明文字 | 由 4.5 / 4.7 反推为 JSON 请求体 |
| 7 | 版本记录 | ~~V1.0~V1.4 的 Description 列全为空~~ | 无法追溯固件间接口变更 | 🟡 **V1.5.1 起已开始填写**，但仍遗漏 4 处变更 —— 见附录 C.2 |
| 8 | 4.1 字段 | `bat_cap` 未标注单位 | 无法确定是 Ah 还是 kWh | 实测或查阅产品规格书 |
| 9 | 4.7 MI1 | 未说明单次最多可下发多少个时间窗 | 超限行为未知 | 实测边界 |

---

## 附录 B：与 EZ1 系列本地 API 的差异对照

| 对比项 | EZ1（旧） | Lake_6 |
|---|---|---|
| 默认端口 | 8050 | **80** |
| 路径风格 | `getDeviceInfo` 等驼峰无前缀 | REST 风格：`/devices`、`/energies`、`/modes` |
| 响应信封 | `{data, message, deviceId}` | **`{data, deviceId, code, message}`（多了 code）** |
| 成功判定 | `message == "SUCCESS"` | **`code == 200`**；仅 `/control-panels` 缺 `code` 时才回退看 `message` |
| 写入能力 | 有（`/setMaxPower` 等） | 有（`POST /modes`、`POST /control-panels`） |
| 字段命名 | 驼峰：`maxPower`、`devVer` | 下划线：`power_limit`、`dev_ver` |
| 数据类型 | 混合（number 居多） | **几乎全为 string** |

> 两个协议的响应结构、字段命名和端口都不兼容，不能共用同一套解析代码。

---

## 附录 C：V1.5.2 变更清单（2026-11-11）

> 基线：V1.4。逐节比对后共发现 **7 处变更**，其中官方在版本记录中声明的只有 3 处。

### C.1 已声明变更（版本记录中有写）

| # | 章节 | 变更 | 版本 |
|---|---|---|---|
| 1 | 4.4 / 4.5 `/modes` | 🗑️ 删除参数 `power_limit`（并网侧输出功率上限，V1.4 中标明范围 0–2500W） | **V1.5.1** |
| 2 | 4.4 / 4.5 `/modes` | 🗑️ 删除参数 `backup_charP`（备电模式充电功率），同时删除示例③中的 `backup_charP: "2500"` | **V1.5.2** |
| 3 | 4.5 `/modes` → `time_cfg[].FI` | ➕ 新增 `GC`、`GD` 两个字段定义，并注明**固件强制为 1、配置值无效** | **V1.5.2** |

### C.2 未声明变更（版本记录中未提及）

| # | 章节 | 变更 | 风险 |
|---|---|---|---|
| 4 | 3.2 返回码 | 删除 `1004`，错误码从 **6 个减为 5 个** | 中：错误码分支需同步删减 |
| 5 | 4.1 `/devices` | `rssi` 类型 `string` → `number` | 中：仅新固件适用，旧固件仍需兼容 |
| 6 | 4.7 `/control-panels` | `MI1.time` 格式 **24 位 → 28 位**（增加“秒”） | **高：双向不兼容，长度错会回 `code=1001`** |
| 7 | 4.5 `/modes` → `FI.P` | 描述中仍引用已删除的 `power_limit`（“若 power_limit 小于 2500W…”） | 低：文档内部矛盾，需实测确认限制是否失效 |

### C.3 仍存在、本次未修正的旧问题

| # | 位置 | 问题 |
|---|---|---|
| 8 | 4.2 示例 | `"bat_cal": "0",` 后多余逗号，仍为非法 JSON |
| 9 | 4.3 示例 | `ongrid_impE ` / `offgrid_expE ` / `offgrid_impE ` 键名末尾空格仍在 |
| 10 | 4.3 示例 | `"bat_status": "1",` 后多余逗号仍在 |
| 11 | 4.1 字段 | `bat_cap` 仍未标注单位 |
| 12 | 4.1 `/devices` | 设备实测会返回 `bat_manuf` / `bat_model`，文档仍未收录。产品侧已答复：后续固件会屏蔽这两个字段，客户无需理解，且 LAKE 为固定型号电池 —— 集成侧不建实体 |
| 13 | 4.4 GET `/modes` | 示例 `"mode": "0"` 不在枚举 1–4 内 |
| 14 | 4.4 `/modes` | `dod` 在 **GET 响应**中仍未写范围，仅在 POST 参数说明中写 15–90% |

### C.4 对本项目集成开发的影响

| 结论项 | 协议现状 | 对实现的影响 |
|---|---|---|
| `power_limit` 实体 | 🗑️ 已删除（V1.5.1） | **不做该实体**。此前「设备实测缺失、待 C1 确认」的悬案由此终结 |
| `backup_charP` 实体 | 🗑️ 已删除（V1.5.2） | **不做该实体**。原「范围未定、禁止沿用 0–2500」的问题**直接消失** |
| `dod` 范围 | POST 明确 **15–90%** | 可定稿为 **15–90**。任何写成 15–100 的实现都是错的 |
| `time_cfg[].FI.GC/GD` | 官方确认为真实字段，固件强制为 1 | 读取时**容忍存在**、**不做实体**、回传无效；旧「未知字段」疑问终结 |
| `rssi` 类型 | 官方改为 `number` | 解析层**仍须兼容 string / number**，不可改为强类型 |
| 错误码数量 | 文档删除 `1004`，剩 **5 个** | 文档口径为 5 个；解析层建议**保留 `1004` 映射**——旧固件仍可能返回，映射只用于日志文案，不参与成功判定 |
| `MI1.time` 格式 | 24 位 → **28 位** | 若实现 control-panels 实体，**必须先探测固件实际接受的位数** |

> **一句话总结**：V1.5.2 删掉的两个字段（`power_limit`、`backup_charP`）恰好是本项目此前悬而未决的两个范围问题 —— 协议层直接把它们移出了，因此**这两个字段既不需要再定范围，也不应该再做实体**；真正需要落地的范围只剩两处：`dod` 的 **15–90**，以及 `time_cfg[].FI.P` 的 **0–2500**（分时充放电功率）。

