from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from macro_dislocation.pit_prices import build_labels, generate_quotes, load_price_events
from macro_dislocation.walk_forward import fit_model


ROOT = Path(__file__).resolve().parents[1]


def spec(phase: int) -> dict[str, Any]:
    return json.loads(
        (ROOT / f"config/phase{phase}_trial_001.json").read_text(encoding="utf-8")
    )


def events_labels() -> tuple[list[Any], list[dict[str, Any]]]:
    phase10 = spec(10)
    events = load_price_events(ROOT / "config/phase10_synthetic_events.csv")
    return events, build_labels(events, generate_quotes(events, phase10), phase10)


def backtest_rows() -> list[dict[str, Any]]:
    _, labels = events_labels()
    return [
        row
        for row in labels
        if row["dataset_role"] == "backtest" and row["exit_horizon_seconds"] == 900
    ]


def forward_rows() -> list[dict[str, Any]]:
    _, labels = events_labels()
    return [
        row
        for row in labels
        if row["dataset_role"] == "forward" and row["exit_horizon_seconds"] == 900
    ]


def final_model() -> dict[str, Any]:
    phase11 = spec(11)
    return fit_model(
        backtest_rows(), list(phase11["features"]), float(phase11["model"]["alpha"])
    )
