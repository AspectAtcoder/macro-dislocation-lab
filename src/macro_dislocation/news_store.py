from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import sqlite3
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class SourceDocument:
    source: str
    source_event_id: str
    document_type: str
    title: str
    canonical_url: str
    raw_bytes: bytes
    canonical_content: bytes
    scheduled_at: str | None
    published_at: str | None
    timestamp_basis: str
    content_type: str
    license_class: str
    received_at: str = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IngestResult:
    document_id: str
    version: int
    inserted_document: bool
    content_sha256: str
    raw_sha256: str


class NewsStore:
    """Content-addressed release store with immutable document vintages."""

    def __init__(self, root: Path):
        self.root = root
        self.db_path = root / "manifest.sqlite3"
        self.raw_root = root / "raw"
        self.content_root = root / "content"
        self.root.mkdir(parents=True, exist_ok=True)
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.content_root.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    source_event_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    document_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    canonical_url TEXT NOT NULL,
                    scheduled_at TEXT,
                    published_at TEXT,
                    first_seen_at TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    feature_ready_at TEXT,
                    timestamp_basis TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    content_path TEXT NOT NULL,
                    raw_sha256 TEXT NOT NULL,
                    raw_path TEXT NOT NULL,
                    license_class TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    UNIQUE(source, source_event_id, content_sha256),
                    UNIQUE(source, source_event_id, version)
                );
                CREATE TABLE IF NOT EXISTS observations (
                    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL REFERENCES documents(document_id),
                    observed_at TEXT NOT NULL,
                    raw_sha256 TEXT NOT NULL,
                    raw_path TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_documents_source_event
                    ON documents(source, source_event_id);
                """
            )
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )

    @staticmethod
    def _extension(content_type: str) -> str:
        base_type = content_type.split(";", 1)[0].strip().lower()
        explicit = {
            "text/html": ".html",
            "text/csv": ".csv",
            "application/rss+xml": ".xml",
            "text/xml": ".xml",
            "application/json": ".json",
        }
        return explicit.get(base_type) or mimetypes.guess_extension(base_type) or ".bin"

    def _write_blob(self, root: Path, digest: str, data: bytes, suffix: str) -> Path:
        relative = Path(root.name) / digest[:2] / f"{digest}{suffix}"
        destination = self.root / relative
        if destination.exists():
            if sha256_bytes(destination.read_bytes()) != digest:
                raise ValueError(f"existing blob hash mismatch: {destination}")
            return relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{digest}.", dir=destination.parent
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, destination)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        return relative

    def ingest(self, document: SourceDocument) -> IngestResult:
        content_digest = sha256_bytes(document.canonical_content)
        raw_digest = sha256_bytes(document.raw_bytes)
        suffix = self._extension(document.content_type)
        raw_path = self._write_blob(self.raw_root, raw_digest, document.raw_bytes, suffix)
        content_path = self._write_blob(
            self.content_root, content_digest, document.canonical_content, suffix
        )
        identity = "\0".join(
            (document.source, document.source_event_id, content_digest)
        ).encode("utf-8")
        document_id = hashlib.sha256(identity).hexdigest()

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT document_id, version FROM documents
                WHERE source = ? AND source_event_id = ? AND content_sha256 = ?
                """,
                (document.source, document.source_event_id, content_digest),
            ).fetchone()
            inserted = existing is None
            if inserted:
                version_row = connection.execute(
                    """
                    SELECT COALESCE(MAX(version), 0) + 1 AS next_version
                    FROM documents WHERE source = ? AND source_event_id = ?
                    """,
                    (document.source, document.source_event_id),
                ).fetchone()
                version = int(version_row["next_version"])
                connection.execute(
                    """
                    INSERT INTO documents(
                        document_id, source, source_event_id, version, document_type,
                        title, canonical_url, scheduled_at, published_at, first_seen_at,
                        received_at, feature_ready_at, timestamp_basis, content_type,
                        content_sha256, content_path, raw_sha256, raw_path,
                        license_class, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        document.source,
                        document.source_event_id,
                        version,
                        document.document_type,
                        document.title,
                        document.canonical_url,
                        document.scheduled_at,
                        document.published_at,
                        document.received_at,
                        document.received_at,
                        document.timestamp_basis,
                        document.content_type,
                        content_digest,
                        str(content_path),
                        raw_digest,
                        str(raw_path),
                        document.license_class,
                        json.dumps(document.metadata, ensure_ascii=False, sort_keys=True),
                    ),
                )
            else:
                document_id = str(existing["document_id"])
                version = int(existing["version"])
            connection.execute(
                """
                INSERT INTO observations(document_id, observed_at, raw_sha256, raw_path)
                VALUES (?, ?, ?, ?)
                """,
                (document_id, document.received_at, raw_digest, str(raw_path)),
            )
        return IngestResult(
            document_id=document_id,
            version=version,
            inserted_document=inserted,
            content_sha256=content_digest,
            raw_sha256=raw_digest,
        )

    def mark_feature_ready(self, document_ids: Iterable[str], ready_at: str) -> None:
        with self._connect() as connection:
            connection.executemany(
                """
                UPDATE documents
                SET feature_ready_at = COALESCE(feature_ready_at, ?)
                WHERE document_id = ?
                """,
                ((ready_at, identifier) for identifier in document_ids),
            )

    def documents(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM documents
                ORDER BY COALESCE(published_at, scheduled_at, first_seen_at),
                         source, source_event_id, version
                """
            ).fetchall()
        documents: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json"))
            documents.append(item)
        return documents

    def read_content(self, record: dict[str, Any]) -> bytes:
        return (self.root / record["content_path"]).read_bytes()

    def counts(self) -> dict[str, Any]:
        with self._connect() as connection:
            document_count = int(
                connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            )
            observation_count = int(
                connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
            )
            by_source = {
                str(row[0]): int(row[1])
                for row in connection.execute(
                    "SELECT source, COUNT(*) FROM documents GROUP BY source ORDER BY source"
                )
            }
        return {
            "documents": document_count,
            "observations": observation_count,
            "by_source": by_source,
        }

    def validate(self) -> dict[str, Any]:
        failures: list[str] = []
        records = self.documents()
        required = {
            "source",
            "source_event_id",
            "version",
            "document_type",
            "title",
            "canonical_url",
            "first_seen_at",
            "received_at",
            "timestamp_basis",
            "content_type",
            "content_sha256",
            "raw_path",
            "license_class",
        }
        for record in records:
            missing = [name for name in required if record.get(name) in (None, "")]
            if missing:
                failures.append(f"{record['document_id']}: missing {','.join(missing)}")
            content_path = self.root / record["content_path"]
            raw_path = self.root / record["raw_path"]
            if not content_path.is_file() or sha256_bytes(content_path.read_bytes()) != record["content_sha256"]:
                failures.append(f"{record['document_id']}: content hash mismatch")
            if not raw_path.is_file() or sha256_bytes(raw_path.read_bytes()) != record["raw_sha256"]:
                failures.append(f"{record['document_id']}: raw hash mismatch")
        return {
            "valid": not failures,
            "failures": failures,
            "documents_checked": len(records),
            "counts": self.counts(),
        }

    def export_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.documents(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def document_asdict(document: SourceDocument) -> dict[str, Any]:
    value = asdict(document)
    value["raw_bytes"] = f"<{len(document.raw_bytes)} bytes>"
    value["canonical_content"] = f"<{len(document.canonical_content)} bytes>"
    return value
