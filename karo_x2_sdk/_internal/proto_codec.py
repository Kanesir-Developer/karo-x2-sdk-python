from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Optional

from .proto_gen.sdk import common_pb2 as _sdk_common
from .proto_gen.sdk import session_pb2 as _sdk_session
from .proto_gen.sdk.v1 import telemetry_pb2 as _sdk_v1_telemetry
from .proto_gen.karo.v1 import (
    rpc_pb2 as _v1_rpc,
    control_pb2 as _v1_control,
    safety_pb2 as _v1_safety,
    tasks_pb2 as _v1_tasks,
    move_pb2 as _v1_move,
    patrol_pb2 as _v1_patrol,
    events_pb2 as _v1_events,
    telemetry_stream_pb2 as _v1_telemetry_stream,
)

from ..capabilities import Capabilities
from ..error import ErrorCode
from ..messages import (
    ChargeType,
    RobotStatus,
    SafetyEvent,
    ServiceState,
    TaskCancelReason,
    TaskEvent,
    TaskPauseReason,
    TaskState,
    TaskType,
)
from ..topic import DeliverySemantics, TopicDescriptor

class SubscribeRejectReason(IntEnum):
    NONE = 0
    TOPIC_NOT_FOUND = 1
    CAPABILITY_DENIED = 2
    ALREADY_SUBSCRIBED = 3
    INVALID_HZ = 4
    HISTORY_TOO_OLD = 10
    REPLAY_NOT_SUPPORTED = 11

    _UNKNOWN = -1

@dataclass
class DecodedResponse:
    request_id: int = 0
    success: bool = False
    sdk_code: ErrorCode = ErrorCode.OK
    message: str = ""
    server_ts_ms: int = 0

    has_handshake: bool = False
    has_rpc: bool = False
    has_subscribe: bool = False

    protocol_version: str = ""
    robot_sn: str = ""
    robot_model: str = ""
    session_token: str = ""
    granted_capabilities: Capabilities = field(default_factory=Capabilities)
    available_topics: List[TopicDescriptor] = field(default_factory=list)

    rpc_id: int = 0
    rpc_code: ErrorCode = ErrorCode.OK
    rpc_message: str = ""
    rpc_payload: bytes = b""

    sub_topic: str = ""
    sub_accepted: bool = False
    sub_reject_reason: SubscribeRejectReason = SubscribeRejectReason.NONE
    sub_next_seq: int = 0
    sub_message: str = ""

@dataclass
class DecodedTopicPush:
    topic: str = ""
    timestamp_ms: int = 0
    seq: int = 0
    payload: bytes = b""

@dataclass
class DecodedCmdVelResponse:
    accepted: bool = False
    device_timestamp_ms: int = 0

@dataclass
class DecodedPingResponse:
    client_timestamp_ms: int = 0
    server_timestamp_ms: int = 0
    protocol_version: str = ""
    device_sn: str = ""

def encode_handshake_cert(
    request_id: int,
    sdk_version: str,
    client_id: str,
    cert_der: bytes,
) -> bytes:
    cmd = _sdk_session.SdkCommand()
    cmd.request_id = request_id
    hs = cmd.handshake
    hs.sdk_version = sdk_version
    hs.client_id = client_id
    hs.certificate_der = cert_der
    return cmd.SerializeToString()

def encode_handshake_token(
    request_id: int,
    sdk_version: str,
    client_id: str,
    token: bytes,
) -> bytes:
    cmd = _sdk_session.SdkCommand()
    cmd.request_id = request_id
    hs = cmd.handshake
    hs.sdk_version = sdk_version
    hs.client_id = client_id
    hs.access_token = token
    return cmd.SerializeToString()

def encode_ping(request_id: int, client_ts_ms: int) -> bytes:
    cmd = _sdk_session.SdkCommand()
    cmd.request_id = request_id
    cmd.ping.client_timestamp_ms = client_ts_ms
    return cmd.SerializeToString()

