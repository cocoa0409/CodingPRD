"""Cascading side effects, dual-variant calculations and derived fields.

Seven instances, one test each.  Every money figure is recomputed from the
PRD's stated formulas against the catalogue the test actually builds, and every
derived field is asserted twice — once before and once after the event that
re-derives it — so a patched-increment implementation cannot pass.
"""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock_to,
    api_client,
    approve_endorsement,
    build_user_headers,
    complete_order,
    create_assignment,
    create_car_type_component_requirement_payload,
    create_car_type_payload,
    create_component_payload,
    create_component_purchase_order_payload,
    create_component_receipt_payload,
    create_endorsement,
    create_lessee_and_contract,
    create_order,
    create_retrofit_program,
    create_return,
    create_work_order,
    receive_component_stock,
    release_order,
    reserve_order,
    set_clock,
    setup_catalogue,
    setup_retained_order_with_fleet_cars,
    setup_retrofit_program_with_car,
    start_production,
    validate_error,
    validate_success,
)

SUPPLY = TEST_USERS["supply_chain_coordinator_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
LEASE = TEST_USERS["lease_administrator_headers"]
PORTFOLIO = TEST_USERS["portfolio_manager_headers"]
RETROFIT = TEST_USERS["regulatory_retrofitist_headers"]


def _single_coating_catalogue(
    model_code: str,
    line_count_family: str,
    part_number: str,
    unit_cost_cents: int = 1000,
    lead_time_days: int = 5,
    qty_per_car: int = 1,
    purchase_qty: int = 0,
    expected_receipt_date: str = "2026-09-06",
) -> dict:
    """A car type whose only bill-of-material row is one COATING component.

    Coating rows never gate lead-time feasibility and never commit stock at
    reservation, so this catalogue isolates the coating-side behaviour from the
    wheelset and casting paths.  A confirmed purchase order covering the
    delivery window is raised when ``purchase_qty`` is set, because release
    demands committed supply for every coating row.
    """
    car_type = validate_success(
        api_client.create_car_type(
            create_car_type_payload(
                model_code=model_code,
                car_class="BOXCAR",
                build_hours=1,
                regulatory_life_years=25,
                line_count_family=line_count_family,
            ),
            PLANNER,
        ),
        expected_status=201,
    )
    coating = validate_success(
        api_client.create_component(
            create_component_payload(
                part_number=part_number,
                component_class="COATING",
                unit_cost_cents=unit_cost_cents,
                lead_time_days=lead_time_days,
            ),
            SUPPLY,
        ),
        expected_status=201,
    )
    requirement = validate_success(
        api_client.create_car_type_component_requirement(
            create_car_type_component_requirement_payload(
                car_type_id=car_type["id"],
                component_id=coating["id"],
                qty_per_car=qty_per_car,
            ),
            PLANNER,
        ),
        expected_status=201,
    )
    purchase_order = None
    if purchase_qty:
        purchase_order = validate_success(
            api_client.create_component_purchase_order(
                create_component_purchase_order_payload(
                    component_id=coating["id"],
                    qty_ordered=purchase_qty,
                    unit_cost_cents=unit_cost_cents,
                    order_date="2026-09-01",
                    expected_receipt_date=expected_receipt_date,
                ),
                SUPPLY,
            ),
            expected_status=201,
        )
        purchase_order = validate_success(
            api_client.confirm_component_purchase_order(purchase_order["id"], SUPPLY)
        )
    return {
        "car_type": car_type,
        "coating": coating,
        "requirement": requirement,
        "purchase_order": purchase_order,
    }


def test_return_booking_cascade_reaches_the_ledger_only_at_settlement(api):
    """PRD §3.7: "On success the placement becomes `COMPLETED`, the parent car
    moves to `UNDER_REPAIR`, and the car's `accumulated_mileage` is recomputed as
    the total miles recorded across every placement and return for that car."
    PRD §3.7: "The number of days in the placement is the placement's `end_date`
    minus its `start_date`.  That figure is divided by thirty and rounded up to
    a whole number to give the number of allowance blocks; the included miles
    are those blocks multiplied by the placement's `mileage_allowance`."
    PRD §3.7: "The charge is the overage miles multiplied by the overage rate of
    12 cents per mile, and it is written to the return's `mileage_overage_cents`
    and to the placement's `mileage_charge_cents`."
    PRD §3.7: "Until a return is settled, its mileage overage does not count
    toward the lessee's balance, because the reconciliation aggregates only
    settled returns."

    The placement runs from 2026-06-03 to 2026-09-01, so 90 days give
    ceil(90 / 30) = 3 allowance blocks of 1000 miles; 5200 miles used overrun by
    2200 miles and the charge is 2200 * 12 = 26400 cents.

    Design: Corner/cross_cutting_complexity_layers/cascade_return_booking_through_settle_reaches_lessee_ledger
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(
        model_code="CT-CAS-1",
        build_hours=1,
        regulatory_life_years=25,
        line_count_family="LINE-CAS",
        wheelset_part_number="WS-CAS-1",
        wheelset_unit_cost_cents=1000,
        wheelset_lead_time_days=5,
        wheelset_qty_per_car=1,
        casting_part_number="CS-CAS-1",
        casting_unit_cost_cents=2000,
        casting_lead_time_days=6,
        casting_qty_per_car=1,
        include_coating=False,
        on_hand_qty=10,
    )
    commercial = create_lessee_and_contract(
        legal_name="LESS-CAS-1",
        per_diem_rate_cents=10000,
        liability_bearer="LESSOR",
        fleet_car_cap=10,
        credit_ceiling_cents=500_000_000,
    )

    # The retained order names neither a contract nor a lessee, so its value is
    # attributable to no lessee and cannot disturb the balance asserted below.
    order = create_order(
        catalogue,
        quantity=1,
        disposition="RETAINED",
        priority_rank=1,
        order_date="2026-06-01",
        required_delivery_date="2026-06-20",
    )
    reserve_order(order["id"])
    release_order(order["id"])
    start_production(order["id"], "LINE-CAS", window_start="2026-06-01")
    complete_order(order["id"], completion_date="2026-06-03")

    cars = validate_success(
        api_client.list_lease_fleet_cars(
            LEASE, {"production_order_id": order["id"], "limit": 10}
        )
    )
    assert len(cars) == 1
    car = cars[0]
    assert car["built_date"] == "2026-06-03"

    assignment = create_assignment(
        car,
        commercial["contract"],
        commercial["lessee"],
        start_date="2026-06-03",
        end_date="2026-09-01",
        mileage_allowance=1000,
    )

    car_return = create_return(
        car,
        assignment,
        return_date="2026-09-01",
        mileage_since_last=5200,
        condition_grade="B",
    )
    assert car_return["settlement_status"] == "PENDING"
    assert car_return["mileage_overage_cents"] == 26400, (
        "(5200 - 3 * 1000) overage miles * 12 cents"
    )

    closed = validate_success(api_client.get_car_assignment(assignment["id"], LEASE))
    assert closed["status"] == "COMPLETED", (
        "the booking closes the placement in the same request"
    )

    repaired = validate_success(api_client.get_lease_fleet_car(car["id"], LEASE))
    assert repaired["status"] == "UNDER_REPAIR"
    assert repaired["accumulated_mileage"] == 5200, (
        "the car banks every mile recorded for it"
    )

    before = validate_success(
        api_client.get_lessee_outstanding_balance(commercial["lessee"]["id"], LEASE)
    )
    assert before["outstanding_balance_cents"] == 0, (
        "an unsettled return has not reached the ledger"
    )

    settled = validate_success(
        api_client.settle_car_return(car_return["id"], PORTFOLIO)
    )
    assert settled["settlement_status"] == "SETTLED"

    after = validate_success(
        api_client.get_lessee_outstanding_balance(
            commercial["lessee"]["id"], PORTFOLIO
        )
    )
    assert after["outstanding_balance_cents"] == 26400, (
        "the settled true-up is the only charge on the ledger"
    )

    repeat = api_client.settle_car_return(car_return["id"], PORTFOLIO)
    validate_error(repeat, ApiErrorId.ERR_INVALID_STATE)
    assert repeat.status_code == 409

    unchanged = validate_success(
        api_client.get_lessee_outstanding_balance(
            commercial["lessee"]["id"], PORTFOLIO
        )
    )
    assert unchanged["outstanding_balance_cents"] == 26400, (
        "the refused second settle does not apply the charge twice"
    )


def test_retrofit_completion_resets_the_car_life_and_recomputes_program_cost(api):
    """PRD §3.8: "On success the work order becomes `COMPLETED`, the parent car
    returns to `HELD`, its `built_date` is set to the completion date and its
    `regulatory_life_end_date` is re-derived from that new build date, and the
    program's `program_cost_cents` is re-derived by the cost rule above."
    PRD §2.8: "A lease fleet car's `regulatory_life_end_date` is derived from its
    build date and its car type: it is the car's `built_date` advanced by the
    car type's `regulatory_life_years`."
    PRD §3.8: "Each contributing work order adds its `shop_days` multiplied by
    the shop-day rate of 185,000 cents, plus its `component_qty_consumed`
    multiplied by the unit cost of the program's required component when a
    `required_component_id` is set."
    PRD §2.10: "Derived fields are recomputed from scratch, never patched
    incrementally, so that any sequence of operations converges on the same
    value."

    The mandate demands 10 shop days per car and the kit costs 5000 cents a
    unit, so the completed work order contributes
    10 * 185000 + 3 * 5000 = 1865000 cents.

    Design: Corner/cross_cutting_complexity_layers/cascade_retrofit_complete_resets_car_life_and_recomputes_program_cost
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(
        model_code="CT-RW-1",
        build_hours=1,
        regulatory_life_years=25,
        line_count_family="LINE-RW",
        wheelset_part_number="WS-RW-1",
        wheelset_unit_cost_cents=1000,
        wheelset_lead_time_days=5,
        wheelset_qty_per_car=1,
        casting_part_number="CS-RW-1",
        casting_unit_cost_cents=2000,
        casting_lead_time_days=6,
        casting_qty_per_car=1,
        coating_part_number="CO-RW-1",
        coating_unit_cost_cents=5000,
        coating_qty_per_car=1,
        coating_lead_time_days=30,
        on_hand_qty=10,
    )
    world = setup_retrofit_program_with_car(
        catalogue=catalogue,
        required_shop_days_per_car=10,
        compliance_deadline_date="2026-12-31",
        required_component_id=catalogue["coating"]["id"],
        work_order_start="2026-09-10",
        shop_line="SL-RW-1",
        component_qty_consumed=3,
        order_date="2026-09-01",
        required_delivery_date="2026-09-20",
        changeover_start="2026-09-02",
        completion_date="2026-09-04",
    )
    car_id = world["car"]["id"]
    program_id = world["program"]["id"]
    work_order = world["work_order"]
    assert work_order["shop_days"] == 10, "the window equals required_shop_days_per_car"

    before = validate_success(api_client.get_lease_fleet_car(car_id, PLANNER))
    assert before["status"] == "UNDER_REPAIR"
    assert before["built_date"] == "2026-09-04"
    assert before["regulatory_life_end_date"] == "2051-09-04", (
        "the build date advanced by the car type's 25 regulatory years"
    )

    started = validate_success(
        api_client.start_retrofit_program(program_id, RETROFIT)
    )
    assert started["status"] == "IN_PROGRESS"
    assert started["program_cost_cents"] == 1865000, (
        "10 * 185000 shop days plus 3 * 5000 kit units"
    )

    # PRD 3.8: "Completion is legal from IN_PROGRESS", so the scheduled work
    # order has to be started before it can be completed.
    started_work = validate_success(
        api_client.start_retrofit_work_order(work_order["id"], PLANNER)
    )
    assert started_work["status"] == "IN_PROGRESS"

    advance_clock_to("2026-09-20T00:00:00Z")
    completed = validate_success(
        api_client.complete_retrofit_work_order(work_order["id"], PLANNER)
    )
    assert completed["status"] == "COMPLETED"

    after = validate_success(api_client.get_lease_fleet_car(car_id, PLANNER))
    assert after["status"] == "HELD", "the car returns to service"
    assert after["built_date"] == "2026-09-20", (
        "the completion date restarts the car's regulatory clock"
    )
    assert after["regulatory_life_end_date"] == "2051-09-20"

    recomputed = validate_success(
        api_client.get_retrofit_program(program_id, RETROFIT)
    )
    assert recomputed["program_cost_cents"] == 1865000

    refused = api_client.complete_retrofit_work_order(work_order["id"], PLANNER)
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE)
    assert refused.status_code == 409

    still_reset = validate_success(api_client.get_lease_fleet_car(car_id, PLANNER))
    assert still_reset["regulatory_life_end_date"] == "2051-09-20", (
        "the refused second completion re-applied neither cascade"
    )
    still_costed = validate_success(
        api_client.get_retrofit_program(program_id, RETROFIT)
    )
    assert still_costed["program_cost_cents"] == 1865000


