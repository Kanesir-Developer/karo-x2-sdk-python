from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, List

from .connection_state import ConnectionState
from .error import ErrorCode
from .subscription import SubscriptionState

class LogLevel(IntEnum):
    TRACE = 0
    DEBUG = 1
    INFO = 2
    WARN = 3
    ERROR = 4
    OFF = 5

    def __str__(self) -> str:
        return _LEVELS[self]

_LEVELS: dict[LogLevel, str] = {
    LogLevel.TRACE: "Trace",
    LogLevel.DEBUG: "Debug",
    LogLevel.INFO:  "Info",
    LogLevel.WARN:  "Warn",
    LogLevel.ERROR: "Error",
    LogLevel.OFF:   "Off",
}

LogHandler = Callable[[LogLevel, str], None]

@dataclass
class _ConnectionStat:
    state: ConnectionState = ConnectionState.IDLE
    last_state_change_ms: int = 0
    reconnect_count: int = 0
    last_error_code: ErrorCode = ErrorCode.OK
    last_error_message: str = ""
    server_protocol_version: str = ""

@dataclass
class _TransportStat:
    rtt_p50_ms: float = 0.0
    rtt_p99_ms: float = 0.0
    bytes_sent: int = 0
    bytes_received: int = 0
    last_ping_age_ms: int = -1

@dataclass
class SubscriptionStat:
    topic: str = ""
    state: SubscriptionState = SubscriptionState.PENDING
    configured_hz: float = 0.0
    received_hz_1min: float = 0.0
    drop_count: int = 0
    last_seq: int = 0
    last_message_age_ms: int = -1

@dataclass
class RpcStat:
    name: str = ""
    count: int = 0
    error_count: int = 0
    p99_latency_ms: float = 0.0

@dataclass
class Diagnostics:

    connection: _ConnectionStat = field(default_factory=_ConnectionStat)
    transport: _TransportStat = field(default_factory=_TransportStat)
    subscriptions: List[SubscriptionStat] = field(default_factory=list)
    rpcs: List[RpcStat] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(_to_dict(self), separators=(",", ":"))

def _to_dict(d: Diagnostics) -> dict:
    conn_err = None
    if d.connection.last_error_code != ErrorCode.OK:
        conn_err = {
            "code": str(d.connection.last_error_code),
            "message": d.connection.last_error_message,
        }
    return {
        "connection": {
            "state": str(d.connection.state),
            "last_state_change_ms": d.connection.last_state_change_ms,
            "reconnect_count": d.connection.reconnect_count,
            "last_error": conn_err,
            "server_protocol_version": d.connection.server_protocol_version,
        },
        "transport": {
            "rtt_p50_ms": d.transport.rtt_p50_ms,
            "rtt_p99_ms": d.transport.rtt_p99_ms,
            "bytes_sent": d.transport.bytes_sent,
            "bytes_received": d.transport.bytes_received,
            "last_ping_age_ms": d.transport.last_ping_age_ms,
        },
        "subscriptions": [
            {
                "topic": s.topic,
                "state": str(s.state),
                "configured_hz": s.configured_hz,
                "received_hz_1min": s.received_hz_1min,
                "drop_count": s.drop_count,
                "last_seq": s.last_seq,
                "last_message_age_ms": s.last_message_age_ms,
            } for s in d.subscriptions
        ],
        "rpcs": [
            {
                "name": r.name,
                "count": r.count,
                "error_count": r.error_count,
                "p99_latency_ms": r.p99_latency_ms,
            } for r in d.rpcs
        ],
    }