def encode_subscribe(
    request_id: int,
    topic: str,
    desired_hz: float,
    since_seq: int,
    history_limit: int,
) -> bytes:
    cmd = _sdk_session.SdkCommand()
    cmd.request_id = request_id
    sub = cmd.subscribe
    sub.topic = topic
    sub.desired_hz = float(desired_hz)
    sub.since_seq = since_seq
    sub.history_limit = history_limit
    return cmd.SerializeToString()

def encode_unsubscribe(request_id: int, topic: str) -> bytes:
    cmd = _sdk_session.SdkCommand()
    cmd.request_id = request_id
    cmd.unsubscribe.topic = topic
    return cmd.SerializeToString()

def encode_cmd_vel(
    request_id: int,
    linear_x: float, linear_y: float, angular_z: float,
    sequence: int, client_ts_ms: int,
) -> bytes:
    req = _v1_control.CmdVelRequest()
    req.twist.linear.x = linear_x
    req.twist.linear.y = linear_y
    req.twist.linear.z = 0.0
    req.twist.angular.x = 0.0
    req.twist.angular.y = 0.0
    req.twist.angular.z = angular_z
    req.sequence = sequence
    req.timestamp_ms = client_ts_ms

    rpc = _v1_rpc.Request()
    rpc.id = request_id
    rpc.method = "control.cmd_vel"
    rpc.deadline_ms = 200
    rpc.payload = req.SerializeToString()

    cmd = _sdk_session.SdkCommand()
    cmd.request_id = request_id
    cmd.rpc.CopyFrom(rpc)
    return cmd.SerializeToString()

def encode_emergency_stop(request_id: int, engage: bool, reason: str) -> bytes:
    req = _v1_safety.EmergencyStopRequest()
    req.activate = engage

    rpc = _v1_rpc.Request()
    rpc.id = request_id
    rpc.method = "safety.emergency_stop"
    rpc.deadline_ms = 2000
    if reason:
        rpc.metadata["reason"] = reason
    rpc.payload = req.SerializeToString()

    cmd = _sdk_session.SdkCommand()
    cmd.request_id = request_id
    cmd.rpc.CopyFrom(rpc)
    return cmd.SerializeToString()

def _wrap_task_rpc(request_id: int, method: str, req) -> bytes:
    rpc = _v1_rpc.Request()
    rpc.id = request_id
    rpc.method = method
    rpc.deadline_ms = 2000
    rpc.payload = req.SerializeToString()

    cmd = _sdk_session.SdkCommand()
    cmd.request_id = request_id
    cmd.rpc.CopyFrom(rpc)
    return cmd.SerializeToString()

def encode_create_nav_task_marker(request_id: int, marker_id: str) -> bytes:
    req = _v1_move.CreateMoveTaskRequest()
    req.marker_id = marker_id
    return _wrap_task_rpc(request_id, "move.create_task", req)

def encode_create_nav_task_pose(
    request_id: int, x: float, y: float, theta: float,
) -> bytes:
    req = _v1_move.CreateMoveTaskRequest()
    req.pose.x = x
    req.pose.y = y
    req.pose.theta = theta
    return _wrap_task_rpc(request_id, "move.create_task", req)

def encode_cancel_task(request_id: int, task_id: str) -> bytes:
    req = _v1_patrol.CancelTaskRequest()
    req.task_id = task_id
    return _wrap_task_rpc(request_id, "task_actions.cancel_task", req)

def encode_pause_task(request_id: int, task_id: str) -> bytes:
    req = _v1_patrol.PauseTaskRequest()
    req.task_id = task_id
    return _wrap_task_rpc(request_id, "task_actions.pause_task", req)

def encode_resume_task(request_id: int, task_id: str) -> bytes:
    req = _v1_patrol.ResumeTaskRequest()
    req.task_id = task_id
    return _wrap_task_rpc(request_id, "task_actions.resume_task", req)

def _convert_capabilities(src) -> Capabilities:
    return Capabilities(
        chassis_control=src.chassis_control,
        telemetry_read=src.telemetry_read,
        image_stream=src.image_stream,
        map_read=src.map_read,
        map_write=src.map_write,
        task_control=src.task_control,
    )

