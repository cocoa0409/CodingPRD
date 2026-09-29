"""Off-season overhaul cost estimation and shop-bay occupancy arithmetic.

The seven-step cost order is pinned because the expedite tier reads the
discounted base, and bay occupancy is tested with a one-day changeover buffer
applied to the requested window only.
"""

from test_helpers import (
    MANAGER,
    api_client,
    assert_work_order,
    assert_work_order_cost_chain,
    factories,
    fixtures,
    validate_error,
    validate_success,
)


def _cyclone_ridge_ready_to_book():
    attraction = fixtures.create_attraction(
        name="Cyclone Ridge",
        park_area="FRONTIER",
        manufacturer="Zierer",
        model_code="TF-24",
        ride_class="THRILL",
        theoretical_hourly_capacity=800,
        min_operators_required=2,
        parts_budget_cents=9000000,
    )
    component = fixtures.create_component(
        attraction["id"],
        name="Main drive gearbox",
        component_type="GEARBOX",
        criticality="SAFETY_CRITICAL",
        ndt_interval_cycles=40000,
        ndt_interval_days=365,
    )
    shop_bay = fixtures.create_shop_bay("Bay 1", 1)
    return {"attraction": attraction, "component": component, "shop_bay": shop_bay}


def test_the_expedite_tier_is_selected_from_the_discounted_base():
    """The tier boundary is tested against the discounted base, not the base total.

    PRD §3.9: "`expedite_pct` is selected from `discounted_base_cents` — **not**
    from `base_total_cents`. When `expedite_requested` is false, `expedite_pct` is
    0. When it is true, `expedite_pct` is 0.12 if `discounted_base_cents` is below
    5,000,000 cents (50,000 dollars), 0.08 if it is below 20,000,000 cents (200,000
    dollars) but not below the first ceiling, and 0.05 otherwise."
    PRD §3.9: "When `off_season` is true, `off_season_discount_cents` is
    `base_total_cents` multiplied by the off-season discount of 6 percent, rounded
    half up to a whole cent".

    Design: Difficulty/combinatorial_formula/overhaul_expedite_tier_selected_from_discounted_base_not_base_total
    """
    bundle = _cyclone_ridge_ready_to_book()

    response = api_client.create_overhaul_work_order(
        factories.create_overhaul_work_order_payload(
            bundle["attraction"]["id"],
            bundle["component"]["id"],
            bundle["shop_bay"]["id"],
            bundle["shop_bay"]["version"],
            window_start_date="2026-11-10",
            window_end_date="2026-11-20",
            parts_subtotal_cents=4500025,
            labor_hours=60,
            expedite_requested=True,
        ),
        MANAGER,
    )
    work_order = validate_success(response, 201)
    assert_work_order(work_order)
    assert_work_order_cost_chain(work_order)

    assert work_order["status"] == "SCHEDULED"
    assert work_order["off_season"] is True
    assert work_order["base_total_cents"] == 5070025
    assert work_order["off_season_discount_cents"] == 304202
    assert work_order["discounted_base_cents"] == 4765823
    assert work_order["expedite_fee_cents"] == 571899
    assert work_order["estimated_total_cents"] == 5337722
    assert work_order["estimated_total_cents"] != 5147089, (
        "selecting the tier from the undiscounted base total would give 5147089"
    )


def test_booking_consumes_a_bay_slot_and_advances_the_bay_version():
    """The booking is the mutation that makes a second planner's read stale.

    PRD §3.9: "Booking succeeds at `status` `SCHEDULED`, increments the bay's
    `booked_order_count` by one, and increments the bay's `version` by one — which
    is precisely why a second planner working from a stale read of the same bay will
    be turned away."
    PRD §3.9: "A new bay begins at `version` 1 with a `booked_order_count` of 0."

    Design: Difficulty/combinatorial_formula/overhaul_expedite_tier_selected_from_discounted_base_not_base_total
    """
    bundle = _cyclone_ridge_ready_to_book()
    assert bundle["shop_bay"]["version"] == 1
    assert bundle["shop_bay"]["booked_order_count"] == 0

    validate_success(
        api_client.create_overhaul_work_order(
            factories.create_overhaul_work_order_payload(
                bundle["attraction"]["id"],
                bundle["component"]["id"],
                bundle["shop_bay"]["id"],
                bundle["shop_bay"]["version"],
                window_start_date="2026-11-10",
                window_end_date="2026-11-20",
                parts_subtotal_cents=4500025,
                labor_hours=60,
                expedite_requested=True,
            ),
            MANAGER,
        ),
        201,
    )

    bay = fixtures.read_shop_bay(bundle["shop_bay"]["id"])
    assert bay["booked_order_count"] == 1
    assert bay["version"] == 2


