"""Lead-time feasibility, the scrap-versus-retrofit decision and program cost.

The feasibility gate reads only the wheelset and casting rows of the bill of
materials; the retrofit decision reads the car's regulatory life first and its
economics second; and the program cost aggregates the shop work the program has
actually booked. Every expected figure below is recomputed from the PRD's stated
formulas against the catalogue the fixture actually builds.
"""

from test_helpers import (
    CLOCK_START_ISO,
    ApiErrorId,
    api_client,
    create_component_payload,
    create_order,
    create_retrofit_program,
    create_retrofit_work_order_payload,
    create_work_order,
    days_between,
    get_success_data,
    set_clock,
    setup_catalogue,
    validate_error,
    worst_gated_lead_days,
)

from test_calculations_support import (
    ADMIN,
    PLANNER,
    RETROFIT,
    SUPPLY,
    flat_car_catalogue,
    held_cars,
)


def test_horizon_clears_the_worst_gated_lead_time(api):
    """PRD §3.1: "The gated rows are those bill-of-material rows of the order's
    car type whose component belongs to the `WHEELSET` or `CASTING` class;
    `COATING` rows are excluded, because coatings are procured against a service
    contract and never gate release. For each gated row, the derived lead time is
    the component's `lead_time_days` divided by the row's `qty_per_car`, rounded
    up to a whole day, and the worst gated lead time is the largest such figure
    across all gated rows."
    PRD §3.1: "The order passes the gate exactly when the horizon is greater than
    or equal to the worst gated lead time"

    A twenty-day horizon clears a worst gated lead time of exactly fifteen days —
    ceil(30 / 2) for the wheelset row and ceil(45 / 3) for the casting row — so
    the order is accepted on the DRAFT status rather than rejected, and the gate
    leaves the quote at 100000: 55000 of ceiled lines plus one 45000-cent build
    hour.

    Design: Corner/calculations/production_feasibility_gate_correct_result_horizon_clears_worst_lead
    """
    set_clock(CLOCK_START_ISO)
    catalogue = setup_catalogue(
        model_code="GATE-100",
        car_class="BOXCAR",
        build_hours=1,
        regulatory_life_years=25,
        line_count_family="GATE_LINE",
        wheelset_part_number="WS-410",
        wheelset_unit_cost_cents=1000,
        wheelset_qty_per_car=2,
        wheelset_lead_time_days=30,
        casting_part_number="CS-410",
        casting_unit_cost_cents=1000,
        casting_qty_per_car=3,
        casting_lead_time_days=45,
        on_hand_qty=1000,
        include_coating=False,
    )
    order = create_order(
        catalogue,
        quantity=5,
        planned_shop_days=5,
        disposition="SOLD",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-09-21",
    )

    assert days_between("2026-09-01", "2026-09-21") == 20
    assert worst_gated_lead_days(catalogue) == 15, (
        "max(ceil(30 / 2), ceil(45 / 3)), not the raw 30- or 45-day lead times"
    )
    assert order["status"] == "DRAFT"
    assert order["unit_price_cents"] == 100000


