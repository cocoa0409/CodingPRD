"""State machines: illegal source states, terminal lockdown and repeat attempts.

Every test here drives one action endpoint from a state the machine does not
admit, or repeats a transition that has already been taken, and then re-reads
the subject to prove the rejection was total: the status, the version and every
field the transition would have written are exactly as they stood before the
call.

The PRD fixes which rejection each site produces: §2.11 evaluates state
legality (``ERR_INVALID_STATE``) before terminality (``ERR_ALREADY_TERMINAL``),
and terminality guards exactly three writes — order completion, sale settlement
and retrofit-program start.  Every other repeat attempt is an illegal source
state and answers ``ERR_INVALID_STATE``.
"""

from test_helpers import (
    ApiErrorId,
    CLOCK_START_ISO,
    TEST_USERS,
    advance_clock_to,
    complete_production_order_payload,
    create_assignment,
    create_lessee_and_contract,
    create_order,
    create_retrofit_program,
    create_sale,
    create_endorsement,
    get_success_data,
    patch_substitution_endorsement_payload,
    receive_component_stock,
    scrap_lease_fleet_car_payload,
    set_clock,
    settle_sale,
    setup_assigned_car,
    setup_catalogue,
    setup_order_with_endorsement,
    setup_retained_order_with_fleet_cars,
    setup_retrofit_program_with_car,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    void_sale,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SUPPLY = TEST_USERS["supply_chain_coordinator_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
LEASE = TEST_USERS["lease_administrator_headers"]
PORTFOLIO = TEST_USERS["portfolio_manager_headers"]
RETROFIT = TEST_USERS["regulatory_retrofitist_headers"]


def _completed_retained_car_world(car_count: int = 1, **kwargs):
    """A RETAINED order completed with no contract named on its release.

    The release body omits ``lease_contract_id``, so no contract's capital
    allocation is written by the completion and the minted cars carry no
    contract link until a placement stamps one.
    """
    return setup_retained_order_with_fleet_cars(
        car_count=car_count,
        build_contract=False,
        changeover_start="2026-09-05",
        completion_date=kwargs.pop("completion_date", "2026-09-15"),
        **kwargs,
    )


# ─── Invalid transitions ──────────────────────────────

def test_complete_draft_order_rejected_as_invalid_state(api):
    """PRD §3.4: "It is legal only from `IN_PRODUCTION`, and it completes the
    remaining cars in one step: the `completed_qty` supplied on the request,
    plus the quantity already finished, must equal the order's `quantity`."
    PRD §2.11: "Fifth, state legality: the target resource must be in a state
    from which the requested action is legal per §3, and an illegal source
    state is rejected with `ERR_INVALID_STATE` (HTTP 409); this check applies
    to every action endpoint."

    Design: Corner/state_machines/production_order_complete_from_draft_invalid_state
    """
    set_clock(CLOCK_START_ISO)
    catalogue = setup_catalogue()
    order = create_order(catalogue, quantity=1, disposition="SOLD", priority_rank=1)
    assert order["status"] == "DRAFT"

    response = api.complete_production_order(
        order["id"],
        complete_production_order_payload(completed_qty=1),
        PLANNER,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert response.status_code == 409

    unchanged = get_success_data(api.get_production_order(order["id"], ADMIN))
    assert unchanged["status"] == "DRAFT", "a DRAFT order must not be completed"
    assert unchanged["completed_qty"] == 0, "no car may be marked finished"
    assert unchanged["version"] == order["version"], "the rejected write must not version"


def test_cancel_order_twice_second_attempt_rejected(api):
    """PRD §3.4: "Cancellation is legal from `DRAFT` or `COMPONENT_RESERVED`,
    and the request accepts an optional `reason`."
    PRD §3.4: "Either cancellation moves the order to `CANCELLED` and
    increments its `version`."

    Design: Corner/state_machines/production_order_cancel_twice_second_invalid_state
    """
    set_clock(CLOCK_START_ISO)
    catalogue = setup_catalogue()
    order = create_order(catalogue, quantity=1, disposition="SOLD", priority_rank=1)

    first = validate_success(
        api.cancel_production_order(order["id"], PLANNER, {"reason": "customer withdrew"})
    )
    assert first["status"] == "CANCELLED"

    second = api.cancel_production_order(
        order["id"], PLANNER, {"reason": "customer withdrew"}
    )
    validate_error(second, ApiErrorId.ERR_INVALID_STATE)
    assert second.status_code == 409

    unchanged = get_success_data(api.get_production_order(order["id"], ADMIN))
    assert unchanged["status"] == "CANCELLED", "the repeat cancel changed nothing"
    assert unchanged["version"] == order["version"] + 1, (
        "only the successful cancellation may bump the version"
    )


def test_complete_already_completed_order_rejected_as_terminal(api):
    """PRD §3.4: "An order that has already reached `COMPLETED` or `CANCELLED`
    accepts no further transition and is rejected with `ERR_ALREADY_TERMINAL`
    (HTTP 409); the fleet cap is re-checked here as it was at release, with a
    breach rejected as `ERR_FLEET_CAP_EXCEEDED` (HTTP 402)."
    PRD §2.11: "Sixth, terminality: a resource that has already reached a
    terminal state accepts no further transitions, and an attempt is rejected
    with `ERR_ALREADY_TERMINAL` (HTTP 409); this check guards order completion,
    sale settlement and retrofit-program start."

    Design: Corner/state_machines/production_order_complete_after_completed_already_terminal
    """
    set_clock(CLOCK_START_ISO)
    world = _completed_retained_car_world()
    order = world["order"]
    assert order["status"] == "COMPLETED"
    assert len(world["cars"]) == 1

    response = api.complete_production_order(
        order["id"],
        complete_production_order_payload(completed_qty=1, completion_date="2026-09-15"),
        PLANNER,
    )
    validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL)
    assert response.status_code == 409

    unchanged = get_success_data(api.get_production_order(order["id"], ADMIN))
    assert unchanged["status"] == "COMPLETED"
    assert unchanged["completed_qty"] == 1
    assert unchanged["version"] == order["version"], "the rejected write must not version"

    cars, meta = validate_paginated(
        api.list_lease_fleet_cars(ADMIN, {"production_order_id": order["id"]})
    )
    assert meta["total_count"] == 1, "no second fleet car may be minted"
    assert len(cars) == 1


def test_terminate_draft_contract_rejected_as_invalid_state(api):
    """PRD §3.5: "Termination ends the contract, and it does not silently
    strand live placements. It is legal from `ACTIVE`."
    PRD §2.11: "Fifth, state legality: the target resource must be in a state
    from which the requested action is legal per §3, and an illegal source
    state is rejected with `ERR_INVALID_STATE` (HTTP 409); this check applies
    to every action endpoint."

    Design: Corner/state_machines/lease_contract_terminate_from_draft_invalid_state
    """
    set_clock(CLOCK_START_ISO)
    contract = create_lessee_and_contract(activate=False)["contract"]
    assert contract["status"] == "DRAFT"

    response = api.terminate_lease_contract(contract["id"], LEASE)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert response.status_code == 409

    unchanged = get_success_data(api.get_lease_contract(contract["id"], ADMIN))
    assert unchanged["status"] == "DRAFT", "a never-activated contract stays DRAFT"
    assert unchanged["version"] == contract["version"]


def test_activate_terminated_contract_rejected_as_invalid_state(api):
    """PRD §3.5: "A contract is put into force by activation, which is legal
    only from `DRAFT`."
    PRD §3.5: "`TERMINATED` and `EXPIRED` are the contract's terminal states,
    and a contract that reaches either accepts no further transitions."

    Design: Corner/state_machines/lease_contract_activate_after_terminated_invalid_state
    """
    set_clock(CLOCK_START_ISO)
    contract = create_lessee_and_contract(activate=True)["contract"]
    terminated = validate_success(
        api.terminate_lease_contract(contract["id"], LEASE)
    )
    assert terminated["status"] == "TERMINATED"

    response = api.activate_lease_contract(contract["id"], LEASE)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert response.status_code == 409

    unchanged = get_success_data(api.get_lease_contract(contract["id"], ADMIN))
    assert unchanged["status"] == "TERMINATED"
    assert unchanged["version"] == terminated["version"]


def test_resume_active_placement_rejected_as_invalid_state(api):
    """PRD §3.6: "Resumption is legal from `SUSPENDED` or from `REASSIGNED`,
    and it requires the governing contract to still be `ACTIVE` and the parent
    car to be `HELD`; it returns the placement to `ACTIVE`, restarts the meter,
    puts the car back to `ASSIGNED`, and increments both versions."

    Design: Corner/state_machines/car_assignment_resume_from_active_invalid_state
    """
    world = setup_assigned_car(
        changeover_start="2026-09-05",
        completion_date="2026-09-15",
        start_date="2026-10-01",
        end_date="2026-10-31",
        mileage_allowance=1000,
    )
    assignment = world["assignment"]
    assert assignment["status"] == "ACTIVE"

    response = api.resume_car_assignment(assignment["id"], LEASE)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert response.status_code == 409

    unchanged = get_success_data(api.get_car_assignment(assignment["id"], ADMIN))
    assert unchanged["status"] == "ACTIVE", "an ACTIVE placement is not resumable"
    car = get_success_data(api.get_lease_fleet_car(world["car"]["id"], ADMIN))
    assert car["status"] == "ASSIGNED", "the car must stay with the placement"
    assert car["lease_contract_id"] == world["contract"]["id"]


def test_scrap_assigned_car_rejected_as_invalid_state(api):
    """PRD §3.9: "A `PortfolioManager` scraps a car from `HELD` status,
    supplying an optional `scrap_reason`."
    PRD §2.11: "Fifth, state legality: the target resource must be in a state
    from which the requested action is legal per §3, and an illegal source
    state is rejected with `ERR_INVALID_STATE` (HTTP 409); this check applies
    to every action endpoint."

    Design: Corner/state_machines/lease_fleet_car_scrap_from_assigned_invalid_state
    """
    world = _completed_retained_car_world()
    contract_world = create_lessee_and_contract()
    contract = contract_world["contract"]
    assignment = create_assignment(
        world["car"],
        contract,
        contract_world["lessee"],
        start_date="2026-10-01",
        end_date="2026-10-31",
        mileage_allowance=1000,
    )
    assert assignment["status"] == "ACTIVE"

    response = api.scrap_lease_fleet_car(
        world["car"]["id"], PORTFOLIO, scrap_lease_fleet_car_payload("end of life")
    )
    # PRD 2.11 puts state legality (p5, ERR_INVALID_STATE) ahead of car
    # availability (p21, ERR_CAR_NOT_HELD) in its evaluation order, but p21
    # names scrapping explicitly as an ERR_CAR_NOT_HELD site, so either code is
    # a faithful reading of the two clauses.
    validate_error_is_one_of(
        response, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_CAR_NOT_HELD]
    )
    assert response.status_code == 409

    unchanged = get_success_data(api.get_lease_fleet_car(world["car"]["id"], ADMIN))
    assert unchanged["status"] == "ASSIGNED", "a placed car cannot be scrapped"
    assert unchanged["lease_contract_id"] == contract["id"]
    unchanged_contract = get_success_data(api.get_lease_contract(contract["id"], ADMIN))
    assert unchanged_contract["capital_allocation_cents"] == 0, (
        "the rejected scrap must not re-derive any contract's capital"
    )


def test_scrap_already_scrapped_car_rejected_as_invalid_state(api):
    """PRD §3.9: "`SOLD` and `SCRAPPED` are the car's terminal states; a car
    that reaches either accepts no further transitions, with the single
    exception of the void path, which returns a sold car to `HELD` when its
    sale is still pending settlement."

    Design: Corner/state_machines/lease_fleet_car_scrap_after_scrapped_invalid_state
    """
    world = _completed_retained_car_world()
    first = validate_success(
        api.scrap_lease_fleet_car(
            world["car"]["id"],
            PORTFOLIO,
            scrap_lease_fleet_car_payload("regulatory life ended"),
        )
    )
    assert first["status"] == "SCRAPPED"

    second = api.scrap_lease_fleet_car(
        world["car"]["id"],
        PORTFOLIO,
        scrap_lease_fleet_car_payload("regulatory life ended"),
    )
    validate_error_is_one_of(
        second, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_CAR_NOT_HELD]
    )
    assert second.status_code == 409

    unchanged = get_success_data(api.get_lease_fleet_car(world["car"]["id"], ADMIN))
    assert unchanged["status"] == "SCRAPPED", "the repeat scrap changed nothing"
    assert unchanged["version"] == first["version"]


