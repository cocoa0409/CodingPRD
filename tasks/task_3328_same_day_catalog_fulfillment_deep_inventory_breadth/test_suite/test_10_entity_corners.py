"""Entity corners: creation shape, retrieval round-trips and parent relationships."""

from test_helpers import (
    ADMIN,
    CURATOR,
    DCM,
    ApiErrorId,
    create_attribute_payload,
    create_cross_reference_payload,
    create_distribution_center_payload,
    create_item_payload,
    create_stock_payload,
    create_supplier_payload,
    make_customer_account_headers,
    setup_account,
    setup_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ABSENT_ITEM = "00000000-0000-4000-8000-000000000000"

DIMENSIONS = {"nominal_length_mm": 55, "nominal_width_mm": 22,
              "nominal_height_mm": 22, "drawing_revision": 7}


def _create_item(api, sku, price=1500, long_tail=False, bundle=4, revision=1,
                 dimensions=None):
    payload = create_item_payload(
        sku=sku, description=f"Entity probe {sku}", material_spec="steel",
        long_tail=long_tail, unit_price_cents=price, unit_weight_kg=0.10,
        curation_bundle_size=bundle,
        curated_dimension_json=dimensions or {
            "nominal_length_mm": 10, "nominal_width_mm": 10,
            "nominal_height_mm": 10, "drawing_revision": revision})
    return validate_success(api.create_item(payload, CURATOR), 201)


def test_a_created_center_returns_every_declared_field_and_starts_open(api):
    """PRD §3.8: "A center is `OPEN` when it has no open quality or damage hold and its
    `inbound_reserved_units` is below a threshold".
    PRD §2.4: "`version` is an integer that starts at 1 when the row is created".
    PRD §2.5: "Setting the clock recomputes every center's `local_current_time` as
    `current_utc` plus that center's `utc_offset_minutes`".

    Design: Corner/entities/distribution_center_create_returns_every_declared_field_and_starts_open
    """
    setup_clock(api)
    dc = validate_success(api.create_distribution_center(
        create_distribution_center_payload(), ADMIN), 201)

    assert dc["operations_posture"] == "OPEN"
    assert dc["inbound_reserved_units"] == 0
    assert dc["version"] == 1
    assert dc["local_current_time"] == "04:00:00"
    assert dc["cutoff_passed"] is False
    assert dc["created_at"] and dc["updated_at"]


def test_an_item_get_round_trips_the_dimension_payload(api):
    """PRD §3.1: "The drawing payload is expected to hold `nominal_length_mm`,
    `nominal_width_mm`, `nominal_height_mm` and `drawing_revision`."
    PRD §3.1: "A newly created item starts with `catalog_status` `ACTIVE` and with
    `curation_review_state` `UNREVIEWED`".

    Design: Corner/entities/catalog_item_get_round_trips_the_dimension_payload
    """
    setup_clock(api)
    item = _create_item(api, "RT-1001", price=2500, bundle=6, dimensions=DIMENSIONS)

    fetched = validate_success(api.get_item(
        item["id"], make_customer_account_headers("acct-roundtrip")))

    assert fetched["sku"] == "RT-1001"
    assert fetched["material_spec"] == "steel"
    assert fetched["curated_dimension_json"]["nominal_length_mm"] == 55
    assert fetched["curated_dimension_json"]["nominal_width_mm"] == 22
    assert fetched["curated_dimension_json"]["drawing_revision"] == 7
    assert fetched["curation_review_state"] == "UNREVIEWED"
    assert fetched["catalog_status"] == "ACTIVE"


def test_the_item_list_filters_and_reports_total_count_and_has_more(api):
    """PRD §2.3: "the `meta` block of a list response carries `limit`, `offset`,
    `total_count` and `has_more`; `has_more` is true when further records remain beyond
    the requested window."
    PRD §3.11: "Searching the catalog accepts a free-text `q` term and narrower filters —
    `material_spec` for the material, `region` for the delivery region, `long_tail` for
    whether the item is long-tail sourced".

    Design: Corner/entities/items_list_filters_and_reports_total_count_and_has_more
    """
    setup_clock(api)
    _create_item(api, "LS-1001", price=1000)
    _create_item(api, "LS-1002", price=1100)
    lt_item = _create_item(api, "LS-1003", price=1200, long_tail=True, bundle=3)

    first, meta = validate_paginated(api.list_items(CURATOR, {"limit": 2, "offset": 0}))
    assert len(first) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    second, meta2 = validate_paginated(api.list_items(CURATOR, {"limit": 2, "offset": 2}))
    assert len(second) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    filtered, meta3 = validate_paginated(api.list_items(
        CURATOR, {"long_tail": True, "limit": 100, "offset": 0}))
    assert len(filtered) == 1
    assert filtered[0]["id"] == lt_item["id"]
    assert meta3["total_count"] == 1


def test_an_item_get_with_an_unknown_id_returns_item_not_found(api):
    """PRD §2.8: "The same left-to-right discipline governs the other parents, each with
    its own not-found code — `ERR_ITEM_NOT_FOUND` for an unresolvable `CatalogItem`".

    Design: Corner/entities/item_get_with_unknown_id_returns_item_not_found
    """
    setup_clock(api)

    response = api.get_item(ABSENT_ITEM, CURATOR)
    error_data = validate_error(response, ApiErrorId.ERR_ITEM_NOT_FOUND)

    assert error_data["error_id"] != ApiErrorId.ERR_ORDER_NOT_FOUND
    assert response.json()["response_type"] == "error"
    assert error_data["message"]


def test_creating_an_order_without_lines_returns_invalid_request(api):
    """PRD §2.9: "a request whose payload is malformed is rejected with
    `ERR_INVALID_REQUEST` (400) whenever a required body field is missing".
    PRD §3.3: "A `CustomerAccount` builds an order by supplying the `account_id` it is
    ordering under together with the complete set of `lines`".

    Design: Corner/entities/order_create_missing_lines_returns_invalid_request
    """
    setup_clock(api)
    acct = setup_account(api)
    headers = make_customer_account_headers(acct["id"])

    response = api.create_order({"account_id": acct["id"]}, headers)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    orders, _meta = validate_paginated(api.list_orders(
        headers, {"account_id": acct["id"], "limit": 10, "offset": 0}))
    assert orders == [], "the malformed request created no order"


def test_a_stock_row_defaults_its_derived_units_to_zero(api):
    """PRD §3.4: "The row's `reserved_units` begins at 0 and grows only through
    allocation, its `available_units` begins equal to `on_hand_units`".
    PRD §3.4: "its `positioning_flag` is left unset until the center's daily cutoff roll
    classifies it."

    Design: Corner/entities/stock_create_defaults_the_derived_units_to_zero
    """
    setup_clock(api)
    dc = validate_success(api.create_distribution_center(
        create_distribution_center_payload(), ADMIN), 201)
    acct = setup_account(api)
    item = _create_item(api, "DF-1001")

    stock = validate_success(api.create_stock(
        create_stock_payload(item_id=item["id"], dc_id=dc["id"], account_id=acct["id"],
                             on_hand_units=9, daily_demand_units=2,
                             inbound_daily_units=2), DCM), 201)

    assert stock["on_hand_units"] == 9
    assert stock["reserved_units"] == 0
    assert stock["available_units"] == 9
    assert stock["daily_demand_units"] == 2
    assert stock["inbound_daily_units"] == 2
    assert stock.get("positioning_flag") is None


def test_the_positioning_flag_is_computed_by_the_cutoff_roll(api):
    """PRD §3.8: "it recomputes the positioning classification of the center's inventory,
    it increments the center's `cutoff_sequence_index`, and it re-derives the center's
    `operations_posture`."
    PRD §3.8: "If that count is at least the positioning threshold of 2, the classification
    is `OK`."

    Design: Corner/entities/inventory_positioning_flag_is_computed_not_client_supplied
    """
    setup_clock(api)
    dc = validate_success(api.create_distribution_center(
        create_distribution_center_payload(), ADMIN), 201)
    acct = setup_account(api)
    items = [_create_item(api, f"CF-100{i}", price=1500 + i)
             for i in range(1, 4)]
    for item in items:
        validate_success(api.create_stock(
            create_stock_payload(item_id=item["id"], dc_id=dc["id"],
                                 account_id=acct["id"], on_hand_units=5,
                                 daily_demand_units=1, inbound_daily_units=1), DCM), 201)

    before, _meta = validate_paginated(api.list_stock(
        DCM, {"dc_id": dc["id"], "limit": 100, "offset": 0}))
    assert all(row.get("positioning_flag") is None for row in before)

    validate_success(api.roll_cutoff(dc["id"], DCM))

    after, _meta = validate_paginated(api.list_stock(
        DCM, {"dc_id": dc["id"], "limit": 100, "offset": 0}))
    assert all(row["positioning_flag"] == "OK" for row in after)
    rolled = validate_success(api.get_distribution_center(dc["id"], DCM))
    assert rolled["cutoff_sequence_index"] == 1


def test_an_attribute_row_is_immutable_and_carries_no_version(api):
    """PRD §2.4: "`ClockTick`, `SupplierAvailabilityReport`, `CurationReviewItem`,
    `ItemAttribute` and `ItemCrossReference` expose only `id` and `created_at`; they have
    no `updated_at` and no `version`".
    PRD §3.1: "Attribute rows are immutable once written: neither the name, the value nor
    the owning `item_id` may be revised later".

    Design: Corner/entities/item_attribute_is_immutable_and_carries_no_version
    """
    setup_clock(api)
    item = _create_item(api, "IM-1001")
    validate_success(api.create_item_attribute(
        item["id"], create_attribute_payload(), CURATOR), 201)
    validate_success(api.create_item_cross_reference(
        item["id"], create_cross_reference_payload(), CURATOR), 201)

    attributes, _meta = validate_paginated(api.list_item_attributes(
        item["id"], CURATOR, {"limit": 100, "offset": 0}))
    assert len(attributes) == 1
    assert attributes[0]["attribute_value"] == "1.25 mm"
    assert attributes[0]["id"] and attributes[0]["created_at"]
    assert "version" not in attributes[0]
    assert "updated_at" not in attributes[0]

    references, _meta = validate_paginated(api.list_item_cross_references(
        item["id"], CURATOR, {"limit": 100, "offset": 0}))
    assert len(references) == 1
    assert references[0]["referenced_part_number"] == "AC-2201"
    assert "version" not in references[0]
    assert "updated_at" not in references[0]


def test_an_order_line_requires_an_existing_item(api):
    """PRD §2.8: "The same left-to-right discipline governs the other parents, each with
    its own not-found code — `ERR_ITEM_NOT_FOUND` for an unresolvable `CatalogItem`".
    PRD §3.3: "Each line names an `item_id` and a `quantity` of at least 1."

    Design: Corner/entities/order_line_requires_an_existing_parent_order_and_item
    """
    setup_clock(api)
    acct = setup_account(api)
    headers = make_customer_account_headers(acct["id"])

    response = api.create_order(
        {"account_id": acct["id"],
         "lines": [{"item_id": ABSENT_ITEM, "quantity": 1}]}, headers)
    validate_error(response, ApiErrorId.ERR_ITEM_NOT_FOUND)

    orders, _meta = validate_paginated(api.list_orders(
        headers, {"account_id": acct["id"], "limit": 10, "offset": 0}))
    assert orders == [], "a line naming an unknown item created no partial order"


def test_a_supplier_availability_report_persists_under_its_supplier(api):
    """PRD §3.2: "Filing a report supplies the `item_id` of the long-tail item the report
    covers and a `reported_available_units` count of at least 0; the report is stamped with
    the `supplier_id` of the filing supplier."
    PRD §3.2: "The eligibility filter admits only suppliers that are `long_tail_authorized`
    and whose `min_stock_commitment_units` is at least the `reported_available_units` just
    filed for the item".
    PRD §2.4: "`SupplierAvailabilityReport` ... expose only `id` and `created_at`".

    Design: Corner/entities/supplier_availability_report_persists_under_its_supplier
    """
    setup_clock(api)
    dc = validate_success(api.create_distribution_center(
        create_distribution_center_payload(), ADMIN), 201)
    supplier = validate_success(api.create_supplier(
        create_supplier_payload(home_dc_id=dc["id"], min_stock_commitment_units=50), ADMIN),
        201)
    item = _create_item(api, "SR-1001", price=5500, long_tail=True)

    selected = validate_success(api.create_availability_report(
        supplier["id"], {"item_id": item["id"], "reported_available_units": 50}, ADMIN),
        201)
    assert selected["id"] == supplier["id"]

    reports, _meta = validate_paginated(api.list_supplier_availability_reports(
        supplier["id"], ADMIN, {"limit": 100, "offset": 0}))
    assert len(reports) == 1
    assert reports[0]["item_id"] == item["id"]
    assert reports[0]["reported_available_units"] == 50

    after = validate_success(api.get_supplier(supplier["id"], ADMIN))
    assert after["commitment_breach_count"] == 0
    assert after["performance_rating_units"] == 100

    by_item, _meta = validate_paginated(api.list_item_availability_reports(
        item["id"], ADMIN, {"limit": 100, "offset": 0}))
    assert len(by_item) == 1