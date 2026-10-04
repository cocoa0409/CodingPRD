"""Breadth: declared creation defaults, resolved read fields, and list reads."""
from test_helpers import ApiErrorId, NON_EXISTENT_UUID, validate_error, validate_paginated, validate_success
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    ANONYMOUS,
    PLATFORM_ADMIN,
    SALES_OPS,
    SETUP_TECH,
    SUPPORT_AGENT,
    create_backorder,
    create_customer,
    create_engineer,
    create_product,
    create_quote,
    add_quote_line,
    create_warranty_plan,
    setup_book_world,
    set_clock,
    setup_reserved_quote,
    setup_submitted_quote,
    walk_unit_to_shipped,
)


def test_engineer_creation_returns_the_declared_tier_defaults():
    """PRD 3.9: "Anything below that leaves them at `TIER_1` with a cap of 5000
    basis points, which is also the default for a newly registered engineer with
    no assessed attempts at all."

    Design: Corner/entities/engineer_create_returns_declared_defaults_and_tier_1
    """
    set_clock("2026-09-01T00:00:00.000Z")
    engineer = validate_success(
        api_client.create_engineer(
            {"full_name": "Dana Riggs", "email": "dana.riggs@sweetwater.example",
             "region": "MIDWEST"},
            PLATFORM_ADMIN,
        ),
        expected_status=201,
    )

    assert engineer["region"] == "MIDWEST"
    assert engineer["status"] == "ACTIVE"
    assert engineer["seniority_tier"] == "TIER_1"
    assert engineer["commission_cap_bps"] == 5000
    assert engineer["active_book_size"] == 0
    assert engineer["certified_family_count"] == 0
    assert engineer["version"] == 1
    assert engineer["created_at"] is not None
    assert engineer["updated_at"] is not None


def test_engineer_creation_answers_with_created_status_and_object_envelope():
    """PRD 4: "An operation that brings a new resource into existence —
    registering an engineer, a customer, a product, a service center, a quote, a
    quote line, an instrument unit, a warranty plan, a warranty claim, a support
    ticket, a backorder, a gear exchange, or a certification attempt — answers
    with HTTP 201 Created."

    Design: Corner/entities/engineer_create_returns_declared_defaults_and_tier_1
    """
    set_clock("2026-09-01T00:00:00.000Z")
    resp = api_client.create_engineer(
        {"full_name": "Dana Riggs", "email": "dana.riggs@sweetwater.example",
         "region": "MIDWEST"},
        PLATFORM_ADMIN,
    )
    assert resp.status_code == 201
    assert resp.json()["response_type"] == "object"
    assert resp.json()["data"]["seniority_tier"] == "TIER_1"


def test_customer_registration_defaults_to_standard_pending_and_unentitled():
    """PRD 3.1: "A self-registration creates a `Customer` in `PENDING` status,
    carrying a `full_name`, an `email` that must be unique among customers, a
    two-letter `home_state`, and an `account_tier` drawn from `STANDARD`,
    `PREMIUM`, or `STUDIO` and defaulting to `STANDARD`."

    Design: Corner/entities/customer_create_defaults_to_standard_pending_and_no_entitlement
    """
    set_clock("2026-09-01T00:00:00.000Z")
    customer = validate_success(
        api_client.create_customer(
            {"full_name": "Riley Chance", "email": "riley.chance@example.com",
             "home_state": "IN"},
            ANONYMOUS,
        ),
        expected_status=201,
    )

    assert customer["account_tier"] == "STANDARD"
    assert customer["status"] == "PENDING"
    assert customer["assigned_engineer_id"] is None