def test_complete_planned_retrofit_program_rejected_as_invalid_state(api):
    """PRD §3.8: "The program completes only from `IN_PROGRESS`, and only when
    every covered car type has at least one work order in `COMPLETED` status
    and every work order of the program is in `COMPLETED` or `CANCELLED`
    status."

    Design: Corner/state_machines/retrofit_program_complete_from_planned_invalid_state
    """
    set_clock(CLOCK_START_ISO)
    program = create_retrofit_program(
        {},
        cover_car_types=False,
        mandate_code="MAND-2026-01",
        description="Boxcar door retrofit mandate",
        compliance_deadline_date="2026-12-31",
        required_shop_days_per_car=10,
    )["program"]
    assert program["status"] == "PLANNED"

    response = api.complete_retrofit_program(program["id"], RETROFIT)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert response.status_code == 409

    unchanged = get_success_data(api.get_retrofit_program(program["id"], ADMIN))
    assert unchanged["status"] == "PLANNED", "a never-started program cannot complete"
    assert unchanged["program_cost_cents"] == 0
    assert unchanged["version"] == program["version"]


def test_start_voided_retrofit_program_rejected_as_terminal(api):
    """PRD §3.8: "A program that has already reached `COMPLETED` or `VOIDED`
    accepts no further transition and is rejected with `ERR_ALREADY_TERMINAL`
    (HTTP 409)."
    PRD §2.11: "Sixth, terminality: a resource that has already reached a
    terminal state accepts no further transitions, and an attempt is rejected
    with `ERR_ALREADY_TERMINAL` (HTTP 409); this check guards order completion,
    sale settlement and retrofit-program start."

    Design: Corner/state_machines/retrofit_program_start_after_voided_already_terminal
    """
    set_clock(CLOCK_START_ISO)
    catalogue = setup_catalogue()
    program = create_retrofit_program(
        catalogue,
        mandate_code="MAND-2026-01",
        description="Boxcar door retrofit mandate",
        compliance_deadline_date="2026-12-31",
        required_shop_days_per_car=10,
    )["program"]
    validate_success(api.start_retrofit_program(program["id"], RETROFIT))
    voided = validate_success(
        api.void_retrofit_program(program["id"], RETROFIT, {"reason": "mandate superseded"})
    )
    assert voided["status"] == "VOIDED"

    response = api.start_retrofit_program(program["id"], RETROFIT)
    validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL)
    assert response.status_code == 409

    unchanged = get_success_data(api.get_retrofit_program(program["id"], ADMIN))
    assert unchanged["status"] == "VOIDED", "a voided mandate cannot restart"
    assert unchanged["version"] == voided["version"]


