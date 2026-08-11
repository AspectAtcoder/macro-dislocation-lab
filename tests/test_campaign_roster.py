from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path

from macro_dislocation.campaign_roster import (
    activation_packet,
    audit_roster_payload,
    campaign_readiness,
    load_campaign_roster,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads(
    (PROJECT_ROOT / "config/phase6_trial_001.json").read_text(encoding="utf-8")
)
ROSTER_PATH = PROJECT_ROOT / "config/phase6_campaign_roster_001.json"
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


class CampaignRosterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.roster = load_campaign_roster(ROSTER_PATH, SPEC["policy"])

    def test_registered_family_floors(self) -> None:
        self.assertEqual(len(self.roster.windows), 6)
        self.assertEqual(sum(w.event_family == "CPI" for w in self.roster.windows), 3)
        self.assertEqual(sum(w.event_family == "NFP" for w in self.roster.windows), 3)

    def test_august_release_uses_daylight_time(self) -> None:
        window = self.roster.windows[0]
        self.assertEqual(window.scheduled_at, "2026-08-12T12:30:00+00:00")
        self.assertEqual(window.operator_at, "2026-08-12T21:30:00+09:00")

    def test_november_release_uses_standard_time(self) -> None:
        window = self.roster.windows[-1]
        self.assertEqual(window.scheduled_at, "2026-11-06T13:30:00+00:00")
        self.assertEqual(window.operator_at, "2026-11-06T22:30:00+09:00")

    def test_frozen_readiness_matches_registered_deadline(self) -> None:
        result = campaign_readiness(
            self.roster, SPEC["evaluated_at"], BLOCKED, SPEC["policy"]
        )
        self.assertEqual(result["activation_candidates"], 1)
        self.assertEqual(
            result["activation_packet"]["seconds_to_access_deadline"], 8502
        )

    def test_missing_access_blocks_activation(self) -> None:
        packet = activation_packet(
            self.roster,
            self.roster.windows[0],
            SPEC["evaluated_at"],
            BLOCKED,
            SPEC["policy"],
        )
        self.assertEqual(packet["activation_status"], "BLOCKED_VENDOR_ACCESS")
        self.assertTrue(packet["schedule_fresh"])

    def test_approved_access_can_activate_fresh_window(self) -> None:
        packet = activation_packet(
            self.roster,
            self.roster.windows[0],
            SPEC["evaluated_at"],
            READY,
            SPEC["policy"],
        )
        self.assertEqual(packet["activation_status"], "READY_FOR_ACTIVATION")
        self.assertEqual(packet["issues"], [])

    def test_fixed_offset_is_rejected(self) -> None:
        payload = json.loads(ROSTER_PATH.read_text(encoding="utf-8"))
        payload["official_timezone"] = "Etc/GMT+4"
        audit = audit_roster_payload(payload, SPEC["policy"])
        self.assertIn("utc_conversion_mismatch", audit["issues"])

    def test_duplicate_release_is_rejected(self) -> None:
        payload = json.loads(ROSTER_PATH.read_text(encoding="utf-8"))
        payload["events"].append(dict(payload["events"][0]))
        audit = audit_roster_payload(payload, SPEC["policy"])
        self.assertIn("duplicate_release_window", audit["issues"])

    def test_stale_schedule_is_rejected(self) -> None:
        roster = replace(self.roster, checked_at="2026-08-01T00:00:00+00:00")
        packet = activation_packet(
            roster,
            roster.windows[0],
            SPEC["evaluated_at"],
            BLOCKED,
            SPEC["policy"],
        )
        self.assertEqual(packet["activation_status"], "BLOCKED_SCHEDULE_REFRESH")
        self.assertIn("schedule_refresh_required", packet["issues"])

    def test_expired_release_cannot_be_reconstructed(self) -> None:
        packet = activation_packet(
            self.roster,
            self.roster.windows[0],
            "2026-08-12T12:30:01+00:00",
            READY,
            SPEC["policy"],
        )
        self.assertEqual(packet["activation_status"], "EXPIRED")
        self.assertIn("release_window_expired", packet["issues"])


if __name__ == "__main__":
    unittest.main()
