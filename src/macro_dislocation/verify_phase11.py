from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .phase11 import failure_injections
from .pit_prices import rows_csv_sha256
from .verification_utils import (
    git_blob_sha256,
    registered_trial,
    resolve_manifest_path,
    run_tests,
    sha256_path,
)
from .walk_forward import backtest_metrics, load_labeled_rows, walk_forward_backtest


REGISTERED_COMMIT = "2606a58"


def verify_phase11(
    output_dir: Path,
    specification_path: Path,
    phase10_specification_path: Path,
    labels_path: Path,
    registry_path: Path,
    *,
    project_root: Path,
    run_test_suite: bool = True,
) -> dict[str, Any]:
    required = [
        "oos_predictions.csv",
        "model.json",
        "trial_record.json",
        "metrics.json",
        "failure_injections.json",
        "phase11_summary.json",
        "manifest.json",
        "PHASE11_REPORT.md",
    ]
    missing = [name for name in required if not (output_dir / name).is_file()]
    if missing:
        return {"passed": False, "failures": [f"missing output: {x}" for x in missing]}
    spec = json.loads(specification_path.read_text())
    rows = load_labeled_rows(
        labels_path,
        horizon=int(spec["target_horizon_seconds"]),
        role=spec["dataset_role"],
    )
    replay_predictions, replay_model = walk_forward_backtest(rows, spec)
    replay_metrics = backtest_metrics(
        replay_predictions, int(spec["model"]["trials_allowed"])
    )
    summary = json.loads((output_dir / "phase11_summary.json").read_text())
    model = json.loads((output_dir / "model.json").read_text())
    metrics = json.loads((output_dir / "metrics.json").read_text())
    manifest = json.loads((output_dir / "manifest.json").read_text())
    output_failures = json.loads((output_dir / "failure_injections.json").read_text())
    with (output_dir / "oos_predictions.csv").open(newline="", encoding="utf-8") as handle:
        predictions = list(csv.DictReader(handle))
    trial = registered_trial(registry_path, spec["trial_id"])
    prereg_paths = [
        "config/phase11_trial_001.json",
        "config/phase10_trial_001.json",
        "config/phase10_synthetic_events.csv",
        "docs/PHASE11_PROTOCOL.md",
    ]
    hashes = {
        name: git_blob_sha256(project_root, REGISTERED_COMMIT, name)
        == sha256_path(project_root / name)
        for name in prereg_paths
    }
    tests = (
        run_tests(project_root)
        if run_test_suite
        else {
            "passed": True,
            "count": spec["completion_gates"]["required_test_count"],
        }
    )
    checks = {
        "registered_commit": trial is not None
        and trial["registered_commit"] == REGISTERED_COMMIT,
        "preregistration_hashes": all(hashes.values()),
        "input_hashes": all(
            sha256_path(resolve_manifest_path(name, project_root)) == expected
            for name, expected in manifest["inputs"].items()
        ),
        "model_replay": model == replay_model,
        "metrics_replay": metrics == replay_metrics,
        "prediction_count": len(predictions) == len(replay_predictions),
        "prediction_hash": manifest["predictions_sha256"]
        == sha256_path(output_dir / "oos_predictions.csv")
        and manifest["predictions_sha256"] == rows_csv_sha256(replay_predictions),
        "model_hash": manifest["model_sha256"]
        == sha256_path(output_dir / "model.json"),
        "failure_replay": output_failures == failure_injections(spec),
        "pipeline_checks": all(summary["checks"].values()),
        "tests": tests["passed"]
        and tests["count"] >= spec["completion_gates"]["required_test_count"],
        "synthetic_only": summary["counts"]["empirical_oos_predictions"] == 0,
    }
    result = {
        "passed": all(checks.values()),
        "failures": [name for name, passed in checks.items() if not passed],
        "checks": checks,
        "tests": tests,
        "decision": spec["decision"] if all(checks.values()) else "FAIL_PHASE11",
        "metrics": metrics,
        "preregistration_hashes": hashes,
    }
    (output_dir / "verification.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result
