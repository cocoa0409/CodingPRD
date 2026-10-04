"""State machines: preconditions, idempotency of repeat writes, initial states.

These claims all sit beside a transition rather than on it: an upstream
aggregate that is missing, a segregation-of-duties duty that is violated, a
retry budget that is spent, a version that has moved, a target car that is not
free.  Each test drives the write, pins the exact rejection, and then re-reads
the subject to show the rejection left nothing behind — including the fields a
successful write would have re-derived.
"""

from test_helpers import (
    ApiErrorId,
    CLOCK_START_ISO,
    TEST_USERS,
    build_user_headers,
    complete_order,
    create_assignment,
    create_endorsement,
    create_lessee_and_contract,
    create_order,
    draft_lease_amendment_payload,
    get_success_data,
    patch_substitution_endorsement_payload,
    reassign_car_assignment_payload,
    reject_endorsement,
    return_endorsement_to_pending,
    set_clock,
    setup_assigned_car,
    setup_catalogue,
    setup_order_in_state,
    setup_retrofit_program_with_car,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
LEASE = TEST_USERS["lease_administrator_headers"]


def _two_component_catalogue():
    """A car type whose bill of materials is one wheelset row and one casting row."""
    return setup_catalogue(
        include_coating=False,
        wheelset_part_number="WS-500",
        wheelset_unit_cost_cents=200000,
        casting_part_number="CS-600",
        casting_unit_cost_cents=150000,
    )


def test_reserve_order_without_bill_of_materials_rejected(api):
    """PRD §3.2: "Before any stock moves, the order must actually have a bill of
    materials: an order whose car type has no bill-of-material rows cannot
    reserve anything and is rejected with `ERR_PREREQUISITE_NOT_MET` (HTTP
    409)."

    Design: Corner/state_machines/production_order_reserve_without_bom_rows_prerequisite_not_met
    """
    set_clock(CLOCK_START_ISO)
    catalogue = setup_catalogue(include_bom=False)
    order = create_order(catalogue, quantity=1, disposition="SOLD", priority_rank=1)

    response = api.reserve_components(order["id"], PLANNER)
    validate_error(response, ApiErrorId.ERR_PREREQUISITE_NOT_MET)
    assert response.status_code == 409

    unchanged = get_success_data(api.get_production_order(order["id"], ADMIN))
    assert unchanged["status"] == "DRAFT", "the order must stay in DRAFT"
    assert unchanged["version"] == order["version"], "the rejected write must not version"


def test_second_approval_of_endorsement_rejected(api):
    """PRD §3.3: "Approving an endorsement that is not `PENDING` is rejected
    with `ERR_INVALID_STATE` (HTTP 409), and approving one whose substitute
    cannot cover the order is rejected with `ERR_COMPONENT_SHORTAGE` (HTTP 409)
    by the same stock test that guards reservation."
    PRD §3.1: "The change fee actually charged is the smaller of the raw fee
    and the cap, and the order's `unit_price_cents` is the unrounded total plus
    that change fee."

    Design: Corner/state_machines/substitution_endorsement_approve_twice_second_invalid_state
    """
    set_clock(CLOCK_START_ISO)
    catalogue = _two_component_catalogue()
    order = create_order(catalogue, quantity=1, disposition="SOLD", priority_rank=1)
    endorsement = create_endorsement(
        order,
        catalogue["wheelset"],
        catalogue["casting"],
        substitute_qty_per_car=2,
        decides_material=True,
    )

    first = validate_success(
        api.approve_substitution_endorsement(endorsement["id"], LEASE)
    )
    assert first["status"] == "APPROVED"
    after_first = get_success_data(api.get_production_order(order["id"], ADMIN))
    assert after_first["unit_price_cents"] == 1115000, (
        "the substitute stands in for the original row and the change fee is charged once"
    )

    second = api.approve_substitution_endorsement(endorsement["id"], LEASE)
    validate_error(second, ApiErrorId.ERR_INVALID_STATE)
    assert second.status_code == 409

    unchanged = get_success_data(api.get_substitution_endorsement(endorsement["id"], ADMIN))
    assert unchanged["status"] == "APPROVED", "the repeat approval changed nothing"
    after_second = get_success_data(api.get_production_order(order["id"], ADMIN))
    assert after_second["unit_price_cents"] == 1115000
    assert after_second["unit_price_cents"] == after_first["unit_price_cents"]


def test_self_approval_of_endorsement_rejected(api):
    """PRD §3.3: "It is legal only from `PENDING`, and it carries a
    segregation-of-duties precondition: the acting `X-User-ID` must not be the
    `X-User-ID` that created the endorsement, and an approval attempted by the
    creator is rejected with `ERR_SELF_APPROVAL_FORBIDDEN` (HTTP 403)."

    Design: Corner/state_machines/substitution_endorsement_self_approval_forbidden
    """
    set_clock(CLOCK_START_ISO)
    catalogue = _two_component_catalogue()
    order = create_order(catalogue, quantity=1, disposition="SOLD", priority_rank=1)
    assert order["unit_price_cents"] == 1600000

    creator = TEST_USERS["production_planner_headers"]
    endorsement = create_endorsement(
        order,
        catalogue["wheelset"],
        catalogue["casting"],
        substitute_qty_per_car=2,
        decides_material=True,
        headers=creator,
    )
    same_operator = build_user_headers(creator["X-User-ID"], "LeaseAdministrator")

    response = api.approve_substitution_endorsement(endorsement["id"], same_operator)
    validate_error(response, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN)
    assert response.status_code == 403

    unchanged = get_success_data(api.get_substitution_endorsement(endorsement["id"], ADMIN))
    assert unchanged["status"] == "PENDING", "the creator's own approval must not land"
    order_after = get_success_data(api.get_production_order(order["id"], ADMIN))
    assert order_after["unit_price_cents"] == 1600000, "no re-quote side effect may fire"


def test_second_return_to_pending_rejected_retry_exhausted(api):
    """PRD §3.3: "The retry is bounded: an endorsement that has already been
    rejected once may be returned to `PENDING` one time, and the third
    rejection is terminal — an attempt to return it to `PENDING` a second time
    is rejected with `ERR_ENDORSEMENT_RETRY_EXHAUSTED` (HTTP 409)."

    Design: Corner/state_machines/substitution_endorsement_retry_exhausted_on_second_return_to_pending
    """
    set_clock(CLOCK_START_ISO)
    catalogue = _two_component_catalogue()
    order = create_order(catalogue, quantity=1, disposition="SOLD", priority_rank=1)
    endorsement = create_endorsement(
        order,
        catalogue["wheelset"],
        catalogue["casting"],
        substitute_qty_per_car=2,
        decides_material=False,
    )

    assert reject_endorsement(endorsement["id"])["status"] == "REJECTED"
    assert return_endorsement_to_pending(endorsement["id"])["status"] == "PENDING"
    assert reject_endorsement(endorsement["id"])["status"] == "REJECTED"

    exhausted = api.patch_substitution_endorsement(
        endorsement["id"],
        patch_substitution_endorsement_payload(status="PENDING"),
        PLANNER,
    )
    validate_error(exhausted, ApiErrorId.ERR_ENDORSEMENT_RETRY_EXHAUSTED)
    assert exhausted.status_code == 409

    unchanged = get_success_data(api.get_substitution_endorsement(endorsement["id"], ADMIN))
    assert unchanged["status"] == "REJECTED", "the exhausted retry changed nothing"


def test_amendment_redraft_with_stale_version_rejected(api):
    """PRD §2.7: "If the contract's version has advanced since the client read
    it, the draft is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.5: "This guard exists because a contract that is already
    `AMENDMENT_DRAFTED` may legitimately be redrafted before ratification, so a
    second draft supersedes the first and the two writes are distinguished only
    by the version the writer observed."

    Design: Corner/state_machines/lease_contract_amendment_redraft_stale_version_rejected
    """
    set_clock(CLOCK_START_ISO)
    contract = create_lessee_and_contract(activate=True)["contract"]
    observed = contract["version"]

    first = validate_success(
        api.draft_lease_amendment(
            contract["id"],
            draft_lease_amendment_payload(
                per_diem_rate_cents=30000,
                liability_bearer="LESSEE",
                expected_lease_version=observed,
            ),
            LEASE,
        )
    )
    assert first["status"] == "AMENDMENT_DRAFTED"
    after_first = get_success_data(api.get_lease_contract(contract["id"], ADMIN))
    assert after_first["version"] == observed + 1

    stale = api.draft_lease_amendment(
        contract["id"],
        draft_lease_amendment_payload(
            per_diem_rate_cents=32000,
            liability_bearer="LESSEE",
            expected_lease_version=observed,
        ),
        LEASE,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert stale.status_code == 412

    unchanged = get_success_data(api.get_lease_contract(contract["id"], ADMIN))
    assert unchanged["status"] == "AMENDMENT_DRAFTED", "the stale draft stored nothing"
    assert unchanged["version"] == after_first["version"]
    assert unchanged["per_diem_rate_cents"] == 30000, (
        "the stale redraft's 32000 was not stored"
    )


def test_reassign_placement_onto_non_held_car_rejected(api):
    """PRD §3.6: "It is legal from `ACTIVE`, and the request names the
    `target_lease_fleet_car_id` and accepts an optional `effective_date`. The
    target car must be `HELD` and must carry the same `lease_contract_id` as
    the source car, so a placement can never hop between contracts through this
    route."
    PRD §2.11: "Fifth, state legality: the target resource must be in a state
    from which the requested action is legal per §3, and an illegal source
    state is rejected with `ERR_INVALID_STATE` (HTTP 409); this check applies
    to every action endpoint."

    Design: Corner/state_machines/car_assignment_reassign_to_car_not_held_rejected
    """
    world = setup_assigned_car(
        car_count=2,
        changeover_start="2026-09-05",
        completion_date="2026-09-25",
        start_date="2026-10-01",
        end_date="2026-10-31",
        mileage_allowance=1000,
    )
    source = world["assignment"]
    target_car = world["cars"][1]
    create_assignment(
        target_car,
        world["contract"],
        world["lessee"],
        start_date="2026-10-01",
        end_date="2026-10-31",
        mileage_allowance=1000,
    )

    response = api.reassign_car_assignment(
        source["id"],
        reassign_car_assignment_payload(target_lease_fleet_car_id=target_car["id"]),
        LEASE,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert response.status_code == 409

    unchanged = get_success_data(api.get_car_assignment(source["id"], ADMIN))
    assert unchanged["status"] == "ACTIVE", "the source placement is not reassigned"
    target = get_success_data(api.get_lease_fleet_car(target_car["id"], ADMIN))
    assert target["status"] == "ASSIGNED", "a busy car cannot receive a placement"
    assignments, meta = validate_paginated(api.list_car_assignments(ADMIN))
    assert meta["total_count"] == 2, "no replacement placement may be minted"
    assert len(assignments) == 2


def test_retained_completion_mints_cars_in_held_state(api):
    """PRD §3.4: "On the retained branch, completion creates one fleet car per
    car built, each starting in `HELD` with its `production_order_id` pointing
    at the producing order, its `acquisition_cost_cents` equal to the order's
    `unit_price_cents`, and its `built_date` set to the completion date"
    PRD §2.3: "`total_count` is the number of records matching the filter
    across the whole result set, not the number in the current page"

    Design: Corner/state_machines/lease_fleet_car_initial_state_held_on_retained_completion
    """
    set_clock(CLOCK_START_ISO)
    world = setup_order_in_state(
        "IN_PRODUCTION",
        disposition="RETAINED",
        quantity=1,
        priority_rank=1,
        changeover_start="2026-09-05",
    )
    order = world["order"]
    assert order["status"] == "IN_PRODUCTION"

    complete_order(order["id"], completed_qty=1, completion_date="2026-09-15")

    cars, meta = validate_paginated(
        api.list_lease_fleet_cars(ADMIN, {"status": "HELD"})
    )
    assert meta["total_count"] == 1, "the completion minted exactly one free car"
    assert len(cars) == 1
    car = cars[0]
    assert car["status"] == "HELD"
    assert car["status"] != "ASSIGNED", "a freshly minted car is never placed"
    assert car["production_order_id"] == order["id"]


def test_portfolio_ledger_starts_open_with_zero_balances(api):
    """PRD §3.9: "The portfolio ledger itself is a singleton that is always
    `OPEN` and has no terminal state."
    PRD §2.9: "It carries three derived figures: `committed_capital_cents`, the
    capital committed to the fleet through retained orders;
    `realized_gain_cents`, the cumulative gain or loss realized on settled
    sales; and `fleet_nbv_cents`, the current net book value of the live
    fleet."

    Design: Corner/state_machines/portfolio_ledger_initial_state_open_with_zero_balances
    """
    set_clock(CLOCK_START_ISO)

    ledger = validate_success(api.get_portfolio_ledger(ADMIN))
    assert ledger["status"] == "OPEN"
    assert ledger["committed_capital_cents"] == 0
    assert ledger["realized_gain_cents"] == 0
    assert ledger["fleet_nbv_cents"] == 0

    reconciliation = validate_success(api.get_portfolio_ledger_reconciliation(ADMIN))
    assert reconciliation["oldest_basis_cents"] == 0
    assert reconciliation["newest_basis_cents"] == 0
    assert reconciliation["drift_cents"] == 0


def test_start_work_order_consumes_retrofit_kit(api):
    """PRD §3.8: "On success the work order becomes `IN_PROGRESS`, and — when
    the program names a `required_component_id` — the component's
    `on_hand_qty` is decremented by the work order's `component_qty_consumed`
    and its `reserved_qty` and `shortfall_qty` are re-derived by the allocation
    rule of §3.2."
    PRD §3.2: "The retrofit term is the sum of `component_qty_consumed` over
    every retrofit work order that is in `IN_PROGRESS` status and whose program
    names this component as its `required_component_id`; work orders in
    `SCHEDULED`, `COMPLETED` or `CANCELLED` contribute nothing."

    Design: Corner/state_machines/retrofit_work_order_start_valid_transition_consumes_kit
    """
    catalogue = setup_catalogue(
        coating_part_number="CT-400",
        coating_unit_cost_cents=50000,
        coating_lead_time_days=90,
        coating_overrides={"on_hand_qty": 5},
    )
    world = setup_retrofit_program_with_car(
        catalogue=catalogue,
        required_component_id=catalogue["coating"]["id"],
        work_order_start="2026-11-01",
        shop_line="SHOP-R8A",
        component_qty_consumed=2,
    )
    work_order = world["work_order"]
    assert work_order["status"] == "SCHEDULED"

    started = validate_success(
        api.start_retrofit_work_order(work_order["id"], PLANNER)
    )
    assert started["status"] == "IN_PROGRESS"

    refreshed = get_success_data(api.get_retrofit_work_order(work_order["id"], ADMIN))
    assert refreshed["status"] == "IN_PROGRESS"
    assert refreshed["version"] == work_order["version"] + 1

    component = get_success_data(api.get_component(catalogue["coating"]["id"], ADMIN))
    assert component["on_hand_qty"] == 3, "five units received minus the two-unit kit"
    assert component["reserved_qty"] == 2, (
        "the in-progress work order's kit is held against the component"
    )
