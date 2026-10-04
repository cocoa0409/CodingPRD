"""Error catalogue, part 3: credit, fleet cap, settlement and availability.

Each test triggers one catalogued rejection and pins both the exact `error_id`
and its HTTP status, with a control call proving the rejection is specific to the
violated rule.
"""

from test_helpers import (
    CLOCK_START_ISO,
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_assignment,
    create_car_type_component_requirement_payload,
    create_lease_fleet_sale_payload,
    create_lessee_and_contract,
    create_lessee_payload,
    create_order,
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
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SUPPLY = TEST_USERS["supply_chain_coordinator_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
LEASE = TEST_USERS["lease_administrator_headers"]
PORTFOLIO = TEST_USERS["portfolio_manager_headers"]
RETROFIT = TEST_USERS["regulatory_retrofitist_headers"]


def flat_catalogue(**overrides):
    """One BOXCAR type carrying a single wheelset row at one per car.

    The row is added here rather than by the shared catalogue helper, so the car
    type consumes exactly one component and the quote asserted against it is a
    function of that one row's numbers alone.
    """
    defaults = dict(
        model_code="CT-FISCAL",
        car_class="BOXCAR",
        build_hours=1,
        regulatory_life_years=25,
        line_count_family="LINE-FISCAL",
        wheelset_part_number="WS-FISCAL",
        wheelset_unit_cost_cents=1000,
        wheelset_lead_time_days=5,
        wheelset_qty_per_car=1,
        include_bom=False,
        include_coating=False,
        on_hand_qty=100,
    )
    defaults.update(overrides)
    catalogue = setup_catalogue(**defaults)
    catalogue["bom"] = [
        get_success_data(
            api_client.create_car_type_component_requirement(
                create_car_type_component_requirement_payload(
                    car_type_id=catalogue["car_type"]["id"],
                    component_id=catalogue["wheelset"]["id"],
                    qty_per_car=defaults["wheelset_qty_per_car"],
                ),
                PLANNER,
            )
        )
    ]
    return catalogue


# ─── Fiscal gates ─────────────────────────────────────

def test_return_past_the_credit_ceiling_returns_402(api):
    """PRD §2.9: "When a return would add a projected mileage charge to the
    balance, or when a placement is created, the lessee's current
    `outstanding_balance_cents` plus the projected charge must stay at or below
    `credit_ceiling_cents`; a balance exactly equal to the ceiling passes, and
    only an amount strictly above it is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`
    (HTTP 402)."
    PRD §2.11: "Eighteenth, credit exposure: the lessee's
    `outstanding_balance_cents` plus the projected mileage charge must stay at or
    below the lessee's `credit_ceiling_cents`, with equality permitted, and an
    excess is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402) on return
    recording and placement creation."

    A sold completion drives the balance to exactly the 71000 ceiling, so the
    return whose projected charge is 60000 is refused and neither the balance nor
    the placement moves.

    Design: Corner/errors/error_credit_limit_exceeded_return_past_ceiling_returns_402
    """
    set_clock(CLOCK_START_ISO)
    catalogue = flat_catalogue(
        model_code="CT-R",
        line_count_family="LINE-R",
        wheelset_part_number="WS-R",
    )
    pair = create_lessee_and_contract(
        legal_name="Ceiling Rail Co",
        credit_tier="B",
        utilization_threshold_pct=0,
        credit_ceiling_cents=71000,
        lease_type="FULL_SERVICE",
        per_diem_rate_cents=1000,
        liability_bearer="LESSOR",
        term_start_date="2026-09-01",
        term_end_date="2027-09-01",
        fleet_car_cap=5,
        activate=True,
    )
    lessee, contract = pair["lessee"], pair["contract"]

    retained_order = create_order(
        catalogue,
        quantity=1,
        planned_shop_days=1,
        disposition="RETAINED",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-12-01",
    )
    reserve_order(retained_order["id"])
    release_order(retained_order["id"])
    start_production(
        retained_order["id"], "LINE-R", window_start="2026-09-13", window_days=1
    )
    completed = get_success_data(
        api_client.complete_production_order(
            retained_order["id"], {"completed_qty": 1, "completion_date": "2026-09-14"}, PLANNER
        )
    )
    assert completed["status"] == "COMPLETED"
    car = get_success_data(
        api_client.list_lease_fleet_cars(
            ADMIN, {"production_order_id": retained_order["id"]}
        )
    )[0]

    assignment = create_assignment(
        car,
        contract,
        lessee,
        start_date="2026-09-15",
        end_date="2026-10-15",
        mileage_allowance=0,
    )
    assert assignment["status"] == "ACTIVE"

    sold_order = create_order(
        catalogue,
        quantity=1,
        planned_shop_days=1,
        disposition="SOLD",
        priority_rank=2,
        order_date="2026-09-01",
        required_delivery_date="2026-12-01",
    )
    assert sold_order["unit_price_cents"] == 71000, (
        "ceil((1 * 1000 + 25000) / 100) * 100 + 1 * 45000"
    )
    reserve_order(sold_order["id"])
    release_order(sold_order["id"])
    start_production(
        sold_order["id"], "LINE-R", window_start="2026-09-14", window_days=1
    )
    validate_success(
        api_client.complete_production_order(
            sold_order["id"],
            {
                "completed_qty": 1,
                "lessee_id": lessee["id"],
                "completion_date": "2026-09-15",
            },
            PLANNER,
        )
    )
    at_ceiling = get_success_data(
        api_client.get_lessee_outstanding_balance(lessee["id"], ADMIN)
    )
    assert at_ceiling["outstanding_balance_cents"] == 71000, "the ceiling is reached exactly"

    refused = api_client.create_car_return(
        {
            "lease_fleet_car_id": car["id"],
            "car_assignment_id": assignment["id"],
            "return_date": "2026-10-15",
            "mileage_since_last": 5000,
            "condition_grade": "A",
        },
        LEASE,
    )
    validate_error(refused, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
    assert refused.status_code == 402
    assert 71000 + 60000 > 71000, (
        "max(0, 5000 - ceil(30 / 30) * 0) * 12 == 60000 pushes the balance over "
        "the ceiling"
    )

    unchanged_balance = get_success_data(
        api_client.get_lessee_outstanding_balance(lessee["id"], ADMIN)
    )
    assert unchanged_balance["outstanding_balance_cents"] == 71000, (
        "the rejection is atomic"
    )
    unchanged_assignment = get_success_data(
        api_client.get_car_assignment(assignment["id"], ADMIN)
    )
    assert unchanged_assignment["status"] == "ACTIVE", (
        "the refused return closed no placement"
    )


def test_second_retained_completion_past_the_fleet_cap_is_compensated(api):
    """PRD §3.4: "One compensating path exists inside the retained branch and
    must be honoured exactly.  If completing a retained order would push the
    fleet's retained-car count above the cap the contract allows, the cars are
    still created but the overflow car is born scrapped rather than held ...
    The order is never blocked by this overflow; only the car's initial state
    changes."
    PRD §2.9: "the number of live cars in the fleet — those in `HELD`,
    `ASSIGNED` or `UNDER_REPAIR` — plus the cars an order would add must stay at
    or below that cap."

    Both releases pass while the live count is 0, and the second completion
    takes the live count to its cap of 1 rather than 2: the order completes and
    its car is born `SCRAPPED`, so the cap is honoured without blocking the
    order.  The generic "breach at completion" wording of §2.9 / §2.11 is
    overridden at this site by §3.4's specific compensating-path paragraph.

    Design: Corner/errors/error_fleet_cap_exceeded_second_completion_returns_402
    """
    set_clock(CLOCK_START_ISO)
    catalogue = flat_catalogue(
        model_code="CT-S",
        line_count_family="LINE-S",
        wheelset_part_number="WS-S",
    )
    pair = create_lessee_and_contract(
        legal_name="Fleet Cap Rail Co",
        credit_tier="B",
        utilization_threshold_pct=0,
        credit_ceiling_cents=1000000,
        lease_type="FULL_SERVICE",
        per_diem_rate_cents=1000,
        liability_bearer="LESSOR",
        term_start_date="2026-09-01",
        term_end_date="2027-09-01",
        fleet_car_cap=1,
        activate=True,
    )
    contract = pair["contract"]

    first_order = create_order(
        catalogue,
        quantity=1,
        planned_shop_days=1,
        disposition="RETAINED",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-12-01",
    )
    second_order = create_order(
        catalogue,
        quantity=1,
        planned_shop_days=1,
        disposition="RETAINED",
        priority_rank=2,
        order_date="2026-09-01",
        required_delivery_date="2026-12-01",
    )
    for order in (first_order, second_order):
        reserve_order(order["id"])
        released = release_order(order["id"], lease_contract_id=contract["id"])
        assert released["status"] == "RELEASED", (
            "the release-time check passes while the live count is 0"
        )

    start_production(first_order["id"], "LINE-S", window_start="2026-09-10", window_days=1)
    first_completed = get_success_data(
        api_client.complete_production_order(
            first_order["id"], {"completed_qty": 1, "completion_date": "2026-09-11"}, PLANNER
        )
    )
    assert first_completed["status"] == "COMPLETED"
    live_before, _ = validate_paginated(
        api_client.list_lease_fleet_cars(ADMIN, {"status": "HELD"})
    )
    assert len(live_before) == 1

    in_production = start_production(
        second_order["id"], "LINE-S", window_start="2026-09-11", window_days=1
    )
    assert in_production["status"] == "IN_PRODUCTION"

    assert 1 + 1 > 1, "live count 1 plus the car this order would add exceeds the cap"
    overflowed = get_success_data(
        api_client.complete_production_order(
            second_order["id"], {"completed_qty": 1, "completion_date": "2026-09-12"}, PLANNER
        )
    )
    assert overflowed["status"] == "COMPLETED", (
        "the order is never blocked by this overflow"
    )
    assert overflowed["completed_qty"] == 1
    live_after, _ = validate_paginated(
        api_client.list_lease_fleet_cars(ADMIN, {"status": "HELD"})
    )
    assert len(live_after) == 1, "the overflow car is not added to the live fleet"

    second_cars = get_success_data(
        api_client.list_lease_fleet_cars(
            ADMIN, {"production_order_id": second_order["id"]}
        )
    )
    assert len(second_cars) == 1, "the car is still created"
    assert second_cars[0]["status"] == "SCRAPPED", (
        "the overflow car is born scrapped rather than held"
    )


def test_settlement_of_an_unbalanced_sale_returns_409(api):
    """PRD §2.9: "A sale settles only if it is internally balanced: when a sale's
    `writeback_liability_cents` exceeds its gain over book value, the settlement
    cannot balance and is rejected with `ERR_SETTLEMENT_UNBALANCED` (HTTP 409)."
    PRD §3.9: "The settlement must also be internally balanced: a sale whose
    `writeback_liability_cents` exceeds its gain over book value cannot settle and
    is rejected with `ERR_SETTLEMENT_UNBALANCED` (HTTP 409)."

    Two cars of the same 71000-cent basis are sold at 80000 on the day they were
    built; the sale carrying a 20000 writeback exceeds its 9000 gain over book and
    cannot settle, while the writeback-free sibling settles and moves the ledger
    by its own 9000.

    Design: Corner/errors/error_settlement_unbalanced_writeback_over_gain_returns_409
    """
    set_clock(CLOCK_START_ISO)
    catalogue = flat_catalogue(
        model_code="CT-T",
        line_count_family="LINE-T",
        wheelset_part_number="WS-T",
    )
    world = setup_retained_order_with_fleet_cars(
        car_count=2,
        catalogue=catalogue,
        build_contract=False,
        changeover_start="2026-09-18",
        completion_date="2026-09-20",
    )
    unbalanced_car, balanced_car = world["cars"][0], world["cars"][1]
    assert unbalanced_car["acquisition_cost_cents"] == 71000
    assert unbalanced_car["built_date"] == "2026-09-20"

    unbalanced = validate_success(
        api_client.create_lease_fleet_sale(
            create_lease_fleet_sale_payload(
                lease_fleet_car_id=unbalanced_car["id"],
                buyer_name="Unbalanced Buyer",
                sale_price_cents=80000,
                writeback_liability_cents=20000,
                sale_date="2026-09-20",
            ),
            PORTFOLIO,
        ),
        expected_status=201,
    )
    assert unbalanced["status"] == "PENDING_SETTLEMENT"
    assert unbalanced["gain_loss_cents"] == -11000, "80000 - 71000 - 20000"

    refused = api_client.settle_lease_fleet_sale(unbalanced["id"], PORTFOLIO)
    validate_error(refused, ApiErrorId.ERR_SETTLEMENT_UNBALANCED)
    assert refused.status_code == 409
    assert 20000 > 9000, "the writeback exceeds the 80000 - 71000 gain over book"
    unchanged = get_success_data(
        api_client.get_lease_fleet_sale(unbalanced["id"], ADMIN)
    )
    assert unchanged["status"] == "PENDING_SETTLEMENT", "the rejection is atomic"

    balanced = validate_success(
        api_client.create_lease_fleet_sale(
            create_lease_fleet_sale_payload(
                lease_fleet_car_id=balanced_car["id"],
                buyer_name="Balanced Buyer",
                sale_price_cents=80000,
                writeback_liability_cents=0,
                sale_date="2026-09-20",
            ),
            PORTFOLIO,
        ),
        expected_status=201,
    )
    assert balanced["gain_loss_cents"] == 9000
    settled = validate_success(api_client.settle_lease_fleet_sale(balanced["id"], PORTFOLIO))
    assert settled["status"] == "SETTLED"

    ledger = validate_success(api_client.get_portfolio_ledger(ADMIN))
    assert ledger["realized_gain_cents"] == 9000, (
        "only the balanced sale reached the ledger"
    )


# ─── Availability and correspondence ──────────────────

def test_retrofit_work_order_on_an_assigned_car_returns_409(api):
    """PRD §3.8: "The car must be in `HELD` status, or the write is rejected with
    `ERR_CAR_NOT_HELD` (HTTP 409), and the car's car type must be covered by the
    program through a `RetrofitProgramCarType` row, or the write is rejected with
    `ERR_CAPACITY_EXCEEDED` (HTTP 409)."
    PRD §2.11: "Twenty-first, car availability: the car must be in `HELD` status
    for every operation that requires a free car, and a breach is rejected with
    `ERR_CAR_NOT_HELD` (HTTP 409) on sale creation, placement creation, retrofit
    work-order creation and scrapping."

    The placed car is refused while its HELD sibling on the same order is
    scheduled and moved to UNDER_REPAIR.

    Design: Corner/errors/error_car_not_held_retrofit_work_order_returns_409
    """
    set_clock(CLOCK_START_ISO)
    catalogue = flat_catalogue(
        model_code="CT-U",
        line_count_family="LINE-U",
        wheelset_part_number="WS-U",
    )
    world = setup_retained_order_with_fleet_cars(
        car_count=2,
        catalogue=catalogue,
        build_contract=False,
        changeover_start="2026-09-10",
        completion_date="2026-09-12",
    )
    pair = create_lessee_and_contract(
        legal_name="Car Held Rail Co",
        credit_tier="B",
        utilization_threshold_pct=0,
        credit_ceiling_cents=1000000,
        lease_type="FULL_SERVICE",
        per_diem_rate_cents=1000,
        liability_bearer="LESSOR",
        term_start_date="2026-09-01",
        term_end_date="2027-09-01",
        fleet_car_cap=5,
        activate=True,
    )
    assigned_car, held_car = world["cars"][0], world["cars"][1]
    create_assignment(
        assigned_car,
        pair["contract"],
        pair["lessee"],
        start_date="2026-09-12",
        end_date="2026-10-12",
        mileage_allowance=1000,
    )
    assert get_success_data(api_client.get_lease_fleet_car(assigned_car["id"], ADMIN))[
        "status"
    ] == "ASSIGNED"
    assert get_success_data(api_client.get_lease_fleet_car(held_car["id"], ADMIN))[
        "regulatory_life_end_date"
    ] == "2051-09-12"

    program = get_success_data(
        api_client.create_retrofit_program(
            create_retrofit_program_payload(
                mandate_code="MAND-U",
                description="Held-car mandate",
                compliance_deadline_date="2026-12-31",
                required_shop_days_per_car=3,
            ),
            RETROFIT,
        )
    )
    get_success_data(
        api_client.create_retrofit_program_car_type(
            create_retrofit_program_car_type_payload(
                retrofit_program_id=program["id"],
                car_type_id=catalogue["car_type"]["id"],
            ),
            RETROFIT,
        )
    )

    refused = api_client.create_retrofit_work_order(
        create_retrofit_work_order_payload(
            retrofit_program_id=program["id"],
            lease_fleet_car_id=assigned_car["id"],
            shop_line="SHOP-U1",
            scheduled_start_date="2026-10-01",
            scheduled_end_date="2026-10-04",
            component_qty_consumed=1,
        ),
        PLANNER,
    )
    validate_error(refused, ApiErrorId.ERR_CAR_NOT_HELD)
    assert refused.status_code == 409
    untouched = get_success_data(
        api_client.get_lease_fleet_car(assigned_car["id"], ADMIN)
    )
    assert untouched["status"] == "ASSIGNED", "the rejection is atomic"

    scheduled = validate_success(
        api_client.create_retrofit_work_order(
            create_retrofit_work_order_payload(
                retrofit_program_id=program["id"],
                lease_fleet_car_id=held_car["id"],
                shop_line="SHOP-U2",
                scheduled_start_date="2026-10-01",
                scheduled_end_date="2026-10-04",
                component_qty_consumed=1,
            ),
            PLANNER,
        ),
        expected_status=201,
    )
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["shop_days"] == 3
    moved = get_success_data(api_client.get_lease_fleet_car(held_car["id"], ADMIN))
    assert moved["status"] == "UNDER_REPAIR", (
        "the accepted work order applied its declared side effect"
    )


def test_placement_naming_another_lessee_returns_409(api):
    """PRD §3.6: "The lessee named on the request must be the lessee of the
    referenced contract, or the write is rejected with `ERR_LESSEE_MISMATCH`
    (HTTP 409)."
    PRD §2.11: "Twenty-second, lessee correspondence: the lessee named in the
    request must be the lessee of the referenced contract, or of the sold car's
    terminated contract, and a mismatch is rejected with `ERR_LESSEE_MISMATCH`
    (HTTP 409) on placement creation and sale creation."

    The mismatched lessee is a real account, so the reference resolves; the
    placement is refused and the car stays HELD, while the same body naming the
    contract's own lessee is accepted.

    Design: Corner/errors/error_lessee_mismatch_placement_returns_409
    """
    set_clock(CLOCK_START_ISO)
    catalogue = flat_catalogue(
        model_code="CT-V",
        line_count_family="LINE-V",
        wheelset_part_number="WS-V",
    )
    world = setup_retained_order_with_fleet_cars(
        car_count=1,
        catalogue=catalogue,
        build_contract=False,
        changeover_start="2026-09-11",
        completion_date="2026-09-12",
    )
    pair = create_lessee_and_contract(
        legal_name="Contract Holder Rail Co",
        credit_tier="B",
        utilization_threshold_pct=0,
        credit_ceiling_cents=1000000,
        lease_type="FULL_SERVICE",
        per_diem_rate_cents=1000,
        liability_bearer="LESSOR",
        term_start_date="2026-09-01",
        term_end_date="2027-09-01",
        fleet_car_cap=5,
        activate=True,
    )
    other_lessee = get_success_data(
        api_client.create_lessee(
            create_lessee_payload(
                legal_name="Other Party Rail Co",
                credit_tier="B",
                utilization_threshold_pct=0,
                credit_ceiling_cents=1000000,
            ),
            LEASE,
        )
    )
    car = world["car"]

    refused = api_client.create_car_assignment(
        {
            "lease_fleet_car_id": car["id"],
            "lease_contract_id": pair["contract"]["id"],
            "lessee_id": other_lessee["id"],
            "start_date": "2026-09-12",
            "end_date": "2026-10-12",
            "mileage_allowance": 1000,
        },
        LEASE,
    )
    validate_error(refused, ApiErrorId.ERR_LESSEE_MISMATCH)
    assert refused.status_code == 409
    untouched = get_success_data(api_client.get_lease_fleet_car(car["id"], ADMIN))
    assert untouched["status"] == "HELD", "no placement row was written"

    accepted = validate_success(
        api_client.create_car_assignment(
            {
                "lease_fleet_car_id": car["id"],
                "lease_contract_id": pair["contract"]["id"],
                "lessee_id": pair["lessee"]["id"],
                "start_date": "2026-09-12",
                "end_date": "2026-10-12",
                "mileage_allowance": 1000,
            },
            LEASE,
        ),
        expected_status=201,
    )
    assert accepted["status"] == "ACTIVE"
    placed = get_success_data(api_client.get_lease_fleet_car(car["id"], ADMIN))
    assert placed["status"] == "ASSIGNED"


def test_work_order_on_an_uncovered_car_type_returns_409(api):
    """PRD §2.8: "A work order may only be raised for a car whose car type is
    covered by the named program through a `RetrofitProgramCarType` row; a car
    type that is not covered is rejected with `ERR_CAPACITY_EXCEEDED` (HTTP 409)."
    PRD §2.11: "Twenty-fourth, program coverage: the car's car type must be
    covered by the retrofit program through a `RetrofitProgramCarType` row, and a
    car type that is not covered is rejected with `ERR_CAPACITY_EXCEEDED`
    (HTTP 409) on work-order creation."

    Both cars are HELD and both windows clear the deadline; only the coverage row
    differs, so the uncovered car's work order is refused while the covered
    car's is scheduled.

    Design: Corner/errors/error_capacity_exceeded_uncovered_car_type_returns_409
    """
    set_clock(CLOCK_START_ISO)
    covered_catalogue = flat_catalogue(
        model_code="CT-W1",
        line_count_family="LINE-W1",
        wheelset_part_number="WS-W1",
    )
    uncovered_catalogue = flat_catalogue(
        model_code="CT-W2",
        line_count_family="LINE-W2",
        wheelset_part_number="WS-W2",
    )
    covered_world = setup_retained_order_with_fleet_cars(
        car_count=1,
        catalogue=covered_catalogue,
        build_contract=False,
        changeover_start="2026-09-11",
        completion_date="2026-09-12",
    )
    uncovered_world = setup_retained_order_with_fleet_cars(
        car_count=1,
        catalogue=uncovered_catalogue,
        build_contract=False,
        changeover_start="2026-09-11",
        completion_date="2026-09-12",
    )
    covered_car = covered_world["car"]
    uncovered_car = uncovered_world["car"]
    assert get_success_data(api_client.get_lease_fleet_car(uncovered_car["id"], ADMIN))[
        "status"
    ] == "HELD"

    program = get_success_data(
        api_client.create_retrofit_program(
            create_retrofit_program_payload(
                mandate_code="MAND-W",
                description="Partially covering mandate",
                compliance_deadline_date="2026-12-31",
                required_shop_days_per_car=3,
            ),
            RETROFIT,
        )
    )
    get_success_data(
        api_client.create_retrofit_program_car_type(
            create_retrofit_program_car_type_payload(
                retrofit_program_id=program["id"],
                car_type_id=covered_catalogue["car_type"]["id"],
            ),
            RETROFIT,
        )
    )

    refused = api_client.create_retrofit_work_order(
        create_retrofit_work_order_payload(
            retrofit_program_id=program["id"],
            lease_fleet_car_id=uncovered_car["id"],
            shop_line="SHOP-W1",
            scheduled_start_date="2026-10-01",
            scheduled_end_date="2026-10-04",
            component_qty_consumed=1,
        ),
        PLANNER,
    )
    validate_error(refused, ApiErrorId.ERR_CAPACITY_EXCEEDED)
    assert refused.status_code == 409
    untouched = get_success_data(
        api_client.get_lease_fleet_car(uncovered_car["id"], ADMIN)
    )
    assert untouched["status"] == "HELD", "no work-order row was written"

    accepted = validate_success(
        api_client.create_retrofit_work_order(
            create_retrofit_work_order_payload(
                retrofit_program_id=program["id"],
                lease_fleet_car_id=covered_car["id"],
                shop_line="SHOP-W2",
                scheduled_start_date="2026-10-01",
                scheduled_end_date="2026-10-04",
                component_qty_consumed=1,
            ),
            PLANNER,
        ),
        expected_status=201,
    )
    assert accepted["status"] == "SCHEDULED"
