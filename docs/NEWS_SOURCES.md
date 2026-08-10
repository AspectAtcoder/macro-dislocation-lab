# News and release-source decision

Phase 0 separates three jobs that should not be conflated:

1. structured actual, consensus, previous and revised values;
2. authoritative release text and detailed tables;
3. unscheduled breaking news and geopolitical headlines.

## MVP decision

- Calendar and consensus: a paid Trading Economics Calendar API plan with
  point-in-time history and streaming is the lower-friction candidate. Its current
  schema exposes Actual, Forecast, Previous, Revised and numeric fields. The public
  research calendar used in Experiment 0 is not acceptable for production.
- Monetary policy: Federal Reserve monetary-policy RSS plus the official statement,
  minutes, projections and speech archives.
- U.S. macro detail: BLS and BEA official releases. A calendar vendor supplies the
  fast structured headline; the official page is the authoritative reconciliation
  and source of components.
- Oil: EIA API v2 and Weekly Petroleum Status Report for structured details; OPEC
  Monthly Oil Market Report and official statements for revisions and language.

This is sufficient for a +30 second to +5 minute research horizon. Public websites
and RSS are not assumed to win the release jump.

## Production decision if the Phase 1 gate passes

Prefer LSEG Machine Readable News plus Real-Time Economics because real-time and
historical news can share a normalized point-in-time model. Bloomberg Event-Driven
Feeds plus ECO is the alternative. Do not buy both before a limited vendor trial.

Before contracting either vendor, obtain written rights for retention, historical
backtesting, embedding generation, machine-learning training and derived data.
Access to a terminal does not automatically grant these rights.

## Dual-path ingestion

The fast vendor event and official source are both retained:

```text
vendor stream ---------\
                         -> immutable raw versions -> event bundle -> extractor
official release/RSS ---/                              |              |
calendar/schedule -------------------------------------+              +-> features
```

Required timestamps are `scheduled_at`, `published_at`, `first_seen_at`,
`received_at` and `feature_ready_at`. Every correction is a new version keyed by
source event ID and content hash. No current page may overwrite an earlier vintage.

## Sources verified during Phase 0

- Trading Economics Calendar: <https://docs.tradingeconomics.com/economic_calendar/>
- Federal Reserve RSS: <https://www.federalreserve.gov/feeds/feeds.htm>
- BLS releases: <https://www.bls.gov/bls/newsrels.htm>
- EIA API v2: <https://www.eia.gov/opendata/documentation.php>
- OPEC MOMR archive: <https://publications.opec.org/momr/information/2476>
- LSEG Machine Readable News: <https://www.lseg.com/en/data-analytics/financial-news-service/machine-readable-news>
- Bloomberg Event-Driven Feeds: <https://professional.bloomberg.com/products/data/enterprise-catalog/event-driven-feeds/>

Generic news aggregators, search-result scraping and social-media scraping are not
primary trade inputs because their latency, completeness, revision history and
rights are not controlled.

## Phase 1 execution result

On 2026-08-10 the official-source path was exercised against real archives, not
fixtures. It acquired 24 Federal Reserve FOMC statements from 2022–2024 and 52 EIA
WPSR issue-specific CSV files from 2024. A second network acquisition added 76
observations but zero document versions, and the extracted feature hash was
identical.

BLS and OPEC returned HTTP 403 from this execution environment, so they remain
catalogued but were not counted toward the Phase 1 gate. No blocking or bot-control
bypass was attempted. Trading Economics, LSEG and Bloomberg remain uncontracted;
therefore consensus vintages, real delivery timestamps and content/ML rights are
still a hard prerequisite for a price-feature trial.
