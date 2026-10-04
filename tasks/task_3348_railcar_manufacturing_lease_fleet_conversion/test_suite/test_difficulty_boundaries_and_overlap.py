"""Difficulty queue: boundary precision and temporal overlap geometry.

Four instances, one test each:

* ``boundary_precision_check`` — the mileage-overage clamp at exactly the
  allowance, and the stock-sufficiency test at exactly the requirement.
* ``resource_temporal_overlap`` — the shop line treats touching windows as
  legal, while a placement of the same car demands a one-day gap.
"""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock_to,
    api_client,
    complete_order,
    create_assignment,
    create_lessee_and_contract,
    create_order,
    create_retrofit_program,
    create_return,
    create_work_order,
    get_success_data,
    release_order,
    reserve_order,
    set_clock,
    settle_return,
    setup_catalogue,
    start_production,
    validate_error,
    validate_success,
)

LEASE = TEST_USERS["lease_administrator_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
PORTFOLIO = TEST_USERS["portfolio_manager_headers"]
RETROFIT = TEST_USERS["regulatory_retrofitist_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ─── boundary_precision_check ─────────────────────────

def test_mileage_overage_zero_at_the_allowance_and_twelve_cents_one_mile_over(api):
    """PRD §3.7: "The overage miles are the placement's `mileage_used` minus the
    included miles, or zero when that difference is negative — an overage of
    exactly zero produces a charge of exactly zero."
    PRD §3.7: "The number of days in the placement is the placement's `end_date`
    minus its `start_date`. That figure is divided by thirty and rounded up to a
    whole number to give the number of allowance blocks; the included miles are
    those blocks multiplied by the placement's `mileage_allowance`."
    PRD §3.7: "The charge is the overage miles multiplied by the overage rate of
    12 cents per mile, and it is written to the return's `mileage_overage_cents`
    and to the placement's `mileage_charge_cents`."

    Two identical thirty-day placements straddle the clamp: 1000 miles against a
    1000-mile allowance charges nothing, 1001 miles charges exactly 12 cents.

    Design: Difficulty/boundary_precision_check/boundary_mileage_allowance_exact_vs_one_mile_over
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(
        model_code="MILE-100",
        car_class="HOPPER",
        build_hours=1,
        regulatory_life_years=20,
        line_count_family="MILE_LINE",
        wheelset_part_number="MILE-WS",
        wheelset_unit_cost_cents=200000,
        wheelset_qty_per_car=1,
        wheelset_lead_time_days=10,
        include_coating=False,
        on_hand_qty=10,
    )

    def _retained_car(priority_rank: int, window_start: str, window_end: str):
        order = create_order(
            catalogue,
            quantity=1,
            planned_shop_days=1,
            disposition="RETAINED",
            priority_rank=priority_rank,
            order_date="2026-09-01",
            required_delivery_date="2026-09-20",
        )
        reserve_order(order["id"])
        release_order(order["id"])
        start_production(order["id"], "MILE_LINE", window_start=window_start,
                         window_days=1)
        complete_order(order["id"], completed_qty=1, completion_date=window_end)
        return get_success_data(
            api_client.list_lease_fleet_cars(
                ADMIN, {"production_order_id": order["id"]}
            )
        )[0]

    car_a = _retained_car(1, "2026-09-02", "2026-09-03")
    car_b = _retained_car(2, "2026-09-04", "2026-09-05")

    world = create_lessee_and_contract(
        legal_name="Boundary Mileage Rail Co",
        credit_tier="A",
        utilization_threshold_pct=70,
        credit_ceiling_cents=50000000,
        lease_type="FULL_SERVICE",
        per_diem_rate_cents=1500,
        liability_bearer="LESSOR",
        term_start_date="2026-09-01",
        term_end_date="2027-09-01",
        fleet_car_cap=10,
    )
    lessee, contract = world["lessee"], world["contract"]

    advance_clock_to("2026-09-05T00:00:00Z")
    assignment_a = create_assignment(
        car_a, contract, lessee, start_date="2026-09-05",
        end_date="2026-10-05", mileage_allowance=1000,
    )
    assignment_b = create_assignment(
        car_b, contract, lessee, start_date="2026-09-05",
        end_date="2026-10-05", mileage_allowance=1000,
    )

    # Both placements span 30 days, so each grants exactly one block of 1000
    # included miles.
    advance_clock_to("2026-10-05T00:00:00Z")
    exact = create_return(
        car_a, assignment_a, return_date="2026-10-05",
        mileage_since_last=1000, condition_grade="A",
    )
    assert exact["mileage_overage_cents"] == 0, (
        "1000 miles against a 1000-mile allowance is exactly at the boundary "
        "and charges nothing"
    )

    one_over = create_return(
        car_b, assignment_b, return_date="2026-10-05",
        mileage_since_last=1001, condition_grade="A",
    )
    assert one_over["mileage_overage_cents"] == 12, (
        "one mile past the allowance charges exactly one mile at 12 cents"
    )
    assert one_over["id"] != exact["id"]

    # The comparison is inclusive on the allowance: mileage_used equal to the
    # included miles charges 0, one extra mile charges 12.
    assert one_over["mileage_overage_cents"] - exact["mileage_overage_cents"] == 12


def test_reservation_accepts_stock_exactly_at_requirement_and_rejects_one_short(api):
    """PRD §3.2: "For rows in the `WHEELSET` and `CASTING` classes, the
    component's `on_hand_qty` must be at least the effective per-car quantity
    multiplied by the order's `quantity`, where the effective quantity is the
    endorsed substitute quantity when an `APPROVED` or `APPLIED` endorsement
    covers that row and the row's own `qty_per_car` otherwise; a shortfall on
    any covered row rejects the whole reservation with `ERR_COMPONENT_SHORTAGE`
    (HTTP 409), and the same shortage test guards the approval of a
    substitution endorsement."
    PRD §3.2: "for each covered row, the component's `on_hand_qty` is
    decremented by the effective per-car quantity multiplied by the order
    quantity".

    Two otherwise identical five-car reservations consuming two wheelsets per
    car turn on the inclusive `>=` in the sufficiency test.

    Design: Difficulty/boundary_precision_check/boundary_component_stock_exact_vs_one_short
    """
    set_clock("2026-09-01T00:00:00Z")
    enough = setup_catalogue(
        model_code="STK-EQ-100",
        car_class="BOXCAR",
        build_hours=1,
        regulatory_life_years=15,
        line_count_family="STK_EQ_LINE",
        wheelset_part_number="WS-EQ-1",
        wheelset_unit_cost_cents=200000,
        wheelset_qty_per_car=2,
        wheelset_lead_time_days=10,
        include_coating=False,
        on_hand_qty=10,
    )
    short = setup_catalogue(
        model_code="STK-SH-100",
        car_class="BOXCAR",
        build_hours=1,
        regulatory_life_years=15,
        line_count_family="STK_SH_LINE",
        wheelset_part_number="WS-SH-1",
        wheelset_unit_cost_cents=200000,
        wheelset_qty_per_car=2,
        wheelset_lead_time_days=10,
        include_coating=False,
        on_hand_qty=9,
    )

    order_eq = create_order(
        enough, quantity=5, planned_shop_days=5, disposition="RETAINED",
        priority_rank=1, order_date="2026-09-01",
        required_delivery_date="2026-09-30",
    )
    order_sh = create_order(
        short, quantity=5, planned_shop_days=5, disposition="RETAINED",
        priority_rank=1, order_date="2026-09-01",
        required_delivery_date="2026-09-30",
    )

    # Requirement is qty_per_car 2 * quantity 5 = 10 units.
    committed = validate_success(
        api_client.reserve_components(order_eq["id"], PLANNER, {})
    )
    assert committed["status"] == "COMPONENT_RESERVED"

    drained = get_success_data(
        api_client.get_component(enough["wheelset"]["id"], ADMIN)
    )
    assert drained["on_hand_qty"] == 0, (
        "the boundary case commits all 10 units rather than rejecting"
    )

    rejected = api_client.reserve_components(order_sh["id"], PLANNER, {})
    validate_error(rejected, ApiErrorId.ERR_COMPONENT_SHORTAGE)
    assert rejected.status_code == 409

    untouched = get_success_data(
        api_client.get_component(short["wheelset"]["id"], ADMIN)
    )
    assert untouched["on_hand_qty"] == 9, (
        "a rejected reservation must commit nothing"
    )

    still_draft = get_success_data(
        api_client.get_production_order(order_sh["id"], ADMIN)
    )
    assert still_draft["status"] == "DRAFT", (
        "the rejected reservation must leave no partial state"
    )


# ─── resource_temporal_overlap ────────────────────────

def test_shop_line_accepts_windows_that_touch_but_rejects_any_overlap(api):
    """PRD §2.8: "Shop lines have exclusive occupancy. The window from
    `scheduled_start_date` up to but not including `scheduled_end_date` may not
    collide with any other retrofit work order on the same `shop_line`; a
    colliding window is rejected with `ERR_SHOP_SLOT_OVERLAP` (HTTP 409)."
    PRD §2.8: "Because the interval is half-open, a window that ends exactly
    when another begins is allowed, while any true overlap is not."
    PRD §2.8: "A work order's derived `shop_days` — the difference between its
    scheduled end and start — must equal the program's
    `required_shop_days_per_car`, so the shop occupancy a mandate demands and
    the occupancy a work order books cannot diverge."

    One day of true overlap is rejected; a window that begins exactly when the
    incumbent ends is accepted.

    Design: Difficulty/resource_temporal_overlap/shop_line_half_open_touching_windows_allowed
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(
        model_code="R8A-100",
        car_class="BOXCAR",
        build_hours=10,
        regulatory_life_years=40,
        line_count_family="R8A_LINE",
        wheelset_part_number="R8A-WS",
        wheelset_unit_cost_cents=100000,
        wheelset_qty_per_car=4,
        wheelset_lead_time_days=20,
        include_casting=False,
        include_coating=False,
        on_hand_qty=100,
    )
    world = create_lessee_and_contract(
        legal_name="R8A Rail Leasing Co",
        credit_tier="B",
        utilization_threshold_pct=80,
        credit_ceiling_cents=10000000,
        lease_type="FULL_SERVICE",
        per_diem_rate_cents=5000,
        liability_bearer="LESSOR",
        term_start_date="2026-09-01",
        term_end_date="2027-09-01",
        fleet_car_cap=10,
    )
    lessee, contract = world["lessee"], world["contract"]

    order = create_order(
        catalogue,
        quantity=2,
        planned_shop_days=20,
        disposition="RETAINED",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-09-20",
        lessee_id=lessee["id"],
    )
    assert order["unit_price_cents"] == 875000
    reserve_order(order["id"])
    release_order(order["id"], lease_contract_id=contract["id"])
    start_production(order["id"], "R8A_LINE", window_start="2026-09-05",
                     window_days=20)
    complete_order(order["id"], completed_qty=2, completion_date="2026-09-25")

    cars = get_success_data(
        api_client.list_lease_fleet_cars(
            ADMIN, {"production_order_id": order["id"]}
        )
    )
    assert len(cars) == 2
    car_a, car_b = cars[0], cars[1]
    assert car_a["acquisition_cost_cents"] == 875000

    # Two live cars of this order put 2 * 875000 = 1750000 cents of capital
    # into the lease fleet for the contract.
    refreshed = get_success_data(
        api_client.get_lease_contract(contract["id"], LEASE)
    )
    assert refreshed["capital_allocation_cents"] == 1750000

    program_world = create_retrofit_program(
        catalogue,
        mandate_code="R8A-MANDATE",
        description="Tank car valve retrofit mandate",
        compliance_deadline_date="2026-12-31",
        required_shop_days_per_car=10,
        required_component_id=catalogue["wheelset"]["id"],
    )
    program = program_world["program"]
    assert program["status"] == "PLANNED"

    # Incumbent: car A books [2026-10-01, 2026-10-11) on shop line SHOP-R8A.
    incumbent = create_work_order(
        program, car_a, shop_line="SHOP-R8A",
        scheduled_start_date="2026-10-01",
        scheduled_end_date="2026-10-11",
        component_qty_consumed=1,
    )
    assert incumbent["shop_days"] == 10
    car_a_after = get_success_data(api_client.get_lease_fleet_car(car_a["id"], ADMIN))
    assert car_a_after["status"] == "UNDER_REPAIR"

    # One day of true overlap: max(2026-10-01, 2026-10-10) < min(2026-10-11,
    # 2026-10-20), so the windows share 2026-10-10.
    overlapping = api_client.create_retrofit_work_order(
        {
            "retrofit_program_id": program["id"],
            "lease_fleet_car_id": car_b["id"],
            "shop_line": "SHOP-R8A",
            "scheduled_start_date": "2026-10-10",
            "scheduled_end_date": "2026-10-20",
            "component_qty_consumed": 1,
        },
        PLANNER,
    )
    validate_error(overlapping, ApiErrorId.ERR_SHOP_SLOT_OVERLAP)
    assert overlapping.status_code == 409

    untouched_car = get_success_data(
        api_client.get_lease_fleet_car(car_b["id"], ADMIN)
    )
    assert untouched_car["status"] == "HELD", (
        "the rejected work order must not partially mutate the car"
    )

    # Touching windows: max(2026-10-01, 2026-10-11) is not < min(2026-10-11,
    # 2026-10-21), so the intersection is empty and the booking is legal.
    accepted = create_work_order(
        program, car_b, shop_line="SHOP-R8A",
        scheduled_start_date="2026-10-11",
        scheduled_end_date="2026-10-21",
        component_qty_consumed=1,
    )
    assert accepted["status"] == "SCHEDULED"
    assert accepted["shop_line"] == "SHOP-R8A"
    assert accepted["shop_days"] == 10

    scheduled_car = get_success_data(
        api_client.get_lease_fleet_car(car_b["id"], ADMIN)
    )
    assert scheduled_car["status"] == "UNDER_REPAIR"


def test_placement_needs_two_clear_days_after_the_prior_end_date(api):
    """PRD §3.6: "Placements of the same car are buffered, not merely
    non-overlapping. The half-open interval from `start_date` up to but not
    including `end_date` must not collide with any other placement of the same
    car, and because the fleet requires a one-day buffer between placements, a
    `start_date` that equals a prior `end_date` plus zero days or plus one day
    is also rejected. Every one of those cases is rejected with
    `ERR_ASSIGNMENT_OVERLAP` (HTTP 409)."
    PRD §3.6: "The end date is exclusive: the car is free from that date
    onward."

    The completed incumbent still supplies the buffered end date, so the next
    placement may start one day after it only if a second clear day is granted.

    Design: Difficulty/resource_temporal_overlap/placement_interval_one_day_buffer_boundary
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(
        model_code="R8B-100",
        car_class="BOXCAR",
        build_hours=10,
        regulatory_life_years=40,
        line_count_family="R8B_LINE",
        wheelset_part_number="R8B-WS",
        wheelset_unit_cost_cents=100000,
        wheelset_qty_per_car=4,
        wheelset_lead_time_days=20,
        include_coating=False,
        on_hand_qty=100,
    )
    world = create_lessee_and_contract(
        legal_name="R8B Rail Leasing Co",
        credit_tier="B",
        utilization_threshold_pct=80,
        credit_ceiling_cents=10000000,
        lease_type="NET",
        per_diem_rate_cents=5000,
        liability_bearer="LESSEE",
        term_start_date="2026-09-01",
        term_end_date="2027-09-01",
        fleet_car_cap=10,
    )
    lessee, contract = world["lessee"], world["contract"]

    order = create_order(
        catalogue,
        quantity=1,
        planned_shop_days=10,
        disposition="RETAINED",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-09-20",
        lessee_id=lessee["id"],
    )
    reserve_order(order["id"])
    release_order(order["id"], lease_contract_id=contract["id"])
    start_production(order["id"], "R8B_LINE", window_start="2026-09-05",
                     window_days=10)
    complete_order(order["id"], completed_qty=1, completion_date="2026-09-15")

    car = get_success_data(
        api_client.list_lease_fleet_cars(
            ADMIN, {"production_order_id": order["id"]}
        )
    )[0]
    assert car["built_date"] == "2026-09-15"
    assert car["regulatory_life_end_date"] == "2066-09-15"

    # Incumbent placement [2026-09-16, 2026-10-16), then closed by a return
    # that leaves the car HELD again with its contract stamp cleared.
    advance_clock_to("2026-09-16T00:00:00Z")
    incumbent = create_assignment(
        car, contract, lessee, start_date="2026-09-16",
        end_date="2026-10-16", mileage_allowance=1000,
    )
    closed_return = create_return(
        car, incumbent, return_date="2026-10-16",
        mileage_since_last=500, condition_grade="A",
    )
    assert closed_return["mileage_overage_cents"] == 0
    settle_return(closed_return["id"])
    released = validate_success(
        api_client.settle_fleet_car_returns(car["id"], PLANNER)
    )
    assert released["status"] == "HELD"
    assert released["lease_contract_id"] is None

    advance_clock_to("2026-11-17T00:00:00Z")

    # One day after the incumbent's end date: the intervals do not intersect,
    # but the mandatory buffer is violated.
    too_soon = api_client.create_car_assignment(
        {
            "lease_fleet_car_id": car["id"],
            "lease_contract_id": contract["id"],
            "lessee_id": lessee["id"],
            "start_date": "2026-10-17",
            "end_date": "2026-11-16",
            "mileage_allowance": 1000,
        },
        LEASE,
    )
    validate_error(too_soon, ApiErrorId.ERR_ASSIGNMENT_OVERLAP)
    assert too_soon.status_code == 409

    still_free = get_success_data(api_client.get_lease_fleet_car(car["id"], ADMIN))
    assert still_free["status"] == "HELD", (
        "the rejected placement must not partially mutate the car"
    )

    # Two days after: the buffer is satisfied and the placement is accepted.
    # PRD 4: "A request that creates a new resource answers with 201 Created".
    accepted = validate_success(
        api_client.create_car_assignment(
            {
                "lease_fleet_car_id": car["id"],
                "lease_contract_id": contract["id"],
                "lessee_id": lessee["id"],
                "start_date": "2026-10-18",
                "end_date": "2026-11-17",
                "mileage_allowance": 1000,
            },
            LEASE,
        ),
        expected_status=201,
    )
    assert accepted["status"] == "ACTIVE"
    assert accepted["start_date"] == "2026-10-18"
    assert accepted["end_date"] == "2026-11-17"

    placed_car = get_success_data(api_client.get_lease_fleet_car(car["id"], ADMIN))
    assert placed_car["status"] == "ASSIGNED"

    prior = get_success_data(
        api_client.get_car_assignment(incumbent["id"], ADMIN)
    )
    assert prior["status"] == "COMPLETED", (
        "the incumbent stays as a closed row; it is not deleted"
    )