def test_fresh_customer_holds_no_purchase_count_credit_or_entitlement():
    """PRD 3.1: "a `Customer`'s `assigned_engineer_id` stays null until an
    assignment actually becomes `ACTIVE`." PRD 3.7: "With no warranty in force,
    the entitlement is `BASIC` only when the customer has both an `ACTIVE`
    assignment and at least one purchased instrument, and it is `NONE`
    otherwise."

    Design: Corner/entities/customer_create_defaults_to_standard_pending_and_no_entitlement
    """
    set_clock("2026-09-01T00:00:00.000Z")
    customer = validate_success(
        api_client.create_customer(
            {"full_name": "Riley Chance", "email": "riley.chance@example.com",
             "home_state": "IN"},
            ANONYMOUS,
        ),
        expected_status=201,
    )

    assert customer["purchased_instrument_count"] == 0
    assert customer["lifetime_gear_credit_cents"] == 0
    assert customer["tech_support_entitlement"] == "NONE"


def test_quote_line_read_exposes_the_server_resolved_catalogue_fields():
    """PRD 3.2: "The service resolves the `product_id` and copies
    `unit_price_cents` from the catalogue at creation time, derives
    `product_family` from the product, and assigns `bundle_discount_bps` — the
    per-line discount that a system package enjoys."

    Design: Corner/entities/quote_line_get_returns_resolved_price_and_family_fields
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    quote = create_quote(world["customer"], world["engineer"], "SYSTEM_PACKAGE")
    line = add_quote_line(quote, world["engineer"], product_code="SW-GTR-100",
                          quantity=1, is_anchor=True)

    fetched = validate_success(
        api_client.get_quote_line(line["id"],
                                  {"X-User-ID": world["engineer_id"],
                                   "X-User-Role": "Engineer",
                                   "Content-Type": "application/json"})
    )
    assert fetched["product_family"] == "GUITAR"
    assert fetched["quantity"] == 1
    assert fetched["is_anchor"] is True
    assert fetched["unit_price_cents"] == 120000
    assert fetched["bundle_discount_bps"] == 6667
    assert fetched["quote_id"] == quote["id"]


def test_quote_line_total_applies_the_system_discount_to_the_catalogue_price():
    """PRD 3.3: "First, the per-unit price for a line is the catalogue
    `unit_price_cents` reduced by the system line discount of 6667 basis points
    and rounded half-up to 2 decimal places".

    Design: Corner/entities/quote_line_get_returns_resolved_price_and_family_fields
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    quote = create_quote(world["customer"], world["engineer"], "SYSTEM_PACKAGE")
    line = add_quote_line(quote, world["engineer"], product_code="SW-GTR-100",
                          quantity=1, is_anchor=True)
    assert line["line_total_cents"] == 39996, (
        "round_half_up(120000 * 3333 / 10000) == 39996, times quantity 1"
    )


