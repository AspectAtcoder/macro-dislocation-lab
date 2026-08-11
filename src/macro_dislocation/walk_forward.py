from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .baseline import fit_ridge, predict
from .pit_prices import dynamic_slippage_bp, parse_utc


@dataclass(frozen=True, slots=True)
class Scale:
    mean: float
    standard_deviation: float

    def transform(self, value: float) -> float:
        if self.standard_deviation <= 1e-12:
            return 0.0
        return (value - self.mean) / self.standard_deviation


def _close(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9)


def _validated_label(row: dict[str, str]) -> dict[str, Any]:
    if not str(row.get("event_id") or "").strip():
        raise ValueError("missing_event_id")
    if not str(row.get("evidence_package_id") or "").strip():
        raise ValueError("missing_evidence_package_id")
    if row.get("cost_model") != "dynamic_spread_volatility_v1":
        raise ValueError("constant_cost_forbidden")
    scheduled = parse_utc(row["scheduled_at"])
    ready = parse_utc(row["feature_ready_at"])
    entry_time = parse_utc(row["entry_timestamp"])
    exit_time = parse_utc(row["exit_timestamp"])
    if ready < scheduled or ready > entry_time:
        raise ValueError("feature_not_point_in_time")
    if not scheduled < entry_time < exit_time:
        raise ValueError("label_timestamp_order_invalid")

    numeric_names = (
        "headline_surprise",
        "revision_surprise",
        "internal_breadth",
        "regime_score",
        "pre_volatility_bp",
        "entry_bid",
        "entry_ask",
        "entry_mid",
        "entry_spread_bp",
        "exit_bid",
        "exit_ask",
        "exit_mid",
        "exit_spread_bp",
        "entry_slippage_bp",
        "exit_slippage_bp",
        "target_mid_bp",
        "long_net_bp",
        "short_net_bp",
    )
    values = {name: float(row[name]) for name in numeric_names}
    if not all(math.isfinite(value) for value in values.values()):
        raise ValueError("nonfinite_numeric_value")
    entry_mid = (values["entry_bid"] + values["entry_ask"]) / 2.0
    exit_mid = (values["exit_bid"] + values["exit_ask"]) / 2.0
    if (
        values["entry_bid"] <= 0
        or values["entry_ask"] <= values["entry_bid"]
        or values["exit_bid"] <= 0
        or values["exit_ask"] <= values["exit_bid"]
    ):
        raise ValueError("invalid_bid_ask")
    entry_spread = (
        (values["entry_ask"] - values["entry_bid"]) / entry_mid * 10_000.0
    )
    exit_spread = (
        (values["exit_ask"] - values["exit_bid"]) / exit_mid * 10_000.0
    )
    expected = {
        "entry_mid": entry_mid,
        "exit_mid": exit_mid,
        "entry_spread_bp": entry_spread,
        "exit_spread_bp": exit_spread,
        "entry_slippage_bp": dynamic_slippage_bp(
            entry_spread, values["pre_volatility_bp"]
        ),
        "exit_slippage_bp": dynamic_slippage_bp(
            exit_spread, values["pre_volatility_bp"]
        ),
        "target_mid_bp": (exit_mid / entry_mid - 1.0) * 10_000.0,
    }
    expected["long_net_bp"] = (
        (values["exit_bid"] - values["entry_ask"]) / entry_mid * 10_000.0
        - expected["entry_slippage_bp"]
        - expected["exit_slippage_bp"]
    )
    expected["short_net_bp"] = (
        (values["entry_bid"] - values["exit_ask"]) / entry_mid * 10_000.0
        - expected["entry_slippage_bp"]
        - expected["exit_slippage_bp"]
    )
    if any(not _close(values[name], value) for name, value in expected.items()):
        raise ValueError("label_cost_or_price_mismatch")
    return {**row, **values}