def _two_units_sharing_one_bay():
    first = fixtures.create_attraction(
        name="Granite Peak Coaster",
        park_area="FRONTIER",
        manufacturer="Vekoma",
        model_code="MK-1100",
        ride_class="THRILL",
        theoretical_hourly_capacity=1000,
        min_operators_required=3,
        parts_budget_cents=7000000,
    )
    first_component = fixtures.create_component(
        first["id"],
        name="Lift chain assembly",
        component_type="LIFT_CHAIN",
        criticality="SAFETY_CRITICAL",
        ndt_interval_cycles=80000,
        ndt_interval_days=365,
    )
    second = fixtures.create_attraction(
        name="Dune Buggies",
        park_area="KIDS_COVE",
        manufacturer="Zamperla",
        model_code="DB-4",
        ride_class="KIDDIE",
        theoretical_hourly_capacity=240,
        min_operators_required=1,
        parts_budget_cents=600000,
    )
    second_component = fixtures.create_component(
        second["id"],
        name="Buggy axle",
        component_type="AXLE",
        criticality="ESSENTIAL",
        ndt_interval_cycles=30000,
        ndt_interval_days=365,
    )
    booked = fixtures.book_work_order(
        first["id"],
        first_component["id"],
        bay_name="Bay 3",
        concurrent_slot_capacity=1,
        window_start_date="2026-11-10",
        window_end_date="2026-11-14",
        parts_subtotal_cents=1000000,
        labor_hours=20,
    )
    return {
        "first": first,
        "first_component": first_component,
        "second": second,
        "second_component": second_component,
        "incumbent": booked["work_order"],
        "shop_bay": booked["shop_bay"],
    }


def test_the_component_installation_check_outranks_the_bay_capacity_conflict():
    """A mismatched component is reported even though the window also collides.

    PRD §3.9: "Three refusals therefore compete on this one operation, and per the
    ladder in §2.6 they resolve in this order: the stale-bay check first with
    `ERR_STALE_SHOP_BAY_VERSION`, then the component-installation check with
    `ERR_COMPONENT_ATTRACTION_MISMATCH`, then the bay-capacity check with
    `ERR_BAY_CAPACITY_CONFLICT`."
    PRD §2.6: "`ERR_COMPONENT_ATTRACTION_MISMATCH` (422) — a supplied component
    identifier names a component installed on a different attraction than the one
    the request targets."

    Design: Difficulty/priority_pair_validation_conflict/overhaul_component_mismatch_priority_12_wins_over_bay_capacity_24
    """
    bundle = _two_units_sharing_one_bay()
    fresh_bay = fixtures.read_shop_bay(bundle["shop_bay"]["id"])

    response = api_client.create_overhaul_work_order(
        factories.create_overhaul_work_order_payload(
            bundle["first"]["id"],
            bundle["second_component"]["id"],
            fresh_bay["id"],
            fresh_bay["version"],
            window_start_date="2026-11-14",
            window_end_date="2026-11-19",
            parts_subtotal_cents=500000,
            labor_hours=10,
        ),
        MANAGER,
    )
    validate_error(response, "ERR_COMPONENT_ATTRACTION_MISMATCH", 422)


def test_the_refused_booking_leaves_the_bay_and_the_incumbent_untouched():
    """A refusal creates no row, consumes no slot and moves no version.

    PRD §2.6: "When a request violates more than one rule, exactly one error is
    returned, and which one is not a matter of implementation convenience."
    PRD §2.9: "`booked_order_count` on a shop bay is the number of overhaul work
    orders for that bay whose `status` is anything other than `RECOMMISSIONED`."

    Design: Difficulty/priority_pair_validation_conflict/overhaul_component_mismatch_priority_12_wins_over_bay_capacity_24
    """
    bundle = _two_units_sharing_one_bay()
    fresh_bay = fixtures.read_shop_bay(bundle["shop_bay"]["id"])

    api_client.create_overhaul_work_order(
        factories.create_overhaul_work_order_payload(
            bundle["first"]["id"],
            bundle["second_component"]["id"],
            fresh_bay["id"],
            fresh_bay["version"],
            window_start_date="2026-11-14",
            window_end_date="2026-11-19",
            parts_subtotal_cents=500000,
            labor_hours=10,
        ),
        MANAGER,
    )

    after = fixtures.read_shop_bay(bundle["shop_bay"]["id"])
    assert after["booked_order_count"] == 1
    assert after["version"] == fresh_bay["version"]

    incumbent = validate_success(
        api_client.get_overhaul_work_order(bundle["incumbent"]["id"], MANAGER)
    )
    assert incumbent["status"] == "SCHEDULED"


