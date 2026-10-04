"""Validation precedence, bands 9-24: deadlines, line exclusivity, lead-time feasibility and coverage.

Five instances, one test each.  The temporal rules are exercised from a clock
pinned at the documented start, with the dated windows themselves doing the
work; the two lead-time instances sit on either side of one boundary.
"""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    changeover_payload,
    complete_order,
    create_car_type_component_requirement_payload,
    create_car_type_payload,
    create_component_payload,
    create_order,
    create_production_order_payload,
    create_retrofit_program_car_type_payload,
    create_retrofit_program_payload,
    create_retrofit_work_order_payload,
    get_success_data,
    release_order,
    reserve_order,
    set_clock,
    setup_catalogue,
    setup_retained_order_with_fleet_cars,
    start_production,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SUPPLY = TEST_USERS["supply_chain_coordinator_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
RETROFIT = TEST_USERS["regulatory_retrofitist_headers"]


def test_retrofit_window_running_past_the_compliance_deadline_is_rejected(api):
    """PRD §2.8: "A shop window is acceptable only if it ends on or before the
    program's `compliance_deadline_date`; scheduling work whose window would run
    past the deadline is rejected with `ERR_RETROFIT_DEADLINE_PASSED` (HTTP 422)".
    PRD §2.11: "Ninth, compliance deadline: a retrofit shop window must end on or
    before the program's `compliance_deadline_date`, and a breach is rejected with
    `ERR_RETROFIT_DEADLINE_PASSED` (HTTP 422) on work-order creation and program
    start."
    PRD §2.5: "Business dates (`order_date`, `required_delivery_date`,
    `term_start_date`, `term_end_date`, `start_date`, `end_date`, `return_date`,
    `built_date`, `regulatory_life_end_date`, `compliance_deadline_date`,
    `scheduled_start_date`, `scheduled_end_date`, `receipt_date`,
    `expected_receipt_date`, `sale_date`) are ISO 8601 calendar dates."

    The clock still reads the mandate's opening day, so the rejection is a
    forward-looking check on the window rather than a lapsed deadline; the
    control window that ends exactly on the deadline is accepted.

    Design: Corner/validations/validation_p9_window_crossing_compliance_deadline_returns_deadline_passed
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(
        model_code="FLT-100",
        car_class="BOXCAR",
        build_hours=1,
        regulatory_life_years=25,
        line_count_family="FLT_LINE",
        wheelset_part_number="WS-310",
        wheelset_unit_cost_cents=1000,
        wheelset_qty_per_car=1,
        lead_time_days=5,
        include_coating=False,
        on_hand_qty=1000,
    )
    world = setup_retained_order_with_fleet_cars(
        car_count=2,
        catalogue=catalogue,
        build_contract=False,
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-09-20",
        changeover_start="2026-09-02",
        completion_date="2026-09-04",
    )
    car_a, car_b = world["cars"][0], world["cars"][1]
    assert car_a["built_date"] == "2026-09-04"
    assert car_a["regulatory_life_end_date"] == "2051-09-04"

    program = validate_success(
        api.create_retrofit_program(
            create_retrofit_program_payload(
                mandate_code="MAND-500",
                description="Deadline-bound retrofit mandate",
                compliance_deadline_date="2026-10-15",
                required_shop_days_per_car=10,
            ),
            RETROFIT,
        ),
        expected_status=201,
    )
    validate_success(
        api.create_retrofit_program_car_type(
            create_retrofit_program_car_type_payload(
                retrofit_program_id=program["id"],
                car_type_id=catalogue["car_type"]["id"],
            ),
            RETROFIT,
        ),
        expected_status=201,
    )

    overrunning = api.create_retrofit_work_order(
        create_retrofit_work_order_payload(
            retrofit_program_id=program["id"],
            lease_fleet_car_id=car_a["id"],
            shop_line="SHOP-500",
            scheduled_start_date="2026-10-10",
            scheduled_end_date="2026-10-20",
            component_qty_consumed=1,
        ),
        RETROFIT,
    )
    validate_error(overrunning, ApiErrorId.ERR_RETROFIT_DEADLINE_PASSED)
    assert overrunning.status_code == 422

    on_deadline = validate_success(
        api.create_retrofit_work_order(
            create_retrofit_work_order_payload(
                retrofit_program_id=program["id"],
                lease_fleet_car_id=car_b["id"],
                shop_line="SHOP-501",
                scheduled_start_date="2026-10-05",
                scheduled_end_date="2026-10-15",
                component_qty_consumed=1,
            ),
            RETROFIT,
        ),
        expected_status=201,
    )
    assert on_deadline["status"] == "SCHEDULED"
    assert on_deadline["shop_days"] == 10

    car_a_after = get_success_data(api.get_lease_fleet_car(car_a["id"], ADMIN))
    assert car_a_after["status"] == "HELD", "the rejected call left the car free"

    on_shop_500 = get_success_data(
        api.list_retrofit_work_orders(ADMIN, {"shop_line": "SHOP-500"})
    )
    assert on_shop_500 == [], "the rejected call created no work order row"


def test_changeover_colliding_on_the_line_family_is_rejected(api):
    """PRD §3.4: "The half-open window from `scheduled_start_date` up to but not
    including `scheduled_end_date` must not collide with any other changeover on
    the same line family, because the line is exclusive-occupancy; a collision is
    rejected with `ERR_CHANGEOVER_CONFLICT` (HTTP 409)."
    PRD §2.11: "Twelfth, line exclusivity: the half-open changeover window must
    not collide with another changeover on the same `line_count_family`, and a
    collision is rejected with `ERR_CHANGEOVER_CONFLICT` (HTTP 409)."
    PRD §2.5: "Second, when two half-open intervals are compared, a window that
    ends exactly when another begins does not collide with it — touching at a
    boundary is legal, overlapping by any amount is not."

    The colliding request is byte-identical in window to the incumbent; the
    control window touches the incumbent's end and is accepted.

    Design: Corner/validations/validation_p12_changeover_window_collision_returns_changeover_conflict
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(
        model_code="FLT-100",
        car_class="BOXCAR",
        build_hours=1,
        regulatory_life_years=25,
        line_count_family="FLT_LINE",
        wheelset_part_number="WS-310",
        wheelset_unit_cost_cents=1000,
        wheelset_qty_per_car=1,
        lead_time_days=5,
        include_coating=False,
        on_hand_qty=1000,
    )
    first_order = create_order(
        catalogue,
        quantity=1,
        planned_shop_days=1,
        disposition="SOLD",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-09-20",
    )
    second_order = create_order(
        catalogue,
        quantity=1,
        planned_shop_days=1,
        disposition="SOLD",
        priority_rank=2,
        order_date="2026-09-01",
        required_delivery_date="2026-09-20",
    )
    reserve_order(first_order["id"])
    release_order(first_order["id"])
    reserve_order(second_order["id"])
    release_order(second_order["id"])

    incumbent = start_production(
        first_order["id"], "FLT_LINE", window_start="2026-09-02", window_days=1
    )
    assert incumbent["status"] == "IN_PRODUCTION"

    collision = api.changeover_production_line(
        "FLT_LINE",
        changeover_payload(
            production_order_id=second_order["id"],
            scheduled_start_date="2026-09-02",
            scheduled_end_date="2026-09-03",
        ),
        PLANNER,
    )
    validate_error(collision, ApiErrorId.ERR_CHANGEOVER_CONFLICT)
    assert collision.status_code == 409

    untouched = get_success_data(
        api.get_production_order(second_order["id"], ADMIN)
    )
    assert untouched["status"] == "RELEASED", "the colliding call did not start work"

    touching = start_production(
        second_order["id"], "FLT_LINE", window_start="2026-09-03", window_days=1
    )
    assert touching["status"] == "IN_PRODUCTION", (
        "a window that touches the incumbent's end is legal"
    )

    incumbent_after = get_success_data(
        api.get_production_order(first_order["id"], ADMIN)
    )
    assert incumbent_after["status"] == "IN_PRODUCTION", (
        "the rejected call did not disturb the incumbent"
    )


def test_horizon_one_day_short_of_the_worst_gated_lead_is_rejected(api):
    """PRD §3.1: "An order whose car type has no gated rows at all takes a worst
    gated lead time of zero by convention, so it is always feasible on this axis.
    The order passes the gate exactly when the horizon is greater than or equal
    to the worst gated lead time; anything shorter is rejected with
    `ERR_LEAD_TIME_INFEASIBLE` (HTTP 422)."
    PRD §3.1: "For each gated row, the derived lead time is the component's
    `lead_time_days` divided by the row's `qty_per_car`, rounded up to a whole
    day, and the worst gated lead time is the largest such figure across all
    gated rows."
    PRD §2.11: "Fourteenth, lead-time feasibility: the order-to-delivery horizon
    must be at least the worst gated component lead time derived in §3.1, and a
    breach is rejected with `ERR_LEAD_TIME_INFEASIBLE` (HTTP 422) on order
    creation and reservation."

    The single gated row derives ceil(60 / 2) = 30 days; the 29-day order is
    rejected and the 30-day order is accepted, and only the latter persists.

    Design: Corner/validations/validation_p14_horizon_short_of_worst_gated_lead_returns_lead_time_infeasible
    """
    set_clock("2026-09-01T00:00:00Z")
    car_type = validate_success(
        api.create_car_type(
            create_car_type_payload(
                model_code="LT-100",
                car_class="BOXCAR",
                build_hours=1,
                regulatory_life_years=15,
                line_count_family="LT_LINE",
            ),
            PLANNER,
        ),
        expected_status=201,
    )
    component = validate_success(
        api.create_component(
            create_component_payload(
                part_number="WS-LT-1",
                component_class="WHEELSET",
                unit_cost_cents=200000,
                lead_time_days=60,
                on_hand_qty=100,
            ),
            SUPPLY,
        ),
        expected_status=201,
    )
    validate_success(
        api.create_car_type_component_requirement(
            create_car_type_component_requirement_payload(
                car_type_id=car_type["id"],
                component_id=component["id"],
                qty_per_car=2,
            ),
            PLANNER,
        ),
        expected_status=201,
    )

    rejected = api.create_production_order(
        create_production_order_payload(
            car_type_id=car_type["id"],
            quantity=1,
            planned_shop_days=1,
            disposition="SOLD",
            priority_rank=1,
            order_date="2026-09-01",
            required_delivery_date="2026-09-30",
        ),
        PLANNER,
    )
    validate_error(rejected, ApiErrorId.ERR_LEAD_TIME_INFEASIBLE)
    assert rejected.status_code == 422

    accepted = validate_success(
        api.create_production_order(
            create_production_order_payload(
                car_type_id=car_type["id"],
                quantity=1,
                planned_shop_days=1,
                disposition="SOLD",
                priority_rank=1,
                order_date="2026-09-01",
                required_delivery_date="2026-10-01",
            ),
            PLANNER,
        ),
        expected_status=201,
    )
    assert accepted["status"] == "DRAFT"

    rows = validate_success(
        api.list_production_orders(ADMIN, {"car_type_id": car_type["id"]})
    )
    assert len(rows) == 1, "the rejected order persisted nothing"
    assert rows[0]["id"] == accepted["id"]


def test_horizon_exactly_at_the_worst_gated_lead_passes_both_gate_sites(api):
    """PRD §3.1: "The order passes the gate exactly when the horizon is greater
    than or equal to the worst gated lead time; anything shorter is rejected with
    `ERR_LEAD_TIME_INFEASIBLE` (HTTP 422)."
    PRD §3.2: "Reservation is legal only from `DRAFT`, and it transitions the
    order to `COMPONENT_RESERVED`."
    PRD §3.2: "A successful reservation commits the wheelset and casting stock:
    for each covered row, the component's `on_hand_qty` is decremented by the
    effective per-car quantity multiplied by the order quantity".

    The horizon equals the derived lead exactly, so the >= gate is satisfied with
    zero slack at both the creation site and the reservation site.

    Design: Corner/validations/validation_p14_satisfaction_horizon_exactly_worst_lead_passes
    """
    set_clock("2026-09-01T00:00:00Z")
    car_type = validate_success(
        api.create_car_type(
            create_car_type_payload(
                model_code="LT-100",
                car_class="BOXCAR",
                build_hours=1,
                regulatory_life_years=15,
                line_count_family="LT_LINE",
            ),
            PLANNER,
        ),
        expected_status=201,
    )
    component = validate_success(
        api.create_component(
            create_component_payload(
                part_number="WS-LT-1",
                component_class="WHEELSET",
                unit_cost_cents=200000,
                lead_time_days=60,
                on_hand_qty=100,
            ),
            SUPPLY,
        ),
        expected_status=201,
    )
    validate_success(
        api.create_car_type_component_requirement(
            create_car_type_component_requirement_payload(
                car_type_id=car_type["id"],
                component_id=component["id"],
                qty_per_car=2,
            ),
            PLANNER,
        ),
        expected_status=201,
    )

    order = validate_success(
        api.create_production_order(
            create_production_order_payload(
                car_type_id=car_type["id"],
                quantity=1,
                planned_shop_days=1,
                disposition="SOLD",
                priority_rank=1,
                order_date="2026-09-01",
                required_delivery_date="2026-10-01",
            ),
            PLANNER,
        ),
        expected_status=201,
    )
    assert order["status"] == "DRAFT"
    assert order["required_delivery_date"] == "2026-10-01"

    reserved = validate_success(api.reserve_components(order["id"], PLANNER))
    assert reserved["status"] == "COMPONENT_RESERVED", (
        "the second gate site passes at exactly the boundary"
    )
    assert reserved["version"] == 2, "1 at creation, 2 at reserve-components"

    component_after = get_success_data(api.get_component(component["id"], ADMIN))
    assert component_after["on_hand_qty"] == 98, (
        "100 minus qty_per_car 2 times quantity 1"
    )


def test_car_type_outside_the_program_coverage_is_rejected(api):
    """PRD §2.8: "A work order may only be raised for a car whose car type is
    covered by the named program through a `RetrofitProgramCarType` row; a car
    type that is not covered is rejected with `ERR_CAPACITY_EXCEEDED` (HTTP 409)."
    PRD §2.11: "Twenty-fourth, program coverage: the car's car type must be
    covered by the retrofit program through a `RetrofitProgramCarType` row, and a
    car type that is not covered is rejected with `ERR_CAPACITY_EXCEEDED`
    (HTTP 409) on work-order creation."
    PRD §3.8: "Coverage is then declared by adding `RetrofitProgramCarType` rows,
    each naming the `retrofit_program_id` and the `car_type_id` it covers; a
    program covers nothing until at least one such row exists."

    Two car types exist with one HELD car each; the program covers only the
    first, so the identical work-order call differs solely in the car's type.

    Design: Corner/validations/validation_p24_car_type_not_covered_by_retrofit_program_returns_capacity_exceeded
    """
    set_clock("2026-09-01T00:00:00Z")
    covered_type = validate_success(
        api.create_car_type(
            create_car_type_payload(
                model_code="R24-A-100",
                car_class="BOXCAR",
                build_hours=1,
                regulatory_life_years=15,
                line_count_family="R24_A_LINE",
            ),
            PLANNER,
        ),
        expected_status=201,
    )
    uncovered_type = validate_success(
        api.create_car_type(
            create_car_type_payload(
                model_code="R24-B-100",
                car_class="TANK",
                build_hours=1,
                regulatory_life_years=15,
                line_count_family="R24_B_LINE",
            ),
            PLANNER,
        ),
        expected_status=201,
    )
    component = validate_success(
        api.create_component(
            create_component_payload(
                part_number="WS-R24-1",
                component_class="WHEELSET",
                unit_cost_cents=1000,
                lead_time_days=5,
                on_hand_qty=100,
            ),
            SUPPLY,
        ),
        expected_status=201,
    )
    for car_type in (covered_type, uncovered_type):
        validate_success(
            api.create_car_type_component_requirement(
                create_car_type_component_requirement_payload(
                    car_type_id=car_type["id"],
                    component_id=component["id"],
                    qty_per_car=1,
                ),
                PLANNER,
            ),
            expected_status=201,
        )

    cars = {}
    for car_type, line_segment in (
        (covered_type, "R24_A_LINE"),
        (uncovered_type, "R24_B_LINE"),
    ):
        catalogue = {
            "car_type": car_type,
            "wheelset": component,
            "casting": None,
            "coating": None,
            "components": [component],
            "bom": [],
        }
        order = create_order(
            catalogue,
            quantity=1,
            planned_shop_days=1,
            disposition="RETAINED",
            priority_rank=1,
            order_date="2026-09-01",
            required_delivery_date="2026-09-20",
        )
        reserve_order(order["id"])
        release_order(order["id"])
        start_production(order["id"], line_segment, window_start="2026-09-02",
                         window_days=1)
        complete_order(order["id"], completed_qty=1, completion_date="2026-09-03")
        cars[car_type["id"]] = get_success_data(
            api.list_lease_fleet_cars(ADMIN, {"production_order_id": order["id"]})
        )[0]
    car_covered = cars[covered_type["id"]]
    car_uncovered = cars[uncovered_type["id"]]
    assert car_covered["car_type_id"] == covered_type["id"]
    assert car_uncovered["car_type_id"] == uncovered_type["id"]

    program = validate_success(
        api.create_retrofit_program(
            create_retrofit_program_payload(
                mandate_code="R24-MAND-1",
                description="Coverage-scoped retrofit mandate",
                compliance_deadline_date="2027-01-01",
                required_shop_days_per_car=2,
            ),
            RETROFIT,
        ),
        expected_status=201,
    )
    assert program["status"] == "PLANNED"
    validate_success(
        api.create_retrofit_program_car_type(
            create_retrofit_program_car_type_payload(
                retrofit_program_id=program["id"],
                car_type_id=covered_type["id"],
            ),
            RETROFIT,
        ),
        expected_status=201,
    )

    rejected = api.create_retrofit_work_order(
        create_retrofit_work_order_payload(
            retrofit_program_id=program["id"],
            lease_fleet_car_id=car_uncovered["id"],
            shop_line="R24-SHOP-1",
            scheduled_start_date="2026-10-01",
            scheduled_end_date="2026-10-03",
            component_qty_consumed=1,
        ),
        PLANNER,
    )
    validate_error(rejected, ApiErrorId.ERR_CAPACITY_EXCEEDED)
    assert rejected.status_code == 409

    accepted = validate_success(
        api.create_retrofit_work_order(
            create_retrofit_work_order_payload(
                retrofit_program_id=program["id"],
                lease_fleet_car_id=car_covered["id"],
                shop_line="R24-SHOP-2",
                scheduled_start_date="2026-10-01",
                scheduled_end_date="2026-10-03",
                component_qty_consumed=1,
            ),
            PLANNER,
        ),
        expected_status=201,
    )
    assert accepted["status"] == "SCHEDULED"
    assert accepted["shop_days"] == 2

    coverage = validate_success(
        api.list_retrofit_program_car_types(
            ADMIN, {"retrofit_program_id": program["id"]}
        )
    )
    assert len(coverage) == 1
    assert coverage[0]["car_type_id"] == covered_type["id"]

    assert get_success_data(
        api.get_lease_fleet_car(car_uncovered["id"], ADMIN)
    )["status"] == "HELD"
    assert get_success_data(
        api.get_lease_fleet_car(car_covered["id"], ADMIN)
    )["status"] == "UNDER_REPAIR"
    assert get_success_data(
        api.get_retrofit_program(program["id"], ADMIN)
    )["status"] == "PLANNED", "the program was never started"
