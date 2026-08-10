from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")

CPI_FIELDS = {
    "CPI m/m": "cpi_mom",
    "Core CPI m/m": "core_cpi_mom",
}
NFP_FIELDS = {
    "Non-Farm Employment Change": "nfp_change",
    "Unemployment Rate": "unemployment_rate",
    "Average Hourly Earnings m/m": "average_hourly_earnings_mom",
}

OUTPUT_FIELDS = [
    "event_id",
    "event_type",
    "release_date_et",
    "release_timestamp_utc",
    "reference_period",
    "cpi_mom_actual_pct",
    "cpi_mom_forecast_pct",
    "cpi_mom_previous_pct",
    "core_cpi_mom_actual_pct",
    "core_cpi_mom_forecast_pct",
    "core_cpi_mom_previous_pct",
    "nfp_change_actual_k",
    "nfp_change_forecast_k",
    "nfp_change_previous_k",
    "unemployment_rate_actual_pct",
    "unemployment_rate_forecast_pct",
    "unemployment_rate_previous_pct",
    "average_hourly_earnings_mom_actual_pct",
    "average_hourly_earnings_mom_forecast_pct",
    "average_hourly_earnings_mom_previous_pct",
    "quality_flags",
    "schedule_source_url",
    "consensus_source_url",
]


def parse_number(value: str) -> float | None:
    text = (value or "").strip().replace(",", "")
    if not text or text in {"-", "N/A", "na", "n/a"}:
        return None
    multiplier = 1.0
    if text.endswith("%"):
        text = text[:-1]
    elif text[-1:].upper() in {"K", "M", "B"}:
        suffix = text[-1].upper()
        text = text[:-1]
        multiplier = {"K": 1.0, "M": 1_000.0, "B": 1_000_000.0}[suffix]
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def _load_calendar_rows(path: Path) -> dict[tuple[str, str], list[dict[str, str]]]:
    indexed: dict[tuple[str, str], list[dict[str, str]]] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row.get("Currency") != "USD":
                continue
            raw_dt = row.get("DateTime", "")
            try:
                day = datetime.fromisoformat(raw_dt).date().isoformat()
            except ValueError:
                continue
            indexed.setdefault((day, row.get("Event", "")), []).append(row)
    return indexed


def _put_component(output: dict[str, str], prefix: str, row: dict[str, str]) -> None:
    for source_name, target_name in (
        ("Actual", "actual"),
        ("Forecast", "forecast"),
        ("Previous", "previous"),
    ):
        value = parse_number(row.get(source_name, ""))
        output[f"{prefix}_{target_name}_{'k' if prefix == 'nfp_change' else 'pct'}"] = (
            "" if value is None else f"{value:g}"
        )


def normalize_calendar(
    raw_calendar_path: Path,
    schedule_path: Path,
    output_path: Path,
    *,
    consensus_source_url: str,
) -> dict[str, int]:
    """Join third-party consensus values to authoritative BLS release times.

    The public calendar's dates are used for matching, but its intraday timestamps
    are deliberately ignored because inspection found corrupted/misaligned times.
    """
    indexed = _load_calendar_rows(raw_calendar_path)
    outputs: list[dict[str, str]] = []
    missing_primary = duplicates = 0
    with schedule_path.open(newline="", encoding="utf-8") as handle:
        schedules = list(csv.DictReader(handle))

    for schedule in schedules:
        day = schedule["release_date_et"]
        event_type = schedule["event_type"]
        local = datetime.fromisoformat(f"{day}T{schedule['release_time_et']}:00").replace(
            tzinfo=NEW_YORK
        )
        utc_time = local.astimezone(UTC)
        output = {field: "" for field in OUTPUT_FIELDS}
        output.update(
            {
                "event_id": f"{day}_{event_type.lower()}",
                "event_type": event_type,
                "release_date_et": day,
                "release_timestamp_utc": utc_time.isoformat(),
                "reference_period": schedule["reference_period"],
                "schedule_source_url": schedule["source_url"],
                "consensus_source_url": consensus_source_url,
            }
        )
        flags = ["calendar_intraday_time_ignored", "bls_schedule_time_applied"]
        components = CPI_FIELDS if event_type == "CPI" else NFP_FIELDS
        for event_name, prefix in components.items():
            matches = indexed.get((day, event_name), [])
            if len(matches) > 1:
                duplicates += 1
                flags.append(f"duplicate:{event_name}")
            if matches:
                _put_component(output, prefix, matches[0])
            else:
                flags.append(f"missing:{event_name}")
        primary = "cpi_mom_actual_pct" if event_type == "CPI" else "nfp_change_actual_k"
        forecast = (
            "cpi_mom_forecast_pct" if event_type == "CPI" else "nfp_change_forecast_k"
        )
        if not output[primary] or not output[forecast]:
            missing_primary += 1
            flags.append("missing_primary_actual_or_forecast")
        output["quality_flags"] = "|".join(flags)
        outputs.append(output)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output_path.with_suffix(output_path.suffix + ".part")
    with temporary_output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(outputs)
    temporary_output.replace(output_path)
    return {
        "events": len(outputs),
        "missing_primary": missing_primary,
        "duplicate_components": duplicates,
    }


def load_event_times(path: Path) -> list[datetime]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [
            datetime.fromisoformat(row["release_timestamp_utc"]).astimezone(UTC)
            for row in csv.DictReader(handle)
        ]
