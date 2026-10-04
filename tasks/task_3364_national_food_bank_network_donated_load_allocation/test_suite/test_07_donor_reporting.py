"""Donor-facing poundage reporting, agreement configuration, and list queries."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_agreement,
    create_certified_member_with_shares,
    create_load,
    get_success_data,
    make_member_headers,
    setup_delivered_load,
    setup_two_member_epoch,
    submit_bid,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def _deliver_two_loads(api, member, agreement):
    """Deliver 1000 lbs and 500 lbs under one agreement (factor 1.2)."""
    first, _ = setup_delivered_load(
        api, agreement["id"], member, weight_lbs=1_000, lot_code="LOT-1000",
        distance_miles=120, window_start="2026-09-03T08:00:00Z",
        window_end="2026-09-03T12:00:00Z",
    )
    second, _ = setup_delivered_load(
        api, agreement["id"], member, weight_lbs=500, lot_code="LOT-500",
        distance_miles=120, window_start="2026-09-04T08:00:00Z",
        window_end="2026-09-04T12:00:00Z",
    )
    return first, second


def test_canonical_poundage_summary_floors_each_load(api):
    """PRD §3.7.1: "The canonical computation floors each load's meals before
    summing: for every qualifying load, `delivered_lbs` is divided by the
    agreement's `meal_equivalency_factor` and floored to a whole number of meals,
    and those per-load meal counts are then added together."

    Design: Difficulty/dual_variant_calc/meal_equivalency_per_load_vs_sum_then_divide
    """
    member = create_certified_member_with_shares(api)
    agreement = create_active_agreement(
        api, donor_name="Prairie Pantry Retail", donor_type="RETAILER",
        product_category="DRY_GOODS", committed_lbs=200_000,
        freight_subsidy_pool_cents=100_000, meal_equivalency_factor=1.2,
    )
    _deliver_two_loads(api, member, agreement)

    summary = validate_success(
        api.get_poundage_summary(agreement["id"], ADMIN), 200
    )
    assert summary["total_lbs"] == 1_500
    assert summary["delivered_load_count"] == 2
    # floor(1000/1.2) + floor(500/1.2) = 833 + 416 = 1249
    assert summary["total_meals"] == 1_249


def test_sum_then_divide_preserves_per_load_remainders(api):
    """PRD §3.7.1: "The request accepts an optional `rounding_basis`; when it is
    set to `SUM_THEN_DIVIDE`, the computation instead sums the pounds first and
    divides once — `total_lbs` divided by the agreement's factor, floored — so
    that the remainders discarded by the canonical per-load flooring are
    preserved."

    Design: Difficulty/dual_variant_calc/meal_equivalency_per_load_vs_sum_then_divide
    """
    member = create_certified_member_with_shares(api)
    agreement = create_active_agreement(
        api, donor_name="Prairie Pantry Retail", donor_type="RETAILER",
        product_category="DRY_GOODS", committed_lbs=200_000,
        freight_subsidy_pool_cents=100_000, meal_equivalency_factor=1.2,
    )
    _deliver_two_loads(api, member, agreement)

    canonical = validate_success(api.get_poundage_summary(agreement["id"], ADMIN), 200)
    alternate = validate_success(
        api.get_poundage_summary(agreement["id"], ADMIN,
                                 params={"rounding_basis": "SUM_THEN_DIVIDE"}),
        200,
    )
    # floor(1500/1.2) = 1250, one meal more than the per-load flooring.
    assert alternate["total_meals"] == 1_250
    assert alternate["total_lbs"] == 1_500
    assert canonical["total_meals"] != alternate["total_meals"]


def test_poundage_summary_excludes_cancelled_loads(api):
    """PRD §3.7.1: "The population it summarizes is the agreement's loads that
    reached `DELIVERED` with a positive `delivered_lbs`; loads that were cancelled,
    and loads whose product was recalled, are excluded from the rollup entirely."

    Design: Corner/calculations/poundage_summary_excludes_cancelled_loads
    """
    member = create_certified_member_with_shares(api)
    agreement = create_active_agreement(api)

    setup_delivered_load(
        api, agreement["id"], member, weight_lbs=1_200, lot_code="LOT-D1",
        distance_miles=150, window_start="2026-09-03T08:00:00Z",
        window_end="2026-09-03T12:00:00Z",
    )
    cancelled_load = create_load(api, agreement["id"], weight_lbs=500,
                                 lot_code="LOT-D2", distance_miles=150)
    validate_success(api.cancel_load(cancelled_load["id"], ADMIN), 200)

    summary = validate_success(api.get_poundage_summary(agreement["id"], ADMIN), 200)
    assert summary["total_lbs"] == 1_200
    assert summary["delivered_load_count"] == 1
    assert summary["total_meals"] == 1_000


def test_donor_agreement_round_trips_stored_configuration(api):
    """PRD §3.3: "The `meal_equivalency_factor`, the pounds-per-meal divisor used
    for that donor's reporting, is optional and defaults to 1.2; when supplied it
    must be strictly positive."
    PRD §3.3: "A new agreement starts in `DRAFT` with `freight_subsidy_used_cents`
    at zero, and only becomes usable when an administrator activates it: activation
    moves a `DRAFT` or a `SUSPENDED` agreement to `ACTIVE` and increments its
    `version`."

    Design: Corner/endpoints/donor_agreement_get_round_trips_stored_configuration
    """
    agreement = create_active_agreement(
        api, donor_name="Midwest Mills Co", product_category="DRY_GOODS",
        committed_lbs=500_000, freight_subsidy_pool_cents=500_000,
    )
    fetched = validate_success(api.get_donor_agreement(agreement["id"], ADMIN), 200)
    assert fetched["donor_name"] == "Midwest Mills Co"
    assert fetched["product_category"] == "DRY_GOODS"
    assert fetched["status"] == "ACTIVE"
    assert fetched["freight_subsidy_used_cents"] == 0
    assert fetched["meal_equivalency_factor"] == pytest.approx(1.2, abs=0.0001)
    assert fetched["committed_lbs"] == 500_000


def test_bid_list_reports_total_count_and_has_more(api):
    """PRD §2.3: "List responses place `limit`, `offset`, `total_count` and
    `has_more` in the `meta` object alongside the standard request identifiers,
    where `total_count` is the size of the full result set ignoring pagination and
    `has_more` indicates whether further items remain beyond the returned window."

    Design: Corner/entities/bid_list_honors_pagination_and_total_count
    """
    m1, m2 = setup_two_member_epoch(api)
    agreement = create_active_agreement(api)
    load = create_load(api, agreement["id"])
    bidding = validate_success(api.post_load(load["id"], ADMIN), 200)

    submit_bid(api, bidding, m1, shares_offered=400, preference_rank=1)
    fresh = get_success_data(api.get_load(bidding["id"], ADMIN))
    submit_bid(api, fresh, m2, shares_offered=300, preference_rank=2)

    data, meta = validate_paginated(
        api.list_bids(ADMIN, params={"load_id": load["id"], "limit": 1, "offset": 0})
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert len(data) == 1
    assert data[0]["load_id"] == load["id"]


def test_member_cannot_create_donor_agreement(api):
    """PRD §2.1: "A request whose role is valid but is not authorized for the
    operation it targets is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/member_cannot_create_donor_agreement
    """
    member = create_certified_member_with_shares(api)
    res = api.create_donor_agreement(
        {"donor_name": "Rogue Member Deal", "donor_type": "RETAILER",
         "product_category": "DRY_GOODS", "committed_lbs": 1_000,
         "freight_subsidy_pool_cents": 5_000},
        make_member_headers(member["id"]),
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)
