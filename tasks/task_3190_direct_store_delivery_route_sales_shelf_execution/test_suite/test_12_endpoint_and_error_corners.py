"""Endpoint and error corners: settlement posting cascade, one-settlement-per-
day uniqueness, post precondition, empty-window snapshot, pending execution."""
from test_helpers import (
    ApiErrorId,
    api_client,
    balance_settlement,
    create_assignment,
    create_order,
    create_product,
    create_promo_agreement_payload,
    create_rep,
    create_route,
    create_route_day,
    create_settlement,
    create_store,
    deliver_line,
    deliver_order,
    get_lot_by_code,
    get_route_day,
    get_settlement,
    load_route_day,
    lot_entry,
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


def test_settle_post_cascades_day_settled_and_lots_closed(api):
    """PRD §3.9: "posting stamps posted_at with the logical clock, moves the
    settlement to POSTED (terminal), settles the route day itself (IN_PROGRESS
    → SETTLED), and closes the truck: every OPEN lot's returned_cases is set to
    its remaining_cases and its status to CLOSED, so all unsold, un-staled
    cases return to depot."

    Design: Corner/endpoints/settle_post_cascades_day_settled_and_lots_closed
    """
    set_clock()
    rep = create_rep()
    store = create_store()
    product = create_product()
    route = create_route(rep["id"])
    create_assignment(route["id"], store["id"])
    day = create_route_day(route["id"])
    load_route_day(
        day["id"], [lot_entry(product["id"], "L-1", "2026-09-20", 100)], rep
    )
    start_route_day(day["id"], rep)
    lot = get_lot_by_code(day["id"], "L-1")
    order = create_order(day["id"], store["id"], [order_line(product["id"], 40)], rep)
    submit_order(order["id"], rep)
    deliver_order(order["id"], [deliver_line(product["id"], 40)], rep)
    settlement = create_settlement(day["id"])
    balance_settlement(settlement["id"], 20000)

    resp = api.post_settlement(settlement["id"], make_supervisor_headers())
    posted = validate_success(resp)
    assert posted["status"] == "POSTED"
    assert posted["posted_at"] is not None

    assert get_route_day(day["id"])["status"] == "SETTLED"
    lot_after = get_lot_by_code(day["id"], "L-1")
    assert lot_after["status"] == "CLOSED"
    assert lot_after["returned_cases"] == 60
    assert lot_after["remaining_cases"] == 0


def test_second_settlement_for_same_day_rejected(api):
    """PRD §3.9: "When the truck returns, a RouteSupervisor opens the route
    day's settlement — at most one per route day, with a second attempt
    rejected as ERR_SETTLEMENT_ALREADY_EXISTS — naming the route_day_id of an
    IN_PROGRESS day."

    Design: Corner/endpoints/second_settlement_for_same_day_rejected
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
    create_settlement(day["id"])

    resp = api.create_settlement(
        {"route_day_id": day["id"]}, make_supervisor_headers()
    )
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_ALREADY_EXISTS)

    settlements, meta = validate_paginated(
        api.list_settlements(
            make_supervisor_headers(), params={"route_day_id": day["id"]}
        )
    )
    assert len(settlements) == 1


def test_settlement_post_blocked_while_orders_submitted(api):
    """PRD §3.9: "A BALANCED settlement may be posted only while no order of
    the route day remains SUBMITTED (ERR_UNRESOLVED_ORDERS otherwise); posting
    stamps posted_at with the logical clock, moves the settlement to POSTED
    (terminal), settles the route day itself (IN_PROGRESS → SETTLED), and
    closes the truck: every OPEN lot's returned_cases is set to its
    remaining_cases and its status to CLOSED, so all unsold, un-staled cases
    return to depot."

    Design: Corner/endpoints/settlement_post_blocked_while_orders_submitted
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
    settlement = create_settlement(day["id"])
    settlement = balance_settlement(settlement["id"], 0)
    assert settlement["status"] == "BALANCED"

    resp = api.post_settlement(settlement["id"], make_supervisor_headers())
    validate_error(resp, ApiErrorId.ERR_UNRESOLVED_ORDERS)

    assert get_settlement(settlement["id"])["status"] == "BALANCED"
    assert get_route_day(day["id"])["status"] == "IN_PROGRESS"


def test_snapshot_without_delivered_orders_returns_no_delivered_orders(api):
    """PRD §3.10: "orders_count is the count of those delivered orders; if the
    window contains none, the request fails with ERR_NO_DELIVERED_ORDERS."

    Design: Corner/errors/snapshot_without_delivered_orders_returns_no_delivered_orders
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

    resp = api.create_service_level_snapshot(
        route["id"],
        {"period_start": "2026-09-01", "period_end": "2026-09-02"},
        make_supervisor_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_NO_DELIVERED_ORDERS)


def test_pending_promo_execution_blocks_second_submission(api):
    """PRD §3.8: "Only one pending execution may exist per agreement: a second
    submission while another is still SUBMITTED fails with
    ERR_PENDING_EXECUTION_EXISTS."

    Design: Corner/errors/pending_promo_execution_blocks_second_submission
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

    resp = api.create_promo_agreement(
        create_promo_agreement_payload(store["id"], product["id"]),
        make_supervisor_headers(),
    )
    agreement = validate_success(resp, expected_status=201)
    resp = api.activate_promo_agreement(agreement["id"], make_supervisor_headers())
    active = validate_success(resp)

    resp = api.create_promo_execution(
        {
            "agreement_id": agreement["id"],
            "route_day_id": day["id"],
            "photo_url": "https://photos/one.jpg",
            "expected_promo_agreement_version": active["version"],
        },
        make_rep_headers(rep["id"]),
    )
    execution1 = validate_success(resp, expected_status=201)

    # The first submission bumped the agreement version (PRD §3.8); fetch the
    # current version so the OCC guard passes and the pending-execution rule is
    # what rejects the second submission.
    agreement_after = validate_success(
        api.get_promo_agreement(agreement["id"], make_supervisor_headers())
    )

    resp = api.create_promo_execution(
        {
            "agreement_id": agreement["id"],
            "route_day_id": day["id"],
            "photo_url": "https://photos/two.jpg",
            "expected_promo_agreement_version": agreement_after["version"],
        },
        make_rep_headers(rep["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PENDING_EXECUTION_EXISTS)

    executions, meta = validate_paginated(
        api.list_promo_executions(
            make_supervisor_headers(), params={"agreement_id": agreement["id"]}
        )
    )
    assert len(executions) == 1
    assert executions[0]["id"] == execution1["id"]


def test_no_scheduled_stop_when_weekday_not_covered(api):
    """PRD §3.2: "the service date's weekday must be covered by at least one
    ACTIVE assignment of the route, failing with ERR_NO_SCHEDULED_STOP
    otherwise."

    Design: Corner/errors/no_scheduled_stop_when_weekday_not_covered
    """
    rep = create_rep()
    store = create_store()
    route = create_route(rep["id"])
    create_assignment(route["id"], store["id"], service_weekdays=["TUE"])

    # 2026-09-02 is a WED; the only assignment covers TUE.
    resp = api.create_route_day(
        {"route_id": route["id"], "service_date": "2026-09-02"},
        make_supervisor_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_NO_SCHEDULED_STOP)

    days, meta = validate_paginated(
        api.list_route_days(make_supervisor_headers(), params={"route_id": route["id"]})
    )
    assert len(days) == 0