def load_labeled_rows(path: Path, *, horizon: int, role: str) -> list[dict[str, Any]]:
    if role not in {"backtest", "forward"}:
        raise ValueError("invalid_dataset_role")
    with path.open(newline="", encoding="utf-8") as handle:
        raw = [
            row
            for row in csv.DictReader(handle)
            if int(row["exit_horizon_seconds"]) == horizon
            and row["dataset_role"] == role
        ]
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    previous = None
    for row in raw:
        if row["event_id"] in seen:
            raise ValueError("duplicate_event_id")
        seen.add(row["event_id"])
        validated = _validated_label(row)
        scheduled = parse_utc(validated["scheduled_at"])
        if previous is not None and scheduled <= previous:
            raise ValueError("events_not_strictly_chronological")
        previous = scheduled
        rows.append(validated)
    return rows


def fit_scales(rows: list[dict[str, Any]], features: list[str]) -> dict[str, Scale]:
    output: dict[str, Scale] = {}
    for feature in features:
        values = [float(row[feature]) for row in rows]
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        output[feature] = Scale(mean, math.sqrt(variance))
    return output


def transform_rows(
    rows: list[dict[str, Any]], features: list[str], scales: dict[str, Scale]
) -> list[list[float]]:
    return [
        [scales[name].transform(float(row[name])) for name in features] for row in rows
    ]


