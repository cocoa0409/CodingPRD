"""Boundary precision on a scalar threshold and on a collection-derived one.

The parity multiplier comparison is strict, and the capacity comparison is
likewise strict, so an implementation that uses `>=` in either place fails.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    build_catalog_scenario,
    create_entry,
    create_region,
    create_subscriber,
    create_tier,
    open_subscription,
    publish_entry,
    set_clock,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_multiplier_of_exactly_one_and_a_half_keeps_the_raw_multiplier(api):
    """PRD §3.7: "The comparison against 1.50 is strict, so a region sitting at
    exactly 1.50 uses its raw multiplier and does not take the blend."
    PRD §3.7: "the regional monthly price is the tier's global default
    multiplied by that final multiplier, rounded half up to two decimal
    places."

    Design: Difficulty/boundary_precision_check/parity_multiplier_threshold_is_strictly_greater
    """
    set_clock(api, "2026-09-02T00:00:00Z")
    create_region(api, region_code="NA", currency_code="USD", price_multiplier=1.50)
    create_region(api, region_code="EU", currency_code="EUR", price_multiplier=1.60)
    create_tier(api, monthly_price_cents=1000)

    na_subscriber = create_subscriber(api, email="na_edge@example.com",
                                      display_name="NA Edge", home_region_code="NA")
    eu_subscriber = create_subscriber(api, email="eu_edge@example.com",
                                      display_name="EU Edge", home_region_code="EU")

    na_sub = validate_success(
        api.create_subscription(
            {"subscriber_id": na_subscriber["id"], "tier_code": "PREMIUM",
             "billing_period": "MONTHLY"},
            ADMIN,
        )
    , expected_status=201)
    assert na_sub["monthly_bill_cents"] == pytest.approx(1500.00, abs=0.01), \
        "1000 times the raw 1.50 multiplier"
    assert na_sub["unpaid_months"] == 1, "a MONTHLY cadence starts one month outstanding"

    eu_sub = validate_success(
        api.create_subscription(
            {"subscriber_id": eu_subscriber["id"], "tier_code": "PREMIUM",
             "billing_period": "MONTHLY"},
            ADMIN,
        )
    , expected_status=201)
    assert eu_sub["monthly_bill_cents"] == pytest.approx(1440.00, abs=0.01), \
        "1.60 blends to round_half_up(1.60 * 0.90, 4) == 1.4400, then 1000 * 1.44"
    assert eu_sub["monthly_bill_cents"] < na_sub["monthly_bill_cents"], \
        "the blended region bills less even though its multiplier is larger"

    reread = validate_success(api.get_region("NA", ADMIN))
    assert reread["price_multiplier"] == pytest.approx(1.50, abs=0.0001), \
        "the blend is computed per read and never written back"

    eu_reread = validate_success(api.get_region("EU", ADMIN))
    assert eu_reread["price_multiplier"] == pytest.approx(1.60, abs=0.0001), \
        "the stored multiplier is never mutated by the pricing calculation"


def _capacity_scenario(api):
    """JP at ceiling 400 with one long-standing and two fresh entries.

    Entry A was added 2026-09-02, so by 2026-09-20 it is past its fourteen-day
    launch window. Entries B and C were added on 2026-09-20 and are still inside
    theirs. Entry D is planned but not published.
    """
    sc = build_catalog_scenario(api)
    create_region(api, region_code="JP", currency_code="JPY", price_multiplier=1.10,
                  availability_ceiling_titles=400, catalog_tier_floor="ESSENTIAL")

    def _plan(popularity):
        return create_entry(api, sc.title["id"], region_code="JP",
                            removal_date="2027-03-31T00:00:00Z",
                            release_class="CATALOG_ADD",
                            popularity_index_cents=popularity,
                            popularity_index_cents_30d_avg=popularity)

    entry_a = _plan(6000)
    publish_entry(api, entry_a["id"])
    set_clock(api, "2026-09-20T00:00:00Z")
    entry_b = publish_entry(api, _plan(8000)["id"])
    entry_c = publish_entry(api, _plan(4000)["id"])
    entry_d = _plan(2000)

    sc.entry_a, sc.entry_b, sc.entry_c, sc.entry_d = entry_a, entry_b, entry_c, entry_d
    return sc


def test_capacity_sits_within_bounds_before_the_fourth_entry_arrives(api):
    """PRD §3.7: "On the supply side, usable slots are the region's
    `availability_ceiling_titles` multiplied by 30".
    PRD §3.7: "An entry counts as a launch entry while the clock is within
    fourteen days of its `actual_add_date`".

    Design: Difficulty/boundary_precision_check/cloud_capacity_over_capacity_boundary_on_a_different_metric
    """
    sc = _capacity_scenario(api)

    region = validate_success(api.get_region("JP", ADMIN))
    assert region["capacity_usable_slots"] == pytest.approx(12000.00, abs=0.01), \
        "the JP ceiling of 400 titles times thirty slots per ceiling unit"
    # Base slots: (6000 + 8000 + 4000) * 0.5 == 9000.
    # Launch spikes: only entries B and C are inside their window,
    # (8000 + 4000) * 0.5 * 0.40 == 2400.
    # Region overhead: 200.
    assert region["capacity_required_slots"] == pytest.approx(11600.00, abs=0.01)
    assert region["capacity_status"] == "WITHIN_CAPACITY", \
        "11600.00 is not strictly greater than the 12000.00 usable slots"
    assert region["capacity_utilization_pct"] == pytest.approx(96.67, abs=0.01)
    assert region["capacity_deficit_slots"] == pytest.approx(-400.00, abs=0.01), \
        "a negative deficit means headroom"

    na = validate_success(api.get_region("NA", ADMIN))
    assert na["capacity_status"] == "WITHIN_CAPACITY"


def test_one_more_launch_entry_tips_the_region_over_capacity(api):
    """PRD §3.7: "The region's `capacity_status` reads `OVER_CAPACITY` when the
    raw requirement is strictly greater than the usable slots, and
    `WITHIN_CAPACITY` otherwise".
    PRD §2.7: "any request that would create or publish catalogue membership
    while the logical clock falls inside an `ACTIVE` maintenance window of the
    target region is rejected".

    Design: Difficulty/boundary_precision_check/cloud_capacity_over_capacity_boundary_on_a_different_metric
    """
    sc = _capacity_scenario(api)
    before = validate_success(api.get_region("JP", ADMIN))

    validate_success(api.publish_catalog_entry(sc.entry_d["id"], ADMIN))

    after = validate_success(api.get_region("JP", ADMIN))
    assert after["capacity_required_slots"] == pytest.approx(
        before["capacity_required_slots"] + 1400.00, abs=0.01
    ), "the new entry contributes base slots 1000.00 plus a launch spike 400.00"
    assert after["capacity_required_slots"] == pytest.approx(13000.00, abs=0.01)
    assert after["capacity_status"] == "OVER_CAPACITY", \
        "the requirement now strictly exceeds the usable slots"
    assert after["capacity_deficit_slots"] == pytest.approx(1000.00, abs=0.01)

    na = validate_success(api.get_region("NA", ADMIN))
    assert na["capacity_status"] == "WITHIN_CAPACITY", \
        "the boundary is regional, not global"