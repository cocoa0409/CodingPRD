"""Accounts, catalog, and component pool: creation defaults, required fields,
enum membership, 404s, pagination, computed pool fields, and the immutable
compatibility-rule record."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_compatibility_rule,
    assert_component_pool_invariant,
    create_account_payload,
    create_chassis,
    create_component,
    add_allowed_rule,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_account_create_applies_defaults_version_one(api):
    """PRD §3.1: "The account starts in `ACTIVE` status with `outstanding_cents`
    and `recovery_credit_cents` both at zero."
    PRD §2.4: "`version` (integer): a system-managed integer that starts at its
    initial value on creation and increments by exactly 1 on every mutation of
    the resource."

    Design: Corner/entities/account_create_applies_defaults
    """
    resp = api.create_account(
        create_account_payload(company_name="ACME-1", account_tier="PREMIER",
                               credit_limit_cents=5_000_000),
        ADMIN,
    )
    data = validate_success(resp, 201)
    assert data["outstanding_cents"] == 0
    assert data["recovery_credit_cents"] == 0
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1


def test_account_create_missing_required_field_returns_invalid_request(api):
    """PRD §2.9: "malformed-request validation (missing fields, wrong types,
    unknown enum members, `ERR_INVALID_REQUEST`) is the lowest-priority check
    of all."

    Design: Corner/entities/account_create_missing_required_field_returns_invalid_request
    """
    resp = api.create_account(
        {"company_name": "ACME-2", "credit_limit_cents": 5_000_000}, ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_account_create_invalid_enum_rejected(api):
    """PRD §3.1: "creating a `CustomerAccount` with its legal `company_name`, an
    `account_tier` of `STANDARD`, `PREMIER`, or `FEDERAL`, and a
    `credit_limit_cents` establishing the maximum outstanding receivable the
    account may carry."
    PRD §2.9: "malformed-request validation (missing fields, wrong types,
    unknown enum members, `ERR_INVALID_REQUEST`) is the lowest-priority check
    of all."

    Design: Corner/entities/account_create_invalid_enum_rejected
    """
    resp = api.create_account(
        create_account_payload(company_name="ACME-3", account_tier="GOLD",
                               credit_limit_cents=5_000_000),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_get_account_not_found_returns_404(api):
    """PRD §2.9: "then path existence left to right (`ERR_NOT_FOUND`), then
    state-machine legality (the target resource is not in a state from which
    the requested transition is defined, `ERR_INVALID_STATE`)."

    Design: Corner/entities/get_account_not_found_returns_404
    """
    resp = api.get_account(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_list_accounts_pagination_envelope(api):
    """PRD §2.3: "`limit` caps the number of items returned in a single page;
    when omitted it defaults to 10, and it is bounded below by 1 and above by
    100. `offset` skips a number of items from the front of the result set and
    defaults to 0. Every list response reports `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the response
    envelope."

    Design: Corner/entities/list_accounts_pagination_envelope
    """
    for name in ("PG-1", "PG-2", "PG-3"):
        resp = api.create_account(
            create_account_payload(company_name=name, credit_limit_cents=1_000), ADMIN,
        )
        assert resp.status_code == 201
    resp = api.list_accounts(ADMIN, params={"limit": 2, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True


def test_component_available_units_is_computed(api):
    """PRD §2.8: "`available_units` is a derived quantity equal to
    `stock_on_hand` minus `reserved_units`; it is never stored as an
    independent input, and every mutation that touches the pool — allocation,
    build start, restock, entitlement parts stocking, entitlement release —
    must keep this identity true."

    Design: Corner/entities/component_available_units_is_computed
    """
    resp = api.create_component(
        {"sku": "CMP-1", "kind": "CPU", "price_cents": 1_000, "lead_time_days": 2,
         "stock_on_hand": 7, "revision": "A01"},
        ADMIN,
    )
    data = validate_success(resp, 201)
    assert data["available_units"] == 7
    assert data["reserved_units"] == 0
    assert_component_pool_invariant(data)


def test_compatibility_rule_immutable_no_version_field(api):
    """PRD §2.4: "One exception applies: a `CompatibilityRule` is immutable
    after creation and carries only `id` and `created_at`; `updated_at` and
    `version` are absent on that resource."

    Design: Corner/entities/compatibility_rule_immutable_no_version_field
    """
    chassis = create_chassis(model_code="IR-1")
    component = create_component(sku="IR-C", price_cents=1_000, lead_time_days=1,
                                 stock_on_hand=1)
    resp = api.create_compatibility_rule(
        {"chassis_model_id": chassis["id"], "component_id": component["id"],
         "rule_type": "ALLOWED"},
        ADMIN,
    )
    data = validate_success(resp, 201)
    assert_compatibility_rule(data)
    # The create response itself is the proof surface: no mutation endpoint is
    # declared for compatibility rules in the PRD §4 endpoint table.
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])


def test_fk_reverse_reachability_order_lines(api):
    """PRD §4: "GET `/api/orders/{id}/lines` — List lines of an order."
    PRD §3.4: "Lines are added to a draft order one at a time. Each line
    references the validated configuration being purchased via
    `configuration_id`, carries a `qty` that must be at least 1, and declares a
    `ship_to_mode` of `SINGLE_ADDRESS` or `DROP_SHIP_EMPLOYEES`."

    Design: Corner/entities/fk_reverse_reachability_order_lines
    """
    from test_helpers import (
        create_account, add_allowed_rule, create_chassis, create_component,
        create_configuration, create_order_with_lines, make_customer_user_headers,
    )
    account = create_account(company_name="FK-1")
    chassis = create_chassis(model_code="FKL1")
    component = create_component(sku="FKC1")
    add_allowed_rule(chassis["id"], component["id"])
    config = create_configuration(account, chassis["id"],
                                  [{"component_id": component["id"], "qty": 1}])
    order, lines = create_order_with_lines(
        account,
        [{"configuration_id": config["id"], "qty": 2, "ship_to_mode": "SINGLE_ADDRESS"}],
        po_number="PO-FK1",
    )
    resp = api.list_order_lines(order["id"], make_customer_user_headers(account["id"]))
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert data[0]["id"] == lines[0]["id"]
    assert data[0]["qty"] == 2


def test_order_line_qty_zero_rejected(api):
    """PRD §3.4: "A line quantity below 1, or a drop-ship plan whose
    destination units do not sum exactly to the line quantity, is rejected
    with `ERR_INVALID_ORDER_QUANTITY` (HTTP 422) — the quantity check applies
    both when a line is added and when the order's deployment waves are
    planned."

    Design: Corner/entities/order_line_qty_zero_rejected
    """
    from test_helpers import (
        create_account, create_configuration, make_customer_user_headers,
    )
    account = create_account(company_name="QZ-1")
    chassis = create_chassis(model_code="QZL1")
    component = create_component(sku="QZC1")
    add_allowed_rule(chassis["id"], component["id"])
    config = create_configuration(account, chassis["id"],
                                  [{"component_id": component["id"], "qty": 1}])
    resp = api.create_order({"account_id": account["id"], "po_number": "PO-QZ"},
                            make_customer_user_headers(account["id"]))
    order = get_success_data(resp)
    resp = api.add_order_line(
        order["id"],
        {"configuration_id": config["id"], "qty": 0, "ship_to_mode": "SINGLE_ADDRESS"},
        make_customer_user_headers(account["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_ORDER_QUANTITY.value, 422)
    resp = api.list_order_lines(order["id"], make_customer_user_headers(account["id"]))
    data, _meta = validate_paginated(resp)
    assert len(data) == 0