def test_open_and_restated_per_diem_variants_diverge_on_one_unchanged_rate(api):
    """PRD §3.6: "The accrual window ends at the placement's `end_date` when the
    placement is `COMPLETED` or `REASSIGNED`, and at the logical clock's current
    date otherwise.  The number of days is that end minus the `start_date`, with
    the end date exclusive, and the gross accrual is those days multiplied by
    the placement's snapshotted `per_diem_rate_cents`."
    PRD §3.6: "A restated accrual is produced whenever the placement history is
    rewritten rather than merely continued — after a contract amendment, after a
    reassignment, or at a return.  The restated basis walks every placement of
    the same car in `start_date` ascending order, breaking ties by `created_at`
    ascending, clips each interval to the governing contract's `term_start_date`
    up to but not including its `term_end_date`, and clips it again to the window
    from 365 days before the current clock date up to but not including the
    current clock date."
    PRD §3.5: "First, the newly ratified `per_diem_rate_cents` is refreshed onto
    every placement referencing this contract whose status is `ACTIVE`, and each
    such placement's `per_diem_accrued_cents` is recomputed by the accrual rule
    of §3.6".

    The placement opens 2024-06-01 and is still ACTIVE at the 2026-09-01 clock,
    so the open basis accrues 822 days at 10000 cents; the restated basis clips
    the same interval to [2025-09-01, 2026-09-01) and accrues 365 days.  The
    lessee's utilization threshold sits above the placement's zero utilization,
    so the utilization credit is zero in both readings.

    Design: Corner/cross_cutting_complexity_layers/dual_variant_assignment_per_diem_current_open_vs_restated_chronological
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(
        model_code="CT-DV-1",
        build_hours=1,
        regulatory_life_years=25,
        line_count_family="LINE-DV",
        wheelset_part_number="WS-DV-1",
        wheelset_unit_cost_cents=1000,
        wheelset_lead_time_days=5,
        wheelset_qty_per_car=1,
        casting_part_number="CS-DV-1",
        casting_unit_cost_cents=2000,
        casting_lead_time_days=6,
        casting_qty_per_car=1,
        include_coating=False,
        on_hand_qty=10,
    )
    commercial = create_lessee_and_contract(
        legal_name="LESS-DV-1",
        credit_tier="A",
        utilization_threshold_pct=50,
        credit_ceiling_cents=500_000_000,
        lease_type="FULL_SERVICE",
        per_diem_rate_cents=10000,
        liability_bearer="LESSOR",
        term_start_date="2024-01-01",
        term_end_date="2028-01-01",
        fleet_car_cap=10,
    )
    order = create_order(
        catalogue,
        quantity=1,
        disposition="RETAINED",
        priority_rank=1,
        order_date="2024-01-01",
        required_delivery_date="2024-01-20",
    )
    reserve_order(order["id"])
    release_order(order["id"])
    start_production(order["id"], "LINE-DV", window_start="2024-01-01")
    complete_order(order["id"], completion_date="2024-01-02")

    cars = validate_success(
        api_client.list_lease_fleet_cars(
            LEASE, {"production_order_id": order["id"], "limit": 10}
        )
    )
    assert len(cars) == 1

    assignment = create_assignment(
        cars[0],
        commercial["contract"],
        commercial["lessee"],
        start_date="2024-06-01",
        end_date="2027-01-01",
        mileage_allowance=1000,
    )
    assert assignment["per_diem_rate_cents"] == 10000, (
        "the placement snapshots the contract's rate at creation"
    )

    open_view = validate_success(
        api_client.get_car_assignment(assignment["id"], LEASE)
    )
    assert open_view["per_diem_accrued_cents"] == 8220000, (
        "822 days from 2024-06-01 to the 2026-09-01 clock, at 10000 cents"
    )

    current = validate_success(
        api_client.get_lease_contract(commercial["contract"]["id"], LEASE)
    )
    drafted = validate_success(
        api_client.draft_lease_amendment(
            commercial["contract"]["id"],
            {
                "per_diem_rate_cents": 10000,
                "liability_bearer": "LESSEE",
                "expected_lease_version": current["version"],
            },
            LEASE,
        )
    )
    assert drafted["status"] == "AMENDMENT_DRAFTED"

    ratified = validate_success(
        api_client.ratify_lease_amendment(
            commercial["contract"]["id"],
            {"expected_lease_version": drafted["version"]},
            LEASE,
        )
    )
    assert ratified["status"] == "ACTIVE"
    assert ratified["amendment_seq"] == 1
    assert ratified["per_diem_rate_cents"] == 10000, (
        "the amendment restates the same rate, so only the window changes"
    )

    restated = validate_success(
        api_client.get_car_assignment(assignment["id"], LEASE)
    )
    assert restated["per_diem_accrued_cents"] == 3650000, (
        "365 days clipped to [2025-09-01, 2026-09-01), at the same 10000 cents"
    )
    assert restated["status"] == "ACTIVE", "the restatement does not close the placement"

    delta = open_view["per_diem_accrued_cents"] - restated["per_diem_accrued_cents"]
    assert delta == 4570000, (
        "the whole difference is the 457-day clip, not a rate change"
    )


def test_scheduled_estimate_and_completed_actual_converge_after_a_cancellation(api):
    """PRD §3.8: "On the scheduled estimate used while the program is `PLANNED`
    or `IN_PROGRESS`, every work order of the program that is not in `CANCELLED`
    status contributes.  On the completed actual used once the program is
    `COMPLETED`, only work orders in `COMPLETED` status contribute — so a work
    order cancelled in the middle of a program reduces the program cost rather
    than leaving an estimate behind."
    PRD §3.8: "Each contributing work order adds its `shop_days` multiplied by
    the shop-day rate of 185,000 cents, plus its `component_qty_consumed`
    multiplied by the unit cost of the program's required component when a
    `required_component_id` is set."
    PRD §3.8: "A scheduled work order that has not started may instead be
    cancelled, which sets it to `CANCELLED`, increments its `version`, and
    re-derives the program cost."

    Each work order books the mandate's 10 shop days and consumes 3 kit units at
    5000 cents, so it contributes 10 * 185000 + 3 * 5000 = 1865000 cents; the
    pair of live orders reads 3730000.

    Design: Corner/cross_cutting_complexity_layers/dual_variant_retrofit_program_cost_scheduled_estimate_vs_completed_actual
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(
        model_code="CT-DV2-1",
        build_hours=1,
        regulatory_life_years=25,
        line_count_family="LINE-DV2",
        wheelset_part_number="WS-DV2-1",
        wheelset_unit_cost_cents=1000,
        wheelset_lead_time_days=5,
        wheelset_qty_per_car=1,
        casting_part_number="CS-DV2-1",
        casting_unit_cost_cents=2000,
        casting_lead_time_days=6,
        casting_qty_per_car=1,
        coating_part_number="CO-DV2-1",
        coating_unit_cost_cents=5000,
        coating_qty_per_car=1,
        coating_lead_time_days=30,
        on_hand_qty=10,
    )
    fleet = setup_retained_order_with_fleet_cars(
        car_count=2,
        catalogue=catalogue,
        order_date="2026-09-01",
        required_delivery_date="2026-09-20",
        changeover_start="2026-09-02",
        completion_date="2026-09-04",
    )
    assert len(fleet["cars"]) == 2

    program_world = create_retrofit_program(
        catalogue,
        mandate_code="MAND-DV2-1",
        compliance_deadline_date="2026-12-31",
        required_shop_days_per_car=10,
        required_component_id=catalogue["coating"]["id"],
    )
    program = program_world["program"]
    work_order_one = create_work_order(
        program,
        fleet["cars"][0],
        shop_line="SL-DV2-1",
        scheduled_start_date="2026-09-10",
        component_qty_consumed=3,
    )
    work_order_two = create_work_order(
        program,
        fleet["cars"][1],
        shop_line="SL-DV2-2",
        scheduled_start_date="2026-09-10",
        component_qty_consumed=3,
    )
    assert work_order_one["shop_days"] == 10

    started = validate_success(
        api_client.start_retrofit_program(program["id"], RETROFIT)
    )
    assert started["status"] == "IN_PROGRESS"
    assert started["program_cost_cents"] == 3730000, (
        "two live work orders at 10 * 185000 + 3 * 5000 each"
    )

    # PRD 3.8: "Completion is legal from IN_PROGRESS" — the first work order has
    # to be started before the completed-actual leg of the variant can run.
    started_one = validate_success(
        api_client.start_retrofit_work_order(work_order_one["id"], PLANNER)
    )
    assert started_one["status"] == "IN_PROGRESS"

    completed = validate_success(
        api_client.complete_retrofit_work_order(work_order_one["id"], PLANNER)
    )
    assert completed["status"] == "COMPLETED"

    while_running = validate_success(
        api_client.get_retrofit_program(program["id"], RETROFIT)
    )
    assert while_running["program_cost_cents"] == 3730000, (
        "a completed work order still counts while the sibling is live"
    )

    cancelled = validate_success(
        api_client.cancel_retrofit_work_order(
            work_order_two["id"], PLANNER, {"reason": "Line taken out of service"}
        )
    )
    assert cancelled["status"] == "CANCELLED"

    after_cancel = validate_success(
        api_client.get_retrofit_program(program["id"], RETROFIT)
    )
    assert after_cancel["program_cost_cents"] == 1865000, (
        "the cancelled work order's estimate is withdrawn"
    )
    assert started["program_cost_cents"] - after_cancel["program_cost_cents"] == 1865000

    closed = validate_success(
        api_client.complete_retrofit_program(program["id"], RETROFIT)
    )
    assert closed["status"] == "COMPLETED"
    assert closed["program_cost_cents"] == 1865000, (
        "the completed actual counts only the completed work order"
    )


