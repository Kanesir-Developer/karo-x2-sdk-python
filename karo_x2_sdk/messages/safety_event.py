from __future__ import annotations

from dataclasses import dataclass

@dataclass
class SafetyEvent:
    code: int = 0
    level: int = 0
    severity: int = 0
    mode: str = ""
    active_source: str = ""
    timestamp_ms: int = 0
