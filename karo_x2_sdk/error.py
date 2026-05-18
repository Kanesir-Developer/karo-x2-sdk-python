from __future__ import annotations

from enum import IntEnum

class ErrorCode(IntEnum):

    OK = 0

    AUTH_FAILED = 1
    AUTH_CN_NOT_ALLOWED = 2
    AUTH_SERIAL_REVOKED = 3
    AUTH_TOKEN_INVALID = 4
    AUTH_TOKEN_EXPIRED = 5
    SESSION_TOKEN_INVALID = 10
    SESSION_TOKEN_EXPIRED = 11
    HANDSHAKE_REQUIRED = 12
    CAPABILITY_DENIED = 20
    RATE_LIMITED = 21
    UNSUPPORTED_VERSION = 22
    TOPIC_NOT_FOUND = 30
    TOPIC_ALREADY_SUBSCRIBED = 31
    TOPIC_NOT_SUBSCRIBED = 32

    CONTROL_E_STOP_ACTIVE = 9300
    CONTROL_PUBLISHER_UNAVAILABLE = 9301
    CONTROL_INVALID_TWIST = 9302

    TASK_RUNNING = 9400
    TASK_NOT_FOUND = 9401
    TASK_INVALID_STATE = 9402
    NAV_MARKER_NOT_FOUND = 9403
    NAV_NO_ACTIVE_MAP = 9404
    NAV_GOAL_UNREACHABLE = 9405
    NAV_LOW_BATTERY = 9406

    TRANSPORT_FAILURE = 10000
    TIMEOUT = 10001
    CANCELLED = 10002

    DISCONNECTED = 10003
    WOULD_DEADLOCK = 10004

    INTERNAL_ERROR = 10999

    def __str__(self) -> str:

        return _PASCAL_NAMES[self]

_PASCAL_NAMES: dict[ErrorCode, str] = {
    ErrorCode.OK: "Ok",
    ErrorCode.AUTH_FAILED: "AuthFailed",
    ErrorCode.AUTH_CN_NOT_ALLOWED: "AuthCnNotAllowed",
    ErrorCode.AUTH_SERIAL_REVOKED: "AuthSerialRevoked",
    ErrorCode.AUTH_TOKEN_INVALID: "AuthTokenInvalid",
    ErrorCode.AUTH_TOKEN_EXPIRED: "AuthTokenExpired",
    ErrorCode.SESSION_TOKEN_INVALID: "SessionTokenInvalid",
    ErrorCode.SESSION_TOKEN_EXPIRED: "SessionTokenExpired",
    ErrorCode.HANDSHAKE_REQUIRED: "HandshakeRequired",
    ErrorCode.CAPABILITY_DENIED: "CapabilityDenied",
    ErrorCode.RATE_LIMITED: "RateLimited",
    ErrorCode.UNSUPPORTED_VERSION: "UnsupportedVersion",
    ErrorCode.TOPIC_NOT_FOUND: "TopicNotFound",
    ErrorCode.TOPIC_ALREADY_SUBSCRIBED: "TopicAlreadySubscribed",
    ErrorCode.TOPIC_NOT_SUBSCRIBED: "TopicNotSubscribed",
    ErrorCode.CONTROL_E_STOP_ACTIVE: "ControlEStopActive",
    ErrorCode.CONTROL_PUBLISHER_UNAVAILABLE: "ControlPublisherUnavailable",
    ErrorCode.CONTROL_INVALID_TWIST: "ControlInvalidTwist",
    ErrorCode.TASK_RUNNING: "TaskRunning",
    ErrorCode.TASK_NOT_FOUND: "TaskNotFound",
    ErrorCode.TASK_INVALID_STATE: "TaskInvalidState",
    ErrorCode.NAV_MARKER_NOT_FOUND: "NavMarkerNotFound",
    ErrorCode.NAV_NO_ACTIVE_MAP: "NavNoActiveMap",
    ErrorCode.NAV_GOAL_UNREACHABLE: "NavGoalUnreachable",
    ErrorCode.NAV_LOW_BATTERY: "NavLowBattery",
    ErrorCode.TRANSPORT_FAILURE: "TransportFailure",
    ErrorCode.TIMEOUT: "Timeout",
    ErrorCode.CANCELLED: "Cancelled",
    ErrorCode.DISCONNECTED: "Disconnected",
    ErrorCode.WOULD_DEADLOCK: "WouldDeadlock",
    ErrorCode.INTERNAL_ERROR: "InternalError",
}

