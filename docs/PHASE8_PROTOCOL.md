# Phase 8 protocol: signed capture authorization

Phase 8 fixes a state-management gap between the 24-hour access-ready deadline
and release-time capture. Re-evaluating a stateless Phase 6 packet after the
deadline cannot prove that credential and rights were ready before it. A signed
access receipt preserves that fact without storing either secret.

## Receipt

Before `access_ready_by`, a fresh `READY_FOR_ACTIVATION` packet, valid rights file,
vendor credential and at least 32-character `MACRO_LAB_AUTHORIZATION_KEY` are all
required. The canonical receipt binds their non-secret evidence to the exact
roster and is signed with HMAC-SHA256. It remains valid through the registered
stream tail.

## Action permit

Every authenticated capture receives a short-lived signed permit:

- `binding_snapshot`: after authorization and before release;
- `pre_release_snapshot`: inside the maximum pre-release snapshot age;
- `calendar_stream`: inside the stream lead, valid through the stream tail.

Snapshot and stream functions verify action, HMAC and current time before any
network or payload processing. A receipt or permit hash without the environment
key is not sufficient.

## Registered result boundary

At 2026-08-11 13:41:13 UTC, the first CPI access deadline had passed by 4,273
seconds and no receipt existed. That release must produce zero empirical evidence.
The next viable roster window is the September 4 Employment Situation release,
whose access-ready deadline is September 3 12:30 UTC.

The offline trial opens no connection. Passing yields
`READY_FOR_SIGNED_CAPTURE_AUTHORIZATION_PENDING_EXTERNAL_ACCESS` and does not
authorize prices, models or orders.
