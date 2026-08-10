from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .event_extractor import (
    extract_eia_features,
    extract_fomc_features,
    feature_hash,
    load_axis_config,
    write_csv,
)
from .news_sources import acquire_official_documents
from .news_store import NewsStore, utc_now


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _report(summary: dict[str, Any], source_availability: dict[str, Any]) -> str:
    counts = summary["counts"]
    timing = summary["timing_audit"]
    checks = summary["pipeline_checks"]
    check_lines = "\n".join(
        f"- {'PASS' if value else 'FAIL'}: `{name}`" for name, value in checks.items()
    )
    return f"""# Phase 1 result

Phase 1の取得・保存・低次元抽出パイプラインは
**{summary['pipeline_status']}** です。これは価格予測のGo判定ではありません。
Phase 0の数値モデルは引き続きNo-Goです。

## 実取得結果

- Federal Reserve FOMC statements: {counts['by_source'].get('federal_reserve', 0)}件
- EIA WPSR table 1: {counts['by_source'].get('eia', 0)}件
- 合計document vintage: {counts['documents']}件
- fetch observation: {counts['observations']}件
- Fedの公開時刻（公式ページ明記）: {timing['official_exact_publication_time']}件
- EIAの公開時刻（公式日付＋通常スケジュールから推定）: {timing['schedule_inferred_publication_time']}件

履歴ページを今取得した時刻は、当時の配信到着時刻ではありません。したがって
`first_seen_at` / `received_at` は今回のアーカイブ取得を表し、履歴レイテンシの
教師には使えません。EIAの祝日週を含む正確な時刻はベンダーのpoint-in-time履歴で
補完が必要です。

## 抽出結果

FOMC声明は直前声明との差分を、事前固定した6軸へ写像しました。学習パラメータは
ゼロで、出力には追加・削除文を残しています。EIAは文章モデルを使わず、公式CSV
から商業原油、SPR、ガソリン、留出油の週次在庫変化を直接抽出しました。

- FOMC feature rows: {summary['feature_counts']['fomc']}件
- EIA feature rows: {summary['feature_counts']['eia']}件
- text dimensions: {summary['text_dimensions']}
- replay hash: `{summary['feature_hash']}`
- replay identical: {summary['replay_identical']}

これらは候補特徴量であり、因果寄与・ニュースの真の意味・売買シグナルではありません。

## Gate

{check_lines}

テスト数を含む最終完了判定は `macro-lab verify-phase1` が行います。

## ニュース経路の残課題

- Fed/EIA公式アーカイブ: 実取得済み。ただし高速ヘッドライン用途ではない。
- BLS/OPEC: この環境からHTTP 403。アクセス制限を回避するスクレイピングはしない。
- Trading Economics/LSEG/Bloomberg: 未契約。実データも保持権も未確認のため未取得。
- CPI/NFPのconsensus、改定のpoint-in-time履歴、実配信到着時刻は未充足。

従って次の合理的な判定は、全検証が通った場合でも
`PASS_PIPELINE_ONLY`です。価格モデルを再試行する前に、限定的なベンダー試用と
別の事前登録が必要です。
"""


