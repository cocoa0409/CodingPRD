"""Queue A (difficulty design), rule compensating_invariant.

Two conserved quantities that must survive compensation: the reverse-rail fee
pool and the ledger's double-entry identity.
"""
import pytest

from test_helpers import (
    CONTROLLER,
    api_client,
    assign_exception,
    build_three_active_return_legs,
    build_two_active_return_legs,
    create_manual_entry,
    get_success_data,
    ledger_scenario,
    list_exceptions,
    list_transactions,
    post_entry,
    recompute_ledger,
    resolve_exception,
)


def test_resolving_a_second_return_leg_conserves_the_fee_pool():
    """PRD §2.11: "The ledger's `delivered_fee_transfers_cents` plus its
    `undeliverable_cents` must always equal 25 cents multiplied by the number of
    return legs that have been resolved on that ledger."

    Design: Difficulty/compensating_invariant/reverse_rail_fee_pool_conserved_across_resolution
    """
    scenario = build_two_active_return_legs()
    ledger_id = scenario["ledger"]["id"]
    exceptions = list_exceptions(ledger_id, kind="RETURN")
    assert len(exceptions) == 2

    assign_exception(exceptions[0]["id"])
    resolve_exception(exceptions[0]["id"], "attributed")

    ledger = get_success_data(api_client.get_ledger(ledger_id, CONTROLLER))
    total = ledger["delivered_fee_transfers_cents"] + ledger["undeliverable_cents"]
    assert total == 25, f"one resolved return leg retains 25 cents, got {total}"


def test_the_conserved_quantity_is_not_a_balance_identity():
    """PRD §3.9: "Delivered shares accumulate on the ledger's
    `delivered_fee_transfers_cents` and shortfalls on its `undeliverable_cents`".

    Design: Difficulty/compensating_invariant/reverse_rail_fee_pool_conserved_across_resolution
    """
    scenario = ledger_scenario()
    _returned_order(scenario, amount_cents=1_500, reason="R01")
    ledger_id = scenario["ledger"]["id"]
    before = get_success_data(api_client.get_ledger(ledger_id, CONTROLLER))

    exception = list_exceptions(ledger_id, kind="RETURN")[0]
    assign_exception(exception["id"])
    resolve_exception(exception["id"], "attributed")

    after = get_success_data(api_client.get_ledger(ledger_id, CONTROLLER))
    assert after["posted_balance_cents"] == before["posted_balance_cents"], (
        "the fee transfer must not move the posted balance"
    )


def test_conserved_pool_grows_by_exactly_twenty_five_cents_per_resolved_leg():
    """PRD §3.9: "`delivered_fee_transfers_cents` plus `undeliverable_cents` must
    equal 25 cents multiplied by the number of resolved return legs on the
    ledger."

    Design: Difficulty/compensating_invariant/reverse_rail_fee_pool_conserved_across_resolution
    """
    scenario = build_three_active_return_legs()
    ledger_id = scenario["ledger"]["id"]
    exceptions = list_exceptions(ledger_id, kind="RETURN")

    assign_exception(exceptions[0]["id"])
    resolve_exception(exceptions[0]["id"], "first leg")
    first = get_success_data(api_client.get_ledger(ledger_id, CONTROLLER))
    assert (first["delivered_fee_transfers_cents"] + first["undeliverable_cents"]) == 25

    assign_exception(exceptions[1]["id"])
    resolve_exception(exceptions[1]["id"], "second leg")
    second = get_success_data(api_client.get_ledger(ledger_id, CONTROLLER))
    assert (second["delivered_fee_transfers_cents"] + second["undeliverable_cents"]) == 50


