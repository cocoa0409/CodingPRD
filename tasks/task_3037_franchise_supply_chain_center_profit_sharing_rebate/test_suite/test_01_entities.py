"""Entity-level claims: creation shape, retrieval round-trip, listing pagination,
not-found errors, required fields, defaults, computed fields, type constraints,
and parent relationships."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_line,
    create_center,
    create_draft_po,
    create_price_book,
    create_product,
    create_store,
    create_supply_center_payload,
    get_success_data,
    get_store_version,
    is_valid_uuid,
    set_clock,
    setup_trading_store,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)
from test_helpers.test_users import TEST_USERS, make_store_manager_headers

ADMIN = TEST_USERS["admin_headers"]
ANY = TEST_USERS["any_headers"]
COORD = TEST_USERS["coordinator_headers"]


class TestSupplyCenterCreation:
    def test_create_returns_all_declared_fields(self, api):
        """PRD §3.1: "A new center is born in `DRAFT` status with `posture` of `ACTIVE`,
        an `ops_run_index` of zero, and both `rebate_pool_balance_cents` and
        `rebate_pool_locked_cents` at zero."
        PRD §3.1: "an optional `surge_capacity_multiplier` that defaults to 1.0,
        meaning no surge."

        Design: Corner/entities/supply_center_create_returns_all_declared_fields
        """
        set_clock()
        resp = api.create_supply_center(create_supply_center_payload(
            center_code="SC-001", display_name="Midwest Supply Center",
            base_weekly_capacity_units=50000), ADMIN)
        data = validate_success(resp, expected_status=201)
        assert is_valid_uuid(data["id"])
        assert data["center_code"] == "SC-001"
        assert data["display_name"] == "Midwest Supply Center"
        assert data["base_weekly_capacity_units"] == 50000
        assert data["surge_capacity_multiplier"] == 1.0
        assert data["status"] == "DRAFT"
        assert data["posture"] == "ACTIVE"
        assert data["ops_run_index"] == 0
        assert data["rebate_pool_balance_cents"] == 0
        assert data["rebate_pool_locked_cents"] == 0
        assert data["version"] == 1


class TestStoreRetrieval:
    def test_get_returns_stored_configuration_unchanged(self, api):
        """PRD §3.2: "Stores join a center in `ONBOARDING` status, created with a
        `store_number` unique within the center and immutable, the franchisee's legal
        `operator_name`, and a `credit_limit_cents` ceiling on unpaid invoiced amounts.
        A new store starts with `compliance_tier` of `FULL_COMPLIANCE`,
        `rebate_eligibility_status` of `ELIGIBLE`, an `exclusive_purchase_pct` of 0,
        and an `outstanding_balance_cents` of 0."

        Design: Corner/entities/store_get_returns_stored_configuration_unchanged
        """
        set_clock()
        center = create_center()
        store = create_store(center["id"], store_number="ST-200",
                             operator_name="Beta Franchise Inc",
                             credit_limit_cents=500000)
        data = validate_success(api.get_store(center["id"], store["id"], ANY))
        assert data["store_number"] == "ST-200"
        assert data["operator_name"] == "Beta Franchise Inc"
        assert data["credit_limit_cents"] == 500000
        assert data["status"] == "ONBOARDING"
        assert data["compliance_tier"] == "FULL_COMPLIANCE"
        assert data["rebate_eligibility_status"] == "ELIGIBLE"
        assert data["outstanding_balance_cents"] == 0


class TestProductListing:
    def test_products_list_paginates_with_limit_offset(self, api):
        """PRD §2.3: "The `meta` object of list responses carries the pagination fields
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/products_list_paginates_with_limit_offset
        """
        set_clock()
        center = create_center()
        for i, (sku, cat, cost) in enumerate(
                [("P1", "DOUGH", 100), ("P2", "FOOD_INGREDIENT", 200), ("P3", "EQUIPMENT", 300)]):
            create_product(center["id"], sku=sku, name=f"Product {i+1}",
                           category=cat, base_cost_cents_per_unit=cost)
        rows, meta = validate_paginated(
            api.list_products(center["id"], ANY, params={"limit": 2, "offset": 0}))
        assert len(rows) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        rows2, meta2 = validate_paginated(
            api.list_products(center["id"], ANY, params={"limit": 2, "offset": 2}))
        assert len(rows2) == 1
        assert meta2["has_more"] is False


class TestNotFound:
    def test_product_get_with_unknown_id_returns_not_found(self, api):
        """PRD §2.6: "every resource identifier in the path must exist within its parent
        scope, else the matching not-found error: `ERR_CENTER_NOT_FOUND`,
        `ERR_STORE_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND` ..."

        Design: Corner/entities/product_get_with_unknown_id_returns_not_found
        """
        set_clock()
        center = create_center()
        resp = api.get_product(center["id"], "00000000-0000-4000-8000-000000000000", ANY)
        err = validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND)
        assert resp.status_code == 404
        assert err["error_id"] == "ERR_PRODUCT_NOT_FOUND"


class TestRequiredFields:
    def test_store_create_missing_credit_limit_returns_invalid_request(self, api):
        """PRD §2.6: "Malformed request bodies, missing required fields, invalid
        enumeration values, and other constraint violations that do not match a more
        specific rule are rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/store_create_missing_credit_limit_returns_invalid_request
        """
        set_clock()
        center = create_center()
        resp = api.create_store(center["id"],
                                {"store_number": "ST-NOCL", "operator_name": "No Credit Limit"},
                                ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400


class TestDefaults:
    def test_product_shelf_life_defaults_to_null_for_non_perishables(self, api):
        """PRD §3.1: "Perishable products carry a `shelf_life_days`; for non-perishables
        that field is null. A product that participates in national promotions is flagged
        with `is_promotion_eligible`, which defaults to false."

        Design: Corner/entities/product_shelf_life_defaults_to_null_for_non_perishables
        """
        set_clock()
        center = create_center()
        data = validate_success(api.create_product(
            center["id"],
            {"sku": "OVEN-01", "name": "Pizza Oven", "category": "EQUIPMENT",
             "base_cost_cents_per_unit": 500000},
            ADMIN), expected_status=201)
        assert data["shelf_life_days"] is None
        assert data["is_promotion_eligible"] is False


class TestComputedFields:
    def test_purchase_order_totals_are_computed_not_input(self, api):
        """PRD §3.4: "The `subtotal_cents` is the sum of `extended_price_cents` over all
        `PENDING` and `CONFIRMED` lines. The `markup_cents` is the subtotal minus the sum
        of each line's base cost times quantity — the supply chain's gross margin on the
        order. ... The `total_cents` is subtotal plus markup plus delivery fee."

        Design: Corner/entities/purchase_order_totals_are_computed_not_input
        """
        center, product, store = setup_trading_store(base_cost=1000, markup=0.15,
                                                     credit_limit=1000000)
        center_id, store_id = center["id"], store["id"]
        po = create_draft_po(center_id, store_id)
        add_line(center_id, store_id, po["id"], product["id"], 10)
        version = get_store_version(center_id, store_id)
        data = validate_success(api.submit_purchase_order(
            center_id, store_id, po["id"], version, make_store_manager_headers(store_id)))
        # 10 * floor(1000 * 1.15) = 11500; markup = 11500 - 10000 = 1500
        assert data["subtotal_cents"] == 11500
        assert data["markup_cents"] == 1500
        assert data["delivery_fee_cents"] == 0
        # PRD §3.4: "The `total_cents` is subtotal plus markup plus delivery fee."
        assert data["total_cents"] == 11500 + 1500 + 0

    def test_order_line_unit_price_is_computed_at_creation(self, api):
        """PRD §3.4: "the unit price is the product's `base_cost_cents_per_unit`
        multiplied by one plus that entry's `markup_pct`, with the fractional cent
        rounded down. The line's `extended_price_cents` is the unit price times the
        quantity"

        Design: Corner/entities/order_line_unit_price_is_computed_at_creation
        """
        center, product, store = setup_trading_store(base_cost=1000, markup=0.15,
                                                     credit_limit=1000000)
        po = create_draft_po(center["id"], store["id"])
        data = validate_success(api.add_order_line(
            center["id"], store["id"], po["id"],
            {"product_id": product["id"], "quantity": 5},
            make_store_manager_headers(store["id"])), expected_status=201)
        assert data["unit_price_cents"] == 1150
        assert data["extended_price_cents"] == 5750


class TestTypeConstraints:
    def test_route_code_enum_rejects_invalid_day(self, api):
        """PRD §3.6: "A route is created with a `route_code`, a `day_of_week` (`MONDAY`
        through `SUNDAY`)"
        PRD §2.6: "Malformed request bodies, missing required fields, invalid enumeration
        values, and other constraint violations that do not match a more specific rule
        are rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/route_code_enum_rejects_invalid_day
        """
        set_clock()
        center = create_center()
        resp = api.create_route(center["id"], {
            "route_code": "R1", "day_of_week": "FUNDAY",
            "truck_capacity_units": 1000, "assigned_store_ids": []}, COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400

    def test_store_number_unique_per_center(self, api):
        """PRD §3.2: "created with a `store_number` unique within the center and
        immutable"
        PRD §2.6: "Malformed request bodies, missing required fields, invalid enumeration
        values, and other constraint violations that do not match a more specific rule
        are rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/store_number_unique_per_center
        """
        set_clock()
        center = create_center()
        create_store(center["id"], store_number="ST-DUP", operator_name="First",
                     credit_limit_cents=100000)
        resp = api.create_store(center["id"],
                                {"store_number": "ST-DUP", "operator_name": "Second",
                                 "credit_limit_cents": 200000}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400


class TestParentRelationships:
    def test_purchase_order_fk_to_store_and_center(self, api):
        """PRD §2.6: "every resource identifier in the path must exist within its parent
        scope, else the matching not-found error ... `ERR_STORE_NOT_FOUND`"

        Design: Corner/entities/purchase_order_fk_to_store_and_center
        """
        set_clock()
        center_a = create_center(center_code="SC-A")
        center_b = create_center(center_code="SC-B")
        store_a = create_store(center_a["id"], store_number="ST-A1",
                               operator_name="A1", credit_limit_cents=100000)
        # Store belongs to center A; referencing it under center B must 404.
        resp = api.create_purchase_order(
            center_b["id"], store_a["id"], {"week_start_date": "2026-09-07T00:00:00Z"},
            make_store_manager_headers(store_a["id"]))
        validate_error(resp, ApiErrorId.ERR_STORE_NOT_FOUND)
        assert resp.status_code == 404
