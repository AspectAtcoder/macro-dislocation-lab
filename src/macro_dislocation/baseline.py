from __future__ import annotations

import csv
import json
import math
import statistics
from pathlib import Path

from .features import FEATURE_NAMES, FeatureTransformer, Observation


def _number(row: dict[str, str], field: str) -> float:
    value = row.get(field, "")
    if value == "":
        raise ValueError(f"{row.get('event_id', '<unknown>')} missing {field}")
    return float(value)


def _quotes_from_metric(row: dict[str, str]) -> tuple[float, float, float]:
    mid = float(row["horizon_mid"])
    spread_price = float(row["spread_pips"]) / 100.0
    return mid, mid - spread_price / 2.0, mid + spread_price / 2.0


def build_observations(
    events_path: Path,
    metrics_path: Path,
    *,
    entry_seconds: int,
    exit_seconds: int,
) -> list[Observation]:
    with events_path.open(newline="", encoding="utf-8") as handle:
        events = {row["event_id"]: row for row in csv.DictReader(handle)}
    with metrics_path.open(newline="", encoding="utf-8") as handle:
        metric_rows = list(csv.DictReader(handle))
    metrics = {
        (row["event_id"], int(row["horizon_seconds"])): row for row in metric_rows
    }
    observations: list[Observation] = []
    for event_id, event in events.items():
        entry = metrics.get((event_id, entry_seconds))
        exit_row = metrics.get((event_id, exit_seconds))
        if entry is None or exit_row is None:
            raise ValueError(f"{event_id} missing entry or exit metric")
        entry_mid, entry_bid, entry_ask = _quotes_from_metric(entry)
        exit_mid, exit_bid, exit_ask = _quotes_from_metric(exit_row)
        event_type = event["event_type"]
        if event_type == "CPI":
            primary = _number(event, "cpi_mom_actual_pct") - _number(
                event, "cpi_mom_forecast_pct"
            )
            core = _number(event, "core_cpi_mom_actual_pct") - _number(
                event, "core_cpi_mom_forecast_pct"
            )
            ahe = unemployment = None
        elif event_type == "NFP":
            primary = _number(event, "nfp_change_actual_k") - _number(
                event, "nfp_change_forecast_k"
            )
            core = None
            ahe = _number(event, "average_hourly_earnings_mom_actual_pct") - _number(
                event, "average_hourly_earnings_mom_forecast_pct"
            )
            unemployment = _number(event, "unemployment_rate_forecast_pct") - _number(
                event, "unemployment_rate_actual_pct"
            )
        else:
            raise ValueError(f"unsupported event type: {event_type}")
        observations.append(
            Observation(
                event_id=event_id,
                event_type=event_type,
                release_timestamp_utc=event["release_timestamp_utc"],
                initial_move_bps=float(entry["cumulative_return_bps"]),
                primary_surprise=primary,
                core_cpi_surprise=core,
                ahe_surprise=ahe,
                unemployment_bullish_surprise=unemployment,
                target_return_bps=(exit_mid / entry_mid - 1.0) * 10_000.0,
                entry_mid=entry_mid,
                entry_bid=entry_bid,
                entry_ask=entry_ask,
                exit_mid=exit_mid,
                exit_bid=exit_bid,
                exit_ask=exit_ask,
            )
        )
    return sorted(observations, key=lambda row: row.release_timestamp_utc)


def solve_linear_system(matrix: list[list[float]], vector: list[float]) -> list[float]:
    size = len(vector)
    augmented = [matrix[row][:] + [vector[row]] for row in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) <= 1e-12:
            raise ValueError("singular regression system")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                current - factor * pivot_value
                for current, pivot_value in zip(augmented[row], augmented[column])
            ]
    return [augmented[row][-1] for row in range(size)]


def fit_ridge(features: list[list[float]], targets: list[float], alpha: float) -> list[float]:
    if not features or len(features) != len(targets):
        raise ValueError("features and targets must be non-empty and aligned")
    width = len(features[0]) + 1
    design = [[1.0, *row] for row in features]
    xtx = [[0.0 for _ in range(width)] for _ in range(width)]
    xty = [0.0 for _ in range(width)]
    for row, target in zip(design, targets):
        for left in range(width):
            xty[left] += row[left] * target
            for right in range(width):
                xtx[left][right] += row[left] * row[right]
    for index in range(1, width):
        xtx[index][index] += alpha
    return solve_linear_system(xtx, xty)


def predict(coefficients: list[float], features: list[list[float]]) -> list[float]:
    return [
        coefficients[0] + sum(coef * value for coef, value in zip(coefficients[1:], row))
        for row in features
    ]


def _mae(actual: list[float], forecast: list[float]) -> float:
    return sum(abs(left - right) for left, right in zip(actual, forecast)) / len(actual)


def _rmse(actual: list[float], forecast: list[float]) -> float:
    return math.sqrt(sum((left - right) ** 2 for left, right in zip(actual, forecast)) / len(actual))


def _correlation(left: list[float], right: list[float]) -> float | None:
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    denominator = math.sqrt(
        sum((x - left_mean) ** 2 for x in left) * sum((y - right_mean) ** 2 for y in right)
    )
    return numerator / denominator if denominator > 1e-12 else None


