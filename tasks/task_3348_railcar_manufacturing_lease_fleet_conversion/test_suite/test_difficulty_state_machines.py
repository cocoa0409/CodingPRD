"""Difficulty queue: non-linear state machines and cross-entity gates.

Four instances, one test each:

* ``non_linear_state_machine`` — the placement fork (suspend rejoins in place,
  reassign mints a replacement row) and the sold/held compensating cycle.
* ``cross_entity_state_dependency`` — a car may only leave the repair queue
  once its returns are settled, and a placement may only be suspended while
  its governing contract is ACTIVE.
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
    create_return,
    get_success_data,
    reassign_assignment,
    release_order,
    reserve_order,
    resume_assignment,
    set_clock,
    settle_return,
    setup_catalogue,
    start_production,
    suspend_assignment,
    validate_error,
    validate_success,
    void_sale,
    create_sale,
)

LEASE = TEST_USERS["lease_administrator_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
PORTFOLIO = TEST_USERS["portfolio_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def _car_world(
    *,
    model_code: str,
    line_family: str,
    part_number: str,
    unit_cost_cents: int,
    build_hours: int,
    regulatory_life_years: int,
    quantity: int,
    order_date: str,
    required_delivery_date: str,
    changeover_start: str,
    changeover_days: int,
    completion_date: str,
    contract_kwargs: dict,
    on_hand_qty: int = 100,
    wheelset_qty_per_car: int = 4,
    include_casting: bool = False,
    casting_part_number: str = None,
    casting_unit_cost_cents: int = None,
    casting_qty_per_car: int = None,
):
    """Catalogue + lessee + ACTIVE contract + one completed RETAINED order.

    The catalogue shape follows the recipe the caller is reproducing: the
    cross-entity instances name a one-row WHEELSET bill of materials, while the
    fork and void-cycle instances carry a second CASTING row.

    Returns the world with the contract, the order and the fleet cars the
    completion minted.
    """
    catalogue = setup_catalogue(
        model_code=model_code,
        car_class="BOXCAR",
        build_hours=build_hours,
        regulatory_life_years=regulatory_life_years,
        line_count_family=line_family,
        wheelset_part_number=part_number,
        wheelset_unit_cost_cents=unit_cost_cents,
        wheelset_qty_per_car=wheelset_qty_per_car,
        wheelset_lead_time_days=20,
        include_casting=include_casting,
        casting_part_number=casting_part_number,
        casting_unit_cost_cents=casting_unit_cost_cents,
        casting_qty_per_car=casting_qty_per_car,
        include_coating=False,
        on_hand_qty=on_hand_qty,
    )
    world = create_lessee_and_contract(**contract_kwargs)
    lessee, contract = world["lessee"], world["contract"]

    order = create_order(
        catalogue,
        quantity=quantity,
        planned_shop_days=build_hours * quantity,
        disposition="RETAINED",
        priority_rank=1,
        order_date=order_date,
        required_delivery_date=required_delivery_date,
        lessee_id=lessee["id"],
    )
    reserve_order(order["id"])
    release_order(order["id"], lease_contract_id=contract["id"])
    start_production(order["id"], line_family, window_start=changeover_start,
                     window_days=changeover_days)
    order = complete_order(order["id"], completed_qty=quantity,
                           completion_date=completion_date)

    cars = get_success_data(
        api_client.list_lease_fleet_cars(
            ADMIN, {"production_order_id": order["id"]}
        )
    )
    world.update(
        {
            "catalogue": catalogue,
            "order": order,
            "cars": cars,
            "car": cars[0] if cars else None,
        }
    )
    return world


# ─── non_linear_state_machine ─────────────────────────

def test_placement_suspend_rejoins_in_place_while_reassign_mints_a_row(api):
    """PRD §3.6: "On success the placement becomes `SUSPENDED`, per-diem accrual
    stops, the parent car returns to `HELD`, and the placement's
    `per_diem_accrued_cents` is recomputed as of the suspension date by the
    accrual rule above; both the placement's and the car's versions move."
    PRD §3.6: "Resumption is legal from `SUSPENDED` or from `REASSIGNED`, and it
    requires the governing contract to still be `ACTIVE` and the parent car to
    be `HELD`; it returns the placement to `ACTIVE`, restarts the meter, puts
    the car back to `ASSIGNED`, and increments both versions."
    PRD §3.6: "On success the source placement becomes `REASSIGNED`, and a
    replacement placement is created on the target car with a `start_date`
    equal to the source placement's `end_date` and a `per_diem_rate_cents`
    snapshotted from the same contract; both the source placement's and the
    target car's versions move."

    The fork at ACTIVE has two branches with different row sets: suspend then
    resume returns the same placement to service, while reassign retires the
    source placement and mints a second one on the target car.

    Design: Difficulty/non_linear_state_machine/car_assignment_suspend_reassign_fork
    """
    set_clock("2026-06-01T00:00:00Z")
    world = _car_world(
        model_code="BOX-100",
        line_family="BOX_LINE",
        part_number="WS-1000",
        unit_cost_cents=250000,
        build_hours=4,
        regulatory_life_years=25,
        quantity=3,
        order_date="2026-05-25",
        required_delivery_date="2026-08-31",
        changeover_start="2026-06-01",
        changeover_days=12,
        completion_date="2026-06-01",
        on_hand_qty=4,
        wheelset_qty_per_car=1,
        include_casting=True,
        casting_part_number="CS-2000",
        casting_unit_cost_cents=180000,
        casting_qty_per_car=1,
        contract_kwargs=dict(
            legal_name="Fork Rail Lessee",
            credit_tier="A",
            utilization_threshold_pct=60,
            credit_ceiling_cents=50000000,
            lease_type="FULL_SERVICE",
            per_diem_rate_cents=45000,
            liability_bearer="LESSOR",
            term_start_date="2026-01-01",
            term_end_date="2027-12-31",
            fleet_car_cap=3,
        ),
    )
    contract, lessee = world["contract"], world["lessee"]
    car_a, car_b, car_c = world["cars"][0], world["cars"][1], world["cars"][2]
    assert len(world["cars"]) == 3

    assignment_a = create_assignment(
        car_a, contract, lessee, start_date="2026-06-01",
        end_date="2026-06-30", mileage_allowance=3000,
    )
    assignment_b = create_assignment(
        car_b, contract, lessee, start_date="2026-06-01",
        end_date="2026-06-10", mileage_allowance=3000,
    )
    assignment_c = create_assignment(
        car_c, contract, lessee, start_date="2026-06-01",
        end_date="2026-06-05", mileage_allowance=3000,
    )

    # Park car C: suspending its placement pulls the car back to HELD while
    # leaving its contract stamp in place, which is what makes it a legal
    # reassign target.
    parked = suspend_assignment(assignment_c["id"], suspend_date="2026-06-01")
    assert parked["status"] == "SUSPENDED"

    # Ten days later the first placement is suspended; the accrual is recomputed
    # as of the suspension date: 10 days * 45000 cents, with mileage_used 0 so
    # the 12 percent utilization credit is exactly zero.
    advance_clock_to("2026-06-11T00:00:00Z")
    suspended = suspend_assignment(assignment_a["id"], suspend_date="2026-06-11")
    assert suspended["status"] == "SUSPENDED"
    assert suspended["per_diem_accrued_cents"] == 450000, (
        "10 days from 2026-06-01 to the 2026-06-11 suspension at 45000 cents "
        "per day, with no utilization credit"
    )

    # Branch one: resume rejoins ACTIVE without minting anything.
    resumed = resume_assignment(assignment_a["id"])
    assert resumed["status"] == "ACTIVE"
    car_a_after = get_success_data(
        api_client.get_lease_fleet_car(car_a["id"], ADMIN)
    )
    assert car_a_after["status"] == "ASSIGNED"

    car_a_rows = get_success_data(
        api_client.list_car_assignments(
            ADMIN, {"lease_fleet_car_id": car_a["id"]}
        )
    )
    assert len(car_a_rows) == 1, "the suspend/resume branch must not mint a row"

    # Branch two: reassign retires the source placement and mints a replacement
    # on the target car, starting on the source placement's end date.
    reassign_assignment(
        assignment_b["id"], car_c["id"], effective_date="2026-06-10"
    )
    source = get_success_data(
        api_client.get_car_assignment(assignment_b["id"], ADMIN)
    )
    assert source["status"] == "REASSIGNED"
    assert resumed["status"] == "ACTIVE"

    car_c_rows = get_success_data(
        api_client.list_car_assignments(
            ADMIN, {"lease_fleet_car_id": car_c["id"]}
        )
    )
    assert len(car_c_rows) == 2, "the reassign branch mints exactly one row"
    replacement = car_c_rows[-1]
    assert replacement["status"] == "ACTIVE"
    assert replacement["start_date"] == "2026-06-10"
    assert replacement["per_diem_rate_cents"] == 45000, (
        "the replacement snapshots the rate from the same contract"
    )
    assert replacement["id"] != assignment_c["id"]


def test_voiding_a_pending_sale_returns_the_car_and_leaves_the_ledger(api):
    """PRD §3.9: "On success the sale becomes `VOIDED` and the car is restored
    to `HELD`, and the portfolio ledger's `realized_gain_cents` is left exactly
    as it stood before this sale was created — the void is an erasure, not a
    loss, and it must leave the ledger where it would have been had the sale
    never been written."
    PRD §2.10: "Where an operation is a compensating action — voiding a sale,
    cancelling a reservation, returning an endorsement to pending — it must
    restore the affected derived fields to the values they would hold had the
    original write never occurred."
    PRD §2.8: "A lease fleet car's `regulatory_life_end_date` is derived from
    its build date and its car type: it is the car's `built_date` advanced by
    the car type's `regulatory_life_years`."

    The car cycles HELD -> SOLD -> HELD -> SOLD: the void re-opens the terminal
    state rather than ending the story.

    Design: Difficulty/non_linear_state_machine/lease_fleet_car_sold_held_void_cycle
    """
    set_clock("2026-06-01T00:00:00Z")
    world = _car_world(
        model_code="BOX-100",
        line_family="BOX_LINE",
        part_number="WS-1000",
        unit_cost_cents=250000,
        build_hours=4,
        regulatory_life_years=25,
        quantity=1,
        order_date="2026-05-25",
        required_delivery_date="2026-08-31",
        changeover_start="2026-06-01",
        changeover_days=4,
        completion_date="2026-06-01",
        on_hand_qty=2,
        wheelset_qty_per_car=1,
        include_casting=True,
        casting_part_number="CS-2000",
        casting_unit_cost_cents=180000,
        casting_qty_per_car=1,
        contract_kwargs=dict(
            legal_name="Void Cycle Lessee",
            credit_tier="A",
            utilization_threshold_pct=60,
            credit_ceiling_cents=50000000,
            lease_type="FULL_SERVICE",
            per_diem_rate_cents=45000,
            liability_bearer="LESSOR",
            term_start_date="2026-01-01",
            term_end_date="2027-12-31",
            fleet_car_cap=1,
        ),
    )
    car = world["car"]
    assert car["acquisition_cost_cents"] == 660000
    assert car["built_date"] == "2026-06-01"
    assert car["regulatory_life_end_date"] == "2051-06-01"
    assert car["status"] == "HELD"

    first = create_sale(
        car, sale_price_cents=900000, sale_date="2026-06-02",
        writeback_liability_cents=0, buyer_name="Midwest Rail Holdings",
    )
    sold = get_success_data(api_client.get_lease_fleet_car(car["id"], ADMIN))
    assert sold["status"] == "SOLD"

    voided = void_sale(first["id"], reason="buyer withdrew financing")
    assert voided["status"] == "VOIDED"
    restored = get_success_data(api_client.get_lease_fleet_car(car["id"], ADMIN))
    assert restored["status"] == "HELD", (
        "the void must restore the car the sale had driven to SOLD"
    )

    second = create_sale(
        car, sale_price_cents=880000, sale_date="2026-06-03",
        writeback_liability_cents=0, buyer_name="Great Lakes Freight",
    )
    assert second["id"] != first["id"]
    assert second["status"] == "PENDING_SETTLEMENT"

    resold = get_success_data(api_client.get_lease_fleet_car(car["id"], ADMIN))
    assert resold["status"] == "SOLD", (
        "HELD -> SOLD -> HELD -> SOLD is a real cycle, not a one-way pipeline"
    )

    ledger = get_success_data(api_client.get_portfolio_ledger(PORTFOLIO))
    assert ledger["realized_gain_cents"] == 0, (
        "no sale ever settled, so the realized gain never moved"
    )


# ─── cross_entity_state_dependency ────────────────────

def test_settle_returns_rejected_until_every_return_is_settled(api):
    """PRD §3.7: "A `ProductionPlanner` may release a car from `UNDER_REPAIR`
    back to `HELD` only when every return of that car has `settlement_status`
    equal to `SETTLED`; a car with any outstanding return is rejected with
    `ERR_UNSETTLED_RETURNS` (HTTP 409)."
    PRD §3.7: "The release sets the car to `HELD`, clears its `lease_contract_id`,
    re-derives its `retrofit_required` flag, and increments the car's `version`
    and `updated_at`."
    PRD §3.7: "Until a return is settled, its mileage overage does not count
    toward the lessee's balance, because the reconciliation aggregates only
    settled returns."

    The car itself sits in the legal from-state throughout; only the
    cross-entity CarReturn gate can reject the call.

    Design: Difficulty/cross_entity_state_dependency/settle_returns_gated_on_car_return_settlement
    """
    set_clock("2026-09-01T00:00:00Z")
    world = _car_world(
        model_code="R7A-100",
        line_family="R7A_LINE",
        part_number="R7A-WS",
        unit_cost_cents=100000,
        build_hours=10,
        regulatory_life_years=40,
        quantity=1,
        order_date="2026-09-01",
        required_delivery_date="2026-09-20",
        changeover_start="2026-09-05",
        changeover_days=10,
        completion_date="2026-09-15",
        contract_kwargs=dict(
            legal_name="R7A Rail Leasing Co",
            credit_tier="B",
            utilization_threshold_pct=80,
            credit_ceiling_cents=10000000,
            lease_type="FULL_SERVICE",
            per_diem_rate_cents=5000,
            liability_bearer="LESSOR",
            term_start_date="2026-09-01",
            term_end_date="2027-09-01",
            fleet_car_cap=10,
        ),
    )
    car, contract, lessee = world["car"], world["contract"], world["lessee"]
    assert car["acquisition_cost_cents"] == 875000
    assert car["regulatory_life_end_date"] == "2066-09-15"

    # The clock is moved to the placement's start so the placement is live
    # rather than future-dated.
    advance_clock_to("2026-09-16T00:00:00Z")
    assignment = create_assignment(
        car, contract, lessee, start_date="2026-09-16",
        end_date="2026-10-16", mileage_allowance=1000,
    )
    assert assignment["status"] == "ACTIVE"

    # 30 days in placement, one allowance block of 1000 miles, 500 miles run:
    # the overage clamps at zero and the true-up charges nothing.
    car_return = create_return(
        car, assignment, return_date="2026-10-16",
        mileage_since_last=500, condition_grade="A",
    )
    assert car_return["mileage_overage_cents"] == 0
    assert car_return["settlement_status"] == "PENDING"

    in_repair = get_success_data(api_client.get_lease_fleet_car(car["id"], ADMIN))
    assert in_repair["status"] == "UNDER_REPAIR"

    blocked = api_client.settle_fleet_car_returns(car["id"], PLANNER)
    validate_error(blocked, ApiErrorId.ERR_UNSETTLED_RETURNS)
    assert blocked.status_code == 409

    still_in_repair = get_success_data(
        api_client.get_lease_fleet_car(car["id"], ADMIN)
    )
    assert still_in_repair["status"] == "UNDER_REPAIR", (
        "the rejected call must not partially mutate the car"
    )

    settled = settle_return(car_return["id"])
    assert settled["settlement_status"] == "SETTLED"

    released = validate_success(
        api_client.settle_fleet_car_returns(car["id"], PLANNER)
    )
    assert released["status"] == "HELD"
    assert released["lease_contract_id"] is None


def test_suspend_rejected_while_governing_contract_is_not_active(api):
    """PRD §3.6: "Suspension is legal when the placement is `ACTIVE`, the parent
    car is `ASSIGNED` and the governing contract is `ACTIVE`; the request
    accepts an optional `suspend_date` that fixes the date the meter stops."
    PRD §3.5: "A successful draft stores the proposed rate and bearer on the
    contract draft, moves the contract to `AMENDMENT_DRAFTED`, and increments
    its `version`."
    PRD §3.5: "On success the contract returns to `ACTIVE`, its `amendment_seq`
    is incremented by one, and two cascades run."

    The placement and its car both sit in legal from-states, so only the
    governing contract's status can reject the suspension.

    Design: Difficulty/cross_entity_state_dependency/suspend_assignment_gated_on_contract_status
    """
    set_clock("2026-09-01T00:00:00Z")
    world = _car_world(
        model_code="R7B-100",
        line_family="R7B_LINE",
        part_number="R7B-WS",
        unit_cost_cents=100000,
        build_hours=10,
        regulatory_life_years=40,
        quantity=1,
        order_date="2026-09-01",
        required_delivery_date="2026-09-20",
        changeover_start="2026-09-05",
        changeover_days=10,
        completion_date="2026-09-15",
        contract_kwargs=dict(
            legal_name="R7B Rail Leasing Co",
            credit_tier="B",
            utilization_threshold_pct=80,
            credit_ceiling_cents=10000000,
            lease_type="NET",
            per_diem_rate_cents=5000,
            liability_bearer="LESSEE",
            term_start_date="2026-09-01",
            term_end_date="2027-09-01",
            fleet_car_cap=10,
        ),
    )
    car, contract, lessee = world["car"], world["contract"], world["lessee"]

    advance_clock_to("2026-09-16T00:00:00Z")
    assignment = create_assignment(
        car, contract, lessee, start_date="2026-09-16",
        end_date="2026-10-16", mileage_allowance=1000,
    )
    assert assignment["status"] == "ACTIVE"

    # Drafting the amendment carries the contract's current version, so the
    # write is not rejected as stale.
    current = get_success_data(api_client.get_lease_contract(contract["id"], LEASE))
    drafted = validate_success(
        api_client.draft_lease_amendment(
            contract["id"],
            {
                "per_diem_rate_cents": 5500,
                "liability_bearer": "LESSEE",
                "expected_lease_version": current["version"],
            },
            LEASE,
        )
    )
    assert drafted["status"] == "AMENDMENT_DRAFTED"

    blocked = api_client.suspend_car_assignment(assignment["id"], LEASE, {})
    validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)
    assert blocked.status_code == 409

    untouched = get_success_data(
        api_client.get_car_assignment(assignment["id"], ADMIN)
    )
    assert untouched["status"] == "ACTIVE", (
        "the rejected suspend must not partially mutate the placement"
    )
    still_assigned = get_success_data(
        api_client.get_lease_fleet_car(car["id"], ADMIN)
    )
    assert still_assigned["status"] == "ASSIGNED"

    ratified = validate_success(
        api_client.ratify_lease_amendment(
            contract["id"],
            {"expected_lease_version": drafted["version"]},
            LEASE,
        )
    )
    assert ratified["status"] == "ACTIVE"
    assert ratified["amendment_seq"] == 1

    suspended = validate_success(
        api_client.suspend_car_assignment(assignment["id"], LEASE, {})
    )
    assert suspended["status"] == "SUSPENDED"
    parked_car = get_success_data(api_client.get_lease_fleet_car(car["id"], ADMIN))
    assert parked_car["status"] == "HELD"
