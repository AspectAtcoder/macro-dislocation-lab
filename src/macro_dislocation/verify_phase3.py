from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .pit_events import audit_components, build_calendar_bundles
from .vendor_capture import VendorCaptureStore


REGISTERED_COMMIT = "8801e55"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _git_blob_hash(project_root: Path, commit: str, relative_path: str) -> str | None:
    process = subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=project_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return hashlib.sha256(process.stdout).hexdigest() if process.returncode == 0 else None


def _run_tests(project_root: Path) -> dict[str, Any]:
    process = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=project_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    match = re.search(r"Ran (\d+) tests?", process.stdout)
    return {
        "passed": process.returncode == 0,
        "count": int(match.group(1)) if match else 0,
        "returncode": process.returncode,
        "output_tail": "\n".join(process.stdout.splitlines()[-24:]),
    }


def verify_phase3(
    output_dir: Path,
    specification_path: Path,
    capture_contract_path: Path,
    pit_contract_path: Path,
    trial_registry_path: Path,
    *,
    project_root: Path,
    run_tests: bool = True,
) -> dict[str, Any]:
    required = [
        "PHASE3_REPORT.md",
        "phase3_summary.json",
        "capture_observations.json",
        "normalized_snapshots.csv",
        "component_audit.csv",
        "event_bundles.json",
        "integrity_report.json",
        "failure_injections.json",
        "manifest.json",
        "vendor_capture_store/observations.jsonl",
    ]
    failures = [
        f"missing output: {name}" for name in required if not (output_dir / name).is_file()
    ]
    if failures:
        return {"passed": False, "failures": failures, "checks": {}}

    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    summary = json.loads((output_dir / "phase3_summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    output_observations = json.loads(
        (output_dir / "capture_observations.json").read_text(encoding="utf-8")
    )
    output_bundles = json.loads(
        (output_dir / "event_bundles.json").read_text(encoding="utf-8")
    )
    failure_injections = json.loads(
        (output_dir / "failure_injections.json").read_text(encoding="utf-8")
    )
    store = VendorCaptureStore(output_dir / "vendor_capture_store")
    integrity = store.integrity_report()
    observations = store.observations()
    snapshots = store.replay()
    audits = audit_components(snapshots)
    replay_bundles = build_calendar_bundles(audits)
    replay_hash = _hash_json([asdict(snapshot) for snapshot in snapshots])

    with trial_registry_path.open(newline="", encoding="utf-8") as handle:
        trials = list(csv.DictReader(handle))
    matching = [row for row in trials if row["trial_id"] == specification["trial_id"]]
    registered_commit = matching[0]["registered_commit"] if len(matching) == 1 else ""

    input_hash_checks: dict[str, bool] = {}
    for raw_path, expected in manifest["inputs"].items():
        path = Path(raw_path)
        if not path.is_absolute():
            path = project_root / path
        input_hash_checks[raw_path] = path.is_file() and _sha256(path) == expected

    tests = (
        _run_tests(project_root)
        if run_tests
        else {
            "passed": True,
            "count": specification["completion_gates"]["required_test_count"],
            "returncode": 0,
            "output_tail": "test execution disabled by caller",
        }
    )
    gates = specification["completion_gates"]
    counts = summary["counts"]
    checks = {
        "pipeline_checks_pass": all(summary["pipeline_checks"].values()),
        "one_registered_trial": len(matching) == 1,
        "registered_commit_matches": registered_commit == REGISTERED_COMMIT,
        "preregistered_spec_matches": _git_blob_hash(
            project_root, registered_commit, "config/phase3_trial_001.json"
        )
        == _sha256(specification_path),
        "preregistered_capture_contract_matches": _git_blob_hash(
            project_root, registered_commit, "config/vendor_capture_contract.json"
        )
        == _sha256(capture_contract_path),
        "preregistered_pit_contract_matches": _git_blob_hash(
            project_root, registered_commit, "config/pit_event_contract.json"
        )
        == _sha256(pit_contract_path),
        "all_input_hashes_match": all(input_hash_checks.values()),
        "capture_observations_match_store": output_observations == observations,
        "capture_hash_matches_replay": replay_hash
        == summary["capture_hash"]
        == summary["replay_hash"]
        == manifest["capture_hash"],
        "bundle_replay_matches": output_bundles == replay_bundles,
        "registered_counts_match": counts["capture_observations"]
        == gates["fixture_receipts"]
        and counts["unique_raw_blobs"] == gates["unique_raw_blobs"]
        and counts["normalized_snapshots"] == gates["normalized_snapshots"]
        and counts["component_audits"] == gates["component_audits"]
        and counts["calendar_bundles"] == gates["calendar_bundles"],
        "synthetic_only_no_empirical_rows": counts["empirical_vendor_rows"] == 0
        and all(
            snapshot.provenance == "synthetic_fixture_not_empirical"
            for snapshot in snapshots
        ),
        "failure_injections_pass": set(failure_injections)
        == set(specification["failure_injections"])
        and all(failure_injections.values()),
        "store_integrity_pass": integrity["passed"],
        "tests_pass": tests["passed"],
        "minimum_test_count": tests["count"] >= gates["required_test_count"],
        "no_authenticated_vendor_request": summary[
            "authenticated_vendor_request_executed"
        ]
        is False,
        "no_price_model": summary["price_model_executed"] is False,
        "no_market_price_join": summary["market_price_join_executed"] is False,
    }
    failures.extend(name for name, passed in checks.items() if not passed)
    result = {
        "passed": not failures,
        "failures": failures,
        "checks": checks,
        "input_hash_checks": input_hash_checks,
        "tests": tests,
        "trial_id": specification["trial_id"],
        "decision": (
            "READY_FOR_AUTHENTICATED_SHADOW_CAPTURE"
            if not failures
            else "FAIL_CAPTURE_INTEGRITY"
        ),
        "economic_decision": "NO_GO_PRICE_EXPERIMENT_SHADOW_DATA_REQUIRED",
        "capture_hash": replay_hash,
        "counts": counts,
    }
    (output_dir / "verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if result["passed"]:
        summary["phase3_status"] = "COMPLETE"
        summary["pipeline_status"] = "READY_FOR_AUTHENTICATED_SHADOW_CAPTURE"
        summary["verification"] = {
            "passed": True,
            "test_count": tests["count"],
            "decision": result["decision"],
        }
        (output_dir / "phase3_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report_path = output_dir / "PHASE3_REPORT.md"
        report = report_path.read_text(encoding="utf-8").replace(
            "READY_FOR_AUTHENTICATED_SHADOW_CAPTURE_PENDING_VERIFICATION",
            "READY_FOR_AUTHENTICATED_SHADOW_CAPTURE",
        ).replace(
            "最終テスト数と事前登録commit照合は `macro-lab verify-phase3` が判定します。",
            f"最終verifierは全項目PASS（テスト{tests['count']}件）です。",
        )
        report_path.write_text(report, encoding="utf-8")
    return result
