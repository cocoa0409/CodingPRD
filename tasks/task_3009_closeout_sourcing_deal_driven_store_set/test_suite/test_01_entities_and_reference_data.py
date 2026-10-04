"""Corner coverage for foundational records: required fields, defaults and
provisional cost, request-shape rejection, not-found envelope, enum typing,
FK existence, listing pagination, reverse reachability, screening
immutability."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_lot,
    complete_screening,
    create_default_jurisdiction,
    create_lot,
    create_lot_payload,
    create_store,
    create_vendor,
    get_success_data,
    open_screening,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_create_vendor_missing_required_vendor_code(api, buyer_headers, admin_headers):
    """PRD §3.1: "A `SourcingBuyer` or `Admin` registers a **Vendor** with a
    display `name` and a `vendor_code` that is unique across all vendors."
    PRD §2.6: "Request-shape validation (required fields, types, enum
    membership, quantity floors, no unknown fields, and the presence of
    required optimistic-concurrency fields) is enforced as
    `ERR_INVALID_REQUEST`".

    Design: Corner/entities/create_vendor_missing_required_vendor_code
    """
    resp = api.create_vendor({"name": "No Code Vendor"}, buyer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_lot_system_defaults_and_provisional_cost(api, buyer_headers):
    """PRD §3.2: "The lot is created directly in `commercial_status` `SOURCED`
    with `safety_status` `PENDING_SCREEN`; its `retail_price_cents` is unset,
    `advertises_comparison` defaults to false, `sellable_qty_confirmed` is null
    until a screening passes, `markdown_rounds` is 0, `on_sale_since` is null
    until first sale, `qty_liquidated` and `qty_scrapped` are 0, and the entire
    `quantity_total` sits in `qty_pool`."
    PRD §3.5: "the provisional variant divides the lot's `total_cost_cents` by
    `est_sellable_qty` and rounds half-up to a whole cent."

    Design: Corner/entities/create_lot_system_defaults_and_provisional_cost
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    resp = api.create_lot(
        create_lot_payload(
            vendor["id"], jur["id"],
            quantity_total=80, total_cost_cents=80000, est_sellable_qty=40),
        buyer_headers)
    lot = validate_success(resp, 201)
    assert_lot(lot)
    assert lot["commercial_status"] == "SOURCED"
    assert lot["safety_status"] == "PENDING_SCREEN"
    assert lot["qty_pool"] == 80
    assert lot["markdown_rounds"] == 0
    assert lot["version"] == 1
    # provisional variant: round_half_up(80000 / 40) == 2000
    assert lot["landed_unit_cost_cents"] == 2000
    assert lot["created_by_user_id"] == "buyer-1"


