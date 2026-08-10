from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_phase0(
    output_dir: Path,
    specification_path: Path,
    trial_registry_path: Path,
    *,
    project_root: Path,
) -> dict[str, object]:
    failures: list[str] = []
    required = [
        "phase0_summary.json",
        "PHASE0_REPORT.md",
        "data_audit.json",
        "manifest.json",
        "experiment0/event_metrics.csv",
        "experiment0/summary.json",
        "experiment0/arrival_curve.svg",
        "baseline/predictions.csv",
        "baseline/summary.json",
    ]
    for relative in required:
        if not (output_dir / relative).is_file():
            failures.append(f"missing output: {relative}")
    if failures:
        return {"passed": False, "failures": failures, "checks": {}}

    summary = json.loads((output_dir / "phase0_summary.json").read_text(encoding="utf-8"))
    data_audit = json.loads((output_dir / "data_audit.json").read_text(encoding="utf-8"))
    baseline = json.loads((output_dir / "baseline/summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    with trial_registry_path.open(newline="", encoding="utf-8") as handle:
        trials = list(csv.DictReader(handle))
    with (output_dir / "experiment0/event_metrics.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        event_metrics = list(csv.DictReader(handle))
    with (output_dir / "baseline/predictions.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        predictions = list(csv.DictReader(handle))

    trial_id = specification["trial_id"]
    matching_trials = [row for row in trials if row["trial_id"] == trial_id]
    expected_decision = (
        "CONDITIONAL_GO_LIMITED_PIT_DATA_TRIAL"
        if baseline["status"] == "TRACE_PRESENT"
        else "NO_GO_CURRENT_NUMERIC_SPECIFICATION"
    )
    hash_checks: dict[str, bool] = {}
    for relative, expected_hash in manifest["inputs"].items():
        input_path = project_root / relative
        matches = input_path.is_file() and _sha256(input_path) == expected_hash
        hash_checks[relative] = matches
        if not matches:
            failures.append(f"input hash mismatch: {relative}")

    checks = {
        "phase0_marked_complete": summary.get("phase0_status") == "COMPLETE",
        "data_audit_valid": data_audit.get("valid") is True,
        "summary_audit_matches_file": summary.get("data_audit") == data_audit,
        "event_metric_rows_24_by_7": len(event_metrics) == 168,
        "test_prediction_rows_12": len(predictions) == 12,
        "one_registered_trial": len(matching_trials) == 1,
        "one_allowed_trial": specification.get("allowed_model_trials") == 1,
        "one_executed_trial": baseline.get("trials_run") == 1,
        "baseline_summary_matches": summary.get("baseline") == baseline,
        "decision_matches_trace_gate": summary.get("decision", {}).get("phase1")
        == expected_decision,
        "all_manifest_input_hashes_match": all(hash_checks.values()),
    }
    failures.extend(name for name, passed in checks.items() if not passed)
    result: dict[str, object] = {
        "passed": not failures,
        "failures": failures,
        "checks": checks,
        "input_hash_checks": hash_checks,
        "trial_id": trial_id,
        "result": baseline["status"],
        "decision": summary["decision"]["phase1"],
    }
    (output_dir / "verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result