def test_reserved_qty_is_rederived_from_released_orders_not_patched_by_receipt(api):
    """PRD §3.2: "For a given component, the reservation term is the sum, over
    every bill-of-material row that names that component, of the row's
    `qty_per_car` multiplied by the total quantity of production orders that
    build that row's car type and are in `RELEASED` status; orders in `DRAFT`,
    `COMPONENT_RESERVED`, `COMPLETED` or `CANCELLED` contribute nothing."
    PRD §3.2: "`COATING` rows are exempt from the on-hand test — they are
    procured to contract and commit through the purchase-receipt path instead —
    but they are not exempt from the lead-time gate of §3.1."
    PRD §3.2: "On success the purchase order becomes `RECEIVED`, the component's
    `on_hand_qty` is increased by `qty_received`, and `reserved_qty` and
    `shortfall_qty` are recomputed by the allocation rule above."
    PRD §2.10: "Derived fields are recomputed from scratch, never patched
    incrementally, so that any sequence of operations converges on the same
    value."

    The order builds three cars and its car type consumes two coating units per
    car, so the reservation term is 2 * 3 = 6 once the order is RELEASED; the
    later receipt lifts the authoritative on-hand figure by ten and leaves the
    reservation term exactly where it stood.

    Design: Corner/cross_cutting_complexity_layers/derived_component_reserved_qty_rederived_not_patched_by_receipt
    """
    set_clock("2026-09-01T00:00:00Z")
    world = _single_coating_catalogue(
        "CT-DF-1", "LINE-DF", "CO-DF-1", unit_cost_cents=1000, qty_per_car=2
    )
    coating_id = world["coating"]["id"]

    at_create = validate_success(api_client.get_component(coating_id, SUPPLY))
    assert at_create["on_hand_qty"] == 0, "no opening quantity was supplied"
    assert at_create["reserved_qty"] == 0

    receive_component_stock(
        world["coating"], 6, order_date="2026-09-01", receipt_date="2026-09-06"
    )
    stocked = validate_success(api_client.get_component(coating_id, SUPPLY))
    assert stocked["on_hand_qty"] == 6

    # A second purchase order is confirmed but not yet received; it is what
    # release needs as the coating row's committed supply.
    second_purchase = receive_component_stock(
        world["coating"],
        10,
        order_date="2026-09-01",
        receipt_date="2026-09-06",
        apply_receipt=False,
    )
    assert second_purchase["purchase_order"]["status"] == "CONFIRMED"

    order = create_order(
        world,
        quantity=3,
        disposition="RETAINED",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-10-01",
    )
    reserved = reserve_order(order["id"])
    assert reserved["status"] == "COMPONENT_RESERVED"

    after_reserve = validate_success(api_client.get_component(coating_id, SUPPLY))
    assert after_reserve["on_hand_qty"] == 6, (
        "a coating row commits through the purchase-receipt path, not by "
        "draining on-hand stock at reservation"
    )
    assert after_reserve["reserved_qty"] == 0, (
        "the reservation term counts only RELEASED orders, and this one has "
        "not been released"
    )

    released = release_order(order["id"])
    assert released["status"] == "RELEASED"

    after_release = validate_success(api_client.get_component(coating_id, SUPPLY))
    assert after_release["reserved_qty"] == 6, "2 units per car * 3 cars"
    assert after_release["on_hand_qty"] == 6

    receipt = validate_success(
        api_client.create_component_receipt(
            create_component_receipt_payload(
                component_purchase_order_id=second_purchase["purchase_order"]["id"],
                component_id=coating_id,
                qty_received=10,
                receipt_date="2026-09-06",
            ),
            SUPPLY,
        ),
        expected_status=201,
    )

    after_booking = validate_success(api_client.get_component(coating_id, SUPPLY))
    assert after_booking["on_hand_qty"] == 6, "booking alone moves no stock"
    assert after_booking["reserved_qty"] == 6, "the derived term has not moved"

    validate_success(api_client.receive_component_receipt(receipt["id"], SUPPLY))

    closed = validate_success(
        api_client.get_component_purchase_order(
            second_purchase["purchase_order"]["id"], SUPPLY
        )
    )
    assert closed["status"] == "RECEIVED"

    final = validate_success(api_client.get_component(coating_id, SUPPLY))
    assert final["on_hand_qty"] == 16, "6 on hand plus the 10 units received"
    assert final["reserved_qty"] == 6, (
        "the receipt re-derives the reservation term from the released-order "
        "set rather than decrementing it"
    )


