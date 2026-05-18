from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from ..error import ErrorCode

class TaskType(IntEnum):
    UNSPECIFIED = 0
    NAVIGATION = 1
    PATROL = 2
    GO_BACK = 3

class TaskState(IntEnum):
    UNSPECIFIED = 0
    PENDING = 1
    RUNNING = 2
    PAUSED = 3
    CANCELLING = 4
    SUCCEEDED = 10
    FAILED = 11
    CANCELLED = 12

class TaskCancelReason(IntEnum):
    UNSPECIFIED = 0
    USER = 1
    ESTOP = 2
    TIMEOUT = 3
    PAUSE_TIMEOUT = 4
    RESUME_FAILED = 5
    ERROR = 6

class TaskPauseReason(IntEnum):
    UNSPECIFIED = 0
    USER = 1
    ESTOP = 2

@dataclass
class TaskEvent:
    task_id: str = ""
    task_type: TaskType = TaskType.UNSPECIFIED
    state: TaskState = TaskState.UNSPECIFIED
    cancel_reason: TaskCancelReason = TaskCancelReason.UNSPECIFIED
    pause_reason: TaskPauseReason = TaskPauseReason.UNSPECIFIED
    error_code: ErrorCode = ErrorCode.OK
    error_message: str = ""
    marker_id: str = ""
    planned_distance: float = 0.0
    traveled_distance: float = 0.0
    created_at_ms: int = 0
    started_at_ms: int = 0
    completed_at_ms: int = 0
    timestamp_ms: int = 0
