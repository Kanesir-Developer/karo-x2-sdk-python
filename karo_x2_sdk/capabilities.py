from __future__ import annotations

from dataclasses import dataclass

@dataclass
class Capabilities:
    chassis_control: bool = False
    telemetry_read: bool = False
    image_stream: bool = False
    map_read: bool = False
    map_write: bool = False
    task_control: bool = False

