from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .pit_prices import (
    build_labels,
    generate_quotes,
    load_price_events,
    rows_csv_sha256,
)
from .phase10 import failure_injections
from .verification_utils import (
    git_blob_sha256,
    registered_trial,
    resolve_manifest_path,
    run_tests,
    sha256_path,
)


REGISTERED_COMMIT = "2606a58"


def verify_phase10(
    output_dir: Path,
    specification_path: Path,
    events_path: Path,
    phase9_specification_path: Path,
    registry_path: Path,
    *,
    project_root: Path,
    run_test_suite: bool = True,
) -> dict[str, Any]:
    required = [
        "quotes.csv",
        "labeled_events.csv",
        "failure_injections.json",
        "phase10_summary.json",
        "manifest.json",
        "PHASE10_REPORT.md",
    ]
    missing = [name for name in required if not (output_dir / name).is_file()]
    if missing:
        return {"passed": False, "failures": [f"missing output: {x}" for x in missing]}
    spec = json.loads(specification_path.read_text())
    events = load_price_events(events_path)
    replay_quotes = generate_quotes(events, spec)
    replay_labels = build_labels(events, replay_quotes, spec)
    replay_failures = failure_injections(events, replay_quotes, spec)
    with (output_dir / "quotes.csv").open(newline="", encoding="utf-8") as handle:
        output_quotes = list(csv.DictReader(handle))
    with (output_dir / "labeled_events.csv").open(newline="", encoding="utf-8") as handle:
        output_labels = list(csv.DictReader(handle))
    summary = json.loads((output_dir / "phase10_summary.json").read_text())
    manifest = json.loads((output_dir / "manifest.json").read_text())
    output_failures = json.loads((output_dir / "failure_injections.json").read_text())
    trial = registered_trial(registry_path, spec["trial_id"])
    prereg_paths = [
        "config/phase10_trial_001.json",
        "config/phase10_synthetic_events.csv",
        "config/phase9_trial_001.json",
        "docs/PHASE10_PROTOCOL.md",
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
        "quotes_replay": len(output_quotes) == len(replay_quotes)
        and manifest["quotes_sha256"] == sha256_path(output_dir / "quotes.csv")
        and manifest["quotes_sha256"] == rows_csv_sha256(replay_quotes),
        "labels_replay": len(output_labels) == len(replay_labels)
        and manifest["labels_sha256"]
        == sha256_path(output_dir / "labeled_events.csv")
        and manifest["labels_sha256"] == rows_csv_sha256(replay_labels),
        "failure_replay": output_failures == replay_failures,
        "pipeline_checks": all(summary["checks"].values()),
        "tests": tests["passed"]
        and tests["count"] >= spec["completion_gates"]["required_test_count"],
        "zero_empirical": summary["counts"]["empirical_events"] == 0,
    }
    result = {
        "passed": all(checks.values()),
        "failures": [name for name, passed in checks.items() if not passed],
        "checks": checks,
        "tests": tests,
        "decision": spec["decision"] if all(checks.values()) else "FAIL_PHASE10",
        "preregistration_hashes": hashes,
    }
    (output_dir / "verification.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result
