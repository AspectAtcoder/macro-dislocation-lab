from __future__ import annotations

import argparse
import json
from pathlib import Path

from .calendar_data import load_event_times, normalize_calendar
from .baseline import run_baseline
from .dukascopy import event_hours, write_quote_csv
from .experiment import run_experiment
from .phase0 import run_phase0

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
    return root


def main() -> None:
    args = parser().parse_args()
    args.func(args)
