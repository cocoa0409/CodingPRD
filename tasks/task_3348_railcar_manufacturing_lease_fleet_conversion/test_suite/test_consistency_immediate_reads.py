"""Immediate consistency: a write's cascades are visible in its own response.

Three instances, one test each.  No test sleeps, retries or advances the clock:
every cascaded value is asserted either in the response body of the write that
caused it or in the very next read, which is what the immediate consistency
model promises.
"""

from test_helpers import (
    TEST_USERS,
    api_client,
    complete_order,
    create_assignment,
    create_car_type_component_requirement_payload,
    create_car_type_payload,
    create_component_payload,
    create_component_purchase_order_payload,
    create_lessee_and_contract,
    create_order,
    release_order,
    reserve_order,
    set_clock,
    setup_catalogue,
    setup_order_in_state,
    start_production,
    validate_success,
)

SUPPLY = TEST_USERS["supply_chain_coordinator_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
LEASE = TEST_USERS["lease_administrator_headers"]
PORTFOLIO = TEST_USERS["portfolio_manager_headers"]
RETROFIT = TEST_USERS["regulatory_retrofitist_headers"]


def test_program_start_response_already_carries_the_recomputed_cost(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.8: "On success the program becomes `IN_PROGRESS`, the
    `retrofit_required` flag is set to true on every fleet car of a covered car
    type whose status is `HELD` or `UNDER_REPAIR`, and the program's
    `program_cost_cents` is re-derived by the cost rule below.  The program's
    `version` and the `version` of every enrolled car move with the write."
    PRD §2.10: "Where a state machine declares a side effect that mutates a
    second entity, that second entity's version and timestamp move in the same
    logical write as the first."
    PRD §3.8: "Each contributing work order adds its `shop_days` multiplied by
    the shop-day rate of 185,000 cents, plus its `component_qty_consumed`
    multiplied by the unit cost of the program's required component when a
    `required_component_id` is set."

    The scheduled work order books 10 shop days and consumes 3 kit units at 5000
    cents, so the start response must already read 1865000 cents rather than the
    zero the program held while PLANNED.

    Design: Corner/consistency_model/consistency_immediate_retrofit_start_response_carries_recomputed_program_cost
    """
    set_clock("2026-09-01T00:00:00Z")
    car_type = validate_success(
        api_client.create_car_type(
            create_car_type_payload(
                model_code="CT-IM-1",
                car_class="BOXCAR",
                build_hours=1,
                regulatory_life_years=25,
                line_count_family="LINE-IM",
            ),
            PLANNER,
        ),
        expected_status=201,
    )
    coating = validate_success(
        api_client.create_component(
            create_component_payload(
                part_number="CO-IM-1",
                component_class="COATING",
                unit_cost_cents=1000,
                lead_time_days=5,
            ),
            SUPPLY,
        ),
        expected_status=201,
    )
    kit = validate_success(
        api_client.create_component(
            create_component_payload(
                part_number="KIT-IM-1",
                component_class="COATING",
                unit_cost_cents=5000,
                lead_time_days=30,
            ),
            SUPPLY,
        ),
        expected_status=201,
    )
    validate_success(
        api_client.create_car_type_component_requirement(
            create_car_type_component_requirement_payload(
                car_type_id=car_type["id"],
                component_id=coating["id"],
                qty_per_car=1,
            ),
            PLANNER,
        ),
        expected_status=201,
    )
    purchase_order = validate_success(
        api_client.create_component_purchase_order(
            create_component_purchase_order_payload(
                component_id=coating["id"],
                qty_ordered=5,
                unit_cost_cents=1000,
                order_date="2026-09-01",
                expected_receipt_date="2026-09-06",
            ),
            SUPPLY,
        ),
        expected_status=201,
    )
    validate_success(
        api_client.confirm_component_purchase_order(purchase_order["id"], SUPPLY)
    )

    catalogue = {"car_type": car_type, "coating": coating}
    order = create_order(
        catalogue,
        quantity=1,
        disposition="RETAINED",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-09-20",
    )
    reserve_order(order["id"])
    release_order(order["id"])
    start_production(order["id"], "LINE-IM", window_start="2026-09-02")
    complete_order(order["id"], completion_date="2026-09-04")

    cars = validate_success(
        api_client.list_lease_fleet_cars(
            PLANNER, {"production_order_id": order["id"], "limit": 10}
        )
    )
    assert len(cars) == 1
    car_id = cars[0]["id"]

    program = validate_success(
        api_client.create_retrofit_program(
            {
                "mandate_code": "MAND-IM-1",
                "description": "Coating mandate",
                "compliance_deadline_date": "2026-12-31",
                "required_shop_days_per_car": 10,
                "required_component_id": kit["id"],
            },
            RETROFIT,
        ),
        expected_status=201,
    )
    assert program["program_cost_cents"] == 0
    assert program["status"] == "PLANNED"

    validate_success(
        api_client.create_retrofit_program_car_type(
            {"retrofit_program_id": program["id"], "car_type_id": car_type["id"]},
            RETROFIT,
        ),
        expected_status=201,
    )
    validate_success(
        api_client.create_retrofit_work_order(
            {
                "retrofit_program_id": program["id"],
                "lease_fleet_car_id": car_id,
                "shop_line": "SL-IM-1",
                "scheduled_start_date": "2026-09-10",
                "scheduled_end_date": "2026-09-20",
                "component_qty_consumed": 3,
            },
            PLANNER,
        ),
        expected_status=201,
    )

    started = validate_success(
        api_client.start_retrofit_program(program["id"], RETROFIT)
    )
    assert started["status"] == "IN_PROGRESS"
    assert started["program_cost_cents"] == 1865000, (
        "the write's own response carries the recomputed cost, not a stale zero"
    )
    assert started["version"] == program["version"] + 1, (
        "the version bump is likewise in the response rather than deferred"
    )

    enrolled = validate_success(api_client.get_lease_fleet_car(car_id, RETROFIT))
    assert enrolled["retrofit_required"] is True, (
        "the cascade onto the enrolled car is visible on the very next read"
    )


def test_retained_completion_response_and_cascade_land_in_the_same_instant(api):
    """PRD §3.4: "On the retained branch, completion creates one fleet car per
    car built, each starting in `HELD` with its `production_order_id` pointing at
    the producing order, its `acquisition_cost_cents` equal to the order's
    `unit_price_cents`, and its `built_date` set to the completion date; each new
    car's `regulatory_life_end_date` and `retrofit_required` are then derived,
    and the contract's capital allocation is re-derived by the rule above."
    PRD §3.4: "The completion also advances the portfolio ledger: its
    `committed_capital_cents` is increased by the order's `unit_price_cents`
    multiplied by the number of cars completed, and its `fleet_nbv_cents` is
    re-derived by the reconciliation rule of §3.9.  The order itself ends as
    `COMPLETED` with `completed_qty` equal to `quantity`, and its `version` and
    `updated_at` move."
    PRD §3.9: "The newest basis is the live fleet's depreciated book value: for
    every car in `HELD`, `ASSIGNED` or `UNDER_REPAIR`, the car's
    `acquisition_cost_cents` minus the number of days from its `built_date` to
    the current clock date multiplied by the daily depreciation of 2,500 cents,
    floored at zero per car so a fully depreciated car contributes nothing,
    summed across the fleet and rounded up to a whole cent."

    Two cars at the 98000-cent committed quote give 196000 cents of capital on
    the same instant they are built, so the historic and depreciated bases agree
    and the drift is zero.

    Design: Corner/consistency_model/consistency_immediate_order_complete_response_carries_completed_state_and_ledger_cascade
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(
        model_code="CT-IM2-1",
        build_hours=1,
        regulatory_life_years=25,
        line_count_family="LINE-IM2",
        wheelset_part_number="WS-IM2-1",
        wheelset_unit_cost_cents=1000,
        wheelset_lead_time_days=5,
        wheelset_qty_per_car=1,
        casting_part_number="CS-IM2-1",
        casting_unit_cost_cents=2000,
        casting_lead_time_days=6,
        casting_qty_per_car=1,
        include_coating=False,
        on_hand_qty=10,
    )
    commercial = create_lessee_and_contract(
        legal_name="LESS-IM2-1",
        per_diem_rate_cents=10000,
        liability_bearer="LESSOR",
        fleet_car_cap=10,
        credit_ceiling_cents=9000000,
    )
    world = setup_order_in_state(
        "IN_PRODUCTION",
        catalogue=catalogue,
        quantity=2,
        disposition="RETAINED",
        priority_rank=1,
        order_date="2026-08-25",
        required_delivery_date="2026-09-20",
        lease_contract_id=commercial["contract"]["id"],
        changeover_start="2026-08-30",
    )
    order = world["order"]
    assert order["status"] == "IN_PRODUCTION"
    assert order["unit_price_cents"] == 98000, (
        "26000 + 27000 component lines plus 45000 labor, with no change fee"
    )

    completed = complete_order(order["id"], completion_date="2026-09-01")
    assert completed["status"] == "COMPLETED"
    assert completed["completed_qty"] == 2
    assert completed["version"] == order["version"] + 1

    cars = validate_success(
        api_client.list_lease_fleet_cars(
            PLANNER, {"production_order_id": order["id"], "limit": 10}
        )
    )
    assert len(cars) == 2, "one fleet car per car built, in the same write"
    assert cars[0]["status"] == "HELD" and cars[1]["status"] == "HELD"
    assert cars[0]["built_date"] == "2026-09-01"
    assert cars[0]["acquisition_cost_cents"] == 98000

    contract = validate_success(
        api_client.get_lease_contract(commercial["contract"]["id"], PORTFOLIO)
    )
    assert contract["capital_allocation_cents"] == 196000, "2 live cars * 98000"

    reconciliation = validate_success(
        api_client.get_portfolio_ledger_reconciliation(PORTFOLIO)
    )
    assert reconciliation["committed_capital_cents"] == 196000, (
        "the ledger's committed capital moved with the completion"
    )
    assert reconciliation["drift_cents"] == 0, (
        "the cars were built at the clock instant, so the depreciated basis "
        "equals the historic basis and the two agree immediately"
    )


def test_ratify_response_already_carries_the_counter_and_the_restated_accrual(api):
    """PRD §3.5: "On success the contract returns to `ACTIVE`, its
    `amendment_seq` is incremented by one, and two cascades run.  First, the
    newly ratified `per_diem_rate_cents` is refreshed onto every placement
    referencing this contract whose status is `ACTIVE`, and each such
    placement's `per_diem_accrued_cents` is recomputed by the accrual rule of
    §3.6 — which is why the ratify path produces a restated accrual rather than
    a continuation of the old one."
    PRD §3.6: "A restated accrual is produced whenever the placement history is
    rewritten rather than merely continued — after a contract amendment, after a
    reassignment, or at a return.  The restated basis walks every placement of
    the same car in `start_date` ascending order, breaking ties by `created_at`
    ascending, clips each interval to the governing contract's `term_start_date`
    up to but not including its `term_end_date`, and clips it again to the window
    from 365 days before the current clock date up to but not including the
    current clock date."
    PRD §2.10: "Where a state machine declares a side effect that mutates a
    second entity, that second entity's version and timestamp move in the same
    logical write as the first."

    The placement opens 2024-06-01 under a term running to 2028-01-01 and is
    still ACTIVE at the 2026-09-01 clock: the open basis reads 822 days at 10000
    cents, and the ratified restatement clips the same interval to
    [2025-09-01, 2026-09-01) for 365 days.

    Design: Corner/consistency_model/consistency_immediate_ratify_response_carries_amendment_seq_and_restated_accrual
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(
        model_code="CT-IM3-1",
        build_hours=1,
        regulatory_life_years=25,
        line_count_family="LINE-IM3",
        wheelset_part_number="WS-IM3-1",
        wheelset_unit_cost_cents=1000,
        wheelset_lead_time_days=5,
        wheelset_qty_per_car=1,
        casting_part_number="CS-IM3-1",
        casting_unit_cost_cents=2000,
        casting_lead_time_days=6,
        casting_qty_per_car=1,
        include_coating=False,
        on_hand_qty=10,
    )
    commercial = create_lessee_and_contract(
        legal_name="LESS-IM3-1",
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
    start_production(order["id"], "LINE-IM3", window_start="2024-01-01")
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

    before = validate_success(api_client.get_car_assignment(assignment["id"], LEASE))
    assert before["per_diem_accrued_cents"] == 8220000, (
        "the open basis runs 822 days from 2024-06-01 to the clock date"
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
    assert ratified["status"] == "ACTIVE", (
        "the ratify response itself carries the new state"
    )
    assert ratified["amendment_seq"] == 1, (
        "the cascade counter is in the response, not deferred to a later read"
    )
    assert ratified["version"] == drafted["version"] + 1

    after = validate_success(api_client.get_car_assignment(assignment["id"], LEASE))
    assert after["per_diem_accrued_cents"] == 3650000, (
        "the restated accrual is readable in the same instant, with no clock "
        "movement and no second write"
    )
    assert after["status"] == "ACTIVE", (
        "the restatement does not disturb the placement's own state"
    )
