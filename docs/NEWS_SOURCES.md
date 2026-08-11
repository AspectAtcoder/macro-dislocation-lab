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
WPSR issue-specific CSV files from 2024. Two subsequent network acquisitions each
added observations but zero document versions. Including one duplicate probe per
run, the store ended with 76 documents and 231 observations, and the extracted
feature hash remained identical.

BLS and OPEC returned HTTP 403 from this execution environment, so they remain
catalogued but were not counted toward the Phase 1 gate. No blocking or bot-control
bypass was attempted. Trading Economics, LSEG and Bloomberg remain uncontracted;
therefore consensus vintages, real delivery timestamps and content/ML rights are
still a hard prerequisite for a price-feature trial.

## Phase 2 vendor preflight

The repository now implements the Trading Economics calendar response normalizer,
append-only snapshot contract and credential preflight. On 2026-08-10 no API key
was configured and the guest endpoint returned HTTP 410. No vendor row was counted
from documentation or unauthenticated access.

The local 2024 research calendar was deliberately used as a negative control: all
60 components were rejected for price use because their pre-release snapshot time,
consensus vintage and data rights are not proven. The required paid-trial sample,
fields, written rights and acceptance tests are frozen in
`config/vendor_trial_requirements.json`.

## Phase 3 capture implementation

The repository now has a transport-neutral immutable capture store for Trading
Economics calendar data. It maps the official HTTPS snapshot field style and the
lower-case calendar-stream field style through one normalizer. The implementation
follows the provider's current official documentation:

- point-in-time calendar: <https://docs.tradingeconomics.com/economic_calendar/point-in-time/>;
- latest-event snapshot and updates: <https://docs.tradingeconomics.com/economic_calendar/snapshot/>;
- persistent calendar stream: <https://docs.tradingeconomics.com/economic_calendar/streaming/>.

The completed offline trial used original synthetic fixtures, not payloads copied
from these pages. It made no authenticated request and acquired zero empirical
vendor rows. The next production action remains conditional on a paid credential
and an approved rights attestation.

## Phase 4 schedule and stream operations

Phase 4 adds versioned schedule evidence and a release-window trace. The schedule
normalizer uses `America/New_York` rather than a fixed Eastern-to-UTC offset. The
supervisor records the schedule hash used by each run because BLS says its release
calendar is updated as needed. The current official references are:

- BLS 2026 selected releases: <https://www.bls.gov/schedule/2026/home.htm>;
- BLS Employment Situation schedule: <https://www.bls.gov/schedule/news_release/empsit.htm>;
- Trading Economics calendar stream: <https://docs.tradingeconomics.com/economic_calendar/streaming/>;
- Trading Economics calendar schema: <https://docs.tradingeconomics.com/economic_calendar/schema/>.

The completed Phase 4 run used only synthetic schedule and telemetry fixtures. It
opened no authenticated connection and counted zero empirical release windows.
Clock, continuity and schedule checks are operational controls, not evidence of a
tradable edge.

## Phase 5 evidence enrollment

Phase 5 treats the Trading Economics streaming and schema pages as interface
references only. A trace assertion is not accepted as vendor evidence until its
capture ID resolves to the immutable raw store and the normalized provider event
identity replays from that blob. CPI and Employment Situation schedule evidence
must remain versioned from BLS official calendars.

The completed Phase 5 trial used only original synthetic payloads. No credential,
rights attestation, authenticated request, empirical window or market-price join
was present. Production use remains conditional on the provider contract and the
runbook's evidence-enrollment gate.

## Phase 6 prospective roster

Phase 6 verified the visible official CPI and Employment Situation schedule pages
and froze the next three releases from each family. The roster is schedule
metadata, not news evidence. It is converted with `America/New_York`, versioned by
SHA-256 and must be rechecked inside 48 hours because BLS updates its calendar as
needed.

At the registered evaluation time only the August 12 CPI release was inside the
activation interval. It remained blocked because no Trading Economics credential
or approved rights attestation was present. No substitute aggregator, historical
backfill or current-page scrape was counted as a live receipt. See
`docs/CAMPAIGN_ACTIVATION_RUNBOOK.md` for the operational boundary.

## Phase 7 provider-component binding

Phase 7 adds the join key that schedule pages cannot provide: stable vendor event
IDs for every logical CPI/NFP component. A binding is not trusted because a JSON
file calls itself licensed. Its capture ID, receive time, license, rights and
provider IDs must replay from the Phase 3 immutable store, and each provider
timestamp must equal the official BLS roster time.

The completed trial used original synthetic provider IDs and made no network
request. It produced one structurally valid Phase 4 schedule preview but zero
executable handoffs. Production remains blocked pending licensed access and a
prospectively captured snapshot.
