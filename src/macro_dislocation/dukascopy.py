from __future__ import annotations

import csv
import lzma
import struct
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable, Iterator

from .models import Quote

RECORD = struct.Struct(">3i2f")
BASE_URL = "https://datafeed.dukascopy.com/datafeed"


def hour_url(instrument: str, hour_utc: datetime) -> str:
    hour_utc = require_utc(hour_utc)
    return (
        f"{BASE_URL}/{instrument.upper()}/{hour_utc.year:04d}/"
        f"{hour_utc.month - 1:02d}/{hour_utc.day:02d}/{hour_utc.hour:02d}h_ticks.bi5"
    )


def require_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def decode_bi5(payload: bytes, hour_utc: datetime, price_scale: int) -> Iterator[Quote]:
    """Decode one Dukascopy hourly tick payload.

    Records are big-endian: millisecond offset, ask integer, bid integer,
    ask volume, bid volume. The price scale is instrument-specific; USDJPY is
    1,000.
    """
    hour_utc = require_utc(hour_utc).replace(minute=0, second=0, microsecond=0)
    if price_scale <= 0:
        raise ValueError("price_scale must be positive")
    raw = lzma.decompress(payload)
    if len(raw) % RECORD.size:
        raise ValueError(f"invalid BI5 payload length: {len(raw)}")
    for millis, ask_raw, bid_raw, ask_volume, bid_volume in RECORD.iter_unpack(raw):
        ask = ask_raw / price_scale
        bid = bid_raw / price_scale
        if millis < 0 or millis >= 3_600_000:
            raise ValueError(f"invalid millisecond offset: {millis}")
        if bid <= 0 or ask <= 0 or bid > ask:
            continue
        yield Quote(
            timestamp_utc=hour_utc + timedelta(milliseconds=millis),
            bid=bid,
            ask=ask,
            bid_volume=float(bid_volume),
            ask_volume=float(ask_volume),
        )


def fetch_hour(
    instrument: str,
    hour_utc: datetime,
    cache_dir: Path,
    *,
    retries: int = 7,
    timeout: float = 30.0,
) -> Path | None:
    """Fetch an hourly BI5 file, returning None for a confirmed 404."""
    hour_utc = require_utc(hour_utc).replace(minute=0, second=0, microsecond=0)
    target = cache_dir / instrument.upper() / f"{hour_utc:%Y/%m/%d/%H}.bi5"
    if target.exists() and target.stat().st_size > 0:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        hour_url(instrument, hour_utc),
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 Safari/537.36 macro-dislocation-lab/0.1"
            )
        },
    )
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read()
            if not payload:
                return None
            temporary = target.with_suffix(".bi5.part")
            temporary.write_bytes(payload)
            temporary.replace(target)
            return target
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            last_error = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
        if attempt + 1 < retries:
            # Public endpoints occasionally throttle bursts with 429/503.
            time.sleep(min(12.0, 1.0 * (2**attempt)))
    raise RuntimeError(f"failed to fetch {request.full_url}: {last_error}")


def event_hours(event_times: Iterable[datetime], window_hours: int = 1) -> list[datetime]:
    hours: set[datetime] = set()
    for event_time in event_times:
        base = require_utc(event_time).replace(minute=0, second=0, microsecond=0)
        for offset in range(-window_hours, window_hours + 1):
            hours.add(base + timedelta(hours=offset))
    return sorted(hours)


def write_quote_csv(
    hours: Iterable[datetime],
    output_path: Path,
    cache_dir: Path,
    *,
    instrument: str = "USDJPY",
    price_scale: int = 1_000,
) -> dict[str, int]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    downloaded = missing = rows = 0
    temporary_output = output_path.with_suffix(output_path.suffix + ".part")
    with temporary_output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["timestamp_utc", "bid", "ask", "bid_volume", "ask_volume", "source"]
        )
        for hour in sorted(set(hours)):
            path = fetch_hour(instrument, hour, cache_dir)
            if path is None:
                missing += 1
                continue
            downloaded += 1
            for quote in decode_bi5(path.read_bytes(), hour, price_scale):
                writer.writerow(
                    [
                        quote.timestamp_utc.isoformat(timespec="milliseconds"),
                        f"{quote.bid:.6f}",
                        f"{quote.ask:.6f}",
                        f"{quote.bid_volume:.6f}",
                        f"{quote.ask_volume:.6f}",
                        "dukascopy_public_datafeed",
                    ]
                )
                rows += 1
            # Keep sequential bootstrap runs deliberately paced. The curl helper
            # offers bounded concurrency for the initial bulk acquisition.
            time.sleep(0.15)
    temporary_output.replace(output_path)
    return {"hours": downloaded, "missing_hours": missing, "quotes": rows}
