from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from macro_dislocation.activation_handoff import (
    audit_component_binding,
    compile_activation_handoff,
    shadow_schedule_bytes,
)
from macro_dislocation.campaign_roster import campaign_readiness, load_campaign_roster
from macro_dislocation.shadow_campaign import build_release_plans
from macro_dislocation.vendor_capture import VendorCaptureStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads(
    (PROJECT_ROOT / "config/phase7_trial_001.json").read_text(encoding="utf-8")
)
PHASE6 = json.loads(
    (PROJECT_ROOT / "config/phase6_trial_001.json").read_text(encoding="utf-8")
)
PHASE4 = json.loads(
    (PROJECT_ROOT / "config/phase4_trial_001.json").read_text(encoding="utf-8")
)
BINDING_PATH = PROJECT_ROOT / "tests/fixtures/phase7_component_binding.json"
BLOCKED = {
    "ready": False,
    "credential_present": False,
    "rights_attestation_present": False,
    "issues": ["missing_vendor_credential", "missing_rights_attestation"],
}
READY = {
    "ready": True,
    "credential_present": True,
    "rights_attestation_present": True,
    "issues": [],
}


class ActivationHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.binding = json.loads(BINDING_PATH.read_text(encoding="utf-8"))
        self.roster = load_campaign_roster(
            PROJECT_ROOT / "config/phase6_campaign_roster_001.json", PHASE6["policy"]
        )
        self.window = self.roster.windows[0]

    def audit(self, binding: dict[str, object] | None = None) -> dict[str, object]:
        return audit_component_binding(
            binding or self.binding,
            self.window,
            SPEC["evaluated_at"],
            SPEC["policy"],
        )

    def licensed_binding(self) -> dict[str, object]:
        value = json.loads(json.dumps(self.binding))
        value["provenance"] = "licensed_vendor_snapshot"
        value["license_class"] = "licensed_internal_research"
        value["rights_profile"] = {
            name: True for name in SPEC["policy"]["required_rights"]
        }
        return value

    def verified_binding(
        self, root: Path
    ) -> tuple[dict[str, object], VendorCaptureStore, dict[str, object]]:
        binding = self.licensed_binding()
        payload = [
            {
                "CalendarId": item["provider_event_id"],
                "Date": item["scheduled_at"],
                "Country": "United States",
                "Category": item["provider_indicator"],
                "Event": item["provider_indicator"],
                "Reference": item["reference_period"],
                "SourceURL": "https://www.bls.gov/cpi/",
                "Actual": "",
                "Forecast": "3.0%",
                "Previous": "2.9%",
                "Currency": "USD",
                "Unit": item["unit"],
            }
            for item in binding["components"]
        ]
        store = VendorCaptureStore(root / "capture_store")
        result = store.capture(
            json.dumps(payload).encode("utf-8"),
            provider="trading_economics",
            transport="https_snapshot",
            endpoint="https://api.tradingeconomics.com/calendar/country/united-states",
            request_started_at="2026-08-11T09:59:59+00:00",
            received_at=binding["captured_at"],
            received_monotonic_ns=1,
            http_status=200,
            license_class=binding["license_class"],
            rights_profile=binding["rights_profile"],
            provenance="authenticated_api_snapshot",
        )
        binding["capture_id"] = result.observation["capture_id"]
        audit = audit_component_binding(
            binding,
            self.window,
            SPEC["evaluated_at"],
            SPEC["policy"],
            capture_store=store,
        )
        return binding, store, audit

    def activation_packet(self, preflight: dict[str, object]) -> dict[str, object]:
        return campaign_readiness(
            self.roster, SPEC["evaluated_at"], preflight, PHASE6["policy"]
        )["activation_packet"]

    def test_synthetic_binding_is_structural_only(self) -> None:
        audit = self.audit()
        self.assertTrue(audit["structurally_complete"])
        self.assertFalse(audit["execution_eligible"])
        self.assertIn("synthetic_binding_not_empirical", audit["issues"])

    def test_missing_logical_component_fails(self) -> None:
        value = json.loads(json.dumps(self.binding))
        value["components"] = value["components"][:1]
        self.assertIn("missing_logical_component", self.audit(value)["issues"])

    def test_duplicate_provider_event_id_fails(self) -> None:
        value = json.loads(json.dumps(self.binding))
        value["components"][1]["provider_event_id"] = value["components"][0][
            "provider_event_id"
        ]
        self.assertIn("duplicate_provider_event_id", self.audit(value)["issues"])

    def test_provider_schedule_drift_fails(self) -> None:
        value = json.loads(json.dumps(self.binding))
        value["components"][0]["scheduled_at"] = "2026-08-12T12:31:00+00:00"
        self.assertIn("provider_schedule_mismatch", self.audit(value)["issues"])

    def test_stale_binding_fails(self) -> None:
        value = json.loads(json.dumps(self.binding))
        value["captured_at"] = "2026-08-09T10:00:00+00:00"
        self.assertIn("binding_snapshot_stale", self.audit(value)["issues"])

    def test_licensed_claim_without_capture_store_is_not_eligible(self) -> None:
        audit = self.audit(self.licensed_binding())
        self.assertTrue(audit["structurally_complete"])
        self.assertFalse(audit["execution_eligible"])
        self.assertIn("capture_receipt_not_verified", audit["issues"])

    def test_immutable_capture_receipt_makes_binding_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, _, audit = self.verified_binding(Path(directory))
        self.assertTrue(audit["structurally_complete"])
        self.assertTrue(audit["capture_receipt_verified"])
        self.assertTrue(audit["execution_eligible"])
        self.assertEqual(audit["issues"], [])

    def test_provider_metadata_must_replay_from_capture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            binding, store, _ = self.verified_binding(Path(directory))
            binding["components"][0]["provider_indicator"] = "Mislabelled CPI"
            audit = audit_component_binding(
                binding,
                self.window,
                SPEC["evaluated_at"],
                SPEC["policy"],
                capture_store=store,
            )
        self.assertFalse(audit["execution_eligible"])
        self.assertIn("capture_provider_indicator_mismatch", audit["issues"])

    def test_blocked_activation_never_issues_permit(self) -> None:
        handoff = compile_activation_handoff(
            self.roster,
            self.window,
            self.binding,
            self.audit(),
            self.activation_packet(BLOCKED),
            SPEC["policy"],
        )
        self.assertFalse(handoff["executable"])
        self.assertIsNone(handoff["execution_permit"])
        self.assertIn("activation_status_not_ready", handoff["issues"])

    def test_ready_activation_and_licensed_binding_issue_permit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            binding, _, audit = self.verified_binding(Path(directory))
            handoff = compile_activation_handoff(
                self.roster,
                self.window,
                binding,
                audit,
                self.activation_packet(READY),
                SPEC["policy"],
            )
        self.assertTrue(handoff["executable"])
        self.assertEqual(handoff["handoff_status"], "AUTHORIZED_FOR_SHADOW_CAPTURE")
        self.assertEqual(handoff["execution_permit"]["action"], "shadow_capture")

    def test_preview_is_accepted_by_phase4_plan_builder(self) -> None:
        handoff = compile_activation_handoff(
            self.roster,
            self.window,
            self.binding,
            self.audit(),
            self.activation_packet(BLOCKED),
            SPEC["policy"],
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.json"
            path.write_bytes(shadow_schedule_bytes(handoff["shadow_schedule_preview"]))
            plans = build_release_plans(path, PHASE4["policy"])
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].schedule_sha256, handoff["shadow_schedule_sha256"])
        self.assertEqual(
            plans[0].expected_components,
            ["SYNTH-TE-CORE-CPI-2026-07", "SYNTH-TE-CPI-2026-07"],
        )


if __name__ == "__main__":
    unittest.main()
