"""Tests for the reconciler.

The suite is organised around the ways a financial ledger gets quietly wrong:
a match that shouldn't have been taken, a record dropped without trace, an
amount compared loosely, a boundary off by one day.
"""

from __future__ import annotations

import datetime as dt
import random

import pytest

from aqueduct.reconcile import (
    Action,
    PendingTap,
    StatementRow,
    _is_opaque_descriptor,
    reconcile,
    resolve_payee,
    statement_imported_id,
    wallet_imported_id,
)

ILS = {"Max Credit Card": "ILS", "Bank Account": "ILS"}
TODAY = dt.date(2026, 9, 1)
D = dt.date


def tap(uuid="t1", account="Max Credit Card", day=D(2026, 8, 10),
        amount=-4500, currency="ILS", payee="קפה גרג"):
    return PendingTap(event_uuid=uuid, account=account, date=day,
                      amount_minor=amount, currency=currency, payee=payee)


def row(row_id="r1", account="Max Credit Card", day=D(2026, 8, 12),
        amount=-4500, currency="ILS", payee="MAX*4821"):
    return StatementRow(row_id=row_id, account=account, date=day,
                        amount_minor=amount, currency=currency, payee=payee)


# ---------------------------------------------------------------- happy paths

def test_unique_mutual_match_merges():
    res = reconcile([row()], [tap()], account_currency=ILS, today=TODAY)
    assert len(res.outcomes) == 1
    out = res.outcomes[0]
    assert out.action is Action.MERGED
    assert out.rows == ("r1",)
    assert out.taps == ("t1",)          # the placeholder the caller must delete
    assert res.still_pending == ()


def test_row_with_no_tap_is_inserted():
    res = reconcile([row()], [], account_currency=ILS, today=TODAY)
    assert res.outcomes[0].action is Action.INSERTED
    assert res.outcomes[0].rows == ("r1",)


def test_merge_carries_over_the_richer_payee():
    # Statement says "MAX*4821"; the tap knows it was a coffee shop.
    res = reconcile([row(payee="MAX*4821")], [tap(payee="קפה גרג")],
                    account_currency=ILS, today=TODAY)
    assert res.outcomes[0].resolved_payee == "קפה גרג"


def test_merge_keeps_a_real_statement_payee():
    res = reconcile([row(payee="שופרסל דיל")], [tap(payee="קפה גרג")],
                    account_currency=ILS, today=TODAY)
    assert res.outcomes[0].resolved_payee == "שופרסל דיל"


# ------------------------------------------------------- ambiguity never wins

def test_two_identical_taps_flag_rather_than_guess():
    """The ₪45 coffee case. Two taps, same amount, both in window, one row."""
    taps = [tap("t1", day=D(2026, 8, 10)), tap("t2", day=D(2026, 8, 11))]
    res = reconcile([row(day=D(2026, 8, 12))], taps,
                    account_currency=ILS, today=TODAY)
    assert [o.action for o in res.outcomes] == [Action.FLAGGED_AMBIGUOUS]
    out = res.outcomes[0]
    assert out.rows == ("r1",)
    assert set(out.taps) == {"t1", "t2"}
    assert not res.by_action(Action.MERGED)     # nothing was merged


def test_ambiguity_in_the_other_direction_also_flags():
    """Two statement rows compatible with a single tap."""
    rows = [row("r1", day=D(2026, 8, 12)), row("r2", day=D(2026, 8, 13))]
    res = reconcile(rows, [tap()], account_currency=ILS, today=TODAY)
    assert [o.action for o in res.outcomes] == [Action.FLAGGED_AMBIGUOUS]
    assert set(res.outcomes[0].rows) == {"r1", "r2"}
    assert res.outcomes[0].taps == ("t1",)


def test_nearer_date_does_not_break_a_tie():
    """Even with a strictly nearer candidate, we refuse to pick. FR-25."""
    taps = [tap("near", day=D(2026, 8, 11)), tap("far", day=D(2026, 8, 8))]
    res = reconcile([row(day=D(2026, 8, 12))], taps,
                    account_currency=ILS, today=TODAY)
    assert res.outcomes[0].action is Action.FLAGGED_AMBIGUOUS


