"""Corner queue (entities): creation defaults, required fields, enum ranges,
404 envelope, list pagination/filtering, and append-only event shape."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_emissions_reading,
    assert_inventory_record,
    assert_product,
    create_product,
    create_product_payload,
    create_permit,
    get_permit,
    is_iso8601_timestamp,
    is_valid_uuid,
    record_reading,
    setup_shaken_units,
    validate_error,
    validate_paginated,
    validate_success,
)

_FM = TEST_USERS["foundry_manager_headers"]
_QI = TEST_USERS["quality_inspector_headers"]

_PRODUCT = dict(sku_code="L8SK3", name="Skillet 10.25in", category="SKILLET")


def test_product_create_success_applies_defaults(api):
    """PRD §3.1: "A product is born with `status` `ACTIVE`."
    PRD §3.1: "Creating a product also auto-creates its `InventoryRecord` in the
    same act: one record per product, unique per product, with `on_hand_units` 0,
    `reserved_units` 0, `shipped_units` 0, `outlet_sold_units` 0, and `version` 1."
    PRD §2.5: "A resource's `version` starts at 1 upon creation and increments by
    exactly 1 on every mutation of that resource"

    Design: Corner/entities/product_create_success_applies_defaults
    """
    resp = api.create_product(create_product_payload(**_PRODUCT), _FM)
    product = validate_success(resp, expected_status=201)
    assert_product(product)
    assert product["status"] == "ACTIVE"
    assert product["version"] == 1
    assert is_valid_uuid(product["id"])
    assert is_iso8601_timestamp(product["created_at"])
    assert is_iso8601_timestamp(product["updated_at"])
    records, meta = validate_paginated(api.list_inventory_records(
        _FM, params={"product_id": product["id"]}))
    assert meta["total_count"] == 1
    record = records[0]
    assert_inventory_record(record)
    assert record["on_hand_units"] == 0
    assert record["reserved_units"] == 0
    assert record["available_units"] == 0
    assert record["version"] == 1


def test_product_create_missing_required_sku_returns_invalid_request(api):
    """PRD §2.9: "fourth, request-body well-formedness — required fields present,
    no undeclared fields, enum values in range, planned percentage sums, window end
    strictly after start, quantities at least 1, week numbers within 1 through 53
    (`ERR_INVALID_REQUEST`)"
    PRD §3.1: "A `FoundryManager` registers a cookware product by supplying a
    `sku_code` that is unique across all products"
    Omitting sku_code is a 400 and persists nothing.

    Design: Corner/entities/product_create_missing_required_sku_returns_invalid_request
    """
    payload = create_product_payload(**_PRODUCT)
    del payload["sku_code"]
    resp = api.create_product(payload, _FM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    _, meta = validate_paginated(api.list_products(_FM))
    assert meta["total_count"] == 0


def test_product_create_invalid_enum_category_rejected(api):
    """PRD §3.1: "a `category` that is one of `SKILLET`, `DUTCH_OVEN`, `GRIDDLE`,
    `GRILL_PAN`, or `BAKEWARE`."
    PRD §2.9: "fourth, request-body well-formedness — required fields present, no
    undeclared fields, enum values in range"
    category PAN is outside the declared enum.

    Design: Corner/entities/product_create_invalid_enum_category_rejected
    """
    payload = create_product_payload(**_PRODUCT)
    payload["category"] = "PAN"
    resp = api.create_product(payload, _FM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_production_order_get_not_found_returns_error(api):
    """PRD §2.10: "every identifier — path or body — must resolve to an existing
    resource; the first identifier that does not resolve rejects the request with
    `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    The 404 body carries response_type "error" with data.error_id and
    data.message; a normal product read carries response_type "object".

    Design: Corner/entities/production_order_get_not_found_returns_error
    """
    product = create_product(**_PRODUCT)
    resp = api.get_production_order(NON_EXISTENT_UUID, _FM)
    err = validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert err["message"].strip()
    assert body["meta"]["api_request_id"]
    assert body["meta"]["api_request_timestamp"]
    ok = api.get_product(product["id"], _FM)
    data = validate_success(ok)
    assert ok.json()["response_type"] == "object"
    assert data["sku_code"] == "L8SK3"


def test_casting_units_list_pagination_and_status_filter(api):
    """PRD §2.3: "List responses carry the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object."
    Thirteen SHAKEOUT_DONE units: page 1 (limit 10) reports has_more true; page 2
    (offset 10) returns 3 rows with has_more false; the state filter narrows
    FINISHED to 0.

    Design: Corner/entities/casting_units_list_pagination_and_status_filter
    """
    ctx = setup_shaken_units(num_units=13, order_overrides={"planned_quantity": 30})
    order_id = ctx["order"]["id"]
    page1, meta1 = validate_paginated(api.list_casting_units(
        _QI, params={"production_order_id": order_id, "limit": 10}))
    assert meta1["total_count"] == 13
    assert meta1["has_more"] is True
    assert len(page1) == 10
    page2, meta2 = validate_paginated(api.list_casting_units(
        _QI, params={"production_order_id": order_id, "limit": 10, "offset": 10}))
    assert meta2["total_count"] == 13
    assert meta2["has_more"] is False
    assert len(page2) == 3
    done, meta_done = validate_paginated(api.list_casting_units(
        _QI, params={"production_order_id": order_id, "state": "FINISHED"}))
    assert meta_done["total_count"] == 0
    assert done == []
    _, meta_shaken = validate_paginated(api.list_casting_units(
        _QI, params={"production_order_id": order_id, "state": "SHAKEOUT_DONE"}))
    assert meta_shaken["total_count"] == 13


def test_emissions_reading_immutable_event_has_no_version(api):
    """PRD §2.5: "An `EmissionsReading` and an `OutletSale` each carry only `id`
    and `created_at` — both `updated_at` and `version` are absent on these two
    resources"
    PRD §3.7: "A reading below `limit_value` leaves the permit unchanged."

    Design: Corner/entities/emissions_reading_immutable_event_has_no_version
    """
    permit = create_permit("AIR_EMISSIONS", limit_value=100.0)
    reading = record_reading(permit["id"], 50.0)
    assert_emissions_reading(reading)
    assert "version" not in reading
    assert "updated_at" not in reading
    assert reading["recorded_by"] == "eo-1"
    permit = get_permit(permit["id"])
    assert permit["status"] == "ACTIVE"
    assert permit["over_limit_reading_count_current_period"] == 0