def _convert_delivery_semantics(wire: int) -> DeliverySemantics:
    if wire == _sdk_common.TOPIC_EVENT:
        return DeliverySemantics.EVENT
    return DeliverySemantics.TELEMETRY

def decode_response(data: bytes) -> Optional[DecodedResponse]:
    resp = _sdk_session.SdkResponse()
    try:
        resp.ParseFromString(data)
    except Exception:
        return None

    out = DecodedResponse(
        request_id=resp.request_id,
        success=resp.success,
        sdk_code=map_sdk_error_code(resp.error_code),
        message=resp.message,
        server_ts_ms=resp.server_timestamp_ms,
    )

    which = resp.WhichOneof("payload")
    if which == "handshake":
        out.has_handshake = True
        hs = resp.handshake
        out.protocol_version = hs.protocol_version
        out.robot_sn = hs.robot_sn
        out.robot_model = hs.robot_model
        out.session_token = hs.session_token
        out.granted_capabilities = _convert_capabilities(hs.granted_capabilities)
        for t in hs.available_topics:
            out.available_topics.append(TopicDescriptor(
                name=t.name,
                description=t.description,
                default_hz=t.default_hz,
                max_hz=t.max_hz,
                delivery_semantics=_convert_delivery_semantics(t.delivery_semantics),
            ))
    elif which == "rpc":
        out.has_rpc = True
        r = resp.rpc
        out.rpc_id = r.id
        out.rpc_code = map_v1_error_code(r.code)
        out.rpc_message = r.message
        out.rpc_payload = r.payload
    elif which == "subscribe":
        out.has_subscribe = True
        a = resp.subscribe
        out.sub_topic = a.topic
        out.sub_accepted = a.accepted

        try:
            out.sub_reject_reason = SubscribeRejectReason(a.reject_reason)
        except ValueError:
            out.sub_reject_reason = SubscribeRejectReason._UNKNOWN
            out.sub_message = (a.message or "") + \
                f" [unknown reject_reason={a.reject_reason}]"
        out.sub_next_seq = a.next_seq
        out.sub_message = a.message
    return out

def decode_topic_push(data: bytes) -> Optional[DecodedTopicPush]:
    push = _sdk_session.SdkTopicPush()
    try:
        push.ParseFromString(data)
    except Exception:
        return None
    return DecodedTopicPush(
        topic=push.topic,
        timestamp_ms=push.timestamp_ms,
        seq=push.seq,
        payload=push.payload,
    )

def decode_cmd_vel_response(payload: bytes) -> Optional[DecodedCmdVelResponse]:
    resp = _v1_control.CmdVelResponse()
    try:
        resp.ParseFromString(payload)
    except Exception:
        return None
    return DecodedCmdVelResponse(
        accepted=resp.accepted,
        device_timestamp_ms=resp.device_timestamp_ms,
    )

def decode_ping_response(payload: bytes) -> Optional[DecodedPingResponse]:
    resp = _v1_rpc.PingResponse()
    try:
        resp.ParseFromString(payload)
    except Exception:
        return None
    return DecodedPingResponse(
        client_timestamp_ms=resp.client_timestamp_ms,
        server_timestamp_ms=resp.server_timestamp_ms,
        protocol_version=resp.protocol_version,
        device_sn=resp.device_sn,
    )

