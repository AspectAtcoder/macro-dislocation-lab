from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from macro_dislocation.evidence_enrollment import (
    EvidenceLedger,
    campaign_checkpoint,
    seal_evidence_package,
    validate_evidence_package,
    validate_ledger_candidates,
    vendor_access_preflight,
)
from macro_dislocation.phase5 import run_phase5
from macro_dislocation.shadow_campaign import shadow_audit_hash


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPECIFICATION = json.loads(
    (PROJECT_ROOT / "config/phase5_trial_001.json").read_text(encoding="utf-8")
)


def run_fixture(output: Path) -> dict[str, object]:
    return run_phase5(
        PROJECT_ROOT / "config/phase5_trial_001.json",
        PROJECT_ROOT / "config/empirical_evidence_contract.json",
        PROJECT_ROOT / "config/vendor_capture_contract.json",
        PROJECT_ROOT / "config/shadow_campaign_contract.json",
        PROJECT_ROOT / "tests/fixtures/phase5_release_schedule.json",
        PROJECT_ROOT / "tests/fixtures/phase5_trace_linked.json",
        PROJECT_ROOT / "tests/fixtures/phase5_te_pre_release.json",
        PROJECT_ROOT / "tests/fixtures/phase5_te_post_release.json",
        output,
        project_root=PROJECT_ROOT,
    )


def licensed_package(
    base: dict[str, object], index: int, event_family: str
) -> dict[str, object]:
    package = deepcopy(base)
    window = package["window_audit"]
    window["run_id"] = f"licensed-run-{index}"
    window["plan_id"] = f"licensed-plan-{index}"
    window["event_family"] = event_family
    window["scheduled_at"] = f"2030-{index + 1:02d}-10T13:30:00+00:00"
    window["provenance"] = "licensed_shadow"
    window["operationally_complete"] = True
    window["empirical_window"] = True
    window["issues"] = []
    window["audit_hash"] = shadow_audit_hash(window)
    package["run_id"] = window["run_id"]
    package["plan_id"] = window["plan_id"]
    package["event_family"] = event_family
    package["scheduled_at"] = window["scheduled_at"]
    package["window_audit_hash"] = window["audit_hash"]
    package["structurally_complete"] = True
    package["enrollable"] = True
    package["structural_issues"] = []
    package["eligibility_issues"] = []
    package["issues"] = []
    return seal_evidence_package(package)


class EvidenceEnrollmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.output = Path(self.temporary.name) / "output"
        self.summary = run_fixture(self.output)
        self.package = self.summary["evidence_package"]

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_fixture_is_structural_only(self) -> None:
        self.assertTrue(self.package["structurally_complete"])
        self.assertFalse(self.package["enrollable"])
        self.assertEqual(self.package["structural_issues"], [])
        self.assertIn("synthetic_capture_not_empirical", self.package["issues"])

    def test_valid_package_hash_and_window_hash_are_self_consistent(self) -> None:
        self.assertEqual(validate_evidence_package(self.package), [])

    def test_package_hash_tamper_fails_closed(self) -> None:
        value = deepcopy(self.package)
        value["capture_reference_count"] = 999
        self.assertIn(
            "evidence_package_hash_mismatch", validate_evidence_package(value)
        )

    def test_offline_preflight_reports_both_external_inputs(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            result = vendor_access_preflight()
        self.assertFalse(result["ready"])
        self.assertEqual(
            result["issues"],
            ["missing_rights_attestation", "missing_vendor_credential"],
        )

    def test_complete_access_preflight_never_exposes_credential(self) -> None:
        path = Path(self.temporary.name) / "rights.json"
        path.write_text(
            json.dumps(
                {
                    "approved": True,
                    "agreement_id": "agreement-2030-001",
                    "approved_by": "Research Compliance",
                    "attested_at": "2030-01-01T00:00:00+00:00",
                    "provider": "Trading Economics",
                    "license_class": "research-production",
                    "rights": {
                        "retention": True,
                        "historical_backtesting": True,
                        "machine_learning": True,
                        "derived_data": True,
                    },
                }
            ),
            encoding="utf-8",
        )
        with patch.dict(
            "os.environ", {"TRADING_ECONOMICS_API_KEY": "not-returned"}, clear=True
        ):
            result = vendor_access_preflight(path)
        self.assertTrue(result["ready"])
        self.assertNotIn("not-returned", json.dumps(result))

    def test_non_enrollable_package_cannot_enter_ledger(self) -> None:
        ledger = EvidenceLedger(Path(self.temporary.name) / "ledger")
        with self.assertRaisesRegex(ValueError, "not_enrollable"):
            ledger.append(self.package)

    def test_hash_valid_enrollable_package_round_trips(self) -> None:
        ledger = EvidenceLedger(Path(self.temporary.name) / "ledger")
        value = licensed_package(self.package, 0, "CPI")
        ledger.append(value)
        self.assertEqual(ledger.packages(), [value])

    def test_duplicate_package_is_rejected_before_append(self) -> None:
        ledger = EvidenceLedger(Path(self.temporary.name) / "ledger")
        value = licensed_package(self.package, 0, "CPI")
        ledger.append(value)
        with self.assertRaisesRegex(ValueError, "duplicate_evidence_package"):
            ledger.append(value)
        self.assertEqual(len(ledger.packages()), 1)

    def test_duplicate_candidate_audit_fails(self) -> None:
        result = validate_ledger_candidates([self.package, self.package])
        self.assertFalse(result["passed"])
        self.assertIn("duplicate_evidence_package", result["issues"])

    def test_empty_campaign_checkpoint_does_not_promote(self) -> None:
        result = campaign_checkpoint([], SPECIFICATION["policy"])
        self.assertFalse(result["promoted"])
        self.assertEqual(result["eligible_packages"], 0)

    def test_three_cpi_and_three_nfp_packages_promote(self) -> None:
        packages = [
            licensed_package(self.package, index, "CPI" if index < 3 else "NFP")
            for index in range(6)
        ]
        result = campaign_checkpoint(packages, SPECIFICATION["policy"])
        self.assertTrue(result["promoted"])
        self.assertEqual(result["complete_cpi_windows"], 3)
        self.assertEqual(result["complete_nfp_windows"], 3)

    def test_all_registered_failure_injections_fail_closed(self) -> None:
        failures = self.summary["failure_injections"]
        self.assertEqual(set(failures), set(SPECIFICATION["failure_injections"]))
        self.assertTrue(all(item["passed"] for item in failures.values()))

    def test_capture_references_resolve_to_two_immutable_receipts(self) -> None:
        self.assertEqual(self.package["capture_reference_count"], 3)
        self.assertEqual(len(self.package["referenced_capture_ids"]), 2)
        self.assertEqual(self.package["capture_integrity"]["observations"], 2)
        self.assertEqual(self.package["capture_integrity"]["unique_raw_blobs"], 2)


if __name__ == "__main__":
    unittest.main()