def test_distinct_amounts_are_not_ambiguous():
    taps = [tap("t1", amount=-4500), tap("t2", amount=-4600)]
    rows = [row("r1", amount=-4500), row("r2", amount=-4600)]
    res = reconcile(rows, taps, account_currency=ILS, today=TODAY)
    assert {o.action for o in res.outcomes} == {Action.MERGED}
    assert len(res.outcomes) == 2


# ------------------------------------------------------------- match criteria

@pytest.mark.parametrize("offset,expected", [
    (0, Action.MERGED),    # settles same day
    (5, Action.MERGED),    # exactly the window edge
    (6, Action.INSERTED),  # one day past
    (-1, Action.INSERTED),  # statement dated before the tap
])
def test_date_window_boundaries(offset, expected):
    res = reconcile([row(day=D(2026, 8, 10) + dt.timedelta(days=offset))],
                    [tap(day=D(2026, 8, 10))],
                    account_currency=ILS, today=TODAY)
    assert res.outcomes[0].action is expected


def test_one_agora_difference_is_not_a_match():
    res = reconcile([row(amount=-4501)], [tap(amount=-4500)],
                    account_currency=ILS, today=TODAY)
    assert res.outcomes[0].action is Action.INSERTED


def test_same_amount_on_a_different_account_is_not_a_match():
    res = reconcile([row(account="Bank Account")], [tap(account="Max Credit Card")],
                    account_currency=ILS, today=TODAY)
    assert res.outcomes[0].action is Action.INSERTED


# ----------------------------------------------------------------- currency

def test_foreign_currency_tap_is_flagged_not_matched():
    res = reconcile([row(amount=-4500)], [tap(currency="USD", amount=-4500)],
                    account_currency=ILS, today=TODAY)
    actions = {o.action for o in res.outcomes}
    assert actions == {Action.FLAGGED_CURRENCY, Action.INSERTED}
    assert not res.by_action(Action.MERGED)


def test_unknown_account_raises_rather_than_skipping_the_check():
    with pytest.raises(ValueError, match="no currency configured"):
        reconcile([], [tap(account="Typo Card")], account_currency=ILS, today=TODAY)


# ------------------------------------------------------------------ orphans

def test_old_unmatched_tap_becomes_an_orphan_not_a_deletion():
    res = reconcile([], [tap(day=D(2026, 6, 1))], account_currency=ILS, today=TODAY)
    assert res.outcomes[0].action is Action.ORPHANED
    assert res.outcomes[0].taps == ("t1",)
    assert res.still_pending == ()


def test_recent_unmatched_tap_is_left_pending():
    res = reconcile([], [tap(day=D(2026, 8, 28))], account_currency=ILS, today=TODAY)
    assert res.outcomes == ()
    assert res.still_pending == ("t1",)


def test_orphan_boundary_is_exact():
    cutoff = TODAY - dt.timedelta(days=45)
    assert reconcile([], [tap(day=cutoff)], account_currency=ILS,
                     today=TODAY).still_pending == ("t1",)
    assert reconcile([], [tap(day=cutoff - dt.timedelta(days=1))],
                     account_currency=ILS, today=TODAY).outcomes[0].action is Action.ORPHANED


# ------------------------------------------------------------- input hygiene

def test_duplicate_row_ids_raise():
    with pytest.raises(ValueError, match="duplicate row_id"):
        reconcile([row("r1"), row("r1")], [], account_currency=ILS, today=TODAY)


def test_duplicate_event_uuids_raise():
    with pytest.raises(ValueError, match="duplicate event_uuid"):
        reconcile([], [tap("t1"), tap("t1")], account_currency=ILS, today=TODAY)


# --------------------------------------------------------------- idempotency

def test_rerunning_after_a_merge_inserts_rather_than_merging():
    """Second ingest of the same statement: the tap is gone, Actual dedups the row."""
    first = reconcile([row()], [tap()], account_currency=ILS, today=TODAY)
    assert first.outcomes[0].action is Action.MERGED
    second = reconcile([row()], [], account_currency=ILS, today=TODAY)
    assert second.outcomes[0].action is Action.INSERTED


