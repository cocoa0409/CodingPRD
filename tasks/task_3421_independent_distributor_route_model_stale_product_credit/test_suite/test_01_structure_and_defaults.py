"""Creation shape, system defaults, computed-field protection, and 404.

Covers PRD §2.5 common fields, §3.1 bakery/distributor creation, §3.3
production-day capacity defaults and draft order shape, and §2.10 path
existence. Instances: Corner/entities/* (5) and
Corner/state_machines/new_order_starts_draft_with_null_computed_fields.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_bakery,
    assert_daily_order,
    assert_distributor,
    assert_production_day,
    create_bakery,
    create_bakery_payload,
    create_distributor_payload,
    create_order,
    create_order_payload,
    create_production_day,
    create_production_day_payload,
    make_distributor_headers,
    order_line,
    reset_clock_to_default,
    setup_active_cash_agreement,
    validate_error,
    validate_success,
)

_ADMIN = TEST_USERS["company_admin_headers"]
_ROUTE_OPS = TEST_USERS["route_ops_manager_headers"]


def test_bakery_create_returns_every_declared_field(api):
    """PRD §3.1: "A `CompanyAdmin` registers a bakery with a display `name`, a
    `daily_capacity_units` default of at least 1, and a fixed `product_catalog`
    whose entries each name a `sku`, a `display_name`, a `shelf_life_days` of
    at least 1, and a `list_price_cents` of at least 1; each `sku` must be
    unique within that catalog."
    PRD §4: "Operations that create new resources — a bakery, a territory, a
    distributor, a production day, an agreement, a financing plan, a retail
    account, an audit entry, an order, or a stale claim — return a `201
    Created` status code."

    Design: Corner/entities/bakery_create_returns_every_declared_field
    """
    reset_clock_to_default()
    resp = api_client.create_bakery(create_bakery_payload(), _ADMIN)
    data = validate_success(resp, 201)
    assert_bakery(data)
    assert data["name"] == "Southwest Bakery"
    assert data["daily_capacity_units"] == 100
    catalog = data["product_catalog"]
    assert len(catalog) == 4
    first = catalog[0]
    assert first["sku"] == "WHT-24"
    assert first["display_name"] == "White 24oz"
    assert first["shelf_life_days"] == 5
    assert first["list_price_cents"] == 320
    assert data["version"] == 1
    assert data["id"]
    assert data["created_at"]
    assert data["updated_at"]
    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"]
    assert body["meta"]["api_request_timestamp"]


def test_distributor_create_applies_system_defaults(api):
    """PRD §3.1: "The new distributor starts in `PROSPECT` status, with
    `classification_status` `INDEPENDENT_CONTRACTOR`, `account_standing`
    `GOOD`, and a zeroed `trade_balance_cents`."
    PRD §4: "Operations that create new resources — a bakery, a territory, a
    distributor, a production day, an agreement, a financing plan, a retail
    account, an audit entry, an order, or a stale claim — return a `201
    Created` status code."

    Design: Corner/entities/distributor_create_applies_system_defaults
    """
    reset_clock_to_default()
    resp = api_client.create_distributor(create_distributor_payload(), _ADMIN)
    data = validate_success(resp, 201)
    assert_distributor(data)
    assert data["status"] == "PROSPECT"
    assert data["classification_status"] == "INDEPENDENT_CONTRACTOR"
    assert data["account_standing"] == "GOOD"
    assert data["trade_balance_cents"] == 0


def test_production_day_capacity_defaults_and_override(api):
    """PRD §3.3: "the day's `capacity_units` takes the override when supplied
    and the bakery's `daily_capacity_units` otherwise, and the day's
    `bakery_id` is taken from the creation path."
    PRD §3.3: "The day opens in `PLANNING`; a bakery's days may be listed
    filtered by `status` or `date`."

    Design: Corner/entities/production_day_capacity_defaults_and_override
    """
    reset_clock_to_default()
    bakery = create_bakery()
    resp_a = api_client.create_production_day(
        bakery["id"], create_production_day_payload("2026-09-04"), _ADMIN
    )
    day_a = validate_success(resp_a, 201)
    resp_b = api_client.create_production_day(
        bakery["id"],
        create_production_day_payload("2026-09-05", capacity_override_units=40),
        _ADMIN,
    )
    day_b = validate_success(resp_b, 201)
    assert_production_day(day_a)
    assert_production_day(day_b)
    assert day_a["capacity_units"] == 100, "default from bakery capacity"
    assert day_b["capacity_units"] == 40, "override honored"
    for day in (day_a, day_b):
        assert day["status"] == "PLANNING"
        assert day["allocated_units"] == 0
        assert day["version"] == 1


def test_agreement_get_unknown_id_returns_not_found(api):
    """PRD §2.10: "Paths that contain several resource identifiers are
    validated left to right: the first identifier that does not resolve to an
    existing resource rejects the request with `ERR_NOT_FOUND` before any later
    identifier is examined."

    Design: Corner/entities/agreement_get_unknown_id_returns_not_found
    """
    reset_clock_to_default()
    resp = api_client.get_agreement(
        "00000000-0000-4000-8000-000000000000", _ROUTE_OPS
    )
    error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert error["error_id"] == "ERR_NOT_FOUND"
    assert error["message"]
    assert resp.json()["response_type"] == "error"


def test_order_create_units_total_input_ignored(api):
    """PRD §3.3: "The draft's `units_total` is the sum of its line quantities,
    and its `submitted_on` stays null while it remains a draft."
    PRD §2.5: "`version` (integer): increments by one on every mutation of the
    resource — including mutations performed as side effects of operations on
    other resources, such as a territory's `version` advancing when an
    agreement is created against it, or a distributor's `version` advancing
    when the trade ledger moves."

    Design: Corner/entities/order_create_units_total_input_ignored
    """
    ctx = setup_active_cash_agreement()
    distributor = ctx["distributor"]
    payload = create_order_payload(
        "2026-09-04", [order_line("WHT-24", 10), order_line("BUN-12", 5)]
    )
    payload["units_total"] = 999
    payload["version"] = 99
    resp = api_client.create_order(
        distributor["id"], payload, make_distributor_headers(distributor["id"])
    )
    data = validate_success(resp, 201)
    assert_daily_order(data)
    assert data["units_total"] == 15, "computed 10 + 5, not client-supplied 999"
    assert data["version"] == 1, "system-managed version, not client-supplied 99"
    assert data["status"] == "DRAFT"


def test_new_order_starts_draft_with_null_computed_fields(api):
    """PRD §3.3: "The draft's `units_total` is the sum of its line quantities,
    and its `submitted_on` stays null while it remains a draft."
    PRD §3.4: "An order that never reaches delivery keeps `total_charge_cents`
    null."
    PRD §3.4: "Until reconciliation, an order's `shortage_credit_cents` is
    zero."

    Design: Corner/state_machines/new_order_starts_draft_with_null_computed_fields
    """
    ctx = setup_active_cash_agreement()
    order = create_order(
        ctx["distributor"], "2026-09-04", [order_line("BUN-12", 3)]
    )
    assert_daily_order(order)
    assert order["status"] == "DRAFT"
    assert order["submitted_on"] is None
    assert order["total_charge_cents"] is None
    assert order["shortage_credit_cents"] == 0
    assert order["cancelled_reason"] is None
    assert order["units_total"] == 3
