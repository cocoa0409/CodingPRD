"""Entity-surface claims: creation, retrieval, defaults, system fields."""

from test_helpers import (
    LOGICAL_CLOCK_START,
    NON_EXISTENT_UUID,
    api_client,
    is_valid_uuid,
    reset_clock,
    setup_active_registration,
    setup_customer,
    setup_regulation,
    setup_registry_row,
    setup_store,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_store_create_returns_declared_fields_and_starts_open(api, chain_admin_headers):
    """PRD §3.1: "its `store_status` starts at `OPEN`, and it must be moved to `ACTIVE` before it may sell credit."
    PRD §2.12: "`version` is an integer that starts at 1 and increments by one on every modification to the resource"

    Design: Corner/entities/store_create_returns_declared_fields_and_starts_open
    """
    reset_clock(LOGICAL_CLOCK_START)
    response = api.create_store({
        "store_code": "0142",
        "name": "Highland Village",
        "state_code": "TX",
        "credit_capacity_cents": 5_000_000,
    }, chain_admin_headers)
    store = validate_success(response, 201)
    body = response.json()

    assert body["response_type"] == "object"
    assert store["store_status"] == "OPEN", "credit selling stays gated on the explicit activate call"
    assert store["version"] == 1
    assert store["open_repair_liability_cents"] == 0
    assert store["open_inspection_count"] == 0
    assert is_valid_uuid(store["id"])
    assert store["created_at"] and store["updated_at"]
    assert body["meta"]["api_request_id"] and body["meta"]["api_request_timestamp"]


def test_customer_get_round_trips_stored_values_including_null_phone(api, customer_service_headers):
    """PRD §3.1: "A `phone` number is optional and defaults to null."
    PRD §3.1: "A newly created customer carries `account_status` of `NO_FILE` and `credit_tier` of `NO_FILE`, an `outstanding_balance_cents` of 0, and no `standalone_credit_limit_cents` at all"

    Design: Corner/entities/customer_get_round_trips_stored_values_including_null_phone
    """
    reset_clock(LOGICAL_CLOCK_START)
    customer = setup_customer(full_name="Ivan Petrov", email="ivan.petrov@example.com",
                              state_code="NV")
    fetched = validate_success(api.get_customer(customer["id"], customer_service_headers), 200)

    assert fetched["full_name"] == "Ivan Petrov"
    assert fetched["email"] == "ivan.petrov@example.com"
    assert fetched["state_code"] == "NV"
    assert fetched["phone"] is None
    assert fetched["account_status"] == "NO_FILE"
    assert fetched["credit_tier"] == "NO_FILE"
    assert fetched["standalone_credit_limit_cents"] == 0
    assert fetched["outstanding_balance_cents"] == 0
    assert fetched["lifetime_purchase_cents"] == 0
    assert fetched["lost_inspection_streak"] == 0


def test_stores_list_paginates_and_reports_total_count_and_has_more(api, chain_admin_headers):
    """PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the response envelope's `meta` object"
    PRD §2.3: "`offset` skips that many items from the front of the result and defaults to 0."

    Design: Corner/entities/stores_list_paginates_and_reports_total_count_and_has_more
    """
    reset_clock(LOGICAL_CLOCK_START)
    setup_store(store_code="0142", name="Highland Village", state_code="TX", activate=False)
    setup_store(store_code="0210", name="Summerlin", state_code="NV", activate=False)
    setup_store(store_code="0333", name="Glendale", state_code="CA", activate=False)

    first, first_meta = validate_paginated(
        api.list_stores(chain_admin_headers, params={"limit": 2, "offset": 0}))
    assert len(first) == 2
    assert first_meta["total_count"] == 3, "total_count counts the whole filtered set"
    assert first_meta["has_more"] is True

    second, second_meta = validate_paginated(
        api.list_stores(chain_admin_headers, params={"limit": 2, "offset": 2}))
    assert len(second) == 1
    assert second_meta["has_more"] is False
    assert len({s["id"] for s in first} | {s["id"] for s in second}) == 3


def test_unknown_store_id_returns_not_found(api, chain_admin_headers):
    """PRD §2.14: "Priority 3 is existence: the path resource must exist, and on a flat entity the foreign-key fields named in the input are resolved left to right in the order the endpoint's input list declares them; a failure is `ERR_RESOURCE_NOT_FOUND` (404)."
    PRD §2.2: "All error API responses (4xx status codes) follow this standard envelope format"

    Design: Corner/entities/unknown_store_id_returns_not_found
    """
    reset_clock(LOGICAL_CLOCK_START)
    response = api.get_store(NON_EXISTENT_UUID, chain_admin_headers)
    validate_error(response, "ERR_RESOURCE_NOT_FOUND", expected_status=404)
    assert response.json()["response_type"] == "error"


def test_purchase_create_missing_required_base_price_returns_invalid_request(
        api, sales_associate_headers):
    """PRD §2.14: "a request body that misses a required field, carries an unknown field, or carries a field of the wrong type is refused with `ERR_INVALID_REQUEST` (400)"
    PRD §3.2: "A purchase ticket is opened by a `SalesAssociate` with the buyer's `customer_id`, the selling `store_id`, the `base_price_cents` of the new item before any credit"

    Design: Corner/entities/purchase_create_missing_required_base_price_returns_invalid_request
    """
    reset_clock(LOGICAL_CLOCK_START)
    store = setup_store()
    customer = setup_customer()
    response = api.create_purchase({
        "customer_id": customer["id"],
        "store_id": store["id"],
    }, sales_associate_headers)
    validate_error(response, "ERR_INVALID_REQUEST", expected_status=400)

    data, meta = validate_paginated(
        api.list_purchases(sales_associate_headers, params={"customer_id": customer["id"]}))
    assert data == []
    assert meta["total_count"] == 0


def test_credit_application_defaults_down_payment_and_income_to_null(
        api, sales_associate_headers):
    """PRD §3.1: "an optional `down_payment_cents` of cash tendered with the request (defaulting to 0), and an optional `declared_annual_income_cents` (defaulting to null, meaning the applicant declared nothing)"
    PRD §2.4: "otherwise `TIER_1` when `requested_limit_cents` is at least 200,000 cents (2,000 dollars)"

    Design: Corner/entities/credit_application_defaults_down_payment_and_income_to_null
    """
    reset_clock(LOGICAL_CLOCK_START)
    store = setup_store()
    setup_regulation()
    setup_registry_row(registry_key="TX", credit_tier="TIER_1", base_limit_cents=400_000,
                       min_down_payment_pct=0.20, min_ticket_cents=200_000)
    customer = setup_customer()

    application = validate_success(api.create_credit_application({
        "customer_id": customer["id"],
        "store_id": store["id"],
        "requested_limit_cents": 250_000,
        "requested_purchase_amount_cents": 250_000,
    }, sales_associate_headers), 201)

    assert application["down_payment_cents"] == 0
    assert application["declared_annual_income_cents"] is None, (
        "the income downgrade branch is skipped rather than treated as zero"
    )
    assert application["decision_status"] == "PENDING"
    assert application["decision_tier"] is None
    assert application["policy_tier"] == "TIER_1"


def test_store_open_repair_liability_is_recomputed_from_live_repairs(
        api, store_manager_headers):
    """PRD §2.16: "`open_repair_liability_cents` sums `loss_liability_cents` across the store's repairs currently in `INTAKE`, `ROUTED`, `IN_REPAIR`, or `QC_REVIEW`."
    PRD §2.16: "`available_credit_capacity_cents` is `credit_capacity_cents` minus `store_absorbed_total_cents` minus the outstanding customer credit, floored at 0"

    Design: Corner/entities/store_open_repair_liability_is_recomputed_from_live_repairs
    """
    customer, store, diamond, bundle, purchase, registration = setup_active_registration()
    repair = validate_success(api.create_repair({
        "customer_id": customer["id"], "store_id": store["id"],
        "diamond_id": diamond["id"], "registration_id": registration["id"],
        "failure_class": "SETTING", "declared_parts_cents": 40_000,
        "declared_labor_cents": 15_000, "declared_loss_liability_cents": 5_000,
    }, store_manager_headers), 201)
    assert repair["repair_status"] == "INTAKE"

    store_after = validate_success(api.get_store(store["id"], store_manager_headers), 200)
    assert repair["loss_liability_cents"] == 35_000
    assert store_after["open_repair_liability_cents"] == 35_000, (
        "the store figure is derived from the live repair"
    )
    assert store_after["available_credit_capacity_cents"] == 5_000_000 - 35_000


def test_invalid_enum_values_are_rejected_on_create(api, sales_associate_headers):
    """PRD §2.14: "a declared enum field receiving a value outside its constraint set, or a numeric field outside its declared range, is refused with `ERR_VALIDATION_FAILED` (422)."
    PRD §3.4: "A stone is registered with a unique `stone_code`, a `stone_kind` of `NATURAL` or `LAB_GROWN`"

    Design: Corner/entities/invalid_enum_values_are_rejected_on_create
    """
    reset_clock(LOGICAL_CLOCK_START)
    rejected = api.create_diamond({
        "stone_code": "ST-BAD", "stone_kind": "CUBIC_ZIRCONIA", "carat": 1.0,
    }, sales_associate_headers)
    validate_error(rejected, "ERR_VALIDATION_FAILED", expected_status=422)

    accepted = validate_success(api.create_diamond({
        "stone_code": "ST-GOOD", "stone_kind": "LAB_GROWN", "carat": 1.0,
    }, sales_associate_headers), 201)
    assert accepted["stone_kind"] == "LAB_GROWN"
    assert accepted["custody_status"] == "IN_CASE"

    rows, meta = validate_paginated(api.list_diamonds(sales_associate_headers))
    assert meta["total_count"] == 1, "the rejected stone was not persisted"
    assert rows[0]["stone_code"] == "ST-GOOD"


def test_flat_topology_foreign_keys_are_checked_in_declared_input_order(
        api, sales_associate_headers):
    """PRD §2.14: "Priority 3 is existence: the path resource must exist, and on a flat entity the foreign-key fields named in the input are resolved left to right in the order the endpoint's input list declares them; a failure is `ERR_RESOURCE_NOT_FOUND` (404)."
    PRD §2.15: "the identifiers are resolved in strict left-to-right order and the request is rejected at the first one that does not resolve, with `ERR_RESOURCE_NOT_FOUND` (404) and no partial processing"

    Design: Corner/entities/flat_topology_foreign_keys_are_checked_in_declared_input_order
    """
    reset_clock(LOGICAL_CLOCK_START)
    customer = setup_customer()
    ghost = "00000000-0000-4000-8000-00000000000b"

    both_unknown = api.create_credit_application({
        "customer_id": "00000000-0000-4000-8000-00000000000a",
        "store_id": ghost,
        "requested_limit_cents": 300_000,
        "requested_purchase_amount_cents": 300_000,
        "down_payment_cents": 30_000,
    }, sales_associate_headers)
    validate_error(both_unknown, "ERR_RESOURCE_NOT_FOUND", expected_status=404)

    store_unknown = api.create_credit_application({
        "customer_id": customer["id"],
        "store_id": ghost,
        "requested_limit_cents": 300_000,
        "requested_purchase_amount_cents": 300_000,
        "down_payment_cents": 30_000,
    }, sales_associate_headers)
    validate_error(store_unknown, "ERR_RESOURCE_NOT_FOUND", expected_status=404)

    rows, meta = validate_paginated(api.list_credit_applications(
        sales_associate_headers, params={"customer_id": customer["id"]}))
    assert meta["total_count"] == 0, "neither attempt persisted a row"

def test_a_newly_opened_store_carries_only_server_minted_common_fields(
        api, chain_admin_headers):
    """PRD §3.1: "its `store_status` starts at `OPEN`, and it must be moved to `ACTIVE` before it may sell credit."
    PRD §2.12: "`id` is a unique, server-minted identifier formatted as a UUID with no type prefix and no enclosing braces."
    PRD §2.16: "Before any call it reads the fixed startup default `2026-09-01T00:00:00Z` and never falls back to real wall-clock time."

    Design: Corner/entities/server_stamped_fields_ignore_client_supplied_values
    """
    reset_clock(LOGICAL_CLOCK_START)
    store = validate_success(api.create_store({
        "store_code": "0142",
        "name": "Highland Village",
        "state_code": "TX",
        "credit_capacity_cents": 5_000_000,
    }, chain_admin_headers), 201)

    assert store["store_status"] == "OPEN", "the server sets the operating status itself"
    assert store["version"] == 1, "version starts at 1 on a freshly written resource"
    assert store["created_at"] == "2026-09-01T00:00:00.000Z", (
        "the creation instant is stamped from the logical clock"
    )
    assert store["updated_at"] == store["created_at"], (
        "a create writes both timestamps to the same instant"
    )
    assert is_valid_uuid(store["id"]), "the id is a plain UUID with no type prefix"