def test_imported_id_helpers_are_distinguishable():
    assert wallet_imported_id("abc") == "wallet:abc"
    assert statement_imported_id("abc") == "stmt:abc"
    assert wallet_imported_id("x") != statement_imported_id("x")


# ------------------------------------------------------------ payee heuristic

@pytest.mark.parametrize("text,opaque", [
    ("MAX*4821", True),      # issuer code
    ("4821", True),          # pure digits
    ("---", True),           # no letters
    ("ABC", True),           # too short
    ("", True),              # empty
    ("קפה גרג", False),      # Hebrew name, no case to rely on
    ("שופרסל דיל אונליין", False),
    ("Cafe Greg", False),
    ("SUPER PHARM 123", False),  # has spaces: reads as a name, keep it
])
def test_opaque_descriptor_detection(text, opaque):
    assert _is_opaque_descriptor(text) is opaque


def test_resolve_payee_falls_back_when_tap_has_none():
    assert resolve_payee("MAX*4821", "") == "MAX*4821"


# ------------------------------------------------------------ the invariant

def test_nothing_is_ever_silently_dropped():
    """G4/FR-27, as an executable assertion, over many generated scenarios.

    Every input row appears in exactly one outcome. Every input tap appears in
    exactly one outcome, or in still_pending. Never zero, never twice.
    """
    accounts = ["Max Credit Card", "Bank Account"]
    for seed in range(400):
        rnd = random.Random(seed)
        rows = [
            StatementRow(
                row_id=f"r{i}",
                account=rnd.choice(accounts),
                date=D(2026, 8, 1) + dt.timedelta(days=rnd.randrange(0, 25)),
                amount_minor=-rnd.choice([4500, 4600, 12000]),
                currency="ILS",
                payee=rnd.choice(["MAX*4821", "שופרסל דיל"]),
            )
            for i in range(rnd.randrange(0, 5))
        ]
        taps = [
            PendingTap(
                event_uuid=f"t{i}",
                account=rnd.choice(accounts),
                date=D(2026, 6, 1) + dt.timedelta(days=rnd.randrange(0, 85)),
                amount_minor=-rnd.choice([4500, 4600, 12000]),
                currency=rnd.choice(["ILS", "ILS", "ILS", "USD"]),
                payee="קפה גרג",
            )
            for i in range(rnd.randrange(0, 5))
        ]

        res = reconcile(rows, taps, account_currency=ILS, today=TODAY)

        row_mentions = [rid for o in res.outcomes for rid in o.rows]
        tap_mentions = [tid for o in res.outcomes for tid in o.taps]
        tap_mentions += list(res.still_pending)

        assert sorted(row_mentions) == sorted(r.row_id for r in rows), (
            f"seed {seed}: a statement row was dropped or double-counted"
        )
        assert sorted(tap_mentions) == sorted(t.event_uuid for t in taps), (
            f"seed {seed}: a tap was dropped or double-counted"
        )


def test_a_merge_is_never_taken_when_any_ambiguity_exists():
    """Stronger than the unit cases: across generated scenarios, every MERGED
    outcome names exactly one row and one tap, and no id is merged twice."""
    for seed in range(400):
        rnd = random.Random(seed)
        rows = [
            StatementRow(f"r{i}", "Max Credit Card",
                         D(2026, 8, 10) + dt.timedelta(days=rnd.randrange(0, 8)),
                         -rnd.choice([4500, 4600]), "ILS", "MAX*1")
            for i in range(rnd.randrange(0, 4))
        ]
        taps = [
            PendingTap(f"t{i}", "Max Credit Card",
                       D(2026, 8, 10) + dt.timedelta(days=rnd.randrange(0, 8)),
                       -rnd.choice([4500, 4600]), "ILS", "קפה")
            for i in range(rnd.randrange(0, 4))
        ]
        res = reconcile(rows, taps, account_currency=ILS, today=TODAY)
        merged_taps = []
        for out in res.by_action(Action.MERGED):
            assert len(out.rows) == 1 and len(out.taps) == 1
            merged_taps.extend(out.taps)
        assert len(merged_taps) == len(set(merged_taps)), (
            f"seed {seed}: a tap was merged into two different statement rows"
        )
