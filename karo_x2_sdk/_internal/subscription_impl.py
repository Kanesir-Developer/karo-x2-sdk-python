from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Deque, Optional

from ..error import ErrorCode
from ..subscription import (
    CallbackMode,
    DropPolicy,
    StreamStatus,
    Subscription,
    SubscriptionState,
)
from ..topic import DeliverySemantics

if TYPE_CHECKING:
    from .proto_codec import DecodedTopicPush
    from .robot_impl import RobotImpl

FrameDispatcher = Callable[["DecodedTopicPush"], Awaitable[None]]

@dataclass
class SubSlot:

    topic: str = ""
    desired_hz: float = 0.0
    semantics: DeliverySemantics = DeliverySemantics.TELEMETRY
    callback_mode: CallbackMode = CallbackMode.DISPATCHED
    drop_policy: DropPolicy = DropPolicy.DROP_OLDEST
    queue_size: int = 100

    frame_dispatcher: Optional[FrameDispatcher] = None

    status_callback: Optional[Callable[[StreamStatus], Any]] = None

    state: SubscriptionState = SubscriptionState.PENDING
    last_seq: int = 0
    drop_count: int = 0
    error_code: ErrorCode = ErrorCode.OK

    pending_buffer: Deque["DecodedTopicPush"] = field(default_factory=deque)
    inflight_subscribe_request_id: int = 0
    fresh_retry_done: bool = False
    expected_resume_seq: int = 0
    ever_active: bool = False
    is_reconnect_resume: bool = False
    unsubscribe_sent: bool = False
    user_closed: bool = False

    messages_received: int = 0
    last_message_at: float = 0.0

    hz_buckets: list = field(default_factory=lambda: [0] * 60)
    hz_last_epoch_ms: int = 0

    dispatch_queue: Optional[Any] = None
    dispatch_worker: Optional[Any] = None

class SubscriptionFacade(Subscription):

    def __init__(self, slot: SubSlot, robot: "RobotImpl") -> None:
        self._slot = slot
        import weakref
        self._robot_ref = weakref.ref(robot)

        self._finalizer = weakref.finalize(
            self, _facade_finalizer_callback,
            weakref.ref(robot), slot,
        )

    @property
    def topic(self) -> str:
        return self._slot.topic

    @property
    def desired_hz(self) -> float:
        return self._slot.desired_hz

    @property
    def state(self) -> SubscriptionState:
        return self._slot.state

    @property
    def last_seq(self) -> int:
        return self._slot.last_seq

    @property
    def drop_count(self) -> int:
        return self._slot.drop_count

    @property
    def error(self) -> ErrorCode:
        return self._slot.error_code

    async def unsubscribe(self) -> ErrorCode:

        self._slot.user_closed = True

        self._finalizer.detach()
        r = self._robot_ref()
        if r is None:
            self._slot.state = SubscriptionState.CLOSED
            self._slot.error_code = ErrorCode.DISCONNECTED
            return ErrorCode.DISCONNECTED
        return await r.unsubscribe_request(self._slot.topic, sync_wait=True)

def _facade_finalizer_callback(robot_ref, slot: SubSlot) -> None:
    slot.user_closed = True
    r = robot_ref()
    if r is None:
        return
    if slot.state == SubscriptionState.CLOSED:
        return

    try:
        r.schedule_fire_and_forget_unsubscribe(slot.topic)
    except Exception:
        pass

