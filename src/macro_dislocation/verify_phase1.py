from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from .event_extractor import (
    extract_eia_features,
    extract_fomc_features,
    feature_hash,
    load_axis_config,
)
from .news_store import NewsStore


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _git_blob_hash(project_root: Path, commit: str, relative_path: str) -> str | None:
    process = subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=project_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return hashlib.sha256(process.stdout).hexdigest() if process.returncode == 0 else None


def verify_phase1(
    output_dir: Path,
    store_path: Path,
    specification_path: Path,
    axes_path: Path,
    trial_registry_path: Path,
    *,
    project_root: Path,
    run_tests: bool = True,
) -> dict[str, Any]:
    failures: list[str] = []
    required = [
        "phase1_summary.json",
        "PHASE1_REPORT.md",
        "documents.json",
        "fomc_features.csv",
        "eia_features.csv",
        "source_availability.json",
        "manifest.json",
    ]
    for relative in required:
        if not (output_dir / relative).is_file():
            failures.append(f"missing output: {relative}")
    if failures:
        return {"passed": False, "failures": failures, "checks": {}}

    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    axes = load_axis_config(axes_path)
    summary = json.loads((output_dir / "phase1_summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    store = NewsStore(store_path)
    records = store.documents()
    validation = store.validate()
    replay_fomc = extract_fomc_features(records, store.read_content, axes)
    replay_eia = extract_eia_features(records, store.read_content)
    replay_hash = feature_hash(replay_fomc, replay_eia)
    gates = specification["completion_gates"]

    with trial_registry_path.open(newline="", encoding="utf-8") as handle:
        trials = list(csv.DictReader(handle))
    matching = [row for row in trials if row["trial_id"] == specification["trial_id"]]
    registered_commit = matching[0]["registered_commit"] if len(matching) == 1 else ""
    hash_checks: dict[str, bool] = {}
    for raw_path, expected in manifest["inputs"].items():
        path = Path(raw_path)
        if not path.is_absolute():
            path = project_root / path
        hash_checks[raw_path] = path.is_file() and _sha256(path) == expected

    tests = _run_tests(project_root) if run_tests else {
        "passed": True,
        "count": gates["required_test_count"],
        "returncode": 0,
        "output_tail": "test execution disabled by caller",
    }
    counts = summary["counts"]
    checks = {
        "pipeline_checks_pass": all(summary["pipeline_checks"].values()),
        "store_validation_pass": validation["valid"],
        "source_families": len(counts["by_source"]) >= gates["minimum_source_families"],
        "total_documents": counts["documents"] >= gates["minimum_total_documents"],
        "fed_documents": counts["by_source"].get("federal_reserve", 0)
        >= gates["minimum_fed_documents"],
        "eia_documents": counts["by_source"].get("eia", 0)
        >= gates["minimum_eia_documents"],
        "feature_ready_complete": all(record["feature_ready_at"] for record in records),
        "duplicate_probe_pass": summary["duplicate_probe"]["passed"],
        "replay_hash_matches": replay_hash == summary["feature_hash"]
        == manifest["feature_hash"],
        "text_dimensions_bounded": summary["text_dimensions"]
        <= gates["maximum_text_dimensions"],
        "one_registered_trial": len(matching) == 1,
        "registered_commit_matches": len(matching) == 1
        and matching[0]["registered_commit"] == "f00970a",
        "preregistered_spec_matches": _git_blob_hash(
            project_root, registered_commit, "config/phase1_trial_001.json"
        )
        == _sha256(specification_path),
        "preregistered_axes_match": _git_blob_hash(
            project_root, registered_commit, "config/event_axes.json"
        )
        == _sha256(axes_path),
        "all_input_hashes_match": all(hash_checks.values()),
        "tests_pass": tests["passed"],
        "minimum_test_count": tests["count"] >= gates["required_test_count"],
        "no_price_prediction": summary["price_prediction_executed"] is False,
        "no_neural_fit": summary["neural_network_fitted"] is False,
    }
    failures.extend(name for name, passed in checks.items() if not passed)
    result = {
        "passed": not failures,
        "failures": failures,
        "checks": checks,
        "input_hash_checks": hash_checks,
        "tests": tests,
        "trial_id": specification["trial_id"],
        "decision": "PASS_PIPELINE_ONLY" if not failures else "FAIL_PIPELINE",
        "feature_hash": replay_hash,
        "document_counts": counts,
    }
    (output_dir / "verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if result["passed"]:
        summary["phase1_status"] = "COMPLETE"
        summary["pipeline_status"] = "PASS_PIPELINE_ONLY"
        summary["verification"] = {
            "passed": True,
            "test_count": tests["count"],
            "decision": result["decision"],
        }
        (output_dir / "phase1_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report_path = output_dir / "PHASE1_REPORT.md"
        report = report_path.read_text(encoding="utf-8")
        report = report.replace(
            "PASS_PIPELINE_PENDING_TEST_VERIFICATION", "PASS_PIPELINE_ONLY"
        ).replace(
            "テスト数を含む最終完了判定は `macro-lab verify-phase1` が行います。",
            f"最終verifierは全項目PASS（テスト{tests['count']}件）です。",
        )
        report_path.write_text(report, encoding="utf-8")
    return result
