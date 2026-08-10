#!/usr/bin/env python3
"""Download the Phase-0 consensus calendar with an explicit provenance record."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

DATASET_PAGE = "https://huggingface.co/datasets/Ehsanrs2/Forex_Factory_Calendar"
DOWNLOAD_URL = (
    "https://huggingface.co/datasets/Ehsanrs2/Forex_Factory_Calendar/resolve/"
    "main/forex_factory_cache.csv?download=true"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/raw/calendar/forex_factory_cache.csv")
    parser.add_argument(
        "--acknowledge-research-only",
        action="store_true",
        help="Acknowledge that upstream redistribution rights were not verified.",
    )
    args = parser.parse_args()
    if not args.acknowledge_research_only:
        parser.error("--acknowledge-research-only is required; see docs/DATA_SOURCES.md")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".csv.part")
    subprocess.run(
        [
            "curl", "-sS", "-L", "--fail", "--retry", "5",
            "--retry-all-errors", DOWNLOAD_URL, "-o", str(temporary),
        ],
        check=True,
    )
    temporary.replace(output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    metadata = {
        "dataset_page": DATASET_PAGE,
        "download_url": DOWNLOAD_URL,
        "downloaded_at_utc": datetime.now(UTC).isoformat(),
        "bytes": output.stat().st_size,
        "sha256": digest,
        "use": "phase-0 research only; do not redistribute raw file",
    }
    output.with_suffix(".source.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
