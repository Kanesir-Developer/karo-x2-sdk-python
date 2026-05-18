from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

class DeliverySemantics(IntEnum):

    TELEMETRY = 0

    EVENT = 1

@dataclass
class TopicDescriptor:

    name: str = ""
    description: str = ""
    default_hz: float = 0.0
    max_hz: float = 0.0
    delivery_semantics: DeliverySemantics = DeliverySemantics.TELEMETRY