def test_complete_scheduled_work_order_rejected_as_invalid_state(api):
    """PRD §3.8: "Completion is legal from `IN_PROGRESS` and requires the work
    order's shop window not to be past the program's
    `compliance_deadline_date`."
    PRD §3.8: "On success the work order becomes `COMPLETED`, the parent car
    returns to `HELD`, its `built_date` is set to the completion date and its
    `regulatory_life_end_date` is re-derived from that new build date"

    Design: Corner/state_machines/retrofit_work_order_complete_from_scheduled_invalid_state
    """
    catalogue = setup_catalogue(
        coating_part_number="CT-400",
        coating_unit_cost_cents=50000,
        coating_lead_time_days=90,
        coating_overrides={"on_hand_qty": 0},
    )
    world = setup_retrofit_program_with_car(
        catalogue=catalogue,
        required_component_id=catalogue["coating"]["id"],
        work_order_start="2026-10-01",
        shop_line="SHOP-R8A",
        component_qty_consumed=2,
    )
    work_order = world["work_order"]
    assert work_order["status"] == "SCHEDULED"

    response = api.complete_retrofit_work_order(work_order["id"], PLANNER)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert response.status_code == 409

    unchanged = get_success_data(api.get_retrofit_work_order(work_order["id"], ADMIN))
    assert unchanged["status"] == "SCHEDULED", "shop work cannot complete before it starts"
    component = get_success_data(api.get_component(catalogue["coating"]["id"], ADMIN))
    assert component["on_hand_qty"] == 0, "the rejected call consumed no kit"
    car = get_success_data(api.get_lease_fleet_car(world["car"]["id"], ADMIN))
    assert car["status"] == "UNDER_REPAIR", "the car is not returned to service"