def test_car_inside_its_life_with_retrofit_within_the_allowance_is_retrofitted(api):
    """PRD §3.8: "when the current clock date is strictly later than the car's
    `regulatory_life_end_date`, the decision is `SCRAP` regardless of retrofit
    economics — a car whose life end date equals the current clock date is still
    inside its life and is not caught by this test."
    PRD §3.8: "the retrofit cost is the program's `required_shop_days_per_car`
    multiplied by the shop-day rate of 185,000 cents, plus, when the program has
    a required component, that component's `unit_cost_cents` multiplied by the
    work order's `component_qty_consumed`. When the retrofit cost exceeds the
    allowance, the decision is `SCRAP` on cost grounds even though the car could
    still legally run"

    A car whose life runs to 2051 is read at 2026, so the life test does not
    force the scrap branch, and a ten-shop-day mandate with no kit costs
    10 * 185000 == 1850000, inside the 2500000-cent allowance. The work order is
    therefore accepted with the ten shop days its window implies, and the car
    moves to the repair queue with its retrofit obligation flagged.

    Design: Corner/calculations/scrape_or_retrofit_decision_correct_result_retrofit_within_allowance
    """
    set_clock(CLOCK_START_ISO)
    catalogue = flat_car_catalogue()
    world = held_cars(
        catalogue,
        car_count=2,
        changeover_start="2026-09-02",
        completion_date="2026-09-04",
        required_delivery_date="2026-09-20",
    )
    program = create_retrofit_program(
        catalogue,
        mandate_code="MAND-100",
        compliance_deadline_date="2026-12-31",
        required_shop_days_per_car=10,
    )["program"]

    assert world["car"]["regulatory_life_end_date"] == "2051-09-04"
    assert 10 * 185000 == 1850000, "inside the 2500000-cent allowance"

    work_order = create_work_order(
        program,
        world["car"],
        shop_line="SHOP-100",
        scheduled_start_date="2026-09-10",
        component_qty_consumed=1,
    )
    car = get_success_data(api_client.get_lease_fleet_car(world["car"]["id"], RETROFIT))

    assert work_order["status"] == "SCHEDULED"
    assert work_order["shop_days"] == 10, (
        "the window 2026-09-10 to 2026-09-20 is the mandate's ten shop days"
    )
    assert work_order["shop_days"] == program["required_shop_days_per_car"]
    assert car["status"] == "UNDER_REPAIR"
    assert car["retrofit_required"] is True


def test_program_cost_aggregates_the_shop_work_the_program_has_booked(api):
    """PRD §3.8: "On the scheduled estimate used while the program is `PLANNED`
    or `IN_PROGRESS`, every work order of the program that is not in `CANCELLED`
    status contributes. On the completed actual used once the program is
    `COMPLETED`, only work orders in `COMPLETED` status contribute — so a work
    order cancelled in the middle of a program reduces the program cost rather
    than leaving an estimate behind."
    PRD §3.8: "Each contributing work order adds its `shop_days` multiplied by
    the shop-day rate of 185,000 cents, plus its `component_qty_consumed`
    multiplied by the unit cost of the program's required component when a
    `required_component_id` is set."

    Two work orders of ten shop days each consume one unit of a 20000-cent kit,
    so each carries 10 * 185000 + 1 * 20000 == 1870000. The program is still
    open, so both work orders are outside `CANCELLED` and both contribute:
    3740000. Cancelling the one that has not started drops the figure back to the
    1870000 the completed work order alone carries, which is what the completed
    actual would report once the program itself closes.

    Design: Corner/calculations/retrofit_program_cost_allocation_correct_result_completed_only
    """
    set_clock(CLOCK_START_ISO)
    catalogue = flat_car_catalogue()
    kit = get_success_data(
        api_client.create_component(
            create_component_payload(
                part_number="CS-510",
                component_class="CASTING",
                unit_cost_cents=20000,
                lead_time_days=30,
                on_hand_qty=100,
            ),
            SUPPLY,
        )
    )
    world = held_cars(
        catalogue,
        car_count=2,
        changeover_start="2026-09-02",
        completion_date="2026-09-04",
        required_delivery_date="2026-09-20",
    )
    program = create_retrofit_program(
        catalogue,
        mandate_code="MAND-200",
        compliance_deadline_date="2026-12-31",
        required_shop_days_per_car=10,
        required_component_id=kit["id"],
    )["program"]
    first = create_work_order(
        program,
        world["cars"][0],
        shop_line="SHOP-200",
        scheduled_start_date="2026-09-10",
        component_qty_consumed=1,
    )
    second = create_work_order(
        program,
        world["cars"][1],
        shop_line="SHOP-201",
        scheduled_start_date="2026-09-10",
        component_qty_consumed=1,
    )

    get_success_data(api_client.start_retrofit_work_order(first["id"], PLANNER))
    finished = get_success_data(
        api_client.complete_retrofit_work_order(first["id"], PLANNER)
    )
    assert finished["status"] == "COMPLETED"
    assert first["shop_days"] == 10
    assert second["shop_days"] == 10

    while_open = get_success_data(
        api_client.get_retrofit_program(program["id"], RETROFIT)
    )
    assert while_open["status"] == "PLANNED"
    assert while_open["program_cost_cents"] == 3740000, (
        "with the program open, both work orders are outside CANCELLED and both "
        "contribute their 10 * 185000 + 1 * 20000"
    )

    cancelled = get_success_data(
        api_client.cancel_retrofit_work_order(second["id"], PLANNER)
    )
    assert cancelled["status"] == "CANCELLED"
    after_cancel = get_success_data(
        api_client.get_retrofit_program(program["id"], RETROFIT)
    )
    assert after_cancel["program_cost_cents"] == 1870000, (
        "a cancelled work order leaves no estimate behind, so only the "
        "completed work order's 1870000 remains"
    )


