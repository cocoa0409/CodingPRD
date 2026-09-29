"""The declared entity surface: creation, defaults, derivations and reads.

These cover the flat parts of the contract that the costing chains take for
granted — what a create echoes back, which fields the server owns, what a
retrieval must report unchanged, and which malformed or dangling reference is
refused before any arithmetic runs.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    BaseUom,
    COST_ANALYST,
    CostBasis,
    CostState,
    ComponentStatus,
    IngredientPriceStatus,
    IngredientStatus,
    MISSING_UUID,
    MISSING_UUID_ALT,
    MarginClass,
    MenuItemStatus,
    PriceFeedStatus,
    RECIPE_DEVELOPER,
    RecipeStatus,
    RegionCode,
    ReviewStatus,
    assert_common_props,
    assert_error_envelope_shape,
    assert_fields,
    assert_ingredient,
    assert_ingredient_price,
    assert_menu_item,
    assert_ordered_by,
    assert_page_meta,
    assert_period_review,
    assert_price_feed,
    assert_recipe,
    assert_recipe_component,
    ceil_div,
    factories,
    fixtures,
    floor_div,
    get_success_data,
    ids_of,
    round_half_up,
    validate_error,
    validate_paginated,
)


class TestIngredientRegistration:
    """The purchasing leaf: its echoed payload, its derived yield, its gates."""

    BEEF_CHUCK = {
        "sku": "BEEF-CHUCK",
        "name": "Beef Chuck",
        "base_uom": BaseUom.GRAM,
        "pack_base_units": 4536,
        "trim_yield_bps": 9000,
        "cook_shrink_bps": 500,
        "allergen_mask": 0,
        "kcal_per_base_unit_micros": 2_500_000,
        "sodium_mcg_per_base_unit": 700,
    }

    def test_the_create_echoes_every_catalogue_field_and_opens_active(
        self, api: ApiClient
    ) -> None:
        """One POST returns 201 with the payload intact and the declared defaults.

        PRD 3.1: "Every new ingredient starts with `status` set to `ACTIVE` and
        `retired_at` null."

        Design: Corner/entities/ingredient_creation_persists_catalogue_fields_and_computes_net_yield
        """
        created = get_success_data(
            api.create_ingredient(
                factories.ingredient_payload(**self.BEEF_CHUCK), RECIPE_DEVELOPER
            ),
            201,
        )

        assert_ingredient(
            created,
            status=IngredientStatus.ACTIVE,
            retired_at=None,
            sku="BEEF-CHUCK",
            name="Beef Chuck",
            base_uom=BaseUom.GRAM,
            pack_base_units=4536,
            trim_yield_bps=9000,
            cook_shrink_bps=500,
            allergen_mask=0,
            kcal_per_base_unit_micros=2_500_000,
            sodium_mcg_per_base_unit=700,
        )
        assert_common_props(created, expected_version=1)

    def test_net_yield_is_the_floor_of_both_yield_factors(
        self, api: ApiClient
    ) -> None:
        """8550, not the 8500 of a subtraction and not the 9000 of trim alone.

        PRD 3.1: "From those two the system derives `net_yield_bps`, the combined
        yield actually used to convert an edible-portion specification into an
        as-purchased quantity: multiply `trim_yield_bps` by the difference between
        10000 and `cook_shrink_bps`, divide by 10000, and discard any fractional
        part."

        Design: Corner/entities/ingredient_creation_persists_catalogue_fields_and_computes_net_yield
        """
        created = get_success_data(
            api.create_ingredient(
                factories.ingredient_payload(**self.BEEF_CHUCK), RECIPE_DEVELOPER
            ),
            201,
        )

        assert_ingredient(
            created, net_yield_bps=floor_div(9000 * (10_000 - 500), 10_000)
        )
        assert created["net_yield_bps"] == 8550
        assert created["net_yield_bps"] != 8500, "the two factors do not subtract"
        assert created["net_yield_bps"] != 9000, "the shrink is not ignored"
        assert_fields(
            get_success_data(api.get_ingredient(created["id"])), net_yield_bps=8550
        )

    def test_a_yield_outside_its_declared_range_is_a_malformed_request(
        self, api: ApiClient
    ) -> None:
        """Zero trim yield and an undeclared unit both stop at the schema gate.

        PRD 2.10: "every enum value is a declared member; every integer respects
        its declared range"

        Design: Corner/entities/ingredient_creation_with_trim_yield_bps_out_of_range_returns_invalid_request
        """
        zero_yield = api.create_ingredient(
            factories.ingredient_payload(
                sku="BAD-YIELD", name="Zero Yield Item", trim_yield_bps=0
            ),
            RECIPE_DEVELOPER,
        )
        bad_uom = api.create_ingredient(
            factories.ingredient_payload(
                sku="BAD-UOM", name="Bad Uom Item", base_uom="OUNCE"
            ),
            RECIPE_DEVELOPER,
        )

        validate_error(zero_yield, ApiErrorId.INVALID_REQUEST)
        validate_error(bad_uom, ApiErrorId.INVALID_REQUEST)
        assert_error_envelope_shape(zero_yield)

    def test_an_unused_identifier_reports_the_ingredient_existence_gate(
        self, api: ApiClient
    ) -> None:
        """A well-formed UUID that names no row is a 404, not a 400.

        PRD 2.10: "An `ingredient_id` in the path or body identifies an existing
        ingredient — `ERR_INGREDIENT_NOT_FOUND`, 404, on every endpoint that takes
        one in either place."

        Design: Corner/entities/ingredient_get_with_unknown_id_returns_ingredient_not_found
        """
        cheddar = fixtures.create_cheddar(api)

        response = api.get_ingredient(MISSING_UUID)

        validate_error(response, ApiErrorId.INGREDIENT_NOT_FOUND)
        assert_error_envelope_shape(response)
        assert response.json()["data"]["message"], "the message must not be empty"
        assert_ingredient(
            get_success_data(api.get_ingredient(cheddar["id"])),
            sku="CHEDDAR-BLOCK",
            status=IngredientStatus.ACTIVE,
        )


class TestRecipeCostingSnapshotRetrieval:
    """A plain GET reports what the last roll-up persisted, byte for byte."""

    def test_the_read_returns_the_persisted_roll_up_figures(
        self, api: ApiClient
    ) -> None:
        """3880071 and 970018 again, under the basis they were produced with.

        PRD 3.3: "Finally the roll-up sets `cost_state` to `FRESH`, stamps
        `last_rollup_at` from the logical clock, increments the recipe's `version`
        and increments the `version` of every component it wrote to."

        Design: Corner/entities/recipe_retrieval_returns_the_persisted_costing_snapshot
        """
        world = fixtures.grill_world_costed(api)

        recipe = get_success_data(api.get_recipe(world["recipe"]["id"]))

        assert_recipe(
            recipe,
            batch_cost_micros=3_880_071,
            portion_cost_micros=970_018,
            cost_basis=CostBasis.LATEST_PUBLISHED,
            cost_state=CostState.FRESH,
            component_count=1,
        )
        assert recipe["last_rollup_at"] is not None
        assert recipe["batch_cost_micros"] == world["recipe"]["batch_cost_micros"]
        assert recipe["portion_cost_micros"] == world["recipe"]["portion_cost_micros"]

    def test_the_read_reports_the_nutrition_profile_and_a_flat_graph(
        self, api: ApiClient
    ) -> None:
        """Depth 0 with all-ingredient leaves, and the per-portion roll-up.

        PRD 3.3: "`depth` measures nesting: a recipe with no active sub-recipe
        component — all ingredient leaves — has a depth of 0"

        Design: Corner/entities/recipe_retrieval_returns_the_persisted_costing_snapshot
        """
        world = fixtures.grill_world_costed(api)

        recipe = get_success_data(api.get_recipe(world["recipe"]["id"]))

        assert_recipe(
            recipe,
            status=RecipeStatus.DRAFT,
            depth=0,
            allergen_mask=1,
            kcal_per_portion_micros=round_half_up(400 * 4_000_000, 4),
            sodium_mcg_per_portion=round_half_up(400 * 6200, 4),
            open_spec_change_count=0,
        )
        assert_fields(
            recipe, kcal_per_portion_micros=400_000_000, sodium_mcg_per_portion=620_000
        )


class TestRecipeComponentDerivation:
    """The as-purchased quantity a component derives from its ingredient."""

    @staticmethod
    def _sauce_with_a_lossy_tomato(api: ApiClient):
        """An ingredient losing trim and shrink, and an unpriced DRAFT recipe."""
        tomato = fixtures.create_ingredient(
            api,
            sku="TOMATO-WHOLE",
            name="Whole Tomatoes",
            base_uom=BaseUom.GRAM,
            pack_base_units=3000,
            trim_yield_bps=8500,
            cook_shrink_bps=1000,
            allergen_mask=0,
            kcal_per_base_unit_micros=180_000,
            sodium_mcg_per_base_unit=90,
        )
        recipe = fixtures.create_sub_recipe(
            api,
            code="SUB-SAUCE",
            name="Tomato Sauce",
            batch_yield_base_units=2000,
            portions_per_batch=20,
        )
        return tomato, recipe

    def test_the_as_purchased_quantity_rounds_up_from_the_net_yield(
        self, api: ApiClient
    ) -> None:
        """1000 edible grams need 1308 purchased grams at a 7650 net yield.

        PRD 3.3: "For an `INGREDIENT` line, multiply `ep_quantity_base_units` by
        10000, divide by the ingredient's `net_yield_bps`, and round the quotient
        *up* to the next whole base unit whenever there is any remainder."

        Design: Corner/entities/recipe_component_ap_quantity_computed_from_ingredient_net_yield
        """
        tomato, recipe = self._sauce_with_a_lossy_tomato(api)
        assert tomato["net_yield_bps"] == 7650

        component = fixtures.add_ingredient_component(
            api, recipe["id"], tomato["id"], ep_quantity_base_units=1000
        )

        assert_recipe_component(
            component,
            ep_quantity_base_units=1000,
            ap_quantity_base_units=ceil_div(1000 * 10_000, 7650),
        )
        assert component["ap_quantity_base_units"] == 1308
        assert component["ap_quantity_base_units"] != 1307, "truncation is not the rule"

    def test_the_add_prices_nothing_and_only_flags_the_recipe(
        self, api: ApiClient
    ) -> None:
        """Every money field stays 0 while the recipe goes STALE one version on.

        PRD 3.3: "A brand-new line has `status` `ACTIVE`, a null `removed_at`, and
        `unit_cost_micros_used`, `pack_base_units_snapshot` and
        `extended_cost_micros` all still at 0 until a roll-up fills them in."

        Design: Corner/entities/recipe_component_ap_quantity_computed_from_ingredient_net_yield
        """
        tomato, recipe = self._sauce_with_a_lossy_tomato(api)

        component = fixtures.add_ingredient_component(
            api, recipe["id"], tomato["id"], ep_quantity_base_units=1000
        )

        assert_recipe_component(
            component,
            status=ComponentStatus.ACTIVE,
            removed_at=None,
            unit_cost_micros_used=0,
            pack_base_units_snapshot=0,
            extended_cost_micros=0,
            sequence_no=1,
            recipe_id=recipe["id"],
        )
        assert_recipe(
            get_success_data(api.get_recipe(recipe["id"])),
            component_count=1,
            cost_state=CostState.STALE,
            version=recipe["version"] + 1,
        )


class TestRecipeComponentJunction:
    """One ingredient row backing components in two separate recipes."""

    @staticmethod
    def _two_recipes_on_one_ingredient(api: ApiClient):
        """Cheddar at ep 400 in the plate and at ep 500 in the sauce."""
        cheddar = fixtures.create_cheddar(api)
        grill = fixtures.create_recipe(api)
        cheese = fixtures.create_sub_recipe(api, code="SUB-CHEESE", name="Cheese Sauce")
        comp_grill = fixtures.add_ingredient_component(
            api, grill["id"], cheddar["id"], ep_quantity_base_units=400
        )
        comp_cheese = fixtures.add_ingredient_component(
            api, cheese["id"], cheddar["id"], ep_quantity_base_units=500
        )
        return {
            "cheddar": cheddar,
            "grill": grill,
            "cheese": cheese,
            "comp_grill": comp_grill,
            "comp_cheese": comp_cheese,
        }

    def test_the_ingredient_filter_finds_every_recipe_that_consumes_it(
        self, api: ApiClient
    ) -> None:
        """Two junction rows, in sequence order with the tie broken by creation.

        PRD 3.3: "The list can be narrowed by owning recipe with `recipe_id`, by
        `child_recipe_id` to discover which recipes consume a given sub-recipe, by
        `ingredient_id` to discover which recipes consume a given ingredient, and
        by `status`; it is ordered `sequence_no` ascending and then `created_at`
        ascending."

        Design: Corner/entities/recipe_component_junction_links_one_ingredient_into_two_recipes
        """
        world = self._two_recipes_on_one_ingredient(api)

        rows, meta = validate_paginated(
            api.list_recipe_components(
                {
                    "ingredient_id": world["cheddar"]["id"],
                    "status": ComponentStatus.ACTIVE,
                    "limit": 10,
                    "offset": 0,
                }
            )
        )

        assert_page_meta(meta, total_count=2, has_more=False)
        assert ids_of(rows) == [
            world["comp_grill"]["id"],
            world["comp_cheese"]["id"],
        ]
        assert_ordered_by(rows, "sequence_no")
        assert rows[0]["recipe_id"] == world["grill"]["id"]
        assert rows[1]["recipe_id"] == world["cheese"]["id"]

    def test_the_two_components_are_quantified_independently(
        self, api: ApiClient
    ) -> None:
        """The recipe filter isolates one side and its own 500-gram quantity.

        PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope, where `total_count` is
        the number of rows matching the request's filters before pagination is
        applied and `has_more` states whether any matching row remains beyond the
        returned page."

        Design: Corner/entities/recipe_component_junction_links_one_ingredient_into_two_recipes
        """
        world = self._two_recipes_on_one_ingredient(api)

        rows, meta = validate_paginated(
            api.list_recipe_components(
                {"recipe_id": world["cheese"]["id"], "limit": 10, "offset": 0}
            )
        )

        assert_page_meta(meta, total_count=1)
        assert_recipe_component(
            rows[0],
            ep_quantity_base_units=500,
            ap_quantity_base_units=500,
        )
        assert rows[0]["id"] == world["comp_cheese"]["id"]
        assert_recipe_component(world["comp_grill"], ap_quantity_base_units=400)
        assert_recipe(
            get_success_data(api.get_recipe(world["grill"]["id"])), component_count=1
        )
        assert_recipe(
            get_success_data(api.get_recipe(world["cheese"]["id"])), component_count=1
        )


class TestPriceLineServerOwnedFields:
    """What a price line takes from its feed rather than from its caller."""

    @staticmethod
    def _west_feed_with_one_line(api: ApiClient):
        """A PROTEIN feed in WEST carrying a single 24000000-micro cheddar line."""
        cheddar = fixtures.create_cheddar(api)
        feed = fixtures.open_price_feed(
            api,
            distributor_code="PROTEIN",
            region_code=RegionCode.WEST,
            feed_date="2026-07-05T00:00:00.000Z",
        )
        line = fixtures.add_price_line(
            api,
            feed["id"],
            cheddar["id"],
            pack_cost_micros=24_000_000,
            effective_from="2026-07-05T00:00:00.000Z",
        )
        return cheddar, feed, line

    def test_the_line_copies_the_feeds_scope_and_freezes_the_pack_size(
        self, api: ApiClient
    ) -> None:
        """WEST, PROTEIN and 2268 arrive without the caller supplying any of them.

        PRD 3.2: "Four values on the line are server-owned and any client-supplied
        value for them is ignored: the line's `price_feed_id` is taken from the feed
        it is being loaded under, its `region_code` and `distributor_code` are
        copied from that feed, and its `pack_base_units_snapshot` is frozen from the
        ingredient's current `pack_base_units` at the moment the line is created."

        Design: Corner/entities/price_feed_line_copies_feed_scope_and_freezes_pack_base_units_snapshot
        """
        cheddar, feed, line = self._west_feed_with_one_line(api)

        assert_ingredient_price(
            line,
            region_code=RegionCode.WEST,
            distributor_code="PROTEIN",
            pack_base_units_snapshot=2268,
            status=IngredientPriceStatus.PENDING,
            price_feed_id=feed["id"],
            effective_to=None,
            pack_cost_micros=24_000_000,
        )
        assert line["pack_base_units_snapshot"] == cheddar["pack_base_units"]

    def test_the_draft_feed_counts_the_line_but_fires_no_cascade(
        self, api: ApiClient
    ) -> None:
        """line_count moves to 1 while all three cascade counters stay 0.

        PRD 3.2: "A new feed opens with `status` `DRAFT`, `line_count` 0,
        `published_at` null and its three cascade counters —
        `superseded_price_count`, `affected_recipe_count` and
        `affected_menu_item_count` — all 0."

        Design: Corner/entities/price_feed_line_copies_feed_scope_and_freezes_pack_base_units_snapshot
        """
        _, feed, _ = self._west_feed_with_one_line(api)

        assert_price_feed(feed, status=PriceFeedStatus.DRAFT, line_count=0)
        assert_price_feed(
            get_success_data(api.get_price_feed(feed["id"])),
            status=PriceFeedStatus.DRAFT,
            published_at=None,
            line_count=1,
            superseded_price_count=0,
            affected_recipe_count=0,
            affected_menu_item_count=0,
        )


class TestMenuItemCreationDefaults:
    """A create that writes no costing figure at all."""

    def test_the_optional_kids_menu_flag_defaults_to_false(
        self, api: ApiClient
    ) -> None:
        """The one omittable input on the create resolves to false.

        PRD 3.5: "an optional `is_kids_menu` boolean that defaults to false when
        omitted"

        Design: Corner/entities/menu_item_creation_applies_declared_defaults_for_kids_menu_and_margin_class
        """
        world = fixtures.grill_world_costed(api)

        item = fixtures.create_menu_item(api, world["recipe"]["id"])

        assert_menu_item(item, is_kids_menu=False, status=MenuItemStatus.DRAFT)
        assert_common_props(item, expected_version=1)

    def test_the_create_copies_no_costing_figure_from_the_fresh_recipe(
        self, api: ApiClient
    ) -> None:
        """Every money, allergen and promotion field opens at zero or null.

        PRD 3.5: "Every new item opens in `status` `DRAFT` with `plate_cost_state`
        `STALE`, `margin_class` `UNCLASSIFIED`, a null `cost_basis`, a null
        `last_price_change_at`, `is_lto` false, and `open_lto_count`,
        `plate_cost_micros`, `plate_cost_cents`, `food_cost_bps`,
        `contribution_margin_cents`, `allergen_mask` and `sodium_mcg_per_portion`
        all at 0."

        Design: Corner/entities/menu_item_creation_applies_declared_defaults_for_kids_menu_and_margin_class
        """
        world = fixtures.grill_world_costed(api)
        assert world["recipe"]["allergen_mask"] == 1

        item = fixtures.create_menu_item(api, world["recipe"]["id"])

        assert_menu_item(
            item,
            plate_cost_state=CostState.STALE,
            margin_class=MarginClass.UNCLASSIFIED,
            cost_basis=None,
            last_price_change_at=None,
            is_lto=False,
            open_lto_count=0,
            plate_cost_micros=0,
            plate_cost_cents=0,
            food_cost_bps=0,
            contribution_margin_cents=0,
            allergen_mask=0,
            sodium_mcg_per_portion=0,
        )
        assert_recipe(
            get_success_data(api.get_recipe(world["recipe"]["id"])),
            cost_state=CostState.FRESH,
            batch_cost_micros=3_880_071,
        )

    def test_an_unknown_recipe_in_the_body_reports_the_recipe_existence_gate(
        self, api: ApiClient
    ) -> None:
        """A body foreign key is resolved exactly like a path identifier.

        PRD 2.10: "A `recipe_id` in the path or body — including the
        `child_recipe_id` of a sub-recipe component — identifies an existing recipe
        — `ERR_RECIPE_NOT_FOUND`, 404. This covers every recipe-scoped endpoint plus
        menu-item creation, specification-change-order creation and component
        creation."

        Design: Corner/entities/menu_item_creation_with_unknown_recipe_returns_recipe_not_found
        """
        real = fixtures.create_recipe(api, code="PLATE-REAL", name="Real Plate")

        response = api.create_menu_item(
            factories.menu_item_payload(
                MISSING_UUID_ALT,
                code="MI-ORPHAN",
                name="Orphan Item",
                declared_allergen_mask=0,
            ),
            RECIPE_DEVELOPER,
        )

        validate_error(response, ApiErrorId.RECIPE_NOT_FOUND)
        _, meta = validate_paginated(api.list_menu_items({"recipe_id": real["id"]}))
        assert_page_meta(meta, total_count=0, has_more=False)


class TestMenuItemListing:
    """A region filter, a page window, and the order they are applied in."""

    @staticmethod
    def _three_items_across_two_regions(api: ApiClient):
        """MI-A-MW and MI-B-MW in that order, then MI-C-NE."""
        recipe = fixtures.create_recipe(
            api, code="PLATE-LIST", name="List Fixture Plate"
        )
        item_a = fixtures.create_menu_item(
            api,
            recipe["id"],
            code="MI-A-MW",
            name="Item A",
            region_code=RegionCode.MW,
            current_price_cents=400,
            declared_allergen_mask=0,
        )
        item_b = fixtures.create_menu_item(
            api,
            recipe["id"],
            code="MI-B-MW",
            name="Item B",
            region_code=RegionCode.MW,
            current_price_cents=500,
            declared_allergen_mask=0,
        )
        item_c = fixtures.create_menu_item(
            api,
            recipe["id"],
            code="MI-C-NE",
            name="Item C",
            region_code=RegionCode.NE,
            current_price_cents=600,
            declared_allergen_mask=0,
        )
        return {"recipe": recipe, "a": item_a, "b": item_b, "c": item_c}

    def test_the_region_filter_narrows_the_count_before_the_page_window(
        self, api: ApiClient
    ) -> None:
        """One returned row, but a total of 2 rather than the table's 3.

        PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope, where `total_count` is
        the number of rows matching the request's filters before pagination is
        applied and `has_more` states whether any matching row remains beyond the
        returned page."

        Design: Corner/entities/menu_item_listing_filters_by_region_and_paginates
        """
        world = self._three_items_across_two_regions(api)

        rows, meta = validate_paginated(
            api.list_menu_items(
                {"region_code": RegionCode.MW, "limit": 1, "offset": 0}
            )
        )

        assert len(rows) == 1, f"limit 1 must return one row, got {len(rows)}"
        assert_page_meta(meta, total_count=2, limit=1, offset=0, has_more=True)
        assert rows[0]["id"] == world["a"]["id"]

    def test_the_second_page_exhausts_the_filtered_set(self, api: ApiClient) -> None:
        """Offset 1 returns MI-B-MW and reports nothing further.

        PRD 3.5: "Items can be listed with filters on `recipe_id`, `region_code`,
        `status` and `margin_class`, ordered `created_at` ascending."

        Design: Corner/entities/menu_item_listing_filters_by_region_and_paginates
        """
        world = self._three_items_across_two_regions(api)

        rows, meta = validate_paginated(
            api.list_menu_items(
                {"region_code": RegionCode.MW, "limit": 1, "offset": 1}
            )
        )

        assert_page_meta(meta, total_count=2, offset=1, has_more=False)
        assert rows[0]["id"] == world["b"]["id"]
        assert_menu_item(rows[0], code="MI-B-MW", region_code=RegionCode.MW)

    def test_the_unfiltered_page_returns_all_three_in_creation_order(
        self, api: ApiClient
    ) -> None:
        """Listing costs nothing: every row still reads 0 and STALE.

        PRD 2.3: "Unless a specific list endpoint states a different ordering,
        collections are returned sorted by `created_at` ascending."

        Design: Corner/entities/menu_item_listing_filters_by_region_and_paginates
        """
        world = self._three_items_across_two_regions(api)

        rows, meta = validate_paginated(api.list_menu_items({"limit": 10, "offset": 0}))

        assert_page_meta(meta, total_count=3, has_more=False)
        assert ids_of(rows) == [
            world["a"]["id"],
            world["b"]["id"],
            world["c"]["id"],
        ]
        assert_ordered_by(rows, "created_at")
        for row in rows:
            assert_menu_item(
                row,
                plate_cost_cents=0,
                plate_cost_state=CostState.STALE,
                margin_class=MarginClass.UNCLASSIFIED,
            )


class TestPeriodReviewWindowValidation:
    """A review window whose bounds are not strictly ordered."""

    def test_a_window_that_does_not_open_before_it_closes_is_refused(
        self, api: ApiClient
    ) -> None:
        """Reversed bounds and equal bounds are both malformed requests.

        PRD 2.10: "and where both bounds of a window are present, `period_start` is
        strictly before `period_end` and `window_start` is strictly before
        `window_end` — `ERR_INVALID_REQUEST`, 400."

        Design: Corner/entities/period_review_with_period_start_after_period_end_returns_invalid_request
        """
        unit = fixtures.create_unit(api)

        reversed_window = api.create_period_review(
            factories.period_review_payload(
                unit["id"],
                period_start="2026-08-01T00:00:00.000Z",
                period_end="2026-07-01T00:00:00.000Z",
            ),
            COST_ANALYST,
        )
        empty_window = api.create_period_review(
            factories.period_review_payload(
                unit["id"],
                period_start="2026-07-01T00:00:00.000Z",
                period_end="2026-07-01T00:00:00.000Z",
            ),
            COST_ANALYST,
        )

        validate_error(reversed_window, ApiErrorId.INVALID_REQUEST)
        validate_error(empty_window, ApiErrorId.INVALID_REQUEST)
        _, meta = validate_paginated(api.list_period_reviews({"unit_id": unit["id"]}))
        assert_page_meta(meta, total_count=0, has_more=False)

    def test_the_period_bounds_are_a_closed_open_interval_when_valid(
        self, api: ApiClient
    ) -> None:
        """A strictly ordered window opens at 0 with the basis fixed for good.

        PRD 3.8: "The review opens in `status` `OPEN` with `total_units_sold`,
        `total_gross_sales_cents`, `popularity_threshold_bps`,
        `margin_threshold_cents`, `theoretical_food_cost_cents`,
        `actual_food_cost_cents` and `variance_bps` all 0, `variance_flag` unset
        until close, and a null `closed_at`."

        Design: Corner/entities/period_review_with_period_start_after_period_end_returns_invalid_request
        """
        unit = fixtures.create_unit(api)

        review = fixtures.open_review(api, unit["id"])

        assert_period_review(
            review,
            status=ReviewStatus.OPEN,
            total_units_sold=0,
            total_gross_sales_cents=0,
            popularity_threshold_bps=0,
            margin_threshold_cents=0,
            theoretical_food_cost_cents=0,
            actual_food_cost_cents=0,
            variance_bps=0,
            closed_at=None,
            period_start="2026-07-01T00:00:00.000Z",
            period_end="2026-08-01T00:00:00.000Z",
        )


class TestCountLineRequiredFields:
    """A count line missing the quantity the usage arithmetic needs."""

    def test_omitting_the_counted_quantity_is_a_malformed_request(
        self, api: ApiClient
    ) -> None:
        """The schema gate fires before the review-status gate and before any usage.

        PRD 2.10: "Request body and query string parse; every required field is
        present; every field has its declared type"

        Design: Corner/entities/count_line_missing_required_counted_base_units_rejected
        """
        unit = fixtures.create_unit(api, code="STORE-001", name="Downtown")
        cheddar = fixtures.create_cheddar(api)
        review = fixtures.open_review(api, unit["id"])

        response = api.add_count_line(
            review["id"],
            {
                "ingredient_id": cheddar["id"],
                "opening_base_units": 500,
                "received_base_units": 0,
            },
            COST_ANALYST,
        )

        validate_error(response, ApiErrorId.INVALID_REQUEST)

    def test_the_rejected_write_leaves_the_review_without_a_count_line(
        self, api: ApiClient
    ) -> None:
        """No row, still OPEN, and the review's own version never moved.

        PRD 2.10: "Requests are validated in one fixed order, and the **first** rule
        that fails determines the response; no later rule is evaluated and no partial
        mutation is persisted."

        Design: Corner/entities/count_line_missing_required_counted_base_units_rejected
        """
        unit = fixtures.create_unit(api, code="STORE-001", name="Downtown")
        cheddar = fixtures.create_cheddar(api)
        review = fixtures.open_review(api, unit["id"])

        api.add_count_line(
            review["id"],
            {
                "ingredient_id": cheddar["id"],
                "opening_base_units": 500,
                "received_base_units": 0,
            },
            COST_ANALYST,
        )

        _, meta = validate_paginated(api.list_count_lines(review["id"]))
        assert_page_meta(meta, total_count=0, has_more=False)
        assert_period_review(
            get_success_data(api.get_period_review(review["id"])),
            status=ReviewStatus.OPEN,
            version=review["version"],
        )
