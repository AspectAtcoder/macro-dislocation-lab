from __future__ import annotations

import math
from dataclasses import dataclass

FEATURE_NAMES = ("initial_move_z", "primary_surprise_z", "secondary_surprise_z")


@dataclass(frozen=True, slots=True)
class Observation:
    event_id: str
    event_type: str
    release_timestamp_utc: str
    initial_move_bps: float
    primary_surprise: float
    core_cpi_surprise: float | None
    ahe_surprise: float | None
    unemployment_bullish_surprise: float | None
    target_return_bps: float
    entry_mid: float
    entry_bid: float
    entry_ask: float
    exit_mid: float
    exit_bid: float
    exit_ask: float


@dataclass(frozen=True, slots=True)
class Scale:
    mean: float
    standard_deviation: float

    def apply(self, value: float) -> float:
        if self.standard_deviation <= 1e-12:
            return 0.0
        return (value - self.mean) / self.standard_deviation

    def as_dict(self) -> dict[str, float]:
        return {"mean": self.mean, "standard_deviation": self.standard_deviation}


def fit_scale(values: list[float]) -> Scale:
    if not values:
        raise ValueError("cannot fit a scale without values")
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return Scale(mean, math.sqrt(variance))


class FeatureTransformer:
    """Train-fitted feature transform shared by research and future live serving."""

    def __init__(self) -> None:
        self.scales: dict[str, Scale] = {}

    def fit(self, observations: list[Observation]) -> "FeatureTransformer":
        if not observations:
            raise ValueError("training observations are required")
        self.scales = {
            "initial_move": fit_scale([row.initial_move_bps for row in observations])
        }
        for event_type in ("CPI", "NFP"):
            rows = [row for row in observations if row.event_type == event_type]
            if not rows:
                raise ValueError(f"training data has no {event_type} events")
            self.scales[f"primary:{event_type}"] = fit_scale(
                [row.primary_surprise for row in rows]
            )
            if event_type == "CPI":
                core = [required(row.core_cpi_surprise, row.event_id, "core CPI") for row in rows]
                self.scales["secondary:CPI:core"] = fit_scale(core)
            else:
                ahe = [required(row.ahe_surprise, row.event_id, "AHE") for row in rows]
                unemployment = [
                    required(row.unemployment_bullish_surprise, row.event_id, "unemployment")
                    for row in rows
                ]
                self.scales["secondary:NFP:ahe"] = fit_scale(ahe)
                self.scales["secondary:NFP:unemployment"] = fit_scale(unemployment)
        return self

    def transform_one(self, row: Observation) -> list[float]:
        if not self.scales:
            raise RuntimeError("feature transformer is not fitted")
        initial = self.scales["initial_move"].apply(row.initial_move_bps)
        primary = self.scales[f"primary:{row.event_type}"].apply(row.primary_surprise)
        if row.event_type == "CPI":
            secondary = self.scales["secondary:CPI:core"].apply(
                required(row.core_cpi_surprise, row.event_id, "core CPI")
            )
        elif row.event_type == "NFP":
            ahe = self.scales["secondary:NFP:ahe"].apply(
                required(row.ahe_surprise, row.event_id, "AHE")
            )
            unemployment = self.scales["secondary:NFP:unemployment"].apply(
                required(row.unemployment_bullish_surprise, row.event_id, "unemployment")
            )
            secondary = (ahe + unemployment) / 2.0
        else:
            raise ValueError(f"unsupported event type: {row.event_type}")
        return [initial, primary, secondary]

    def transform(self, observations: list[Observation]) -> list[list[float]]:
        return [self.transform_one(row) for row in observations]

    def as_dict(self) -> dict[str, object]:
        return {
            "feature_names": list(FEATURE_NAMES),
            "scales": {name: scale.as_dict() for name, scale in sorted(self.scales.items())},
        }


def required(value: float | None, event_id: str, name: str) -> float:
    if value is None:
        raise ValueError(f"{event_id} is missing required {name} surprise")
    return value
