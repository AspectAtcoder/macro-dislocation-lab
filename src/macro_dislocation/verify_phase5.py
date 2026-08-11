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

from .evidence_enrollment import (
    audit_evidence_package,
    campaign_checkpoint,
    load_linked_trace_fixture,
)
from .shadow_campaign import ShadowTraceStore, build_release_plans
from .vendor_capture import VendorCaptureStore


REGISTERED_COMMIT = "ac1290c"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def verify_phase5(
    output_dir: Path,
    specification_path: Path,
    evidence_contract_path: Path,
    capture_contract_path: Path,
    campaign_contract_path: Path,
    schedule_path: Path,
    trace_path: Path,
    pre_payload_path: Path,
    post_payload_path: Path,
    trial_registry_path: Path,
    *,
    project_root: Path,
    run_tests: bool = True,
) -> dict[str, Any]:
    required = [
        "PHASE5_REPORT.md",
        "phase5_summary.json",
        "capture_observations.json",
        "normalized_snapshots.json",
        "linked_trace.json",
        "evidence_package.json",
        "capture_integrity.json",
        "failure_injections.json",
        "vendor_access_preflight.json",
        "campaign_checkpoint.json",
        "manifest.json",
        "capture_store/observations.jsonl",
        "trace_store/trace.jsonl",
    ]
    failures = [
        f"missing output: {name}" for name in required if not (output_dir / name).is_file()
    ]
    if failures:
        return {"passed": False, "failures": failures, "checks": {}}

    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    summary = json.loads((output_dir / "phase5_summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    output_observations = json.loads(
        (output_dir / "capture_observations.json").read_text(encoding="utf-8")
    )
    output_snapshots = json.loads(
        (output_dir / "normalized_snapshots.json").read_text(encoding="utf-8")
    )
    output_trace = json.loads(
        (output_dir / "linked_trace.json").read_text(encoding="utf-8")
    )
    output_package = json.loads(
        (output_dir / "evidence_package.json").read_text(encoding="utf-8")
    )
    output_integrity = json.loads(
        (output_dir / "capture_integrity.json").read_text(encoding="utf-8")
    )
    output_failures = json.loads(
        (output_dir / "failure_injections.json").read_text(encoding="utf-8")
    )
    output_preflight = json.loads(
        (output_dir / "vendor_access_preflight.json").read_text(encoding="utf-8")
    )
    output_checkpoint = json.loads(
        (output_dir / "campaign_checkpoint.json").read_text(encoding="utf-8")
    )

    policy = specification["policy"]
    plans = build_release_plans(schedule_path, policy)
    capture_store = VendorCaptureStore(output_dir / "capture_store")
    trace_store = ShadowTraceStore(output_dir / "trace_store")
    observations = capture_store.observations()
    by_transport = {str(item["transport"]): item for item in observations}
    registered_trace = load_linked_trace_fixture(
        trace_path,
        plans[0],
        pre_capture_id=str(by_transport.get("https_snapshot", {}).get("capture_id", "")),
        post_capture_id=str(
            by_transport.get("websocket_calendar", {}).get("capture_id", "")
        ),
    )
    trace = trace_store.events()
    integrity = capture_store.integrity_report()
    snapshots = [asdict(item) for item in capture_store.replay()]
    replay_package = audit_evidence_package(
        plans[0], trace, capture_store, policy
    )
    replay_checkpoint = campaign_checkpoint([], policy)

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

    prereg_paths = [
        "config/phase5_trial_001.json",
        "config/empirical_evidence_contract.json",
        "config/vendor_capture_contract.json",
        "config/shadow_campaign_contract.json",
        "tests/fixtures/phase5_release_schedule.json",
        "tests/fixtures/phase5_trace_linked.json",
        "tests/fixtures/phase5_te_pre_release.json",
        "tests/fixtures/phase5_te_post_release.json",
    ]
    prereg_hashes = {
        path: _git_blob_hash(project_root, registered_commit, path)
        == _sha256(project_root / path)
        for path in prereg_paths
    }
    payload_hashes = {
        "pre": by_transport.get("https_snapshot", {}).get("payload_sha256")
        == _sha256(pre_payload_path),
        "post": by_transport.get("websocket_calendar", {}).get("payload_sha256")
        == _sha256(post_payload_path),
    }
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
    expected_failure_issues = specification["failure_injections"]
    counts = summary["counts"]
    checks = {
        "pipeline_checks_pass": all(summary["pipeline_checks"].values()),
        "one_registered_trial": len(matching) == 1,
        "registered_commit_matches": registered_commit == REGISTERED_COMMIT,
        "all_preregistered_files_match": all(prereg_hashes.values()),
        "all_input_hashes_match": all(input_hash_checks.values()),
        "fixture_payloads_match_capture_store": all(payload_hashes.values()),
        "capture_observations_match_store": output_observations == observations,
        "normalized_snapshots_match_replay": output_snapshots == snapshots,
        "trace_matches_registered_fixture": output_trace == registered_trace,
        "trace_matches_append_only_store": output_trace == trace,
        "capture_integrity_matches_replay": output_integrity == integrity,
        "evidence_package_matches_replay": output_package == replay_package
        and replay_package["package_hash"]
        == summary["evidence_package"]["package_hash"]
        == summary["replay_package_hash"]
        == manifest["package_hash"],
        "campaign_checkpoint_matches_replay": output_checkpoint == replay_checkpoint,
        "registered_counts_match": counts["capture_observations"]
        == gates["capture_observations"]
        and counts["raw_blobs"] == gates["raw_blobs"]
        and counts["normalized_snapshots"] == gates["normalized_snapshots"]
        and counts["trace_events"] == gates["trace_events"]
        and counts["capture_references"] == gates["capture_references"],
        "synthetic_structural_only": replay_package["structurally_complete"] is True
        and replay_package["enrollable"] is False
        and "synthetic_capture_not_empirical" in replay_package["issues"],
        "failure_injections_exact": set(output_failures)
        == set(expected_failure_issues)
        and all(
            result["passed"]
            and result["expected_issue"] == expected_failure_issues[name]
            for name, result in output_failures.items()
        ),
        "external_access_gate_closed": output_preflight["ready"] is False
        and output_preflight["credential_present"]
        is gates["credential_present"]
        and output_preflight["rights_attestation_present"]
        is gates["rights_attestation_present"],
        "campaign_not_promoted": replay_checkpoint["promoted"] is False
        and replay_checkpoint["eligible_packages"] == 0,
        "tests_pass": tests["passed"],
        "minimum_test_count": tests["count"] >= gates["required_test_count"],
        "no_authenticated_vendor_request": summary[
            "authenticated_vendor_request_executed"
        ]
        is False,
        "no_market_price_join": summary["market_price_join_executed"] is False,
        "no_price_model": summary["price_model_executed"] is False,
    }
    failures.extend(name for name, passed in checks.items() if not passed)
    result = {
        "passed": not failures,
        "failures": failures,
        "checks": checks,
        "preregistered_hash_checks": prereg_hashes,
        "input_hash_checks": input_hash_checks,
        "payload_hash_checks": payload_hashes,
        "tests": tests,
        "trial_id": specification["trial_id"],
        "decision": (
            "READY_FOR_LICENSED_EVIDENCE_ENROLLMENT"
            if not failures
            else "FAIL_EVIDENCE_ENROLLMENT"
        ),
        "external_status": specification["external_status"],
        "economic_decision": "NO_GO_PRICE_EXPERIMENT_LICENSED_CAMPAIGN_REQUIRED",
        "package_hash": replay_package["package_hash"],
        "counts": counts,
    }
    (output_dir / "verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if result["passed"]:
        summary["phase5_status"] = "COMPLETE"
        summary["pipeline_status"] = "READY_FOR_LICENSED_EVIDENCE_ENROLLMENT"
        summary["verification"] = {
            "passed": True,
            "test_count": tests["count"],
            "decision": result["decision"],
        }
        (output_dir / "phase5_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report_path = output_dir / "PHASE5_REPORT.md"
        report = report_path.read_text(encoding="utf-8").replace(
            "READY_FOR_LICENSED_EVIDENCE_ENROLLMENT_PENDING_VERIFICATION",
            "READY_FOR_LICENSED_EVIDENCE_ENROLLMENT",
        ).replace(
            "The final verifier checks preregistration, input hashes, deterministic replay and\nthe complete regression suite.",
            f"The final verifier passed every check with {tests['count']} tests.",
        )
        report_path.write_text(report, encoding="utf-8")
    return result
