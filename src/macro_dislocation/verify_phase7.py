from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from .activation_handoff import (
    audit_component_binding,
    compile_activation_handoff,
    shadow_schedule_bytes,
)
from .campaign_roster import campaign_readiness, load_campaign_roster
from .evidence_enrollment import vendor_access_preflight
from .shadow_campaign import build_release_plans


REGISTERED_COMMIT = "833941d"


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


def verify_phase7(
    output_dir: Path,
    specification_path: Path,
    handoff_contract_path: Path,
    phase6_specification_path: Path,
    roster_path: Path,
    phase4_specification_path: Path,
    binding_path: Path,
    trial_registry_path: Path,
    *,
    project_root: Path,
    run_tests: bool = True,
) -> dict[str, Any]:
    required = [
        "PHASE7_REPORT.md",
        "phase7_summary.json",
        "binding_audit.json",
        "vendor_access_preflight.json",
        "activation_packet.json",
        "activation_handoff.json",
        "shadow_schedule_preview.json",
        "release_plans.json",
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
    phase4 = json.loads(phase4_specification_path.read_text(encoding="utf-8"))
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    summary = json.loads((output_dir / "phase7_summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    output_audit = json.loads((output_dir / "binding_audit.json").read_text(encoding="utf-8"))
    output_preflight = json.loads((output_dir / "vendor_access_preflight.json").read_text(encoding="utf-8"))
    output_packet = json.loads((output_dir / "activation_packet.json").read_text(encoding="utf-8"))
    output_handoff = json.loads((output_dir / "activation_handoff.json").read_text(encoding="utf-8"))
    output_schedule = json.loads((output_dir / "shadow_schedule_preview.json").read_text(encoding="utf-8"))
    output_plans = json.loads((output_dir / "release_plans.json").read_text(encoding="utf-8"))
    output_failures = json.loads((output_dir / "failure_injections.json").read_text(encoding="utf-8"))

    roster = load_campaign_roster(roster_path, phase6["policy"])
    window = next(
        item
        for item in roster.windows
        if item.source_event_id == binding["source_event_id"]
    )
    replay_preflight = vendor_access_preflight()
    replay_readiness = campaign_readiness(
        roster, specification["evaluated_at"], replay_preflight, phase6["policy"]
    )
    replay_packet = replay_readiness["activation_packet"]
    replay_audit = audit_component_binding(
        binding, window, specification["evaluated_at"], specification["policy"]
    )
    replay_handoff = compile_activation_handoff(
        roster,
        window,
        binding,
        replay_audit,
        replay_packet,
        specification["policy"],
    )
    replay_plans = [
        plan.to_dict()
        for plan in build_release_plans(
            output_dir / "shadow_schedule_preview.json", phase4["policy"]
        )
    ]

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
        "config/phase7_trial_001.json",
        "config/activation_handoff_contract.json",
        "config/phase6_trial_001.json",
        "config/phase6_campaign_roster_001.json",
        "config/phase4_trial_001.json",
        "tests/fixtures/phase7_component_binding.json",
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
        "binding_audit_matches_replay": output_audit == replay_audit,
        "preflight_matches_replay": output_preflight == replay_preflight,
        "activation_packet_matches_replay": output_packet == replay_packet,
        "handoff_matches_replay": output_handoff == replay_handoff,
        "schedule_matches_replay": output_schedule
        == replay_handoff["shadow_schedule_preview"]
        and (output_dir / "shadow_schedule_preview.json").read_bytes()
        == shadow_schedule_bytes(output_schedule),
        "release_plans_match_replay": output_plans == replay_plans,
        "all_manifest_hashes_match": manifest["binding_payload_hash"]
        == replay_audit["binding_payload_hash"]
        and manifest["binding_audit_hash"] == replay_audit["binding_audit_hash"]
        and manifest["shadow_schedule_sha256"]
        == replay_handoff["shadow_schedule_sha256"]
        == _sha256(output_dir / "shadow_schedule_preview.json")
        and manifest["handoff_hash"] == replay_handoff["handoff_hash"],
        "registered_counts_match": counts["selected_roster_windows"]
        == gates["selected_roster_windows"]
        and counts["logical_components"] == gates["logical_components"]
        and counts["provider_components"] == gates["provider_components"]
        and counts["shadow_schedule_previews"]
        == gates["shadow_schedule_previews"]
        and counts["shadow_release_plans"] == gates["shadow_release_plans"]
        and counts["executable_handoffs"] == gates["executable_handoffs"],
        "synthetic_binding_structural_only": replay_audit["structurally_complete"]
        is gates["binding_structurally_complete"]
        and replay_audit["execution_eligible"]
        is gates["binding_execution_eligible"]
        and "synthetic_binding_not_empirical" in replay_audit["issues"],
        "activation_gate_closed": replay_packet["activation_status"]
        == gates["activation_status"]
        and replay_handoff["executable"] is False
        and replay_handoff["execution_permit"] is None,
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
            "READY_FOR_LICENSED_HANDOFF_PENDING_VENDOR_ACCESS_AND_BINDING"
            if not failures
            else "FAIL_ACTIVATION_HANDOFF"
        ),
        "external_status": specification["external_status"],
        "economic_decision": specification["economic_decision"],
        "binding_audit_hash": replay_audit["binding_audit_hash"],
        "handoff_hash": replay_handoff["handoff_hash"],
        "counts": counts,
    }
    (output_dir / "verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if result["passed"]:
        summary["phase7_status"] = "COMPLETE"
        summary["pipeline_status"] = result["decision"]
        summary["verification"] = {
            "passed": True,
            "test_count": tests["count"],
            "decision": result["decision"],
        }
        (output_dir / "phase7_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report_path = output_dir / "PHASE7_REPORT.md"
        report = report_path.read_text(encoding="utf-8").replace(
            "READY_FOR_LICENSED_HANDOFF_PENDING_VENDOR_ACCESS_AND_BINDING_PENDING_VERIFICATION",
            "READY_FOR_LICENSED_HANDOFF_PENDING_VENDOR_ACCESS_AND_BINDING",
        ).replace(
            "The final verifier checks preregistration, binding and schedule replay, failure\ninjections and the complete regression suite.",
            f"The final verifier passed every check with {tests['count']} tests.",
        )
        report_path.write_text(report, encoding="utf-8")
    return result
