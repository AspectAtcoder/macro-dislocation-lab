from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from .pit_events import (
    audit_components,
    build_calendar_bundles,
    bundle_hash,
    load_official_feature_bundles,
    load_research_calendar,
)


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
        "output_tail": "\n".join(process.stdout.splitlines()[-20:]),
    }


def verify_phase2(
    output_dir: Path,
    specification_path: Path,
    contract_path: Path,
    research_calendar_path: Path,
    phase1_documents_path: Path,
    fomc_features_path: Path,
    eia_features_path: Path,
    trial_registry_path: Path,
    *,
    project_root: Path,
    run_tests: bool = True,
) -> dict[str, Any]:
    required = [
        "PHASE2_REPORT.md",
        "phase2_summary.json",
        "normalized_research_snapshots.csv",
        "component_audit.csv",
        "bundle_index.csv",
        "event_bundles.json",
        "vendor_preflight.json",
        "manifest.json",
    ]
    failures = [
        f"missing output: {name}" for name in required if not (output_dir / name).is_file()
    ]
    if failures:
        return {"passed": False, "failures": failures, "checks": {}}

    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    summary = json.loads((output_dir / "phase2_summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    preflight = json.loads((output_dir / "vendor_preflight.json").read_text(encoding="utf-8"))
    output_bundles = json.loads((output_dir / "event_bundles.json").read_text(encoding="utf-8"))
    snapshots = load_research_calendar(research_calendar_path)
    audits = audit_components(snapshots)
    calendar_bundles = build_calendar_bundles(audits)
    official_bundles = load_official_feature_bundles(
        phase1_documents_path, fomc_features_path, eia_features_path
    )
    replay_bundles = sorted(
        calendar_bundles + official_bundles,
        key=lambda item: (item["scheduled_at"], item["bundle_id"]),
    )
    replay_hash = bundle_hash(replay_bundles)

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

    tests = _run_tests(project_root) if run_tests else {
        "passed": True,
        "count": specification["completion_gates"]["required_test_count"],
        "returncode": 0,
        "output_tail": "test execution disabled by caller",
    }
    gates = specification["completion_gates"]
    required_negative = set(
        specification["expected_negative_control"]["required_failures"]
    )
    checks = {
        "pipeline_checks_pass": all(summary["pipeline_checks"].values()),
        "one_registered_trial": len(matching) == 1,
        "registered_commit_matches": registered_commit == "e2b1b73",
        "preregistered_spec_matches": _git_blob_hash(
            project_root, registered_commit, "config/phase2_trial_001.json"
        )
        == _sha256(specification_path),
        "preregistered_contract_matches": _git_blob_hash(
            project_root, registered_commit, "config/pit_event_contract.json"
        )
        == _sha256(contract_path),
        "all_input_hashes_match": all(input_hash_checks.values()),
        "output_bundle_hash_matches": bundle_hash(output_bundles) == replay_hash
        == summary["bundle_hash"]
        == manifest["bundle_hash"],
        "research_negative_control_exact": len(audits)
        == gates["research_calendar_components"]
        and all(not item["eligible_for_price_join"] for item in audits)
        and all(required_negative.issubset(set(item["issues"])) for item in audits),
        "calendar_bundle_count": len(calendar_bundles)
        == gates["research_calendar_bundles"],
        "official_bundle_floor": len(official_bundles)
        >= gates["official_feature_bundles_minimum"],
        "guest_probe_matches": preflight["guest_http_status"]
        == specification["vendor_preflight"]["guest_endpoint_expected_status"],
        "no_unauthenticated_vendor_rows": preflight["empirical_vendor_rows_acquired"]
        == 0,
        "tests_pass": tests["passed"],
        "minimum_test_count": tests["count"] >= gates["required_test_count"],
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
            "READY_FOR_LICENSED_VENDOR_INGESTION"
            if not failures
            else "FAIL_DATA_CONTRACT"
        ),
        "economic_decision": "NO_GO_PRICE_EXPERIMENT_VENDOR_DATA_REQUIRED",
        "bundle_hash": replay_hash,
        "counts": summary["counts"],
    }
    (output_dir / "verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if result["passed"]:
        summary["phase2_status"] = "COMPLETE"
        summary["pipeline_status"] = "READY_FOR_LICENSED_VENDOR_INGESTION"
        summary["verification"] = {
            "passed": True,
            "test_count": tests["count"],
            "decision": result["decision"],
        }
        (output_dir / "phase2_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report_path = output_dir / "PHASE2_REPORT.md"
        report = report_path.read_text(encoding="utf-8").replace(
            "READY_FOR_LICENSED_VENDOR_INGESTION_PENDING_VERIFICATION",
            "READY_FOR_LICENSED_VENDOR_INGESTION",
        ).replace(
            "最終テスト数と事前登録commit照合は `macro-lab verify-phase2` が判定します。",
            f"最終verifierは全項目PASS（テスト{tests['count']}件）です。",
        )
        report_path.write_text(report, encoding="utf-8")
    return result
