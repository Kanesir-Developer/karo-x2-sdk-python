from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import List

class ChargeType(IntEnum):
    NONE = 0
    WIRE = 1
    DOCK = 2

class ServiceState(IntEnum):
    IDLE = 0
    TASK = 1
    MAPPING = 2
    STARTING = 3
    SHUTTING_DOWN = 4
    UPGRADING = 5
    REMOTE_CONTROL = 6
    GOTO_CHARGING = 7

@dataclass
class RobotStatus:

    robot_id: str = ""
    sequence: int = 0
    timestamp_ms: int = 0

    health_score: int = 0
    battery_percent: int = 0

    charge_type: ChargeType = ChargeType.NONE

    service_state: ServiceState = ServiceState.IDLE

    is_estop: bool = False
    is_hw_estop: bool = False
    is_sw_estop: bool = False

    active_map_id: str = ""
    active_map_name: str = ""
    active_floor: int = 0
    current_task_id: str = ""

    uptime_seconds: int = 0
    idle_seconds: int = 0
    charging_seconds: int = 0

    error_codes: List[int] = field(default_factory=list)

