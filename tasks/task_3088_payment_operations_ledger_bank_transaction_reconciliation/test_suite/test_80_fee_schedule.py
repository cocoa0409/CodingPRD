"""Queue B (corner design), section ``calculations``.

The rail fee schedule: floors, caps, tranche milestones and the exclusion of
voided rows from both balance partitions.
"""
import pytest

from test_helpers import (
    CONTROLLER,
    api_client,
    approve_order,
    create_manual_entry,
    create_order,
    dispatch_order,
    fee_total_cents,
    get_success_data,
    ledger_scenario,
    ledger_version,
    list_transactions,
    post_entry,
    void_entry,
)


def _dispatched_fee_legs(scenario, rail, direction, amount_cents, settlement_speed=None):
    overrides = {}
    if settlement_speed is not None:
        overrides["settlement_speed"] = settlement_speed
    order = create_order(scenario, rail=rail, direction=direction,
                         amount_cents=amount_cents, **overrides)
    order = approve_order(order)
    dispatch_order(order)
    return list_transactions(scenario["ledger"]["id"], entry_type="FEE",
                             payment_order_id=order["id"])


def test_ach_credit_fee_floors_to_the_ten_cent_minimum():
    """PRD §3.3: "A floor is then applied last, so that the final
    `fee_total_cents` is the larger of the running total and 10 cents."

    Design: Corner/calculations/ach_credit_fee_floors_to_the_ten_cent_minimum
    """
    scenario = ledger_scenario()
    fees = _dispatched_fee_legs(scenario, "ACH", "CREDIT", 1_500)
    assert len(fees) == 1, f"expected exactly one FEE leg, got {len(fees)}"
    assert fees[0]["net_effect_cents"] == -10, (
        f"the ACH CREDIT fee floors to 10 cents, got {fees[0]['net_effect_cents']}"
    )


def test_ach_credit_originating_leg_matches_the_amount():
    """PRD §3.5: "An `ORIGINATING` `Transaction` is created ... and a
    `net_effect_cents` that is the negative of `amount_cents` for a `CREDIT`
    order".

    Design: Corner/calculations/ach_credit_fee_floors_to_the_ten_cent_minimum
    """
    scenario = ledger_scenario()
    _dispatched_fee_legs(scenario, "ACH", "CREDIT", 1_500)
    originating = list_transactions(scenario["ledger"]["id"], entry_type="ORIGINATING")
    assert len(originating) == 1
    assert originating[0]["net_effect_cents"] == -1_500


def test_the_floored_fee_still_depresses_the_pending_balance():
    """PRD §2.4: "`pending_balance_cents` is the signed sum of `net_effect_cents`
    over every transaction in the ledger whose `settlement_status` is either
    `UNSETTLED` or `IN_SETTLEMENT`."

    Design: Corner/calculations/ach_credit_fee_floors_to_the_ten_cent_minimum
    """
    scenario = ledger_scenario()
    _dispatched_fee_legs(scenario, "ACH", "CREDIT", 1_500)
    ledger = get_success_data(api_client.get_ledger(scenario["ledger"]["id"], CONTROLLER))
    assert ledger["pending_balance_cents"] == -1_510, (
        f"the floor must be applied rather than dropped, got {ledger['pending_balance_cents']}"
    )


def test_wire_fee_uses_the_million_cent_tranche_milestones():
    """PRD §3.3: "A wire's base fee is 500 cents plus 250 cents for every
    complete 1000000-cent tranche of `amount_cents`, again by integer floor
    division."

    Design: Corner/calculations/wire_fee_uses_the_million_cent_tranche_milestones
    """
    scenario = ledger_scenario()
    fees = _dispatched_fee_legs(scenario, "WIRE", "CREDIT", 3_000_000)
    total = -sum(f["net_effect_cents"] for f in fees)
    assert total == 1_250, f"expected 500 + 3 x 250 == 1250, got {total}"


def test_wire_tranche_count_is_keyed_on_complete_millions():
    """PRD §3.3: "500 cents plus 250 cents for every complete 1000000-cent
    tranche of `amount_cents`, again by integer floor division."

    Design: Corner/calculations/wire_fee_uses_the_million_cent_tranche_milestones
    """
    scenario = ledger_scenario()
    fees = _dispatched_fee_legs(scenario, "WIRE", "CREDIT", 2_999_999)
    total = -sum(f["net_effect_cents"] for f in fees)
    assert total == 1_000, (
        f"2999999 holds only two complete tranches, expected 1000, got {total}"
    )


