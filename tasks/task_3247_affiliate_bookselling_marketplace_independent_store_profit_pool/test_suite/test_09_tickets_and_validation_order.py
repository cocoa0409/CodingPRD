"""Service tickets and the place-time validation ordering."""
from test_helpers import (
    ADMIN,
    FINANCE,
    SERVICE,
    WHOLESALER,
    ApiErrorId,
    create_order,
    create_placed_order,
    create_ticket_for_order,
    get_success_data,
    make_customer_headers,
    place_order,
    resolve_ticket,
    set_clock,
    setup_catalog_and_store,
    store_ledger,
    validate_error,
    validate_success,
)


def test_ticket_reopen_window_boundary(api):
    """PRD §3.5: "the customer may reopen a `RESOLVED` ticket within fourteen
    days of `resolved_at` measured against the logical clock, and a reopen
    attempted after that window fails with `ERR_WINDOW_NOT_SATISFIED`
    (HTTP 422); a reopened ticket returns to `IN_REVIEW` through a fresh
    assignment."

    Design: Corner/state_machines/ticket_reopen_window_boundary
    """
    set_clock("2026-09-01T00:00:00Z")
    _publisher, book, store = setup_catalog_and_store(
        store_overrides={"commission_pct": 0.30, "payout_threshold_cents": 20000}
    )
    order = create_placed_order("cust-c1", book["id"], attributed_store_id=store["id"])

    ticket_ok = create_ticket_for_order(order["id"], "cust-c1", issue_kind="BILLING")
    ticket_late = create_ticket_for_order(
        order["id"], "cust-c1", issue_kind="LATE_SHIPMENT"
    )
    resolve_ticket(ticket_ok["id"], "credited")
    resolve_ticket(ticket_late["id"], "apologized")

    cust = make_customer_headers("cust-c1")
    set_clock("2026-09-15T00:00:00Z")  # exactly resolved_at + 14 days
    resp = api.ticket_action(ticket_ok["id"], {"action": "reopen"}, cust)
    reopened = validate_success(resp, expected_status=200)
    assert reopened["status"] == "REOPENED"

    set_clock("2026-09-16T00:00:00Z")  # past the window
    resp = api.ticket_action(ticket_late["id"], {"action": "reopen"}, cust)
    validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_SATISFIED, expected_status=422)


def test_state_vs_business_safety_on_order_place(api):
    """PRD §2.11: "Only then are state-machine preconditions checked
    (`ERR_INVALID_STATE`, HTTP 409), followed by the pool-approval OCC check
    (`ERR_STALE_VERSION`). Business safety rules come after state:
    affiliate-active checks (`ERR_AFFILIATE_NOT_ACTIVE`, HTTP 422) and book
    availability (`ERR_BOOK_UNAVAILABLE`, HTTP 422)."
    PRD §3.4: "the attributed affiliate — store or partner — must be `ACTIVE`,
    or the placement is rejected with `ERR_AFFILIATE_NOT_ACTIVE` (HTTP 422)"

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_order_place
    """
    set_clock("2026-09-01T00:00:00Z")
    _publisher, book, store = setup_catalog_and_store(
        store_overrides={"commission_pct": 0.30, "payout_threshold_cents": 20000}
    )
    order = create_placed_order("cust-7", book["id"], attributed_store_id=store["id"])
    cust = make_customer_headers("cust-7")
    get_success_data(api.order_action(order["id"], {"action": "cancel"}, cust))
    get_success_data(api.store_action(store["id"], {"action": "suspend"}, ADMIN))

    # Both violations hold (order CANCELLED; store SUSPENDED): the earlier
    # state-machine check must mask the affiliate gate.
    resp = api.order_action(order["id"], {"action": "place"}, cust)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    entries = store_ledger(store["id"])
    assert len(entries) == 2, "only the original accrual + reversal pair exist"


def test_place_on_shipped_order_is_state_violation(api):
    """PRD §3.4: "An order's fulfillment lifecycle runs `DRAFT` → `PLACED` →
    `SENT_TO_WHOLESALER` → `SHIPPED` → `DELIVERED`, with `CANCELLED` as the
    terminal alternative reachable from `DRAFT` or `PLACED`"
    PRD §2.11: "Only then are state-machine preconditions checked
    (`ERR_INVALID_STATE`, HTTP 409), followed by the pool-approval OCC check
    (`ERR_STALE_VERSION`). Business safety rules come after state:
    affiliate-active checks (`ERR_AFFILIATE_NOT_ACTIVE`, HTTP 422) and book
    availability (`ERR_BOOK_UNAVAILABLE`, HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_order_place
    """
    set_clock("2026-09-01T00:00:00Z")
    _publisher, book, store = setup_catalog_and_store(
        store_overrides={"commission_pct": 0.30, "payout_threshold_cents": 20000}
    )
    order = create_placed_order("cust-7", book["id"], attributed_store_id=store["id"])
    get_success_data(api.order_action(order["id"], {"action": "dispatch"}, WHOLESALER))
    get_success_data(api.order_action(order["id"], {"action": "ship"}, WHOLESALER))

    cust = make_customer_headers("cust-7")
    resp = api.order_action(order["id"], {"action": "place"}, cust)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    order_now = get_success_data(api.get_order(order["id"], FINANCE))
    assert order_now["fulfillment_status"] == "SHIPPED"
