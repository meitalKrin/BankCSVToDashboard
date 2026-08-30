"""Reconciliation between provisional Wallet taps and authoritative statement rows.

Implements PRD FR-23 … FR-27 and architecture §3.6.

Two provenances meet here:

* :class:`PendingTap` — created from a Google Wallet notification and already
  written to Actual as **uncleared**, with ``imported_id = wallet:<event_uuid>``.
  It is a *prediction*: an authorisation that may never settle, or may settle for
  a different amount.
* :class:`StatementRow` — parsed from an issuer's statement export.
  **Authoritative.** It wins every disagreement.

The reconciler is a **pure function**. It performs no I/O, talks to no server and
mutates nothing: it maps ``(rows, taps)`` to a list of decisions that the caller
applies to Actual. That is deliberate — this is the logic most likely to be
subtly wrong, and purity is what makes it exhaustively testable.

Load-bearing rules
------------------

* **Ambiguity never auto-resolves** (FR-25). Two ₪45.00 coffees in one week is a
  completely normal thing to happen, and quietly picking one is how you end up
  with a ledger you cannot trust. A merge is taken only when the match is
  *mutually* unique: exactly one row compatible with exactly one tap, and that
  tap compatible with no other row. Ambiguity in **either** direction flags
  everything involved and merges nothing.
* **Nothing is ever silently dropped** (G4, FR-27). Every input row and every
  input tap appears in exactly one outcome, or in ``still_pending``. There is a
  test asserting exactly that, over generated inputs.
* **Sign and currency normalisation happen upstream**, in the CSV profile parser.
  By the time values arrive here, expenses are negative integer minor units
  (agorot). No floats, ever.

Known future knob
-----------------
FR-23 defines the match window as ``[tap.date, tap.date + N]``. If timezone skew
ever produces a statement dated the day *before* its tap, this is the place that
needs a small negative lower bound. Deliberately not added until real data shows
it — an untested knob is a liability.
"""

from __future__ import annotations

import datetime as dt
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence

DEFAULT_MATCH_WINDOW_DAYS = 5
DEFAULT_ORPHAN_AGE_DAYS = 45

WALLET_IMPORTED_ID_PREFIX = "wallet"
STATEMENT_IMPORTED_ID_PREFIX = "stmt"


def wallet_imported_id(event_uuid: str) -> str:
    """Actual's dedup key for a tap-derived transaction (D2)."""
    return f"{WALLET_IMPORTED_ID_PREFIX}:{event_uuid}"


def statement_imported_id(row_id: str) -> str:
    """Actual's dedup key for a statement-derived transaction.

    Because ``row_id`` is stable across re-parses of the same file, re-ingesting
    a statement is idempotent: Actual rejects the duplicate ``imported_id``.
    """
    return f"{STATEMENT_IMPORTED_ID_PREFIX}:{row_id}"


class Action(str, Enum):
    """What the caller should do. One decision per outcome."""

    MERGED = "MERGED"
    """Unique mutual match. Keep the statement transaction, apply
    ``resolved_payee``, delete the tap placeholder named in ``taps``."""

    INSERTED = "INSERTED"
    """No compatible tap. Write the statement row as a new cleared transaction."""

    FLAGGED_AMBIGUOUS = "FLAGGED_AMBIGUOUS"
    """Two or more plausible pairings. Write the rows as cleared transactions but
    leave every tap in ``taps`` alone, and surface all of it for a human."""

    FLAGGED_CURRENCY = "FLAGGED_CURRENCY"
    """The tap's currency differs from its account's (FR-26). Never matched on
    amount — the settled figure will have been converted."""

    ORPHANED = "ORPHANED"
    """A tap with no statement row, older than ``orphan_age_days``. A refund, a
    declined payment we mis-captured, or a gap. Surfaced, never deleted."""


@dataclass(frozen=True)
class PendingTap:
    """A provisional transaction derived from a Wallet notification."""

    event_uuid: str
    account: str
    date: dt.date
    amount_minor: int
    currency: str
    payee: str = ""
    notes: str = ""


