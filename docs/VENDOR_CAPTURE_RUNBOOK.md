# Trading Economics shadow-capture runbook

This runbook starts data collection only. It does not authorize trading, a price
join or model fitting.

## Preconditions

1. Obtain a paid Trading Economics credential that includes the calendar methods
   and streaming channel needed for the trial.
2. Confirm the retention, historical-backtest, machine-learning and derived-data
   rights in writing.
3. Create a rights attestation outside Git, following
   `config/vendor_rights_attestation.schema.json`. Store it under `data/private/`
   if it must live inside the working directory; that path is ignored by Git.
4. Supply the credential only through `TRADING_ECONOMICS_API_KEY`. Do not place it
   in a command argument, config file, notebook or shell history.
5. Confirm the host clock is synchronized before every release window. The local
   receive timestamp is part of the research evidence.

The runtime validator rejects unapproved, incomplete, test or placeholder rights
attestations before opening a network connection.

## HTTPS snapshot capture

Use a pre-release snapshot to preserve the consensus that was visible before the
scheduled release. For example, a scheduler can invoke:

```bash
macro-lab capture-te-snapshot \
  --rights-attestation data/private/vendor_rights.json \
  --indicator "inflation rate" \
  --start YYYY-MM-DD \
  --end YYYY-MM-DD
```

The command stores exact bytes under `data/raw/vendor_capture_store/raw/` and one
receipt envelope in `observations.jsonl`. Its persisted endpoint contains no query
string or credential.

Historical retrieval records today's local receipt. It must not be relabelled as
a historical live arrival or used to prove a pre-release consensus snapshot.

## Calendar stream capture

Trading Economics documents an authenticated persistent WebSocket subscription to
the `calendar` topic. The repository deliberately keeps the socket client separate
from the durable recorder. Feed one complete JSON message per line from the
official SDK callback into:

```bash
macro-lab capture-te-stream-jsonl \
  --rights-attestation data/private/vendor_rights.json
```

The recorder validates `topic=calendar`, provider identity, JSON integrity and
rights, then stamps the complete in-memory message with local UTC and monotonic
receipt clocks. Empty lines are ignored. A message containing the configured
credential is rejected before persistence.

## Release-window procedure

For each CPI or employment release:

1. record clock-sync evidence and process start time;
2. capture an HTTPS consensus snapshot before the scheduled time;
3. keep the calendar stream recorder active through the release and revision
   window;
4. preserve reconnects and duplicate messages as observations;
5. run the store integrity audit before using any normalized output;
6. compare official release time, provider `LastUpdate`, local receipt and
   monotonic order; do not collapse these clocks.

At least several real release cycles are required to validate timing and schema
stability. Passing the offline Step 3 test alone is not empirical evidence.
