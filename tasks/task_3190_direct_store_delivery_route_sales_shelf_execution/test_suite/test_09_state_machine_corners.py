"""State-machine corners: initial states, preconditions, terminal lockdown,
idempotency, cyclic suspend/reactivate, clock-driven expiry, dispute cycle."""
from test_helpers import (
    ApiErrorId,
    api_client,
    balance_settlement,
    create_assignment,
    create_order,
    create_product,
    create_rep,
    create_route,
    create_route_day,
    create_settlement,
    create_store,
    deliver_line,
    deliver_order,
    get_credit,
    get_lot_by_code,
    load_route_day,
    lot_entry,
    make_admin_headers,
    make_rep_headers,
    make_supervisor_headers,
    order_line,
    set_clock,
    start_route_day,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_route_day_created_in_planned_initial_state(api):
    """PRD §3.2: "A new route day is born PLANNED with loaded_cases,
    delivered_cases, and stale_pulled_cases all at zero."

    Design: Corner/state_machines/route_day_created_in_planned_initial_state
    """
    rep = create_rep()
    store = create_store()
    route = create_route(rep["id"])
    create_assignment(route["id"], store["id"])

    day = create_route_day(route["id"])
    assert day["status"] == "PLANNED"
    assert day["loaded_cases"] == 0
    assert day["delivered_cases"] == 0
    assert day["stale_pulled_cases"] == 0
    assert day["capacity_cases"] == 100
    assert day["is_event_day"] is False
    assert day["event_surge_cases"] == 0


def test_start_from_planned_rejected_not_loaded(api):
    """PRD §3.3: "Starting the route day — again the assigned rep's action,
    requiring the day to be LOADED (ERR_ROUTE_DAY_NOT_LOADED otherwise) — flips
    every lot of the day from SEALED to OPEN and moves the day to IN_PROGRESS,
    incrementing the day's version."

    Design: Corner/state_machines/start_from_planned_rejected_not_loaded
    """
    rep = create_rep()
    store = create_store()
    route = create_route(rep["id"])
    create_assignment(route["id"], store["id"])
    day = create_route_day(route["id"])

    resp = api.start_route_day(day["id"], make_rep_headers(rep["id"]))
    validate_error(resp, ApiErrorId.ERR_ROUTE_DAY_NOT_LOADED)

    resp = api.get_route_day(day["id"], make_supervisor_headers())
    day_after = validate_success(resp)
    assert day_after["status"] == "PLANNED"


def test_cancel_delivered_order_returns_invalid_state(api):
    """PRD §3.4: "may cancel an order from either DRAFT or SUBMITTED, moving it
    to CANCELLED."
    PRD §5: "ERR_INVALID_STATE | 409 Conflict".

    Design: Corner/state_machines/cancel_delivered_order_returns_invalid_state
    """
    set_clock()
    rep = create_rep()
    store = create_store()
    product = create_product()
    route = create_route(rep["id"])
    create_assignment(route["id"], store["id"])
    day = create_route_day(route["id"])
    load_route_day(
        day["id"], [lot_entry(product["id"], "L-1", "2026-09-20", 10)], rep
    )
    start_route_day(day["id"], rep)
    order = create_order(day["id"], store["id"], [order_line(product["id"], 5)], rep)
    submit_order(order["id"], rep)
    deliver_order(order["id"], [deliver_line(product["id"], 5)], rep)

    resp = api.cancel_order(order["id"], make_rep_headers(rep["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    order_after = validate_success(
        api.get_order(order["id"], make_supervisor_headers())
    )
    assert order_after["status"] == "DELIVERED"
    assert order_after["gross_total_cents"] == 2500


def test_approve_already_approved_credit_is_not_idempotent(api):
    """PRD §3.7: "Approval stamps decided_by_user_id, moves the credit to
    APPROVED (terminal), and only now mutates inventory: the pinned lot's
    stale_pulled_cases increases by qty_cases, the route day's stale totals
    recompute from the lots, and if a settlement exists for the day its
    credits_cents and both expected variants recompute — with a BALANCED
    settlement auto-reopening to OPEN."
    PRD §5: "ERR_INVALID_STATE | 409 Conflict".

    Design: Corner/state_machines/approve_already_approved_credit_is_not_idempotent
    """
    set_clock()
    rep = create_rep()
    store = create_store()
    product = create_product()
    route = create_route(rep["id"])
    create_assignment(route["id"], store["id"])
    day = create_route_day(route["id"])
    load_route_day(
        day["id"], [lot_entry(product["id"], "L-ST", "2026-09-06", 20)], rep
    )
    start_route_day(day["id"], rep)

    resp = api.create_stale_credit(
        {
            "route_day_id": day["id"],
            "store_id": store["id"],
            "product_id": product["id"],
            "qty_cases": 4,
        },
        make_rep_headers(rep["id"]),
    )
    credit = validate_success(resp, expected_status=201)
    resp = api.approve_stale_credit(credit["id"], make_supervisor_headers())
    validate_success(resp)

    resp = api.approve_stale_credit(credit["id"], make_supervisor_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    credit_after = get_credit(credit["id"])
    assert credit_after["status"] == "APPROVED"
    lot = get_lot_by_code(day["id"], "L-ST")
    assert lot["stale_pulled_cases"] == 4


def test_route_suspend_reactivate_cycle_gates_planning(api):
    """PRD §3.1: "A RouteSupervisor may suspend a route (ACTIVE → SUSPENDED),
    after which planning route days, creating assignments, or loading the truck
    on that route is rejected with ERR_ROUTE_NOT_ACTIVE; reactivation
    (SUSPENDED → ACTIVE) succeeds only while the assigned representative is
    ACTIVE."

    Design: Corner/state_machines/route_suspend_reactivate_cycle_gates_planning
    """
    rep = create_rep()
    store = create_store()
    route = create_route(rep["id"])
    create_assignment(route["id"], store["id"])

    resp = api.suspend_route(route["id"], make_supervisor_headers())
    validate_success(resp)

    resp = api.create_route_day(
        {"route_id": route["id"], "service_date": "2026-09-01"},
        make_supervisor_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_ACTIVE)

    resp = api.reactivate_route(route["id"], make_supervisor_headers())
    validate_success(resp)

    resp = api.create_route_day(
        {"route_id": route["id"], "service_date": "2026-09-01"},
        make_supervisor_headers(),
    )
    day = validate_success(resp, expected_status=201)
    assert day["status"] == "PLANNED"


def test_promo_agreement_expires_when_clock_passes_window_end(api):
    """PRD §2.8: "Advancing the clock has a standing side effect: every promo
    agreement still in SCHEDULED or ACTIVE whose window_end is on or before the
    new clock date transitions automatically to EXPIRED."
    PRD §2.8: "a clock date exactly equal to window_end falls outside the
    window."

    Design: Corner/state_machines/promo_agreement_expires_when_clock_passes_window_end
    """
    set_clock()
    store = create_store()
    product = create_product()
    resp = api.create_promo_agreement(
        {
            "store_id": store["id"],
            "product_id": product["id"],
            "window_start": "2026-09-01",
            "window_end": "2026-09-10",
            "display_type": "ENDCAP",
            "rebate_cents": 5000,
        },
        make_supervisor_headers(),
    )
    agreement = validate_success(resp, expected_status=201)
    resp = api.activate_promo_agreement(agreement["id"], make_supervisor_headers())
    active = validate_success(resp)
    assert active["status"] == "ACTIVE"

    resp = api.set_clock({"current_utc": "2026-09-10T00:00:00Z"}, make_admin_headers())
    validate_success(resp)

    resp = api.get_promo_agreement(agreement["id"], make_supervisor_headers())
    expired = validate_success(resp)
    assert expired["status"] == "EXPIRED"


def test_settlement_dispute_cycle_returns_to_open_without_ledger_drift(api):
    """PRD §3.9: "The route's assigned rep (identity matched to rsr_id, else
    ERR_REP_NOT_ASSIGNED) may dispute a settlement from either OPEN or
    BALANCED, moving it to DISPUTED; a supervisor resolves the dispute,
    returning the settlement to OPEN."

    Design: Corner/state_machines/settlement_dispute_cycle_returns_to_open_without_ledger_drift
    """
    set_clock()
    rep = create_rep()
    store = create_store()
    product = create_product()
    route = create_route(rep["id"])
    create_assignment(route["id"], store["id"])
    day = create_route_day(route["id"])
    load_route_day(
        day["id"], [lot_entry(product["id"], "L-1", "2026-09-20", 30)], rep
    )
    start_route_day(day["id"], rep)
    order = create_order(day["id"], store["id"], [order_line(product["id"], 20)], rep)
    submit_order(order["id"], rep)
    deliver_order(order["id"], [deliver_line(product["id"], 20)], rep)
    settlement = create_settlement(day["id"])
    settlement = balance_settlement(settlement["id"], 10000)
    assert settlement["status"] == "BALANCED"

    resp = api.dispute_settlement(settlement["id"], make_rep_headers(rep["id"]))
    disputed = validate_success(resp)
    assert disputed["status"] == "DISPUTED"

    resp = api.resolve_settlement(settlement["id"], make_supervisor_headers())
    resolved = validate_success(resp)
    assert resolved["status"] == "OPEN"
    assert resolved["cash_collected_cents"] == 10000
    assert resolved["chronological_expected_cents"] == 10000
    assert resolved["gross_delivered_cents"] == 10000
