from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from macro_dislocation.news_store import NewsStore, SourceDocument


def sample_document(content: bytes = b"first") -> SourceDocument:
    return SourceDocument(
        source="example",
        source_event_id="example:event:1",
        document_type="statement",
        title="Example",
        canonical_url="https://example.test/1",
        raw_bytes=b"<html>" + content + b"</html>",
        canonical_content=content,
        scheduled_at="2024-01-01T14:00:00-05:00",
        published_at="2024-01-01T14:00:00-05:00",
        timestamp_basis="official",
        content_type="text/html",
        license_class="official_public_release",
        received_at="2024-01-01T19:00:01+00:00",
    )


class NewsStoreTests(unittest.TestCase):
    def test_duplicate_is_observation_not_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = NewsStore(Path(directory))
            first = store.ingest(sample_document())
            duplicate = store.ingest(
                replace(sample_document(), received_at="2024-01-01T19:00:02+00:00")
            )
            self.assertTrue(first.inserted_document)
            self.assertFalse(duplicate.inserted_document)
            self.assertEqual(first.document_id, duplicate.document_id)
            self.assertEqual(store.counts()["documents"], 1)
            self.assertEqual(store.counts()["observations"], 2)

    def test_changed_content_creates_next_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = NewsStore(Path(directory))
            first = store.ingest(sample_document(b"first"))
            second = store.ingest(sample_document(b"corrected"))
            self.assertEqual(first.version, 1)
            self.assertEqual(second.version, 2)
            self.assertNotEqual(first.document_id, second.document_id)
            self.assertEqual(store.counts()["documents"], 2)

    def test_validation_and_feature_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = NewsStore(Path(directory))
            result = store.ingest(sample_document())
            store.mark_feature_ready([result.document_id], "2024-01-01T19:00:03+00:00")
            self.assertTrue(store.validate()["valid"])
            self.assertEqual(
                store.documents()[0]["feature_ready_at"],
                "2024-01-01T19:00:03+00:00",
            )


if __name__ == "__main__":
    unittest.main()