def test_life_end_date_is_inclusive_for_retrofit_scheduling(api):
    """PRD §2.8: "The boundary is inclusive of the end date itself: a car whose
    `regulatory_life_end_date` equals the current clock date is still eligible
    for retrofit, and the scrapping decision described in §3.8 treats it the
    same way."
    PRD §3.8: "when the current clock date is strictly later than the car's
    `regulatory_life_end_date`, the decision is `SCRAP` regardless of retrofit
    economics"

    Two cars built on 2041-09-03 under a ten-year regulatory life end on
    2051-09-03. On that date the mandate's work order for the first car is
    accepted, so the life test is inclusive; one day later the identical call for
    the second car is rejected as `ERR_REGULATORY_LIFE_EXCEEDED`, and the
    rejected call leaves the car exactly where it stood. The retrofit economics
    are the same in both calls, so the divergence is caused only by the one-day
    crossing.

    Design: Corner/calculations/scrape_or_retrofit_decision_variant_selection_life_end_inclusive
    """
    set_clock("2041-09-01T00:00:00Z")
    catalogue = flat_car_catalogue(
        model_code="LIFE-100",
        regulatory_life_years=10,
        line_count_family="LIFE_LINE",
        set_clock_first=False,
    )
    world = held_cars(
        catalogue,
        car_count=2,
        changeover_start="2041-09-02",
        completion_date="2041-09-03",
        order_date="2041-09-01",
        required_delivery_date="2041-09-20",
    )
    program = create_retrofit_program(
        catalogue,
        mandate_code="MAND-400",
        compliance_deadline_date="2051-12-31",
        required_shop_days_per_car=10,
    )["program"]
    for car in world["cars"]:
        assert car["built_date"] == "2041-09-03"
        assert car["regulatory_life_end_date"] == "2051-09-03"

    set_clock("2051-09-03T00:00:00Z")
    accepted = create_work_order(
        program,
        world["cars"][0],
        shop_line="SHOP-400",
        scheduled_start_date="2051-09-10",
        component_qty_consumed=1,
    )
    assert accepted["status"] == "SCHEDULED"
    assert accepted["shop_days"] == 10, (
        "10 * 185000 == 1850000 is inside the 2500000-cent allowance in both calls"
    )

    set_clock("2051-09-04T00:00:00Z")
    rejected = api_client.create_retrofit_work_order(
        create_retrofit_work_order_payload(
            retrofit_program_id=program["id"],
            lease_fleet_car_id=world["cars"][1]["id"],
            shop_line="SHOP-401",
            scheduled_start_date="2051-09-10",
            scheduled_end_date="2051-09-20",
            component_qty_consumed=1,
        ),
        RETROFIT,
    )
    validate_error(rejected, ApiErrorId.ERR_REGULATORY_LIFE_EXCEEDED)

    unchanged = get_success_data(
        api_client.get_lease_fleet_car(world["cars"][1]["id"], ADMIN)
    )
    assert unchanged["status"] == "HELD"
    assert unchanged["retrofit_required"] is False
    work_orders = get_success_data(
        api_client.list_retrofit_work_orders(ADMIN, {"limit": 100})
    )
    assert all(
        row["lease_fleet_car_id"] != world["cars"][1]["id"] for row in work_orders
    ), "the rejected scheduling write committed no work order"
