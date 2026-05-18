from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, Optional

from .error import ErrorCode

class StreamStatusKind(IntEnum):

    STARTED = 0
    PAUSED = 1
    RESUMED = 2
    GAP = 3
    CLOSED = 4

    def __str__(self) -> str:
        return _STREAM_NAMES[self]

_STREAM_NAMES: dict[StreamStatusKind, str] = {
    StreamStatusKind.STARTED: "Started",
    StreamStatusKind.PAUSED: "Paused",
    StreamStatusKind.RESUMED: "Resumed",
    StreamStatusKind.GAP: "Gap",
    StreamStatusKind.CLOSED: "Closed",
}

@dataclass
class StreamStatus:

    kind: StreamStatusKind = StreamStatusKind.STARTED
    reason: str = ""

    gap_count: Optional[int] = None

    error_code: ErrorCode = ErrorCode.OK

class SubscriptionState(IntEnum):

    PENDING = 0
    ACTIVE = 1
    PAUSED = 2
    CLOSED = 3

    def __str__(self) -> str:
        return _SUB_NAMES[self]

_SUB_NAMES: dict[SubscriptionState, str] = {
    SubscriptionState.PENDING: "Pending",
    SubscriptionState.ACTIVE: "Active",
    SubscriptionState.PAUSED: "Paused",
    SubscriptionState.CLOSED: "Closed",
}

class DropPolicy(IntEnum):

    DROP_OLDEST = 0
    DROP_NEWEST = 1

class CallbackMode(IntEnum):

    DISPATCHED = 0
    INLINE = 1

StatusCallback = Callable[[StreamStatus], None]

class Subscription(ABC):

    @property
    @abstractmethod
    def topic(self) -> str:
        ...

    @property
    @abstractmethod
    def desired_hz(self) -> float:
        ...

    @property
    @abstractmethod
    def state(self) -> SubscriptionState:
        ...

    @property
    @abstractmethod
    def last_seq(self) -> int:
        ...

    @property
    @abstractmethod
    def drop_count(self) -> int:
        ...

    @property
    @abstractmethod
    def error(self) -> ErrorCode:
        ...

    @abstractmethod
    async def unsubscribe(self) -> ErrorCode:
        ...

    async def __aenter__(self) -> "Subscription":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.unsubscribe()