def decode_robot_status(payload: bytes) -> Optional[RobotStatus]:
    src = _sdk_v1_telemetry.SdkRobotStateUpdate()
    try:
        src.ParseFromString(payload)
    except Exception:
        return None

    try:
        charge = ChargeType(src.charge_type)
    except ValueError:
        charge = ChargeType.NONE
    try:
        svc = ServiceState(src.service_state)
    except ValueError:
        svc = ServiceState.IDLE
    return RobotStatus(
        robot_id=src.robot_id,
        sequence=src.sequence,

        timestamp_ms=0,
        health_score=src.health_score,
        battery_percent=src.battery_level,
        charge_type=charge,
        service_state=svc,
        is_estop=src.is_estop,
        is_hw_estop=src.is_hw_estop,
        is_sw_estop=src.is_sw_estop,
        active_map_id=src.active_map_id,
        active_map_name=src.active_map_name,
        active_floor=src.active_floor,
        current_task_id=src.current_task_id,
        uptime_seconds=src.uptime_seconds,
        idle_seconds=src.idle_seconds,
        charging_seconds=src.charging_seconds,
        error_codes=list(src.errors),
    )

_TASK_TYPE_MAP: dict[int, TaskType] = {
    _v1_tasks.TASK_TYPE_NAVIGATION: TaskType.NAVIGATION,
    _v1_tasks.TASK_TYPE_PATROL: TaskType.PATROL,
    _v1_tasks.TASK_TYPE_GO_BACK: TaskType.GO_BACK,
}

_TASK_STATE_MAP: dict[int, TaskState] = {
    _v1_tasks.TASK_STATE_PENDING: TaskState.PENDING,
    _v1_tasks.TASK_STATE_RUNNING: TaskState.RUNNING,
    _v1_tasks.TASK_STATE_PAUSED: TaskState.PAUSED,
    _v1_tasks.TASK_STATE_CANCELLING: TaskState.CANCELLING,
    _v1_tasks.TASK_STATE_SUCCEEDED: TaskState.SUCCEEDED,
    _v1_tasks.TASK_STATE_FAILED: TaskState.FAILED,
    _v1_tasks.TASK_STATE_CANCELLED: TaskState.CANCELLED,
}

_TASK_CANCEL_MAP: dict[int, TaskCancelReason] = {
    _v1_tasks.TASK_CANCEL_REASON_USER: TaskCancelReason.USER,
    _v1_tasks.TASK_CANCEL_REASON_ESTOP: TaskCancelReason.ESTOP,
    _v1_tasks.TASK_CANCEL_REASON_TIMEOUT: TaskCancelReason.TIMEOUT,
    _v1_tasks.TASK_CANCEL_REASON_PAUSE_TIMEOUT: TaskCancelReason.PAUSE_TIMEOUT,
    _v1_tasks.TASK_CANCEL_REASON_RESUME_FAILED: TaskCancelReason.RESUME_FAILED,
    _v1_tasks.TASK_CANCEL_REASON_ERROR: TaskCancelReason.ERROR,
}

_TASK_PAUSE_MAP: dict[int, TaskPauseReason] = {
    _v1_tasks.TASK_PAUSE_REASON_USER: TaskPauseReason.USER,
    _v1_tasks.TASK_PAUSE_REASON_ESTOP: TaskPauseReason.ESTOP,
}

def decode_create_task_response(payload: bytes) -> Optional[str]:
    resp = _v1_move.CreateMoveTaskResponse()
    try:
        resp.ParseFromString(payload)
    except Exception:
        return None
    return resp.task.task_id

def _flatten_task(t) -> TaskEvent:
    ev = TaskEvent(
        task_id=t.task_id,
        task_type=_TASK_TYPE_MAP.get(t.task_type, TaskType.UNSPECIFIED),
        state=_TASK_STATE_MAP.get(t.state, TaskState.UNSPECIFIED),
        cancel_reason=_TASK_CANCEL_MAP.get(
            t.cancel_reason, TaskCancelReason.UNSPECIFIED),
        pause_reason=_TASK_PAUSE_MAP.get(
            t.pause_reason, TaskPauseReason.UNSPECIFIED),
        error_code=map_v1_error_code(t.error_code),
        error_message=t.error_message,
        created_at_ms=t.created_at_ms,
        started_at_ms=t.started_at_ms,
        completed_at_ms=t.completed_at_ms,
    )
    if t.WhichOneof("details") == "move":
        ev.marker_id = t.move.marker_id
        ev.planned_distance = t.move.planned_distance
        ev.traveled_distance = t.move.distance_traveled
    return ev

