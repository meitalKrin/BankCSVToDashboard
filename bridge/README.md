# aqueduct-bridge

The Pi-side service. See [`../docs/architecture.md`](../docs/architecture.md).

## Status

| Module | State |
| --- | --- |
| `aqueduct/reconcile.py` | **Implemented and tested** — 35 tests, no dependencies |
| `aqueduct/api.py` — ingest endpoint | not started (Epic 3.3) |
| `aqueduct/inbox.py` — durable inbox | not started (Epic 3.2) |
| `aqueduct/flush.py` — writer to Actual | blocked on spike 0.2 (`actualpy` version pair) |
| `aqueduct/profiles/` — statement CSV profiles | blocked on spike 0.4 (real sample exports) |

## Running the tests

No dependencies beyond `pytest`. Nothing here touches a network or a database.

```bash
cd bridge
pip install -e '.[dev]'
pytest -q
```

## Why the reconciler is a pure function

It performs no I/O and mutates nothing: `(statement rows, pending taps)` in,
a list of decisions out. The caller applies those decisions to Actual.

This is the logic most likely to be subtly wrong — a wrong merge writes a wrong
payee onto a real transaction, and nobody notices for months — so it is the one
piece worth being able to test exhaustively, offline, with no Pi and no phone.
Two of the tests are invariants over 400 generated scenarios each: *nothing is
ever silently dropped*, and *no tap is ever merged into two statement rows*.
