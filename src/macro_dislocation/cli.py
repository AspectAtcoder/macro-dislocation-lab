from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .calendar_data import load_event_times, normalize_calendar
from .baseline import run_baseline
from .dukascopy import event_hours, write_quote_csv
from .experiment import run_experiment
from .phase0 import run_phase0
from .phase1 import run_phase1
from .phase2 import run_phase2
from .phase3 import run_phase3
from .phase4 import run_phase4
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
    te_snapshot.add_argument("--rights-attestation", required=True)
    te_snapshot.add_argument("--store", default="data/raw/vendor_capture_store")
    te_snapshot.add_argument("--country", default="united states")
    te_snapshot.add_argument("--indicator", action="append", required=True)
    te_snapshot.add_argument("--start", required=True)
    te_snapshot.add_argument("--end", required=True)
    te_snapshot.add_argument("--timeout", type=float, default=30.0)
    te_snapshot.set_defaults(func=_capture_te_snapshot)

    te_stream = commands.add_parser("capture-te-stream-jsonl")
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
    return root


def main() -> None:
    args = parser().parse_args()
    args.func(args)
