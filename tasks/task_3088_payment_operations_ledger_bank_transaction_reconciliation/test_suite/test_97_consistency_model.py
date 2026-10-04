"""Queue B (corner design), section ``consistency_model``.

The derived balances recomputed by a posting are already readable in the same
request and in an immediate follow-up read.
"""
import pytest

from test_helpers import (
    ANALYST,
    CONTROLLER,
    api_client,
    create_manual_entry,
    get_success_data,
    ledger_scenario,
    validate_success,
)


def test_derived_balances_are_visible_in_the_same_response():
    """PRD §2.4: "All four derived balances are recomputed after every posting,
    every settlement decision and every recomputation, and the recomputation
    happens inside the same request that caused it, so the response to the
    mutating call already carries the new numbers."
    PRD §3.6: "The projection is refreshed inside the request that caused it, so
    the response to that request already carries the new balances."

    Design: Corner/consistency_model/derived_balances_are_visible_in_the_same_response
    """
    scenario = ledger_scenario()
    res = api_client.book_transaction(
        scenario["ledger"]["id"],
        {"entry_type": "ADJUSTMENT", "direction": "CREDIT", "amount_cents": 2_100,
         "value_effective_utc": "2026-09-01T09:00:00Z"},
        ANALYST)
    entry = validate_success(res, 201)
    assert entry["net_effect_cents"] == 2_100


def test_the_immediate_follow_up_read_reports_the_projected_balance():
    """PRD §2.4: "This is a derived-field reconciliation model, not an
    eventually-consistent one."

    Design: Corner/consistency_model/derived_balances_are_visible_in_the_same_response
    """
    scenario = ledger_scenario()
    create_manual_entry(
        scenario["ledger"]["id"], entry_type="ADJUSTMENT", direction="CREDIT",
        amount_cents=2_100, value_effective_utc="2026-09-01T09:00:00Z")

    ledger = get_success_data(
        api_client.get_ledger(scenario["ledger"]["id"], CONTROLLER))
    assert ledger["pending_balance_cents"] == 2_100, (
        f"the follow-up read must already carry the projection, "
        f"got {ledger['pending_balance_cents']}"
    )


def test_the_ledger_version_advances_exactly_once_across_the_posting():
    """PRD §2.5: "`version` is an integer that increments by one on every
    modification to the resource and exists so that clients can participate in
    optimistic concurrency control."

    Design: Corner/consistency_model/derived_balances_are_visible_in_the_same_response
    """
    scenario = ledger_scenario()
    before = get_success_data(
        api_client.get_ledger(scenario["ledger"]["id"], CONTROLLER))["version"]

    create_manual_entry(
        scenario["ledger"]["id"], entry_type="ADJUSTMENT", direction="CREDIT",
        amount_cents=2_100, value_effective_utc="2026-09-01T09:00:00Z")

    after = get_success_data(
        api_client.get_ledger(scenario["ledger"]["id"], CONTROLLER))["version"]
    assert after == before + 1, (
        f"expected the ledger version to advance by exactly 1, got {before} -> {after}"
    )