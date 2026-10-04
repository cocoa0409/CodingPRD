"""The award selector, the award cascade, and freight subsidy decisions."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_ledger_reconciles,
    create_active_agreement,
    create_bidding_load,
    create_certified_member,
    create_certified_member_with_shares,
    create_load,
    expected_freight_estimate,
    expected_freight_subsidy,
    get_success_data,
    grant_shares,
    make_member_headers,
    record_freight_decision,
    setup_awarded_load,
    submit_bid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import SECOND_ADMIN_OPERATOR_ID, make_admin_headers

ADMIN = TEST_USERS["admin_headers"]


def test_award_tie_break_prefers_earlier_created_bid(api):
    """PRD §3.5: "Ties are resolved in two steps, in order: the earliest bid
    `created_at` wins, and if two bids were created at the same instant, the
    earliest member `created_at` wins."

    Design: Corner/cross_cutting_complexity_layers/award_tie_break_prefers_earlier_created_bid
    """
    api.set_clock({"current_utc": "2026-09-01T00:00:00Z"}, ADMIN)

    member_first = create_certified_member(
        api, name="Buckeye Harvest", state_code="OH",
        food_insecure_population=250_000, storage_capacity_lbs=200_000,
        refrigerated_capacity_lbs=50_000, transport_ability="LOCAL",
    )
    member_second = create_certified_member(
        api, name="Hawkeye Harvest", state_code="IA",
        food_insecure_population=100_000, storage_capacity_lbs=150_000,
        refrigerated_capacity_lbs=30_000, transport_ability="LOCAL",
        audit_opened_by=SECOND_ADMIN_OPERATOR_ID,
    )
    grant_shares(api, member_first)
    grant_shares(api, member_second)

    agreement = create_active_agreement(api)
    load = create_bidding_load(api, agreement["id"], distance_miles=620)

    api.set_clock({"current_utc": "2026-09-01T00:05:00Z"}, ADMIN)
    early_bid = submit_bid(api, load, member_second, shares_offered=300,
                           preference_rank=1, can_self_transport=True)

    fresh = get_success_data(api.get_load(load["id"], ADMIN))
    api.set_clock({"current_utc": "2026-09-01T00:10:00Z"}, ADMIN)
    late_bid = submit_bid(api, fresh, member_first, shares_offered=300,
                          preference_rank=1, can_self_transport=True)

    # Both bids score 300*100 + 40 (self transport) + 10 (LOCAL) - 6 (620 miles) = 30038.
    awarded = validate_success(api.award_load(load["id"], ADMIN), 200)
    assert awarded["status"] == "AWARDED"
    assert awarded["awarded_bid_id"] == early_bid["id"]
    assert awarded["awarded_member_id"] == member_second["id"]

    loser = validate_success(api.get_bid(late_bid["id"], ADMIN), 200)
    assert loser["bid_status"] == "REJECTED"
    assert loser["rejection_reason"] == "LOSING_BID"


def test_award_with_no_eligible_bids_rejected(api):
    """PRD §3.5: "If the filter leaves no candidate at all — whether because no
    bid was ever submitted or because every submitted bid was filtered out — the
    award is rejected with `ERR_NO_ELIGIBLE_BIDS`."

    Design: Corner/cross_cutting_complexity_layers/award_with_no_eligible_bids_returns_no_eligible_bids
    """
    member = create_certified_member_with_shares(api)
    agreement = create_active_agreement(api)
    load = create_bidding_load(api, agreement["id"])
    bid = submit_bid(api, load, member, shares_offered=400)
    api.withdraw_bid(bid["id"], make_member_headers(member["id"]))

    res = api.award_load(load["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_NO_ELIGIBLE_BIDS)

    after = validate_success(api.get_load(load["id"], ADMIN), 200)
    assert after["status"] == "BIDDING"
    assert after["awarded_bid_id"] is None


def test_award_response_carries_post_cascade_state(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data field."
    PRD §3.5.1: "The load's `freight_estimate_cents` is recomputed from the haul
    distance and the winner's `transport_ability`, the `freight_decision` is set
    back to `PENDING`, `freight_subsidy_cents` is set to zero, and
    `member_freight_due_cents` is set equal to the full estimate, since no subsidy
    has yet been granted."

    Design: Corner/consistency_model/award_response_carries_post_cascade_state
    """
    member = create_certified_member_with_shares(api)
    agreement = create_active_agreement(api)
    load = create_bidding_load(api, agreement["id"], distance_miles=620)
    bid = submit_bid(api, load, member, shares_offered=400)

    awarded = validate_success(api.award_load(load["id"], ADMIN), 200)
    assert awarded["status"] == "AWARDED"
    assert awarded["awarded_bid_id"] == bid["id"]
    assert awarded["awarded_member_id"] == member["id"]
    assert awarded["freight_estimate_cents"] == expected_freight_estimate(620)
    assert awarded["freight_estimate_cents"] == 114_700
    assert awarded["freight_decision"] == "PENDING"
    assert awarded["freight_subsidy_cents"] == 0
    assert awarded["member_freight_due_cents"] == 114_700


