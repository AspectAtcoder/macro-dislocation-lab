from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Quote:
    timestamp_utc: datetime
    bid: float
    ask: float
    bid_volume: float = 0.0
    ask_volume: float = 0.0

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return self.ask - self.bid


@dataclass(frozen=True, slots=True)
class Target:
    timestamp_utc: datetime
    event_id: str
    label: str
    side: str  # "before" or "after"
