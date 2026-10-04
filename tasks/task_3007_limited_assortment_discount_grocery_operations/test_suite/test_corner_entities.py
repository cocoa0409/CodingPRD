"""Entity surface: creation defaults, stored-field reads, pagination, references."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CATEGORY_MANAGER_HEADERS,
    OPERATIONS_ADMIN_HEADERS,
    assert_cart_coin_event,
    fixtures,
    make_store_manager_headers,
)
from test_helpers.factories import cart_coin_event_payload, product_payload


def test_category_creation_defaults_applied(api):
    """Omitting sku_cap yields 2, active_sku_count 0, status OPEN, version 1.

    PRD §3.1: "It defaults to 2 when not supplied and must be at least 1 and at most 5 — the limited-assortment model tolerates narrow variation between categories, never breadth. A newly created category starts in `OPEN` status with an `active_sku_count` of 0."
    PRD §2.4: "The `version` field is a system-managed integer that increments by exactly 1 on every mutation and underpins optimistic concurrency control."

    Design: Corner/entities/category_creation_defaults_applied
    """
    created = validate_success(
        api.create_category({"code": "DAIRY", "name": "Dairy"}, CATEGORY_MANAGER_HEADERS),
        201,
    )
    assert created["sku_cap"] == 2
    assert created["active_sku_count"] == 0
    assert created["status"] == "OPEN"
    assert created["version"] == 1


def test_store_retrieval_returns_stored_fields_and_zero_ledgers(api):
    """GET echoes the stored fields; computed ledger fields initialize to zero.

    PRD §3.6: "The store's `coins_outstanding` — coins currently held by customers in carts — is derived by replaying the store's events in `created_at` ascending order (timestamps carry three fractional digits, and `id` is never used for ordering): an `INSERT` adds its `coin_count`, a `RETURN` and a `CORRAL_COLLECT` each subtract theirs, and an `AUDIT_ADJUST` adds its signed `coin_count`."
    PRD §3.6: "The store's `coin_liability_cents` is the outstanding count multiplied by 25 — the quarter deposit per cart."

    Design: Corner/entities/entity_retrieval_returns_stored_fields
    """
    store = fixtures.create_store(api, name="Store One")
    read = validate_success(api.get_store(store["id"], OPERATIONS_ADMIN_HEADERS))
    assert read["name"] == "Store One"
    assert read["coins_outstanding"] == 0
    assert read["coin_liability_cents"] == 0
    assert read["refund_liability_cents"] == 0
    assert read["refund_paid_cents"] == 0
    assert read["finds_sell_through_pct"] == 0.0


def test_list_pagination_envelope_fields(api):
    """limit=1 over two categories yields one row, total_count 2, has_more true.

    PRD §2.3: "The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/list_pagination_envelope_fields
    """
    fixtures.create_category(api, code="C1")
    fixtures.create_category(api, code="C2")

    response = api.list_categories(CATEGORY_MANAGER_HEADERS, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(response)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    body = response.json()
    assert body["response_type"] == "array"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_get_missing_category_returns_not_found(api):
    """A random UUID yields 404 ERR_NOT_FOUND in the error envelope.

    PRD §2.8: "4. Existence: every path identifier and body foreign-key reference resolves to an existing resource (`ERR_NOT_FOUND`)."

    Design: Corner/entities/get_missing_category_returns_not_found
    """
    response = api.get_category(NON_EXISTENT_UUID, CATEGORY_MANAGER_HEADERS)
    error = validate_error(response, "ERR_NOT_FOUND", 404)
    assert response.json()["response_type"] == "error"
    assert error["error_id"] == "ERR_NOT_FOUND"


def test_product_missing_required_sku_code_rejected(api):
    """POST /v1/products without sku_code yields 400 ERR_VALIDATION.

    PRD §2.8: "3. Request shape: required fields present, types correct, enum members valid (`ERR_VALIDATION`)."
    PRD §3.2: "A `CategoryManager` creates a product by supplying its `category_id`, a globally unique `sku_code`, a display `name`, its `kind`, whether it ships in `shelf_ready_packaging`, its `barcode_count`, a target `unit_cost_cents`, and a shelf `price_cents`."

    Design: Corner/entities/product_missing_required_field_rejected
    """
    category = fixtures.create_category(api)
    payload = product_payload(category["id"])
    del payload["sku_code"]
    response = api.create_product(payload, CATEGORY_MANAGER_HEADERS)
    validate_error(response, "ERR_VALIDATION", 400)


def test_product_invalid_kind_enum_rejected(api):
    """kind 'MEGA' is not in {CORE, FINDS}: 400 ERR_VALIDATION.

    PRD §2.8: "3. Request shape: required fields present, types correct, enum members valid (`ERR_VALIDATION`)."
    PRD §3.2: "The `kind` field splits the assortment in two. `CORE` products are permanent line items, fully subject to the owning category's `sku_cap`. `FINDS` products are weekly one-time promotional buys: exempt from the cap, but held to a stricter merchandising standard — a `FINDS` product created without `shelf_ready_packaging` set to true is rejected with `ERR_SHELF_READY_REQUIRED`, because pallet-display merchandising admits no decanting labor."

    Design: Corner/entities/product_invalid_kind_enum_rejected
    """
    category = fixtures.create_category(api)
    payload = product_payload(category["id"], kind="MEGA")
    response = api.create_product(payload, CATEGORY_MANAGER_HEADERS)
    validate_error(response, "ERR_VALIDATION", 400)


def test_cart_coin_event_is_append_only_without_version(api):
    """A cart coin event carries id and created_at only — no version, no updated_at.

    PRD §2.4: "The one exception is the `CartCoinEvent`, which is an append-only ledger entry: it carries `id` and `created_at` only, and has neither `updated_at` nor `version`."

    Design: Corner/entities/cart_coin_event_immutable_no_version
    """
    store = fixtures.create_store(api)
    event = validate_success(
        api.create_cart_coin_event(
            store["id"],
            cart_coin_event_payload("INSERT", 3),
            make_store_manager_headers(store["id"]),
        ),
        201,
    )
    assert_cart_coin_event(event)


def test_product_created_proposed_with_null_suppliers(api):
    """Products are born PROPOSED with both supplier fields null.

    PRD §3.2: "Every product is born in `PROPOSED` status: creation alone never places an item on the shelf."
    PRD §3.2: "A product's sourcing is recorded in `primary_supplier_id` and `secondary_supplier_id`. Both are null at creation and are populated only by a tender award; the secondary must always be a different supplier from the primary, so the supply base is genuinely dual-sourced."

    Design: Corner/entities/product_computed_supplier_fields_ignore_input
    """
    category = fixtures.create_category(api)
    product = fixtures.create_product(api, category["id"])
    assert product["status"] == "PROPOSED"
    assert product["primary_supplier_id"] is None
    assert product["secondary_supplier_id"] is None


def test_employee_requires_existing_store_parent(api):
    """Hiring under a nonexistent store id fails on the store: 404 ERR_NOT_FOUND.

    PRD §2.9: "Endpoints whose paths nest one resource beneath another validate identifiers strictly left to right. The first identifier in the path that fails to resolve to an existing resource produces the `ERR_NOT_FOUND` response, and no later identifier is examined. A request addressing a bid under a tender that does not exist fails on the tender; a request addressing an employee under a store that does not exist fails on the store."

    Design: Corner/entities/employee_requires_existing_store_parent
    """
    response = api.create_employee(
        NON_EXISTENT_UUID,
        {"name": "Ghost", "role": "CASHIER"},
        make_store_manager_headers(NON_EXISTENT_UUID),
    )
    validate_error(response, "ERR_NOT_FOUND", 404)
