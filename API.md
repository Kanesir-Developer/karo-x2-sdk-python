# karo-x2-sdk-python 接口文档

Karo X2 机器人 Python SDK 对外接口参考。所有公开符号从顶层包导入：
`from karo_x2_sdk import Robot, ConnectOptions, ...`。

- 适用版本：SDK 3.3.x
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
- [导航任务](#导航任务)
- [安全事件](#安全事件)
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
| `async subscribe_task_events(on_data, on_status=None) -> Subscription` | 订阅 `tasks.events`，回调收到 `TaskEvent` |
| `async subscribe_safety_events(on_data, on_status=None) -> Subscription` | 订阅 `robot.safety`，回调收到 `SafetyEvent` |

- `on_data` / `on_status` 可以是普通函数或协程函数。
- 非 `READY` 状态也可调用：SDK 记录订阅意图，转 `READY` 后自动建立。
- `desired_hz <= 0` 表示使用服务端默认频率。

### 控制命令

| 签名 | 说明 |
|---|---|
| `async cmd_vel(linear_x, linear_y, angular_z) -> CmdVelResult` | 速度控制（单位同 ROS `geometry_msgs/Twist`） |
| `async emergency_stop(engage: bool, reason: str = "") -> EmergencyStopResult` | 软急停：`engage=True` 触发，`False` 解除 |
| `async ping() -> float` | 诊断 RTT（秒）；非 `READY` 返回 `-1.0` |

### 任务控制

| 签名 | 说明 |
|---|---|
| `async create_navigation_task_to_marker(marker_id: str) -> CreateTaskResult` | 创建导航任务，目标为已存点位 |
| `async create_navigation_task_to_pose(x: float, y: float, theta: float) -> CreateTaskResult` | 创建导航任务，目标为原始位姿 |
| `async cancel_task(task_id: str) -> TaskCommandResult` | 取消任务 |
| `async pause_task(task_id: str) -> TaskCommandResult` | 暂停任务 |
| `async resume_task(task_id: str) -> TaskCommandResult` | 恢复已暂停的任务 |

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

## 导航任务

任务相关的全部接口需要凭据授予 `task_control` 能力，否则返回 `CAPABILITY_DENIED`。

任务生命周期由服务端维护，客户端创建任务后拿到 `task_id`，后续
`cancel_task` / `pause_task` / `resume_task` 均以 `task_id` 为入参；任务状态变化
通过 `subscribe_task_events` 推送。

### create_navigation_task_to_marker / create_navigation_task_to_pose

```python
async create_navigation_task_to_marker(marker_id: str) -> CreateTaskResult
async create_navigation_task_to_pose(x: float, y: float, theta: float) -> CreateTaskResult
```

- `create_navigation_task_to_marker`：导航到机器人地图上已标记的点位。
- `create_navigation_task_to_pose`：导航到原始位姿 `(x, y, theta)`，`x` / `y` 为 map
  坐标系位置（米），`theta` 为朝向（弧度）。
- 成功时 `CreateTaskResult.task_id` 为新任务 ID。
- `marker_id` 为空字符串返回 `NAV_MARKER_NOT_FOUND`。
- 机器人当前已有任务在执行时返回 `TASK_RUNNING`（需先取消）。

### cancel_task / pause_task / resume_task

```python
async cancel_task(task_id: str) -> TaskCommandResult
async pause_task(task_id: str) -> TaskCommandResult
async resume_task(task_id: str) -> TaskCommandResult
```

- 三者均为幂等：对已处于目标状态的任务重复调用返回成功。
- `pause_task` 仅对 `RUNNING` 状态的任务有效；`resume_task` 仅对 `PAUSED` 状态有效，
  否则返回 `TASK_INVALID_STATE`。`task_id` 不存在时返回 `TASK_NOT_FOUND`。
- 暂停的任务若长时间未恢复，服务端会以 `TaskCancelReason.PAUSE_TIMEOUT` 自动取消。

### subscribe_task_events

```python
async subscribe_task_events(on_data, on_status=None) -> Subscription
```

- 订阅 `tasks.events`（`EVENT` 语义 topic）。
- 每次任务状态变化推送一份完整的 `TaskEvent` 快照。
- `on_data` 签名 `Callable[[TaskEvent], None | Awaitable[None]]`。

---

## 安全事件

### subscribe_safety_events

```python
async subscribe_safety_events(on_data, on_status=None) -> Subscription
```

- 订阅 `robot.safety`，机器人安全状态变化时推送 `SafetyEvent`。
- 需要凭据授予 `telemetry_read` 能力。
- `on_data` 签名 `Callable[[SafetyEvent], None | Awaitable[None]]`。

---

## 错误处理

- 构造 `Robot` 时参数非法 → 抛 `SdkException`。
- 业务异步路径（`connect` / `cmd_vel` / `emergency_stop` / 订阅 / 任务控制）**不抛异常**，
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
| `TASK_RUNNING` | 9400 | APPLICATION | 机器人已有任务在执行，需先取消 |
| `TASK_NOT_FOUND` | 9401 | APPLICATION | 指定的 `task_id` 不存在 |
| `TASK_INVALID_STATE` | 9402 | APPLICATION | 任务当前状态不允许该操作 |
| `NAV_MARKER_NOT_FOUND` | 9403 | APPLICATION | 指定的点位不存在 |
| `NAV_NO_ACTIVE_MAP` | 9404 | APPLICATION | 机器人当前无激活地图 |
| `NAV_GOAL_UNREACHABLE` | 9405 | APPLICATION | 目标不可达（被拒 / 在禁行区 / 无可行路径） |
| `NAV_LOW_BATTERY` | 9406 | APPLICATION | 电量过低，无法执行导航任务 |
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

### CreateTaskResult

| 字段 | 类型 | 说明 |
|---|---|---|
| `accepted` | `bool` | 任务是否创建成功 |
| `code` | `ErrorCode` | 错误码 |
| `message` | `str` | 诊断信息 |
| `task_id` | `str` | 创建成功时的新任务 ID |

### TaskCommandResult

`cancel_task` / `pause_task` / `resume_task` 的返回值。

| 字段 | 类型 | 说明 |
|---|---|---|
| `ok` | `bool` | 是否成功 |
| `code` | `ErrorCode` | 错误码 |
| `message` | `str` | 诊断信息 |

### TaskEvent

`subscribe_task_events` 回调收到的任务状态快照。

| 字段 | 类型 | 说明 |
|---|---|---|
| `task_id` | `str` | 任务 ID |
| `task_type` | `TaskType` | 任务类型 |
| `state` | `TaskState` | 当前状态 |
| `cancel_reason` | `TaskCancelReason` | 取消原因（`state == CANCELLED` 时有意义） |
| `pause_reason` | `TaskPauseReason` | 暂停原因（`state == PAUSED` 时有意义） |
| `error_code` | `ErrorCode` | 失败错误码（`state == FAILED` 时有意义） |
| `error_message` | `str` | 失败信息 |
| `marker_id` | `str` | 目标点位 ID（按点位导航时） |
| `planned_distance` | `float` | 规划总距离（米） |
| `traveled_distance` | `float` | 已行驶距离（米） |
| `created_at_ms` | `int` | 任务创建时间戳 |
| `started_at_ms` | `int` | 任务开始时间戳 |
| `completed_at_ms` | `int` | 任务结束时间戳 |
| `timestamp_ms` | `int` | 本次事件时间戳 |

### SafetyEvent

`subscribe_safety_events` 回调收到的安全状态快照。

| 字段 | 类型 | 说明 |
|---|---|---|
| `code` | `int` | 安全错误码 |
| `level` | `int` | 安全等级 |
| `severity` | `int` | 严重度 |
| `mode` | `str` | 当前安全模式 |
| `active_source` | `str` | 触发源 |
| `timestamp_ms` | `int` | 事件时间戳 |

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
| `telemetry_read` | `bool` | 状态订阅（`subscribe_robot_status` / `subscribe_safety_events`） |
| `image_stream` | `bool` | 图像流（后续版本） |
| `map_read` | `bool` | 地图读取（后续版本） |
| `map_write` | `bool` | 地图修改（后续版本） |
| `task_control` | `bool` | 任务控制（创建 / 取消 / 暂停 / 恢复任务，订阅任务事件） |

### TopicDescriptor

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | `str` | topic 名 |
| `description` | `str` | 说明 |
| `default_hz` | `float` | 默认推送频率 |
| `max_hz` | `float` | 最大推送频率 |
| `delivery_semantics` | `DeliverySemantics` | 投递语义 |

### 枚举

#### ChargeType

| 取值 | 含义 |
|---|---|
| `NONE` | 未充电 |
| `WIRE` | 充电线直连充电 |
| `DOCK` | 充电桩对接充电 |

#### ServiceState

| 取值 | 含义 |
|---|---|
| `IDLE` | 空闲 |
| `TASK` | 执行任务中 |
| `MAPPING` | 建图中 |
| `STARTING` | 启动中 |
| `SHUTTING_DOWN` | 关机中，拒绝新任务 |
| `UPGRADING` | OTA 升级中，拒绝新任务 |
| `REMOTE_CONTROL` | 操作员遥控中 |
| `GOTO_CHARGING` | 自主返回充电桩中 |

#### SubscriptionState

| 取值 | 含义 |
|---|---|
| `PENDING` | 待生效，已记录订阅意图，尚未与服务端建立 |
| `ACTIVE` | 已激活，正常接收数据 |
| `PAUSED` | 已暂停 |
| `CLOSED` | 已关闭 |

#### StreamStatusKind

| 取值 | 含义 |
|---|---|
| `STARTED` | 订阅已建立，开始推送 |
| `PAUSED` | 推送暂停 |
| `RESUMED` | 推送恢复（通常发生在重连后） |
| `GAP` | 检测到丢帧 |
| `CLOSED` | 订阅已关闭 |

#### DropPolicy

队列满时的丢弃策略。

| 取值 | 含义 |
|---|---|
| `DROP_OLDEST` | 丢弃队列中最旧的消息 |
| `DROP_NEWEST` | 丢弃最新到达的消息 |

#### CallbackMode

数据回调的派发模式。

| 取值 | 含义 |
|---|---|
| `DISPATCHED` | 回调在 SDK 内部线程派发，不阻塞 IO 线程 |
| `INLINE` | 回调在 IO 线程直接执行，低延迟；回调内不可做耗时操作 |

#### DeliverySemantics

topic 的投递语义。

| 取值 | 含义 |
|---|---|
| `TELEMETRY` | 遥测流，服务端按频率降采样，缺帧属正常采样 |
| `EVENT` | 事件流，每帧应送达，SDK 做丢帧检测 |

#### TaskType

| 取值 | 含义 |
|---|---|
| `UNSPECIFIED` | 未指定 |
| `NAVIGATION` | 导航任务 |
| `PATROL` | 巡逻任务 |
| `GO_BACK` | 返回充电桩任务 |

#### TaskState

| 取值 | 含义 |
|---|---|
| `UNSPECIFIED` | 未指定 |
| `PENDING` | 已创建，等待开始 |
| `RUNNING` | 执行中 |
| `PAUSED` | 已暂停 |
| `CANCELLING` | 取消中 |
| `SUCCEEDED` | 已成功完成 |
| `FAILED` | 已失败 |
| `CANCELLED` | 已取消 |

#### TaskCancelReason

| 取值 | 含义 |
|---|---|
| `UNSPECIFIED` | 未指定 |
| `USER` | 客户主动取消 |
| `ESTOP` | 急停触发取消 |
| `TIMEOUT` | 任务执行超时 |
| `PAUSE_TIMEOUT` | 暂停超时未恢复，自动取消 |
| `RESUME_FAILED` | 恢复失败 |
| `ERROR` | 执行错误 |

#### TaskPauseReason

| 取值 | 含义 |
|---|---|
| `UNSPECIFIED` | 未指定 |
| `USER` | 客户主动暂停 |
| `ESTOP` | 急停触发暂停 |

---

## 反馈

接口问题请发 **developer@kanesir.com**，附 SDK 版本号 + 复现步骤。