def _ironwood_express_with_an_incumbent_booking():
    attraction = fixtures.create_attraction(
        name="Ironwood Express",
        park_area="FRONTIER",
        manufacturer="Vekoma",
        model_code="IE-15",
        ride_class="FAMILY",
        theoretical_hourly_capacity=700,
        min_operators_required=2,
        parts_budget_cents=3000000,
    )
    component = fixtures.create_component(
        attraction["id"],
        name="Transfer table gearbox",
        component_type="GEARBOX",
        criticality="SAFETY_CRITICAL",
        ndt_interval_cycles=70000,
        ndt_interval_days=365,
    )
    booked = fixtures.book_work_order(
        attraction["id"],
        component["id"],
        bay_name="Bay 5",
        concurrent_slot_capacity=1,
        window_start_date="2026-11-10",
        window_end_date="2026-11-14",
        parts_subtotal_cents=200000,
        labor_hours=8,
    )
    return {
        "attraction": attraction,
        "component": component,
        "incumbent": booked["work_order"],
        "shop_bay": booked["shop_bay"],
    }


def test_a_window_one_day_after_the_incumbent_collides_through_the_buffer():
    """The requested window is widened a day at each end before the day-count runs.

    PRD §3.9: "The requested window is widened by one changeover day at each end,
    giving an expanded window that starts one day before `window_start_date` and
    ends one day after `window_end_date`, both endpoints inclusive."
    PRD §3.9: "If the count on any single day already equals or exceeds the bay's
    `concurrent_slot_capacity`, the booking is refused with
    `ERR_BAY_CAPACITY_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/shop_bay_closed_windows_collide_through_the_one_day_changeover_buffer
    """
    bundle = _ironwood_express_with_an_incumbent_booking()
    fresh_bay = fixtures.read_shop_bay(bundle["shop_bay"]["id"])

    response = api_client.create_overhaul_work_order(
        factories.create_overhaul_work_order_payload(
            bundle["attraction"]["id"],
            bundle["component"]["id"],
            fresh_bay["id"],
            fresh_bay["version"],
            window_start_date="2026-11-15",
            window_end_date="2026-11-18",
            parts_subtotal_cents=300000,
            labor_hours=9,
        ),
        MANAGER,
    )
    validate_error(response, "ERR_BAY_CAPACITY_CONFLICT", 409)

    after = fixtures.read_shop_bay(bundle["shop_bay"]["id"])
    assert after["booked_order_count"] == 1
    assert after["version"] == fresh_bay["version"]


def test_a_two_day_gap_clears_the_buffer_and_books_a_second_slot():
    """Existing windows are not themselves widened, so a two-day gap is legal.

    PRD §3.9: "Note the asymmetry deliberately built into this test: the requested
    window is buffered but the existing windows are not, so a new booking is pushed
    away from its neighbours by one day without existing bookings pushing away from
    each other retroactively."
    PRD §3.9: "`off_season` is true when **every** calendar date in the inclusive
    window from `window_start_date` through `window_end_date` falls inside the
    park's off-season span, which runs from the 1st of November in one year through
    the 28th of February in the next".

    Design: Difficulty/resource_temporal_overlap/shop_bay_closed_windows_collide_through_the_one_day_changeover_buffer
    """
    bundle = _ironwood_express_with_an_incumbent_booking()
    fresh_bay = fixtures.read_shop_bay(bundle["shop_bay"]["id"])

    work_order = validate_success(
        api_client.create_overhaul_work_order(
            factories.create_overhaul_work_order_payload(
                bundle["attraction"]["id"],
                bundle["component"]["id"],
                fresh_bay["id"],
                fresh_bay["version"],
                window_start_date="2026-11-16",
                window_end_date="2026-11-19",
                parts_subtotal_cents=300000,
                labor_hours=9,
            ),
            MANAGER,
        ),
        201,
    )
    assert work_order["status"] == "SCHEDULED"
    assert work_order["off_season"] is True

    after = fixtures.read_shop_bay(bundle["shop_bay"]["id"])
    assert after["booked_order_count"] == 2

    incumbent = validate_success(
        api_client.get_overhaul_work_order(bundle["incumbent"]["id"], MANAGER)
    )
    assert incumbent["window_end_date"] == "2026-11-14", (
        "the incumbent window is never widened by a later booking"
    )