def test_award_provisional_freight_estimate_pins_detour_to_zero(api):
    """PRD §3.6: "The provisional computation happens at award time and fixes
    `detour_miles` at zero, so it uses the straight-line haul distance only"
    PRD §3.6: "The cost of the haul is built from a base amount: the load's
    `distance_miles` plus any recorded `detour_miles`, multiplied by the network's
    standard haulage rate of 185 cents per mile."

    Design: Difficulty/dual_variant_calc/freight_provisional_vs_final_on_awarded_load
    """
    member = create_certified_member_with_shares(api)
    agreement = create_active_agreement(api, freight_subsidy_pool_cents=500_000)
    awarded, _bid = setup_awarded_load(
        api, agreement["id"], member, distance_miles=620, lot_code="LOT-77",
    )
    # 620 * 185 = 114700 with the detour pinned to zero.
    assert awarded["freight_estimate_cents"] == 114_700
    assert awarded["freight_subsidy_cents"] == 0
    assert awarded["member_freight_due_cents"] == 114_700
    assert awarded["freight_decision"] == "PENDING"


def test_final_freight_decision_uses_detour_and_charges_pool(api):
    """PRD §3.6: "When the member cannot self-transport, the haul is at least 400
    miles, and the member's `transport_ability` is `NONE` or `LOCAL`, an additional
    uplift of 15 percent of the base is computed and rounded up to the next whole
    cent."
    PRD §3.6: "Whatever survives becomes `freight_subsidy_cents`, and the member's
    `member_freight_due_cents` is the base minus that subsidy."
    PRD §3.6: "recording a `COVERED` decision immediately commits that subsidy
    against the agreement's freight budget: the agreement's
    `freight_subsidy_used_cents` is increased by the load's `freight_subsidy_cents`"

    Design: Difficulty/dual_variant_calc/freight_provisional_vs_final_on_awarded_load
    """
    member = create_certified_member_with_shares(api, transport_ability="LOCAL")
    agreement = create_active_agreement(api, freight_subsidy_pool_cents=500_000)
    awarded, _bid = setup_awarded_load(
        api, agreement["id"], member, distance_miles=620, lot_code="LOT-77",
        can_self_transport=False,
    )
    decided = record_freight_decision(api, awarded["id"], decision="COVERED",
                                      detour_miles=60)

    # base = (620 + 60) * 185 = 125800; ceil(0.75*base) + ceil(0.15*base) = 113220.
    assert decided["freight_subsidy_cents"] == 113_220
    assert decided["member_freight_due_cents"] == 12_580
    assert decided["freight_decision"] == "COVERED"

    agreement_after = validate_success(api.get_donor_agreement(agreement["id"], ADMIN), 200)
    assert agreement_after["freight_subsidy_used_cents"] == 113_220


def test_absolute_subsidy_cap_binds_on_long_remote_haul(api):
    """PRD §3.6: "The two components are added, and the sum is then capped by two
    independent ceilings: the agreement's remaining pool, which is the
    `freight_subsidy_pool_cents` minus the `freight_subsidy_used_cents` already
    committed, and a per-load maximum of 250,000 cents."

    Design: Difficulty/combinatorial_formula/freight_subsidy_nested_caps_on_remote_member
    """
    member = create_certified_member_with_shares(api, transport_ability="NONE",
                                                 storage_capacity_lbs=200_000)
    agreement = create_active_agreement(api, freight_subsidy_pool_cents=500_000)
    awarded, _bid = setup_awarded_load(
        api, agreement["id"], member, distance_miles=1700, lot_code="LOT-1700",
        can_self_transport=False,
    )
    decided = record_freight_decision(api, awarded["id"], decision="COVERED")

    # raw = ceil(314500*1.00) = 314500, uplift = ceil(314500*0.15) = 47175,
    # sum 361675 is capped by the 250000 per-load maximum.
    assert decided["freight_subsidy_cents"] == 250_000
    assert decided["member_freight_due_cents"] == 64_500
    assert decided["freight_decision"] == "COVERED"

    agreement_after = validate_success(api.get_donor_agreement(agreement["id"], ADMIN), 200)
    assert agreement_after["freight_subsidy_used_cents"] == 250_000


def test_remote_uplift_applies_at_the_400_mile_threshold(api):
    """PRD §3.6: "Otherwise the share is set by the member's `transport_ability`:
    30 percent for a `NATIONAL` carrier, 55 percent for `REGIONAL`, 75 percent for
    `LOCAL` and the full 100 percent for a member with `NONE`."
    PRD §3.6: "When the member cannot self-transport, the haul is at least 400
    miles, and the member's `transport_ability` is `NONE` or `LOCAL`, an additional
    uplift of 15 percent of the base is computed and rounded up to the next whole
    cent."

    Design: Difficulty/combinatorial_formula/freight_subsidy_nested_caps_on_remote_member
    """
    member = create_certified_member_with_shares(api, transport_ability="LOCAL")
    agreement = create_active_agreement(api, freight_subsidy_pool_cents=500_000)
    awarded, _bid = setup_awarded_load(
        api, agreement["id"], member, distance_miles=400, lot_code="LOT-400",
        can_self_transport=False,
    )
    decided = record_freight_decision(api, awarded["id"], decision="COVERED")

    # base = 400 * 185 = 74000; ceil(0.75*base) = 55500, ceil(0.15*base) = 11100.
    assert decided["freight_subsidy_cents"] == 66_600
    assert decided["member_freight_due_cents"] == 7_400
    assert decided["freight_subsidy_cents"] == expected_freight_subsidy(
        400, "LOCAL", False, 500_000
    )