def run_phase1(
    specification_path: Path,
    axes_path: Path,
    news_sources_path: Path,
    store_path: Path,
    output_dir: Path,
    *,
    workers: int = 8,
) -> dict[str, Any]:
    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    axis_config = load_axis_config(axes_path)
    store = NewsStore(store_path)
    documents, acquisition = acquire_official_documents(
        fed_years=specification["scope"]["federal_reserve"]["years"],
        eia_years=specification["scope"]["eia"]["years"],
        workers=workers,
    )
    ingest_results = [store.ingest(document) for document in documents]

    before_duplicate = store.counts()
    duplicate_result = store.ingest(replace(documents[0], received_at=utc_now()))
    after_duplicate = store.counts()
    duplicate_probe = {
        "document_id": duplicate_result.document_id,
        "inserted_document": duplicate_result.inserted_document,
        "documents_before": before_duplicate["documents"],
        "documents_after": after_duplicate["documents"],
        "observations_before": before_duplicate["observations"],
        "observations_after": after_duplicate["observations"],
        "passed": (
            not duplicate_result.inserted_document
            and before_duplicate["documents"] == after_duplicate["documents"]
            and after_duplicate["observations"] == before_duplicate["observations"] + 1
        ),
    }

    records = store.documents()
    fomc_features = extract_fomc_features(records, store.read_content, axis_config)
    eia_features = extract_eia_features(records, store.read_content)
    first_hash = feature_hash(fomc_features, eia_features)
    replay_fomc = extract_fomc_features(records, store.read_content, axis_config)
    replay_eia = extract_eia_features(records, store.read_content)
    replay_hash = feature_hash(replay_fomc, replay_eia)
    replay_identical = first_hash == replay_hash

    ready_at = utc_now()
    store.mark_feature_ready((record["document_id"] for record in records), ready_at)
    records = store.documents()
    validation = store.validate()
    counts = store.counts()
    text_dimensions = len(axis_config["axes"])
    exact_count = sum(
        record["timestamp_basis"] == "official_page_release_time" for record in records
    )
    inferred_count = sum("inferred" in record["timestamp_basis"] for record in records)
    timing_audit = {
        "scheduled_at_present": sum(record["scheduled_at"] is not None for record in records),
        "published_at_present": sum(record["published_at"] is not None for record in records),
        "first_seen_at_present": sum(record["first_seen_at"] is not None for record in records),
        "received_at_present": sum(record["received_at"] is not None for record in records),
        "feature_ready_at_present": sum(record["feature_ready_at"] is not None for record in records),
        "official_exact_publication_time": exact_count,
        "schedule_inferred_publication_time": inferred_count,
        "historical_real_time_arrival_recovered": 0,
    }

    gates = specification["completion_gates"]
    pipeline_checks = {
        "minimum_source_families": len(counts["by_source"])
        >= gates["minimum_source_families"],
        "minimum_total_documents": counts["documents"]
        >= gates["minimum_total_documents"],
        "minimum_fed_documents": counts["by_source"].get("federal_reserve", 0)
        >= gates["minimum_fed_documents"],
        "minimum_eia_documents": counts["by_source"].get("eia", 0)
        >= gates["minimum_eia_documents"],
        "raw_hashes_valid": validation["valid"],
        "duplicate_refetch_creates_no_document_version": duplicate_probe["passed"],
        "replay_feature_hash_identical": replay_identical,
        "maximum_text_dimensions": text_dimensions <= gates["maximum_text_dimensions"],
        "price_prediction_not_executed": gates["price_prediction_executed"] is False,
    }
    pipeline_status = (
        "PASS_PIPELINE_PENDING_TEST_VERIFICATION"
        if all(pipeline_checks.values())
        else "FAIL_PIPELINE"
    )
    source_availability = {
        "checked_at": utc_now(),
        "acquired": {
            "federal_reserve": {
                "status": "success",
                "documents": counts["by_source"].get("federal_reserve", 0),
                "role": "authoritative FOMC statement text; archive is not a low-latency feed",
            },
            "eia": {
                "status": "success",
                "documents": counts["by_source"].get("eia", 0),
                "role": "authoritative WPSR components; archive is not a consensus feed",
            },
        },
        "unavailable_in_this_run": {
            "bls": "HTTP 403 from this execution environment; no bypass attempted",
            "opec": "HTTP 403 from this execution environment; no bypass attempted",
            "trading_economics": "not contracted; no point-in-time consensus data acquired",
            "lseg": "not contracted; no content or retention rights",
            "bloomberg": "not contracted; no content or retention rights",
        },
        "catalog": json.loads(news_sources_path.read_text(encoding="utf-8")),
    }
    summary = {
        "trial_id": specification["trial_id"],
        "phase1_status": "PIPELINE_EXECUTED",
        "pipeline_status": pipeline_status,
        "decision_if_verified": (
            "PASS_PIPELINE_ONLY" if pipeline_status.startswith("PASS") else "FAIL_PIPELINE"
        ),
        "price_prediction_executed": False,
        "neural_network_fitted": False,
        "acquisition": acquisition,
        "ingest": {
            "attempted": len(ingest_results),
            "new_documents": sum(item.inserted_document for item in ingest_results),
        },
        "counts": counts,
        "feature_counts": {"fomc": len(fomc_features), "eia": len(eia_features)},
        "text_dimensions": text_dimensions,
        "feature_hash": first_hash,
        "replay_hash": replay_hash,
        "replay_identical": replay_identical,
        "duplicate_probe": duplicate_probe,
        "timing_audit": timing_audit,
        "store_validation": validation,
        "pipeline_checks": pipeline_checks,
        "limitations": [
            "archive first_seen_at is not historical live arrival time",
            "EIA publication time is schedule-inferred rather than recovered from a point-in-time feed",
            "consensus and news-vendor history remain unavailable without a licensed contract",
            "features have not been tested against prices",
        ],
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "fomc_features.csv", fomc_features)
    write_csv(output_dir / "eia_features.csv", eia_features)
    store.export_json(output_dir / "documents.json")
    _write_json(output_dir / "source_availability.json", source_availability)
    _write_json(output_dir / "phase1_summary.json", summary)
    manifest = {
        "inputs": {
            str(specification_path): _sha256(specification_path),
            str(axes_path): _sha256(axes_path),
            str(news_sources_path): _sha256(news_sources_path),
        },
        "store": str(store_path),
        "database": str(store.db_path),
        "feature_hash": first_hash,
        "document_content_hashes": {
            record["document_id"]: record["content_sha256"] for record in records
        },
    }
    _write_json(output_dir / "manifest.json", manifest)
    (output_dir / "PHASE1_REPORT.md").write_text(
        _report(summary, source_availability), encoding="utf-8"
    )
    return summary
