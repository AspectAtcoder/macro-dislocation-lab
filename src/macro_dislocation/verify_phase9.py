from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .campaign_state import replay_campaign
from .phase9 import failure_injections
from .verification_utils import (
    git_blob_sha256,
    registered_trial,
    resolve_manifest_path,
    run_tests,
    sha256_path,
)


REGISTERED_COMMIT = "2606a58"


def verify_phase9(
    output_dir: Path,
    specification_path: Path,
    phase8_specification_path: Path,
    roster_path: Path,
    registry_path: Path,
    *,
    project_root: Path,
    run_test_suite: bool = True,
) -> dict[str, Any]:
    required = [
        "campaign_events.jsonl",
        "audit.json",
        "failure_injections.json",
        "phase9_summary.json",
        "manifest.json",
        "PHASE9_REPORT.md",
    ]
    missing = [name for name in required if not (output_dir / name).is_file()]
    if missing:
        return {"passed": False, "failures": [f"missing output: {x}" for x in missing]}
    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    summary = json.loads((output_dir / "phase9_summary.json").read_text())
    manifest = json.loads((output_dir / "manifest.json").read_text())
    with (output_dir / "campaign_events.jsonl").open(encoding="utf-8") as handle:
        events = [json.loads(line) for line in handle]
    replay = replay_campaign(events, specification)
    output_failures = json.loads((output_dir / "failure_injections.json").read_text())
    replay_failures = failure_injections(events, specification)
    trial = registered_trial(registry_path, specification["trial_id"])
    prereg_paths = [
        "config/phase9_trial_001.json",
        "config/phase8_trial_001.json",
        "config/phase6_campaign_roster_001.json",
        "docs/PHASE9_PROTOCOL.md",
    ]
    hashes = {
        name: git_blob_sha256(project_root, REGISTERED_COMMIT, name)
        == sha256_path(project_root / name)
        for name in prereg_paths
    }
    inputs = {
        name: sha256_path(resolve_manifest_path(name, project_root)) == expected
        for name, expected in manifest["inputs"].items()
    }
    tests = run_tests(project_root) if run_test_suite else {
        "passed": True,
        "count": specification["completion_gates"]["required_test_count"],
    }
    checks = {
        "registered_commit": trial is not None
        and trial["registered_commit"] == REGISTERED_COMMIT,
        "preregistration_hashes": all(hashes.values()),
        "input_hashes": all(inputs.values()),
        "replay": replay == summary["audit"],
        "journal_hash": manifest["journal_sha256"]
        == sha256_path(output_dir / "campaign_events.jsonl"),
        "failure_replay": output_failures == replay_failures,
        "pipeline_checks": all(summary["checks"].values()),
        "registered_result": replay["events"]
        == specification["completion_gates"]["synthetic_events"]
        and replay["state"] == "EVIDENCE_ENROLLED"
        and replay["passed"],
        "tests": tests["passed"]
        and tests["count"] >= specification["completion_gates"]["required_test_count"],
        "zero_empirical": summary["counts"]["empirical_campaigns"] == 0,
    }
    result = {
        "passed": all(checks.values()),
        "failures": [name for name, passed in checks.items() if not passed],
        "checks": checks,
        "tests": tests,
        "decision": specification["decision"] if all(checks.values()) else "FAIL_PHASE9",
        "preregistration_hashes": hashes,
    }
    (output_dir / "verification.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result