def decode_task_event(payload: bytes) -> Optional[TaskEvent]:
    env = _v1_events.TaskEventEnvelope()
    try:
        env.ParseFromString(payload)
    except Exception:
        return None
    # tasks.events 信封每帧含一种事件; SDK 只把含完整 Task 快照的
    # created / updated 透出. state_changed 与 updated 同时发出, deleted
    # 当前设备端不产生 — 两者跳过 (返回 None, 调用方不 emit).
    kind = env.WhichOneof("kind")
    if kind == "created":
        return _flatten_task(env.created.task)
    if kind == "updated":
        return _flatten_task(env.updated.task)
    return None

def decode_safety_event(payload: bytes) -> Optional[SafetyEvent]:
    s = _v1_telemetry_stream.SafetyStateUpdate()
    try:
        s.ParseFromString(payload)
    except Exception:
        return None
    return SafetyEvent(
        code=s.code,
        level=s.level,
        severity=s.severity,
        mode=s.mode,
        active_source=s.active_source,
    )

_SDK_TO_PUBLIC: dict[int, ErrorCode] = {
    _sdk_common.SDK_ERROR_NONE: ErrorCode.OK,
    _sdk_common.SDK_AUTH_FAILED: ErrorCode.AUTH_FAILED,
    _sdk_common.SDK_AUTH_CN_NOT_ALLOWED: ErrorCode.AUTH_CN_NOT_ALLOWED,
    _sdk_common.SDK_AUTH_SERIAL_REVOKED: ErrorCode.AUTH_SERIAL_REVOKED,
    _sdk_common.SDK_AUTH_TOKEN_INVALID: ErrorCode.AUTH_TOKEN_INVALID,
    _sdk_common.SDK_AUTH_TOKEN_EXPIRED: ErrorCode.AUTH_TOKEN_EXPIRED,
    _sdk_common.SDK_SESSION_TOKEN_INVALID: ErrorCode.SESSION_TOKEN_INVALID,
    _sdk_common.SDK_SESSION_TOKEN_EXPIRED: ErrorCode.SESSION_TOKEN_EXPIRED,
    _sdk_common.SDK_HANDSHAKE_REQUIRED: ErrorCode.HANDSHAKE_REQUIRED,
    _sdk_common.SDK_CAPABILITY_DENIED: ErrorCode.CAPABILITY_DENIED,
    _sdk_common.SDK_RATE_LIMITED: ErrorCode.RATE_LIMITED,
    _sdk_common.SDK_UNSUPPORTED_VERSION: ErrorCode.UNSUPPORTED_VERSION,
    _sdk_common.SDK_TOPIC_NOT_FOUND: ErrorCode.TOPIC_NOT_FOUND,
    _sdk_common.SDK_TOPIC_ALREADY_SUBSCRIBED: ErrorCode.TOPIC_ALREADY_SUBSCRIBED,
    _sdk_common.SDK_TOPIC_NOT_SUBSCRIBED: ErrorCode.TOPIC_NOT_SUBSCRIBED,

    _sdk_common.SDK_DISCONNECTED: ErrorCode.DISCONNECTED,
    _sdk_common.SDK_WOULD_DEADLOCK: ErrorCode.WOULD_DEADLOCK,

    _sdk_common.CONTROL_REJECTED_CHARGING: ErrorCode.CONTROL_E_STOP_ACTIVE,
    _sdk_common.CONTROL_REJECTED_ESTOP: ErrorCode.CONTROL_E_STOP_ACTIVE,
    _sdk_common.CONTROL_REJECTED_TASK_RUNNING: ErrorCode.TASK_RUNNING,
    _sdk_common.CONTROL_REJECTED_POSE_ABNORMAL: ErrorCode.CONTROL_E_STOP_ACTIVE,
    _sdk_common.CONTROL_REJECTED_SHUTTING_DOWN: ErrorCode.CONTROL_E_STOP_ACTIVE,
    _sdk_common.CONTROL_REJECTED_OBSTACLE_TOO_CLOSE: ErrorCode.CONTROL_E_STOP_ACTIVE,
    _sdk_common.CONTROL_REJECTED_MOTOR_FAULT: ErrorCode.CONTROL_PUBLISHER_UNAVAILABLE,
    _sdk_common.CONTROL_REJECTED_STEERING_FAULT: ErrorCode.CONTROL_PUBLISHER_UNAVAILABLE,
    _sdk_common.CONTROL_REJECTED_CAN_FAULT: ErrorCode.CONTROL_PUBLISHER_UNAVAILABLE,
    _sdk_common.CONTROL_REJECTED_NOT_READY: ErrorCode.CONTROL_PUBLISHER_UNAVAILABLE,
}