def test_retrofit_required_flag_tracks_the_covering_programs_lifecycle(api):
    """PRD §2.8: "A car's `retrofit_required` flag is derived too: it is true
    while the car is enrolled in a retrofit program whose status is
    `IN_PROGRESS` and whose `compliance_deadline_date` has not yet passed, and
    false otherwise."
    PRD §3.8: "On success the program becomes `IN_PROGRESS`, the
    `retrofit_required` flag is set to true on every fleet car of a covered car
    type whose status is `HELD` or `UNDER_REPAIR`, and the program's
    `program_cost_cents` is re-derived by the cost rule below."
    PRD §3.8: "Voiding is the abandonment path: it is legal from `IN_PROGRESS`,
    accepts an optional `reason`, sets the program to `VOIDED`, sets every work
    order of the program to `CANCELLED`, and sets `retrofit_required` to false
    on every enrolled car."

    No work order is ever raised, so the flag is shown to track the program's
    own state rather than any shop-work state.

    Design: Corner/cross_cutting_complexity_layers/derived_lease_fleet_car_retrofit_required_across_program_lifecycle
    """
    set_clock("2026-09-01T00:00:00Z")
    world = _single_coating_catalogue(
        "CT-DF2-1",
        "LINE-DF2",
        "CO-DF2-1",
        qty_per_car=1,
        purchase_qty=5,
        expected_receipt_date="2026-09-06",
    )
    order = create_order(
        world,
        quantity=1,
        disposition="RETAINED",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-09-20",
    )
    reserve_order(order["id"])
    release_order(order["id"])
    start_production(order["id"], "LINE-DF2", window_start="2026-09-02")
    complete_order(order["id"], completion_date="2026-09-04")

    cars = validate_success(
        api_client.list_lease_fleet_cars(
            PLANNER, {"production_order_id": order["id"], "limit": 10}
        )
    )
    assert len(cars) == 1
    car_id = cars[0]["id"]
    assert cars[0]["status"] == "HELD"
    assert cars[0]["retrofit_required"] is False, (
        "no mandate covers this car yet"
    )

    mandate = create_retrofit_program(
        world,
        mandate_code="MAND-DF2-1",
        compliance_deadline_date="2026-12-31",
        required_shop_days_per_car=4,
    )
    assert mandate["program"]["status"] == "PLANNED"

    started = validate_success(
        api_client.start_retrofit_program(mandate["program"]["id"], RETROFIT)
    )
    assert started["status"] == "IN_PROGRESS"

    enrolled = validate_success(api_client.get_lease_fleet_car(car_id, RETROFIT))
    assert enrolled["retrofit_required"] is True, (
        "starting the covering mandate enrolls the HELD car of the covered type"
    )

    voided = validate_success(
        api_client.void_retrofit_program(
            mandate["program"]["id"], RETROFIT, {"reason": "Mandate withdrawn"}
        )
    )
    assert voided["status"] == "VOIDED"

    released_flag = validate_success(api_client.get_lease_fleet_car(car_id, RETROFIT))
    assert released_flag["retrofit_required"] is False, (
        "the flag follows the source program back down rather than latching"
    )


