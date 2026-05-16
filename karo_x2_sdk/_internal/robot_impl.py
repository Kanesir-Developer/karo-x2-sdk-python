from __future__ import annotations

import asyncio
import inspect
import os
import random
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, Optional

from ..connection_state import ConnectionState, StateChangeInfo
from ..diagnostics import (
    Diagnostics,
    LogHandler,
    LogLevel,
    RpcStat,
    SubscriptionStat,
)
from ..error import ErrorCategory, ErrorCode, SdkException, classify
from ..subscription import (
    CallbackMode,
    DropPolicy,
    StreamStatus,
    StreamStatusKind,
    Subscription,
    SubscriptionState,
)
from ..topic import DeliverySemantics, TopicMessage

from . import proto_codec as pc
from .proto_codec import (
    DecodedResponse,
    DecodedTopicPush,
    SubscribeRejectReason,
    reject_reason_to_error,
)
from .subscription_impl import SubSlot, SubscriptionFacade
from .ws_client import WsClient

def _now_ms() -> int:
    return int(time.time() * 1000)

def _now_steady() -> float:
    return time.monotonic()

async def _maybe_await(result: Any) -> None:
    if inspect.isawaitable(result):
        try:
            await result
        except Exception:
            pass

class _RttHist:

    def __init__(self, cap: int = 1024) -> None:
        self._d: Deque[float] = deque(maxlen=cap)

    def record(self, rtt_ms: float) -> None:
        self._d.append(rtt_ms)

    def p50_ms(self) -> float:
        if not self._d:
            return 0.0
        s = sorted(self._d)
        return s[len(s) // 2]

    def p99_ms(self) -> float:
        if not self._d:
            return 0.0
        s = sorted(self._d)
        return s[min(len(s) - 1, (len(s) * 99) // 100)]

class _TokenBucket:

    def __init__(self, max_hz: float, burst: float = 1.0) -> None:
        self._max_hz = max_hz
        self._burst = burst
        self._tokens = burst
        self._last = _now_steady()

    def try_acquire(self) -> bool:
        now = _now_steady()
        elapsed = now - self._last
        self._last = now
        self._tokens = min(self._burst, self._tokens + elapsed * self._max_hz)
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False

class _InflightRpc:
    __slots__ = ("request_id", "method", "future", "timeout_handle", "enqueued_at")

    def __init__(
        self, request_id: int, method: str,
        future: "asyncio.Future[DecodedResponse]",
        timeout_handle: Optional[asyncio.TimerHandle],
        enqueued_at: float,
    ) -> None:
        self.request_id = request_id
        self.method = method
        self.future = future
        self.timeout_handle = timeout_handle
        self.enqueued_at = enqueued_at

class RobotImpl:

    def __init__(self, opts: Any) -> None:
        self.opts = opts
        self._validate_opts()

        self._state: ConnectionState = ConnectionState.IDLE
        self._state_changed_evt = asyncio.Event()

        self._ws: Optional[WsClient] = None

        self._connection_state_handler: Optional[Callable] = None
        self._log_handler: Optional[LogHandler] = None

        self._robot_info = None

        self._next_request_id = 1

        self._inflight: Dict[int, _InflightRpc] = {}

        self._subs: Dict[str, SubSlot] = {}

        self._inflight_sub: Dict[int, str] = {}

        self._sub_ack_timers: Dict[int, asyncio.TimerHandle] = {}

        self._heartbeat_task: Optional[asyncio.Task[None]] = None
        self._last_inbound: float = _now_steady()
        self._miss_count = 0
        self._last_ping_request_id = 0

        self._ping_deadline_evt: asyncio.Event = asyncio.Event()
        self._heartbeat_wakeup: asyncio.Event = asyncio.Event()

        self._reconnect_attempt = 0
        self._reconnect_total_count = 0
        self._reconnect_task: Optional[asyncio.Task[None]] = None

        self._rng = random.Random((os.getpid() << 32) ^ time.monotonic_ns())

        self._last_estop_intent: str = "none"
        self._last_estop_reason: str = ""

        self._reconnect_subs_pending = 0
        self._reconnect_estop_pending = False

        self._cmdvel_rate = _TokenBucket(20.0, 1.0)

        self._last_state_change_ms = _now_ms()
        self._last_error_code: ErrorCode = ErrorCode.OK
        self._last_error_msg: str = ""
        self._bytes_sent = 0
        self._bytes_received = 0
        self._last_ping_sent_ms = -1
        self._rtt_hist = _RttHist()
        self._rpc_stats: Dict[str, Dict[str, Any]] = {
            "cmd_vel": {"count": 0, "error_count": 0, "hist": _RttHist()},
            "emergency_stop": {"count": 0, "error_count": 0, "hist": _RttHist()},
            "ping": {"count": 0, "error_count": 0, "hist": _RttHist()},
        }

        self._connect_invoked = False

        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def _validate_opts(self) -> None:
        o = self.opts
        if not o.host:
            raise SdkException(ErrorCode.TRANSPORT_FAILURE, "ConnectOptions.host is empty")
        if ":" in o.host:
            raise SdkException(ErrorCode.TRANSPORT_FAILURE,
                "ConnectOptions.host must not contain port; SDK uses fixed port 4434")
        if not o.cert.cert_pem and not o.access_token.token:
            raise SdkException(ErrorCode.AUTH_FAILED,
                "neither CertCredentials nor AccessTokenCredentials provided")
        if o.cert.cert_pem and not o.cert.key_pem:
            raise SdkException(ErrorCode.AUTH_FAILED,
                "CertCredentials.cert_pem provided but key_pem empty")
        if o.heartbeat_interval < 0:
            raise SdkException(ErrorCode.INTERNAL_ERROR, "heartbeat_interval must be >= 0")
        if o.reconnect_max_delay < o.reconnect_base_delay:
            raise SdkException(ErrorCode.INTERNAL_ERROR,
                "reconnect_max_delay < reconnect_base_delay")
        if not (0.0 <= o.reconnect_jitter_ratio <= 1.0):
            raise SdkException(ErrorCode.INTERNAL_ERROR,
                "reconnect_jitter_ratio out of [0, 1]")
        if o.subscription_queue_size <= 0:
            raise SdkException(ErrorCode.INTERNAL_ERROR,
                "subscription_queue_size must be >= 1")

    def set_connection_state_handler(self, handler: Callable) -> None:
        self._connection_state_handler = handler

    def set_log_handler(self, handler: Optional[LogHandler]) -> None:
        self._log_handler = handler

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def info(self):
        return self._robot_info

    async def connect(self) -> None:
        self._loop = asyncio.get_running_loop()
        if self._connect_invoked:
            return
        self._connect_invoked = True
        t = asyncio.create_task(self._establish(is_reconnect=False),
                                name="establish-initial")

        def _on_done(task: "asyncio.Task") -> None:
            if task.cancelled():
                return
            exc = task.exception()
            if exc is None:
                return

            asyncio.create_task(
                self._abort_to_fatal(ErrorCode.INTERNAL_ERROR,
                                     f"establish task crashed: {exc!r}"),
                name="abort-on-establish-crash",
            )
        t.add_done_callback(_on_done)

    async def wait_until_ready(self, timeout: Optional[float] = None) -> bool:
        async def _wait():
            while True:

                self._state_changed_evt.clear()
                s = self._state
                if s in (ConnectionState.READY, ConnectionState.FATAL,
                         ConnectionState.SHUTDOWN):
                    return s == ConnectionState.READY
                await self._state_changed_evt.wait()
        if timeout is None:
            return await _wait()
        return await asyncio.wait_for(_wait(), timeout=timeout)

    async def close(self) -> None:
        if self._state == ConnectionState.SHUTDOWN:
            return
        await self._transition(ConnectionState.SHUTDOWN, StateChangeInfo(
            reason="user close()", last_error_code=ErrorCode.CANCELLED,
        ))

        current = asyncio.current_task()
        if (self._reconnect_task and not self._reconnect_task.done() and
            self._reconnect_task is not current):
            self._reconnect_task.cancel()
        if (self._heartbeat_task and not self._heartbeat_task.done() and
            self._heartbeat_task is not current):
            self._heartbeat_task.cancel()
        for rid, entry in list(self._inflight.items()):
            if entry.timeout_handle:
                entry.timeout_handle.cancel()
            if not entry.future.done():
                entry.future.set_exception(
                    SdkException(ErrorCode.CANCELLED, "Robot.close()"))
        self._inflight.clear()
        for h in self._sub_ack_timers.values():
            h.cancel()
        self._sub_ack_timers.clear()
        self._inflight_sub.clear()

        for slot in self._subs.values():
            if slot.state != SubscriptionState.CLOSED:
                slot.state = SubscriptionState.CLOSED
                slot.error_code = ErrorCode.CANCELLED
                await self._fire_status(slot, StreamStatusKind.CLOSED,
                                        error_code=ErrorCode.CANCELLED,
                                        reason="Robot.close()")
            self._stop_sub_worker(slot)
        self._subs.clear()
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def _transition(self, new_state: ConnectionState, info: StateChangeInfo) -> None:
        old = self._state
        if old == new_state:
            return
        self._state = new_state
        self._last_state_change_ms = _now_ms()
        if info.last_error_code != ErrorCode.OK:
            self._last_error_code = info.last_error_code
            self._last_error_msg = info.last_error_message
        info.reconnect_attempt = self._reconnect_attempt
        await self._post_log(LogLevel.INFO,
            f"state transition {old} -> {new_state}" +
            (f" ({info.reason})" if info.reason else ""))
        await self._post_state_callback(old, new_state, info)

        self._state_changed_evt.set()

    async def _post_state_callback(
        self, old: ConnectionState, new: ConnectionState, info: StateChangeInfo
    ) -> None:
        h = self._connection_state_handler
        if h is None:
            return
        async def _dispatch():
            try:
                await _maybe_await(h(old, new, info))
            except Exception:
                pass

        asyncio.create_task(_dispatch(), name="state-handler")

    async def _post_log(self, level: LogLevel, msg: str) -> None:
        h = self._log_handler
        if h is None:

            import sys
            level_str = str(level).lower()
            min_level_str = os.environ.get("KARO_SDK_LOG_LEVEL", "info").lower()
            level_order = {"trace": 0, "debug": 1, "info": 2, "warn": 3, "error": 4, "off": 5}
            if level_order.get(level_str, 2) >= level_order.get(min_level_str, 2):
                print(f"[karo-x2-sdk {level_str}] {msg}", file=sys.stderr)
            return
        async def _dispatch():
            try:
                await _maybe_await(h(level, msg))
            except Exception:
                pass
        asyncio.create_task(_dispatch(), name="log-handler")

    async def _abort_to_fatal(self, code: ErrorCode, message: str) -> None:
        for slot in list(self._subs.values()):
            if slot.state != SubscriptionState.CLOSED:
                slot.state = SubscriptionState.CLOSED
                slot.error_code = code
                await self._fire_status(slot, StreamStatusKind.CLOSED,
                                        error_code=code, reason=message or "Fatal")
            self._stop_sub_worker(slot)
        self._subs.clear()
        for rid, entry in list(self._inflight.items()):
            if entry.timeout_handle:
                entry.timeout_handle.cancel()
            if not entry.future.done():
                entry.future.set_exception(SdkException(code, message))
        self._inflight.clear()
        for h in self._sub_ack_timers.values():
            h.cancel()
        self._sub_ack_timers.clear()
        self._inflight_sub.clear()
        current = asyncio.current_task()
        if (self._heartbeat_task and not self._heartbeat_task.done() and
            self._heartbeat_task is not current):
            self._heartbeat_task.cancel()
        if (self._reconnect_task and not self._reconnect_task.done() and
            self._reconnect_task is not current):
            self._reconnect_task.cancel()
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
        await self._transition(ConnectionState.FATAL, StateChangeInfo(
            reason=message, last_error_code=code, last_error_message=message,
        ))

    async def _establish(self, is_reconnect: bool) -> None:
        if not is_reconnect:
            if self._state != ConnectionState.IDLE:
                return
            await self._transition(ConnectionState.CONNECTING, StateChangeInfo(
                reason="connect()", last_error_code=ErrorCode.OK,
            ))
        else:
            if self._state != ConnectionState.RECONNECTING:
                return

        ws = WsClient(
            host=self.opts.host,
            port=4434,
            cert_pem=self.opts.cert.cert_pem,
            key_pem=self.opts.cert.key_pem,
            ca_pem=self.opts.cert.ca_pem,
            insecure_skip_verify=self.opts.cert.insecure_skip_verify,
        )
        try:
            await ws.connect(timeout=self.opts.connect_timeout)
        except SdkException as e:
            cat = classify(e.code)
            if cat == ErrorCategory.FATAL:
                await self._abort_to_fatal(e.code, f"ws connect fatal: {e}")
                return

            await self._transition(ConnectionState.TRANSIENT_FAILURE, StateChangeInfo(
                reason="ws connect failed",
                last_error_code=e.code, last_error_message=str(e),
                next_retry_in_ms=self._next_backoff_ms(self._reconnect_attempt),
            ))
            self._schedule_reconnect(self._reconnect_attempt + 1)
            return

        ws.on_message = self._on_inbound_message
        ws.on_close = self._on_transport_close
        self._ws = ws
        if not is_reconnect:
            self._bytes_sent = 0
            self._bytes_received = 0

        hs_rid = self._next_rid()
        try:

            from ..robot import sdk_version as _sdk_default_version
            default_ver = _sdk_default_version()
            if self.opts.cert.cert_pem:
                der = pc.pem_to_der(self.opts.cert.cert_pem)
                hs_bytes = pc.encode_handshake_cert(
                    hs_rid,
                    self.opts.sdk_version or default_ver,
                    self.opts.client_id, der,
                )
            else:
                hs_bytes = pc.encode_handshake_token(
                    hs_rid,
                    self.opts.sdk_version or default_ver,
                    self.opts.client_id,
                    self.opts.access_token.token,
                )
        except SdkException as e:
            await self._abort_to_fatal(e.code, f"handshake encode: {e}")
            return

        try:
            resp = await self._send_rpc_and_wait(
                hs_rid, "handshake", hs_bytes,
                timeout=self.opts.connect_timeout,
            )
        except asyncio.TimeoutError:
            await self._transition(ConnectionState.TRANSIENT_FAILURE, StateChangeInfo(
                reason="handshake timeout",
                last_error_code=ErrorCode.TIMEOUT,
                next_retry_in_ms=self._next_backoff_ms(self._reconnect_attempt),
            ))
            if self._ws is not None:
                await self._ws.close()
                self._ws = None
            self._schedule_reconnect(self._reconnect_attempt + 1)
            return
        except SdkException as e:
            cat = classify(e.code)
            if cat == ErrorCategory.FATAL:
                await self._abort_to_fatal(e.code, f"handshake error: {e}")
                return
            await self._transition(ConnectionState.TRANSIENT_FAILURE, StateChangeInfo(
                reason="handshake transport failed",
                last_error_code=e.code, last_error_message=str(e),
                next_retry_in_ms=self._next_backoff_ms(self._reconnect_attempt),
            ))
            if self._ws is not None:
                await self._ws.close()
                self._ws = None
            self._schedule_reconnect(self._reconnect_attempt + 1)
            return

        if not resp.success or not resp.has_handshake:
            code = resp.sdk_code if not resp.success else ErrorCode.INTERNAL_ERROR
            cat = classify(code)
            if cat == ErrorCategory.FATAL:
                await self._abort_to_fatal(code, f"handshake rejected: {resp.message}")
                return
            await self._transition(ConnectionState.TRANSIENT_FAILURE, StateChangeInfo(
                reason="handshake failed",
                last_error_code=code, last_error_message=resp.message,
                next_retry_in_ms=self._next_backoff_ms(self._reconnect_attempt),
            ))
            if self._ws is not None:
                await self._ws.close()
                self._ws = None
            self._schedule_reconnect(self._reconnect_attempt + 1)
            return

        from ..robot import RobotInfo
        self._robot_info = RobotInfo(
            sn=resp.robot_sn, model=resp.robot_model,
            protocol_version=resp.protocol_version,
            granted_capabilities=resp.granted_capabilities,
            available_topics=list(resp.available_topics),
        )

        self._start_heartbeat()

        for slot in self._subs.values():
            slot.semantics = self._resolve_semantics(slot.topic)

        if not is_reconnect:
            await self._transition(ConnectionState.READY, StateChangeInfo(
                reason="handshake ok", last_error_code=ErrorCode.OK,
            ))

            for topic, slot in list(self._subs.items()):
                if slot.state == SubscriptionState.PENDING and slot.inflight_subscribe_request_id == 0:
                    await self._send_subscribe(slot, since_seq=0)
            return

        self._reconnect_subs_pending = len(self._subs)
        self._reconnect_estop_pending = (self._last_estop_intent == "engaged")
        if self._reconnect_subs_pending == 0 and not self._reconnect_estop_pending:
            self._reconnect_attempt = 0
            self._reconnect_total_count += 1
            await self._transition(ConnectionState.READY, StateChangeInfo(
                reason="reconnect ok", last_error_code=ErrorCode.OK,
            ))
            return
        await self._resubscribe_all_after_reconnect()
        if self._reconnect_estop_pending:
            asyncio.create_task(self._do_estop_replay(), name="estop-replay")

    async def _on_inbound_message(self, data: bytes) -> None:
        self._bytes_received += len(data)
        self._reset_liveness_on_inbound()

        resp = pc.decode_response(data)

        if resp is not None and (resp.has_handshake or resp.has_rpc or resp.has_subscribe or
                                 resp.request_id != 0):
            await self._handle_sdk_response(resp)
            return
        push = pc.decode_topic_push(data)
        if push is not None and push.topic:
            await self._handle_sdk_topic_push(push)
            return
        await self._post_log(LogLevel.WARN, f"unknown wire message ({len(data)} bytes)")

    async def _on_transport_close(self, reason: ErrorCode, msg: str) -> None:
        s = self._state
        if s in (ConnectionState.SHUTDOWN, ConnectionState.FATAL):
            return

        for slot in self._subs.values():
            prev = slot.state
            if prev in (SubscriptionState.ACTIVE, SubscriptionState.PENDING):
                slot.state = SubscriptionState.PAUSED
                await self._fire_status(slot, StreamStatusKind.PAUSED,
                                        error_code=reason, reason=msg)
            slot.pending_buffer.clear()
            slot.inflight_subscribe_request_id = 0

        for rid, entry in list(self._inflight.items()):
            if entry.timeout_handle:
                entry.timeout_handle.cancel()
            if not entry.future.done():
                entry.future.set_exception(SdkException(reason, msg))
        self._inflight.clear()
        for h in self._sub_ack_timers.values():
            h.cancel()
        self._sub_ack_timers.clear()
        self._inflight_sub.clear()

        current = asyncio.current_task()
        if (self._heartbeat_task and not self._heartbeat_task.done() and
            self._heartbeat_task is not current):
            self._heartbeat_task.cancel()
        self._miss_count = 0

        await self._transition(ConnectionState.TRANSIENT_FAILURE, StateChangeInfo(
            reason=msg or "transport closed",
            last_error_code=reason, last_error_message=msg,
            next_retry_in_ms=self._next_backoff_ms(self._reconnect_attempt),
        ))

        if self._ws is not None:
            await self._ws.close()
            self._ws = None
        self._schedule_reconnect(self._reconnect_attempt + 1)

    async def _handle_sdk_response(self, resp: DecodedResponse) -> None:

        if resp.has_subscribe:
            await self._handle_subscribe_ack(resp)
            return

        entry = self._inflight.pop(resp.request_id, None)
        if entry is None:
            await self._post_log(LogLevel.DEBUG,
                f"response for unknown request_id={resp.request_id}")
            return
        if entry.timeout_handle:
            entry.timeout_handle.cancel()
        if not entry.future.done():
            entry.future.set_result(resp)

    async def _handle_sdk_topic_push(self, push: DecodedTopicPush) -> None:
        slot = self._subs.get(push.topic)
        if slot is None:
            await self._post_log(LogLevel.DEBUG,
                f"topic push for unknown sub: {push.topic}")
            return
        if slot.state == SubscriptionState.CLOSED:
            return

        if slot.state == SubscriptionState.PENDING:
            if len(slot.pending_buffer) >= slot.queue_size:
                if slot.drop_policy == DropPolicy.DROP_NEWEST:
                    slot.drop_count += 1
                    return

                slot.pending_buffer.popleft()
                slot.drop_count += 1
            slot.pending_buffer.append(push)
            return
        if slot.state == SubscriptionState.PAUSED:
            slot.drop_count += 1
            return
        await self._deliver_push_to_sub(slot, push)

    async def _deliver_push_to_sub(self, slot: SubSlot, push: DecodedTopicPush) -> None:

        if slot.semantics == DeliverySemantics.EVENT:
            new_seq = push.seq
            last = slot.last_seq
            if new_seq == 0:
                pass
            elif last == 0:
                slot.last_seq = new_seq
            elif new_seq == last + 1:
                slot.last_seq = new_seq
            elif new_seq > last + 1:
                gap = new_seq - last - 1
                slot.last_seq = new_seq
                await self._fire_status(slot, StreamStatusKind.GAP, gap_count=gap)
            elif new_seq == last:
                await self._post_log(LogLevel.DEBUG,
                    f"duplicate envelope seq, dropping: {slot.topic}")
                return
            else:
                await self._post_log(LogLevel.WARN,
                    f"envelope seq regression in-session: {slot.topic} "
                    f"new={new_seq} last={last}")
                return

        slot.messages_received += 1
        slot.last_message_at = _now_steady()

        cur_sec = self._slide_hz_buckets(slot)
        slot.hz_buckets[cur_sec % 60] += 1

        if slot.callback_mode == CallbackMode.INLINE:

            if slot.frame_dispatcher is not None:
                try:
                    await slot.frame_dispatcher(push)
                except Exception:
                    pass
            return

        if slot.dispatch_queue is None:
            return
        q = slot.dispatch_queue
        if q.full():
            if slot.drop_policy == DropPolicy.DROP_OLDEST:
                try:
                    q.get_nowait()
                    slot.drop_count += 1
                except asyncio.QueueEmpty:
                    pass
                q.put_nowait(push)
            else:
                slot.drop_count += 1
                return
        else:
            q.put_nowait(push)

    async def _sub_dispatch_worker(self, slot: SubSlot) -> None:
        try:
            while True:

                if slot.state == SubscriptionState.CLOSED or slot.dispatch_queue is None:
                    return
                try:
                    push = await slot.dispatch_queue.get()
                except (AttributeError, RuntimeError):
                    return
                if push is None:
                    return
                if slot.state == SubscriptionState.CLOSED:
                    return
                if slot.frame_dispatcher is None:
                    continue
                try:
                    await slot.frame_dispatcher(push)
                except Exception:
                    pass
        except asyncio.CancelledError:
            pass

    def _start_sub_worker(self, slot: SubSlot) -> None:
        if slot.callback_mode == CallbackMode.INLINE:
            return
        if slot.dispatch_queue is None:
            slot.dispatch_queue = asyncio.Queue(maxsize=slot.queue_size)
        if slot.dispatch_worker is None or slot.dispatch_worker.done():
            slot.dispatch_worker = asyncio.create_task(
                self._sub_dispatch_worker(slot),
                name=f"sub-worker-{slot.topic}",
            )

    def _slide_hz_buckets(self, slot: SubSlot) -> int:
        epoch_ms = _now_ms()
        cur_sec = epoch_ms // 1000
        last_sec = slot.hz_last_epoch_ms // 1000
        if cur_sec == last_sec and slot.hz_last_epoch_ms > 0:
            return cur_sec
        if slot.hz_last_epoch_ms == 0:
            slot.hz_last_epoch_ms = epoch_ms
            return cur_sec
        gap = min(60, cur_sec - last_sec)
        for i in range(1, gap + 1):
            slot.hz_buckets[(last_sec + i) % 60] = 0
        slot.hz_last_epoch_ms = epoch_ms
        return cur_sec

    def _stop_sub_worker(self, slot: SubSlot) -> None:
        worker = slot.dispatch_worker
        if worker is not None and not worker.done():
            current = asyncio.current_task()
            if worker is not current:
                worker.cancel()

    async def _close_slot(
        self, slot: SubSlot, code: ErrorCode, reason: str = "",
        kind: StreamStatusKind = StreamStatusKind.CLOSED,
    ) -> None:
        if slot.state == SubscriptionState.CLOSED:
            return
        slot.state = SubscriptionState.CLOSED
        slot.error_code = code
        await self._fire_status(slot, kind, error_code=code, reason=reason)
        self._stop_sub_worker(slot)
        self._subs.pop(slot.topic, None)

    def _resolve_semantics(self, topic: str) -> DeliverySemantics:
        if self._robot_info is not None:
            for d in self._robot_info.available_topics:
                if d.name == topic:
                    return d.delivery_semantics
        return DeliverySemantics.TELEMETRY

    async def subscribe_generic(
        self, topic: str, desired_hz: float,
        on_data, on_status,
    ) -> Subscription:
        slot = SubSlot(
            topic=topic, desired_hz=desired_hz,
            semantics=self._resolve_semantics(topic),
            callback_mode=self.opts.callback_mode,
            drop_policy=self.opts.drop_policy,
            queue_size=self.opts.subscription_queue_size,
            status_callback=on_status,
        )

        async def _frame_dispatcher(push: DecodedTopicPush) -> None:
            m = TopicMessage(
                topic=push.topic, timestamp_ms=push.timestamp_ms,
                seq=push.seq, payload=push.payload,
            )
            await _maybe_await(on_data(m))
        slot.frame_dispatcher = _frame_dispatcher

        if slot.user_closed:
            slot.state = SubscriptionState.CLOSED
            return SubscriptionFacade(slot, self)
        if topic in self._subs:
            slot.state = SubscriptionState.CLOSED
            slot.error_code = ErrorCode.TOPIC_ALREADY_SUBSCRIBED
            await self._fire_status(slot, StreamStatusKind.CLOSED,
                                    error_code=ErrorCode.TOPIC_ALREADY_SUBSCRIBED,
                                    reason="already subscribed")
            return SubscriptionFacade(slot, self)
        self._subs[topic] = slot
        self._start_sub_worker(slot)
        if self._state == ConnectionState.READY:
            await self._send_subscribe(slot, since_seq=0)
        return SubscriptionFacade(slot, self)

    async def subscribe_robot_status(
        self, desired_hz: float, on_data, on_status,
    ) -> Subscription:
        topic = "robot.state"
        slot = SubSlot(
            topic=topic, desired_hz=desired_hz,
            semantics=self._resolve_semantics(topic),
            callback_mode=self.opts.callback_mode,
            drop_policy=self.opts.drop_policy,
            queue_size=self.opts.subscription_queue_size,
            status_callback=on_status,
        )

        async def _frame_dispatcher(push: DecodedTopicPush) -> None:
            rs = pc.decode_robot_status(push.payload)
            if rs is not None:
                rs.timestamp_ms = push.timestamp_ms
                await _maybe_await(on_data(rs))
        slot.frame_dispatcher = _frame_dispatcher

        if slot.user_closed:
            slot.state = SubscriptionState.CLOSED
            return SubscriptionFacade(slot, self)
        if topic in self._subs:
            slot.state = SubscriptionState.CLOSED
            slot.error_code = ErrorCode.TOPIC_ALREADY_SUBSCRIBED
            await self._fire_status(slot, StreamStatusKind.CLOSED,
                                    error_code=ErrorCode.TOPIC_ALREADY_SUBSCRIBED,
                                    reason="already subscribed")
            return SubscriptionFacade(slot, self)
        self._subs[topic] = slot
        self._start_sub_worker(slot)
        if self._state == ConnectionState.READY:
            await self._send_subscribe(slot, since_seq=0)
        return SubscriptionFacade(slot, self)

    async def _send_subscribe(self, slot: SubSlot, since_seq: int) -> None:
        rid = self._next_rid()
        try:
            effective_since = since_seq
            if slot.semantics == DeliverySemantics.TELEMETRY:
                effective_since = 0
            bytes_ = pc.encode_subscribe(
                rid, slot.topic, slot.desired_hz,
                effective_since,
                self.opts.history_limit if effective_since > 0 else 0,
            )
            slot.expected_resume_seq = effective_since
        except Exception as e:
            slot.state = SubscriptionState.CLOSED
            slot.error_code = ErrorCode.INTERNAL_ERROR
            await self._fire_status(slot, StreamStatusKind.CLOSED,
                                    error_code=ErrorCode.INTERNAL_ERROR,
                                    reason=str(e))
            self._stop_sub_worker(slot)
            self._subs.pop(slot.topic, None)
            return

        old_state = slot.state
        slot.is_reconnect_resume = (
            old_state == SubscriptionState.PAUSED or
            (slot.ever_active and self._state == ConnectionState.RECONNECTING)
        )
        slot.state = SubscriptionState.PENDING
        slot.inflight_subscribe_request_id = rid
        self._inflight_sub[rid] = slot.topic

        def _on_ack_timeout():
            asyncio.create_task(self._handle_subscribe_ack_timeout(rid, slot.topic))
        handle = self._loop.call_later(self.opts.subscribe_ack_timeout, _on_ack_timeout)
        self._sub_ack_timers[rid] = handle

        if self._ws is None or not await self._ws.send(bytes_):

            handle.cancel()
            self._sub_ack_timers.pop(rid, None)
            self._inflight_sub.pop(rid, None)
            slot.inflight_subscribe_request_id = 0
            await self._on_transport_close(ErrorCode.TRANSPORT_FAILURE,
                                            "SendSubscribe failed")
            return
        self._bytes_sent += len(bytes_)

    async def _handle_subscribe_ack_timeout(self, rid: int, topic: str) -> None:

        if rid not in self._sub_ack_timers:
            return
        await self._post_log(LogLevel.WARN, f"SubscribeAck timeout for {topic}")
        await self._on_transport_close(ErrorCode.TIMEOUT, "SubscribeAck timeout")

    async def _resubscribe_all_after_reconnect(self) -> None:
        for topic, slot in list(self._subs.items()):
            slot.fresh_retry_done = False
            since = 0
            if (slot.semantics == DeliverySemantics.EVENT
                and self.opts.reconnect_replay_history
                and slot.last_seq > 0):
                since = slot.last_seq + 1
            await self._send_subscribe(slot, since_seq=since)

    async def _handle_subscribe_ack(self, resp: DecodedResponse) -> None:
        topic = self._inflight_sub.pop(resp.request_id, None)
        if topic is None:
            await self._post_log(LogLevel.DEBUG,
                f"SubscribeAck for unknown request_id={resp.request_id}")
            return
        handle = self._sub_ack_timers.pop(resp.request_id, None)
        if handle is not None:
            handle.cancel()

        slot = self._subs.get(topic)
        if slot is None:
            return
        if slot.inflight_subscribe_request_id != resp.request_id:
            return
        slot.inflight_subscribe_request_id = 0

        is_reconnect_phase = (self._state == ConnectionState.RECONNECTING)

        async def _maybe_finish_reconnect():
            if is_reconnect_phase and self._reconnect_subs_pending > 0:
                self._reconnect_subs_pending -= 1
                if self._reconnect_subs_pending == 0 and not self._reconnect_estop_pending:
                    self._reconnect_attempt = 0
                    self._reconnect_total_count += 1
                    await self._transition(ConnectionState.READY, StateChangeInfo(
                        reason="reconnect ok", last_error_code=ErrorCode.OK,
                    ))

        if not resp.success:
            cat = classify(resp.sdk_code)
            if cat == ErrorCategory.FATAL:
                await self._abort_to_fatal(resp.sdk_code, f"subscribe fatal: {resp.message}")
                return
            if cat == ErrorCategory.TRANSIENT:
                if is_reconnect_phase:
                    await self._on_transport_close(resp.sdk_code, resp.message)
                else:
                    slot.state = SubscriptionState.CLOSED
                    slot.error_code = resp.sdk_code
                    await self._fire_status(slot, StreamStatusKind.CLOSED,
                                            error_code=resp.sdk_code, reason=resp.message)
                    self._stop_sub_worker(slot)
                    self._subs.pop(topic, None)
                return

            slot.state = SubscriptionState.CLOSED
            slot.error_code = resp.sdk_code
            await self._fire_status(slot, StreamStatusKind.CLOSED,
                                    error_code=resp.sdk_code, reason=resp.message)
            self._stop_sub_worker(slot)
            self._subs.pop(topic, None)
            await _maybe_finish_reconnect()
            return

        if slot.semantics == DeliverySemantics.TELEMETRY:
            if not resp.sub_accepted:
                err = reject_reason_to_error(resp.sub_reject_reason)
                slot.state = SubscriptionState.CLOSED
                slot.error_code = err
                await self._fire_status(slot, StreamStatusKind.CLOSED,
                                        error_code=err, reason=resp.sub_message)
                self._stop_sub_worker(slot)
                self._subs.pop(topic, None)
                await _maybe_finish_reconnect()
                return
            slot.last_seq = 0
            slot.state = SubscriptionState.ACTIVE

            if slot.is_reconnect_resume:
                await self._fire_status(slot, StreamStatusKind.RESUMED)
            else:
                await self._fire_status(slot, StreamStatusKind.STARTED)
            await self._drain_pending_buffer(slot, next_seq=0)
            slot.ever_active = True
            slot.is_reconnect_resume = False
            await _maybe_finish_reconnect()
            return

        if not resp.sub_accepted:
            if resp.sub_reject_reason in (SubscribeRejectReason.HISTORY_TOO_OLD,
                                          SubscribeRejectReason.REPLAY_NOT_SUPPORTED):
                if slot.fresh_retry_done:
                    slot.state = SubscriptionState.CLOSED
                    slot.error_code = ErrorCode.INTERNAL_ERROR
                    await self._fire_status(slot, StreamStatusKind.CLOSED,
                                            error_code=ErrorCode.INTERNAL_ERROR,
                                            reason="fresh subscribe rejected after replay fallback")
                    self._stop_sub_worker(slot)
                    self._subs.pop(topic, None)
                    await _maybe_finish_reconnect()
                    return

                slot.last_seq = 0
                slot.fresh_retry_done = True
                await self._send_subscribe(slot, since_seq=0)
                return
            err = reject_reason_to_error(resp.sub_reject_reason)
            slot.state = SubscriptionState.CLOSED
            slot.error_code = err
            await self._fire_status(slot, StreamStatusKind.CLOSED,
                                    error_code=err, reason=resp.sub_message)
            self._stop_sub_worker(slot)
            self._subs.pop(topic, None)
            await _maybe_finish_reconnect()
            return

        K = resp.sub_next_seq
        expected = slot.expected_resume_seq
        is_resume = slot.is_reconnect_resume
        kind = StreamStatusKind.STARTED
        gap = None

        if expected == 0:
            if K >= 1:
                slot.last_seq = K - 1
            else:
                slot.last_seq = 0
            if is_resume:
                kind = StreamStatusKind.RESUMED
            else:
                kind = StreamStatusKind.STARTED
        else:
            if K == expected:
                kind = StreamStatusKind.RESUMED
                gap = 0
            elif K > expected:
                gap_count = K - expected
                slot.last_seq = K - 1
                kind = StreamStatusKind.RESUMED
                gap = gap_count
            else:
                slot.last_seq = (K - 1) if K >= 1 else 0
                kind = StreamStatusKind.RESUMED

        slot.state = SubscriptionState.ACTIVE
        await self._fire_status(slot, kind, gap_count=gap)
        await self._drain_pending_buffer(slot, next_seq=K)
        slot.ever_active = True
        slot.is_reconnect_resume = False
        await _maybe_finish_reconnect()

    async def _drain_pending_buffer(self, slot: SubSlot, next_seq: int) -> None:
        while slot.pending_buffer:
            front = slot.pending_buffer.popleft()
            if (slot.semantics == DeliverySemantics.EVENT and
                next_seq > 0 and front.seq != 0 and front.seq < next_seq):
                slot.drop_count += 1
                continue
            await self._deliver_push_to_sub(slot, front)

    async def _fire_status(
        self, slot: SubSlot, kind: StreamStatusKind,
        gap_count: Optional[int] = None,
        error_code: ErrorCode = ErrorCode.OK,
        reason: str = "",
    ) -> None:
        s = StreamStatus(kind=kind, gap_count=gap_count, error_code=error_code, reason=reason)
        cb = slot.status_callback
        if cb is None:
            return
        async def _dispatch():
            try:
                await _maybe_await(cb(s))
            except Exception:
                pass
        asyncio.create_task(_dispatch(), name=f"sub-status-{slot.topic}")

    async def unsubscribe_request(self, topic: str, sync_wait: bool) -> ErrorCode:
        slot = self._subs.get(topic)
        if slot is None:
            return ErrorCode.OK

        if self._state != ConnectionState.READY or self._ws is None or not self._ws.is_open:

            slot.state = SubscriptionState.CLOSED
            slot.error_code = ErrorCode.DISCONNECTED
            await self._fire_status(slot, StreamStatusKind.CLOSED,
                                    error_code=ErrorCode.DISCONNECTED,
                                    reason="Unsubscribe() while disconnected")
            self._stop_sub_worker(slot)
            self._subs.pop(topic, None)
            return ErrorCode.DISCONNECTED if sync_wait else ErrorCode.OK

        rid = self._next_rid()
        bytes_ = pc.encode_unsubscribe(rid, topic)

        if not sync_wait:

            if await self._ws.send(bytes_):
                self._bytes_sent += len(bytes_)
                slot.unsubscribe_sent = True
            slot.state = SubscriptionState.CLOSED
            slot.error_code = ErrorCode.OK
            await self._fire_status(slot, StreamStatusKind.CLOSED, reason="Unsubscribe()")
            self._stop_sub_worker(slot)
            self._subs.pop(topic, None)
            await self._post_log(LogLevel.WARN,
                f"subscription dropped without explicit unsubscribe() — topic={topic}")
            return ErrorCode.OK

        try:
            resp = await self._send_rpc_and_wait(
                rid, "unsubscribe", bytes_,
                timeout=self.opts.subscribe_ack_timeout,
            )
            slot.unsubscribe_sent = True
            err = ErrorCode.OK if resp.success else resp.sdk_code
            slot.state = SubscriptionState.CLOSED
            slot.error_code = err
            await self._fire_status(slot, StreamStatusKind.CLOSED,
                                    error_code=err, reason=resp.message)
            self._stop_sub_worker(slot)
            self._subs.pop(topic, None)
            return err
        except asyncio.TimeoutError:
            slot.state = SubscriptionState.CLOSED
            slot.error_code = ErrorCode.TIMEOUT
            await self._fire_status(slot, StreamStatusKind.CLOSED,
                                    error_code=ErrorCode.TIMEOUT,
                                    reason="Unsubscribe timeout")
            self._stop_sub_worker(slot)
            self._subs.pop(topic, None)
            return ErrorCode.TIMEOUT
        except SdkException as e:

            slot.state = SubscriptionState.CLOSED
            slot.error_code = e.code
            await self._fire_status(slot, StreamStatusKind.CLOSED,
                                    error_code=e.code, reason=str(e))
            self._stop_sub_worker(slot)
            self._subs.pop(topic, None)
            return e.code

    def schedule_fire_and_forget_unsubscribe(self, topic: str) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(
            self.unsubscribe_request(topic, sync_wait=False), loop,
        )

    async def cmd_vel(self, vx: float, vy: float, wz: float):
        from ..robot import CmdVelResult
        if self._state != ConnectionState.READY:
            self._rpc_stats["cmd_vel"]["error_count"] += 1
            return CmdVelResult(
                accepted=False, code=ErrorCode.DISCONNECTED,
                message="Robot is not Ready",
            )
        if not self._cmdvel_rate.try_acquire():
            self._rpc_stats["cmd_vel"]["error_count"] += 1
            return CmdVelResult(
                accepted=False, code=ErrorCode.RATE_LIMITED,
                message="client-side rate limit (20 Hz)",
            )
        self._rpc_stats["cmd_vel"]["count"] += 1
        rid = self._next_rid()

        if not hasattr(self, "_cmdvel_seq"):
            self._cmdvel_seq = 0
        self._cmdvel_seq += 1
        bytes_ = pc.encode_cmd_vel(rid, vx, vy, wz, self._cmdvel_seq, _now_ms())
        t0 = _now_steady()
        try:
            resp = await self._send_rpc_and_wait(
                rid, "control.cmd_vel", bytes_,
                timeout=self.opts.cmdvel_rpc_timeout,
            )
            rtt_ms = int((_now_steady() - t0) * 1000)
            self._rpc_stats["cmd_vel"]["hist"].record(rtt_ms)
            if not resp.success:
                self._rpc_stats["cmd_vel"]["error_count"] += 1
                return CmdVelResult(accepted=False, code=resp.sdk_code,
                                    message=resp.message, rtt_ms=rtt_ms)

            if not resp.has_rpc:
                self._rpc_stats["cmd_vel"]["error_count"] += 1
                return CmdVelResult(accepted=False, code=ErrorCode.INTERNAL_ERROR,
                                    message="missing rpc payload in response",
                                    rtt_ms=rtt_ms)
            if resp.rpc_code != ErrorCode.OK:
                self._rpc_stats["cmd_vel"]["error_count"] += 1
                return CmdVelResult(accepted=False, code=resp.rpc_code,
                                    message=resp.rpc_message, rtt_ms=rtt_ms)
            return CmdVelResult(accepted=True, code=ErrorCode.OK, rtt_ms=rtt_ms)
        except asyncio.TimeoutError:
            self._rpc_stats["cmd_vel"]["error_count"] += 1
            return CmdVelResult(accepted=False, code=ErrorCode.TIMEOUT,
                                message="cmd_vel timeout")
        except SdkException as e:
            self._rpc_stats["cmd_vel"]["error_count"] += 1
            return CmdVelResult(accepted=False, code=e.code, message=str(e))

    async def emergency_stop_rpc(self, engage: bool, reason: str):
        from ..robot import EmergencyStopResult
        if self._state != ConnectionState.READY:
            return EmergencyStopResult(
                ok=False, code=ErrorCode.DISCONNECTED, message="Robot is not Ready")
        self._rpc_stats["emergency_stop"]["count"] += 1
        rid = self._next_rid()
        bytes_ = pc.encode_emergency_stop(rid, engage, reason)
        t0 = _now_steady()
        try:
            resp = await self._send_rpc_and_wait(
                rid, "safety.emergency_stop", bytes_,
                timeout=self.opts.estop_rpc_timeout,
            )
            self._rpc_stats["emergency_stop"]["hist"].record(
                int((_now_steady() - t0) * 1000))
            if not resp.success:
                self._rpc_stats["emergency_stop"]["error_count"] += 1
                return EmergencyStopResult(ok=False, code=resp.sdk_code,
                                            message=resp.message)

            if not resp.has_rpc:
                self._rpc_stats["emergency_stop"]["error_count"] += 1
                return EmergencyStopResult(ok=False, code=ErrorCode.INTERNAL_ERROR,
                                            message="missing rpc payload in response")
            if resp.rpc_code != ErrorCode.OK:
                self._rpc_stats["emergency_stop"]["error_count"] += 1
                return EmergencyStopResult(ok=False, code=resp.rpc_code,
                                            message=resp.rpc_message)

            self._last_estop_intent = "engaged" if engage else "none"
            self._last_estop_reason = reason
            return EmergencyStopResult(ok=True, code=ErrorCode.OK)
        except asyncio.TimeoutError:
            self._rpc_stats["emergency_stop"]["error_count"] += 1
            return EmergencyStopResult(ok=False, code=ErrorCode.TIMEOUT,
                                        message="estop timeout")
        except SdkException as e:

            self._rpc_stats["emergency_stop"]["error_count"] += 1
            return EmergencyStopResult(ok=False, code=e.code, message=str(e))

    async def ping(self) -> float:
        if self._state != ConnectionState.READY:
            return -1.0
        self._rpc_stats["ping"]["count"] += 1
        rid = self._next_rid()
        bytes_ = pc.encode_ping(rid, _now_ms())
        t0 = _now_steady()
        try:
            await self._send_rpc_and_wait(
                rid, "ping", bytes_, timeout=self.opts.ping_timeout,
            )
            rtt_s = _now_steady() - t0
            self._rtt_hist.record(rtt_s * 1000)
            self._last_ping_sent_ms = _now_ms()
            return rtt_s
        except (asyncio.TimeoutError, SdkException):
            self._rpc_stats["ping"]["error_count"] += 1
            return -1.0

    async def _send_rpc_and_wait(
        self, rid: int, method: str, bytes_: bytes, timeout: float,
    ) -> DecodedResponse:
        if self._ws is None:
            raise SdkException(ErrorCode.TRANSPORT_FAILURE, "ws not open")
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[DecodedResponse] = loop.create_future()

        def _on_timeout():
            entry = self._inflight.pop(rid, None)
            if entry is not None and not entry.future.done():
                entry.future.set_exception(asyncio.TimeoutError())

        timeout_handle = loop.call_later(timeout, _on_timeout)
        self._inflight[rid] = _InflightRpc(rid, method, fut, timeout_handle, _now_steady())

        if not await self._ws.send(bytes_):
            self._inflight.pop(rid, None)
            timeout_handle.cancel()
            raise SdkException(ErrorCode.TRANSPORT_FAILURE, "ws send failed")
        self._bytes_sent += len(bytes_)
        return await fut

    def _start_heartbeat(self) -> None:
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
        self._last_inbound = _now_steady()
        self._miss_count = 0
        if self.opts.heartbeat_interval <= 0:
            return
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(), name="heartbeat")

    async def _heartbeat_loop(self) -> None:
        try:
            while self._state == ConnectionState.READY:
                idle = _now_steady() - self._last_inbound
                if idle < self.opts.heartbeat_interval:

                    try:
                        await asyncio.wait_for(
                            self._heartbeat_wakeup.wait(),
                            timeout=self.opts.heartbeat_interval - idle,
                        )
                        self._heartbeat_wakeup.clear()
                    except asyncio.TimeoutError:
                        pass
                    continue

                if self._ws is None or not self._ws.is_open:
                    return

                await self._send_and_wait_ping()
        except asyncio.CancelledError:
            pass

    async def _send_and_wait_ping(self) -> None:
        for _ in range(self.opts.max_missed_pings + 1):
            if self._state != ConnectionState.READY:
                return
            if self._ws is None or not self._ws.is_open:
                return
            rid = self._next_rid()
            self._last_ping_request_id = rid
            self._last_ping_sent_ms = _now_ms()
            send_t = _now_steady()
            bytes_ = pc.encode_ping(rid, _now_ms())

            loop = asyncio.get_running_loop()
            fut: asyncio.Future[DecodedResponse] = loop.create_future()
            self._inflight[rid] = _InflightRpc(rid, "ping", fut, None, send_t)
            self._ping_deadline_evt.clear()
            ok = await self._ws.send(bytes_)
            if not ok:
                self._inflight.pop(rid, None)
                await self._on_transport_close(ErrorCode.TRANSPORT_FAILURE,
                                                "heartbeat send failed")
                return
            self._bytes_sent += len(bytes_)
            try:
                await asyncio.wait_for(
                    self._wait_ping_or_inbound(fut),
                    timeout=self.opts.ping_timeout,
                )

                rtt_ms = (_now_steady() - send_t) * 1000

                if fut.done() and not fut.cancelled():
                    self._rtt_hist.record(rtt_ms)
                self._miss_count = 0
                self._inflight.pop(rid, None)
                return
            except asyncio.TimeoutError:
                self._inflight.pop(rid, None)
                self._miss_count += 1
                if self._miss_count >= self.opts.max_missed_pings:
                    await self._post_log(LogLevel.WARN,
                        f"heartbeat miss_count={self._miss_count}, declaring dead")
                    await self._on_transport_close(ErrorCode.TRANSPORT_FAILURE,
                                                    "heartbeat dead")
                    return

                continue

    async def _wait_ping_or_inbound(self, ping_fut: "asyncio.Future") -> None:
        evt_wait = asyncio.ensure_future(self._ping_deadline_evt.wait())
        ping_wait = asyncio.ensure_future(asyncio.shield(ping_fut))
        try:
            done, pending = await asyncio.wait(
                {evt_wait, ping_wait},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()

        finally:
            if not evt_wait.done():
                evt_wait.cancel()
            if not ping_wait.done():
                ping_wait.cancel()

    def _reset_liveness_on_inbound(self) -> None:
        self._last_inbound = _now_steady()
        self._miss_count = 0

        if hasattr(self, "_ping_deadline_evt"):
            self._ping_deadline_evt.set()
        if hasattr(self, "_heartbeat_wakeup"):
            self._heartbeat_wakeup.set()

    def _next_backoff_ms(self, attempt: int) -> int:
        base = self.opts.reconnect_base_delay * 1000
        mx = self.opts.reconnect_max_delay * 1000
        exp = base
        for _ in range(attempt):
            if exp >= mx:
                break
            exp *= 2
        if exp > mx:
            exp = mx
        jr = max(0.05, self.opts.reconnect_jitter_ratio)
        j = exp * jr * self._rng.random()
        actual = exp - j
        if actual < 0:
            actual = 0
        return int(actual)

    def _schedule_reconnect(self, attempt: int) -> None:
        if self._state in (ConnectionState.FATAL, ConnectionState.SHUTDOWN):
            return
        if self.opts.reconnect_max_attempts >= 0 and attempt > self.opts.reconnect_max_attempts:
            asyncio.create_task(self._abort_to_fatal(
                ErrorCode.TRANSPORT_FAILURE, "reconnect_max_attempts reached"))
            return
        delay_ms = self._next_backoff_ms(attempt - 1)
        self._reconnect_attempt = attempt - 1

        async def _do_reconnect():
            try:
                await asyncio.sleep(delay_ms / 1000.0)
            except asyncio.CancelledError:
                return
            if self._state != ConnectionState.TRANSIENT_FAILURE:
                return
            self._reconnect_attempt = attempt
            await self._transition(ConnectionState.RECONNECTING, StateChangeInfo(
                reason="reconnecting", last_error_code=ErrorCode.OK,
            ))
            await self._establish(is_reconnect=True)

        self._reconnect_task = asyncio.create_task(_do_reconnect(), name="reconnect")

    async def _do_estop_replay(self) -> None:
        rid = self._next_rid()
        bytes_ = pc.encode_emergency_stop(
            rid, True,
            self._last_estop_reason + " [auto-replayed after reconnect]",
        )
        try:
            resp = await self._send_rpc_and_wait(
                rid, "safety.emergency_stop.replay", bytes_,
                timeout=self.opts.estop_rpc_timeout,
            )

            ok = resp.success and resp.has_rpc and resp.rpc_code == ErrorCode.OK
            self._reconnect_estop_pending = False
            if not ok:
                code = resp.rpc_code if resp.has_rpc and resp.rpc_code != ErrorCode.OK else resp.sdk_code
                await self._on_transport_close(code, "estop replay failed")
                return
            if self._reconnect_subs_pending == 0:
                self._reconnect_attempt = 0
                self._reconnect_total_count += 1
                await self._transition(ConnectionState.READY, StateChangeInfo(
                    reason="reconnect ok (estop replayed)",
                    last_error_code=ErrorCode.OK,
                    last_action="estop_replay_ok",
                ))
        except (asyncio.TimeoutError, SdkException) as e:
            self._reconnect_estop_pending = False
            await self._on_transport_close(ErrorCode.TIMEOUT, "estop replay timeout")
            _ = e

    async def get_diagnostics(self) -> Diagnostics:
        d = Diagnostics()
        d.connection.state = self._state
        d.connection.last_state_change_ms = self._last_state_change_ms
        d.connection.reconnect_count = self._reconnect_total_count
        d.connection.last_error_code = self._last_error_code
        d.connection.last_error_message = self._last_error_msg
        if self._robot_info is not None:
            d.connection.server_protocol_version = self._robot_info.protocol_version
        d.transport.rtt_p50_ms = self._rtt_hist.p50_ms()
        d.transport.rtt_p99_ms = self._rtt_hist.p99_ms()
        d.transport.bytes_sent = self._bytes_sent
        d.transport.bytes_received = self._bytes_received
        d.transport.last_ping_age_ms = (
            _now_ms() - self._last_ping_sent_ms
            if self._last_ping_sent_ms >= 0 else -1
        )
        for topic, slot in self._subs.items():
            s = SubscriptionStat()
            s.topic = topic
            s.state = slot.state
            s.configured_hz = slot.desired_hz

            self._slide_hz_buckets(slot)
            s.received_hz_1min = sum(slot.hz_buckets) / 60.0
            s.drop_count = slot.drop_count
            s.last_seq = slot.last_seq
            s.last_message_age_ms = (
                int((_now_steady() - slot.last_message_at) * 1000)
                if slot.last_message_at > 0 else -1
            )
            d.subscriptions.append(s)
        for name in ("cmd_vel", "emergency_stop", "ping"):
            st = self._rpc_stats[name]
            r = RpcStat()
            r.name = name
            r.count = st["count"]
            r.error_count = st["error_count"]
            r.p99_latency_ms = st["hist"].p99_ms()
            d.rpcs.append(r)
        return d

    def _next_rid(self) -> int:
        rid = self._next_request_id
        self._next_request_id += 1
        return rid

