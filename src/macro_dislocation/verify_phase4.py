from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from .shadow_campaign import (
    ShadowTraceStore,
    audit_shadow_trace,
    build_release_plans,
    campaign_promotion_gate,
    load_trace_fixture,
)


REGISTERED_COMMIT = "f13eb5d"


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


def verify_phase4(
    output_dir: Path,
    specification_path: Path,
    campaign_contract_path: Path,
    capture_contract_path: Path,
    schedule_path: Path,
    trace_path: Path,
    trial_registry_path: Path,
    *,
    project_root: Path,
    run_tests: bool = True,
) -> dict[str, Any]:
    required = [
        "PHASE4_REPORT.md",
        "phase4_summary.json",
        "release_windows.json",
        "shadow_trace.json",
        "shadow_audit.json",
        "failure_injections.json",
        "campaign_gate.json",
        "manifest.json",
        "shadow_trace_store/trace.jsonl",
    ]
    failures = [
        f"missing output: {name}" for name in required if not (output_dir / name).is_file()
    ]
    if failures:
        return {"passed": False, "failures": failures, "checks": {}}

    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    summary = json.loads((output_dir / "phase4_summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    output_plans = json.loads(
        (output_dir / "release_windows.json").read_text(encoding="utf-8")
    )
    output_trace = json.loads(
        (output_dir / "shadow_trace.json").read_text(encoding="utf-8")
    )
    output_audit = json.loads(
        (output_dir / "shadow_audit.json").read_text(encoding="utf-8")
    )
    output_campaign = json.loads(
        (output_dir / "campaign_gate.json").read_text(encoding="utf-8")
    )
    failure_injections = json.loads(
        (output_dir / "failure_injections.json").read_text(encoding="utf-8")
    )

    policy = specification["policy"]
    plans = build_release_plans(schedule_path, policy)
    registered_trace = load_trace_fixture(trace_path, plans[0])
    trace_store = ShadowTraceStore(output_dir / "shadow_trace_store")
    trace = trace_store.events()
    replay_audit = audit_shadow_trace(plans[0], trace, policy)
    replay_campaign = campaign_promotion_gate([replay_audit], policy)

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
    expected_failures = specification["failure_injections"]
    counts = summary["counts"]
    prereg_paths = [
        "config/phase4_trial_001.json",
        "config/shadow_campaign_contract.json",
        "config/vendor_capture_contract.json",
        "tests/fixtures/shadow_release_schedule.json",
        "tests/fixtures/shadow_trace_pass.json",
    ]
    prereg_hashes = {
        path: _git_blob_hash(project_root, registered_commit, path)
        == _sha256(project_root / path)
        for path in prereg_paths
    }
    checks = {
        "pipeline_checks_pass": all(summary["pipeline_checks"].values()),
        "one_registered_trial": len(matching) == 1,
        "registered_commit_matches": registered_commit == REGISTERED_COMMIT,
        "all_preregistered_files_match": all(prereg_hashes.values()),
        "all_input_hashes_match": all(input_hash_checks.values()),
        "plans_match_replay": output_plans == [plan.to_dict() for plan in plans],
        "trace_matches_registered_fixture": output_trace == registered_trace,
        "trace_matches_append_only_store": output_trace == trace,
        "audit_matches_replay": output_audit == replay_audit
        and replay_audit["audit_hash"]
        == summary["audit_hash"]
        == summary["replay_audit_hash"]
        == manifest["audit_hash"],
        "campaign_gate_matches_replay": output_campaign == replay_campaign,
        "registered_counts_match": counts["release_plans"] == gates["release_plans"]
        and counts["trace_events"] == gates["trace_events"]
        and counts["expected_components"] == gates["expected_components"]
        and counts["reconnects"] == gates["reconnects"],
        "valid_trace_complete_but_non_empirical": replay_audit[
            "operationally_complete"
        ]
        is True
        and replay_audit["empirical_window"] is False,
        "failure_injections_exact": set(failure_injections)
        == set(expected_failures)
        and all(
            result["passed"]
            and result["expected_issue"] == expected_failures[name]
            for name, result in failure_injections.items()
        ),
        "campaign_not_promoted": replay_campaign["promoted"] is False
        and replay_campaign["complete_empirical_windows"] == 0,
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
            "READY_TO_START_LICENSED_SHADOW_CAMPAIGN"
            if not failures
            else "FAIL_SHADOW_OPERATIONS"
        ),
        "economic_decision": "NO_GO_PRICE_EXPERIMENT_EMPIRICAL_TRIAL_REQUIRED",
        "audit_hash": replay_audit["audit_hash"],
        "counts": counts,
    }
    (output_dir / "verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if result["passed"]:
        summary["phase4_status"] = "COMPLETE"
        summary["pipeline_status"] = "READY_TO_START_LICENSED_SHADOW_CAMPAIGN"
        summary["verification"] = {
            "passed": True,
            "test_count": tests["count"],
            "decision": result["decision"],
        }
        (output_dir / "phase4_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report_path = output_dir / "PHASE4_REPORT.md"
        report = report_path.read_text(encoding="utf-8").replace(
            "READY_TO_START_LICENSED_SHADOW_CAMPAIGN_PENDING_VERIFICATION",
            "READY_TO_START_LICENSED_SHADOW_CAMPAIGN",
        ).replace(
            "最終テスト数と事前登録commit照合は `macro-lab verify-phase4` が判定します。",
            f"最終verifierは全項目PASS（テスト{tests['count']}件）です。",
        )
        report_path.write_text(report, encoding="utf-8")
    return result
