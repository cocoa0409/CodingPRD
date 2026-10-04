"""Queue A (difficulty design), rule dual_variant_calc.

Two valid algorithms over one population diverge: the ledger's provisional
pending projection versus its final posted projection, and the two fee-booking
variants that differ in the number of legs emitted rather than in their sum.
"""
import pytest

from test_helpers import (
    CONTROLLER,
    api_client,
    approve_order,
    create_manual_entry,
    create_order,
    dispatch_order,
    get_success_data,
    ledger_scenario,
    ledger_summary,
    list_transactions,
    mark_entry_settled,
    mark_in_flight,
    post_entry,
    settle_order,
)


def test_ledger_provisional_variant_reports_the_unsettled_dispatch():
    """PRD §3.6: "The provisional view is what an operator sees while payments
    are still in flight; it includes `UNSETTLED` and `IN_SETTLEMENT` rows, so a
    payment that has been dispatched but not yet settled already depresses the
    balance it reports."

    Design: Difficulty/dual_variant_calc/ledger_pending_vs_posted_variant_divergence
    """
    scenario = ledger_scenario()
    ledger_id = scenario["ledger"]["id"]

    # A 2500000-cent inbound deposit, posted and settled, so it leaves the
    # pending partition and enters the posted book.
    deposit = create_manual_entry(
        ledger_id, entry_type="DEPOSIT", direction="CREDIT", amount_cents=2_500_000,
        value_effective_utc="2026-09-01T12:00:00Z")
    post_entry(deposit["id"])
    mark_entry_settled(deposit["id"])

    # An ACH CREDIT order of 250000 cents, approved and dispatched but never
    # settled: its ORIGINATING -250000 leg and its 10-cent FEE leg sit in the
    # pending partition.
    order = create_order(scenario, rail="ACH", direction="CREDIT", amount_cents=250_000)
    order = approve_order(order)
    dispatch_order(order)

    # PRD §3.3 gives the ACH CREDIT fee as 25 - 25 floored to the 10-cent
    # minimum, so the dispatched pair contributes -(amount + fee).
    order_amount, order_fee = 250_000, 10
    summary = ledger_summary(ledger_id, settled=False)
    ledger = get_success_data(api_client.get_ledger(ledger_id, CONTROLLER))
    assert summary["provisional_pending_cents"] == -(order_amount + order_fee), (
        f"the settled deposit is out of the pending partition and the dispatched "
        f"pair depresses it by amount plus fee, expected {-order_amount - order_fee}, "
        f"got {summary['provisional_pending_cents']}"
    )
    assert ledger["pending_balance_cents"] == -(order_amount + order_fee), (
        f"pending_balance_cents is the same projection as provisional_pending_cents"
    )
    assert summary["posted_balance_cents"] == 2_500_000, (
        f"posted expected 2500000, got {summary['posted_balance_cents']}"
    )


def test_ledger_final_variant_excludes_the_unsettled_dispatch():
    """PRD §3.6: "The final view is the book of record used for financial
    reporting; it includes only `SETTLED` rows, so the same ledger reports a
    materially different number before and after settlement of an identical
    population."

    Design: Difficulty/dual_variant_calc/ledger_pending_vs_posted_variant_divergence
    """
    scenario = ledger_scenario()
    ledger_id = scenario["ledger"]["id"]

    deposit = create_manual_entry(
        ledger_id, entry_type="DEPOSIT", direction="CREDIT", amount_cents=2_500_000,
        value_effective_utc="2026-09-01T12:00:00Z")
    post_entry(deposit["id"])
    mark_entry_settled(deposit["id"])

    order = create_order(scenario, rail="ACH", direction="CREDIT", amount_cents=250_000)
    order = approve_order(order)
    dispatch_order(order)

    ledger = get_success_data(api_client.get_ledger(ledger_id, CONTROLLER))
    assert ledger["posted_balance_cents"] == 2_500_000, (
        f"final posted projection expected 2500000, got {ledger['posted_balance_cents']}"
    )