def test_cancel_confirmed_purchase_order_rejected_as_invalid_state(api):
    """PRD §3.2: "A placed purchase can be confirmed by its supplier, moving it
    to `CONFIRMED`, and it can be cancelled while it is still `PLACED`, moving
    it to `CANCELLED`; once confirmed it can no longer be cancelled."
    PRD §3.2: "an action attempted from the wrong source state — confirming a
    purchase that is not `PLACED`, receiving against one that is not
    `CONFIRMED`, or cancelling one that is not `PLACED` — is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/component_purchase_order_cancel_after_confirmed_invalid_state
    """
    catalogue = setup_catalogue(wheelset_overrides={"on_hand_qty": 0})
    purchase = receive_component_stock(
        catalogue["wheelset"], 4, confirm=True, apply_receipt=False
    )["purchase_order"]
    assert purchase["status"] == "CONFIRMED"

    response = api.cancel_component_purchase_order(
        purchase["id"], SUPPLY, {"reason": "supplier slipped"}
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert response.status_code == 409

    unchanged = get_success_data(api.get_component_purchase_order(purchase["id"], ADMIN))
    assert unchanged["status"] == "CONFIRMED", "a confirmed purchase stays confirmed"
    assert unchanged["version"] == purchase["version"]
    component = get_success_data(api.get_component(catalogue["wheelset"]["id"], ADMIN))
    assert component["on_hand_qty"] == 0, "cancellation never moves stock either way"


def test_settle_voided_sale_rejected_as_terminal(api):
    """PRD §3.9: "A sale that has already reached `SETTLED` or `VOIDED`
    accepts no further transition and is rejected with `ERR_ALREADY_TERMINAL`
    (HTTP 409)."
    PRD §2.11: "Sixth, terminality: a resource that has already reached a
    terminal state accepts no further transitions, and an attempt is rejected
    with `ERR_ALREADY_TERMINAL` (HTTP 409); this check guards order completion,
    sale settlement and retrofit-program start."

    Design: Corner/state_machines/lease_fleet_sale_settle_after_voided_already_terminal
    """
    world = _completed_retained_car_world()
    advance_clock_to("2026-10-01T00:00:00Z")
    sale = create_sale(
        world["car"],
        sale_price_cents=1500000,
        sale_date="2026-10-01",
        writeback_liability_cents=0,
        buyer_name="Rail Trust LLC",
    )
    voided = void_sale(sale["id"], "buyer withdrew")
    assert voided["status"] == "VOIDED"

    response = api.settle_lease_fleet_sale(sale["id"], PORTFOLIO)
    validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL)
    assert response.status_code == 409

    unchanged = get_success_data(api.get_lease_fleet_sale(sale["id"], ADMIN))
    assert unchanged["status"] == "VOIDED"
    assert unchanged["version"] == voided["version"]
    car = get_success_data(api.get_lease_fleet_car(world["car"]["id"], ADMIN))
    assert car["status"] == "HELD", "the void already returned the car to the fleet"

    reconciliation = get_success_data(api.get_portfolio_ledger_reconciliation(ADMIN))
    assert reconciliation["realized_gain_cents"] == 0, (
        "the voided sale must leave the ledger exactly where it stood"
    )
    assert reconciliation["committed_capital_cents"] == 1450000, (
        "the retained completion's capital is undiminished by a voided sale"
    )


