"""RBAC: authentication, authorization, and ownership boundaries."""
from test_helpers import (
    ADMIN,
    FINANCE,
    SERVICE,
    WHOLESALER,
    ApiErrorId,
    create_active_partner,
    create_active_store,
    create_book,
    create_delivered_order,
    create_list_for_store,
    create_order,
    create_partner,
    create_placed_order,
    create_publisher,
    create_store,
    get_success_data,
    make_customer_headers,
    make_partner_headers,
    make_store_manager_headers,
    open_return,
    place_order,
    set_clock,
    setup_catalog_and_store,
    setup_delivered_order_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "A request whose `X-User-Role` header is missing or does not
    name one of the declared roles is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."
    PRD §2.11: "Authentication comes first (`ERR_UNAUTHENTICATED`), then role
    authorization (`ERR_UNAUTHORIZED`), then ownership
    (`ERR_FORBIDDEN_OWNER_MISMATCH`). Path resources are resolved next
    (`ERR_NOT_FOUND`)"

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api._request(
        "GET",
        "/bookshop/stores/00000000-0000-0000-0000-000000000000",
        headers={"X-User-ID": "test-anon"},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_partner_and_customer_cannot_write_admin_resources(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the
    endpoint — or, on lifecycle action endpoints, not mapped to the specific
    `action` being attempted — is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "A `PlatformAdmin` onboards stores and partners, manages the
    publisher and book catalog, schedules promotions, drives every store and
    partner lifecycle action, and controls the logical clock."

    Design: Corner/rbac/partner_and_customer_cannot_write_admin_resources
    """
    set_clock("2026-09-01T00:00:00Z")
    partner = create_partner(
        display_name="Terminal Author", partner_kind="AUTHOR", commission_pct=0.10
    )
    create_store(
        shop_name="State Books",
        slug="state-books",
        commission_pct=0.30,
        payout_threshold_cents=20000,
    )

    resp = api.create_store(
        {"shop_name": "Illegal", "slug": "illegal", "commission_pct": 0.20},
        make_partner_headers(partner["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    resp = api.create_publisher(
        {
            "name": "Illegal Press",
            "discount_pct": 0.40,
            "returns_allowed": False,
            "return_window_days": 0,
            "return_credit_pct": 0.0,
        },
        make_customer_headers("cust-c9"),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_store_manager_cannot_touch_other_stores_list(api):
    """PRD §2.1: "When `X-User-Role` is `StoreManager`, `X-User-ID` is the `id`
    of the acting `AffiliateStore`; ownership checks on any resource that
    references an `AffiliateStore` — most notably a list's `owner_store_id` —
    compare the resource's foreign-key field to `X-User-ID`. A mismatch is
    rejected with `ERR_FORBIDDEN_OWNER_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/store_manager_cannot_touch_other_stores_list
    """
    set_clock("2026-09-01T00:00:00Z")
    _publisher, book, store_a = setup_catalog_and_store()
    store_b = create_active_store(
        shop_name="Other Books", slug="other-books", commission_pct=0.20
    )
    list_b = create_list_for_store(store_b["id"], book_id=book["id"], title="B Picks")

    # StoreManager of store A attempts to publish store B's list.
    resp = api.list_action(
        list_b["id"],
        {"action": "publish"},
        make_store_manager_headers(store_a["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNER_MISMATCH, expected_status=403)


def test_customer_cannot_open_return_on_another_customers_order(api):
    """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is an opaque
    customer handle, and on any endpoint acting on an order, a return of an
    order, or a ticket of an order, the server requires `X-User-ID` to equal the
    order's `customer_id`; a mismatch yields `ERR_FORBIDDEN_OWNER_MISMATCH`."

    Design: Corner/rbac/customer_cannot_open_return_on_another_customers_order
    """
    set_clock("2026-09-01T00:00:00Z")
    _publisher, _book, _store, order = setup_delivered_order_scenario(
        customer_id="cust-c1",
        store_overrides={"commission_pct": 0.30, "payout_threshold_cents": 20000},
    )
    resp = api.create_return(
        order["id"],
        {"line_index": 0, "quantity": 1, "reason_code": "DAMAGED"},
        make_customer_headers("cust-x"),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNER_MISMATCH, expected_status=403)

    resp = api.list_order_returns(order["id"], FINANCE)
    returns, _ = validate_paginated(resp)
    assert returns == []


def test_order_dispatch_by_non_wholesaler_roles_rejected(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the
    endpoint — or, on lifecycle action endpoints, not mapped to the specific
    `action` being attempted — is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "`WholesalerOps` dispatches orders to the wholesaler, emits ship
    and deliver fulfillment events, and logs physical receipt of returned
    stock."

    Design: Corner/endpoints/order_dispatch_by_non_wholesaler_roles_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    _publisher, book, store = setup_catalog_and_store()
    order = create_placed_order("cust-c1", book["id"], attributed_store_id=store["id"])

    resp = api.order_action(
        order["id"], {"action": "dispatch"}, make_store_manager_headers(store["id"])
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)
    resp = api.order_action(
        order["id"], {"action": "dispatch"}, make_customer_headers("cust-c1")
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    order_now = get_success_data(api.get_order(order["id"], FINANCE))
    assert order_now["fulfillment_status"] == "PLACED"


def test_return_receive_and_credit_role_map(api):
    """PRD §3.5: "For print, `WholesalerOps` logs physical receipt, moving the
    request to `RECEIVED`; digital formats take the same step in the same call,
    there being nothing physical to wait for."
    PRD §3.5: "Crediting is a `FinanceOps` act and the point where the money
    moves."
    PRD §2.1: "A request whose role is recognized but not permitted for the
    endpoint — or, on lifecycle action endpoints, not mapped to the specific
    `action` being attempted — is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/endpoints/return_receive_and_credit_role_map
    """
    set_clock("2026-09-01T00:00:00Z")
    _publisher, _book, _store, order = setup_delivered_order_scenario(
        customer_id="cust-c1",
        store_overrides={"commission_pct": 0.30, "payout_threshold_cents": 20000},
    )
    ret = open_return(
        order["id"], "cust-c1", line_index=0, quantity=1, reason_code="DAMAGED"
    )
    get_success_data(api.return_action(ret["id"], {"action": "approve"}, SERVICE))

    resp = api.return_action(ret["id"], {"action": "receive"}, FINANCE)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    received = validate_success(
        api.return_action(ret["id"], {"action": "receive"}, WHOLESALER),
        expected_status=200,
    )
    assert received["status"] == "RECEIVED"

    resp = api.return_action(ret["id"], {"action": "credit"}, WHOLESALER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_payout_actions_by_non_finance_roles_rejected(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the
    endpoint — or, on lifecycle action endpoints, not mapped to the specific
    `action` being attempted — is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "The `FinanceOps` role runs money movement. When `X-User-Role` is
    `FinanceOps`, `X-User-ID` is an opaque operator identifier not compared to
    any entity's `id`. `FinanceOps` owns the profit pool lifecycle, the payout
    lifecycle, and the crediting of returns."

    Design: Corner/endpoints/payout_actions_by_non_finance_roles_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    _publisher, book, store = setup_catalog_and_store()
    order = create_placed_order("cust-c1", book["id"], attributed_store_id=store["id"])
    payouts, _ = validate_paginated(
        api.list_payouts(FINANCE, {"affiliate_store_id": store["id"]})
    )
    assert len(payouts) == 1
    payout_id = payouts[0]["id"]

    resp = api.payout_action(payout_id, {"action": "process"}, SERVICE)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)
    resp = api.payout_action(payout_id, {"action": "process"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    payout_now = get_success_data(api.get_payout(payout_id, FINANCE))
    assert payout_now["status"] == "PENDING"
