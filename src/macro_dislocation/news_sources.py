from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, time as clock_time
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .news_store import SourceDocument, utc_now


FED_BASE = "https://www.federalreserve.gov"
FED_INDEX = FED_BASE + "/newsevents/pressreleases/{year}-press-fomc.htm"
EIA_BASE = "https://www.eia.gov"
EIA_ARCHIVE = EIA_BASE + "/petroleum/supply/weekly/archive/"


@dataclass(frozen=True)
class HttpResponse:
    body: bytes
    content_type: str
    final_url: str


class HttpFetcher:
    def __init__(
        self,
        *,
        user_agent: str = "macro-dislocation-lab/0.1 (+official-archive-research)",
        timeout: float = 30.0,
        attempts: int = 3,
    ):
        self.user_agent = user_agent
        self.timeout = timeout
        self.attempts = attempts

    def fetch(self, url: str) -> HttpResponse:
        last_error: Exception | None = None
        for attempt in range(self.attempts):
            request = Request(
                url,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "text/html,text/csv,application/xml;q=0.9,*/*;q=0.5",
                },
            )
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    return HttpResponse(
                        body=response.read(),
                        content_type=response.headers.get_content_type(),
                        final_url=response.geturl(),
                    )
            except Exception as exc:  # pragma: no cover - precise network errors vary
                last_error = exc
                if attempt + 1 < self.attempts:
                    time.sleep(0.5 * (2**attempt))
        assert last_error is not None
        raise last_error


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            text = re.sub(r"\s+", " ", " ".join(self._text)).strip()
            self.links.append((self._href, text))
            self._href = None
            self._text = []


class ElementTextParser(HTMLParser):
    def __init__(self, *, element_id: str):
        super().__init__(convert_charrefs=True)
        self.element_id = element_id
        self._active_depth: int | None = None
        self._depth = 0
        self._ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._depth += 1
        if dict(attrs).get("id") == self.element_id and self._active_depth is None:
            self._active_depth = self._depth
        if self._active_depth is not None and tag.lower() in {"script", "style", "nav"}:
            self._ignored_depth += 1
        if self._active_depth is not None and not self._ignored_depth and tag.lower() in {
            "p",
            "h1",
            "h2",
            "h3",
            "li",
            "br",
        }:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self._active_depth is not None and tag.lower() in {"script", "style", "nav"} and self._ignored_depth:
            self._ignored_depth -= 1
        if self._active_depth == self._depth:
            self._active_depth = None
        self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._active_depth is not None and not self._ignored_depth:
            self.parts.append(data)

    def text(self) -> str:
        lines = [re.sub(r"\s+", " ", line).strip() for line in "".join(self.parts).splitlines()]
        return "\n".join(line for line in lines if line)


def parse_links(html_bytes: bytes) -> list[tuple[str, str]]:
    parser = LinkParser()
    parser.feed(html_bytes.decode("utf-8-sig", errors="replace"))
    return parser.links


def extract_element_text(html_bytes: bytes, element_id: str) -> str:
    parser = ElementTextParser(element_id=element_id)
    parser.feed(html_bytes.decode("utf-8-sig", errors="replace"))
    return unescape(parser.text())


def _published_at(release_date: date, release_time: clock_time) -> str:
    return datetime.combine(
        release_date, release_time, tzinfo=ZoneInfo("America/New_York")
    ).isoformat()


def discover_fomc_statement_urls(
    years: Iterable[int], fetcher: HttpFetcher
) -> list[str]:
    urls: set[str] = set()
    expected_title = "federal reserve issues fomc statement"
    for year in years:
        index_url = FED_INDEX.format(year=year)
        response = fetcher.fetch(index_url)
        for href, title in parse_links(response.body):
            normalized = re.sub(r"\s+", " ", title).strip().lower()
            if normalized == expected_title and re.search(rf"monetary{year}\d{{4}}a\.htm$", href):
                urls.add(urljoin(index_url, href))
    return sorted(urls)