@dataclass(frozen=True)
class StatementRow:
    """One parsed row of an issuer statement. Authoritative."""

    row_id: str
    account: str
    date: dt.date
    amount_minor: int
    currency: str
    payee: str = ""
    notes: str = ""


@dataclass(frozen=True)
class Outcome:
    action: Action
    rows: tuple[str, ...] = ()
    taps: tuple[str, ...] = ()
    resolved_payee: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class ReconciliationResult:
    outcomes: tuple[Outcome, ...]
    still_pending: tuple[str, ...]
    """Taps with no match yet, but too young to call orphans. Left untouched."""

    def by_action(self, action: Action) -> tuple[Outcome, ...]:
        return tuple(o for o in self.outcomes if o.action is action)


def _is_opaque_descriptor(text: str) -> bool:
    """Does this look like an issuer code rather than a merchant name?

    Script-agnostic on purpose: Hebrew has no letter case, so any rule built on
    uppercase would misclassify every Hebrew merchant as a code.
    """
    s = (text or "").strip()
    if not s:
        return True
    if not any(ch.isalpha() for ch in s):
        return True
    if len(s) < 4:
        return True
    if " " not in s and any(ch.isdigit() for ch in s):
        return True
    return False


def resolve_payee(statement_payee: str, tap_payee: str) -> str:
    """FR-24 — carry the tap's payee over only when the statement's isn't a name.

    Conservative by design: the statement is authoritative, *including* its
    payee. We override only when it is clearly a descriptor rather than a name.
    """
    tap = (tap_payee or "").strip()
    stmt = (statement_payee or "").strip()
    if not tap:
        return stmt
    if _is_opaque_descriptor(stmt):
        return tap
    return stmt


def _compatible(row: StatementRow, tap: PendingTap, window_days: int) -> bool:
    """FR-23 — same account, same currency, equal amount, settlement in window."""
    return (
        row.account == tap.account
        and row.currency == tap.currency
        and row.amount_minor == tap.amount_minor
        and tap.date <= row.date <= tap.date + dt.timedelta(days=window_days)
    )


def _require_unique(items: Sequence[str], label: str) -> None:
    seen: set[str] = set()
    for i in items:
        if i in seen:
            raise ValueError(
                f"duplicate {label} {i!r}. Identifiers must be unique — two "
                f"identical purchases are two rows and need two distinct ids, "
                f"which is the parser's responsibility, not the reconciler's."
            )
        seen.add(i)


