"""Entity creation, defaults, and domain constraint tests (PRD §3.1, §3.3, §3.4, §3.6)."""
from test_helpers import (
    ApiErrorId,
    assert_item,
    create_customer_payload,
    create_item_payload,
    create_membership_payload,
    create_sale_payload,
    create_store_payload,
    create_warranty_line_payload,
    get_success_data,
    make_customer,
    make_store,
    create_active_item,
    add_line,
    make_open_sale,
    validate_error,
    validate_paginated,
    validate_success,
    NON_EXISTENT_UUID,
)


class TestItemCreation:

    def test_item_creation_required_fields_and_defaults(
            self, api, purchasing_manager_headers):
        """PRD §3.1: "A newly created item starts with `lifecycle_status` in
        `DRAFT`, an `open_recall_count` of zero, a `warranty_claim_rate` of
        zero, and `current_landed_unit_cost_cents` null until the first receipt
        of a container carrying the item establishes a landed cost."

        Design: Corner/entities/item_creation_required_fields_and_defaults
        """
        payload = create_item_payload(
            sku="E1", name="Hammer", unit_retail_cents=1200,
            member_price_cents=1100, floor_margin_pct=0.05,
            lead_time_days=30, unit_weight_kg=1.0)
        item = validate_success(
            api.create_item(payload, purchasing_manager_headers),
            expected_status=201)
        assert_item(item)
        assert item["lifecycle_status"] == "DRAFT"
        assert item["open_recall_count"] == 0
        assert item["current_landed_unit_cost_cents"] is None
        assert item["version"] == 1

        fetched = validate_success(
            api.get_item(item["id"], purchasing_manager_headers))
        assert fetched["lifecycle_status"] == "DRAFT"
        assert fetched["open_recall_count"] == 0

    def test_item_member_price_above_retail_rejected(
            self, api, purchasing_manager_headers):
        """PRD §3.1: "a `member_price_cents` that must be greater than zero and
        must not exceed `unit_retail_cents`"

        Design: Corner/entities/item_member_price_above_retail_rejected
        """
        payload = create_item_payload(
            sku="E2", name="Bad", unit_retail_cents=1000,
            member_price_cents=1500, floor_margin_pct=0.05,
            lead_time_days=30, unit_weight_kg=1.0)
        resp = api.create_item(payload, purchasing_manager_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_item_get_not_found(self, api, purchasing_manager_headers):
        """PRD §2.6: "the first identifier in the URL hierarchy that does not
        correspond to an existing resource produces `ERR_NOT_FOUND` (HTTP 404)"

        Design: Corner/entities/item_get_not_found
        """
        resp = api.get_item(NON_EXISTENT_UUID, purchasing_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_item_create_duplicate_sku_rejected(self, api, purchasing_manager_headers):
        """PRD §3.1: "Duplicate SKU codes are rejected with `ERR_VALIDATION`."

        Design: Corner/entities/item_creation_required_fields_and_defaults
        """
        payload = create_item_payload(sku="DUP-1")
        validate_success(api.create_item(payload, purchasing_manager_headers),
                         expected_status=201)
        resp = api.create_item(payload, purchasing_manager_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestStoreAssortmentCap:

    def test_small_format_assortment_cap_exceeded_rejected(
            self, api, ops_admin_headers, purchasing_manager_headers):
        """PRD §3.3: "a `SMALL_FORMAT` store's assortment may contain at most 8
        entries (duplicates counted); exceeding that cap is rejected with
        `ERR_VALIDATION`."

        Design: Corner/entities/small_format_assortment_cap
        """
        item = get_success_data(api.create_item(
            create_item_payload(sku="E3", name="Nail", unit_retail_cents=100,
                                member_price_cents=100, floor_margin_pct=0.01,
                                lead_time_days=15, unit_weight_kg=0.01),
            purchasing_manager_headers))
        payload = create_store_payload(
            [item["id"]] * 9, store_code="ST-SF", name="Small",
            format="SMALL_FORMAT", market_tier="SECONDARY",
            receiving_capacity_units=100)
        resp = api.create_store(payload, ops_admin_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestMembershipUniqueness:

    def test_membership_unique_per_customer(self, api, store_clerk_headers):
        """PRD §3.4: "creates at most one Membership per customer; a second
        enrollment attempt is rejected with `ERR_MEMBERSHIP_EXISTS`."

        Design: Corner/entities/membership_unique_per_customer
        """
        cust = make_customer(email="e5@x.com")
        validate_success(api.create_membership(
            cust["id"], create_membership_payload("CLUB"), store_clerk_headers),
            expected_status=201)
        resp = api.create_membership(
            cust["id"], create_membership_payload("CLUB_PLUS"),
            store_clerk_headers)
        validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_EXISTS)


class TestWarrantyLineReferences:

    def test_warranty_line_requires_covered_item_on_same_sale(
            self, api, purchasing_manager_headers, store_clerk_headers):
        """PRD §3.6: "must name a `covered_item_id` that is the item of another
        line on the same sale — a covered item not present as a merchandise
        line on the sale is rejected with `ERR_INVALID_REFERENCE`"

        Design: Corner/entities/warranty_line_requires_covered_item_on_same_sale
        """
        i1 = create_active_item(sku="E6A", unit_retail_cents=5000,
                                member_price_cents=4500)
        i2 = create_active_item(sku="E6B", unit_retail_cents=7000,
                                member_price_cents=6500)
        store = make_store([i1["id"], i2["id"]], store_code="ST-E6")
        cust = make_customer(email="e6@x.com")
        sale = make_open_sale(store["id"], cust["id"])
        add_line(sale["id"], i1["id"], 1)
        resp = api.add_sale_line(
            sale["id"],
            create_warranty_line_payload(i1["id"], i2["id"], 900),
            store_clerk_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REFERENCE)


class TestContainerLineReferences:

    def test_container_line_item_must_be_on_po(
            self, api, purchasing_manager_headers, logistics_coordinator_headers):
        """PRD §3.2: "`lines` whose every item already appears on the PO (a
        container line item not on the PO is rejected with
        `ERR_INVALID_REFERENCE`)"

        Design: Corner/entities/container_line_item_must_be_on_po
        """
        from test_helpers import (create_container_payload,
                                  create_purchase_order_payload)
        ia = create_active_item(sku="E7A", unit_retail_cents=1000,
                                member_price_cents=1000)
        ib = create_active_item(sku="E7B", unit_retail_cents=1000,
                                member_price_cents=1000)
        po = get_success_data(api.create_purchase_order(
            create_purchase_order_payload(ia["id"], 2, 500, po_number="PO-E7"),
            purchasing_manager_headers))
        get_success_data(api.issue_purchase_order(po["id"], purchasing_manager_headers))
        resp = api.create_container(
            create_container_payload(po["id"], ib["id"], 1,
                                     container_number="C-E7"),
            logistics_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REFERENCE)


class TestItemsListPagination:

    def test_items_list_pagination_envelope(self, api, purchasing_manager_headers):
        """PRD §2.3: "List responses include `limit`, `offset`, `total_count`,
        and `has_more` in the response envelope's `meta` object."

        Design: Corner/endpoints/items_list_pagination_envelope
        """
        for sku in ("PG1", "PG2", "PG3"):
            get_success_data(api.create_item(
                create_item_payload(sku=sku, unit_retail_cents=1000,
                                    member_price_cents=1000,
                                    floor_margin_pct=0.01),
                purchasing_manager_headers))
        resp = api.list_items(purchasing_manager_headers,
                              params={"limit": 2, "offset": 1})
        data, meta = validate_paginated(resp)
        assert len(data) == 2, f"Expected 2 rows, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
