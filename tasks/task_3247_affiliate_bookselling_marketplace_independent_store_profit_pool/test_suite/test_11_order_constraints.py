"""Order-level business constraints: attribution XOR, uniqueness, consistency."""
from test_helpers import (
    ADMIN,
    FINANCE,
    ApiErrorId,
    create_active_partner,
    create_active_store,
    create_book,
    create_order,
    create_publisher,
    create_store,
    get_success_data,
    make_customer_headers,
    place_order,
    set_clock,
    setup_catalog_and_store,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_attribution_xor_both_set_and_neither_set(api):
    """PRD §2.8: "Every sale is attributable to exactly one affiliate: either an
    independent store or an author/publication/influencer partner, never both
    and never neither. Orders carrying both `attributed_store_id` and
    `attributed_partner_id`, or neither, are rejected with
    `ERR_ATTRIBUTION_AMBIGUOUS` (HTTP 422)."

    Design: Corner/validations/attribution_xor_both_set_and_neither_set
    """
    set_clock("2026-09-01T00:00:00Z")
    _publisher, book, store = setup_catalog_and_store()
    partner = create_active_partner(
        display_name="Terminal Author", partner_kind="AUTHOR", commission_pct=0.10
    )
    cust = make_customer_headers("cust-c3")

    resp = api.create_order(
        {
            "customer_id": "cust-c3",
            "attributed_store_id": store["id"],
            "attributed_partner_id": partner["id"],
            "lines": [{"book_id": book["id"], "quantity": 1}],
        },
        cust,
    )
    validate_error(resp, ApiErrorId.ERR_ATTRIBUTION_AMBIGUOUS, expected_status=422)

    resp = api.create_order(
        {
            "customer_id": "cust-c3",
            "lines": [{"book_id": book["id"], "quantity": 1}],
        },
        cust,
    )
    validate_error(resp, ApiErrorId.ERR_ATTRIBUTION_AMBIGUOUS, expected_status=422)

    resp = api.list_orders(FINANCE, {"customer_id": "cust-c3"})
    orders, _ = validate_paginated(resp)
    assert orders == []


def test_uniqueness_conflicts_isbn_slug(api):
    """PRD §3.1: "Books enter the catalog under a publisher via a payload
    carrying `publisher_id`, an `isbn` unique across the entire catalog, a
    display `title`"
    PRD §3.2: "An independent bookstore joins the marketplace when a
    `PlatformAdmin` onboards it with a `shop_name`, a `slug` that must be unique
    after lowercase normalization"
    PRD §2.11: "then body shape — required fields, types, enum membership,
    uniqueness, list positions, and index ranges — as `ERR_VALIDATION`
    (HTTP 400)."

    Design: Corner/validations/uniqueness_conflicts_isbn_slug
    """
    set_clock("2026-09-01T00:00:00Z")
    pub = create_publisher(
        name="Corner Press",
        discount_pct=0.45,
        returns_allowed=True,
        return_window_days=60,
        return_credit_pct=1.0,
    )
    create_book(pub["id"], isbn="9780000001040", title="First", list_price_cents=1000)
    create_store(shop_name="Unique Books", slug="unique-books", commission_pct=0.20)

    resp = api.create_book(
        {
            "publisher_id": pub["id"],
            "isbn": "9780000001040",
            "title": "Second",
            "format": "PRINT",
            "list_price_cents": 2000,
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)

    resp = api.create_store(
        {"shop_name": "Other Shop", "slug": "Unique-Books", "commission_pct": 0.20},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_immediate_consistency_on_action_response(api):
    """PRD §3.4: "A successful placement moves the order to `PLACED` and, in the
    same request, flips `payment_status` from `PENDING` to `PAID` — payment
    capture is atomic with placement."
    PRD §3.4: "for `PRINT`, the line's net is its `line_total_cents` minus its
    `wholesale_unit_cents` times quantity, and the line commission is that net
    multiplied by the affiliate's `commission_pct`, floored."
    PRD §3.4: "its `platform_margin_cents` is, for print lines, each line's
    total minus its wholesale cost minus its commission, and for digital lines,
    each line's total minus the platform keep minus its commission, all summed."

    Design: Corner/cross_cutting/immediate_consistency_on_action_response
    """
    set_clock("2026-09-01T00:00:00Z")
    publisher, book, store = setup_catalog_and_store(
        publisher_overrides={
            "name": "Corner Press",
            "discount_pct": 0.45,
            "returns_allowed": True,
            "return_window_days": 60,
            "return_credit_pct": 1.0,
        },
        store_overrides={"commission_pct": 0.30, "payout_threshold_cents": 20000},
    )
    order = create_order("cust-c1", book["id"], attributed_store_id=store["id"])
    placed = validate_success(
        api.order_action(
            order["id"], {"action": "place"}, make_customer_headers("cust-c1")
        ),
        expected_status=200,
    )
    # The action response itself carries the updated state — no re-read needed.
    assert placed["payment_status"] == "PAID"
    assert placed["fulfillment_status"] == "PLACED"
    assert placed["gross_cents"] == 100000
    assert placed["wholesale_cost_cents"] == 55000
    assert placed["commission_cents"] == 13500  # floor((100000-55000) * 0.30)
    assert placed["platform_margin_cents"] == 31500  # 100000 - 55000 - 13500