def reconcile(
    rows: Sequence[StatementRow],
    taps: Sequence[PendingTap],
    *,
    account_currency: Mapping[str, str],
    today: dt.date,
    window_days: int = DEFAULT_MATCH_WINDOW_DAYS,
    orphan_age_days: int = DEFAULT_ORPHAN_AGE_DAYS,
) -> ReconciliationResult:
    """Decide what to do with each statement row and each pending tap.

    :param account_currency: account name -> ISO 4217 code. Required, so that
        FR-26 is always enforced rather than optionally enforced.
    :param today: injected rather than read from the clock, so the orphan sweep
        is deterministic and testable.
    """
    _require_unique([r.row_id for r in rows], "row_id")
    _require_unique([t.event_uuid for t in taps], "event_uuid")

    outcomes: list[Outcome] = []

    # FR-26: a tap in a currency other than its account's never matches on
    # amount — the settled figure will have been through an FX conversion.
    eligible: list[PendingTap] = []
    for tap in taps:
        if tap.account not in account_currency:
            # A typo in AQUEDUCT_CARD_MAP must not degrade into "skip the
            # currency check for this one". Fail loudly (project rule: never
            # guess with money).
            raise ValueError(
                f"tap {tap.event_uuid!r} references account {tap.account!r}, "
                f"which has no currency configured. Known accounts: "
                f"{sorted(account_currency)}"
            )
        expected = account_currency[tap.account]
        if tap.currency != expected:
            outcomes.append(
                Outcome(
                    action=Action.FLAGGED_CURRENCY,
                    taps=(tap.event_uuid,),
                    reason=(
                        f"tap is {tap.currency}, account {tap.account!r} is "
                        f"{expected}; amounts are not comparable"
                    ),
                )
            )
        else:
            eligible.append(tap)

    edges_row: dict[str, set[str]] = {r.row_id: set() for r in rows}
    edges_tap: dict[str, set[str]] = {t.event_uuid: set() for t in eligible}
    for row in rows:
        for tap in eligible:
            if _compatible(row, tap, window_days):
                edges_row[row.row_id].add(tap.event_uuid)
                edges_tap[tap.event_uuid].add(row.row_id)

    row_by_id = {r.row_id: r for r in rows}
    tap_by_id = {t.event_uuid: t for t in eligible}

    # Connected components over the bipartite compatibility graph. A merge is
    # only safe inside a component of exactly one row and one tap — that is what
    # "mutually unique" means, and it catches ambiguity in both directions.
    seen: set[tuple[str, str]] = set()
    matched: set[str] = set()
    nodes = [("r", r.row_id) for r in rows] + [("t", t.event_uuid) for t in eligible]

    for start in nodes:
        if start in seen:
            continue
        comp_rows: list[str] = []
        comp_taps: list[str] = []
        queue = deque([start])
        seen.add(start)
        while queue:
            kind, ident = queue.popleft()
            if kind == "r":
                comp_rows.append(ident)
                neighbours = [("t", x) for x in edges_row[ident]]
            else:
                comp_taps.append(ident)
                neighbours = [("r", x) for x in edges_tap[ident]]
            for node in neighbours:
                if node not in seen:
                    seen.add(node)
                    queue.append(node)

        comp_rows.sort()
        comp_taps.sort()

        if not comp_rows:
            # A tap with no compatible row. The orphan sweep decides its fate.
            continue

        if len(comp_rows) == 1 and not comp_taps:
            row = row_by_id[comp_rows[0]]
            outcomes.append(
                Outcome(
                    action=Action.INSERTED,
                    rows=(row.row_id,),
                    resolved_payee=row.payee.strip(),
                    reason="no compatible pending tap",
                )
            )
        elif len(comp_rows) == 1 and len(comp_taps) == 1:
            row = row_by_id[comp_rows[0]]
            tap = tap_by_id[comp_taps[0]]
            matched.add(tap.event_uuid)
            outcomes.append(
                Outcome(
                    action=Action.MERGED,
                    rows=(row.row_id,),
                    taps=(tap.event_uuid,),
                    resolved_payee=resolve_payee(row.payee, tap.payee),
                    reason="unique mutual match",
                )
            )
        else:
            outcomes.append(
                Outcome(
                    action=Action.FLAGGED_AMBIGUOUS,
                    rows=tuple(comp_rows),
                    taps=tuple(comp_taps),
                    reason=(
                        f"{len(comp_rows)} row(s) and {len(comp_taps)} tap(s) are "
                        f"mutually compatible; no pairing is unambiguous"
                    ),
                )
            )

    # FR-27: unmatched taps past the age threshold become exceptions, never
    # deletions. Anything younger is simply still waiting for its statement.
    still_pending: list[str] = []
    cutoff = today - dt.timedelta(days=orphan_age_days)
    for tap in eligible:
        if tap.event_uuid in matched:
            continue
        if any(tap.event_uuid in o.taps for o in outcomes):
            continue
        if tap.date < cutoff:
            outcomes.append(
                Outcome(
                    action=Action.ORPHANED,
                    taps=(tap.event_uuid,),
                    reason=(
                        f"no statement row after {orphan_age_days} days "
                        f"(tap dated {tap.date.isoformat()})"
                    ),
                )
            )
        else:
            still_pending.append(tap.event_uuid)

    return ReconciliationResult(
        outcomes=tuple(outcomes),
        still_pending=tuple(sorted(still_pending)),
    )