def fetch_fomc_statement(url: str, fetcher: HttpFetcher) -> SourceDocument:
    response = fetcher.fetch(url)
    match = re.search(r"monetary(\d{8})a\.htm", response.final_url)
    if not match:
        raise ValueError(f"unrecognized FOMC statement URL: {response.final_url}")
    release_date = datetime.strptime(match.group(1), "%Y%m%d").date()
    content = extract_element_text(response.body, "article")
    if "Federal Reserve issues FOMC statement" not in content or len(content) < 500:
        raise ValueError(f"FOMC article extraction failed: {response.final_url}")
    published = _published_at(release_date, clock_time(14, 0))
    return SourceDocument(
        source="federal_reserve",
        source_event_id=f"fed:fomc_statement:{release_date.isoformat()}",
        document_type="fomc_statement",
        title="Federal Reserve issues FOMC statement",
        canonical_url=response.final_url,
        raw_bytes=response.body,
        canonical_content=(content + "\n").encode("utf-8"),
        scheduled_at=published,
        published_at=published,
        timestamp_basis="official_page_release_time",
        content_type="text/html",
        license_class="official_public_release",
        received_at=utc_now(),
        metadata={"release_date": release_date.isoformat(), "archive": True},
    )


def discover_eia_wpsr_urls(years: Iterable[int], fetcher: HttpFetcher) -> list[str]:
    response = fetcher.fetch(EIA_ARCHIVE)
    year_set = {str(year) for year in years}
    urls: set[str] = set()
    pattern = re.compile(
        r"/petroleum/supply/weekly/archive/(\d{4})/(\d{4}_\d{2}_\d{2})/wpsr_\2\.php$"
    )
    for href, _ in parse_links(response.body):
        match = pattern.search(href)
        if match and match.group(1) in year_set:
            issue_page = urljoin(EIA_ARCHIVE, href)
            urls.add(urljoin(issue_page, "csv/table1.csv"))
    return sorted(urls)


def fetch_eia_wpsr_table1(url: str, fetcher: HttpFetcher) -> SourceDocument:
    response = fetcher.fetch(url)
    match = re.search(r"/(\d{4})_(\d{2})_(\d{2})/csv/table1\.csv$", response.final_url)
    if not match:
        raise ValueError(f"unrecognized EIA WPSR URL: {response.final_url}")
    release_date = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    if b"Commercial (Excluding SPR)" not in response.body:
        raise ValueError(f"EIA table1 validation failed: {response.final_url}")
    # Historical archive pages identify the release date. The exact historical
    # holiday time is not embedded in the CSV, so this is explicitly an inference.
    inferred_time = clock_time(10, 30) if release_date.weekday() == 2 else clock_time(12, 0)
    published = _published_at(release_date, inferred_time)
    return SourceDocument(
        source="eia",
        source_event_id=f"eia:wpsr:{release_date.isoformat()}",
        document_type="wpsr_table1_csv",
        title=f"Weekly Petroleum Status Report table 1 — {release_date.isoformat()}",
        canonical_url=response.final_url,
        raw_bytes=response.body,
        canonical_content=response.body,
        scheduled_at=published,
        published_at=published,
        timestamp_basis="official_archive_date_schedule_time_inferred",
        content_type="text/csv",
        license_class="official_public_data",
        received_at=utc_now(),
        metadata={
            "release_date": release_date.isoformat(),
            "archive": True,
            "historical_arrival_recovered": False,
        },
    )


def _parallel_fetch(
    urls: list[str],
    function: Callable[[str, HttpFetcher], SourceDocument],
    fetcher: HttpFetcher,
    workers: int,
) -> list[SourceDocument]:
    results: list[SourceDocument] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(function, url, fetcher): url for url in urls}
        for future in as_completed(futures):
            results.append(future.result())
    return sorted(results, key=lambda item: item.source_event_id)


def acquire_official_documents(
    *,
    fed_years: Iterable[int],
    eia_years: Iterable[int],
    workers: int = 8,
    fetcher: HttpFetcher | None = None,
) -> tuple[list[SourceDocument], dict[str, object]]:
    active_fetcher = fetcher or HttpFetcher()
    fed_urls = discover_fomc_statement_urls(fed_years, active_fetcher)
    eia_urls = discover_eia_wpsr_urls(eia_years, active_fetcher)
    fed_documents = _parallel_fetch(
        fed_urls, fetch_fomc_statement, active_fetcher, workers
    )
    eia_documents = _parallel_fetch(
        eia_urls, fetch_eia_wpsr_table1, active_fetcher, workers
    )
    return fed_documents + eia_documents, {
        "federal_reserve_urls": len(fed_urls),
        "eia_urls": len(eia_urls),
        "federal_reserve_documents": len(fed_documents),
        "eia_documents": len(eia_documents),
    }