def test_provisional_and_final_variants_disagree_by_the_unsettled_order():
    """PRD §2.4: "`posted_balance_cents` is the signed sum of `net_effect_cents`
    over every transaction in the ledger whose `settlement_status` is exactly
    `SETTLED`, and it is the only balance eligible for reconciliation against a
    bank statement."

    Design: Difficulty/dual_variant_calc/ledger_pending_vs_posted_variant_divergence
    """
    scenario = ledger_scenario()
    ledger_id = scenario["ledger"]["id"]

    deposit = create_manual_entry(
        ledger_id, entry_type="DEPOSIT", direction="CREDIT", amount_cents=2_500_000,
        value_effective_utc="2026-09-01T12:00:00Z")
    post_entry(deposit["id"])
    mark_entry_settled(deposit["id"])

    order = create_order(scenario, rail="ACH", direction="CREDIT", amount_cents=250_000)
    order = approve_order(order)
    dispatch_order(order)

    provisional = ledger_summary(ledger_id, settled=False)
    final = ledger_summary(ledger_id, settled=True)
    assert provisional["provisional_pending_cents"] == -(250_000 + 10), (
        f"the provisional variant carries the dispatched pair — the ORIGINATING "
        f"leg and the ACH CREDIT fee floored to 10 cents — expected -250010, got "
        f"{provisional['provisional_pending_cents']}"
    )
    assert final["posted_balance_cents"] == 2_500_000
    assert final["posted_balance_cents"] != provisional["provisional_pending_cents"], (
        "the two variants must report different numbers over an identical population"
    )


def test_variants_converge_after_the_order_settles():
    """PRD §3.6: "Both derived ledger balances are projections of the same
    transaction population."

    Design: Difficulty/dual_variant_calc/ledger_pending_vs_posted_variant_divergence
    """
    scenario = ledger_scenario()
    ledger_id = scenario["ledger"]["id"]

    deposit = create_manual_entry(
        ledger_id, entry_type="DEPOSIT", direction="CREDIT", amount_cents=2_500_000,
        value_effective_utc="2026-09-01T12:00:00Z")
    post_entry(deposit["id"])
    mark_entry_settled(deposit["id"])

    order = create_order(scenario, rail="ACH", direction="CREDIT", amount_cents=250_000)
    order = approve_order(order)
    dispatched = dispatch_order(order)
    # PRD §3.5: settlement is declared from IN_FLIGHT only, and "a settlement
    # decision" is what moves the legs into the posted partition.  The dispatch
    # branch joins the shared in-flight state first.
    in_flight = mark_in_flight(dispatched)
    settled = settle_order(in_flight)

    ledger = get_success_data(api_client.get_ledger(ledger_id, CONTROLLER))
    assert settled["settlement_status"] == "SETTLED"
    # The settled deposit alone is 2500000; the order's settled pair adds
    # -(250000 + 10), so the posted book reports the whole settled population.
    assert ledger["posted_balance_cents"] == 2_500_000 - 250_010, (
        f"posted expected {-250010 + 2500000} after settlement, "
        f"got {ledger['posted_balance_cents']}"
    )


def test_wire_fee_is_booked_as_one_aggregate_fee_leg():
    """PRD §3.3: "the whole fee in one entry, never a series" and PRD §3.5:
    "the `WIRE` dispatch moves it `APPROVED` → `WIRE_DISPATCHED` and books the
    whole wire fee as one `FEE` entry with `net_effect_cents` equal to the
    negative of the wire total rather than as a tranche series".

    Design: Difficulty/dual_variant_calc/rail_fee_aggregate_charge_vs_tranche_series
    """
    scenario = ledger_scenario()
    order = create_order(scenario, rail="WIRE", direction="CREDIT", amount_cents=3_000_000)
    order = approve_order(order)
    dispatch_order(order)

    fees = list_transactions(scenario["ledger"]["id"], entry_type="FEE")
    assert len(fees) == 1, f"expected exactly 1 FEE leg, got {len(fees)}"
    assert fees[0]["net_effect_cents"] == -1_250, (
        f"expected the whole 1250-cent wire fee in one entry, got {fees[0]['net_effect_cents']}"
    )


def test_wire_fee_total_is_not_the_discriminator_between_the_variants():
    """PRD §3.3: "The operator-facing presentation may itemise that same total
    as a breakdown of wire milestone tranches, emitting one component of 500
    cents plus 250 cents for every complete 1000000-cent tranche of the amount;
    the components sum to the identical total, so the ledger effect is the same
    while the reported line count is not."

    Design: Difficulty/dual_variant_calc/rail_fee_aggregate_charge_vs_tranche_series
    """
    scenario = ledger_scenario()
    order = create_order(scenario, rail="WIRE", direction="CREDIT", amount_cents=3_000_000)
    order = approve_order(order)
    dispatch_order(order)

    ledger_id = scenario["ledger"]["id"]
    fees = list_transactions(ledger_id, entry_type="FEE")
    assert sum(f["net_effect_cents"] for f in fees) == -1_250

    ledger = get_success_data(api_client.get_ledger(ledger_id, CONTROLLER))
    assert ledger["pending_balance_cents"] == -3_001_250, (
        f"expected -3001250 regardless of how the fee is itemised, "
        f"got {ledger['pending_balance_cents']}"
    )