def test_declined_freight_unwinds_award_and_refunds_shares(api):
    """PRD §3.6: "A `DECLINED` outcome for a member that cannot self-transport does
    not merely record a refusal; it unwinds the award."
    PRD §3.6: "The load returns to `BIDDING`, `awarded_bid_id` and
    `awarded_member_id` are cleared to null, `freight_decision` returns to
    `PENDING`, `freight_subsidy_cents` is zeroed, and `member_freight_due_cents` is
    zeroed"

    Design: Difficulty/compensating_invariant/share_balance_conserved_across_award_and_refund
    """
    member = create_certified_member_with_shares(api, transport_ability="LOCAL")
    agreement = create_active_agreement(api, freight_subsidy_pool_cents=500_000)
    awarded, bid = setup_awarded_load(
        api, agreement["id"], member, distance_miles=20, lot_code="LOT-12",
        can_self_transport=False,
    )
    reverted = record_freight_decision(api, awarded["id"], decision="DECLINED")

    assert reverted["status"] == "BIDDING"
    assert reverted["awarded_bid_id"] is None
    assert reverted["awarded_member_id"] is None
    assert reverted["freight_decision"] == "PENDING"
    assert reverted["freight_subsidy_cents"] == 0
    assert reverted["member_freight_due_cents"] == 0

    bid_after = validate_success(api.get_bid(bid["id"], ADMIN), 200)
    assert bid_after["bid_status"] == "REJECTED"
    assert bid_after["rejection_reason"] == "FREIGHT_DECLINED"


def test_ledger_reconstructs_balance_after_award_and_refund(api):
    """PRD §3.6: "The winning bid becomes `REJECTED` with `rejection_reason`
    `FREIGHT_DECLINED`, and the member's spend is returned by an `AWARD_REFUND`
    ledger entry of the positive `shares_offered` amount, which restores the
    balance to its pre-award value and decrements the member's `active_bid_count`."
    PRD §2.8: "a cascade never silently discards value — every share that was held
    is released by an explicit ledger row, so the sum of a member's ledger always
    reconstructs its balance."

    Design: Difficulty/compensating_invariant/share_balance_conserved_across_award_and_refund
    """
    member = create_certified_member_with_shares(api, transport_ability="LOCAL")
    agreement = create_active_agreement(api, freight_subsidy_pool_cents=500_000)
    awarded, _bid = setup_awarded_load(
        api, agreement["id"], member, distance_miles=20, lot_code="LOT-12",
        can_self_transport=False,
    )
    record_freight_decision(api, awarded["id"], decision="DECLINED")

    member_after = validate_success(api.get_member(member["id"], ADMIN), 200)
    assert member_after["share_balance"] == 100_000
    assert member_after["active_bid_count"] == 0
    assert member_after["share_reserved"] == 0

    ledger = validate_success(api.list_member_ledger(member["id"], ADMIN), 200)
    types = [entry["entry_type"] for entry in ledger]
    amounts = {entry["entry_type"]: entry["amount"] for entry in ledger}
    assert types == ["GRANT", "BID_HOLD", "BID_RELEASE", "AWARD_DEBIT", "AWARD_REFUND"]
    assert amounts["BID_HOLD"] == -400
    assert amounts["BID_RELEASE"] == 400
    assert amounts["AWARD_DEBIT"] == -400
    assert amounts["AWARD_REFUND"] == 400
    assert_ledger_reconciles(api, member_after, ADMIN)


def test_freight_decision_rejected_when_pool_below_minimum(api):
    """PRD §3.6: "When the request asks the network to cover a member that cannot
    self-transport, the agreement's remaining pool must be at least the
    5,000-cent minimum grantable subsidy, or the request is rejected with
    `ERR_SUBSIDY_POOL_EXHAUSTED`."

    Design: Corner/errors/freight_subsidy_pool_below_minimum_returns_409
    """
    member = create_certified_member_with_shares(api, transport_ability="LOCAL")
    agreement = create_active_agreement(api, freight_subsidy_pool_cents=1_000)
    awarded, _bid = setup_awarded_load(
        api, agreement["id"], member, distance_miles=620, lot_code="LOT-THIN",
        can_self_transport=False,
    )

    res = api.record_freight_decision(awarded["id"], {"decision": "COVERED"}, ADMIN)
    validate_error(res, ApiErrorId.ERR_SUBSIDY_POOL_EXHAUSTED)

    after = validate_success(api.get_load(awarded["id"], ADMIN), 200)
    assert after["freight_decision"] == "PENDING"
    assert after["freight_subsidy_cents"] == 0
