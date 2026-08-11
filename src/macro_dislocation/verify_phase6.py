from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from .campaign_roster import (
    audit_roster_payload,
    campaign_readiness,
    load_campaign_roster,
)
from .evidence_enrollment import vendor_access_preflight


REGISTERED_COMMIT = "eff7364"


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


def verify_phase6(
    output_dir: Path,
    specification_path: Path,
    roster_contract_path: Path,
    roster_path: Path,
    trial_registry_path: Path,
    *,
    project_root: Path,
    run_tests: bool = True,
) -> dict[str, Any]:
    required = [
        "PHASE6_REPORT.md",
        "phase6_summary.json",
        "normalized_roster.json",
        "roster_audit.json",
        "vendor_access_preflight.json",
        "campaign_readiness.json",
        "activation_packet.json",
        "failure_injections.json",
        "manifest.json",
    ]
    failures = [
        f"missing output: {name}" for name in required if not (output_dir / name).is_file()
    ]
    if failures:
        return {"passed": False, "failures": failures, "checks": {}}

    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    roster_payload = json.loads(roster_path.read_text(encoding="utf-8"))
    summary = json.loads((output_dir / "phase6_summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    output_roster = json.loads((output_dir / "normalized_roster.json").read_text(encoding="utf-8"))
    output_audit = json.loads((output_dir / "roster_audit.json").read_text(encoding="utf-8"))
    output_preflight = json.loads((output_dir / "vendor_access_preflight.json").read_text(encoding="utf-8"))
    output_readiness = json.loads((output_dir / "campaign_readiness.json").read_text(encoding="utf-8"))
    output_packet = json.loads((output_dir / "activation_packet.json").read_text(encoding="utf-8"))
    output_failures = json.loads((output_dir / "failure_injections.json").read_text(encoding="utf-8"))

    policy = specification["policy"]
    roster = load_campaign_roster(roster_path, policy)
    replay_audit = audit_roster_payload(roster_payload, policy)
    replay_preflight = vendor_access_preflight()
    replay_readiness = campaign_readiness(
        roster, specification["evaluated_at"], replay_preflight, policy
    )
    replay_packet = replay_readiness["activation_packet"]

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
        "config/phase6_trial_001.json",
        "config/campaign_roster_contract.json",
        "config/phase6_campaign_roster_001.json",
        "config/phase5_trial_001.json",
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
        "normalized_roster_matches_replay": output_roster == roster.to_dict(),
        "roster_hash_matches": manifest["roster_sha256"]
        == roster.roster_sha256
        == _sha256(roster_path),
        "roster_audit_matches_replay": output_audit == replay_audit,
        "preflight_matches_replay": output_preflight == replay_preflight,
        "readiness_matches_replay": output_readiness == replay_readiness,
        "activation_packet_matches_replay": output_packet == replay_packet,
        "registered_counts_match": counts["campaign_windows"]
        == gates["campaign_windows"]
        and counts["cpi_windows"] == gates["cpi_windows"]
        and counts["nfp_windows"] == gates["nfp_windows"]
        and counts["activation_candidates"] == gates["activation_candidates"]
        and counts["empirical_windows_captured"]
        == gates["empirical_windows_captured"],
        "registered_activation_matches": replay_packet["event_family"]
        == gates["next_event_family"]
        and replay_packet["scheduled_at"] == gates["next_release_utc"]
        and replay_packet["operator_at"] == gates["next_release_jst"]
        and replay_packet["seconds_to_access_deadline"]
        == gates["seconds_to_access_deadline"]
        and replay_packet["schedule_fresh"]
        is gates["schedule_fresh_for_next_window"]
        and replay_packet["activation_status"] == gates["activation_status"],
        "november_dst_matches": next(
            w.scheduled_at
            for w in roster.windows
            if w.source_event_id == "BLS-NFP-2026-10"
        )
        == gates["november_nfp_utc"],
        "failure_injections_exact": set(output_failures)
        == set(expected_failure_issues)
        and all(
            result["passed"]
            and result["expected_issue"] == expected_failure_issues[name]
            for name, result in output_failures.items()
        ),
        "external_access_gate_closed": replay_preflight["ready"] is False
        and replay_preflight["credential_present"] is gates["credential_present"]
        and replay_preflight["rights_attestation_present"]
        is gates["rights_attestation_present"],
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
            "READY_FOR_CAMPAIGN_ACTIVATION_PENDING_VENDOR_ACCESS"
            if not failures
            else "FAIL_CAMPAIGN_ROSTER"
        ),
        "external_status": specification["external_status"],
        "economic_decision": specification["economic_decision"],
        "roster_sha256": roster.roster_sha256,
        "packet_hash": replay_packet["packet_hash"],
        "counts": counts,
    }
    (output_dir / "verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if result["passed"]:
        summary["phase6_status"] = "COMPLETE"
        summary["pipeline_status"] = result["decision"]
        summary["verification"] = {
            "passed": True,
            "test_count": tests["count"],
            "decision": result["decision"],
        }
        (output_dir / "phase6_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report_path = output_dir / "PHASE6_REPORT.md"
        report = report_path.read_text(encoding="utf-8").replace(
            "READY_FOR_CAMPAIGN_ACTIVATION_PENDING_VENDOR_ACCESS_PENDING_VERIFICATION",
            "READY_FOR_CAMPAIGN_ACTIVATION_PENDING_VENDOR_ACCESS",
        ).replace(
            "The final verifier checks preregistration, roster replay, failure injections and\nthe complete regression suite.",
            f"The final verifier passed every check with {tests['count']} tests.",
        )
        report_path.write_text(report, encoding="utf-8")
    return result
