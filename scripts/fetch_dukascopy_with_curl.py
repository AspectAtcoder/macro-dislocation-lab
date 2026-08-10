#!/usr/bin/env python3
"""Bootstrap cached Dukascopy files using curl with bounded concurrency.

urllib is kept in the library for portability. This helper exists because some
TLS/CDN paths throttle Python's urllib disproportionately while accepting curl.
"""

from __future__ import annotations

import argparse
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from macro_dislocation.calendar_data import load_event_times
from macro_dislocation.dukascopy import event_hours, hour_url


def fetch(hour, cache: Path, instrument: str) -> tuple[str, str]:
    target = cache / instrument / f"{hour:%Y/%m/%d/%H}.bi5"
    if target.exists() and target.stat().st_size:
        return hour.isoformat(), "cached"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".bi5.part")
    command = [
        "curl",
        "-sS",
        "-L",
        "--fail",
        "--retry",
        "5",
        "--retry-all-errors",
        "--retry-delay",
        "2",
        hour_url(instrument, hour),
        "-o",
        str(temporary),
    ]
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0 or not temporary.exists() or not temporary.stat().st_size:
        temporary.unlink(missing_ok=True)
        return hour.isoformat(), f"failed:{completed.returncode}"
    temporary.replace(target)
    return hour.isoformat(), "downloaded"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", default="data/processed/events_2024.csv")
    parser.add_argument("--cache", default="data/raw/dukascopy")
    parser.add_argument("--instrument", default="USDJPY")
    parser.add_argument("--window-hours", type=int, default=1)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    hours = event_hours(load_event_times(Path(args.events)), args.window_hours)
    counts: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [
            pool.submit(fetch, hour, Path(args.cache), args.instrument) for hour in hours
        ]
        for future in as_completed(futures):
            hour, status = future.result()
            counts[status] = counts.get(status, 0) + 1
            print(f"{hour} {status}", flush=True)
    print(f"summary={counts}")
    if any(key.startswith("failed") for key in counts):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