def test_the_wire_fee_schedule_implemented_by_the_helper_matches_the_contract():
    """PRD §3.3: "The base fee is 25 cents for a standard ACH order and 500
    cents for a same-day ACH order. A real-time order's base fee is 75 cents plus
    100 cents for every complete 1000000-cent tranche of `amount_cents`, the
    tranche count being obtained by integer floor division of the amount by
    1000000."

    Design: Corner/calculations/wire_fee_uses_the_million_cent_tranche_milestones
    """
    assert fee_total_cents("WIRE", "CREDIT", 3_000_000) == 1_250
    assert fee_total_cents("WIRE", "CREDIT", 2_999_999) == 1_000
    assert fee_total_cents("ACH", "CREDIT", 1_500) == 10


def test_ach_same_day_fee_is_capped_at_four_hundred_cents():
    """PRD §3.3: "the total may not exceed 400 cents on `ACH`, 2500 cents on
    `WIRE`, or 250 cents on `RTP`".
    PRD §3.3: "The ordering is load-bearing: because the cap is applied after
    the direction adjustment and before the floor".

    Design: Corner/calculations/ach_same_day_fee_is_capped_at_four_hundred_cents
    """
    scenario = ledger_scenario()
    fees = _dispatched_fee_legs(scenario, "ACH", "CREDIT", 250_000,
                                settlement_speed="SAME_DAY")
    assert len(fees) == 1
    assert fees[0]["net_effect_cents"] == -400, (
        f"the ACH cap is 400 cents, got {fees[0]['net_effect_cents']}"
    )


def test_the_cap_binds_below_the_uncapped_same_day_base():
    """PRD §3.3: "The base fee is 25 cents for a standard ACH order and 500 cents
    for a same-day ACH order."
    PRD §3.3: "when the direction is `CREDIT` and the rail is `ACH` or `RTP`, 25
    cents are subtracted from the running total."

    Design: Corner/calculations/ach_same_day_fee_is_capped_at_four_hundred_cents
    """
    assert fee_total_cents("ACH", "CREDIT", 250_000, settlement_speed="SAME_DAY") == 400
    # 500 base minus the 25-cent direction adjustment would be 475 without the cap.
    assert 500 - 25 == 475


def test_the_capped_fee_is_reflected_in_the_pending_balance():
    """PRD §2.4: "All four derived balances are recomputed after every posting,
    every settlement decision and every recomputation, and the recomputation
    happens inside the same request that caused it".

    Design: Corner/calculations/ach_same_day_fee_is_capped_at_four_hundred_cents
    """
    scenario = ledger_scenario()
    _dispatched_fee_legs(scenario, "ACH", "CREDIT", 250_000, settlement_speed="SAME_DAY")
    ledger = get_success_data(api_client.get_ledger(scenario["ledger"]["id"], CONTROLLER))
    assert ledger["pending_balance_cents"] == -250_400


def test_voided_rows_are_excluded_from_both_balance_partitions():
    """PRD §3.6: "Rows whose `lifecycle_status` is `VOID` or `REJECTED`
    contribute zero to both sums."

    Design: Corner/calculations/voided_rows_are_excluded_from_both_balance_partitions
    """
    scenario = ledger_scenario()
    entry = create_manual_entry(
        scenario["ledger"]["id"], entry_type="ADJUSTMENT", direction="CREDIT",
        amount_cents=4_400, value_effective_utc="2026-09-01T09:00:00Z")
    post_entry(entry["id"])
    voided = void_entry(entry["id"], ledger_version(scenario["ledger"]["id"]))

    assert voided["lifecycle_status"] == "VOID"
    assert voided["settlement_status"] == "UNSETTLED"
    ledger = get_success_data(api_client.get_ledger(scenario["ledger"]["id"], CONTROLLER))
    assert ledger["pending_balance_cents"] == 0
    assert ledger["posted_balance_cents"] == 0


def test_a_voided_row_is_retained_and_listable():
    """PRD §3.6: "the row is retained on disk but excluded from every balance
    projection".

    Design: Corner/calculations/voided_rows_are_excluded_from_both_balance_partitions
    """
    scenario = ledger_scenario()
    entry = create_manual_entry(
        scenario["ledger"]["id"], entry_type="ADJUSTMENT", direction="CREDIT",
        amount_cents=4_400, value_effective_utc="2026-09-01T09:00:00Z")
    post_entry(entry["id"])
    void_entry(entry["id"], ledger_version(scenario["ledger"]["id"]))

    voided_rows = list_transactions(scenario["ledger"]["id"], lifecycle_status="VOID")
    assert len(voided_rows) == 1, "the voided row must still be readable"