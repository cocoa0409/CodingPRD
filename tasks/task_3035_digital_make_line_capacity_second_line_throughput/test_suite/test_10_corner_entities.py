"""Breadth coverage of the declared resources: creation defaults, retrieval, listing,
required fields, defaults, computed fields, system fields, types and parenting."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    assert_cents,
    assert_created_equals_updated,
    assert_instant,
    assert_list_page,
    factories as f,
    fixtures,
)


class TestStoreCreateReturnsDefaultsAndComputedFields:
    def test_new_store_starts_open_with_zeroed_counters(self, api):
        """A freshly provisioned store reports the declared defaults.

        PRD §3.1: "A new store starts with `throttle_state` `OPEN`, both interval loads at zero, `theoretical_food_cost_cents` and `actual_food_cost_cents` at zero, `food_cost_variance_bps` at zero, and `current_business_day` set to the logical clock's date."
        PRD §3.1: "An optional `forecast_day_cents` seeds the day's revenue forecast and defaults to zero."
        Design: Corner/entities/store_create_returns_defaults_and_computed_fields
        """
        fixtures.set_clock(api, fixtures.MORNING)
        store = fixtures.create_store(
            api,
            store_code="SC",
            name="Corner Store",
            digital_line_capacity_per_interval=10,
            instore_line_capacity_per_interval=8,
            pacing_interval_minutes=15,
            overage_threshold_pct=0.8,
            marketplace_commission_pct=0.22,
        )
        assert store["throttle_state"] == "OPEN"
        assert store["digital_interval_load"] == 0
        assert store["instore_interval_load"] == 0
        assert store["forecast_day_cents"] == 0
        assert store["theoretical_food_cost_cents"] == 0
        assert store["actual_food_cost_cents"] == 0
        assert store["current_business_day"] == "2026-09-01"
        assert_created_equals_updated(store, "store")


class TestStoreGetByIdRoundTrips:
    def test_get_returns_the_stored_pacing_configuration(self, api):
        """GET /stores/{id} returns the exact configuration the create supplied.

        PRD §3.1: "A `PlatformAdmin` onboards a store by supplying its `store_code` (a human-readable code unique per tenant), a display `name`, and the pacing configuration: `digital_line_capacity_per_interval` and `instore_line_capacity_per_interval` (the maximum entrees each make-line can assemble in one pacing window), `pacing_interval_minutes` (the length of one window), the `overage_threshold_pct` fraction of digital capacity at which throttling engages, and `marketplace_commission_pct`, the fraction of marketplace gross the store expects to pay in commission."
        Design: Corner/entities/store_get_by_id_round_trips
        """
        fixtures.set_clock(api, fixtures.MORNING)
        store = fixtures.create_store(
            api,
            store_code="SG",
            name="Get Store",
            digital_line_capacity_per_interval=12,
            instore_line_capacity_per_interval=9,
            pacing_interval_minutes=20,
            overage_threshold_pct=0.75,
            marketplace_commission_pct=0.25,
        )
        read = fixtures.read_store(api, store["id"])
        assert read["pacing_interval_minutes"] == 20
        assert read["overage_threshold_pct"] == 0.75
        assert read["digital_line_capacity_per_interval"] == 12
        assert read["instore_line_capacity_per_interval"] == 9
        assert read["store_code"] == "SG"


class TestStoresListPaginates:
    def test_limit_and_offset_page_through_the_collection(self, api):
        """With three stores, limit=2 pages 2 then 1 with the declared meta fields.

        PRD §2.3: "List endpoints accept two query parameters: `limit`, the maximum number of items to return, which defaults to 10 with a minimum of 1 and a maximum of 100; and `offset`, the number of items to skip, which defaults to 0. Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope."
        Design: Corner/entities/stores_list_paginates
        """
        fixtures.set_clock(api, fixtures.MORNING)
        for code in ("L1", "L2", "L3"):
            fixtures.create_store(
                api,
                store_code=code,
                name=f"Store {code}",
                digital_line_capacity_per_interval=5,
                instore_line_capacity_per_interval=5,
                pacing_interval_minutes=15,
                overage_threshold_pct=0.8,
                marketplace_commission_pct=0.2,
            )
        page1, meta1 = validate_paginated(
            api.list_stores(fixtures.GENERAL_MANAGER_HEADERS, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert_list_page(meta1, 2, 0, 3, True)

        page2, meta2 = validate_paginated(
            api.list_stores(fixtures.GENERAL_MANAGER_HEADERS, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert_list_page(meta2, 2, 2, 3, False)


class TestStoreGetUnknownIdReturns404:
    def test_unallocated_store_id_returns_entity_specific_404(self, api):
        """An unknown storeId yields ERR_STORE_NOT_FOUND, not a generic error.

        PRD §2.7: "When a path contains multiple resource identifiers (for example, a store followed by an order), the server resolves each identifier in order and rejects the request immediately with the 404 error corresponding to the first identifier that does not resolve — `ERR_STORE_NOT_FOUND` for a store segment, then `ERR_ORDER_NOT_FOUND`, `ERR_MENU_ITEM_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_DEPLOYMENT_NOT_FOUND`, `ERR_SUPPRESSION_EVENT_NOT_FOUND`, `ERR_CHANNEL_NOT_FOUND`, or `ERR_INGREDIENT_NOT_FOUND` as appropriate — before any business rule is evaluated."
        Design: Corner/entities/store_get_unknown_id_returns_404
        """
        fixtures.set_clock(api, fixtures.MORNING)
        response = api.get_store(NON_EXISTENT_UUID, fixtures.STORE_MANAGER_HEADERS)
        validate_error(response, ApiErrorId.STORE_NOT_FOUND.value)
        body = response.json()
        assert body["response_type"] == "error"
        assert "message" in body["data"]


class TestIngredientCreateMissingRequiredField:
    def test_omitting_par_level_grams_is_rejected_400(self, api):
        """par_level_grams is a required input; omitting it is ERR_INVALID_REQUEST.

        PRD §3.1: "Ingredients are provisioned centrally with a stable `ingredient_code`, a `display_name`, the theoretical `unit_cost_cents_per_gram`, the start-of-day target `par_level_grams`, the `hold_time_minutes` a cooked batch may be served before mandatory discard, and the standard `batch_size_grams` for a cook."
        PRD §2.7: "A request payload with a missing required field, a wrong-typed value, or an enum value outside its declared set is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
        Design: Corner/entities/ingredient_create_missing_required_field_returns_400
        """
        fixtures.set_clock(api, fixtures.MORNING)
        payload = f.ingredient_payload()
        del payload["par_level_grams"]
        response = api.create_ingredient(payload, fixtures.PLATFORM_ADMIN_HEADERS)
        validate_error(response, ApiErrorId.INVALID_REQUEST.value)

        rows, meta = validate_paginated(
            api.list_ingredients(fixtures.PLATFORM_ADMIN_HEADERS)
        )
        assert meta["total_count"] == 0
        assert rows == []


class TestMenuItemDigitalEligibleDefaultsTrue:
    def test_omitted_is_digital_eligible_stores_true(self, api):
        """The flag defaults to true when the create payload omits it.

        PRD §3.2: "Each menu item carries an `item_code`, a customer-facing `display_name`, a `base_price_cents` that serves both walk-in and first-party digital guests, and an `is_digital_eligible` flag (defaulting to true) controlling whether the item may be sold on the digital make-line. A new item's `suppression_state` is `SELLABLE` and its `theoretical_cost_cents` is zero until its recipe is defined."
        Design: Corner/entities/menu_item_digital_eligible_defaults_true
        """
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_bowl(api, with_window=False, store_overrides={"store_code": "MD"})
        item = fixtures.read_menu_item(api, world["item_id"])
        assert item["is_digital_eligible"] is True
        assert item["suppression_state"] == "SELLABLE"


class TestMenuItemTheoreticalCostRecomputed:
    def test_components_recompute_theoretical_cost(self, api):
        """Adding components recomputes the item's theoretical cost per the recipe sum.

        PRD §3.2: "Adding a component immediately recomputes the item's `theoretical_cost_cents` as the sum, over all of its components, of each component's `standard_grams` multiplied by the ingredient's `unit_cost_cents_per_gram`, rounded half-up to a whole cent."
        Design: Corner/entities/menu_item_theoretical_cost_recomputed_on_component_add
        """
        fixtures.set_clock(api, fixtures.MORNING)
        store = fixtures.create_store(api, store_code="MC")
        chicken = fixtures.create_ingredient(api, unit_cost_cents_per_gram=2.1)
        rice = fixtures.create_ingredient(
            api,
            ingredient_code="RICE",
            display_name="Rice",
            unit_cost_cents_per_gram=0.8,
            par_level_grams=5000,
            hold_time_minutes=90,
            batch_size_grams=4000,
        )
        item = fixtures.create_menu_item(api, store["id"])
        assert item["theoretical_cost_cents"] == 0

        fixtures.add_recipe_component(api, item["id"], chicken["id"], standard_grams=120)
        fixtures.add_recipe_component(api, item["id"], rice["id"], standard_grams=180)
        read = fixtures.read_menu_item(api, item["id"])
        # 120 * 2.1 + 180 * 0.8 = 252 + 144 = 396
        assert_cents(read["theoretical_cost_cents"], 396, "theoretical_cost_cents")


class TestBatchCreateIgnoresClientSuppliedStatus:
    def test_status_is_system_managed_and_created_active(self, api):
        """A client-supplied status is ignored; the batch starts ACTIVE.

        PRD §3.1: "The new batch starts `ACTIVE` with `grams_remaining` initialized to `grams_cooked`, a `discard_at` computed as the `cooked_at` instant plus the ingredient's `hold_time_minutes`, and `discarded_grams` at zero; the ingredient's `on_hand_grams` increases by `grams_cooked`."
        PRD §2.5: "Every resource in the system carries a standard set of system-managed fields:"
        Design: Corner/entities/batch_create_extra_field_status_is_ignored_input
        """
        fixtures.set_clock(api, fixtures.MORNING)
        store = fixtures.create_store(api, store_code="SB")
        chicken = fixtures.create_ingredient(api)
        payload = f.batch_payload(store["id"], grams_cooked=1000)
        payload["status"] = "EXPIRED"
        batch = validate_success(
            api.create_batch(chicken["id"], payload, fixtures.STORE_MANAGER_HEADERS),
            expected_status=201,
        )
        assert batch["status"] == "ACTIVE"
        assert batch["grams_remaining"] == 1000
        assert_instant(batch["discard_at"], "2026-09-01T13:00:00Z", "discard_at")


class TestChannelCreateInvalidMarkup:
    def test_negative_markup_pct_rejected_400(self, api):
        """A negative markup fraction is not a valid price markup.

        PRD §3.2: "Marketplace channels are provisioned by a `PlatformAdmin` with a `channel_code`, a `markup_pct` applied over `base_price_cents` to form the marketplace menu price, a `commission_pct` taken by the marketplace on gross marketplace sales, and an `active` flag (defaulting to true) controlling whether the channel currently injects orders."
        PRD §2.7: "A request payload with a missing required field, a wrong-typed value, or an enum value outside its declared set is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
        Design: Corner/entities/channel_create_invalid_markup_enum_returns_400
        """
        fixtures.set_clock(api, fixtures.MORNING)
        response = api.create_marketplace_channel(
            f.marketplace_channel_payload(channel_code="BAD", markup_pct=-0.5),
            fixtures.PLATFORM_ADMIN_HEADERS,
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value)


class TestOrderLineRequiresValidParentOrder:
    def test_lines_of_unknown_order_return_404(self, api):
        """Listing lines under an unknown order id resolves the order segment first.

        PRD §2.7: "When a path contains multiple resource identifiers (for example, a store followed by an order), the server resolves each identifier in order and rejects the request immediately with the 404 error corresponding to the first identifier that does not resolve — `ERR_STORE_NOT_FOUND` for a store segment, then `ERR_ORDER_NOT_FOUND`, `ERR_MENU_ITEM_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_DEPLOYMENT_NOT_FOUND`, `ERR_SUPPRESSION_EVENT_NOT_FOUND`, `ERR_CHANNEL_NOT_FOUND`, or `ERR_INGREDIENT_NOT_FOUND` as appropriate — before any business rule is evaluated."
        Design: Corner/entities/order_line_requires_valid_parent_order
        """
        fixtures.set_clock(api, fixtures.MORNING)
        response = api.list_order_lines(NON_EXISTENT_UUID, fixtures.STORE_MANAGER_HEADERS)
        validate_error(response, ApiErrorId.ORDER_NOT_FOUND.value)
