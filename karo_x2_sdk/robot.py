from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable, List, Optional, Union

from .capabilities import Capabilities
from .connection_state import ConnectionState, StateChangeInfo
from .diagnostics import Diagnostics, LogHandler
from .error import ErrorCode
from .messages import RobotStatus
from .subscription import (
    CallbackMode,
    DropPolicy,
    StatusCallback,
    Subscription,
)
from .topic import TopicDescriptor, TopicMessage

@dataclass
class CertCredentials:

    cert_pem: str = ""
    key_pem: str = ""
    ca_pem: str = ""

    insecure_skip_verify: bool = False

@dataclass
class AccessTokenCredentials:

    token: bytes = b""

@dataclass
class ConnectOptions:

    host: str = "192.168.10.10"

    cert: CertCredentials = field(default_factory=CertCredentials)
    access_token: AccessTokenCredentials = field(default_factory=AccessTokenCredentials)

    client_id: str = "karo-x2-sdk-python"

    sdk_version: str = ""

    connect_timeout: float = 5.0
    heartbeat_interval: float = 10.0
    ping_timeout: float = 3.0
    max_missed_pings: int = 3

    reconnect_max_attempts: int = -1
    reconnect_base_delay: float = 0.5
    reconnect_max_delay: float = 30.0
    reconnect_jitter_ratio: float = 0.3

    reconnect_replay_history: bool = True
    history_limit: int = 1000
    subscribe_ack_timeout: float = 5.0

    subscription_queue_size: int = 100
    drop_policy: DropPolicy = DropPolicy.DROP_OLDEST

    callback_mode: CallbackMode = CallbackMode.DISPATCHED

    cmdvel_rpc_timeout: float = 0.2
    estop_rpc_timeout: float = 2.0

@dataclass
class RobotInfo:
    sn: str = ""
    model: str = ""
    protocol_version: str = ""
    granted_capabilities: Capabilities = field(default_factory=Capabilities)
    available_topics: List[TopicDescriptor] = field(default_factory=list)

@dataclass
class CmdVelResult:

    accepted: bool = False
    code: ErrorCode = ErrorCode.OK
    message: str = ""
    rtt_ms: int = 0

@dataclass
class EmergencyStopResult:
    ok: bool = False
    code: ErrorCode = ErrorCode.OK
    message: str = ""

ConnectionStateHandler = Callable[
    [ConnectionState, ConnectionState, StateChangeInfo],
    Union[None, Awaitable[None]],
]

def sdk_version() -> str:
    return "3.2.16"

class Robot:

    def __init__(self, opts: ConnectOptions) -> None:

        from ._internal.robot_impl import RobotImpl
        self._impl = RobotImpl(opts)

    def on_connection_state(self, handler: ConnectionStateHandler) -> None:
        self._impl.set_connection_state_handler(handler)

    def on_log(self, handler: LogHandler) -> None:
        self._impl.set_log_handler(handler)

    async def connect(self) -> None:
        await self._impl.connect()

    async def wait_until_ready(self, timeout: Optional[float] = None) -> bool:
        return await self._impl.wait_until_ready(timeout)

    async def close(self) -> None:
        await self._impl.close()

    @property
    def state(self) -> ConnectionState:
        return self._impl.state

    @property
    def is_connected(self) -> bool:
        return self._impl.state == ConnectionState.READY

    @property
    def info(self) -> Optional[RobotInfo]:
        return self._impl.info

    async def subscribe_robot_status(
        self,
        desired_hz: float,
        on_data: Callable[[RobotStatus], Union[None, Awaitable[None]]],
        on_status: Optional[StatusCallback] = None,
    ) -> Subscription:
        return await self._impl.subscribe_robot_status(desired_hz, on_data, on_status)

    async def subscribe(
        self,
        topic: str,
        desired_hz: float,
        on_data: Callable[[TopicMessage], Union[None, Awaitable[None]]],
        on_status: Optional[StatusCallback] = None,
    ) -> Subscription:
        return await self._impl.subscribe_generic(topic, desired_hz, on_data, on_status)

    async def cmd_vel(self, linear_x: float, linear_y: float, angular_z: float) -> CmdVelResult:
        return await self._impl.cmd_vel(linear_x, linear_y, angular_z)

    async def emergency_stop(self, engage: bool, reason: str = "") -> EmergencyStopResult:
        return await self._impl.emergency_stop_rpc(engage, reason)

    async def ping(self) -> float:
        return await self._impl.ping()

    async def get_diagnostics(self) -> Diagnostics:
        return await self._impl.get_diagnostics()

    async def __aenter__(self) -> "Robot":
        await self.connect()

        await self.wait_until_ready()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