def test_order_unit_price_is_rederived_when_an_endorsement_is_approved(api):
    """PRD §3.3: "On success the endorsement becomes `APPROVED`, the production
    order's `unit_price_cents` is recomputed on the committed basis of §3.1 with
    the endorsed substitute standing in for the original component, and the
    endorsement's own `version` and `updated_at` move."
    PRD §3.1: "Endorsements in `PENDING`, `REJECTED` or `SUPERSEDED` status are
    excluded from that substitution set entirely and never affect the quote."
    PRD §3.1: "The change-fee cap is 8 percent of the unrounded total, floored to
    a whole cent.  The raw change fee is 15,000 cents multiplied by the number
    of endorsements on this order whose status is `APPROVED` or `APPLIED`.  The
    change fee actually charged is the smaller of the raw fee and the cap".

    With build_hours 1, one wheelset at 1000 cents and one casting at 2000 cents
    per car, the draft quote is ceil(26000 / 100) * 100 + ceil(27000 / 100) * 100
    + 45000 = 98000 cents.  Approving a 3000-cent substitute moves the wheelset
    line to 28000 and the unrounded total to 100000, so the fee is
    min(15000, floor(100000 * 8 / 100)) = 8000 and the price becomes 108000.

    Design: Corner/cross_cutting_complexity_layers/derived_production_order_unit_price_after_endorsement_approval
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(
        model_code="CT-DF3-1",
        build_hours=1,
        regulatory_life_years=25,
        line_count_family="LINE-DF3",
        wheelset_part_number="WS-DF3-A",
        wheelset_unit_cost_cents=1000,
        wheelset_lead_time_days=5,
        wheelset_qty_per_car=1,
        casting_part_number="CS-DF3-1",
        casting_unit_cost_cents=2000,
        casting_lead_time_days=6,
        casting_qty_per_car=1,
        include_coating=False,
        on_hand_qty=1000,
    )
    substitute = validate_success(
        api_client.create_component(
            create_component_payload(
                part_number="WS-DF3-B",
                component_class="WHEELSET",
                unit_cost_cents=3000,
                lead_time_days=5,
                on_hand_qty=1000,
            ),
            SUPPLY,
        ),
        expected_status=201,
    )
    order = create_order(
        catalogue,
        quantity=1,
        disposition="RETAINED",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-09-20",
    )
    assert order["unit_price_cents"] == 98000, (
        "26000 + 27000 component lines plus 45000 labor, with no change fee"
    )

    maker = build_user_headers("user-df3-maker", "ProductionPlanner")
    checker = build_user_headers("user-df3-checker", "LeaseAdministrator")
    endorsement = create_endorsement(
        order,
        catalogue["wheelset"],
        substitute,
        substitute_qty_per_car=1,
        decides_material=False,
        headers=maker,
    )
    assert endorsement["status"] == "PENDING"

    pending = validate_success(api_client.get_production_order(order["id"], PLANNER))
    assert pending["unit_price_cents"] == 98000, (
        "a PENDING endorsement is outside the substitution set and never "
        "affects the quote"
    )

    approved = approve_endorsement(endorsement["id"], checker)
    assert approved["status"] == "APPROVED"

    repriced = validate_success(api_client.get_production_order(order["id"], PLANNER))
    assert repriced["unit_price_cents"] == 108000, (
        "28000 substituted line + 27000 casting line + 45000 labor + the "
        "8000-cent capped change fee"
    )
    assert repriced["unit_price_cents"] - pending["unit_price_cents"] == 10000, (
        "2000 cents of substitute line delta plus 8000 cents of capped fee"
    )