class ErrorCategory(IntEnum):

    OK = 0
    TRANSIENT = 1
    APPLICATION = 2
    FATAL = 3
    LOCAL = 4

_CATEGORY: dict[ErrorCode, ErrorCategory] = {
    ErrorCode.OK: ErrorCategory.OK,

    ErrorCode.AUTH_FAILED: ErrorCategory.FATAL,
    ErrorCode.AUTH_CN_NOT_ALLOWED: ErrorCategory.FATAL,
    ErrorCode.AUTH_SERIAL_REVOKED: ErrorCategory.FATAL,
    ErrorCode.AUTH_TOKEN_INVALID: ErrorCategory.FATAL,
    ErrorCode.AUTH_TOKEN_EXPIRED: ErrorCategory.FATAL,
    ErrorCode.UNSUPPORTED_VERSION: ErrorCategory.FATAL,

    ErrorCode.SESSION_TOKEN_INVALID: ErrorCategory.TRANSIENT,
    ErrorCode.SESSION_TOKEN_EXPIRED: ErrorCategory.TRANSIENT,
    ErrorCode.HANDSHAKE_REQUIRED: ErrorCategory.TRANSIENT,
    ErrorCode.TRANSPORT_FAILURE: ErrorCategory.TRANSIENT,

    ErrorCode.TIMEOUT: ErrorCategory.TRANSIENT,

    ErrorCode.CAPABILITY_DENIED: ErrorCategory.APPLICATION,
    ErrorCode.RATE_LIMITED: ErrorCategory.APPLICATION,
    ErrorCode.TOPIC_NOT_FOUND: ErrorCategory.APPLICATION,
    ErrorCode.TOPIC_ALREADY_SUBSCRIBED: ErrorCategory.APPLICATION,
    ErrorCode.TOPIC_NOT_SUBSCRIBED: ErrorCategory.APPLICATION,
    ErrorCode.CONTROL_E_STOP_ACTIVE: ErrorCategory.APPLICATION,
    ErrorCode.CONTROL_PUBLISHER_UNAVAILABLE: ErrorCategory.APPLICATION,
    ErrorCode.CONTROL_INVALID_TWIST: ErrorCategory.APPLICATION,
    ErrorCode.TASK_RUNNING: ErrorCategory.APPLICATION,
    ErrorCode.TASK_NOT_FOUND: ErrorCategory.APPLICATION,
    ErrorCode.TASK_INVALID_STATE: ErrorCategory.APPLICATION,
    ErrorCode.NAV_MARKER_NOT_FOUND: ErrorCategory.APPLICATION,
    ErrorCode.NAV_NO_ACTIVE_MAP: ErrorCategory.APPLICATION,
    ErrorCode.NAV_GOAL_UNREACHABLE: ErrorCategory.APPLICATION,
    ErrorCode.NAV_LOW_BATTERY: ErrorCategory.APPLICATION,

    ErrorCode.CANCELLED: ErrorCategory.LOCAL,
    ErrorCode.DISCONNECTED: ErrorCategory.LOCAL,
    ErrorCode.WOULD_DEADLOCK: ErrorCategory.LOCAL,
    ErrorCode.INTERNAL_ERROR: ErrorCategory.LOCAL,
}

def classify(code: ErrorCode) -> ErrorCategory:
    return _CATEGORY.get(code, ErrorCategory.LOCAL)

class SdkException(Exception):

    def __init__(self, code: ErrorCode, message: str = "") -> None:
        super().__init__(message)
        self.code = code

    def __str__(self) -> str:
        return f"{self.code}: {super().__str__()}"

