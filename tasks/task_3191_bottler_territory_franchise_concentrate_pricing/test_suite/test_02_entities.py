"""Entity creation, retrieval, defaults, computed-field, and constraint tests."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
    validate_paginated,
    get_success_data,
    is_valid_uuid,
    is_iso8601_timestamp,
    set_clock_default,
    create_brand_owner,
    create_territory,
    create_draft_agreement,
    create_product_line,
    create_price_index,
    seed_active_agreement,
    create_customer,
    create_cpo,
    ops_headers,
    make_bottler_ops_headers,
)

PA = TEST_USERS["platform_admin_headers"]
BOA = TEST_USERS["brand_owner_admin_headers"]


def test_brand_owner_create_returns_defaults_and_system_fields(api):
    """PRD §3.1: "A `PlatformAdmin` begins by registering a **brand owner**
    with a `name` and a `home_country`; the record starts in `ACTIVE` status
    and may later be `RETIRED`."
    PRD §2.4: "`version` is an integer that starts at 1 on creation and
    increments by 1 on every mutation, including mutations the system applies
    automatically as cascade side effects."

    Design: Corner/entities/brand_owner_create_returns_defaults_and_system_fields
    """
    set_clock_default()
    r = api_client.create_brand_owner({"name": "ColaCo", "home_country": "US"}, PA)
    assert r.status_code == 201
    body = r.json()
    assert body["response_type"] == "object"
    data = body["data"]
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert "api_request_id" in body["meta"] and body["meta"]["api_request_id"]
    assert "api_request_timestamp" in body["meta"] and body["meta"]["api_request_timestamp"]


def test_territory_get_roundtrips_stored_fields(api):
    """PRD §3.1: "The same operator then carves out **territories** for the
    brand, each identified by a unique `code` (for example, `SO-ATL-07`) and a
    human-readable `region_label`, linked to its owning brand through
    `brand_owner_id`. A territory is born `OPEN`."

    Design: Corner/entities/territory_get_roundtrips_stored_fields
    """
    set_clock_default()
    bo = create_brand_owner()
    ter = create_territory(bo["id"], code="SO-ATL-07", region_label="South Atlanta 07")
    data = validate_success(api_client.get_territory(ter["id"], PA))
    assert data["code"] == "SO-ATL-07"
    assert data["region_label"] == "South Atlanta 07"
    assert data["status"] == "OPEN"
    assert data["brand_owner_id"] == bo["id"]


def test_product_line_list_paginates_with_envelope_fields(api):
    """PRD §2.3: "`limit` caps the number of items returned; when omitted it
    defaults to 10, with a minimum of 1 and a maximum of 100. `offset`
    specifies how many items to skip and defaults to 0."
    PRD §2.3: "List responses carry the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the response
    envelope."

    Design: Corner/entities/product_line_list_paginates_with_envelope_fields
    """
    set_clock_default()
    bo = create_brand_owner()
    create_product_line(bo["id"], line_code="COLA-12OZ-CAN",
                        concentrate_base_price_per_gallon=12.0, is_mandatory=True)
    create_product_line(bo["id"], line_code="COLA-20OZ-PET",
                        concentrate_base_price_per_gallon=12.5, is_mandatory=False)
    data1, meta1 = validate_paginated(
        api_client.list_product_lines(BOA, params={"limit": 1, "offset": 0})
    )
    assert len(data1) == 1
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True
    data2, meta2 = validate_paginated(
        api_client.list_product_lines(BOA, params={"limit": 1, "offset": 1})
    )
    assert len(data2) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False
    assert data1[0]["id"] != data2[0]["id"]


def test_customer_get_missing_id_returns_not_found(api):
    """PRD §2.7: "(3) existence of every path identifier and every foreign-key
    identifier in the body — validated left to right, path parameters first and
    then body fields in their declared order — with any miss rejected as
    `ERR_RESOURCE_NOT_FOUND` (HTTP 404)".

    Design: Corner/entities/customer_get_missing_id_returns_not_found
    """
    set_clock_default()
    r = api_client.get_customer(NON_EXISTENT_UUID, PA)
    validate_error(r, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)
    assert r.status_code == 404


def test_territory_create_missing_code_rejected(api):
    """PRD §2.7: "(7) shape rules — required fields present and correctly typed,
    enum values valid, `discount_pct` within range, uniqueness of codes and
    tags (`ERR_VALIDATION`, HTTP 400)".
    PRD §3.1: "The same operator then carves out **territories** for the brand,
    each identified by a unique `code` (for example, `SO-ATL-07`) and a
    human-readable `region_label`, linked to its owning brand through
    `brand_owner_id`."

    Design: Corner/entities/territory_create_missing_code_rejected
    """
    set_clock_default()
    bo = create_brand_owner()
    r = api_client.create_territory(
        {"brand_owner_id": bo["id"], "region_label": "No Code Territory"}, PA
    )
    validate_error(r, ApiErrorId.ERR_VALIDATION.value)
    assert r.status_code == 400


def test_agreement_create_defaults_zero_ledgers_and_draft(api):
    """PRD §3.1: "A new agreement sits in `DRAFT`, with
    `marketing_fund_balance_cents`, `service_spent_cents`, and
    `margin_ledger_cents` all starting at zero."

    Design: Corner/entities/agreement_create_defaults_zero_ledgers_and_draft
    """
    set_clock_default()
    bo = create_brand_owner()
    create_price_index(bo["id"], quarter="2026-Q2", index_value=110.00)
    create_product_line(bo["id"])
    ter = create_territory(bo["id"])
    ag = create_draft_agreement(ter["id"])
    data = validate_success(api_client.get_agreement(ag["id"], PA))
    assert data["status"] == "DRAFT"
    assert data["version"] == 1
    assert data["marketing_fund_balance_cents"] == 0
    assert data["service_spent_cents"] == 0
    assert data["margin_ledger_cents"] == 0


def test_cpo_create_provisional_unit_price_input_ignored(api):
    """PRD §3.2: "At placement, the system computes the **provisional** unit
    price. The base is the product line's `concentrate_base_price_per_gallon`."
    PRD §3.2: "For the provisional variant, the selected index is the
    `index_value` of the most recent concentrate price index for the brand
    whose `quarter` is on or before the order's `delivery_quarter`; because at
    most one index exists per quarter, \"most recent\" is unambiguous."

    Design: Corner/entities/cpo_create_provisional_unit_price_input_ignored
    """
    env = seed_active_agreement()
    payload = {
        "agreement_id": env["agreement"]["id"],
        "product_line_id": env["line"]["id"],
        "quantity_gallons": 10000,
        "delivery_quarter": "2026-Q3",
        "expected_agreement_version": env["ag_v1"],
        "provisional_unit_price": 99.99,
    }
    r = api_client.create_cpo(payload, ops_headers(env))
    assert r.status_code == 201
    data = get_success_data(r)
    # 12.0 * (110/100) = 13.2000; qty 10000 -> no tier discount; 13.2*10000*100
    assert data["provisional_unit_price"] == pytest.approx(13.2, abs=1e-9)
    assert data["provisional_amount_cents"] == 13200000


def test_fountain_account_retail_customer_rejected(api):
    """PRD §3.5: "**Fountain accounts** serve customers whose `channel` is
    `FOUNTAIN`; opening an account against a `RETAIL` customer breaks the
    cross-reference rule and is rejected with `ERR_REFERENTIAL_INTEGRITY`."

    Design: Corner/entities/fountain_account_retail_customer_rejected
    """
    env = seed_active_agreement()
    cust = create_customer(env, channel="RETAIL")
    r = api_client.create_fountain_account({"customer_id": cust["id"]}, ops_headers(env))
    validate_error(r, ApiErrorId.ERR_REFERENTIAL_INTEGRITY.value)
    assert r.status_code == 422


def test_territory_code_uniqueness_enforced(api):
    """PRD §2.9: "Territory codes are unique across all territories
    system-wide; product-line codes are unique per brand owner; NCA codes are
    unique system-wide; and equipment asset tags are unique system-wide. A
    duplicate on any of these is a shape violation rejected with
    `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/territory_code_uniqueness_enforced
    """
    set_clock_default()
    bo = create_brand_owner()
    create_territory(bo["id"], code="SO-ATL-07")
    r = api_client.create_territory(
        {"brand_owner_id": bo["id"], "code": "SO-ATL-07", "region_label": "Duplicate Code"},
        PA,
    )
    validate_error(r, ApiErrorId.ERR_VALIDATION.value)
    assert r.status_code == 400
