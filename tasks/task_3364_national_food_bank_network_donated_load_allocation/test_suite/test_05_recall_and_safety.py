"""Product safety: recall tracing, holds, and the orthogonal safety dimension."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_recall,
    assert_recall_hold,
    create_active_agreement,
    create_bidding_load,
    create_certified_member,
    create_certified_member_with_shares,
    create_load,
    create_loads_sharing_lot,
    create_recall,
    get_success_data,
    make_member_headers,
    resolve_recall,
    setup_awarded_load,
    setup_load_with_bid,
    submit_bid,
    trace_recall,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_trace_counts_matches_and_held_pounds(api):
    """PRD §3.8: "A matched load that has not yet been delivered and weighs at
    least 500 pounds receives a `RecallHold` row in `ACTIVE` status; a matched
    load that has not been delivered and weighs less than 500 pounds is counted as
    traced but is not held, because the network does not open a quarantine case
    over a partial pallet."
    PRD §3.8: "Finally the recall's `held_lbs` is set to the sum of `weight_lbs`
    across all of its `ACTIVE` holds, and the recall moves to `TRACING`."

    Design: Corner/calculations/recall_trace_counts_matches_and_held_pounds
    """
    agreement = create_active_agreement(
        api, donor_name="Valley Protein Partners", donor_type="DISTRIBUTOR",
        product_category="FROZEN_PROTEIN", committed_lbs=400_000,
        freight_subsidy_pool_cents=150_000,
    )
    loads = create_loads_sharing_lot(
        api, agreement["id"], weights=[800, 600, 300], lot_code="LOT-RC",
        category="FROZEN_PROTEIN", storage_type="FROZEN", post=False,
        distance_miles=260,
    )

    recall = create_recall(api, agreement["id"], lot_code="LOT-RC",
                           product_category="FROZEN_PROTEIN", affected_lbs=1_700)
    traced = trace_recall(api, recall["id"])
    assert_recall(traced)
    assert traced["traced_load_count"] == 3
    assert traced["held_lbs"] == 1_400
    assert traced["recall_status"] == "TRACING"

    statuses = [
        validate_success(api.get_load(load["id"], ADMIN), 200)["safety_status"]
        for load in loads
    ]
    assert statuses == ["HELD", "HELD", "CLEAR"]


def test_first_recall_runs_open_tracing_resolved(api):
    """PRD §3.8: "if no recall for the same agreement and the same lot code
    exists, the new row opens in `OPEN`;"
    PRD §3.8: "Every `ACTIVE` hold belonging to the recall is set to `RELEASED`,
    and each affected load that was `HELD` and has no other recall's `ACTIVE` hold
    upon it returns to `CLEAR`."

    Design: Difficulty/non_linear_state_machine/product_recall_resolved_then_reopened_cycle
    """
    agreement = create_active_agreement(
        api, donor_name="Great Lakes Creamery", product_category="DAIRY",
        committed_lbs=300_000, freight_subsidy_pool_cents=120_000,
    )
    load_800 = create_load(api, agreement["id"], product_category="DAIRY",
                           storage_type="REFRIGERATED", weight_lbs=800,
                           lot_code="LOT-77", distance_miles=210)
    load_400 = create_load(api, agreement["id"], product_category="DAIRY",
                           storage_type="REFRIGERATED", weight_lbs=400,
                           lot_code="LOT-88", distance_miles=210)

    recall = create_recall(api, agreement["id"], lot_code="LOT-77",
                           product_category="DAIRY", affected_lbs=800)
    assert recall["recall_status"] == "OPEN"

    traced = trace_recall(api, recall["id"])
    assert traced["recall_status"] == "TRACING"
    assert traced["traced_load_count"] == 1
    assert traced["held_lbs"] == 800

    resolved = resolve_recall(api, recall["id"])
    assert resolved["recall_status"] == "RESOLVED"
    assert resolved["held_lbs"] == 0

    assert validate_success(api.get_load(load_800["id"], ADMIN), 200)["safety_status"] == "CLEAR"
    assert validate_success(api.get_load(load_400["id"], ADMIN), 200)["safety_status"] == "CLEAR"


def test_second_recall_for_same_lot_opens_reopened(api):
    """PRD §3.8: "if a recall for that agreement and lot already exists in any
    state — including one that was already resolved — the new row is created
    directly in `REOPENED` and the earlier row is left completely untouched."

    Design: Difficulty/non_linear_state_machine/product_recall_resolved_then_reopened_cycle
    """
    agreement = create_active_agreement(
        api, donor_name="Great Lakes Creamery", product_category="DAIRY",
        committed_lbs=300_000, freight_subsidy_pool_cents=120_000,
    )
    create_load(api, agreement["id"], product_category="DAIRY",
                storage_type="REFRIGERATED", weight_lbs=800, lot_code="LOT-77",
                distance_miles=210)

    first = create_recall(api, agreement["id"], lot_code="LOT-77",
                          product_category="DAIRY", affected_lbs=800)
    trace_recall(api, first["id"])
    resolve_recall(api, first["id"])

    second = create_recall(api, agreement["id"], lot_code="LOT-77",
                           product_category="DAIRY", affected_lbs=800)
    assert second["recall_status"] == "REOPENED"

    first_after = validate_success(
        api.list_agreement_recalls(agreement["id"], ADMIN), 200
    )
    first_row = [r for r in first_after if r["id"] == first["id"]][0]
    assert first_row["recall_status"] == "RESOLVED"

    traced = trace_recall(api, second["id"])
    assert traced["recall_status"] == "TRACING"
    assert traced["traced_load_count"] == 1


def test_trace_holds_only_loads_at_or_above_500_lbs(api):
    """PRD §3.8: "A matched load that has not yet been delivered and weighs at
    least 500 pounds receives a `RecallHold` row in `ACTIVE` status; a matched
    load that has not been delivered and weighs less than 500 pounds is counted as
    traced but is not held, because the network does not open a quarantine case
    over a partial pallet."

    Design: Difficulty/boundary_precision_check/min_hold_lbs_500_boundary_on_recall_trace
    """
    agreement = create_active_agreement(
        api, donor_name="Heartland Bakeries", product_category="BAKERY",
        committed_lbs=100_000, freight_subsidy_pool_cents=80_000,
    )
    load_500 = create_load(api, agreement["id"], product_category="BAKERY",
                           storage_type="DRY", weight_lbs=500, lot_code="LOT-77",
                           distance_miles=90)
    load_499 = create_load(api, agreement["id"], product_category="BAKERY",
                           storage_type="DRY", weight_lbs=499, lot_code="LOT-77",
                           distance_miles=90)

    recall = create_recall(api, agreement["id"], lot_code="LOT-77",
                           product_category="BAKERY", affected_lbs=999)
    traced = trace_recall(api, recall["id"])

    assert traced["traced_load_count"] == 2
    assert traced["held_lbs"] == 500
    assert validate_success(api.get_load(load_500["id"], ADMIN), 200)["safety_status"] == "HELD"
    assert validate_success(api.get_load(load_499["id"], ADMIN), 200)["safety_status"] == "CLEAR"


def test_exactly_one_active_hold_created_on_the_boundary_load(api):
    """PRD §3.8: "A matched load that has not yet been delivered and weighs at
    least 500 pounds receives a `RecallHold` row in `ACTIVE` status; a matched
    load that has not been delivered and weighs less than 500 pounds is counted as
    traced but is not held, because the network does not open a quarantine case
    over a partial pallet."

    Design: Difficulty/boundary_precision_check/min_hold_lbs_500_boundary_on_recall_trace
    """
    agreement = create_active_agreement(
        api, donor_name="Heartland Bakeries", product_category="BAKERY",
        committed_lbs=100_000, freight_subsidy_pool_cents=80_000,
    )
    load_500 = create_load(api, agreement["id"], product_category="BAKERY",
                           storage_type="DRY", weight_lbs=500, lot_code="LOT-77",
                           distance_miles=90)
    create_load(api, agreement["id"], product_category="BAKERY",
                storage_type="DRY", weight_lbs=499, lot_code="LOT-77",
                distance_miles=90)

    recall = create_recall(api, agreement["id"], lot_code="LOT-77",
                           product_category="BAKERY", affected_lbs=999)
    trace_recall(api, recall["id"])

    holds, meta = validate_paginated(
        api.list_recall_holds(ADMIN, params={"recall_id": recall["id"]})
    )
    assert meta["total_count"] == 1
    assert holds[0]["load_id"] == load_500["id"]
    assert holds[0]["hold_status"] == "ACTIVE"
    assert_recall_hold(holds[0])


def test_trace_holds_all_matching_pounds(api):
    """PRD §3.8: "The number of matched loads becomes the recall's
    `traced_load_count`."
    PRD §3.8: "Finally the recall's `held_lbs` is set to the sum of `weight_lbs`
    across all of its `ACTIVE` holds, and the recall moves to `TRACING`."

    Design: Difficulty/compensating_invariant/agreement_poundage_conserved_across_hold_and_release
    """
    agreement = create_active_agreement(
        api, donor_name="Valley Protein Partners", donor_type="DISTRIBUTOR",
        product_category="FROZEN_PROTEIN", committed_lbs=400_000,
        freight_subsidy_pool_cents=150_000,
    )
    load_800 = create_load(api, agreement["id"], product_category="FROZEN_PROTEIN",
                           storage_type="FROZEN", weight_lbs=800, lot_code="LOT-77",
                           distance_miles=260)
    load_500 = create_load(api, agreement["id"], product_category="FROZEN_PROTEIN",
                           storage_type="FROZEN", weight_lbs=500, lot_code="LOT-77",
                           distance_miles=260)
    validate_success(api.post_load(load_800["id"], ADMIN), 200)

    recall = create_recall(api, agreement["id"], lot_code="LOT-77",
                           product_category="FROZEN_PROTEIN", affected_lbs=1_300)
    traced = trace_recall(api, recall["id"])

    assert traced["traced_load_count"] == 2
    assert traced["held_lbs"] == 1_300
    assert validate_success(api.get_load(load_800["id"], ADMIN), 200)["safety_status"] == "HELD"
    assert validate_success(api.get_load(load_500["id"], ADMIN), 200)["safety_status"] == "HELD"


def test_resolve_releases_holds_and_clears_loads(api):
    """PRD §3.8: "Every `ACTIVE` hold belonging to the recall is set to
    `RELEASED`, and each affected load that was `HELD` and has no other recall's
    `ACTIVE` hold upon it returns to `CLEAR`."
    PRD §3.8: "The recall's `held_lbs` drops to zero and its `recall_status`
    becomes `RESOLVED`."

    Design: Difficulty/compensating_invariant/agreement_poundage_conserved_across_hold_and_release
    """
    agreement = create_active_agreement(
        api, donor_name="Valley Protein Partners", donor_type="DISTRIBUTOR",
        product_category="FROZEN_PROTEIN", committed_lbs=400_000,
        freight_subsidy_pool_cents=150_000,
    )
    load_800 = create_load(api, agreement["id"], product_category="FROZEN_PROTEIN",
                           storage_type="FROZEN", weight_lbs=800, lot_code="LOT-77",
                           distance_miles=260)
    load_500 = create_load(api, agreement["id"], product_category="FROZEN_PROTEIN",
                           storage_type="FROZEN", weight_lbs=500, lot_code="LOT-77",
                           distance_miles=260)
    validate_success(api.post_load(load_800["id"], ADMIN), 200)

    recall = create_recall(api, agreement["id"], lot_code="LOT-77",
                           product_category="FROZEN_PROTEIN", affected_lbs=1_300)
    trace_recall(api, recall["id"])
    resolved = resolve_recall(api, recall["id"])

    assert resolved["held_lbs"] == 0
    assert resolved["recall_status"] == "RESOLVED"
    assert validate_success(api.get_load(load_800["id"], ADMIN), 200)["safety_status"] == "CLEAR"
    assert validate_success(api.get_load(load_500["id"], ADMIN), 200)["safety_status"] == "CLEAR"

    holds, meta = validate_paginated(
        api.list_recall_holds(ADMIN, params={"recall_id": recall["id"]})
    )
    assert meta["total_count"] == 2
    assert {hold["hold_status"] for hold in holds} == {"RELEASED"}


def test_declined_freight_returns_load_to_bidding(api):
    """PRD §3.6: "The load returns to `BIDDING`, `awarded_bid_id` and
    `awarded_member_id` are cleared to null, `freight_decision` returns to
    `PENDING`, `freight_subsidy_cents` is zeroed, and `member_freight_due_cents` is
    zeroed"

    Design: Difficulty/non_linear_state_machine/donated_load_parallel_dimensions_and_award_cycle
    """
    member = create_certified_member_with_shares(api, transport_ability="LOCAL")
    agreement = create_active_agreement(api, freight_subsidy_pool_cents=500_000)
    awarded, bid = setup_awarded_load(
        api, agreement["id"], member, distance_miles=620, lot_code="LOT-77",
        can_self_transport=False,
    )

    reverted = validate_success(
        api.record_freight_decision(awarded["id"], {"decision": "DECLINED"}, ADMIN), 200
    )
    assert reverted["status"] == "BIDDING"
    assert reverted["awarded_bid_id"] is None
    assert reverted["freight_decision"] == "PENDING"

    bid_after = validate_success(api.get_bid(bid["id"], ADMIN), 200)
    assert bid_after["bid_status"] == "REJECTED"
    assert bid_after["rejection_reason"] == "FREIGHT_DECLINED"


def test_safety_dimension_gates_bidding_independently_of_status(api):
    """PRD §2.11: "The two dimensions are orthogonal: a load can be `IN_TRANSIT`
    and `HELD`, and a load can be `DELIVERED` and `RECALLED`."
    PRD §2.9: "`ERR_LOAD_SAFETY_HOLD` (HTTP 409) guards posting, bid creation,
    award and dispatch: the load's `safety_status` must be `CLEAR`, and a `HELD`
    or `RECALLED` load is rejected here even when every other rule would pass."

    Design: Difficulty/non_linear_state_machine/donated_load_parallel_dimensions_and_award_cycle
    """
    member = create_certified_member_with_shares(api, transport_ability="LOCAL")
    agreement = create_active_agreement(api, freight_subsidy_pool_cents=500_000)
    awarded, _bid = setup_awarded_load(
        api, agreement["id"], member, distance_miles=620, lot_code="LOT-77",
        can_self_transport=False,
    )
    validate_success(
        api.record_freight_decision(awarded["id"], {"decision": "DECLINED"}, ADMIN), 200
    )

    recall = create_recall(api, agreement["id"], lot_code="LOT-77",
                           product_category="DRY_GOODS", affected_lbs=40_000)
    traced = trace_recall(api, recall["id"])
    assert traced["recall_status"] == "TRACING"
    assert traced["traced_load_count"] == 1

    held = validate_success(api.get_load(awarded["id"], ADMIN), 200)
    assert held["status"] == "BIDDING"
    assert held["safety_status"] == "HELD"

    res = api.create_bid(
        awarded["id"],
        {"member_id": member["id"], "shares_offered": 100, "preference_rank": 1,
         "can_self_transport": False, "expected_load_version": held["version"]},
        make_member_headers(member["id"]),
    )
    validate_error(res, ApiErrorId.ERR_LOAD_SAFETY_HOLD)


def test_safety_hold_error_wins_over_storage_constraint(api):
    """PRD §2.9: "`ERR_LOAD_SAFETY_HOLD` (HTTP 409) guards posting, bid creation,
    award and dispatch: the load's `safety_status` must be `CLEAR`, and a `HELD`
    or `RECALLED` load is rejected here even when every other rule would pass."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_storage_constraint_on_bid_for_held_load
    """
    member = create_certified_member_with_shares(
        api, storage_capacity_lbs=10_000, refrigerated_capacity_lbs=1_000,
        transport_ability="LOCAL",
    )
    agreement = create_active_agreement(api)
    load = create_bidding_load(api, agreement["id"], weight_lbs=40_000,
                               lot_code="LOT-77")

    recall = create_recall(api, agreement["id"], lot_code="LOT-77",
                           product_category="DRY_GOODS", affected_lbs=40_000)
    trace_recall(api, recall["id"])

    held = validate_success(api.get_load(load["id"], ADMIN), 200)
    assert held["safety_status"] == "HELD"
    assert member["storage_capacity_lbs"] < held["weight_lbs"]

    res = api.create_bid(
        load["id"],
        {"member_id": member["id"], "shares_offered": 100, "preference_rank": 1,
         "can_self_transport": False, "expected_load_version": held["version"]},
        make_member_headers(member["id"]),
    )
    validate_error(res, ApiErrorId.ERR_LOAD_SAFETY_HOLD)


def test_storage_constraint_alone_rejects_bid(api):
    """PRD §2.9: "`ERR_STORAGE_CAPACITY_EXCEEDED` (HTTP 409) guards bid creation
    and award: the load's `weight_lbs` must fit the candidate member's storage for
    the load's `storage_type`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_storage_constraint_on_bid_for_held_load
    """
    member = create_certified_member_with_shares(
        api, storage_capacity_lbs=10_000, refrigerated_capacity_lbs=1_000,
        transport_ability="LOCAL",
    )
    agreement = create_active_agreement(api)
    load = create_bidding_load(api, agreement["id"], weight_lbs=40_000,
                               lot_code="LOT-CLEAR")
    assert load["safety_status"] == "CLEAR"

    res = api.create_bid(
        load["id"],
        {"member_id": member["id"], "shares_offered": 100, "preference_rank": 1,
         "can_self_transport": False, "expected_load_version": load["version"]},
        make_member_headers(member["id"]),
    )
    validate_error(res, ApiErrorId.ERR_STORAGE_CAPACITY_EXCEEDED)
