# karo-x2-sdk-python 接口文档

Karo X2 机器人 Python SDK 对外接口参考。所有公开符号从顶层包导入：
`from karo_x2_sdk import Robot, ConnectOptions, ...`。

- 适用版本：SDK 3.2.x
- 传输：WSS + mTLS，机器人 LAN 端口固定 4434
- 运行模型：基于 `asyncio`，连接 / 订阅 / 控制方法均为 `async`

---

## 目录

- [快速开始](#快速开始)
- [Robot](#robot)
- [连接配置](#连接配置)
- [连接生命周期](#连接生命周期)
- [订阅](#订阅)
- [控制命令](#控制命令)
- [错误处理](#错误处理)
- [诊断](#诊断)
- [数据类型](#数据类型)

---

## 快速开始

```python
import asyncio
from karo_x2_sdk import Robot, ConnectOptions, CertCredentials, RobotStatus

async def main():
    opts = ConnectOptions(
        host="192.168.10.10",
        cert=CertCredentials(
            cert_pem=...,
            key_pem=...,
            ca_pem=...,
        ),
        client_id="my-app/1.0",
    )

    robot = Robot(opts)
    robot.on_connection_state(lambda old, new, info: print(old, "→", new))

    async with robot:                       # 自动 connect + wait_until_ready
        def on_data(s: RobotStatus):
            print("battery", s.battery_percent)

        await robot.subscribe_robot_status(1.0, on_data)
        await robot.cmd_vel(0.2, 0.0, 0.0)

asyncio.run(main())
```

---

## Robot

SDK 的唯一入口。

### 构造

| 签名 | 说明 |
|---|---|
| `Robot(opts: ConnectOptions)` | 构造。参数非法时抛 `SdkException`。 |

`Robot` 支持异步上下文管理器：`async with robot:` 进入时自动 `connect()` +
`wait_until_ready()`，退出时自动 `close()`。

### 回调注册

| 签名 | 说明 |
|---|---|
| `on_connection_state(handler: ConnectionStateHandler) -> None` | 注册连接状态变化回调 |
| `on_log(handler: LogHandler) -> None` | 注册 SDK 日志回调 |

### 连接控制

| 签名 | 说明 |
|---|---|
| `async connect() -> None` | 发起连接 |
| `async wait_until_ready(timeout: float | None = None) -> bool` | 等待进入 `READY`，返回是否就绪 |
| `async close() -> None` | 终止连接，进入 `SHUTDOWN` 终态 |

### 状态查询

| 签名 | 说明 |
|---|---|
| `state -> ConnectionState` | 当前连接状态（property） |
| `is_connected -> bool` | 等价于 `state == READY`（property） |
| `info -> RobotInfo | None` | 握手成功后的机器人信息；未握手成功返回 `None`（property） |

### 订阅

| 签名 | 说明 |
|---|---|
| `async subscribe_robot_status(desired_hz, on_data, on_status=None) -> Subscription` | 订阅 `robot.state`，回调收到 `RobotStatus` |
| `async subscribe(topic, desired_hz, on_data, on_status=None) -> Subscription` | 通用订阅，回调收到 `TopicMessage` |

- `on_data` / `on_status` 可以是普通函数或协程函数。
- 非 `READY` 状态也可调用：SDK 记录订阅意图，转 `READY` 后自动建立。
- `desired_hz <= 0` 表示使用服务端默认频率。

### 控制命令

| 签名 | 说明 |
|---|---|
| `async cmd_vel(linear_x, linear_y, angular_z) -> CmdVelResult` | 速度控制（单位同 ROS `geometry_msgs/Twist`） |
| `async emergency_stop(engage: bool, reason: str = "") -> EmergencyStopResult` | 软急停：`engage=True` 触发，`False` 解除 |
| `async ping() -> float` | 诊断 RTT（秒）；非 `READY` 返回 `-1.0` |

### 诊断

| 签名 | 说明 |
|---|---|
| `async get_diagnostics() -> Diagnostics` | 当前诊断快照 |

### 模块级函数

| 签名 | 说明 |
|---|---|
| `karo_x2_sdk.sdk_version() -> str` | SDK 版本字符串 |
| `karo_x2_sdk.__version__` | SDK 版本字符串 |

---

## 连接配置

### ConnectOptions

时间类字段单位为**秒**（`float`）。

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `host` | `str` | `"192.168.10.10"` | 机器人 LAN 地址，不含端口 |
| `cert` | `CertCredentials` | — | X.509 证书认证（优先） |
| `access_token` | `AccessTokenCredentials` | — | Access Token 认证（备用） |
| `client_id` | `str` | `"karo-x2-sdk-python"` | 客户端标识 |
| `sdk_version` | `str` | `""` | 留空时握手用库内置版本，一般无需覆盖 |
| `connect_timeout` | `float` | `5.0` | 单次连接超时（秒） |
| `heartbeat_interval` | `float` | `10.0` | 心跳间隔（秒），`0` = 关闭心跳 |
| `ping_timeout` | `float` | `3.0` | 单次 Ping 响应超时（秒） |
| `max_missed_pings` | `int` | `3` | 连续未响应判死阈值 |
| `reconnect_max_attempts` | `int` | `-1` | `-1` 无限重连，`0` 不重连，`>0` 上限次数 |
| `reconnect_base_delay` | `float` | `0.5` | 重连退避基准（秒） |
| `reconnect_max_delay` | `float` | `30.0` | 重连退避上限（秒） |
| `reconnect_jitter_ratio` | `float` | `0.3` | 退避抖动比例 |
| `reconnect_replay_history` | `bool` | `True` | 重连后尝试补发历史 |
| `history_limit` | `int` | `1000` | 单次补发上限 |
| `subscribe_ack_timeout` | `float` | `5.0` | 订阅确认超时（秒） |
| `subscription_queue_size` | `int` | `100` | 单订阅回调队列长度 |
| `drop_policy` | `DropPolicy` | `DROP_OLDEST` | 队列满时的丢弃策略 |
| `callback_mode` | `CallbackMode` | `DISPATCHED` | 数据回调派发模式 |
| `cmdvel_rpc_timeout` | `float` | `0.2` | `cmd_vel` RPC 超时（秒） |
| `estop_rpc_timeout` | `float` | `2.0` | `emergency_stop` RPC 超时（秒） |

### CertCredentials

| 字段 | 类型 | 说明 |
|---|---|---|
| `cert_pem` | `str` | 客户端证书（PEM） |
| `key_pem` | `str` | 客户端私钥（PEM） |
| `ca_pem` | `str` | 校验服务端证书的 CA（PEM） |
| `insecure_skip_verify` | `bool` | 跳过服务端证书校验，仅测试用，生产保持 `False` |

### AccessTokenCredentials

| 字段 | 类型 | 说明 |
|---|---|---|
| `token` | `bytes` | 122 字节 Access Token |

---

## 连接生命周期

### ConnectionState

`IntEnum`。

| 取值 | 说明 |
|---|---|
| `IDLE` | 初始态，未连接 |
| `CONNECTING` | 首次连接中 |
| `READY` | 已连接可用 |
| `TRANSIENT_FAILURE` | 临时故障，将自动重连 |
| `RECONNECTING` | 重连中（含重订阅恢复） |
| `SHUTDOWN` | 已主动关闭，终态 |
| `FATAL` | 不可恢复错误，终态，不再重连 |

### StateChangeInfo

`ConnectionStateHandler` 回调参数。

| 字段 | 类型 | 说明 |
|---|---|---|
| `reason` | `str` | 状态变化原因 |
| `last_error_code` | `ErrorCode` | 最近一次错误码 |
| `last_error_message` | `str` | 最近一次错误信息 |
| `next_retry_in_ms` | `int` | 距下次重连的时间（毫秒） |
| `reconnect_attempt` | `int` | 当前重连尝试次数 |
| `last_action` | `str` | 最近一次内部动作 |

### ConnectionStateHandler

```python
ConnectionStateHandler = Callable[
    [ConnectionState, ConnectionState, StateChangeInfo],
    None | Awaitable[None],
]
```

回调可为普通函数或协程函数。

---

## 订阅

### Subscription

`subscribe*` 返回的句柄。支持异步上下文管理器，退出时自动 `unsubscribe()`。

| 成员 | 说明 |
|---|---|
| `topic -> str` | 订阅的 topic 名（property） |
| `desired_hz -> float` | 请求频率（property） |
| `state -> SubscriptionState` | 当前订阅状态（property） |
| `last_seq -> int` | 最近收到的序列号（property） |
| `drop_count -> int` | 队列丢弃计数（property） |
| `error -> ErrorCode` | 最近错误码（property） |
| `async unsubscribe() -> ErrorCode` | 主动取消订阅 |

### StreamStatus

`StatusCallback` 回调参数。

| 字段 | 类型 | 说明 |
|---|---|---|
| `kind` | `StreamStatusKind` | 事件类型 |
| `reason` | `str` | 说明 |
| `gap_count` | `int | None` | 丢帧数（`GAP` / `RESUMED` 时有意义） |
| `error_code` | `ErrorCode` | 错误码 |

### StatusCallback

```python
StatusCallback = Callable[[StreamStatus], None]
```

---

## 控制命令

### cmd_vel

```python
async cmd_vel(linear_x: float, linear_y: float, angular_z: float) -> CmdVelResult
```

- 客户端令牌桶限频 ≤ 20 Hz，超频本地丢弃并返回 `RATE_LIMITED`。
- 需要凭据授予 `chassis_control` 能力，否则返回 `CAPABILITY_DENIED`。
- 服务端 0.5s watchdog：停止发送后机器人自动归零速度。
- 断连时立即返回 `DISCONNECTED`，**不重试、不排队**。

### emergency_stop

```python
async emergency_stop(engage: bool, reason: str = "") -> EmergencyStopResult
```

- `engage=True` 触发的软急停，会在重连成功后**自动重放**；`engage=False` 不重放。

---

## 错误处理

- 构造 `Robot` 时参数非法 → 抛 `SdkException`。
- 业务异步路径（`connect` / `cmd_vel` / `emergency_stop` / `subscribe`）**不抛异常**，
  通过返回值或回调携带 `ErrorCode`。

### ErrorCode

`IntEnum`。

| 取值 | 编号 | 分类 | 含义 |
|---|---|---|---|
| `OK` | 0 | — | 无错误 |
| `AUTH_FAILED` | 1 | FATAL | 认证失败（证书无效 / 过期 / 已吊销） |
| `AUTH_CN_NOT_ALLOWED` | 2 | FATAL | 证书未被授权（不在机器人允许的应用列表中） |
| `AUTH_SERIAL_REVOKED` | 3 | FATAL | 证书序列号已被吊销 |
| `AUTH_TOKEN_INVALID` | 4 | FATAL | Access Token 无效 |
| `AUTH_TOKEN_EXPIRED` | 5 | FATAL | Access Token 已过期 |
| `SESSION_TOKEN_INVALID` | 10 | TRANSIENT | 会话令牌无效 |
| `SESSION_TOKEN_EXPIRED` | 11 | TRANSIENT | 会话令牌已过期 |
| `HANDSHAKE_REQUIRED` | 12 | TRANSIENT | 未完成握手就发送命令 |
| `CAPABILITY_DENIED` | 20 | APPLICATION | 凭据未授予该操作所需能力 |
| `RATE_LIMITED` | 21 | APPLICATION | 命令被限频丢弃 |
| `UNSUPPORTED_VERSION` | 22 | FATAL | SDK 协议版本不被机器人支持 |
| `TOPIC_NOT_FOUND` | 30 | APPLICATION | 订阅的 topic 不存在 |
| `TOPIC_ALREADY_SUBSCRIBED` | 31 | APPLICATION | 该 topic 已订阅，不可重复订阅 |
| `TOPIC_NOT_SUBSCRIBED` | 32 | APPLICATION | 该 topic 尚未订阅 |
| `CONTROL_E_STOP_ACTIVE` | 9300 | APPLICATION | 机器人处于急停态，控制命令被拒 |
| `CONTROL_PUBLISHER_UNAVAILABLE` | 9301 | APPLICATION | 机器人控制链路未就绪 |
| `CONTROL_INVALID_TWIST` | 9302 | APPLICATION | 速度参数非法（NaN / Inf 或超物理上限） |
| `TRANSPORT_FAILURE` | 10000 | TRANSIENT | WebSocket 连接或读写失败 |
| `TIMEOUT` | 10001 | TRANSIENT | 请求超时 |
| `CANCELLED` | 10002 | LOCAL | 请求被客户端取消 |
| `DISCONNECTED` | 10003 | LOCAL | 未连接（在非 `READY` 状态调用） |
| `WOULD_DEADLOCK` | 10004 | LOCAL | 在 SDK 回调内调用同步方法（被拦截以避免死锁） |
| `INTERNAL_ERROR` | 10999 | LOCAL | SDK 内部错误 |

### ErrorCategory

`IntEnum`。

| 取值 | 含义 |
|---|---|
| `OK` | 无错误 |
| `TRANSIENT` | 临时错误，SDK 自动重连 |
| `APPLICATION` | 单次调用失败，不触发重连 |
| `FATAL` | 致命错误，进 `FATAL` 终态 |
| `LOCAL` | 客户端本地错误 |

### 辅助函数

| 签名 | 说明 |
|---|---|
| `classify(code: ErrorCode) -> ErrorCategory` | 错误码分类 |

### SdkException

| 成员 | 说明 |
|---|---|
| `code: ErrorCode` | 错误码 |
| `str(exc)` | `"<code>: <message>"` |

---

## 诊断

### Diagnostics

`get_diagnostics()` 返回的快照，含 `connection` / `transport` / `subscriptions` /
`rpcs` 四组。`Diagnostics.to_json() -> str` 可序列化为 JSON。

| 分组 | 字段 |
|---|---|
| `connection` | `state` / `last_state_change_ms` / `reconnect_count` / `last_error_code` / `last_error_message` / `server_protocol_version` |
| `transport` | `rtt_p50_ms` / `rtt_p99_ms` / `bytes_sent` / `bytes_received` / `last_ping_age_ms` |
| `subscriptions` | `SubscriptionStat` 列表 |
| `rpcs` | `RpcStat` 列表 |

`SubscriptionStat`：`topic` / `state` / `configured_hz` / `received_hz_1min` /
`drop_count` / `last_seq` / `last_message_age_ms`。

`RpcStat`：`name` / `count` / `error_count` / `p99_latency_ms`。

### LogLevel / LogHandler

```python
class LogLevel(IntEnum):
    TRACE, DEBUG, INFO, WARN, ERROR, OFF

LogHandler = Callable[[LogLevel, str], None]
```

---

## 数据类型

### RobotStatus

`subscribe_robot_status` 回调收到的 typed 状态。

| 字段 | 类型 | 说明 |
|---|---|---|
| `robot_id` | `str` | 机器人 ID |
| `sequence` | `int` | 心跳序号 |
| `timestamp_ms` | `int` | 服务端时间戳 |
| `health_score` | `int` | 健康度 0-100 |
| `battery_percent` | `int` | 电量 0-100 |
| `charge_type` | `ChargeType` | 充电类型 |
| `service_state` | `ServiceState` | 服务状态 |
| `is_estop` | `bool` | 是否急停（硬或软） |
| `is_hw_estop` | `bool` | 硬急停 |
| `is_sw_estop` | `bool` | 软急停 |
| `active_map_id` | `str` | 当前地图 ID |
| `active_map_name` | `str` | 当前地图名 |
| `active_floor` | `int` | 当前楼层 |
| `current_task_id` | `str` | 当前任务 ID，空为无任务 |
| `uptime_seconds` | `int` | 运行时长 |
| `idle_seconds` | `int` | 空闲时长 |
| `charging_seconds` | `int` | 充电时长 |
| `error_codes` | `list[int]` | 当前活跃错误码 |

### CmdVelResult

| 字段 | 类型 | 说明 |
|---|---|---|
| `accepted` | `bool` | 是否被接受 |
| `code` | `ErrorCode` | 错误码 |
| `message` | `str` | 诊断信息 |
| `rtt_ms` | `int` | 往返时延（毫秒） |

### EmergencyStopResult

| 字段 | 类型 | 说明 |
|---|---|---|
| `ok` | `bool` | 是否成功 |
| `code` | `ErrorCode` | 错误码 |
| `message` | `str` | 诊断信息 |

### RobotInfo

| 字段 | 类型 | 说明 |
|---|---|---|
| `sn` | `str` | 机器人序列号 |
| `model` | `str` | 机器人型号 |
| `protocol_version` | `str` | 服务端协议版本 |
| `granted_capabilities` | `Capabilities` | 已授权能力 |
| `available_topics` | `list[TopicDescriptor]` | 可订阅 topic 列表 |

### Capabilities

| 字段 | 类型 | 说明 |
|---|---|---|
| `chassis_control` | `bool` | 底盘控制（`cmd_vel` / `emergency_stop`） |
| `telemetry_read` | `bool` | 状态订阅 |
| `image_stream` | `bool` | 图像流（后续版本） |
| `map_read` | `bool` | 地图读取（后续版本） |
| `map_write` | `bool` | 地图修改（后续版本） |
| `task_control` | `bool` | 任务控制（后续版本） |

### TopicDescriptor

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | `str` | topic 名 |
| `description` | `str` | 说明 |
| `default_hz` | `float` | 默认推送频率 |
| `max_hz` | `float` | 最大推送频率 |
| `delivery_semantics` | `DeliverySemantics` | 投递语义 |

### TopicMessage

`subscribe`（通用订阅）回调收到的原始消息。

| 字段 | 类型 | 说明 |
|---|---|---|
| `topic` | `str` | topic 名 |
| `timestamp_ms` | `int` | 服务端时间戳 |
| `seq` | `int` | 序列号 |
| `payload` | `bytes` | 序列化负载 |

### 枚举

| 枚举 | 取值 |
|---|---|
| `ChargeType` | `NONE` / `WIRE` / `DOCK` |
| `ServiceState` | `IDLE` / `TASK` / `MAPPING` / `STARTING` / `SHUTTING_DOWN` / `UPGRADING` / `REMOTE_CONTROL` / `GOTO_CHARGING` |
| `SubscriptionState` | `PENDING` / `ACTIVE` / `PAUSED` / `CLOSED` |
| `StreamStatusKind` | `STARTED` / `PAUSED` / `RESUMED` / `GAP` / `CLOSED` |
| `DropPolicy` | `DROP_OLDEST` / `DROP_NEWEST` |
| `CallbackMode` | `DISPATCHED` / `INLINE` |
| `DeliverySemantics` | `TELEMETRY` / `EVENT` |

---

## 反馈

接口问题请发 **developer@kanesir.com**，附 SDK 版本号 + 复现步骤。
