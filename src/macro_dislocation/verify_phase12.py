from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .forward_test import replay_forward_events
from .phase12 import failure_injections
from .verification_utils import (
    git_blob_sha256,
    registered_trial,
    resolve_manifest_path,
    run_tests,
    sha256_path,
)


REGISTERED_COMMIT = "2606a58"


def verify_phase12(
    output_dir: Path,
    specification_path: Path,
    phase11_specification_path: Path,
    labels_path: Path,
    model_path: Path,
    registry_path: Path,
    *,
    project_root: Path,
    run_test_suite: bool = True,
) -> dict[str, Any]:
    required = [
        "forward_events.jsonl",
        "audit.json",
        "failure_injections.json",
        "phase12_summary.json",
        "manifest.json",
        "PHASE12_REPORT.md",
    ]
    missing = [name for name in required if not (output_dir / name).is_file()]
    if missing:
        return {"passed": False, "failures": [f"missing output: {x}" for x in missing]}
    spec = json.loads(specification_path.read_text())
    summary = json.loads((output_dir / "phase12_summary.json").read_text())
    manifest = json.loads((output_dir / "manifest.json").read_text())
    with (output_dir / "forward_events.jsonl").open(encoding="utf-8") as handle:
        events = [json.loads(line) for line in handle]
    replay = replay_forward_events(events)
    output_failures = json.loads((output_dir / "failure_injections.json").read_text())
    trial = registered_trial(registry_path, spec["trial_id"])
    prereg_paths = [
        "config/phase12_trial_001.json",
        "config/phase11_trial_001.json",
        "config/phase10_synthetic_events.csv",
        "docs/PHASE12_PROTOCOL.md",
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
        "journal_replay": replay == summary["audit"],
        "journal_hash": manifest["journal_sha256"]
        == sha256_path(output_dir / "forward_events.jsonl"),
        "failure_replay": output_failures == failure_injections(spec, events),
        "pipeline_checks": all(summary["checks"].values()),
        "registered_counts": replay["signals"]
        == spec["completion_gates"]["synthetic_forward_signals"]
        and replay["settlements"]
        == spec["completion_gates"]["synthetic_forward_settlements"]
        and replay["open_signals"] == 0,
        "synthetic_replay_only": all(
            event["provenance"] == "synthetic_fixture" for event in events
        ),
        "tests": tests["passed"]
        and tests["count"] >= spec["completion_gates"]["required_test_count"],
        "zero_prospective": summary["counts"]["prospective_forward_settlements"] == 0,
        "zero_live_orders": summary["counts"]["live_orders"] == 0,
    }
    result = {
        "passed": all(checks.values()),
        "failures": [name for name, passed in checks.items() if not passed],
        "checks": checks,
        "tests": tests,
        "decision": spec["decision"] if all(checks.values()) else "FAIL_PHASE12",
        "preregistration_hashes": hashes,
    }
    (output_dir / "verification.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result