def _wilson(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    probability = successes / total
    denominator = 1.0 + z * z / total
    center = (probability + z * z / (2.0 * total)) / denominator
    margin = z * math.sqrt(probability * (1.0 - probability) / total + z * z / (4 * total * total)) / denominator
    return center - margin, center + margin


def _two_sided_binomial_p(successes: int, total: int) -> float:
    tail_start = max(successes, total - successes)
    tail = sum(math.comb(total, count) for count in range(tail_start, total + 1)) / (2**total)
    return min(1.0, 2.0 * tail)


def run_baseline(
    events_path: Path,
    metrics_path: Path,
    specification_path: Path,
    output_dir: Path,
) -> dict[str, object]:
    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    entry_seconds = int(specification["timing"]["entry_seconds_after_release"])
    exit_seconds = int(specification["timing"]["exit_seconds_after_release"])
    observations = build_observations(
        events_path, metrics_path, entry_seconds=entry_seconds, exit_seconds=exit_seconds
    )
    expected = int(specification["sample"]["expected_events"])
    if len(observations) != expected:
        raise ValueError(f"expected {expected} observations, found {len(observations)}")
    train_count = int(specification["split"]["train_events"])
    test_count = int(specification["split"]["test_events"])
    if train_count + test_count != len(observations):
        raise ValueError("registered split does not cover the observations exactly")
    train, test = observations[:train_count], observations[train_count:]
    transformer = FeatureTransformer().fit(train)
    train_features = transformer.transform(train)
    test_features = transformer.transform(test)
    train_target = [row.target_return_bps for row in train]
    test_target = [row.target_return_bps for row in test]
    alpha = float(specification["model"]["alpha"])
    coefficients = fit_ridge(train_features, train_target, alpha)
    forecasts = predict(coefficients, test_features)
    train_mean = sum(train_target) / len(train_target)
    slippage_pips = float(specification["cost"]["additional_roundtrip_slippage_pips"])
    prediction_rows: list[dict[str, object]] = []
    net_after_buffer: list[float] = []
    successes = 0
    for observation, features, forecast in zip(test, test_features, forecasts):
        direction = 1 if forecast >= 0.0 else -1
        actual_direction = 1 if observation.target_return_bps >= 0.0 else -1
        successes += int(direction == actual_direction)
        if direction > 0:
            observed_net = (
                (observation.exit_bid - observation.entry_ask) / observation.entry_mid * 10_000.0
            )
        else:
            observed_net = (
                (observation.entry_bid - observation.exit_ask) / observation.entry_mid * 10_000.0
            )
        slippage_bps = slippage_pips * 0.01 / observation.entry_mid * 10_000.0
        after_buffer = observed_net - slippage_bps
        net_after_buffer.append(after_buffer)
        prediction_rows.append(
            {
                "event_id": observation.event_id,
                "event_type": observation.event_type,
                "release_timestamp_utc": observation.release_timestamp_utc,
                **dict(zip(FEATURE_NAMES, features)),
                "actual_target_bps": observation.target_return_bps,
                "forecast_target_bps": forecast,
                "forecast_direction": direction,
                "direction_correct": int(direction == actual_direction),
                "observed_bid_ask_net_bps": observed_net,
                "slippage_buffer_bps": slippage_bps,
                "net_after_buffer_bps": after_buffer,
            }
        )
    sign_accuracy = successes / len(test)
    wilson_low, wilson_high = _wilson(successes, len(test))
    model_mae = _mae(test_target, forecasts)
    zero_mae = _mae(test_target, [0.0] * len(test))
    mean_mae = _mae(test_target, [train_mean] * len(test))
    gate = specification["trace_gate"]
    gate_checks = {
        "sign_accuracy": sign_accuracy >= float(gate["minimum_test_sign_accuracy"]),
        "mae_below_zero": model_mae < zero_mae,
        "mae_below_train_mean": model_mae < mean_mae,
        "positive_median_net_after_buffer": statistics.median(net_after_buffer) > 0.0,
    }
    trace_present = all(gate_checks.values())
    summary: dict[str, object] = {
        "trial_id": specification["trial_id"],
        "status": "TRACE_PRESENT" if trace_present else "NO_TRACE",
        "sample_warning": "Pilot only; 2024 was inspected before this trial and is not a final holdout.",
        "train": {
            "events": len(train),
            "first": train[0].release_timestamp_utc,
            "last": train[-1].release_timestamp_utc,
            "target_mean_bps": train_mean,
        },
        "test": {
            "events": len(test),
            "first": test[0].release_timestamp_utc,
            "last": test[-1].release_timestamp_utc,
            "sign_successes": successes,
            "sign_accuracy": sign_accuracy,
            "sign_accuracy_wilson_95": [wilson_low, wilson_high],
            "sign_binomial_p_value_vs_50": _two_sided_binomial_p(successes, len(test)),
            "mae_model_bps": model_mae,
            "mae_zero_forecast_bps": zero_mae,
            "mae_train_mean_forecast_bps": mean_mae,
            "rmse_model_bps": _rmse(test_target, forecasts),
            "forecast_actual_correlation": _correlation(forecasts, test_target),
            "median_net_after_buffer_bps": statistics.median(net_after_buffer),
            "mean_net_after_buffer_bps": statistics.mean(net_after_buffer),
            "net_win_rate": sum(value > 0.0 for value in net_after_buffer) / len(net_after_buffer),
        },
        "gate_checks": gate_checks,
        "model": {
            "feature_names": list(FEATURE_NAMES),
            "coefficients": {"intercept": coefficients[0], **dict(zip(FEATURE_NAMES, coefficients[1:]))},
            "alpha": alpha,
            "transformer": transformer.as_dict(),
        },
        "trials_run": 1,
        "deflated_sharpe_ratio": None,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "predictions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(prediction_rows[0]))
        writer.writeheader()
        writer.writerows(prediction_rows)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary
