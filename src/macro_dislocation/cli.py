from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .calendar_data import load_event_times, normalize_calendar
from .baseline import run_baseline
from .campaign_roster import (
    CampaignRoster,
    CampaignWindow,
    activation_packet,
    campaign_readiness,
    load_campaign_roster,
)
from .capture_authorization import (
    issue_access_authorization,
    issue_capture_permit,
    write_signed_artifact_once,
)
from .dukascopy import event_hours, write_quote_csv
from .experiment import run_experiment
from .evidence_enrollment import (
    EvidenceLedger,
    audit_evidence_package,
    campaign_checkpoint,
    vendor_access_preflight,
)
from .phase0 import run_phase0
from .phase1 import run_phase1
from .phase2 import run_phase2
from .phase3 import run_phase3
from .phase4 import run_phase4
from .phase5 import run_phase5
from .phase6 import run_phase6
from .phase7 import run_phase7
from .phase8 import run_phase8
from .phase9 import run_phase9
from .phase10 import build_empirical_pit_labels, run_phase10
from .phase11 import run_phase11, run_registered_backtest
from .phase12 import run_phase12
from .forward_test import (
    ForwardJournal,
    record_paper_signal,
    replay_forward_events,
    settle_paper_signal,
)
from .shadow_campaign import (
    ShadowTraceStore,
    audit_shadow_trace,
    build_release_plans,
    create_trace_event,
    query_ntp_clock_sample,
)
from .vendor_capture import (
    VendorCaptureStore,
    capture_authenticated_snapshot,
    capture_stream_jsonl,
)
from .verify import verify_phase0
from .verify_phase1 import verify_phase1
from .verify_phase2 import verify_phase2
from .verify_phase3 import verify_phase3
from .verify_phase4 import verify_phase4
from .verify_phase5 import verify_phase5
from .verify_phase6 import verify_phase6
from .verify_phase7 import verify_phase7
from .verify_phase8 import verify_phase8
from .verify_phase9 import verify_phase9
from .verify_phase10 import verify_phase10
from .verify_phase11 import verify_phase11
from .verify_phase12 import verify_phase12

CONSENSUS_URL = "https://huggingface.co/datasets/Ehsanrs2/Forex_Factory_Calendar"


def _calendar(args: argparse.Namespace) -> None:
    result = normalize_calendar(
        Path(args.raw_calendar),
        Path(args.schedule),
        Path(args.output),
        consensus_source_url=CONSENSUS_URL,
    )
    print(json.dumps(result, indent=2))


def _quotes(args: argparse.Namespace) -> None:
    times = load_event_times(Path(args.events))
    hours = event_hours(times, window_hours=args.window_hours)
    result = write_quote_csv(
        hours,
        Path(args.output),
        Path(args.cache),
        instrument=args.instrument,
        price_scale=args.price_scale,
    )
    print(json.dumps(result, indent=2))


def _experiment(args: argparse.Namespace) -> None:
    result = run_experiment(
        Path(args.quotes),
        Path(args.events),
        Path(args.output_dir),
        min_final_move_bps=args.min_final_move_bps,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _baseline(args: argparse.Namespace) -> None:
    result = run_baseline(
        Path(args.events),
        Path(args.metrics),
        Path(args.specification),
        Path(args.output_dir),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _phase0(args: argparse.Namespace) -> None:
    result = run_phase0(
        Path(args.events),
        Path(args.quotes),
        Path(args.specification),
        Path(args.news_sources),
        Path(args.output_dir),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _verify_phase0(args: argparse.Namespace) -> None:
    result = verify_phase0(
        Path(args.output_dir),
        Path(args.specification),
        Path(args.trial_registry),
        project_root=Path(args.project_root),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


def _phase1(args: argparse.Namespace) -> None:
    result = run_phase1(
        Path(args.specification),
        Path(args.axes),
        Path(args.news_sources),
        Path(args.store),
        Path(args.output_dir),
        workers=args.workers,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _verify_phase1(args: argparse.Namespace) -> None:
    result = verify_phase1(
        Path(args.output_dir),
        Path(args.store),
        Path(args.specification),
        Path(args.axes),
        Path(args.trial_registry),
        project_root=Path(args.project_root),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


def _phase2(args: argparse.Namespace) -> None:
    result = run_phase2(
        Path(args.specification),
        Path(args.contract),
        Path(args.research_calendar),
        Path(args.phase1_documents),
        Path(args.fomc_features),
        Path(args.eia_features),
        Path(args.output_dir),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _verify_phase2(args: argparse.Namespace) -> None:
    result = verify_phase2(
        Path(args.output_dir),
        Path(args.specification),
        Path(args.contract),
        Path(args.research_calendar),
        Path(args.phase1_documents),
        Path(args.fomc_features),
        Path(args.eia_features),
        Path(args.trial_registry),
        project_root=Path(args.project_root),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


def _phase3(args: argparse.Namespace) -> None:
    result = run_phase3(
        Path(args.specification),
        Path(args.capture_contract),
        Path(args.pit_contract),
        Path(args.output_dir),
        project_root=Path(args.project_root),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _verify_phase3(args: argparse.Namespace) -> None:
    result = verify_phase3(
        Path(args.output_dir),
        Path(args.specification),
        Path(args.capture_contract),
        Path(args.pit_contract),
        Path(args.trial_registry),
        project_root=Path(args.project_root),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


def _capture_te_snapshot(args: argparse.Namespace) -> None:
    result = capture_authenticated_snapshot(
        VendorCaptureStore(Path(args.store)),
        authorization_permit_path=Path(args.authorization_permit),
        permit_action=args.permit_action,
        rights_attestation_path=Path(args.rights_attestation),
        country=args.country,
        indicators=args.indicator,
        start=args.start,
        end=args.end,
        timeout=args.timeout,
    )
    print(
        json.dumps(
            {
                "observation": result.observation,
                "snapshots": [asdict(snapshot) for snapshot in result.snapshots],
                "inserted_blob": result.inserted_blob,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _capture_te_stream_jsonl(args: argparse.Namespace) -> None:
    results = capture_stream_jsonl(
        VendorCaptureStore(Path(args.store)),
        sys.stdin,
        authorization_permit_path=Path(args.authorization_permit),
        rights_attestation_path=Path(args.rights_attestation),
        endpoint=args.endpoint,
    )
    print(
        json.dumps(
            {
                "captured_messages": len(results),
                "capture_ids": [item.observation["capture_id"] for item in results],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _phase4(args: argparse.Namespace) -> None:
    result = run_phase4(
        Path(args.specification),
        Path(args.campaign_contract),
        Path(args.capture_contract),
        Path(args.schedule),
        Path(args.trace),
        Path(args.output_dir),
        project_root=Path(args.project_root),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _verify_phase4(args: argparse.Namespace) -> None:
    result = verify_phase4(
        Path(args.output_dir),
        Path(args.specification),
        Path(args.campaign_contract),
        Path(args.capture_contract),
        Path(args.schedule),
        Path(args.trace),
        Path(args.trial_registry),
        project_root=Path(args.project_root),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


def _shadow_plan(args: argparse.Namespace) -> None:
    specification = json.loads(Path(args.specification).read_text(encoding="utf-8"))
    plans = build_release_plans(Path(args.schedule), specification["policy"])
    value = [plan.to_dict() for plan in plans]
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _shadow_clock_sample(args: argparse.Namespace) -> None:
    event = query_ntp_clock_sample(
        args.server,
        run_id=args.run_id,
        plan_id=args.plan_id,
        timeout=args.timeout,
    )
    stored = ShadowTraceStore(Path(args.trace_store)).append(event)
    print(json.dumps(stored, ensure_ascii=False, indent=2))


def _record_shadow_event(args: argparse.Namespace) -> None:
    details = json.loads(Path(args.details_file).read_text(encoding="utf-8"))
    if not isinstance(details, dict):
        raise SystemExit("details file must contain one JSON object")
    event = create_trace_event(
        run_id=args.run_id,
        plan_id=args.plan_id,
        kind=args.kind,
        details=details,
    )
    stored = ShadowTraceStore(Path(args.trace_store)).append(event)
    print(json.dumps(stored, ensure_ascii=False, indent=2))


def _audit_shadow_run(args: argparse.Namespace) -> None:
    specification = json.loads(Path(args.specification).read_text(encoding="utf-8"))
    plans = build_release_plans(Path(args.schedule), specification["policy"])
    matching = [plan for plan in plans if plan.plan_id == args.plan_id]
    if len(matching) != 1:
        raise SystemExit(f"plan_id must identify exactly one plan: {args.plan_id}")
    audit = audit_shadow_trace(
        matching[0],
        ShadowTraceStore(Path(args.trace_store)).events(),
        specification["policy"],
    )
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2))


def _phase5(args: argparse.Namespace) -> None:
    result = run_phase5(
        Path(args.specification),
        Path(args.evidence_contract),
        Path(args.capture_contract),
        Path(args.campaign_contract),
        Path(args.schedule),
        Path(args.trace),
        Path(args.pre_payload),
        Path(args.post_payload),
        Path(args.output_dir),
        project_root=Path(args.project_root),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _verify_phase5(args: argparse.Namespace) -> None:
    result = verify_phase5(
        Path(args.output_dir),
        Path(args.specification),
        Path(args.evidence_contract),
        Path(args.capture_contract),
        Path(args.campaign_contract),
        Path(args.schedule),
        Path(args.trace),
        Path(args.pre_payload),
        Path(args.post_payload),
        Path(args.trial_registry),
        project_root=Path(args.project_root),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


def _phase6(args: argparse.Namespace) -> None:
    rights = Path(args.rights_attestation) if args.rights_attestation else None
    result = run_phase6(
        Path(args.specification),
        Path(args.roster_contract),
        Path(args.roster),
        Path(args.output_dir),
        project_root=Path(args.project_root),
        rights_attestation_path=rights,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _verify_phase6(args: argparse.Namespace) -> None:
    result = verify_phase6(
        Path(args.output_dir),
        Path(args.specification),
        Path(args.roster_contract),
        Path(args.roster),
        Path(args.trial_registry),
        project_root=Path(args.project_root),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


def _campaign_roster_status(args: argparse.Namespace) -> None:
    specification = json.loads(Path(args.specification).read_text(encoding="utf-8"))
    rights = Path(args.rights_attestation) if args.rights_attestation else None
    preflight = vendor_access_preflight(rights)
    roster = load_campaign_roster(Path(args.roster), specification["policy"])
    evaluated_at = datetime.now(timezone.utc).isoformat()
    result = campaign_readiness(
        roster, evaluated_at, preflight, specification["policy"]
    )
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _phase7(args: argparse.Namespace) -> None:
    result = run_phase7(
        Path(args.specification),
        Path(args.handoff_contract),
        Path(args.phase6_specification),
        Path(args.roster),
        Path(args.phase4_specification),
        Path(args.binding),
        Path(args.output_dir),
        project_root=Path(args.project_root),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _verify_phase7(args: argparse.Namespace) -> None:
    result = verify_phase7(
        Path(args.output_dir),
        Path(args.specification),
        Path(args.handoff_contract),
        Path(args.phase6_specification),
        Path(args.roster),
        Path(args.phase4_specification),
        Path(args.binding),
        Path(args.trial_registry),
        project_root=Path(args.project_root),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


def _phase8(args: argparse.Namespace) -> None:
    result = run_phase8(
        Path(args.specification),
        Path(args.authorization_contract),
        Path(args.phase6_specification),
        Path(args.roster),
        Path(args.phase4_specification),
        Path(args.rights_schema),
        Path(args.phase7_specification),
        Path(args.output_dir),
        project_root=Path(args.project_root),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _verify_phase8(args: argparse.Namespace) -> None:
    result = verify_phase8(
        Path(args.output_dir),
        Path(args.specification),
        Path(args.authorization_contract),
        Path(args.phase6_specification),
        Path(args.roster),
        Path(args.phase4_specification),
        Path(args.rights_schema),
        Path(args.phase7_specification),
        Path(args.trial_registry),
        project_root=Path(args.project_root),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


def _phase9(args: argparse.Namespace) -> None:
    result = run_phase9(
        Path(args.specification),
        Path(args.phase8_specification),
        Path(args.roster),
        Path(args.output_dir),
        project_root=Path(args.project_root),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _verify_phase9(args: argparse.Namespace) -> None:
    result = verify_phase9(
        Path(args.output_dir),
        Path(args.specification),
        Path(args.phase8_specification),
        Path(args.roster),
        Path(args.trial_registry),
        project_root=Path(args.project_root),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


def _phase10(args: argparse.Namespace) -> None:
    result = run_phase10(
        Path(args.specification),
        Path(args.events),
        Path(args.phase9_specification),
        Path(args.output_dir),
        project_root=Path(args.project_root),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _verify_phase10(args: argparse.Namespace) -> None:
    result = verify_phase10(
        Path(args.output_dir),
        Path(args.specification),
        Path(args.events),
        Path(args.phase9_specification),
        Path(args.trial_registry),
        project_root=Path(args.project_root),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


def _phase11(args: argparse.Namespace) -> None:
    result = run_phase11(
        Path(args.specification),
        Path(args.phase10_specification),
        Path(args.labels),
        Path(args.output_dir),
        project_root=Path(args.project_root),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _verify_phase11(args: argparse.Namespace) -> None:
    result = verify_phase11(
        Path(args.output_dir),
        Path(args.specification),
        Path(args.phase10_specification),
        Path(args.labels),
        Path(args.trial_registry),
        project_root=Path(args.project_root),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


def _phase12(args: argparse.Namespace) -> None:
    result = run_phase12(
        Path(args.specification),
        Path(args.phase11_specification),
        Path(args.labels),
        Path(args.model),
        Path(args.output_dir),
        project_root=Path(args.project_root),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _verify_phase12(args: argparse.Namespace) -> None:
    result = verify_phase12(
        Path(args.output_dir),
        Path(args.specification),
        Path(args.phase11_specification),
        Path(args.labels),
        Path(args.model),
        Path(args.trial_registry),
        project_root=Path(args.project_root),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


def _build_pit_labels(args: argparse.Namespace) -> None:
    result = build_empirical_pit_labels(
        Path(args.specification),
        Path(args.features),
        Path(args.quotes),
        Path(args.evidence_ledger),
        Path(args.output_dir),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _registered_backtest(args: argparse.Namespace) -> None:
    result = run_registered_backtest(
        Path(args.specification),
        Path(args.labels),
        Path(args.trial_registry),
        Path(args.output_dir),
        project_root=Path(args.project_root),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _paper_forward_status(args: argparse.Namespace) -> None:
    events = ForwardJournal(Path(args.journal)).events()
    print(json.dumps(replay_forward_events(events), ensure_ascii=False, indent=2))


def _paper_forward_signal(args: argparse.Namespace) -> None:
    now = datetime.now(timezone.utc).isoformat()
    journal = ForwardJournal(Path(args.journal))
    model = json.loads(Path(args.model).read_text(encoding="utf-8"))
    signal_input = json.loads(Path(args.input).read_text(encoding="utf-8"))
    specification = json.loads(Path(args.specification).read_text(encoding="utf-8"))
    phase11 = json.loads(Path(args.phase11_specification).read_text(encoding="utf-8"))
    if "synthetic_fixture" in model.get("training_provenance", []):
        raise SystemExit("prospective paper signals require a non-synthetic model")
    packages = {
        package["package_id"]: package
        for package in EvidenceLedger(Path(args.evidence_ledger)).packages()
    }
    evidence_id = str(signal_input.get("evidence_package_id") or "")
    package = packages.get(evidence_id)
    if package is None:
        raise SystemExit("prospective paper signal evidence is not enrolled")
    if (
        package.get("scheduled_at") != signal_input.get("scheduled_at")
        or str(package.get("event_family") or "").upper()
        != str(signal_input.get("event_family") or "").upper()
    ):
        raise SystemExit("prospective paper signal evidence identity mismatch")
    training_evidence = set(model.get("training_evidence_package_ids", []))
    if not training_evidence or not training_evidence.issubset(packages):
        raise SystemExit("model training evidence is not fully enrolled")
    event = record_paper_signal(
        journal,
        model,
        signal_input,
        now=now,
        policy=specification["policy"],
        kill_switch=not args.clear_kill_switch,
        trade_threshold_bp=float(phase11["model"]["trade_threshold_bp"]),
    )
    print(json.dumps(event, ensure_ascii=False, indent=2))


def _paper_forward_settle(args: argparse.Namespace) -> None:
    event = settle_paper_signal(
        ForwardJournal(Path(args.journal)),
        args.signal_id,
        occurred_at=datetime.now(timezone.utc).isoformat(),
        exit_bid=float(args.exit_bid),
        exit_ask=float(args.exit_ask),
        provenance=args.provenance,
    )
    print(json.dumps(event, ensure_ascii=False, indent=2))


def _select_roster_window(
    roster: CampaignRoster, source_event_id: str
) -> CampaignWindow:
    matching = [
        window for window in roster.windows if window.source_event_id == source_event_id
    ]
    if len(matching) != 1:
        raise SystemExit(
            f"source-event-id must select exactly one roster window: {source_event_id}"
        )
    return matching[0]


def _authorize_campaign_access(args: argparse.Namespace) -> None:
    phase6 = json.loads(Path(args.phase6_specification).read_text(encoding="utf-8"))
    phase8 = json.loads(Path(args.phase8_specification).read_text(encoding="utf-8"))
    roster = load_campaign_roster(Path(args.roster), phase6["policy"])
    window = _select_roster_window(roster, args.source_event_id)
    rights_path = Path(args.rights_attestation)
    preflight = vendor_access_preflight(rights_path)
    evaluated_at = datetime.now(timezone.utc).isoformat()
    packet = activation_packet(
        roster, window, evaluated_at, preflight, phase6["policy"]
    )
    decision = issue_access_authorization(
        roster, window, packet, rights_path, phase8["policy"]
    )
    receipt = decision["access_receipt"]
    if receipt is not None:
        write_signed_artifact_once(Path(args.output), receipt)
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    if receipt is None:
        raise SystemExit(1)


def _issue_capture_permit(args: argparse.Namespace) -> None:
    phase6 = json.loads(Path(args.phase6_specification).read_text(encoding="utf-8"))
    phase8 = json.loads(Path(args.phase8_specification).read_text(encoding="utf-8"))
    roster = load_campaign_roster(Path(args.roster), phase6["policy"])
    window = _select_roster_window(roster, args.source_event_id)
    receipt = json.loads(Path(args.access_receipt).read_text(encoding="utf-8"))
    evaluated_at = args.as_of or datetime.now(timezone.utc).isoformat()
    decision = issue_capture_permit(
        receipt,
        roster,
        window,
        args.action,
        evaluated_at,
        phase8["policy"],
    )
    permit = decision["capture_permit"]
    if permit is not None:
        write_signed_artifact_once(Path(args.output), permit)
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    if permit is None:
        raise SystemExit(1)


def _vendor_preflight(args: argparse.Namespace) -> None:
    path = Path(args.rights_attestation) if args.rights_attestation else None
    result = vendor_access_preflight(path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ready"]:
        raise SystemExit(1)


def _audit_evidence(args: argparse.Namespace) -> None:
    specification = json.loads(Path(args.specification).read_text(encoding="utf-8"))
    plans = build_release_plans(Path(args.schedule), specification["policy"])
    matching = [plan for plan in plans if plan.plan_id == args.plan_id]
    if len(matching) != 1:
        raise SystemExit(f"plan_id must identify exactly one plan: {args.plan_id}")
    rights = Path(args.rights_attestation) if args.rights_attestation else None
    credential = os.environ.get("TRADING_ECONOMICS_API_KEY", "")
    package = audit_evidence_package(
        matching[0],
        ShadowTraceStore(Path(args.trace_store)).events(),
        VendorCaptureStore(Path(args.capture_store)),
        specification["policy"],
        rights_attestation_path=rights,
        forbidden_values=(credential,) if credential else (),
    )
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(
        json.dumps(package, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(package, ensure_ascii=False, indent=2))


def _enroll_evidence(args: argparse.Namespace) -> None:
    package = json.loads(Path(args.package).read_text(encoding="utf-8"))
    stored = EvidenceLedger(Path(args.ledger)).append(package)
    print(json.dumps(stored, ensure_ascii=False, indent=2))


def _campaign_checkpoint(args: argparse.Namespace) -> None:
    specification = json.loads(Path(args.specification).read_text(encoding="utf-8"))
    result = campaign_checkpoint(
        EvidenceLedger(Path(args.ledger)).packages(), specification["policy"]
    )
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="macro-lab")
    commands = root.add_subparsers(required=True)

    calendar = commands.add_parser("normalize-calendar")
    calendar.add_argument("--raw-calendar", required=True)
    calendar.add_argument("--schedule", default="config/bls_2024_release_schedule.csv")
    calendar.add_argument("--output", default="data/processed/events_2024.csv")
    calendar.set_defaults(func=_calendar)

    quotes = commands.add_parser("download-quotes")
    quotes.add_argument("--events", default="data/processed/events_2024.csv")
    quotes.add_argument("--output", default="data/processed/usdjpy_ticks_2024.csv")
    quotes.add_argument("--cache", default="data/raw/dukascopy")
    quotes.add_argument("--instrument", default="USDJPY")
    quotes.add_argument("--price-scale", type=int, default=1_000)
    quotes.add_argument("--window-hours", type=int, default=1)
    quotes.set_defaults(func=_quotes)

    experiment = commands.add_parser("experiment0")
    experiment.add_argument("--events", default="data/processed/events_2024.csv")
    experiment.add_argument("--quotes", default="data/processed/usdjpy_ticks_2024.csv")
    experiment.add_argument("--output-dir", default="artifacts/experiment0_2024")
    experiment.add_argument("--min-final-move-bps", type=float, default=2.0)
    experiment.set_defaults(func=_experiment)

    baseline = commands.add_parser("phase0-baseline")
    baseline.add_argument("--events", default="data/processed/events_2024.csv")
    baseline.add_argument(
        "--metrics", default="artifacts/experiment0_2024/event_metrics.csv"
    )
    baseline.add_argument("--specification", default="config/phase0_trial_001.json")
    baseline.add_argument("--output-dir", default="artifacts/phase0_baseline_2024")
    baseline.set_defaults(func=_baseline)

    phase0 = commands.add_parser("phase0-complete")
    phase0.add_argument("--events", default="data/processed/events_2024.csv")
    phase0.add_argument("--quotes", default="data/processed/usdjpy_ticks_2024.csv")
    phase0.add_argument("--specification", default="config/phase0_trial_001.json")
    phase0.add_argument("--news-sources", default="config/news_sources.json")
    phase0.add_argument("--output-dir", default="artifacts/phase0_complete_2024")
    phase0.set_defaults(func=_phase0)

    verify = commands.add_parser("verify-phase0")
    verify.add_argument("--output-dir", default="artifacts/phase0_complete_2024")
    verify.add_argument("--specification", default="config/phase0_trial_001.json")
    verify.add_argument("--trial-registry", default="config/trial_registry.csv")
    verify.add_argument("--project-root", default=".")
    verify.set_defaults(func=_verify_phase0)

    phase1 = commands.add_parser("phase1-complete")
    phase1.add_argument("--specification", default="config/phase1_trial_001.json")
    phase1.add_argument("--axes", default="config/event_axes.json")
    phase1.add_argument("--news-sources", default="config/news_sources.json")
    phase1.add_argument("--store", default="data/raw/news_store")
    phase1.add_argument("--output-dir", default="artifacts/phase1_complete")
    phase1.add_argument("--workers", type=int, default=8)
    phase1.set_defaults(func=_phase1)

    verify1 = commands.add_parser("verify-phase1")
    verify1.add_argument("--output-dir", default="artifacts/phase1_complete")
    verify1.add_argument("--store", default="data/raw/news_store")
    verify1.add_argument("--specification", default="config/phase1_trial_001.json")
    verify1.add_argument("--axes", default="config/event_axes.json")
    verify1.add_argument("--trial-registry", default="config/trial_registry.csv")
    verify1.add_argument("--project-root", default=".")
    verify1.set_defaults(func=_verify_phase1)

    phase2 = commands.add_parser("phase2-complete")
    phase2.add_argument("--specification", default="config/phase2_trial_001.json")
    phase2.add_argument("--contract", default="config/pit_event_contract.json")
    phase2.add_argument("--research-calendar", default="data/processed/events_2024.csv")
    phase2.add_argument("--phase1-documents", default="artifacts/phase1_complete/documents.json")
    phase2.add_argument("--fomc-features", default="artifacts/phase1_complete/fomc_features.csv")
    phase2.add_argument("--eia-features", default="artifacts/phase1_complete/eia_features.csv")
    phase2.add_argument("--output-dir", default="artifacts/phase2_complete")
    phase2.set_defaults(func=_phase2)

    verify2 = commands.add_parser("verify-phase2")
    verify2.add_argument("--output-dir", default="artifacts/phase2_complete")
    verify2.add_argument("--specification", default="config/phase2_trial_001.json")
    verify2.add_argument("--contract", default="config/pit_event_contract.json")
    verify2.add_argument("--research-calendar", default="data/processed/events_2024.csv")
    verify2.add_argument("--phase1-documents", default="artifacts/phase1_complete/documents.json")
    verify2.add_argument("--fomc-features", default="artifacts/phase1_complete/fomc_features.csv")
    verify2.add_argument("--eia-features", default="artifacts/phase1_complete/eia_features.csv")
    verify2.add_argument("--trial-registry", default="config/trial_registry.csv")
    verify2.add_argument("--project-root", default=".")
    verify2.set_defaults(func=_verify_phase2)

    phase3 = commands.add_parser("phase3-complete")
    phase3.add_argument("--specification", default="config/phase3_trial_001.json")
    phase3.add_argument(
        "--capture-contract", default="config/vendor_capture_contract.json"
    )
    phase3.add_argument("--pit-contract", default="config/pit_event_contract.json")
    phase3.add_argument("--output-dir", default="artifacts/phase3_complete")
    phase3.add_argument("--project-root", default=".")
    phase3.set_defaults(func=_phase3)

    verify3 = commands.add_parser("verify-phase3")
    verify3.add_argument("--output-dir", default="artifacts/phase3_complete")
    verify3.add_argument("--specification", default="config/phase3_trial_001.json")
    verify3.add_argument(
        "--capture-contract", default="config/vendor_capture_contract.json"
    )
    verify3.add_argument("--pit-contract", default="config/pit_event_contract.json")
    verify3.add_argument("--trial-registry", default="config/trial_registry.csv")
    verify3.add_argument("--project-root", default=".")
    verify3.set_defaults(func=_verify_phase3)

    te_snapshot = commands.add_parser("capture-te-snapshot")
    te_snapshot.add_argument("--authorization-permit", required=True)
    te_snapshot.add_argument(
        "--permit-action",
        choices=("binding_snapshot", "pre_release_snapshot"),
        required=True,
    )
    te_snapshot.add_argument("--rights-attestation", required=True)
    te_snapshot.add_argument("--store", default="data/raw/vendor_capture_store")
    te_snapshot.add_argument("--country", default="united states")
    te_snapshot.add_argument("--indicator", action="append", required=True)
    te_snapshot.add_argument("--start", required=True)
    te_snapshot.add_argument("--end", required=True)
    te_snapshot.add_argument("--timeout", type=float, default=30.0)
    te_snapshot.set_defaults(func=_capture_te_snapshot)

    te_stream = commands.add_parser("capture-te-stream-jsonl")
    te_stream.add_argument("--authorization-permit", required=True)
    te_stream.add_argument("--rights-attestation", required=True)
    te_stream.add_argument("--store", default="data/raw/vendor_capture_store")
    te_stream.add_argument(
        "--endpoint", default="wss://stream.tradingeconomics.com/"
    )
    te_stream.set_defaults(func=_capture_te_stream_jsonl)

    phase4 = commands.add_parser("phase4-complete")
    phase4.add_argument("--specification", default="config/phase4_trial_001.json")
    phase4.add_argument(
        "--campaign-contract", default="config/shadow_campaign_contract.json"
    )
    phase4.add_argument(
        "--capture-contract", default="config/vendor_capture_contract.json"
    )
    phase4.add_argument(
        "--schedule", default="tests/fixtures/shadow_release_schedule.json"
    )
    phase4.add_argument("--trace", default="tests/fixtures/shadow_trace_pass.json")
    phase4.add_argument("--output-dir", default="artifacts/phase4_complete")
    phase4.add_argument("--project-root", default=".")
    phase4.set_defaults(func=_phase4)

    verify4 = commands.add_parser("verify-phase4")
    verify4.add_argument("--output-dir", default="artifacts/phase4_complete")
    verify4.add_argument("--specification", default="config/phase4_trial_001.json")
    verify4.add_argument(
        "--campaign-contract", default="config/shadow_campaign_contract.json"
    )
    verify4.add_argument(
        "--capture-contract", default="config/vendor_capture_contract.json"
    )
    verify4.add_argument(
        "--schedule", default="tests/fixtures/shadow_release_schedule.json"
    )
    verify4.add_argument("--trace", default="tests/fixtures/shadow_trace_pass.json")
    verify4.add_argument("--trial-registry", default="config/trial_registry.csv")
    verify4.add_argument("--project-root", default=".")
    verify4.set_defaults(func=_verify_phase4)

    shadow_plan = commands.add_parser("plan-shadow-window")
    shadow_plan.add_argument("--schedule", required=True)
    shadow_plan.add_argument("--specification", default="config/phase4_trial_001.json")
    shadow_plan.add_argument("--output", required=True)
    shadow_plan.set_defaults(func=_shadow_plan)

    clock_sample = commands.add_parser("record-shadow-clock-sample")
    clock_sample.add_argument("--server", required=True)
    clock_sample.add_argument("--run-id", required=True)
    clock_sample.add_argument("--plan-id", required=True)
    clock_sample.add_argument("--trace-store", required=True)
    clock_sample.add_argument("--timeout", type=float, default=2.0)
    clock_sample.set_defaults(func=_shadow_clock_sample)

    shadow_event = commands.add_parser("record-shadow-event")
    shadow_event.add_argument("--run-id", required=True)
    shadow_event.add_argument("--plan-id", required=True)
    shadow_event.add_argument("--kind", required=True)
    shadow_event.add_argument("--details-file", required=True)
    shadow_event.add_argument("--trace-store", required=True)
    shadow_event.set_defaults(func=_record_shadow_event)

    shadow_audit = commands.add_parser("audit-shadow-run")
    shadow_audit.add_argument("--schedule", required=True)
    shadow_audit.add_argument("--trace-store", required=True)
    shadow_audit.add_argument("--plan-id", required=True)
    shadow_audit.add_argument("--specification", default="config/phase4_trial_001.json")
    shadow_audit.add_argument("--output", required=True)
    shadow_audit.set_defaults(func=_audit_shadow_run)

    phase5 = commands.add_parser("phase5-complete")
    phase5.add_argument("--specification", default="config/phase5_trial_001.json")
    phase5.add_argument(
        "--evidence-contract", default="config/empirical_evidence_contract.json"
    )
    phase5.add_argument(
        "--capture-contract", default="config/vendor_capture_contract.json"
    )
    phase5.add_argument(
        "--campaign-contract", default="config/shadow_campaign_contract.json"
    )
    phase5.add_argument(
        "--schedule", default="tests/fixtures/phase5_release_schedule.json"
    )
    phase5.add_argument("--trace", default="tests/fixtures/phase5_trace_linked.json")
    phase5.add_argument(
        "--pre-payload", default="tests/fixtures/phase5_te_pre_release.json"
    )
    phase5.add_argument(
        "--post-payload", default="tests/fixtures/phase5_te_post_release.json"
    )
    phase5.add_argument("--output-dir", default="artifacts/phase5_complete")
    phase5.add_argument("--project-root", default=".")
    phase5.set_defaults(func=_phase5)

    verify5 = commands.add_parser("verify-phase5")
    verify5.add_argument("--output-dir", default="artifacts/phase5_complete")
    verify5.add_argument("--specification", default="config/phase5_trial_001.json")
    verify5.add_argument(
        "--evidence-contract", default="config/empirical_evidence_contract.json"
    )
    verify5.add_argument(
        "--capture-contract", default="config/vendor_capture_contract.json"
    )
    verify5.add_argument(
        "--campaign-contract", default="config/shadow_campaign_contract.json"
    )
    verify5.add_argument(
        "--schedule", default="tests/fixtures/phase5_release_schedule.json"
    )
    verify5.add_argument("--trace", default="tests/fixtures/phase5_trace_linked.json")
    verify5.add_argument(
        "--pre-payload", default="tests/fixtures/phase5_te_pre_release.json"
    )
    verify5.add_argument(
        "--post-payload", default="tests/fixtures/phase5_te_post_release.json"
    )
    verify5.add_argument("--trial-registry", default="config/trial_registry.csv")
    verify5.add_argument("--project-root", default=".")
    verify5.set_defaults(func=_verify_phase5)

    phase6 = commands.add_parser("phase6-complete")
    phase6.add_argument("--specification", default="config/phase6_trial_001.json")
    phase6.add_argument(
        "--roster-contract", default="config/campaign_roster_contract.json"
    )
    phase6.add_argument(
        "--roster", default="config/phase6_campaign_roster_001.json"
    )
    phase6.add_argument("--rights-attestation")
    phase6.add_argument("--output-dir", default="artifacts/phase6_complete")
    phase6.add_argument("--project-root", default=".")
    phase6.set_defaults(func=_phase6)

    verify6 = commands.add_parser("verify-phase6")
    verify6.add_argument("--output-dir", default="artifacts/phase6_complete")
    verify6.add_argument("--specification", default="config/phase6_trial_001.json")
    verify6.add_argument(
        "--roster-contract", default="config/campaign_roster_contract.json"
    )
    verify6.add_argument(
        "--roster", default="config/phase6_campaign_roster_001.json"
    )
    verify6.add_argument("--trial-registry", default="config/trial_registry.csv")
    verify6.add_argument("--project-root", default=".")
    verify6.set_defaults(func=_verify_phase6)

    roster_status = commands.add_parser("campaign-roster-status")
    roster_status.add_argument(
        "--roster", default="config/phase6_campaign_roster_001.json"
    )
    roster_status.add_argument(
        "--specification", default="config/phase6_trial_001.json"
    )
    roster_status.add_argument("--as-of")
    roster_status.add_argument("--rights-attestation")
    roster_status.add_argument("--output")
    roster_status.set_defaults(func=_campaign_roster_status)

    phase7 = commands.add_parser("phase7-complete")
    phase7.add_argument("--specification", default="config/phase7_trial_001.json")
    phase7.add_argument(
        "--handoff-contract", default="config/activation_handoff_contract.json"
    )
    phase7.add_argument(
        "--phase6-specification", default="config/phase6_trial_001.json"
    )
    phase7.add_argument(
        "--roster", default="config/phase6_campaign_roster_001.json"
    )
    phase7.add_argument(
        "--phase4-specification", default="config/phase4_trial_001.json"
    )
    phase7.add_argument(
        "--binding", default="tests/fixtures/phase7_component_binding.json"
    )
    phase7.add_argument("--output-dir", default="artifacts/phase7_complete")
    phase7.add_argument("--project-root", default=".")
    phase7.set_defaults(func=_phase7)

    verify7 = commands.add_parser("verify-phase7")
    verify7.add_argument("--output-dir", default="artifacts/phase7_complete")
    verify7.add_argument("--specification", default="config/phase7_trial_001.json")
    verify7.add_argument(
        "--handoff-contract", default="config/activation_handoff_contract.json"
    )
    verify7.add_argument(
        "--phase6-specification", default="config/phase6_trial_001.json"
    )
    verify7.add_argument(
        "--roster", default="config/phase6_campaign_roster_001.json"
    )
    verify7.add_argument(
        "--phase4-specification", default="config/phase4_trial_001.json"
    )
    verify7.add_argument(
        "--binding", default="tests/fixtures/phase7_component_binding.json"
    )
    verify7.add_argument("--trial-registry", default="config/trial_registry.csv")
    verify7.add_argument("--project-root", default=".")
    verify7.set_defaults(func=_verify_phase7)

    phase8 = commands.add_parser("phase8-complete")
    phase8.add_argument("--specification", default="config/phase8_trial_001.json")
    phase8.add_argument(
        "--authorization-contract", default="config/capture_authorization_contract.json"
    )
    phase8.add_argument(
        "--phase6-specification", default="config/phase6_trial_001.json"
    )
    phase8.add_argument(
        "--roster", default="config/phase6_campaign_roster_001.json"
    )
    phase8.add_argument(
        "--phase4-specification", default="config/phase4_trial_001.json"
    )
    phase8.add_argument(
        "--rights-schema", default="config/vendor_rights_attestation.schema.json"
    )
    phase8.add_argument(
        "--phase7-specification", default="config/phase7_trial_001.json"
    )
    phase8.add_argument("--output-dir", default="artifacts/phase8_complete")
    phase8.add_argument("--project-root", default=".")
    phase8.set_defaults(func=_phase8)

    verify8 = commands.add_parser("verify-phase8")
    verify8.add_argument("--output-dir", default="artifacts/phase8_complete")
    verify8.add_argument("--specification", default="config/phase8_trial_001.json")
    verify8.add_argument(
        "--authorization-contract", default="config/capture_authorization_contract.json"
    )
    verify8.add_argument(
        "--phase6-specification", default="config/phase6_trial_001.json"
    )
    verify8.add_argument(
        "--roster", default="config/phase6_campaign_roster_001.json"
    )
    verify8.add_argument(
        "--phase4-specification", default="config/phase4_trial_001.json"
    )
    verify8.add_argument(
        "--rights-schema", default="config/vendor_rights_attestation.schema.json"
    )
    verify8.add_argument(
        "--phase7-specification", default="config/phase7_trial_001.json"
    )
    verify8.add_argument("--trial-registry", default="config/trial_registry.csv")
    verify8.add_argument("--project-root", default=".")
    verify8.set_defaults(func=_verify_phase8)

    phase9 = commands.add_parser("phase9-complete")
    phase9.add_argument("--specification", default="config/phase9_trial_001.json")
    phase9.add_argument(
        "--phase8-specification", default="config/phase8_trial_001.json"
    )
    phase9.add_argument(
        "--roster", default="config/phase6_campaign_roster_001.json"
    )
    phase9.add_argument("--output-dir", default="artifacts/phase9_complete")
    phase9.add_argument("--project-root", default=".")
    phase9.set_defaults(func=_phase9)

    verify9 = commands.add_parser("verify-phase9")
    verify9.add_argument("--output-dir", default="artifacts/phase9_complete")
    verify9.add_argument("--specification", default="config/phase9_trial_001.json")
    verify9.add_argument(
        "--phase8-specification", default="config/phase8_trial_001.json"
    )
    verify9.add_argument(
        "--roster", default="config/phase6_campaign_roster_001.json"
    )
    verify9.add_argument("--trial-registry", default="config/trial_registry.csv")
    verify9.add_argument("--project-root", default=".")
    verify9.set_defaults(func=_verify_phase9)

    phase10 = commands.add_parser("phase10-complete")
    phase10.add_argument("--specification", default="config/phase10_trial_001.json")
    phase10.add_argument("--events", default="config/phase10_synthetic_events.csv")
    phase10.add_argument(
        "--phase9-specification", default="config/phase9_trial_001.json"
    )
    phase10.add_argument("--output-dir", default="artifacts/phase10_complete")
    phase10.add_argument("--project-root", default=".")
    phase10.set_defaults(func=_phase10)

    verify10 = commands.add_parser("verify-phase10")
    verify10.add_argument("--output-dir", default="artifacts/phase10_complete")
    verify10.add_argument("--specification", default="config/phase10_trial_001.json")
    verify10.add_argument("--events", default="config/phase10_synthetic_events.csv")
    verify10.add_argument(
        "--phase9-specification", default="config/phase9_trial_001.json"
    )
    verify10.add_argument("--trial-registry", default="config/trial_registry.csv")
    verify10.add_argument("--project-root", default=".")
    verify10.set_defaults(func=_verify_phase10)

    phase11 = commands.add_parser("phase11-complete")
    phase11.add_argument("--specification", default="config/phase11_trial_001.json")
    phase11.add_argument(
        "--phase10-specification", default="config/phase10_trial_001.json"
    )
    phase11.add_argument(
        "--labels", default="artifacts/phase10_complete/labeled_events.csv"
    )
    phase11.add_argument("--output-dir", default="artifacts/phase11_complete")
    phase11.add_argument("--project-root", default=".")
    phase11.set_defaults(func=_phase11)

    verify11 = commands.add_parser("verify-phase11")
    verify11.add_argument("--output-dir", default="artifacts/phase11_complete")
    verify11.add_argument("--specification", default="config/phase11_trial_001.json")
    verify11.add_argument(
        "--phase10-specification", default="config/phase10_trial_001.json"
    )
    verify11.add_argument(
        "--labels", default="artifacts/phase10_complete/labeled_events.csv"
    )
    verify11.add_argument("--trial-registry", default="config/trial_registry.csv")
    verify11.add_argument("--project-root", default=".")
    verify11.set_defaults(func=_verify_phase11)

    phase12 = commands.add_parser("phase12-complete")
    phase12.add_argument("--specification", default="config/phase12_trial_001.json")
    phase12.add_argument(
        "--phase11-specification", default="config/phase11_trial_001.json"
    )
    phase12.add_argument(
        "--labels", default="artifacts/phase10_complete/labeled_events.csv"
    )
    phase12.add_argument("--model", default="artifacts/phase11_complete/model.json")
    phase12.add_argument("--output-dir", default="artifacts/phase12_complete")
    phase12.add_argument("--project-root", default=".")
    phase12.set_defaults(func=_phase12)

    verify12 = commands.add_parser("verify-phase12")
    verify12.add_argument("--output-dir", default="artifacts/phase12_complete")
    verify12.add_argument("--specification", default="config/phase12_trial_001.json")
    verify12.add_argument(
        "--phase11-specification", default="config/phase11_trial_001.json"
    )
    verify12.add_argument(
        "--labels", default="artifacts/phase10_complete/labeled_events.csv"
    )
    verify12.add_argument("--model", default="artifacts/phase11_complete/model.json")
    verify12.add_argument("--trial-registry", default="config/trial_registry.csv")
    verify12.add_argument("--project-root", default=".")
    verify12.set_defaults(func=_verify_phase12)

    pit_labels = commands.add_parser("build-pit-labels")
    pit_labels.add_argument("--specification", required=True)
    pit_labels.add_argument("--features", required=True)
    pit_labels.add_argument("--quotes", required=True)
    pit_labels.add_argument("--evidence-ledger", required=True)
    pit_labels.add_argument("--output-dir", required=True)
    pit_labels.set_defaults(func=_build_pit_labels)

    registered_backtest = commands.add_parser("registered-backtest")
    registered_backtest.add_argument("--specification", required=True)
    registered_backtest.add_argument("--labels", required=True)
    registered_backtest.add_argument("--trial-registry", default="config/trial_registry.csv")
    registered_backtest.add_argument("--output-dir", required=True)
    registered_backtest.add_argument("--project-root", default=".")
    registered_backtest.set_defaults(func=_registered_backtest)

    forward_status = commands.add_parser("paper-forward-status")
    forward_status.add_argument("--journal", default="data/raw/paper_forward/events.jsonl")
    forward_status.set_defaults(func=_paper_forward_status)

    forward_signal = commands.add_parser("paper-forward-signal")
    forward_signal.add_argument("--journal", default="data/raw/paper_forward/events.jsonl")
    forward_signal.add_argument("--model", required=True)
    forward_signal.add_argument("--input", required=True)
    forward_signal.add_argument(
        "--evidence-ledger", default="data/raw/evidence_ledger"
    )
    forward_signal.add_argument("--clear-kill-switch", action="store_true")
    forward_signal.add_argument("--specification", default="config/phase12_trial_001.json")
    forward_signal.add_argument(
        "--phase11-specification", default="config/phase11_trial_001.json"
    )
    forward_signal.set_defaults(func=_paper_forward_signal)

    forward_settle = commands.add_parser("paper-forward-settle")
    forward_settle.add_argument("--journal", default="data/raw/paper_forward/events.jsonl")
    forward_settle.add_argument("--signal-id", required=True)
    forward_settle.add_argument("--exit-bid", required=True, type=float)
    forward_settle.add_argument("--exit-ask", required=True, type=float)
    forward_settle.add_argument("--provenance", default="licensed_shadow")
    forward_settle.set_defaults(func=_paper_forward_settle)

    authorize = commands.add_parser("authorize-campaign-access")
    authorize.add_argument("--source-event-id", required=True)
    authorize.add_argument("--rights-attestation", required=True)
    authorize.add_argument("--output", required=True)
    authorize.add_argument(
        "--roster", default="config/phase6_campaign_roster_001.json"
    )
    authorize.add_argument(
        "--phase6-specification", default="config/phase6_trial_001.json"
    )
    authorize.add_argument(
        "--phase8-specification", default="config/phase8_trial_001.json"
    )
    authorize.set_defaults(func=_authorize_campaign_access)

    permit = commands.add_parser("issue-capture-permit")
    permit.add_argument("--source-event-id", required=True)
    permit.add_argument("--access-receipt", required=True)
    permit.add_argument(
        "--action",
        choices=("binding_snapshot", "pre_release_snapshot", "calendar_stream"),
        required=True,
    )
    permit.add_argument("--output", required=True)
    permit.add_argument(
        "--roster", default="config/phase6_campaign_roster_001.json"
    )
    permit.add_argument(
        "--phase6-specification", default="config/phase6_trial_001.json"
    )
    permit.add_argument(
        "--phase8-specification", default="config/phase8_trial_001.json"
    )
    permit.set_defaults(func=_issue_capture_permit)

    access = commands.add_parser("vendor-access-preflight")
    access.add_argument("--rights-attestation")
    access.set_defaults(func=_vendor_preflight)

    evidence = commands.add_parser("audit-evidence-package")
    evidence.add_argument("--schedule", required=True)
    evidence.add_argument("--trace-store", required=True)
    evidence.add_argument("--capture-store", required=True)
    evidence.add_argument("--plan-id", required=True)
    evidence.add_argument("--rights-attestation")
    evidence.add_argument("--specification", default="config/phase5_trial_001.json")
    evidence.add_argument("--output", required=True)
    evidence.set_defaults(func=_audit_evidence)

    enroll = commands.add_parser("enroll-evidence-package")
    enroll.add_argument("--package", required=True)
    enroll.add_argument("--ledger", default="data/raw/evidence_ledger")
    enroll.set_defaults(func=_enroll_evidence)

    checkpoint = commands.add_parser("campaign-checkpoint")
    checkpoint.add_argument("--ledger", default="data/raw/evidence_ledger")
    checkpoint.add_argument("--specification", default="config/phase5_trial_001.json")
    checkpoint.add_argument("--output", required=True)
    checkpoint.set_defaults(func=_campaign_checkpoint)
    return root


def main() -> None:
    args = parser().parse_args()
    args.func(args)