def map_sdk_error_code(proto_sdk_code: int) -> ErrorCode:
    return _SDK_TO_PUBLIC.get(proto_sdk_code, ErrorCode.INTERNAL_ERROR)

def map_v1_error_code(proto_v1_code: int) -> ErrorCode:
    if proto_v1_code == 0:
        return ErrorCode.OK

    if proto_v1_code == 201:
        return ErrorCode.CAPABILITY_DENIED
    if proto_v1_code == 202:
        return ErrorCode.AUTH_FAILED
    if proto_v1_code == 203:
        return ErrorCode.CONTROL_INVALID_TWIST
    if proto_v1_code == 204:
        return ErrorCode.CANCELLED
    if proto_v1_code == 205:
        return ErrorCode.TIMEOUT

    if proto_v1_code == 1200:
        return ErrorCode.NAV_MARKER_NOT_FOUND
    if proto_v1_code == 1201:
        return ErrorCode.NAV_NO_ACTIVE_MAP
    if proto_v1_code in (1202, 1208):
        return ErrorCode.TASK_RUNNING
    if proto_v1_code == 1203:
        return ErrorCode.NAV_LOW_BATTERY
    if proto_v1_code == 1204:
        return ErrorCode.CONTROL_E_STOP_ACTIVE
    if proto_v1_code in (1205, 1206, 1211, 1212):
        return ErrorCode.NAV_GOAL_UNREACHABLE
    if proto_v1_code == 1207:
        return ErrorCode.TIMEOUT
    if proto_v1_code == 1209:
        return ErrorCode.TASK_NOT_FOUND
    if proto_v1_code == 1210:
        return ErrorCode.CONTROL_PUBLISHER_UNAVAILABLE

    if proto_v1_code == 9300:
        return ErrorCode.CONTROL_E_STOP_ACTIVE
    if proto_v1_code == 9301:
        return ErrorCode.CONTROL_PUBLISHER_UNAVAILABLE
    if proto_v1_code == 9302:
        return ErrorCode.CONTROL_INVALID_TWIST
    return ErrorCode.INTERNAL_ERROR

def reject_reason_to_error(r: SubscribeRejectReason) -> ErrorCode:
    if r == SubscribeRejectReason.NONE:
        return ErrorCode.OK
    if r == SubscribeRejectReason.TOPIC_NOT_FOUND:
        return ErrorCode.TOPIC_NOT_FOUND
    if r == SubscribeRejectReason.CAPABILITY_DENIED:
        return ErrorCode.CAPABILITY_DENIED
    if r == SubscribeRejectReason.ALREADY_SUBSCRIBED:
        return ErrorCode.TOPIC_ALREADY_SUBSCRIBED
    if r == SubscribeRejectReason.INVALID_HZ:
        return ErrorCode.CONTROL_INVALID_TWIST

    return ErrorCode.INTERNAL_ERROR

def pem_to_der(pem: str) -> bytes:
    if not pem:
        return b""
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        cert = x509.load_pem_x509_certificate(pem.encode())
        return cert.public_bytes(serialization.Encoding.DER)
    except Exception as e:
        from ..error import SdkException, ErrorCode as _EC
        raise SdkException(_EC.AUTH_FAILED, f"PEM → DER failed: {e}")

