"""Entity basics: sites, products, customers — creation defaults, computed
mirrors, system fields, not-found, and validation-priority ordering."""
from test_helpers import (
    ApiErrorId,
    assert_order,
    assert_order_money_invariants,
    assert_product,
    assert_site,
    canonical_instant,
    create_customer,
    create_product,
    create_site,
    get_success_data,
    instants_equal,
    make_customer_headers,
    make_picker_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSiteCreation:
    def test_site_create_returns_defaults_and_computed_posture(self, api, site_ops_headers):
        """PRD §3.1: "A new site starts in OPERATING with version 1."
        PRD §3.1: "an empty list means the site never peaks"

        Design: Corner/entities/site_create_returns_defaults_and_computed_posture
        """
        resp = api.create_site(
            {
                "code": "SITE-Z",
                "name": "Zed MFC",
                "delivery_radius_miles": 3.0,
                "fee_schedule": {
                    "base_cents": 199,
                    "per_mile_cents": 99,
                    "included_miles": 1,
                    "peak_surcharge_cents": 150,
                    "min_fee_cents": 99,
                    "max_fee_cents": 999,
                },
                "fee_waiver_threshold_cents": 3000,
                "batch_max_lines": 2,
                "batch_max_items": 20,
                "expiry_horizon_days": 2,
            },
            site_ops_headers,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["response_type"] == "object"
        assert "api_request_id" in body["meta"] and "api_request_timestamp" in body["meta"]
        site = body["data"]
        assert_site(site)
        assert site["status"] == "OPERATING", site
        assert site["effective_status"] == "OPERATING", site
        assert site["peak_windows"] == [], site
        assert site["version"] == 1, site

    def test_site_create_missing_fee_schedule_returns_invalid_request(self, api, site_ops_headers):
        """PRD §3.1: "A SiteOps operator onboards a micro-fulfillment site by
        creating a Site with a human-readable code (unique across all sites), a
        display name, and the operating parameters that every downstream rule
        depends on: delivery_radius_miles ... the fee_schedule object ..."

        Design: Corner/entities/site_create_missing_fee_schedule_returns_invalid_request
        """
        resp = api.create_site(
            {
                "code": "SITE-N",
                "name": "NoFee MFC",
                "delivery_radius_miles": 3.0,
                "fee_waiver_threshold_cents": 3000,
                "batch_max_lines": 2,
                "batch_max_items": 20,
                "expiry_horizon_days": 2,
            },
            site_ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        rows, _ = validate_paginated(api.list_sites(site_ops_headers))
        assert rows == [], f"no site may persist after a rejected creation: {rows}"


class TestClock:
    def test_clock_set_returns_new_instant(self, api, site_ops_headers):
        """PRD §2.4: "it changes only when a SiteOps operator sets it through
        the test-driving clock endpoint by supplying a current_utc instant."

        Design: Corner/endpoints/clock_set_returns_new_instant_and_defaults_at_startup
        """
        resp = api.set_clock({"current_utc": "2026-12-25T00:00:00Z"}, site_ops_headers)
        data = validate_success(resp)
        assert instants_equal(
            data["current_utc"], "2026-12-25T00:00:00Z"
        ), f"set_current_utc must echo the new instant: {data}"

    def test_clock_startup_default_is_2026_09_01(self, api, site_ops_headers):
        """PRD §2.4: "At server startup the logical clock reads exactly
        2026-09-01T00:00:00Z; it never falls back to wall-clock time, and it
        changes only when a SiteOps operator sets it through the test-driving
        clock endpoint by supplying a current_utc instant."

        The fresh server's clock is observed through the pre-screen rule of
        PRD §3.6: "if the order contains_age_restricted, the customer's age at
        the logical clock must be at least 21 ... otherwise the append is
        rejected with ERR_AGE_VERIFICATION_REQUIRED". A customer born
        2005-09-02 is 20 at the pinned startup instant (21st birthday tomorrow)
        but 21 under any wall-clock time in 2026-09-29 or later, so only the
        pinned startup default produces the rejection.

        Design: Corner/endpoints/clock_set_returns_new_instant_and_defaults_at_startup
        """
        site = create_site()
        product = create_product(product_class="AGE_RESTRICTED")
        from test_helpers import create_balance, create_picker, open_batch, seed_on_hand

        balance = create_balance(site["id"], product["id"])
        seed_on_hand(balance["id"], 10)
        customer = create_customer(date_of_birth="2005-09-02T00:00:00Z")
        picker = create_picker(site["id"], name="Pat Picker")
        order_resp = api.create_order(
            {
                "customer_id": customer["id"],
                "site_id": site["id"],
                "lines": [{"product_id": product["id"], "qty": 1}],
                "delivery_distance_miles": 1.0,
            },
            make_customer_headers(customer["id"]),
        )
        order = validate_success(order_resp, expected_status=201)
        batch = open_batch(site["id"], picker["id"])
        append = api.append_order_to_batch(
            batch["id"], {"order_id": order["id"]}, make_picker_headers(picker["id"])
        )
        validate_error(append, ApiErrorId.ERR_AGE_VERIFICATION_REQUIRED)


class TestCustomerRetrieval:
    def test_customer_get_returns_stored_row_and_zero_wallet(self, api, site_ops_headers):
        """PRD §3.4: "A new customer starts ACTIVE with a wallet_credit_cents
        balance of 0."

        Design: Corner/entities/customer_get_returns_stored_row_and_zero_wallet
        """
        customer = create_customer(
            email="ronda@example.com",
            full_name="Ronda Retrieval",
            date_of_birth="1995-03-03T00:00:00Z",
        )
        resp = api.get_customer(customer["id"], make_customer_headers(customer["id"]))
        assert resp.status_code == 200, resp.text
        data = validate_success(resp)
        assert data["email"] == "ronda@example.com"
        assert data["wallet_credit_cents"] == 0
        assert data["status"] == "ACTIVE"


class TestProducts:
    def test_product_get_with_unknown_id_returns_product_not_found(self, api, site_ops_headers):
        """PRD §2.6: "each missing identifier produces the corresponding
        not-found error — ERR_SITE_NOT_FOUND, ERR_PRODUCT_NOT_FOUND ..."

        Design: Corner/entities/product_get_with_unknown_id_returns_product_not_found
        """
        resp = api.get_product("00000000-0000-4000-8000-000000000000", site_ops_headers)
        err = validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND)
        assert "error_id" in err and "message" in err

    def test_product_create_with_out_of_enum_class_returns_invalid_request(self, api, site_ops_headers):
        """PRD §3.1: "a product_class of STANDARD, AGE_RESTRICTED, or
        PERISHABLE."

        Design: Corner/entities/product_create_with_out_of_enum_class_returns_invalid_request
        """
        resp = api.create_product(
            {"sku": "SKU-X", "name": "Mystery", "price_cents": 100, "product_class": "HAZMAT"},
            site_ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        rows, _ = validate_paginated(api.list_products(site_ops_headers))
        assert rows == [], f"no product may persist after a rejected creation: {rows}"

    def test_product_restricted_and_perishable_flags_computed_from_class_input_ignored(
        self, api, site_ops_headers
    ):
        """PRD §3.1: "Two read-only mirrors are derived from the class:
        restricted is true exactly when the class is AGE_RESTRICTED, and
        perishable is true exactly when the class is PERISHABLE."

        Design: Corner/entities/product_restricted_and_perishable_flags_computed_from_class_input_ignored
        """
        resp = api.create_product(
            {
                "sku": "SKU-VODKA",
                "name": "Vodka",
                "price_cents": 1500,
                "product_class": "AGE_RESTRICTED",
                "restricted": False,
                "perishable": True,
            },
            site_ops_headers,
        )
        assert resp.status_code == 201, resp.text
        product = validate_success(resp, expected_status=201)
        assert_product(product)
        assert product["restricted"] is True, product
        assert product["perishable"] is False, product

    def test_duplicate_sku_rejected(self, api, site_ops_headers):
        """PRD §3.1: "A SiteOps operator creates a Product with a sku (unique
        across the catalog)"

        Design: Corner/validations/duplicate_sku_rejected
        """
        create_product(sku="SKU-DUP", name="First", price_cents=100, product_class="STANDARD")
        resp = api.create_product(
            {"sku": "SKU-DUP", "name": "Second", "price_cents": 200, "product_class": "PERISHABLE"},
            site_ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE)
        rows, _ = validate_paginated(api.list_products(site_ops_headers))
        assert len(rows) == 1, f"the duplicate sku must not persist a second product: {rows}"

    def test_retired_product_cannot_be_placed(self, api, site_ops_headers):
        """PRD §3.1: "A RETIRED product is unpickable: order placement for a
        non-ACTIVE product fails with ERR_PRODUCT_UNSELLABLE."

        Design: Corner/validations/retired_product_cannot_be_placed
        """
        from test_helpers import set_clock

        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        product = create_product(sku="SKU-OLD", name="Old Stock", price_cents=100)
        resp = api.retire_product(product["id"], site_ops_headers)
        assert resp.status_code == 200, resp.text
        customer = create_customer()
        order_resp = api.create_order(
            {
                "customer_id": customer["id"],
                "site_id": site["id"],
                "lines": [{"product_id": product["id"], "qty": 1}],
                "delivery_distance_miles": 1.0,
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(order_resp, ApiErrorId.ERR_PRODUCT_UNSELLABLE)
        reread = validate_success(api.get_product(product["id"], site_ops_headers))
        assert reread["status"] == "RETIRED", "retirement is not deletion"


class TestOrderPlacementBasics:
    def test_order_client_supplied_status_and_totals_input_ignored(self, api, site_ops_headers):
        """PRD §3.5: "The server then computes the order's money fields in a
        pinned order and creates the order in PLACED with pick_batch_id null."

        Design: Corner/entities/order_client_supplied_status_and_totals_input_ignored
        """
        from test_helpers import set_clock

        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        product = create_product(price_cents=500)
        customer = create_customer()
        resp = api.create_order(
            {
                "customer_id": customer["id"],
                "site_id": site["id"],
                "lines": [{"product_id": product["id"], "qty": 2}],
                "delivery_distance_miles": 1.0,
                "status": "DELIVERED",
                "subtotal_cents": 1,
                "total_cents": 1,
            },
            make_customer_headers(customer["id"]),
        )
        assert resp.status_code == 201, resp.text
        order = validate_success(resp, expected_status=201)
        assert_order(order)
        assert order["status"] == "PLACED", order
        assert order["subtotal_cents"] == 1000, order
        assert order["total_cents"] == 1199, order
        assert_order_money_invariants(order)

    def test_order_body_foreign_keys_checked_in_declared_input_order(self, api, site_ops_headers):
        """PRD §2.6: "Body foreign-key fields are then validated in the order
        they are declared in the endpoint's input contract."

        Design: Corner/entities/order_body_foreign_keys_checked_in_declared_input_order
        """
        unknown_customer = "00000000-0000-4000-8000-000000000001"
        unknown_site = "00000000-0000-4000-8000-000000000002"
        unknown_product = "00000000-0000-4000-8000-000000000003"
        both = api.create_order(
            {
                "customer_id": unknown_customer,
                "site_id": unknown_site,
                "lines": [{"product_id": unknown_product, "qty": 1}],
                "delivery_distance_miles": 1.0,
            },
            make_customer_headers(unknown_customer),
        )
        validate_error(both, ApiErrorId.ERR_CUSTOMER_NOT_FOUND)
        customer = create_customer(email="solo@example.com", full_name="Solo Check")
        only_site = api.create_order(
            {
                "customer_id": customer["id"],
                "site_id": unknown_site,
                "lines": [{"product_id": unknown_product, "qty": 1}],
                "delivery_distance_miles": 1.0,
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(only_site, ApiErrorId.ERR_SITE_NOT_FOUND)

    def test_placement_response_reflects_all_computed_fields_immediately(self, api, site_ops_headers):
        """PRD §3.5: "the order's total_cents is the subtotal plus tax plus the
        delivery fee minus the applied loyalty credit."
        PRD §3.5: "each taxed line's amount — quantity multiplied by unit price
        multiplied by the 7 percent rate — is rounded half-up to integer cents
        individually, and the rounded line amounts are summed into tax_cents."

        Design: Corner/consistency_model/placement_response_reflects_all_computed_fields_immediately
        """
        from test_helpers import set_clock, wallet_adjust

        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        chips = create_product(sku="SKU-CHIPS", price_cents=500, product_class="STANDARD")
        beer = create_product(sku="SKU-BEER-A", name="Lager 6-pack", price_cents=999,
                              product_class="AGE_RESTRICTED")
        customer = create_customer()
        wallet_adjust(customer["id"], 100, reason="seed")
        resp = api.create_order(
            {
                "customer_id": customer["id"],
                "site_id": site["id"],
                "lines": [
                    {"product_id": chips["id"], "qty": 1},
                    {"product_id": beer["id"], "qty": 1},
                ],
                "delivery_distance_miles": 1.0,
            },
            make_customer_headers(customer["id"]),
        )
        assert resp.status_code == 201, resp.text
        order = validate_success(resp, expected_status=201)
        assert order["subtotal_cents"] == 1499, order
        assert order["tax_cents"] == 70, f"round_half_up(999 * 0.07) == 70: {order}"
        assert order["delivery_fee_cents"] == 199, order
        assert order["loyalty_credit_applied_cents"] == 100, order
        assert order["total_cents"] == 1668, order
        reread = validate_success(api.get_order(order["id"], site_ops_headers))
        for field in ("subtotal_cents", "tax_cents", "delivery_fee_cents",
                      "loyalty_credit_applied_cents", "total_cents"):
            assert reread[field] == order[field], f"{field} drifted: {reread[field]} != {order[field]}"

    def test_orders_list_paginates_with_total_count_and_has_more(self, api, site_ops_headers):
        """PRD §2.3: "The meta object of a list response always carries the
        four pagination fields limit, offset, total_count, and has_more."
        PRD §2.3: "it defaults to 10, accepts a minimum of 1, and rejects
        values above 100. The offset parameter specifies how many items to
        skip and defaults to 0."

        Design: Corner/entities/orders_list_paginates_with_total_count_and_has_more
        """
        from test_helpers import place_order, set_clock

        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        product = create_product()
        customer = create_customer()
        for _ in range(3):
            place_order(customer["id"], site["id"], [{"product_id": product["id"], "qty": 1}])

        page1, meta1 = validate_paginated(
            api.list_orders(site_ops_headers, params={"customer_id": customer["id"], "limit": 2, "offset": 0})
        )
        assert len(page1) == 2 and meta1["total_count"] == 3 and meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api.list_orders(site_ops_headers, params={"customer_id": customer["id"], "limit": 2, "offset": 2})
        )
        assert len(page2) == 1 and meta2["total_count"] == 3 and meta2["has_more"] is False
        default_rows, default_meta = validate_paginated(api.list_orders(site_ops_headers))
        assert len(default_rows) == 3
        assert default_meta["limit"] == 10 and default_meta["offset"] == 0


class TestPickerDefaults:
    def test_picker_create_defaults_status_active(self, api, site_ops_headers):
        """PRD §3.7: "pickers are rostered similarly with a `status` of
        `ACTIVE` or `INACTIVE`.""
        PRD §3.6: "Only ACTIVE pickers may own batches."

        A picker rostered without an explicit status reads back ACTIVE and may
        own a batch.

        Design: Corner/entities/picker_create_defaults_status_active
        """
        site = validate_success(api.create_site(
            {"code": "SITE-PD", "name": "Defaults MFC", "delivery_radius_miles": 5.0,
             "fee_schedule": {"base_cents": 199, "per_mile_cents": 99, "included_miles": 1,
                              "peak_surcharge_cents": 150, "min_fee_cents": 99, "max_fee_cents": 999},
             "fee_waiver_threshold_cents": 3000, "batch_max_lines": 2, "batch_max_items": 20,
             "expiry_horizon_days": 2},
            site_ops_headers,
        ), expected_status=201)
        picker = validate_success(
            api.create_picker({"site_id": site["id"], "name": "Default Dan"}, site_ops_headers),
            expected_status=201,
        )
        assert picker["status"] == "ACTIVE"
        batch = validate_success(
            api.create_pick_batch({"site_id": site["id"], "picker_id": picker["id"]}, site_ops_headers),
            expected_status=201,
        )
        assert batch["status"] == "OPEN"
        assert batch["picker_id"] == picker["id"]