def test_void_settled_sale_rejected_as_invalid_state(api):
    """PRD §3.9: "Voiding is the compensating action and it must be exact. It
    is legal only from `PENDING_SETTLEMENT` and accepts an optional `reason`."
    PRD §2.11: "Fifth, state legality: the target resource must be in a state
    from which the requested action is legal per §3, and an illegal source
    state is rejected with `ERR_INVALID_STATE` (HTTP 409); this check applies
    to every action endpoint."

    Design: Corner/state_machines/lease_fleet_sale_void_after_settled_invalid_state
    """
    world = _completed_retained_car_world()
    advance_clock_to("2026-10-01T00:00:00Z")
    sale = create_sale(
        world["car"],
        sale_price_cents=1500000,
        sale_date="2026-10-01",
        writeback_liability_cents=0,
        buyer_name="Rail Trust LLC",
    )
    settled = settle_sale(sale["id"])
    assert settled["status"] == "SETTLED"

    response = api.void_lease_fleet_sale(sale["id"], PORTFOLIO, {"reason": "buyer withdrew"})
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert response.status_code == 409

    unchanged = get_success_data(api.get_lease_fleet_sale(sale["id"], ADMIN))
    assert unchanged["status"] == "SETTLED", "a settled sale cannot be voided"
    assert unchanged["version"] == settled["version"]
    reconciliation = get_success_data(api.get_portfolio_ledger_reconciliation(ADMIN))
    assert reconciliation["realized_gain_cents"] == 90000, (
        "the settled gain must not be reversed by the rejected void"
    )


