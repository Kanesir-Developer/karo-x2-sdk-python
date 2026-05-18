from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from .error import ErrorCode

class ConnectionState(IntEnum):
    IDLE = 0
    CONNECTING = 1
    READY = 2
    TRANSIENT_FAILURE = 3
    RECONNECTING = 4
    SHUTDOWN = 5
    FATAL = 6

    def __str__(self) -> str:
        return _NAMES[self]

_NAMES: dict[ConnectionState, str] = {
    ConnectionState.IDLE: "Idle",
    ConnectionState.CONNECTING: "Connecting",
    ConnectionState.READY: "Ready",
    ConnectionState.TRANSIENT_FAILURE: "TransientFailure",
    ConnectionState.RECONNECTING: "Reconnecting",
    ConnectionState.SHUTDOWN: "Shutdown",
    ConnectionState.FATAL: "Fatal",
}

@dataclass
class StateChangeInfo:

    reason: str = ""

    last_error_code: ErrorCode = ErrorCode.OK
    last_error_message: str = ""

    next_retry_in_ms: int = 0

    reconnect_attempt: int = 0

    last_action: str = ""