def test_create_lot_extra_field_rejected(api, buyer_headers):
    """PRD §2.6: "Request-shape validation (required fields, types, enum
    membership, quantity floors, no unknown fields, and the presence of
    required optimistic-concurrency fields) is enforced as
    `ERR_INVALID_REQUEST`".

    Design: Corner/entities/create_lot_extra_field_rejected
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    payload = create_lot_payload(vendor["id"], jur["id"], quantity_total=80,
                                 total_cost_cents=80000, est_sellable_qty=40)
    payload["qty_pool"] = 999  # computed field is never client-settable
    resp = api.create_lot(payload, buyer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_lot_not_found_returns_404(api, admin_headers):
    """PRD §2.6: "Existence checks come next: path identifiers are validated
    left-to-right, and body foreign-key references ... must resolve to existing
    resources, with any failure reported as `ERR_NOT_FOUND`."
    PRD §2.2 error envelope: "The `error_id` is a unique, machine-readable
    string that identifies the specific error."

    Design: Corner/entities/get_lot_not_found_returns_404
    """
    resp = api.get_lot(NON_EXISTENT_UUID, admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)
    body = resp.json()
    assert body["response_type"] == "error"
    assert "api_request_id" in body["meta"]


def test_create_member_invalid_tier_enum(api, guest_headers):
    """PRD §3.1: "an `Anonymous` caller or an `Admin` registers a
    **LoyaltyMember** with a fleet-unique `member_code`, a `tier` of `BRONZE`,
    `SILVER`, or `GOLD`, and a `home_store_id` anchoring the member to a
    store."
    PRD §2.6: request-shape validation of "enum membership ... is enforced as
    `ERR_INVALID_REQUEST`".

    Design: Corner/entities/create_member_invalid_tier_enum
    """
    jur = create_default_jurisdiction()
    store = create_store(jur["id"])
    resp = api.create_member(
        {"member_code": "M-X", "tier": "PLATINUM", "home_store_id": store["id"]},
        guest_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_store_with_missing_jurisdiction_not_found(api, admin_headers):
    """PRD §2.6: "body foreign-key references such as `vendor_id`,
    `home_jurisdiction_id`, `jurisdiction_id`, `store_id`, `lot_id`,
    `member_id`, and `home_store_id` must resolve to existing resources, with
    any failure reported as `ERR_NOT_FOUND`."

    Design: Corner/entities/create_store_with_missing_jurisdiction_not_found
    """
    resp = api.create_store(
        {"name": "Store X", "store_code": "SX",
         "jurisdiction_id": NON_EXISTENT_UUID, "performance_tier": "TIER_1"},
        admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


def test_lots_list_pagination_defaults(api, admin_headers, buyer_headers):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items
    to return; it defaults to 10, with a minimum of 1 and a maximum of 100.
    The `offset` parameter specifies the number of items to skip and defaults
    to 0."
    PRD §3.2: "Lots may be listed with optional `commercial_status`,
    `vendor_id`, and `source_type` filters alongside the standard pagination
    parameters."

    Design: Corner/entities/lots_list_pagination_defaults
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    for i in range(11):
        create_lot(vendor["id"], jur["id"], title=f"Lot {i + 1:02d}",
                   quantity_total=10, total_cost_cents=1000, est_sellable_qty=10,
                   comparison_price_cents=1000, vendor_msrp_cents=1000)
    data, meta = validate_paginated(api.list_lots(admin_headers))
    assert len(data) == 10
    assert meta["total_count"] == 11
    assert meta["has_more"] is True
    data2, meta2 = validate_paginated(api.list_lots(admin_headers, params={"offset": 10}))
    assert len(data2) == 1
    assert meta2["has_more"] is False


def test_fk_reverse_vendor_lots_listing(api, admin_headers):
    """PRD §4: GET /vendors/{id}/lots — "List lots sourced from a vendor".
    PRD §3.2: "Lots may be listed with optional `commercial_status`,
    `vendor_id`, and `source_type` filters alongside the standard pagination
    parameters."

    Design: Corner/entities/fk_reverse_vendor_lots_listing
    """
    jur = create_default_jurisdiction()
    ven1 = create_vendor(name="Acme Closeouts", vendor_code="ACME")
    ven2 = create_vendor(name="Beta Salvage", vendor_code="BETA")
    lot = create_lot(ven1["id"], jur["id"], quantity_total=10,
                     total_cost_cents=1000, est_sellable_qty=10,
                     comparison_price_cents=1000, vendor_msrp_cents=1000)
    data1, meta1 = validate_paginated(api.list_vendor_lots(ven1["id"], admin_headers))
    assert [row["id"] for row in data1] == [lot["id"]]
    data2, meta2 = validate_paginated(api.list_vendor_lots(ven2["id"], admin_headers))
    assert data2 == []
    assert meta2["total_count"] == 0


def test_complete_screening_twice_rejected(api, admin_headers, officer_headers):
    """PRD §3.3: "Only a `PENDING` screening can be completed — attempting
    otherwise is `ERR_INVALID_STATE`" and "a completed screening is never
    edited."

    Design: Corner/entities/complete_screening_twice_rejected
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    lot = create_lot(vendor["id"], jur["id"], quantity_total=10,
                     total_cost_cents=1000, est_sellable_qty=10,
                     comparison_price_cents=10000, vendor_msrp_cents=10000)
    scr = open_screening(lot["id"], officer_headers)
    done = complete_screening(lot["id"], scr["id"], officer_headers,
                              qty_grade_a=10, qty_grade_b=0, qty_grade_c=0)
    assert done["result"] == "PASSED"
    resp = api.complete_screening(
        lot["id"], scr["id"],
        {"recall_check": "FAIL", "expiration_check": "FAIL",
         "condition_verified": False,
         "qty_grade_a": 10, "qty_grade_b": 0, "qty_grade_c": 0},
        officer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    lot_after = get_success_data(api.get_lot(lot["id"], admin_headers))
    assert lot_after["commercial_status"] == "CLEARED"
