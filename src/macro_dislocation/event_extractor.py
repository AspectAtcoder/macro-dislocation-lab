from __future__ import annotations

import csv
import difflib
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any, Callable


WORD_RE = re.compile(r"[a-z]+(?:'[a-z]+)?")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def load_axis_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _count_weighted_terms(text: str, terms: dict[str, float]) -> float:
    normalized = " ".join(WORD_RE.findall(text.lower()))
    occupied = [False] * len(normalized)
    score = 0.0
    for term, weight in sorted(terms.items(), key=lambda item: len(item[0]), reverse=True):
        needle = " ".join(WORD_RE.findall(term.lower()))
        if not needle:
            continue
        pattern = re.compile(rf"(?<![a-z]){re.escape(needle)}(?![a-z])")
        for match in pattern.finditer(normalized):
            if not any(occupied[match.start() : match.end()]):
                score += float(weight)
                occupied[match.start() : match.end()] = [True] * (match.end() - match.start())
    return score


def score_text(text: str, axes: dict[str, Any]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for axis, lexicon in axes.items():
        positive = _count_weighted_terms(text, lexicon.get("positive", {}))
        negative = _count_weighted_terms(text, lexicon.get("negative", {}))
        scores[axis] = round(positive - negative, 6)
    return scores


def _sentence_diff(previous: str, current: str) -> tuple[str, str, float]:
    old = [item.strip() for item in SENTENCE_RE.split(previous) if item.strip()]
    new = [item.strip() for item in SENTENCE_RE.split(current) if item.strip()]
    matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    removed: list[str] = []
    added: list[str] = []
    equal = 0
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag == "equal":
            equal += old_end - old_start
        if tag in {"delete", "replace"}:
            removed.extend(old[old_start:old_end])
        if tag in {"insert", "replace"}:
            added.extend(new[new_start:new_end])
    denominator = max(len(old), len(new), 1)
    novelty = round(1.0 - equal / denominator, 6)
    return " ".join(added)[:1000], " ".join(removed)[:1000], novelty


def extract_fomc_features(
    records: list[dict[str, Any]],
    read_content: Callable[[dict[str, Any]], bytes],
    axis_config: dict[str, Any],
) -> list[dict[str, Any]]:
    axes = axis_config["axes"]
    statements = sorted(
        (record for record in records if record["document_type"] == "fomc_statement"),
        key=lambda item: (item["published_at"], item["version"]),
    )
    features: list[dict[str, Any]] = []
    previous_text: str | None = None
    previous_id: str | None = None
    for record in statements:
        current_text = read_content(record).decode("utf-8", errors="replace")
        current_scores = score_text(current_text, axes)
        if previous_text is None:
            previous_scores = {name: 0.0 for name in axes}
            deltas = {name: 0.0 for name in axes}
            added = removed = ""
            novelty = 0.0
        else:
            previous_scores = score_text(previous_text, axes)
            deltas = {
                name: round(current_scores[name] - previous_scores[name], 6)
                for name in axes
            }
            added, removed, novelty = _sentence_diff(previous_text, current_text)
        row: dict[str, Any] = {
            "document_id": record["document_id"],
            "source_event_id": record["source_event_id"],
            "published_at": record["published_at"],
            "previous_document_id": previous_id or "",
            "novelty": novelty,
            "added_text": added,
            "removed_text": removed,
        }
        row.update({f"axis_{name}": value for name, value in deltas.items()})
        row.update({f"level_{name}": value for name, value in current_scores.items()})
        features.append(row)
        previous_text = current_text
        previous_id = record["document_id"]
    return features


def _number(value: str) -> float:
    cleaned = value.replace(",", "").strip()
    return float(cleaned) if cleaned else float("nan")


def extract_eia_features(
    records: list[dict[str, Any]],
    read_content: Callable[[dict[str, Any]], bytes],
) -> list[dict[str, Any]]:
    targets = {
        "Commercial (Excluding SPR)": "commercial_crude_inventory_change_mmbbl",
        "Strategic Petroleum Reserve (SPR)": "spr_inventory_change_mmbbl",
        "Total Motor Gasoline": "gasoline_inventory_change_mmbbl",
        "Distillate Fuel Oil": "distillate_inventory_change_mmbbl",
    }
    output: list[dict[str, Any]] = []
    for record in sorted(
        (item for item in records if item["document_type"] == "wpsr_table1_csv"),
        key=lambda item: (item["published_at"], item["version"]),
    ):
        decoded = read_content(record).decode("utf-8-sig", errors="replace")
        rows = list(csv.reader(io.StringIO(decoded)))
        if not rows:
            raise ValueError(f"empty EIA CSV: {record['source_event_id']}")
        values: dict[str, float] = {}
        for row in rows[1:]:
            if row and row[0] == "STUB_1":
                break
            if len(row) >= 4 and row[0] in targets:
                values[targets[row[0]]] = _number(row[3])
        missing = sorted(set(targets.values()) - set(values))
        if missing:
            raise ValueError(
                f"missing EIA fields for {record['source_event_id']}: {missing}"
            )
        output.append(
            {
                "document_id": record["document_id"],
                "source_event_id": record["source_event_id"],
                "published_at": record["published_at"],
                "data_week_ending": rows[0][1],
                **values,
            }
        )
    return output


def feature_hash(
    fomc_features: list[dict[str, Any]], eia_features: list[dict[str, Any]]
) -> str:
    encoded = json.dumps(
        {"fomc": fomc_features, "eia": eia_features},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