def model_identity(model: dict[str, Any]) -> str:
    core = {key: value for key, value in model.items() if key != "model_hash"}
    return hashlib.sha256(
        json.dumps(core, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def fit_model(
    rows: list[dict[str, Any]], features: list[str], alpha: float
) -> dict[str, Any]:
    scales = fit_scales(rows, features)
    matrix = transform_rows(rows, features, scales)
    targets = [float(row["target_mid_bp"]) for row in rows]
    model: dict[str, Any] = {
        "family": "ridge_linear_regression",
        "alpha": alpha,
        "features": features,
        "scales": {
            name: {
                "mean": scale.mean,
                "standard_deviation": scale.standard_deviation,
            }
            for name, scale in scales.items()
        },
        "coefficients": fit_ridge(matrix, targets, alpha),
        "training_events": len(rows),
        "training_last_scheduled_at": rows[-1]["scheduled_at"],
        "training_provenance": sorted({str(row["provenance"]) for row in rows}),
        "training_evidence_package_ids": sorted(
            {str(row["evidence_package_id"]) for row in rows}
        ),
        "training_dataset_roles": sorted({str(row["dataset_role"]) for row in rows}),
    }
    model["model_hash"] = model_identity(model)
    return model


def predict_model(model: dict[str, Any], row: dict[str, Any]) -> float:
    if model.get("model_hash") != model_identity(model):
        raise ValueError("model_hash_mismatch")
    features = list(model["features"])
    scales = {
        name: Scale(
            float(model["scales"][name]["mean"]),
            float(model["scales"][name]["standard_deviation"]),
        )
        for name in features
    }
    matrix = transform_rows([row], features, scales)
    return predict([float(value) for value in model["coefficients"]], matrix)[0]


def validate_backtest_policy(
    specification: dict[str, Any],
    *,
    feature_count: int,
    train_last: str | None = None,
    predict_at: str | None = None,
    trial_registered: bool = True,
    duplicate_prediction: bool = False,
    cost_model: str = "dynamic_spread_volatility_v1",
    dataset_role: str = "backtest",
) -> list[str]:
    issues: set[str] = set()
    model = specification["model"]
    if feature_count > int(model["maximum_features"]):
        issues.add("feature_limit_exceeded")
    if train_last is not None and predict_at is not None and train_last >= predict_at:
        issues.add("walk_forward_leakage")
    if not trial_registered:
        issues.add("trial_not_registered")
    if duplicate_prediction:
        issues.add("duplicate_oos_prediction")
    if cost_model != "dynamic_spread_volatility_v1":
        issues.add("constant_cost_forbidden")
    if dataset_role != specification["dataset_role"]:
        issues.add("dataset_role_leakage")
    return sorted(issues)


def walk_forward_backtest(
    rows: list[dict[str, Any]], specification: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    features = list(specification["features"])
    model_spec = specification["model"]
    initial = int(model_spec["initial_train_events"])
    alpha = float(model_spec["alpha"])
    threshold = float(model_spec["trade_threshold_bp"])
    if len(rows) <= initial:
        raise ValueError("insufficient_walk_forward_rows")
    policy_issues = validate_backtest_policy(
        specification, feature_count=len(features)
    )
    if policy_issues:
        raise ValueError(policy_issues[0])
    predictions: list[dict[str, Any]] = []
    for index in range(initial, len(rows)):
        train = rows[:index]
        test = rows[index]
        if train[-1]["scheduled_at"] >= test["scheduled_at"]:
            raise ValueError("walk_forward_leakage")
        model = fit_model(train, features, alpha)
        forecast = predict_model(model, test)
        position = 1 if forecast >= threshold else -1 if forecast <= -threshold else 0
        net = (
            float(test["long_net_bp"])
            if position > 0
            else float(test["short_net_bp"])
            if position < 0
            else 0.0
        )
        predictions.append(
            {
                "event_id": test["event_id"],
                "evidence_package_id": test["evidence_package_id"],
                "scheduled_at": test["scheduled_at"],
                "train_events": len(train),
                "train_last_scheduled_at": train[-1]["scheduled_at"],
                "model_hash": model["model_hash"],
                "forecast_target_bp": forecast,
                "actual_target_bp": float(test["target_mid_bp"]),
                "position": position,
                "net_return_bp": net,
                "direction_correct": int(
                    position != 0
                    and (position > 0) == (float(test["target_mid_bp"]) > 0)
                ),
                "cost_model": test["cost_model"],
                "provenance": test["provenance"],
            }
        )
    return predictions, fit_model(rows, features, alpha)


def deflated_sharpe_ratio(returns: list[float], trials: int) -> float | None:
    if len(returns) < 3 or trials < 1:
        return None
    mean = statistics.mean(returns)
    standard = statistics.stdev(returns)
    if standard <= 1e-12:
        return None
    sharpe = mean / standard
    centered = [(value - mean) / standard for value in returns]
    skew = sum(value**3 for value in centered) / len(centered)
    kurtosis = sum(value**4 for value in centered) / len(centered)
    expected_max = math.sqrt(max(0.0, 2.0 * math.log(trials))) / math.sqrt(len(returns))
    denominator = math.sqrt(
        max(
            1e-12,
            (1.0 - skew * sharpe + ((kurtosis - 1.0) / 4.0) * sharpe**2)
            / (len(returns) - 1),
        )
    )
    z_score = (sharpe - expected_max) / denominator
    return 0.5 * (1.0 + math.erf(z_score / math.sqrt(2.0)))


def backtest_metrics(predictions: list[dict[str, Any]], trials: int) -> dict[str, Any]:
    actual = [float(row["actual_target_bp"]) for row in predictions]
    forecast = [float(row["forecast_target_bp"]) for row in predictions]
    returns = [float(row["net_return_bp"]) for row in predictions]
    active = [row for row in predictions if int(row["position"]) != 0]
    cumulative = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in returns:
        cumulative += value
        peak = max(peak, cumulative)
        drawdown = min(drawdown, cumulative - peak)
    standard = statistics.stdev(returns) if len(returns) > 1 else 0.0
    event_sharpe = statistics.mean(returns) / standard * math.sqrt(len(returns)) if standard > 1e-12 else None
    return {
        "oos_predictions": len(predictions),
        "active_trades": len(active),
        "mae_bp": sum(abs(a - f) for a, f in zip(actual, forecast)) / len(actual),
        "direction_accuracy_active": (
            sum(int(row["direction_correct"]) for row in active) / len(active)
            if active
            else None
        ),
        "total_net_bp": sum(returns),
        "median_net_bp": statistics.median(returns),
        "event_sharpe": event_sharpe,
        "maximum_drawdown_bp": drawdown,
        "deflated_sharpe_ratio": deflated_sharpe_ratio(returns, trials),
    }