def test_quote_line_read_denies_a_role_the_operation_does_not_admit():
    """PRD 2.1: "A request that presents a perfectly well-formed pair of headers
    but claims a role the target operation does not admit is rejected with
    `ERR_UNAUTHORIZED` and HTTP 403." PRD 4: "GET | `/quote-lines/{id}` | Fetch
    one quote line | `PlatformAdmin`, `SalesEngineerOps`,
    `Engineer`"

    Design: Corner/entities/quote_line_get_returns_resolved_price_and_family_fields
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    quote = create_quote(world["customer"], world["engineer"], "SYSTEM_PACKAGE")
    line = add_quote_line(quote, world["engineer"], product_code="SW-GTR-100",
                          quantity=1, is_anchor=True)

    denied = api_client.get_quote_line(line["id"], ANONYMOUS)
    validate_error(denied, ApiErrorId.ERR_UNAUTHORIZED)

    ok = api_client.get_quote_line(line["id"], SALES_OPS)
    assert ok.status_code == 200


def test_unknown_quote_id_returns_quote_not_found():
    """PRD 2.10: "an unknown `Quote` yields `ERR_QUOTE_NOT_FOUND`".
    PRD 2.10: "All of these carry HTTP 404."

    Design: Corner/entities/quote_get_with_unknown_id_returns_quote_not_found
    """
    set_clock("2026-09-01T00:00:00.000Z")
    resp = api_client.get_quote(NON_EXISTENT_UUID, SALES_OPS)
    validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_FOUND)


def test_unknown_quote_error_body_carries_only_the_error_contract():
    """PRD 2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`." PRD 2.2: "The `error_id` is
    a unique, machine-readable string that identifies the specific error."

    Design: Corner/entities/quote_get_with_unknown_id_returns_quote_not_found
    """
    set_clock("2026-09-01T00:00:00.000Z")
    resp = api_client.get_quote(NON_EXISTENT_UUID, SALES_OPS)
    body = resp.json()
    assert resp.status_code == 404
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}
    assert set(body["data"].keys()) == {"error_id", "message"}


def test_backorders_list_scopes_by_engineer_and_reports_page_metadata():
    """PRD 2.3: "The `meta` object of a list response carries all four
    pagination fields: `limit`, `offset`, the total number of records matching
    the query before pagination as `total_count`, and a boolean `has_more` that
    is true exactly when more records remain beyond the returned window."

    Design: Corner/entities/backorders_list_filters_by_engineer_and_reports_pagination
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_submitted_quote(world)
    other_engineer = create_engineer("Priya Nair", "priya.nair@sweetwater.example", "EAST")
    create_backorder(world["guitar_line"], world["engineer"], units_requested=2,
                     preorder_open_at="2026-09-01T00:00:00.000Z")
    create_backorder(world["amp_line"], world["engineer"], units_requested=1,
                     preorder_open_at="2026-09-02T00:00:00.000Z")
    create_backorder(world["amp_line"], other_engineer, units_requested=1,
                     preorder_open_at="2026-09-03T00:00:00.000Z")

    first_page, meta = validate_paginated(
        api_client.list_backorders(SALES_OPS, {"engineer_id": world["engineer_id"],
                                              "limit": 1, "offset": 0})
    )
    assert len(first_page) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True

    second_page, meta2 = validate_paginated(
        api_client.list_backorders(SALES_OPS, {"engineer_id": world["engineer_id"],
                                              "limit": 1, "offset": 1})
    )
    assert len(second_page) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False


def test_backorders_list_default_page_returns_every_row_at_the_default_limit():
    """PRD 2.3: "When `limit` is omitted it defaults to 10; when `offset` is
    omitted it defaults to 0."

    Design: Corner/entities/backorders_list_filters_by_engineer_and_reports_pagination
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_submitted_quote(world)
    other_engineer = create_engineer("Priya Nair", "priya.nair@sweetwater.example", "EAST")
    create_backorder(world["guitar_line"], world["engineer"], units_requested=2,
                     preorder_open_at="2026-09-01T00:00:00.000Z")
    create_backorder(world["amp_line"], world["engineer"], units_requested=1,
                     preorder_open_at="2026-09-02T00:00:00.000Z")
    create_backorder(world["amp_line"], other_engineer, units_requested=1,
                     preorder_open_at="2026-09-03T00:00:00.000Z")

    rows, meta = validate_paginated(api_client.list_backorders(SALES_OPS))
    assert len(rows) == 3
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert all("alloc_sequence" in row and "eta_deadline" in row for row in rows)


def test_backorders_list_scopes_to_the_named_engineers_book():
    """PRD 3.10: "Backorders can be listed by `engineer_id`, `quote_line_id`, or
    `status`".

    Design: Corner/entities/backorders_list_filters_by_engineer_and_reports_pagination
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_submitted_quote(world)
    other_engineer = create_engineer("Priya Nair", "priya.nair@sweetwater.example", "EAST")
    create_backorder(world["guitar_line"], world["engineer"], units_requested=2,
                     preorder_open_at="2026-09-01T00:00:00.000Z")
    create_backorder(world["amp_line"], world["engineer"], units_requested=1,
                     preorder_open_at="2026-09-02T00:00:00.000Z")
    third = create_backorder(world["amp_line"], other_engineer, units_requested=1,
                             preorder_open_at="2026-09-03T00:00:00.000Z")

    rows, _ = validate_paginated(
        api_client.list_backorders(SALES_OPS, {"engineer_id": other_engineer["id"]})
    )
    assert len(rows) == 1
    assert rows[0]["id"] == third["id"]


def test_quote_creation_without_package_type_is_a_missing_required_field():
    """PRD 2.11: "a required body field that is simply absent raises
    `ERR_MISSING_REQUIRED_FIELD` at HTTP 400 rather than a state error".
    PRD 3.2: "A quote opens in `DRAFT` status against a `customer_id` and an
    `engineer_id`, and declares a `package_type` of `SYSTEM_PACKAGE`,
    `INSTRUMENT_ONLY`, or `ACCESSORY_ONLY`."

    Design: Corner/entities/quote_create_missing_package_type_returns_missing_required_field
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z", with_catalog=False)
    resp = api_client.create_quote(
        {"customer_id": world["customer_id"], "engineer_id": world["engineer_id"]},
        {"X-User-ID": world["engineer_id"], "X-User-Role": "Engineer",
         "Content-Type": "application/json"},
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_REQUIRED_FIELD)


def test_rejected_quote_creation_leaves_no_quote_row_behind():
    """PRD 2.11: "Structural body problems are the exception that proves the
    rule: a required body field that is simply absent raises
    `ERR_MISSING_REQUIRED_FIELD` at HTTP 400 rather than a state error."

    Design: Corner/entities/quote_create_missing_package_type_returns_missing_required_field
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z", with_catalog=False)
    api_client.create_quote(
        {"customer_id": world["customer_id"], "engineer_id": world["engineer_id"]},
        {"X-User-ID": world["engineer_id"], "X-User-Role": "Engineer",
         "Content-Type": "application/json"},
    )
    rows, meta = validate_paginated(
        api_client.list_quotes(SALES_OPS, {"customer_id": world["customer_id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_warranty_plan_creation_defaults_the_term_to_twenty_four_months():
    """PRD 3.6: "A `WarrantyPlan` is registered against the `customer_id` that
    owns it and the `instrument_unit_id` it covers, with a `term_months` drawn
    from exactly `12`, `24`, or `36` and defaulting to 24".

    Design: Corner/entities/warranty_plan_create_term_default_and_type_constraint
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    from test_helpers.fixtures import setup_shipped_instrument

    shipped = setup_shipped_instrument(world)
    plan = validate_success(
        api_client.create_warranty_plan(
            {"customer_id": world["customer_id"], "instrument_unit_id": shipped["id"]},
            SALES_OPS,
        ),
        expected_status=201,
    )
    assert plan["term_months"] == 24
    assert plan["status"] == "PENDING"


def test_new_warranty_plan_holds_the_full_three_round_allowance():
    """PRD 3.6: "`repair_rounds_used` counts the claims on the plan that have
    been closed, and `remaining_repair_rounds` is three minus that count,
    floored at zero so that it never goes negative."

    Design: Corner/entities/warranty_plan_create_term_default_and_type_constraint
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    from test_helpers.fixtures import setup_shipped_instrument

    shipped = setup_shipped_instrument(world)
    plan = create_warranty_plan(world["customer"], shipped)
    assert plan["repair_rounds_used"] == 0
    assert plan["remaining_repair_rounds"] == 3


def test_warranty_term_outside_the_declared_set_is_a_shape_violation():
    """PRD 3.6: "a term outside that set is a shape violation and raises
    `ERR_INVALID_FIELD_VALUE` at HTTP 400."

    Design: Corner/entities/warranty_plan_create_term_default_and_type_constraint
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    setup_reserved_quote(world)
    from test_helpers.fixtures import setup_shipped_instrument

    shipped = setup_shipped_instrument(world)
    create_warranty_plan(world["customer"], shipped)

    resp = api_client.create_warranty_plan(
        {"customer_id": world["customer_id"], "instrument_unit_id": shipped["id"],
         "term_months": 18},
        SALES_OPS,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_FIELD_VALUE)

    rows, _ = validate_paginated(
        api_client.list_warranty_plans(SUPPORT_AGENT,
                                       {"instrument_unit_id": shipped["id"]})
    )
    assert len(rows) == 1