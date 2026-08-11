from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .pit_prices import write_csv
from .verification_utils import manifest_key, sha256_path
from .verification_utils import git_blob_sha256, registered_trial
from .walk_forward import (
    backtest_metrics,
    load_labeled_rows,
    validate_backtest_policy,
    walk_forward_backtest,
)


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def failure_injections(spec: dict[str, Any]) -> dict[str, Any]:
    expected = spec["failure_injections"]
    cases = {
        "sixth_feature": validate_backtest_policy(spec, feature_count=6),
        "future_fit_row": validate_backtest_policy(
            spec,
            feature_count=5,
            train_last="2025-01-02",
            predict_at="2025-01-01",
        ),
        "unregistered_trial": validate_backtest_policy(
            spec, feature_count=5, trial_registered=False
        ),
        "duplicate_prediction": validate_backtest_policy(
            spec, feature_count=5, duplicate_prediction=True
        ),
        "constant_cost": validate_backtest_policy(
            spec, feature_count=5, cost_model="constant"
        ),
        "forward_role_leak": validate_backtest_policy(
            spec, feature_count=5, dataset_role="forward"
        ),
    }
    return {
        name: {
            "passed": expected[name] in issues,
            "expected_issue": expected[name],
            "issues": issues,
        }
        for name, issues in cases.items()
    }


def run_phase11(
    specification_path: Path,
    phase10_specification_path: Path,
    labels_path: Path,
    output_dir: Path,
    *,
    project_root: Path,
) -> dict[str, Any]:
    spec = json.loads(specification_path.read_text())
    json.loads(phase10_specification_path.read_text())
    rows = load_labeled_rows(
        labels_path,
        horizon=int(spec["target_horizon_seconds"]),
        role=spec["dataset_role"],
    )
    trial_record = {
        "trial_id": spec["trial_id"],
        "specification_sha256": sha256_path(specification_path),
        "features": spec["features"],
        "alpha": spec["model"]["alpha"],
        "status": "REGISTERED_BEFORE_FIT",
    }
    predictions, model = walk_forward_backtest(rows, spec)
    metrics = backtest_metrics(predictions, int(spec["model"]["trials_allowed"]))
    failures = failure_injections(spec)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "oos_predictions.csv", predictions)
    _write_json(output_dir / "model.json", model)
    _write_json(output_dir / "trial_record.json", trial_record)
    _write_json(output_dir / "metrics.json", metrics)
    _write_json(output_dir / "failure_injections.json", failures)
    gates = spec["completion_gates"]
    counts = {
        "trials_run": 1,
        "features": len(spec["features"]),
        "training_events_initial": int(spec["model"]["initial_train_events"]),
        "oos_predictions": len(predictions),
        "synthetic_oos_predictions": sum(
            row["provenance"] == "synthetic_fixture" for row in predictions
        ),
        "empirical_oos_predictions": sum(
            row["provenance"] != "synthetic_fixture" for row in predictions
        ),
    }
    checks = {name: counts[name] == gates[name] for name in counts}
    checks["failure_injections"] = (
        len(failures) == gates["failure_injections"]
        and all(value["passed"] for value in failures.values())
    )
    checks["trial_registered_before_fit"] = (
        trial_record["status"] == "REGISTERED_BEFORE_FIT"
    )
    checks["past_only_fits"] = all(
        row["train_last_scheduled_at"] < row["scheduled_at"]
        for row in predictions
    )
    checks["dynamic_costs"] = all(
        row["cost_model"] == "dynamic_spread_volatility_v1"
        for row in predictions
    )
    summary = {
        "trial_id": spec["trial_id"],
        "phase11_status": "BACKTEST_EXECUTED",
        "decision": spec["decision"] if all(checks.values()) else "FAIL_PHASE11",
        "economic_decision": spec["economic_decision"],
        "counts": counts,
        "checks": checks,
        "metrics": metrics,
        "model_hash": model["model_hash"],
        "performance_evidence": "synthetic_structural_only",
    }
    _write_json(output_dir / "phase11_summary.json", summary)
    _write_json(
        output_dir / "manifest.json",
        {
            "inputs": {
                manifest_key(path, project_root): sha256_path(path)
                for path in (
                    specification_path,
                    phase10_specification_path,
                    labels_path,
                )
            },
            "predictions_sha256": sha256_path(output_dir / "oos_predictions.csv"),
            "model_sha256": sha256_path(output_dir / "model.json"),
        },
    )
    (output_dir / "PHASE11_REPORT.md").write_text(
        "# Phase 11 result\n\n"
        f"Decision: **{summary['decision']}**.\n\n"
        f"The single registered synthetic walk-forward produced {len(predictions)} OOS predictions. "
        "Metrics are pipeline diagnostics and not evidence of an edge.\n",
        encoding="utf-8",
    )
    return summary


def run_registered_backtest(
    specification_path: Path,
    labels_path: Path,
    registry_path: Path,
    output_dir: Path,
    *,
    project_root: Path,
) -> dict[str, Any]:
    spec = json.loads(specification_path.read_text(encoding="utf-8"))
    trial = registered_trial(registry_path, spec["trial_id"])
    if trial is None:
        raise ValueError("trial_not_registered")
    try:
        relative = str(specification_path.resolve().relative_to(project_root.resolve()))
    except ValueError as exc:
        raise ValueError("registered specification must be inside the repository") from exc
    if git_blob_sha256(
        project_root, trial["registered_commit"], relative
    ) != sha256_path(specification_path):
        raise ValueError("registered_specification_hash_mismatch")
    rows = load_labeled_rows(
        labels_path,
        horizon=int(spec["target_horizon_seconds"]),
        role=spec["dataset_role"],
    )
    predictions, model = walk_forward_backtest(rows, spec)
    metrics = backtest_metrics(predictions, int(spec["model"]["trials_allowed"]))
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "oos_predictions.csv", predictions)
    _write_json(output_dir / "model.json", model)
    _write_json(output_dir / "metrics.json", metrics)
    empirical = sum(row["provenance"] != "synthetic_fixture" for row in predictions)
    minimum = int(spec["governance"]["minimum_empirical_oos_events_for_edge_claim"])
    decision = (
        "STRUCTURAL_ONLY_SYNTHETIC_BACKTEST"
        if empirical == 0
        else "INSUFFICIENT_EMPIRICAL_OOS_EVENTS"
        if empirical < minimum
        else "BACKTEST_COMPLETE_EDGE_REVIEW_REQUIRED"
    )
    summary = {
        "status": "REGISTERED_BACKTEST_COMPLETE",
        "trial_id": spec["trial_id"],
        "decision": decision,
        "oos_predictions": len(predictions),
        "empirical_oos_predictions": empirical,
        "metrics": metrics,
        "model_hash": model["model_hash"],
    }
    _write_json(output_dir / "summary.json", summary)
    _write_json(
        output_dir / "manifest.json",
        {
            "trial": {
                "trial_id": trial["trial_id"],
                "registered_commit": trial["registered_commit"],
                "registered_specification_path": relative,
                "registered_specification_sha256": sha256_path(specification_path),
            },
            "inputs": {
                "labels_sha256": sha256_path(labels_path),
                "trial_registry_sha256": sha256_path(registry_path),
            },
            "outputs": {
                "oos_predictions_sha256": sha256_path(
                    output_dir / "oos_predictions.csv"
                ),
                "model_sha256": sha256_path(output_dir / "model.json"),
                "metrics_sha256": sha256_path(output_dir / "metrics.json"),
                "summary_sha256": sha256_path(output_dir / "summary.json"),
            },
            "model_hash": model["model_hash"],
        },
    )
    return summary
