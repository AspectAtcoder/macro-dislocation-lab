from __future__ import annotations

import unittest

from macro_dislocation.news_sources import (
    HttpResponse,
    discover_eia_wpsr_urls,
    discover_fomc_statement_urls,
    extract_element_text,
    fetch_eia_wpsr_table1,
    fetch_fomc_statement,
)


class FakeFetcher:
    def __init__(self, responses: dict[str, bytes]):
        self.responses = responses

    def fetch(self, url: str) -> HttpResponse:
        return HttpResponse(self.responses[url], "text/html", url)


class NewsSourceTests(unittest.TestCase):
    def test_discovers_only_exact_fomc_statement_title(self) -> None:
        index = "https://www.federalreserve.gov/newsevents/pressreleases/2024-press-fomc.htm"
        html = b"""
        <a href="/newsevents/pressreleases/monetary20240131a.htm">
          <em>Federal Reserve issues FOMC statement</em></a>
        <a href="/newsevents/pressreleases/monetary20240131b.htm">
          Other monetary release</a>
        """
        urls = discover_fomc_statement_urls([2024], FakeFetcher({index: html}))
        self.assertEqual(
            urls,
            ["https://www.federalreserve.gov/newsevents/pressreleases/monetary20240131a.htm"],
        )

    def test_extracts_article_not_navigation(self) -> None:
        html = b"<nav>menu words</nav><div id='article'><h1>Title</h1><p>Body text.</p></div>"
        self.assertEqual(extract_element_text(html, "article"), "Title\nBody text.")

    def test_fetches_fomc_document_with_exact_time(self) -> None:
        url = "https://www.federalreserve.gov/newsevents/pressreleases/monetary20240612a.htm"
        body = (
            "<div id='article'><h3>Federal Reserve issues FOMC statement</h3><p>"
            + "Policy content. " * 80
            + "</p></div>"
        ).encode()
        document = fetch_fomc_statement(url, FakeFetcher({url: body}))
        self.assertEqual(document.source_event_id, "fed:fomc_statement:2024-06-12")
        self.assertEqual(document.published_at, "2024-06-12T14:00:00-04:00")
        self.assertEqual(document.timestamp_basis, "official_page_release_time")

    def test_discovers_eia_issue_csv(self) -> None:
        index = "https://www.eia.gov/petroleum/supply/weekly/archive/"
        html = b'<a href="/petroleum/supply/weekly/archive/2024/2024_12_18/wpsr_2024_12_18.php">18</a>'
        urls = discover_eia_wpsr_urls([2024], FakeFetcher({index: html}))
        self.assertEqual(
            urls,
            ["https://www.eia.gov/petroleum/supply/weekly/archive/2024/2024_12_18/csv/table1.csv"],
        )

    def test_fetches_eia_with_inferred_timestamp_label(self) -> None:
        url = "https://www.eia.gov/petroleum/supply/weekly/archive/2024/2024_12_18/csv/table1.csv"
        body = b'STUB_1,current,previous,Difference\nCommercial (Excluding SPR),1,2,-1\n'
        document = fetch_eia_wpsr_table1(url, FakeFetcher({url: body}))
        self.assertEqual(document.source_event_id, "eia:wpsr:2024-12-18")
        self.assertEqual(document.published_at, "2024-12-18T10:30:00-05:00")
        self.assertIn("inferred", document.timestamp_basis)


if __name__ == "__main__":
    unittest.main()
