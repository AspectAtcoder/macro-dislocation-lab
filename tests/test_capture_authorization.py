from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from macro_dislocation.campaign_roster import campaign_readiness, load_campaign_roster
from macro_dislocation.cli import parser
from macro_dislocation.capture_authorization import (
    authorization_key_preflight,
    issue_access_authorization,
    issue_capture_permit,
    next_viable_window,
    validate_access_receipt,
    validate_capture_permit,
    write_signed_artifact_once,
)
from macro_dislocation.pit_events import RIGHTS
from macro_dislocation.vendor_capture import (
    VendorCaptureStore,
    capture_authenticated_snapshot,
    capture_stream_jsonl,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads(
    (PROJECT_ROOT / "config/phase8_trial_001.json").read_text(encoding="utf-8")
)
PHASE6 = json.loads(
    (PROJECT_ROOT / "config/phase6_trial_001.json").read_text(encoding="utf-8")
)
AUTH_KEY = "phase8-unit-authorization-key-00000001"
READY = {
    "ready": True,
    "credential_present": True,
    "rights_attestation_present": True,
    "issues": [],
}
BLOCKED = {
    "ready": False,
    "credential_present": False,
    "rights_attestation_present": False,
    "issues": ["missing_vendor_credential", "missing_rights_attestation"],
}


def rights_attestation() -> dict[str, object]:
    return {
        "approved": True,
        "agreement_id": "agreement-2026-authorization",
        "approved_by": "data-governance",
        "attested_at": "2026-08-10T00:00:00+00:00",
        "provider": "Trading Economics",
        "license_class": "licensed_internal_research",
        "rights": {name: True for name in RIGHTS},
    }


class CaptureAuthorizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.roster = load_campaign_roster(
            PROJECT_ROOT / "config/phase6_campaign_roster_001.json", PHASE6["policy"]
        )
        self.window = self.roster.windows[0]
        self.ready_packet = campaign_readiness(
            self.roster, PHASE6["evaluated_at"], READY, PHASE6["policy"]
        )["activation_packet"]

    def issue_receipt(self, root: Path) -> dict[str, object]:
        rights = root / "rights.json"
        rights.write_text(json.dumps(rights_attestation()), encoding="utf-8")
        with patch.dict(
            os.environ,
            {
                "TRADING_ECONOMICS_API_KEY": "unit-vendor-credential",
                "MACRO_LAB_AUTHORIZATION_KEY": AUTH_KEY,
            },
            clear=True,
        ):
            decision = issue_access_authorization(
                self.roster,
                self.window,
                self.ready_packet,
                rights,
                SPEC["policy"],
            )
        self.assertEqual(decision["authorization_status"], "ACCESS_RECEIPT_ISSUED")
        return decision["access_receipt"]

    def test_authorization_key_preflight_never_returns_key(self) -> None:
        with patch.dict(
            os.environ, {"MACRO_LAB_AUTHORIZATION_KEY": AUTH_KEY}, clear=True
        ):
            result = authorization_key_preflight(SPEC["policy"])
        self.assertTrue(result["present"])
        self.assertTrue(result["valid"])
        self.assertNotIn(AUTH_KEY, json.dumps(result))

    def test_late_window_issues_no_receipt(self) -> None:
        packet = campaign_readiness(
            self.roster, SPEC["evaluated_at"], BLOCKED, PHASE6["policy"]
        )["activation_packet"]
        with patch.dict(os.environ, {}, clear=True):
            result = issue_access_authorization(
                self.roster, self.window, packet, None, SPEC["policy"]
            )
        self.assertEqual(result["authorization_status"], "MISSED_ACCESS_DEADLINE")
        self.assertIsNone(result["access_receipt"])

    def test_authorized_receipt_survives_access_deadline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            receipt = self.issue_receipt(Path(directory))
        with patch.dict(
            os.environ, {"MACRO_LAB_AUTHORIZATION_KEY": AUTH_KEY}, clear=True
        ):
            issues = validate_access_receipt(
                receipt,
                self.roster,
                self.window,
                SPEC["evaluated_at"],
                SPEC["policy"],
            )
        self.assertEqual(issues, [])

    def test_receipt_tampering_breaks_hmac(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            receipt = self.issue_receipt(Path(directory))
        receipt["license_class"] = "changed"
        with patch.dict(
            os.environ, {"MACRO_LAB_AUTHORIZATION_KEY": AUTH_KEY}, clear=True
        ):
            issues = validate_access_receipt(
                receipt,
                self.roster,
                self.window,
                SPEC["evaluated_at"],
                SPEC["policy"],
            )
        self.assertIn("access_receipt_signature_mismatch", issues)

    def test_next_viable_window_skips_missed_cpi(self) -> None:
        window = next_viable_window(self.roster, SPEC["evaluated_at"])
        self.assertIsNotNone(window)
        self.assertEqual(window.source_event_id, "BLS-NFP-2026-08")

    def test_pre_release_snapshot_permit_is_too_early(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            receipt = self.issue_receipt(Path(directory))
        with patch.dict(
            os.environ, {"MACRO_LAB_AUTHORIZATION_KEY": AUTH_KEY}, clear=True
        ):
            decision = issue_capture_permit(
                receipt,
                self.roster,
                self.window,
                "pre_release_snapshot",
                SPEC["evaluated_at"],
                SPEC["policy"],
            )
        self.assertIsNone(decision["capture_permit"])
        self.assertIn("capture_action_too_early", decision["issues"])

    def test_binding_snapshot_permit_can_be_issued(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            receipt = self.issue_receipt(Path(directory))
        with patch.dict(
            os.environ, {"MACRO_LAB_AUTHORIZATION_KEY": AUTH_KEY}, clear=True
        ):
            decision = issue_capture_permit(
                receipt,
                self.roster,
                self.window,
                "binding_snapshot",
                SPEC["evaluated_at"],
                SPEC["policy"],
            )
        self.assertEqual(decision["permit_status"], "CAPTURE_PERMIT_ISSUED")
        self.assertEqual(decision["capture_permit"]["action"], "binding_snapshot")

    def test_permit_action_confusion_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            receipt = self.issue_receipt(Path(directory))
        with patch.dict(
            os.environ, {"MACRO_LAB_AUTHORIZATION_KEY": AUTH_KEY}, clear=True
        ):
            permit = issue_capture_permit(
                receipt,
                self.roster,
                self.window,
                "binding_snapshot",
                SPEC["evaluated_at"],
                SPEC["policy"],
            )["capture_permit"]
            issues = validate_capture_permit(
                permit, "calendar_stream", SPEC["evaluated_at"], SPEC["policy"]
            )
        self.assertIn("capture_permit_action_mismatch", issues)

    def test_permit_expiry_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            receipt = self.issue_receipt(Path(directory))
        with patch.dict(
            os.environ, {"MACRO_LAB_AUTHORIZATION_KEY": AUTH_KEY}, clear=True
        ):
            permit = issue_capture_permit(
                receipt,
                self.roster,
                self.window,
                "binding_snapshot",
                SPEC["evaluated_at"],
                SPEC["policy"],
            )["capture_permit"]
            issues = validate_capture_permit(
                permit,
                "binding_snapshot",
                "2026-08-12T12:30:01+00:00",
                SPEC["policy"],
            )
        self.assertIn("capture_permit_expired", issues)

    def test_snapshot_capture_requires_permit_before_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("macro_dislocation.vendor_capture.urlopen") as network:
                with self.assertRaisesRegex(RuntimeError, "authorization permit"):
                    capture_authenticated_snapshot(
                        VendorCaptureStore(root / "store"),
                        authorization_permit_path=root / "missing.json",
                        permit_action="binding_snapshot",
                        rights_attestation_path=root / "rights.json",
                        country="united states",
                        indicators=["cpi"],
                        start="2026-08-12",
                        end="2026-08-12",
                    )
            network.assert_not_called()

    def test_stream_capture_requires_permit_before_input(self) -> None:
        class ExplodingLines:
            def __iter__(self) -> object:
                raise AssertionError("stream input was consumed")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(RuntimeError, "authorization permit"):
                capture_stream_jsonl(
                    VendorCaptureStore(root / "store"),
                    ExplodingLines(),
                    authorization_permit_path=root / "missing.json",
                    rights_attestation_path=root / "rights.json",
                )

    def test_short_authorization_key_is_rejected(self) -> None:
        with patch.dict(
            os.environ, {"MACRO_LAB_AUTHORIZATION_KEY": "short"}, clear=True
        ):
            result = authorization_key_preflight(SPEC["policy"])
        self.assertTrue(result["present"])
        self.assertFalse(result["valid"])

    def test_signed_artifact_is_private_and_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            write_signed_artifact_once(path, {"receipt": "first"})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(RuntimeError, "already exists"):
                write_signed_artifact_once(path, {"receipt": "second"})
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")), {"receipt": "first"}
            )

    def test_authorization_cli_has_no_clock_override(self) -> None:
        command = parser()._subparsers._group_actions[0].choices[
            "authorize-campaign-access"
        ]
        self.assertNotIn("as_of", {action.dest for action in command._actions})

    def test_permit_cli_has_no_clock_override(self) -> None:
        command = parser()._subparsers._group_actions[0].choices[
            "issue-capture-permit"
        ]
        self.assertNotIn("as_of", {action.dest for action in command._actions})


if __name__ == "__main__":
    unittest.main()
