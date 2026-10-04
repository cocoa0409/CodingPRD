"""Corner design — section: entities."""
from test_helpers import (
    ADMIN,
    OPS,
    ApiErrorId,
    create_customer_payload,
    create_order,
    create_store,
    cust_headers,
    get_success_data,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_ORDER_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def test_store_create_applies_defaults_and_system_fields(api):
    """PRD §3.1: "an optional `low_stock_threshold` — the number of units at
    or above which an article signals healthy stock — which defaults to 5 and
    must be at least 1."
    PRD §2.4: "`version` is an integer that starts at 1 when the resource is
    created and increments by exactly 1 on every mutation"

    Design: Corner/entities/store_create_applies_defaults_and_system_fields
    """
    set_clock()
    resp = api.create_store({"name": "Renton", "code": "ST-DEF-1"}, ADMIN)
    store = validate_success(resp, expected_status=201)
    assert resp.json()["response_type"] == "object"
    assert store["low_stock_threshold"] == 5
    assert store["version"] == 1
    assert store["id"]
    assert store["created_at"]
    assert store["updated_at"]
    meta = resp.json()["meta"]
    assert meta["api_request_id"]
    assert meta["api_request_timestamp"]


def test_article_create_computed_carton_fields_and_roundtrip(api):
    """PRD §3.1: "The article's `carton_count` is recomputed every time a
    carton is registered, and `is_multi_carton` is true exactly when that
    count is greater than 1; until any carton is registered the count is 0."

    Design: Corner/entities/article_create_computed_carton_fields_and_roundtrip
    """
    set_clock()
    created = validate_success(api.create_article(
        {"article_number": "904.111.22", "name": "BILLY", "category": "FURNITURE",
         "pick_policy": "SELF_SERVE", "price_cents": 8900}, ADMIN),
        expected_status=201)
    assert created["carton_count"] == 0
    assert created["is_multi_carton"] is False
    assert created["family_price_cents"] is None
    assert created["lowest_price_365d_cents"] is None

    validate_success(api.create_carton(
        created["id"],
        {"carton_seq": 1, "aisle": "12", "bin": "03", "weight_kg": 18, "volume_m3": 0.09},
        ADMIN), expected_status=201)
    validate_success(api.create_carton(
        created["id"],
        {"carton_seq": 2, "aisle": "12", "bin": "04", "weight_kg": 14, "volume_m3": 0.07},
        ADMIN), expected_status=201)

    fetched = get_success_data(api.get_article(created["id"], OPS))
    assert fetched["carton_count"] == 2
    assert fetched["is_multi_carton"] is True
    assert fetched["article_number"] == "904.111.22"
    assert fetched["price_cents"] == 8900


def test_customer_create_defaults_not_member_zero_points(api):
    """PRD §3.2: "New customers start with `member_status` of `NONE`, a null
    `member_since`, and a `points_balance` of 0."

    Design: Corner/entities/customer_create_defaults_not_member_zero_points
    """
    set_clock()
    resp = api.create_customer(create_customer_payload(), OPS)
    customer = validate_success(resp, expected_status=201)
    assert customer["member_status"] == "NONE"
    assert customer["member_since"] is None
    assert customer["points_balance"] == 0


def test_enroll_flips_member_status_and_stamps_member_since(api):
    """PRD §3.2: "A `StoreOps` operator can enroll a customer in the family
    program, which flips `member_status` to `ACTIVE` and stamps `member_since`
    with the current logical time; enrollment is the only path into
    membership."
    PRD §2.6: "Before any client call has been made, the clock reads exactly
    2026-09-01T00:00:00Z, and it never falls back to wall-clock time
    thereafter."

    Design: Corner/entities/enroll_flips_member_status_and_stamps_member_since
    """
    from datetime import datetime, timezone
    set_clock("2026-09-01T00:00:00Z")
    customer = get_success_data(api.create_customer(create_customer_payload(), OPS))

    enrolled = validate_success(api.enroll_customer(customer["id"], OPS))
    assert enrolled["member_status"] == "ACTIVE"
    stamped = datetime.fromisoformat(enrolled["member_since"].replace("Z", "+00:00"))
    assert stamped == datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc), (
        "member_since is stamped with the current logical time"
    )


def test_order_get_with_unknown_id_returns_order_not_found(api):
    """PRD §2.8: "Every resource class has its own not-found error —
    `ERR_CARTON_NOT_FOUND`, `ERR_BIN_STOCK_NOT_FOUND`,
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_ORDER_LINE_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`,
    `ERR_SLOT_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_JOB_NOT_FOUND`,
    `ERR_CLAIM_NOT_FOUND`, and `ERR_STANDARD_NOT_FOUND` alongside those above
    — and all of them carry HTTP 404."

    Design: Corner/entities/order_get_with_unknown_id_returns_order_not_found
    """
    set_clock()
    resp = api.get_order(UNKNOWN_ORDER_ID, OPS)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND)
    assert resp.status_code == 404


def test_orders_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "List endpoints accept two query parameters: `limit`, the
    page size, defaulting to 10 with a minimum of 1 and a maximum of 100, and
    `offset`, the number of records to skip, defaulting to 0. Both are
    optional on every list endpoint. Every list response reports `limit`,
    `offset`, `total_count`, and `has_more` inside `meta`."
    PRD §3.3: "Orders can be listed with optional `customer_id`, `store_id`,
    and `status` filters"

    Design: Corner/entities/orders_list_paginates_with_total_count_and_has_more
    """
    set_clock()
    store = create_store()
    customer = get_success_data(api.create_customer(create_customer_payload(), OPS))
    for _ in range(3):
        create_order(customer, store["id"])

    page1, meta1 = validate_paginated(
        api.list_orders(OPS, params={"customer_id": customer["id"], "limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_orders(OPS, params={"customer_id": customer["id"], "limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    all_rows, meta_default = validate_paginated(
        api.list_orders(OPS, params={"customer_id": customer["id"]}))
    assert len(all_rows) == 3
    assert meta_default["limit"] == 10
    assert meta_default["offset"] == 0

    drafts, _ = validate_paginated(
        api.list_orders(OPS, params={"customer_id": customer["id"], "status": "DRAFT"}))
    assert len(drafts) == 3
    paid, _ = validate_paginated(
        api.list_orders(OPS, params={"customer_id": customer["id"], "status": "PAID"}))
    assert len(paid) == 0