def test_compensation_returns_the_ledger_balances_to_zero():
    """PRD §2.11: "The invariant is that booked credits minus booked debits
    equals `posted_balance_cents` plus `pending_balance_cents`, to a tolerance of
    zero cents."
    PRD §3.6: "A `POSTED` transaction of `entry_type` `ORIGINATING` that entered
    the `POSTED` lifecycle through the reversal command must be voided through
    that same command".

    Design: Difficulty/compensating_invariant/double_entry_identity_returns_to_baseline_after_compensation
    """
    scenario = ledger_scenario()
    ledger_id = scenario["ledger"]["id"]
    entry = create_manual_entry(
        ledger_id, entry_type="ADJUSTMENT", direction="CREDIT", amount_cents=6_400,
        value_effective_utc="2026-09-01T09:00:00Z")
    post_entry(entry["id"])

    before = get_success_data(api_client.ledger_summary(ledger_id, {"settled": False}, CONTROLLER))
    assert before["provisional_pending_cents"] == 6_400

    reversal = create_manual_entry(
        ledger_id, entry_type="REVERSAL", direction="DEBIT", amount_cents=6_400,
        value_effective_utc="2026-09-01T10:00:00Z", reverses_transaction_id=entry["id"])
    post_entry(reversal["id"])

    ledger = get_success_data(api_client.get_ledger(ledger_id, CONTROLLER))
    assert ledger["pending_balance_cents"] == 0, (
        f"the compensation should zero the pending book, got {ledger['pending_balance_cents']}"
    )
    assert ledger["posted_balance_cents"] == 0


def test_double_entry_identity_holds_at_zero_after_the_compensation():
    """PRD §2.11: "Rows whose `lifecycle_status` is `VOID` or `REJECTED` are
    excluded from both sides of that identity, so voiding an entry removes its
    contribution from both sums in the same step and the identity survives the
    void intact."

    Design: Difficulty/compensating_invariant/double_entry_identity_returns_to_baseline_after_compensation
    """
    scenario = ledger_scenario()
    ledger_id = scenario["ledger"]["id"]
    entry = create_manual_entry(
        ledger_id, entry_type="ADJUSTMENT", direction="CREDIT", amount_cents=6_400,
        value_effective_utc="2026-09-01T09:00:00Z")
    post_entry(entry["id"])
    reversal = create_manual_entry(
        ledger_id, entry_type="REVERSAL", direction="DEBIT", amount_cents=6_400,
        value_effective_utc="2026-09-01T10:00:00Z", reverses_transaction_id=entry["id"])
    post_entry(reversal["id"])

    rows = list_transactions(ledger_id)
    credits = sum(t["amount_cents"] for t in rows
                  if t["direction"] == "CREDIT"
                  and t["lifecycle_status"] in ("PENDING", "POSTED"))
    debits = sum(t["amount_cents"] for t in rows
                 if t["direction"] == "DEBIT"
                 and t["lifecycle_status"] in ("PENDING", "POSTED"))
    ledger = get_success_data(api_client.get_ledger(ledger_id, CONTROLLER))
    assert credits - debits == (ledger["posted_balance_cents"] + ledger["pending_balance_cents"])


def test_recompute_confirms_zero_drift_rather_than_cancellation():
    """PRD §3.9: "Recomputing a ledger re-derives `pending_balance_cents` and
    `posted_balance_cents` under the projection rule of §3.6, re-verifies the
    double-entry identity and the reverse-rail fee invariant, raises
    `ERR_LEDGER_UNBALANCED` with HTTP 409 on failure".

    Design: Difficulty/compensating_invariant/double_entry_identity_returns_to_baseline_after_compensation
    """
    scenario = ledger_scenario()
    ledger_id = scenario["ledger"]["id"]
    entry = create_manual_entry(
        ledger_id, entry_type="ADJUSTMENT", direction="CREDIT", amount_cents=6_400,
        value_effective_utc="2026-09-01T09:00:00Z")
    post_entry(entry["id"])
    reversal = create_manual_entry(
        ledger_id, entry_type="REVERSAL", direction="DEBIT", amount_cents=6_400,
        value_effective_utc="2026-09-01T10:00:00Z", reverses_transaction_id=entry["id"])
    post_entry(reversal["id"])

    recomputed = recompute_ledger(ledger_id)
    assert recomputed["pending_balance_cents"] == 0
    assert recomputed["posted_balance_cents"] == 0


def _returned_order(scenario, amount_cents, reason):
    from test_helpers import approve_order, create_order, dispatch_order, mark_in_flight, return_order

    order = create_order(scenario, rail="ACH", direction="CREDIT", amount_cents=amount_cents)
    order = approve_order(order)
    dispatch_order(order)
    in_flight = mark_in_flight(order)
    return return_order(in_flight, return_reason=reason, expected_version=in_flight["version"])