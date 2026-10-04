"""Entity-level corners: creation defaults, round-trips, listing, errors."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    create_assignment,
    create_order,
    create_product,
    create_rep,
    create_route,
    create_route_day,
    create_store,
    is_iso8601_timestamp,
    is_valid_uuid,
    load_route_day,
    lot_entry,
    make_admin_headers,
    make_rep_headers,
    make_supervisor_headers,
    order_line,
    set_clock,
    start_route_day,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_store_create_returns_declared_fields_with_defaults(api):
    """PRD §3.1: "New stores begin with status set to ACTIVE and a
    promo_rebate_balance_cents of zero."
    PRD §2.4: "Every resource in this API carries a server-minted id formatted
    as a UUID with no type prefix, plus a created_at timestamp in ISO 8601 UTC
    with three fractional digits."

    Design: Corner/entities/store_create_returns_declared_fields_with_defaults
    """
    set_clock()
    resp = api.create_store(
        {
            "store_code": "SA",
            "name": "Store A",
            "format": "CONVENIENCE",
            "credit_policy": "SALVAGE_RATE",
            "delivery_window_start_minute": 480,
            "delivery_window_end_minute": 720,
            "store_credit_cap_cents": 5000,
        },
        make_admin_headers(),
    )
    assert resp.status_code == 201
    store = validate_success(resp, expected_status=201)

    assert store["status"] == "ACTIVE"
    assert store["promo_rebate_balance_cents"] == 0
    assert store["version"] == 1
    assert store["credit_policy"] == "SALVAGE_RATE"
    assert store["format"] == "CONVENIENCE"
    assert is_valid_uuid(store["id"])
    assert is_iso8601_timestamp(store["created_at"])
    assert is_iso8601_timestamp(store["updated_at"])

    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])


def test_product_get_roundtrips_stored_fields(api):
    """PRD §3.1: "each product has a unique sku, a display name, a strictly
    positive case_price_cents list price per case, a strictly positive
    informational shelf_life_days, and a promo_eligible flag defaulting to
    true."

    Design: Corner/entities/product_get_roundtrips_stored_fields
    """
    resp = api.create_product(
        {"sku": "P-1", "name": "Chips", "case_price_cents": 335, "shelf_life_days": 60},
        make_admin_headers(),
    )
    product = validate_success(resp, expected_status=201)

    resp = api.get_product(product["id"], make_supervisor_headers())
    fetched = validate_success(resp)
    assert fetched["sku"] == "P-1"
    assert fetched["name"] == "Chips"
    assert fetched["case_price_cents"] == 335
    assert fetched["shelf_life_days"] == 60
    assert fetched["promo_eligible"] is True


def test_orders_list_filters_by_store_and_paginates(api):
    """PRD §2.3: "The meta object of a list response carries limit, offset,
    total_count, and has_more."
    PRD §4: "GET /dsd/orders — List orders filtered by route day, store, and/or
    status."

    Design: Corner/entities/orders_list_filters_by_store_and_paginates
    """
    set_clock()
    rep = create_rep()
    store_a = create_store(store_code="SA")
    store_b = create_store(store_code="SB", format="DOLLAR", credit_policy="SALVAGE_RATE")
    product = create_product()
    route = create_route(rep["id"])
    create_assignment(route["id"], store_a["id"])
    create_assignment(route["id"], store_b["id"], stop_sequence=2)
    day = create_route_day(route["id"])
    load_route_day(
        day["id"], [lot_entry(product["id"], "L-1", "2026-09-20", 100)], rep
    )
    start_route_day(day["id"], rep)
    create_order(day["id"], store_a["id"], [order_line(product["id"], 1)], rep)
    create_order(day["id"], store_a["id"], [order_line(product["id"], 2)], rep)
    create_order(day["id"], store_b["id"], [order_line(product["id"], 3)], rep)

    page_a, meta_a = validate_paginated(
        api.list_orders(
            make_supervisor_headers(),
            params={"store_id": store_a["id"], "limit": 1, "offset": 0},
        )
    )
    assert len(page_a) == 1
    assert meta_a["total_count"] == 2
    assert meta_a["has_more"] is True
    assert meta_a["limit"] == 1
    assert meta_a["offset"] == 0

    page_b, meta_b = validate_paginated(
        api.list_orders(make_supervisor_headers(), params={"store_id": store_b["id"]})
    )
    assert len(page_b) == 1
    assert meta_b["total_count"] == 1
    assert meta_b["has_more"] is False


def test_route_day_get_with_unknown_id_returns_not_found(api):
    """PRD §2.2: "The error_id is a unique, machine-readable string that
    identifies the specific error."
    PRD §5: ERR_ROUTE_DAY_NOT_FOUND is "RouteDay id does not exist" (404).

    Design: Corner/entities/route_day_get_with_unknown_id_returns_not_found
    """
    resp = api.get_route_day(NON_EXISTENT_UUID, make_supervisor_headers())
    assert resp.status_code == 404
    err = validate_error(resp, ApiErrorId.ERR_ROUTE_DAY_NOT_FOUND)
    assert isinstance(err["message"], str) and err["message"]
    body = resp.json()
    assert body["response_type"] == "error"


def test_order_create_missing_lines_returns_validation_error(api):
    """PRD §3.4: "the order must carry at least one line (ERR_VALIDATION on an
    empty set)."
    PRD §5: "ERR_VALIDATION | 400 Bad Request".

    Design: Corner/entities/order_create_missing_lines_returns_validation_error
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

    resp = api.create_order(
        {"route_day_id": day["id"], "store_id": store["id"]},
        make_rep_headers(rep["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_order_line_discount_defaults_to_zero(api):
    """PRD §3.4: "an optional line_discount_pct — a fractional discount of at
    least 0 and strictly less than 1, defaulting to 0."
    PRD §3.4: "Each line's line_total_cents is the line's qty_ordered_cases
    multiplied by the product's case_price_cents, multiplied by one minus the
    line_discount_pct, rounded half up to whole cents."

    Design: Corner/entities/order_line_discount_defaults_to_zero
    """
    set_clock()
    rep = create_rep()
    store = create_store()
    product = create_product(case_price_cents=335)
    route = create_route(rep["id"])
    create_assignment(route["id"], store["id"])
    day = create_route_day(route["id"])
    load_route_day(
        day["id"], [lot_entry(product["id"], "L-1", "2026-09-20", 10)], rep
    )
    start_route_day(day["id"], rep)

    resp = api.create_order(
        {
            "route_day_id": day["id"],
            "store_id": store["id"],
            "lines": [{"product_id": product["id"], "qty_ordered_cases": 7}],
        },
        make_rep_headers(rep["id"]),
    )
    order = validate_success(resp, expected_status=201)
    assert order["gross_total_cents"] == 2345  # 7 * 335, no discount

    lines, _ = validate_paginated(
        api.list_order_lines(make_supervisor_headers(), params={"order_id": order["id"]})
    )
    assert len(lines) == 1
    assert lines[0]["line_discount_pct"] == 0
    assert lines[0]["line_total_cents"] == 2345


def test_store_create_with_system_fields_input_ignored(api):
    """PRD §2.4: "Every resource in this API carries a server-minted id
    formatted as a UUID with no type prefix, plus a created_at timestamp in ISO
    8601 UTC with three fractional digits."
    PRD §3.1: "New stores begin with status set to ACTIVE and a
    promo_rebate_balance_cents of zero."

    Design: Corner/entities/store_create_with_system_fields_input_ignored
    """
    resp = api.create_store(
        {
            "store_code": "SA",
            "name": "Store A",
            "format": "GROCERY",
            "credit_policy": "FULL_RETAIL",
            "delivery_window_start_minute": 480,
            "delivery_window_end_minute": 720,
            "store_credit_cap_cents": 100000,
        },
        make_admin_headers(),
    )
    store = validate_success(resp, expected_status=201)
    assert store["version"] == 1
    assert store["status"] == "ACTIVE"
    assert is_valid_uuid(store["id"])


def test_order_type_invalid_enum_rejected(api):
    """PRD §3.4: "While the route day is IN_PROGRESS and the store is ACTIVE,
    the rep captures an order on the handheld: a payload containing the
    route_day_id, the store_id, an order_type (defaulting to STANDARD;
    EVENT_SURGE is permitted only on an event day, and supplying it on a
    standard day is ERR_VALIDATION), and a lines array."
    PRD §5: "ERR_VALIDATION | 400 Bad Request".

    Design: Corner/entities/order_type_invalid_enum_rejected
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

    resp = api.create_order(
        {
            "route_day_id": day["id"],
            "store_id": store["id"],
            "order_type": "BOGUS",
            "lines": [{"product_id": product["id"], "qty_ordered_cases": 1}],
        },
        make_rep_headers(rep["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_assignments_reverse_reachable_from_store_via_filtered_list(api):
    """PRD §4: "List assignments filtered by route and/or store".
    PRD §4: "List routes, optionally filtered by rsr_id".
    PRD §2.3: "Unless otherwise specified, every list endpoint returns
    resources sorted by their creation timestamp (created_at) in ascending
    order."

    Design: Corner/entities/assignments_reverse_reachable_from_store_via_filtered_list
    """
    rep1 = create_rep(full_name="Rep One")
    rep2 = create_rep(full_name="Rep Two")
    store = create_store()
    route1 = create_route(rep1["id"], territory_code="T-1")
    route2 = create_route(rep2["id"], territory_code="T-2")
    asg = create_assignment(route1["id"], store["id"])

    assignments, meta = validate_paginated(
        api_client.list_assignments(
            make_supervisor_headers(), params={"store_id": store["id"]}
        )
    )
    assert len(assignments) == 1
    assert assignments[0]["id"] == asg["id"]
    assert assignments[0]["route_id"] == route1["id"]

    routes, meta = validate_paginated(
        api_client.list_routes(
            make_supervisor_headers(), params={"rsr_id": rep2["id"]}
        )
    )
    assert len(routes) == 1
    assert routes[0]["id"] == route2["id"]
