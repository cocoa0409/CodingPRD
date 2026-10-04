"""Validation corners: delivery-window boundary, stale-window boundary,
credit-cap boundary, existence-before-state ordering, stock boundary."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_assignment,
    create_order,
    create_product,
    create_rep,
    create_route,
    create_route_day,
    create_store,
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


def test_delivery_window_half_open_start_ok_end_rejected(api):
    """PRD §3.4: "the logical clock's minute-of-day must fall inside the
    store's half-open delivery window — at or after
    delivery_window_start_minute and strictly before
    delivery_window_end_minute, with a delivery at exactly the end minute
    rejected as ERR_DELIVERY_WINDOW_MISSED — and the order must carry at least
    one line (ERR_VALIDATION on an empty set)."

    Design: Corner/validations/delivery_window_half_open_start_ok_end_rejected
    """
    set_clock("2026-09-01T08:00:00Z")  # minute 480 — the inclusive start
    rep = create_rep()
    store_a = create_store(store_code="SA")
    store_b = create_store(store_code="SB")
    product = create_product()
    route = create_route(rep["id"])
    create_assignment(route["id"], store_a["id"])
    create_assignment(route["id"], store_b["id"], stop_sequence=2)
    day = create_route_day(route["id"])
    load_route_day(
        day["id"], [lot_entry(product["id"], "L-1", "2026-09-20", 20)], rep
    )
    start_route_day(day["id"], rep)
    order_a = create_order(day["id"], store_a["id"], [order_line(product["id"], 5)], rep)
    order_b = create_order(day["id"], store_b["id"], [order_line(product["id"], 5)], rep)

    # Submit at exactly minute 480: inside the half-open window.
    resp = api.submit_order(order_a["id"], make_rep_headers(rep["id"]))
    submitted = validate_success(resp)
    assert submitted["status"] == "SUBMITTED"

    # Move the clock to minute 720 — the exclusive end.
    resp = api.set_clock({"current_utc": "2026-09-01T12:00:00Z"}, make_admin_headers())
    validate_success(resp)

    resp = api.submit_order(order_b["id"], make_rep_headers(rep["id"]))
    validate_error(resp, ApiErrorId.ERR_DELIVERY_WINDOW_MISSED)

    order_b_after = validate_success(
        api.get_order(order_b["id"], make_supervisor_headers())
    )
    assert order_b_after["status"] == "DRAFT"


def test_stale_pull_window_boundary_five_eligible_six_not(api):
    """PRD §3.7: "The pull is stale-window eligible only when some OPEN lot of
    that product on the day has days-to-expiry of 5 or fewer — the exact
    complement of the freshness guarantee, so a lot at precisely 5 days is
    stale-eligible but undeliverable — and the absence of any such lot is
    ERR_PRODUCT_NOT_STALE_ELIGIBLE."

    Design: Corner/validations/stale_pull_window_boundary_five_eligible_six_not
    """
    set_clock()
    rep = create_rep()
    store = create_store()
    product = create_product()
    route = create_route(rep["id"])
    create_assignment(route["id"], store["id"], service_weekdays=["TUE", "WED"])

    # D1 (2026-09-01) with lot expiring 2026-09-07: days_to_expiry 6.
    day1 = create_route_day(route["id"], service_date="2026-09-01")
    load_route_day(
        day1["id"], [lot_entry(product["id"], "L-1", "2026-09-07", 10)], rep
    )
    start_route_day(day1["id"], rep)

    # D2 (2026-09-02) with lot expiring 2026-09-07: days_to_expiry 5.
    day2 = create_route_day(route["id"], service_date="2026-09-02")
    load_route_day(
        day2["id"], [lot_entry(product["id"], "L-2", "2026-09-07", 10)], rep
    )
    start_route_day(day2["id"], rep)

    resp = api.create_stale_credit(
        {
            "route_day_id": day1["id"],
            "store_id": store["id"],
            "product_id": product["id"],
            "qty_cases": 2,
        },
        make_rep_headers(rep["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_STALE_ELIGIBLE)

    resp = api.create_stale_credit(
        {
            "route_day_id": day2["id"],
            "store_id": store["id"],
            "product_id": product["id"],
            "qty_cases": 2,
        },
        make_rep_headers(rep["id"]),
    )
    credit = validate_success(resp, expected_status=201)
    assert credit["status"] == "PENDING_APPROVAL"
    assert credit["credit_cents"] == 1000  # 2 * 500 FULL_RETAIL


def test_credit_cap_equality_permitted_one_cent_over_rejected(api):
    """PRD §3.7: "the sum of credit_cents over the store's PENDING_APPROVAL and
    APPROVED credits for that route day, plus the new credit's amount, may not
    exceed the store's store_credit_cap_cents, with equality permitted; breach
    is ERR_STORE_CREDIT_CAP_EXCEEDED (HTTP 402)."

    Design: Corner/validations/credit_cap_equality_permitted_one_cent_over_rejected
    """
    set_clock()
    rep = create_rep()
    store = create_store(store_credit_cap_cents=5000)
    product = create_product(case_price_cents=250)
    route = create_route(rep["id"])
    create_assignment(route["id"], store["id"])
    day = create_route_day(route["id"])
    load_route_day(
        day["id"], [lot_entry(product["id"], "L-ST", "2026-09-06", 40)], rep
    )
    start_route_day(day["id"], rep)

    # First pending credit: 10 * 250 = 2500.
    resp = api.create_stale_credit(
        {
            "route_day_id": day["id"],
            "store_id": store["id"],
            "product_id": product["id"],
            "qty_cases": 10,
        },
        make_rep_headers(rep["id"]),
    )
    validate_success(resp, expected_status=201)

    # Second pending credit: 2500 + 2500 == 5000 — equality permitted.
    resp = api.create_stale_credit(
        {
            "route_day_id": day["id"],
            "store_id": store["id"],
            "product_id": product["id"],
            "qty_cases": 10,
        },
        make_rep_headers(rep["id"]),
    )
    credit2 = validate_success(resp, expected_status=201)
    assert credit2["status"] == "PENDING_APPROVAL"

    # Third: 5000 + 250 > 5000 — rejected 402.
    resp = api.create_stale_credit(
        {
            "route_day_id": day["id"],
            "store_id": store["id"],
            "product_id": product["id"],
            "qty_cases": 1,
        },
        make_rep_headers(rep["id"]),
    )
    assert resp.status_code == 402
    validate_error(resp, ApiErrorId.ERR_STORE_CREDIT_CAP_EXCEEDED)


def test_existence_checked_before_state_in_body_fk_order(api):
    """PRD §2.5: "The order is: (1) presence and recognizability of the auth
    headers; (2) role permission and ownership scope — rep owns the route day
    through the route's rsr_id, store managers are scoped to their own store;
    (3) existence of path identifiers, validated left to right, followed by
    foreign-key identifiers in the request body in the endpoint's declared
    input order, each miss producing its resource-specific ERR_..._NOT_FOUND
    (HTTP 404); (4) optimistic-concurrency version matching on the endpoints
    that take a version field; (5) state preconditions — the target resource in
    a valid from-state, the route ACTIVE, the store ACTIVE, the route day
    IN_PROGRESS or LOADED as the transition requires, the promo agreement
    ACTIVE; (6) segregation of duties on credit adjudication; (7) the freshness
    guarantee on delivery; (8) temporal window checks — the delivery window,
    promo-window overlap, assignment weekday conflicts, scheduled-stop
    coverage, agreement activation windows; (9) referential allocation checks —
    the product is on the truck that day, deliver lines reference products
    actually on the order; (10) capacity and stock sufficiency; and finally
    (11) the per-store stale-credit cap."
    PRD §5: "ERR_ROUTE_DAY_NOT_FOUND | 404 Not Found".

    Design: Corner/validations/existence_checked_before_state_in_body_fk_order
    """
    set_clock()
    rep = create_rep()
    store = create_store()
    product = create_product()
    resp = api.suspend_store(store["id"], make_supervisor_headers())
    validate_success(resp)

    # Unknown route_day_id (body FK, first in input order) AND suspended store:
    # the 404 existence error beats the 409 state error.
    resp = api.create_order(
        {
            "route_day_id": "00000000-0000-4000-8000-0000000000aa",
            "store_id": store["id"],
            "lines": [{"product_id": product["id"], "qty_ordered_cases": 1}],
        },
        make_rep_headers(rep["id"]),
    )
    err = validate_error(resp, ApiErrorId.ERR_ROUTE_DAY_NOT_FOUND)
    assert err["error_id"] != ApiErrorId.ERR_STORE_NOT_ACTIVE


def test_insufficient_stock_boundary_equal_ok_over_rejected(api):
    """PRD §3.5: "if the freshness-eligible remaining stock across those lots
    is short of the requested quantity, the delivery fails with
    ERR_INSUFFICIENT_TRUCK_STOCK."

    Design: Corner/validations/insufficient_stock_boundary_equal_ok_over_rejected
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

    order1 = create_order(
        day["id"], store["id"], [order_line(product["id"], 10)], rep
    )
    submit_order(order1["id"], rep)
    order2 = create_order(
        day["id"], store["id"], [order_line(product["id"], 11)], rep
    )
    submit_order(order2["id"], rep)

    # Exactly the remaining 10 cases: permitted.
    resp = api.deliver_order(
        order1["id"],
        {"lines": [{"product_id": product["id"], "qty_delivered_cases": 10}]},
        make_rep_headers(rep["id"]),
    )
    delivered = validate_success(resp)
    assert delivered["status"] == "DELIVERED"

    # 11 > 0 remaining: rejected.
    resp = api.deliver_order(
        order2["id"],
        {"lines": [{"product_id": product["id"], "qty_delivered_cases": 11}]},
        make_rep_headers(rep["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_TRUCK_STOCK)

    order2_after = validate_success(
        api.get_order(order2["id"], make_supervisor_headers())
    )
    assert order2_after["status"] == "SUBMITTED"