def test_confirm_cancelled_purchase_order_rejected_as_invalid_state(api):
    """PRD §3.2: "an action attempted from the wrong source state — confirming
    a purchase that is not `PLACED`, receiving against one that is not
    `CONFIRMED`, or cancelling one that is not `PLACED` — is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/component_purchase_order_confirm_after_cancelled_invalid_state
    """
    set_clock(CLOCK_START_ISO)
    catalogue = setup_catalogue()
    purchase = receive_component_stock(
        catalogue["wheelset"], 4, confirm=False, apply_receipt=False
    )["purchase_order"]
    assert purchase["status"] == "PLACED"

    cancelled = validate_success(
        api.cancel_component_purchase_order(
            purchase["id"], SUPPLY, {"reason": "no longer needed"}
        )
    )
    assert cancelled["status"] == "CANCELLED"

    response = api.confirm_component_purchase_order(purchase["id"], SUPPLY)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert response.status_code == 409

    unchanged = get_success_data(api.get_component_purchase_order(purchase["id"], ADMIN))
    assert unchanged["status"] == "CANCELLED", "a cancelled purchase stays cancelled"
    assert unchanged["version"] == cancelled["version"]


def test_cancel_cancelled_work_order_rejected_as_invalid_state(api):
    """PRD §3.8: "A scheduled work order that has not started may instead be
    cancelled, which sets it to `CANCELLED`, increments its `version`, and
    re-derives the program cost. `COMPLETED` and `CANCELLED` are the work
    order's terminal states."
    PRD §2.11: "Fifth, state legality: the target resource must be in a state
    from which the requested action is legal per §3, and an illegal source
    state is rejected with `ERR_INVALID_STATE` (HTTP 409); this check applies
    to every action endpoint."

    Design: Corner/state_machines/retrofit_work_order_cancel_after_cancelled_invalid_state
    """
    catalogue = setup_catalogue()
    world = setup_retrofit_program_with_car(
        catalogue=catalogue,
        work_order_start="2026-10-01",
        shop_line="SHOP-R8A",
        component_qty_consumed=2,
    )
    work_order = world["work_order"]
    cancelled = validate_success(
        api.cancel_retrofit_work_order(
            work_order["id"], PLANNER, {"reason": "shop capacity pulled"}
        )
    )
    assert cancelled["status"] == "CANCELLED"

    response = api.cancel_retrofit_work_order(
        work_order["id"], PLANNER, {"reason": "shop capacity pulled"}
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert response.status_code == 409

    unchanged = get_success_data(api.get_retrofit_work_order(work_order["id"], ADMIN))
    assert unchanged["status"] == "CANCELLED"
    assert unchanged["version"] == cancelled["version"]
    car = get_success_data(api.get_lease_fleet_car(world["car"]["id"], ADMIN))
    assert car["status"] == "UNDER_REPAIR", (
        "a cancelled work order does not return the car to the fleet"
    )


def test_patch_superseded_endorsement_rejected_as_invalid_state(api):
    """PRD §3.3: "An edit attempted from a status the editing write does not
    accept is rejected with `ERR_INVALID_STATE` (HTTP 409), and `APPLIED`,
    `REJECTED` and `SUPERSEDED` are terminal: an endorsement that reaches any
    of them accepts no further transitions."
    PRD §3.3: "A successful create starts the endorsement in `PENDING`,
    supersedes any earlier `PENDING` endorsement for the same original
    component on that order, and increments the production order's `version`."

    Design: Corner/state_machines/substitution_endorsement_patch_after_superseded_invalid_state
    """
    world = setup_order_with_endorsement(
        substitute_part_number="WS-SUB",
        substitute_qty_per_car=4,
        decides_material=False,
    )
    superseded_id = world["endorsement"]["id"]
    live = create_endorsement(
        world["order"],
        world["catalogue"]["wheelset"],
        world["substitute"],
        substitute_qty_per_car=3,
        decides_material=False,
    )

    superseded = get_success_data(
        api.get_substitution_endorsement(superseded_id, ADMIN)
    )
    assert superseded["status"] == "SUPERSEDED", (
        "raising a second endorsement for the same original component supersedes the first"
    )

    response = api.patch_substitution_endorsement(
        superseded_id,
        patch_substitution_endorsement_payload(status="REJECTED"),
        LEASE,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert response.status_code == 409

    unchanged = get_success_data(api.get_substitution_endorsement(superseded_id, ADMIN))
    assert unchanged["status"] == "SUPERSEDED"
    untouched = get_success_data(api.get_substitution_endorsement(live["id"], ADMIN))
    assert untouched["status"] == "PENDING", "the live endorsement is untouched"
