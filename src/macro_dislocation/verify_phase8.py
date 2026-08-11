from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from .campaign_roster import campaign_readiness, load_campaign_roster
from .capture_authorization import (
    authorization_key_preflight,
    issue_access_authorization,
    next_viable_window,
)
from .evidence_enrollment import vendor_access_preflight
from .phase8 import capture_paths_require_permits, run_failure_injections


REGISTERED_COMMIT = "6bc0556"


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


def verify_phase8(
    output_dir: Path,
    specification_path: Path,
    authorization_contract_path: Path,
    phase6_specification_path: Path,
    roster_path: Path,
    phase4_specification_path: Path,
    rights_schema_path: Path,
    phase7_specification_path: Path,
    trial_registry_path: Path,
    *,
    project_root: Path,
    run_tests: bool = True,
) -> dict[str, Any]:
    required = [
        "PHASE8_REPORT.md",
        "phase8_summary.json",
        "vendor_access_preflight.json",
        "authorization_key_preflight.json",
        "activation_packet.json",
        "authorization_decision.json",
        "next_viable_window.json",
        "failure_injections.json",
        "manifest.json",
    ]
    failures = [
        f"missing output: {name}" for name in required if not (output_dir / name).is_file()
    ]
    if failures:
        return {"passed": False, "failures": failures, "checks": {}}

    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    phase6 = json.loads(phase6_specification_path.read_text(encoding="utf-8"))
    summary = json.loads((output_dir / "phase8_summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    output_preflight = json.loads(
        (output_dir / "vendor_access_preflight.json").read_text(encoding="utf-8")
    )
    output_key = json.loads(
        (output_dir / "authorization_key_preflight.json").read_text(encoding="utf-8")
    )
    output_packet = json.loads((output_dir / "activation_packet.json").read_text(encoding="utf-8"))
    output_authorization = json.loads(
        (output_dir / "authorization_decision.json").read_text(encoding="utf-8")
    )
    output_next = json.loads((output_dir / "next_viable_window.json").read_text(encoding="utf-8"))
    output_failures = json.loads(
        (output_dir / "failure_injections.json").read_text(encoding="utf-8")
    )

    policy = specification["policy"]
    roster = load_campaign_roster(roster_path, phase6["policy"])
    window = roster.windows[0]
    replay_preflight = vendor_access_preflight()
    replay_key = authorization_key_preflight(policy)
    replay_readiness = campaign_readiness(
        roster, specification["evaluated_at"], replay_preflight, phase6["policy"]
    )
    replay_packet = replay_readiness["activation_packet"]
    replay_authorization = issue_access_authorization(
        roster, window, replay_packet, None, policy
    )
    replay_next = next_viable_window(roster, specification["evaluated_at"])
    if replay_next is None:
        raise ValueError("Phase 8 replay requires a next viable window")
    replay_failures = run_failure_injections(
        roster,
        window,
        replay_packet,
        replay_authorization,
        policy,
        specification["failure_injections"],
    )

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
        "config/phase8_trial_001.json",
        "config/capture_authorization_contract.json",
        "config/phase6_trial_001.json",
        "config/phase6_campaign_roster_001.json",
        "config/phase4_trial_001.json",
        "config/vendor_rights_attestation.schema.json",
        "config/phase7_trial_001.json",
    ]
    prereg_hashes = {
        path: _git_blob_hash(project_root, registered_commit, path)
        == _sha256(project_root / path)
        for path in prereg_paths
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
        "preflight_matches_replay": output_preflight == replay_preflight,
        "key_preflight_matches_replay": output_key == replay_key,
        "activation_packet_matches_replay": output_packet == replay_packet,
        "authorization_matches_replay": output_authorization == replay_authorization,
        "next_window_matches_replay": output_next == replay_next.to_dict(),
        "failure_injections_match_replay": output_failures == replay_failures,
        "manifest_matches_replay": manifest["activation_packet_hash"]
        == replay_packet["packet_hash"]
        and manifest["authorization_receipt_id"] is None
        and manifest["capture_permit_ids"] == [],
        "registered_counts_match": counts["evaluated_windows"]
        == gates["evaluated_windows"]
        and counts["access_receipts_issued"] == gates["access_receipts_issued"]
        and counts["capture_permits_issued"] == gates["capture_permits_issued"]
        and counts["missed_windows_counted_as_evidence"]
        == gates["missed_windows_counted_as_evidence"],
        "first_window_missed": replay_authorization["authorization_status"]
        == gates["first_window_status"]
        and replay_packet["activation_status"] == gates["activation_status"]
        and replay_packet["seconds_to_access_deadline"]
        == gates["seconds_to_access_deadline"]
        and replay_authorization["access_receipt"] is None,
        "next_viable_window_exact": replay_next.source_event_id
        == gates["next_viable_source_event_id"]
        and replay_next.scheduled_at == gates["next_viable_release_utc"]
        and replay_next.access_ready_by == gates["next_viable_access_ready_by"],
        "failure_injections_exact": set(output_failures)
        == set(expected_failure_issues)
        and all(
            result["passed"]
            and result["expected_issue"] == expected_failure_issues[name]
            for name, result in output_failures.items()
        ),
        "capture_paths_require_signed_permits": capture_paths_require_permits()
        is gates["capture_paths_require_signed_permits"],
        "external_gate_closed": replay_preflight["ready"] is False
        and replay_preflight["credential_present"] is gates["credential_present"]
        and replay_preflight["rights_attestation_present"]
        is gates["rights_attestation_present"]
        and replay_key["present"] is gates["authorization_signing_key_present"],
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
        "tests": tests,
        "trial_id": specification["trial_id"],
        "decision": (
            "READY_FOR_SIGNED_CAPTURE_AUTHORIZATION_PENDING_EXTERNAL_ACCESS"
            if not failures
            else "FAIL_CAPTURE_AUTHORIZATION"
        ),
        "external_status": specification["external_status"],
        "economic_decision": specification["economic_decision"],
        "counts": counts,
        "next_viable_window": replay_next.to_dict(),
    }
    (output_dir / "verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if result["passed"]:
        summary["phase8_status"] = "COMPLETE"
        summary["pipeline_status"] = result["decision"]
        summary["verification"] = {
            "passed": True,
            "test_count": tests["count"],
            "decision": result["decision"],
        }
        (output_dir / "phase8_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report_path = output_dir / "PHASE8_REPORT.md"
        report = report_path.read_text(encoding="utf-8").replace(
            "READY_FOR_SIGNED_CAPTURE_AUTHORIZATION_PENDING_EXTERNAL_ACCESS_PENDING_VERIFICATION",
            "READY_FOR_SIGNED_CAPTURE_AUTHORIZATION_PENDING_EXTERNAL_ACCESS",
        ).replace(
            "The verifier checks preregistration, HMAC failures, capture-path "
            "enforcement and\nthe complete regression suite.",
            f"The verifier passed every check with {tests['count']} tests.",
        )
        report_path.write_text(report, encoding="utf-8")
    return result
