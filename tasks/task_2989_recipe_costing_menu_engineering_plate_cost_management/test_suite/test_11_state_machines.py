"""Lifecycle edges: the ones that fire, the ones that refuse and the ones that lock.

Each group walks one entity's state machine over a world built only from the
documented endpoints: an initial state, a guarded transition whose guard lives on
a neighbour, a terminal state that refuses a repeat, a side effect that is minted
exactly once, and a cascade that stops the moment its target is already flagged.
"""

from test_helpers import (
    APPROVER_USER_ID,
    ApiClient,
    ApiErrorId,
    ApprovalStatus,
    CLOCK_EPOCH,
    COST_ANALYST,
    CULINARY_DIRECTOR,
    CostBasis,
    CostState,
    ComponentStatus,
    DistributorCode,
    IngredientPriceStatus,
    IngredientStatus,
    LtoDecision,
    LtoStatus,
    LtoVerdict,
    MarginClass,
    MenuItemStatus,
    PriceFeedStatus,
    PropagationStatus,
    RECIPE_DEVELOPER,
    RecipeStatus,
    RegionCode,
    ReviewBasis,
    ReviewStatus,
    SUBMITTER_USER_ID,
    SyncState,
    assert_ingredient,
    assert_ingredient_price,
    assert_lto_campaign,
    assert_menu_item,
    assert_mix_line,
    assert_period_review,
    assert_prep_guide,
    assert_price_feed,
    assert_recipe,
    assert_recipe_component,
    assert_spec_change_order,
    factories,
    fixtures,
    get_success_data,
    ids_of,
    make_culinary_director_headers,
    round_half_up,
    single_row,
    validate_error,
    validate_paginated,
)


class TestRecipeCreationInitialState:
    """The first state a recipe can be in, before anything has been priced."""

    def test_a_new_recipe_opens_draft_with_a_stale_and_unbased_cost(
        self, api: ApiClient
    ) -> None:
        """DRAFT and STALE, with neither a basis nor a roll-up instant.

        PRD 3.3: "A new recipe opens in `status` `DRAFT` with `cost_state`
        `STALE`, a null `cost_basis` and a null `last_rollup_at`"

        Design: Corner/state_machines/recipe_created_starts_in_draft_with_stale_cost
        """
        created = get_success_data(
            api.create_recipe(factories.recipe_payload(), RECIPE_DEVELOPER), 201
        )

        assert_recipe(
            created,
            status=RecipeStatus.DRAFT,
            cost_state=CostState.STALE,
            cost_basis=None,
            last_rollup_at=None,
        )
        assert_recipe(
            get_success_data(api.get_recipe(created["id"])),
            status=RecipeStatus.DRAFT,
            cost_state=CostState.STALE,
            cost_basis=None,
            last_rollup_at=None,
        )

    def test_every_derived_figure_and_both_counters_start_at_zero(
        self, api: ApiClient
    ) -> None:
        """Eight zeroes on the create response and the same eight on the read.

        PRD 3.3: "with `batch_cost_micros`, `portion_cost_micros`,
        `allergen_mask`, `kcal_per_portion_micros`, `sodium_mcg_per_portion`,
        `depth`, `component_count` and `open_spec_change_count` all at 0"

        Design: Corner/state_machines/recipe_created_starts_in_draft_with_stale_cost
        """
        created = get_success_data(
            api.create_recipe(factories.recipe_payload(), RECIPE_DEVELOPER), 201
        )

        zeroes = dict(
            batch_cost_micros=0,
            portion_cost_micros=0,
            allergen_mask=0,
            kcal_per_portion_micros=0,
            sodium_mcg_per_portion=0,
            depth=0,
            component_count=0,
            open_spec_change_count=0,
        )
        assert_recipe(created, version=1, **zeroes)
        assert_recipe(get_success_data(api.get_recipe(created["id"])), **zeroes)


class TestRecipeSubmitReviewPreconditionOrder:
    """The empty-specification gate against the freshness gate, in that order."""

    @staticmethod
    def _priced_cheddar_and_an_empty_draft(api: ApiClient):
        """A published MW cheddar price and a DRAFT recipe with no components."""
        world = fixtures.grill_world_priced(api)
        world["recipe"] = fixtures.create_recipe(api)
        return world

    def test_an_empty_specification_reports_the_recipe_status_error(
        self, api: ApiClient
    ) -> None:
        """No components and a stale cost still reads as a status violation.

        PRD 3.4: "The recipe must have at least one active component, and an
        empty specification is refused with `ERR_RECIPE_INVALID_STATE` as well,
        because a recipe with nothing in it is not a reviewable specification in
        any status."

        Design: Corner/state_machines/recipe_draft_to_under_review_requires_a_component_and_a_fresh_cost
        """
        world = self._priced_cheddar_and_an_empty_draft(api)

        response = api.submit_recipe_review(world["recipe"]["id"], RECIPE_DEVELOPER)

        validate_error(response, ApiErrorId.RECIPE_INVALID_STATE)
        assert_recipe(
            get_success_data(api.get_recipe(world["recipe"]["id"])),
            status=RecipeStatus.DRAFT,
            component_count=0,
            cost_state=CostState.STALE,
        )

    def test_a_component_less_roll_up_succeeds_at_zero_and_turns_the_cost_fresh(
        self, api: ApiClient
    ) -> None:
        """Zero is a legitimate batch cost, and it is a FRESH one.

        PRD 3.3: "A recipe with no active components at all rolls up
        legitimately: `batch_cost_micros` and `portion_cost_micros` are both 0
        and the recipe is nonetheless marked `FRESH`."

        Design: Corner/state_machines/recipe_draft_to_under_review_requires_a_component_and_a_fresh_cost
        """
        world = self._priced_cheddar_and_an_empty_draft(api)

        rolled = fixtures.rollup(api, world["recipe"]["id"])

        assert_recipe(
            rolled,
            cost_state=CostState.FRESH,
            cost_basis=CostBasis.LATEST_PUBLISHED,
            batch_cost_micros=0,
            portion_cost_micros=0,
            component_count=0,
        )
        assert rolled["last_rollup_at"] is not None

    def test_a_fresh_cost_does_not_make_an_empty_specification_reviewable(
        self, api: ApiClient
    ) -> None:
        """The position-18 gate outranks the position-26 gate.

        PRD 3.4: "Note the ordering carefully: the empty-specification refusal is
        part of the recipe-status gate at position 18 of §2.10 and therefore
        **outranks** the freshness gate at position 26 — a brand-new recipe with
        no components and a stale cost reports `ERR_RECIPE_INVALID_STATE`, not
        `ERR_COST_STALE`."

        Design: Corner/state_machines/recipe_draft_to_under_review_requires_a_component_and_a_fresh_cost
        """
        world = self._priced_cheddar_and_an_empty_draft(api)
        rolled = fixtures.rollup(api, world["recipe"]["id"])
        assert rolled["cost_state"] == CostState.FRESH

        response = api.submit_recipe_review(world["recipe"]["id"], RECIPE_DEVELOPER)

        validate_error(response, ApiErrorId.RECIPE_INVALID_STATE)

    def test_adding_the_component_moves_the_refusal_onto_the_freshness_gate(
        self, api: ApiClient
    ) -> None:
        """The same call now reports staleness, because the add reset the flag.

        PRD 3.4: "The recipe's `cost_state` must be `FRESH`, and a stale cost is
        refused with `ERR_COST_STALE`."

        Design: Corner/state_machines/recipe_draft_to_under_review_requires_a_component_and_a_fresh_cost
        """
        world = self._priced_cheddar_and_an_empty_draft(api)
        fixtures.rollup(api, world["recipe"]["id"])
        fixtures.add_ingredient_component(
            api,
            world["recipe"]["id"],
            world["cheddar"]["id"],
            ep_quantity_base_units=400,
        )

        response = api.submit_recipe_review(world["recipe"]["id"], RECIPE_DEVELOPER)

        validate_error(response, ApiErrorId.COST_STALE)
        assert_recipe(
            get_success_data(api.get_recipe(world["recipe"]["id"])),
            status=RecipeStatus.DRAFT,
            cost_state=CostState.STALE,
            component_count=1,
        )

    def test_both_preconditions_satisfied_opens_the_review_at_three_versions_on(
        self, api: ApiClient
    ) -> None:
        """Component add, roll-up and submission are three separate mutations.

        PRD 3.4: "A successful submission increments the recipe's `version`."

        Design: Corner/state_machines/recipe_draft_to_under_review_requires_a_component_and_a_fresh_cost
        """
        world = self._priced_cheddar_and_an_empty_draft(api)
        after_empty_rollup = fixtures.rollup(api, world["recipe"]["id"])
        fixtures.add_ingredient_component(
            api,
            world["recipe"]["id"],
            world["cheddar"]["id"],
            ep_quantity_base_units=400,
        )
        rolled = fixtures.rollup(api, world["recipe"]["id"])

        submitted = fixtures.submit_recipe_review(api, world["recipe"]["id"])

        assert_recipe(
            rolled, batch_cost_micros=round_half_up(400 * 22_000_000, 2268)
        )
        assert rolled["batch_cost_micros"] == 3_880_071
        assert_recipe(
            submitted,
            status=RecipeStatus.UNDER_REVIEW,
            cost_state=CostState.FRESH,
            version=after_empty_rollup["version"] + 3,
        )


class TestRecipeActivationMintsOnePrepGuide:
    """One document per recipe, minted on the first activation and never again."""

    def test_the_first_activation_mints_revision_one_and_freezes_three_figures(
        self, api: ApiClient
    ) -> None:
        """The snapshot version is the post-increment 5, not the pre-increment 4.

        PRD 3.4: "If no prep guide yet exists for the recipe, activation mints one
        with `revision_no` 1 and `sync_state` `CURRENT`, freezing three figures
        from the recipe as it now stands — `batch_yield_base_units_snapshot`,
        `portions_per_batch_snapshot` and `component_count_snapshot` — and
        recording `synced_spec_version` as the recipe's `version` *after* this
        transition's increment."

        Design: Corner/state_machines/recipe_activation_mints_prep_guide_revision_one_only_on_first_activation
        """
        world = fixtures.grill_world_under_review(api)
        assert_recipe(world["recipe"], status=RecipeStatus.UNDER_REVIEW, version=4)

        activated = fixtures.activate_recipe(api, world["recipe"]["id"])

        assert_recipe(activated, status=RecipeStatus.ACTIVE, version=5)
        assert activated["version"] == world["recipe"]["version"] + 1
        assert_prep_guide(
            fixtures.sole_prep_guide(api, world["recipe"]["id"]),
            recipe_id=world["recipe"]["id"],
            revision_no=1,
            sync_state=SyncState.CURRENT,
            synced_spec_version=5,
            batch_yield_base_units_snapshot=4,
            portions_per_batch_snapshot=4,
            component_count_snapshot=1,
        )

    def test_an_active_recipe_can_be_sent_back_through_review_and_activated_again(
        self, api: ApiClient
    ) -> None:
        """ACTIVE to UNDER_REVIEW to ACTIVE, two more versions.

        PRD 3.4: "an already-`ACTIVE` recipe whose specification has changed is
        submitted for review by exactly the same action, moving `ACTIVE` to
        `UNDER_REVIEW` so that the component set becomes directly editable again"

        Design: Corner/state_machines/recipe_activation_mints_prep_guide_revision_one_only_on_first_activation
        """
        world = fixtures.grill_world_under_review(api)
        fixtures.activate_recipe(api, world["recipe"]["id"])

        resubmitted = fixtures.submit_recipe_review(api, world["recipe"]["id"])
        reactivated = fixtures.activate_recipe(api, world["recipe"]["id"])

        assert_recipe(
            resubmitted,
            status=RecipeStatus.UNDER_REVIEW,
            cost_state=CostState.FRESH,
            version=6,
        )
        assert_recipe(
            reactivated,
            status=RecipeStatus.ACTIVE,
            cost_state=CostState.FRESH,
            batch_cost_micros=3_880_071,
            version=7,
        )

    def test_the_second_activation_leaves_the_existing_guide_entirely_untouched(
        self, api: ApiClient
    ) -> None:
        """Same row, same revision 1, same CURRENT flag, same snapshot version.

        PRD 3.4: "If a prep guide already exists, activation leaves it entirely
        untouched, **including its `sync_state`**: re-activating a recipe after a
        specification change never silently marks an out-of-date prep guide as
        current again."

        Design: Corner/state_machines/recipe_activation_mints_prep_guide_revision_one_only_on_first_activation
        """
        world = fixtures.grill_world_under_review(api)
        fixtures.activate_recipe(api, world["recipe"]["id"])
        first_guide = fixtures.sole_prep_guide(api, world["recipe"]["id"])

        fixtures.submit_recipe_review(api, world["recipe"]["id"])
        fixtures.activate_recipe(api, world["recipe"]["id"])

        second_guide = fixtures.sole_prep_guide(api, world["recipe"]["id"])
        assert second_guide["id"] == first_guide["id"]
        assert_prep_guide(
            second_guide,
            revision_no=1,
            sync_state=SyncState.CURRENT,
            synced_spec_version=5,
            version=first_guide["version"],
        )

    def test_the_guide_is_a_single_row_listing_that_now_lags_the_recipe(
        self, api: ApiClient
    ) -> None:
        """One row, snapshotting version 5 while the recipe stands at 7.

        PRD 3.4: "Prep guides are readable as a list per recipe, which will
        contain either zero rows or exactly one, and it is the only place the
        minted revision and the `OUT_OF_DATE` flag can be observed."

        Design: Corner/state_machines/recipe_activation_mints_prep_guide_revision_one_only_on_first_activation
        """
        world = fixtures.grill_world_under_review(api)
        fixtures.activate_recipe(api, world["recipe"]["id"])
        fixtures.submit_recipe_review(api, world["recipe"]["id"])
        recipe = fixtures.activate_recipe(api, world["recipe"]["id"])

        rows, meta = validate_paginated(
            api.list_prep_guides(world["recipe"]["id"], None, COST_ANALYST)
        )

        assert meta["total_count"] == 1
        guide = single_row(rows)
        assert guide["synced_spec_version"] == 5
        assert recipe["version"] == 7
        assert guide["synced_spec_version"] < recipe["version"]
        assert_prep_guide(guide, sync_state=SyncState.CURRENT)


class TestParentActivationGuardedByChildStatus:
    """A plated parent that cannot go live until its sub-recipe does."""

    @staticmethod
    def _parent_under_review_over_a_draft_child(api: ApiClient):
        """PLATE-CHEESE reviewed and costed over a deliberately DRAFT SUB-CHEESE."""
        world = fixtures.grill_world_priced(api)
        child = fixtures.create_sub_recipe(api)
        fixtures.add_ingredient_component(
            api, child["id"], world["cheddar"]["id"], ep_quantity_base_units=500
        )
        child = fixtures.rollup(api, child["id"])
        parent = fixtures.create_recipe(
            api,
            code="PLATE-CHEESE",
            name="Cheese Plate",
            batch_yield_base_units=5,
            portions_per_batch=5,
        )
        parent_component = fixtures.add_sub_recipe_component(
            api, parent["id"], child["id"], ep_quantity_base_units=500
        )
        parent = fixtures.rollup(api, parent["id"])
        parent = fixtures.submit_recipe_review(api, parent["id"])
        world.update(
            {"child": child, "parent": parent, "parent_component": parent_component}
        )
        return world

    def test_the_child_costs_its_own_ingredient_line_first(
        self, api: ApiClient
    ) -> None:
        """4850088 in the child batch, 242504 per child portion.

        PRD 3.3: "For an `INGREDIENT` component, take `ap_quantity_base_units`
        (recomputed as the ceiling of `ep_quantity_base_units` multiplied by 10000
        and divided by the ingredient's `net_yield_bps`), multiply by
        `unit_cost_micros_used`, divide by `pack_base_units_snapshot`, and round
        half up to whole micro-dollars."

        Design: Corner/state_machines/recipe_activation_with_a_draft_sub_recipe_child_is_rejected_then_succeeds
        """
        world = self._parent_under_review_over_a_draft_child(api)

        assert_recipe(
            world["child"],
            status=RecipeStatus.DRAFT,
            cost_state=CostState.FRESH,
            batch_cost_micros=round_half_up(500 * 22_000_000, 2268),
            portion_cost_micros=round_half_up(4_850_088, 20),
            depth=0,
        )
        assert_recipe(
            world["child"], batch_cost_micros=4_850_088, portion_cost_micros=242_504
        )

    def test_the_parent_prices_the_child_batch_pro_rata_and_records_depth_one(
        self, api: ApiClient
    ) -> None:
        """A quarter of the child batch, at ap equal to ep.

        PRD 3.3: "For a `SUB_RECIPE` component, `ap_quantity_base_units` equals
        `ep_quantity_base_units`, `unit_cost_micros_used` is set to the child
        recipe's `batch_cost_micros` and `pack_base_units_snapshot` to the child's
        `batch_yield_base_units`; the extended cost is then
        `ep_quantity_base_units` multiplied by the child's `batch_cost_micros`,
        divided by the child's `batch_yield_base_units`, rounded half up."

        Design: Corner/state_machines/recipe_activation_with_a_draft_sub_recipe_child_is_rejected_then_succeeds
        """
        world = self._parent_under_review_over_a_draft_child(api)

        assert_recipe_component(
            get_success_data(
                api.get_recipe_component(world["parent_component"]["id"])
            ),
            ep_quantity_base_units=500,
            ap_quantity_base_units=500,
            unit_cost_micros_used=4_850_088,
            pack_base_units_snapshot=2000,
            extended_cost_micros=round_half_up(500 * 4_850_088, 2000),
        )
        assert_recipe(
            world["parent"],
            status=RecipeStatus.UNDER_REVIEW,
            cost_state=CostState.FRESH,
            batch_cost_micros=1_212_522,
            portion_cost_micros=round_half_up(1_212_522, 5),
            depth=1,
            component_count=1,
        )
        assert_recipe(world["parent"], portion_cost_micros=242_504)

    def test_activating_over_a_draft_child_is_refused_and_mints_no_guide(
        self, api: ApiClient
    ) -> None:
        """The parent stays UNDER_REVIEW with an empty prep-guide listing.

        PRD 3.4: "Every active sub-recipe component's child recipe must itself be
        `ACTIVE`, so a plated recipe can never go live on a sub-recipe that is
        still in draft — otherwise `ERR_SUBRECIPE_NOT_ACTIVE`."

        Design: Corner/state_machines/recipe_activation_with_a_draft_sub_recipe_child_is_rejected_then_succeeds
        """
        world = self._parent_under_review_over_a_draft_child(api)

        response = api.activate_recipe(world["parent"]["id"], CULINARY_DIRECTOR)

        validate_error(response, ApiErrorId.SUBRECIPE_NOT_ACTIVE)
        assert_recipe(
            get_success_data(api.get_recipe(world["parent"]["id"])),
            status=RecipeStatus.UNDER_REVIEW,
            version=world["parent"]["version"],
        )
        assert fixtures.prep_guide_rows(api, world["parent"]["id"]) == []

    def test_the_child_walks_its_own_review_cycle_without_recosting(
        self, api: ApiClient
    ) -> None:
        """Two transitions on the child, and its money figure never moves.

        PRD 3.4: "Activation is the `CulinaryDirector`'s decision and moves
        `UNDER_REVIEW` to `ACTIVE`."

        Design: Corner/state_machines/recipe_activation_with_a_draft_sub_recipe_child_is_rejected_then_succeeds
        """
        world = self._parent_under_review_over_a_draft_child(api)

        fixtures.submit_recipe_review(api, world["child"]["id"])
        activated_child = fixtures.activate_recipe(api, world["child"]["id"])

        assert_recipe(
            activated_child,
            status=RecipeStatus.ACTIVE,
            cost_state=CostState.FRESH,
            batch_cost_micros=4_850_088,
            version=world["child"]["version"] + 2,
        )

    def test_the_same_parent_activation_now_succeeds_and_mints_its_first_guide(
        self, api: ApiClient
    ) -> None:
        """Two recipes, two guides, each at revision 1 and CURRENT.

        PRD 3.4: "If no prep guide yet exists for the recipe, activation mints one
        with `revision_no` 1 and `sync_state` `CURRENT`"

        Design: Corner/state_machines/recipe_activation_with_a_draft_sub_recipe_child_is_rejected_then_succeeds
        """
        world = self._parent_under_review_over_a_draft_child(api)
        api.activate_recipe(world["parent"]["id"], CULINARY_DIRECTOR)
        fixtures.submit_recipe_review(api, world["child"]["id"])
        fixtures.activate_recipe(api, world["child"]["id"])

        activated_parent = fixtures.activate_recipe(api, world["parent"]["id"])

        assert_recipe(
            activated_parent,
            status=RecipeStatus.ACTIVE,
            cost_state=CostState.FRESH,
            batch_cost_micros=1_212_522,
            depth=1,
        )
        for recipe_id in (world["parent"]["id"], world["child"]["id"]):
            assert_prep_guide(
                fixtures.sole_prep_guide(api, recipe_id),
                recipe_id=recipe_id,
                revision_no=1,
                sync_state=SyncState.CURRENT,
            )


class TestIngredientRetirementFiresNoCascade:
    """A terminal move on the ingredient that deliberately touches no money."""

    def test_retirement_stamps_the_clock_and_bumps_only_the_ingredient(
        self, api: ApiClient
    ) -> None:
        """ACTIVE to RETIRED, with `retired_at` at the logical clock's reading.

        PRD 3.1: "Retiring an ingredient moves its `status` from `ACTIVE` to
        `RETIRED` — a terminal state — writes `retired_at` from the logical clock
        and increments the ingredient's `version`."

        Design: Corner/state_machines/ingredient_retire_sets_retired_at_and_leaves_every_cost_state_untouched
        """
        world = fixtures.grill_world_active_item(api)

        retired = fixtures.retire_ingredient(api, world["cheddar"]["id"])

        assert_ingredient(
            retired,
            status=IngredientStatus.RETIRED,
            retired_at=CLOCK_EPOCH,
            version=world["cheddar"]["version"] + 1,
        )

    def test_the_recipe_keeps_its_fresh_cost_and_its_active_status(
        self, api: ApiClient
    ) -> None:
        """Nothing the last roll-up consumed changed, so nothing goes stale.

        PRD 3.1: "What retirement deliberately does **not** do is touch a single
        cost figure: no specification and no published price changed, so every
        recipe's `cost_state` and every menu item's `plate_cost_state` are left
        exactly as they were, and every published price row for that ingredient
        remains usable."

        Design: Corner/state_machines/ingredient_retire_sets_retired_at_and_leaves_every_cost_state_untouched
        """
        world = fixtures.grill_world_active_item(api)

        fixtures.retire_ingredient(api, world["cheddar"]["id"])

        assert_recipe(
            get_success_data(api.get_recipe(world["recipe"]["id"])),
            status=RecipeStatus.ACTIVE,
            cost_state=CostState.FRESH,
            batch_cost_micros=3_880_071,
            portion_cost_micros=970_018,
            version=world["recipe"]["version"],
        )

    def test_the_menu_item_keeps_its_fresh_plate_cost(self, api: ApiClient) -> None:
        """Retirement is absent from the list of things that restale a cost.

        PRD 2.6: "A state becomes `FRESH` only as the immediate result of a
        successful roll-up call on that specific row, and it reverts to `STALE` the
        moment anything the last roll-up consumed changes underneath it — a
        component added or removed, a quantity re-specified, a distributor price
        published, or a sub-recipe's own cost going stale."

        Design: Corner/state_machines/ingredient_retire_sets_retired_at_and_leaves_every_cost_state_untouched
        """
        world = fixtures.grill_world_active_item(api)

        fixtures.retire_ingredient(api, world["cheddar"]["id"])

        assert_menu_item(
            get_success_data(api.get_menu_item(world["menu_item"]["id"])),
            status=MenuItemStatus.ACTIVE,
            plate_cost_state=CostState.FRESH,
            plate_cost_cents=100,
            version=world["menu_item"]["version"],
        )

    def test_the_published_price_row_and_the_prep_guide_both_survive(
        self, api: ApiClient
    ) -> None:
        """One usable PUBLISHED row at 22000000 and an untouched revision 1.

        PRD 3.2: "The full set of price rows quoted for one ingredient — across
        every feed and every region — is readable as a list ordered by
        `effective_from` ascending and then `created_at` ascending, optionally
        narrowed by `status` or by `region_code`."

        Design: Corner/state_machines/ingredient_retire_sets_retired_at_and_leaves_every_cost_state_untouched
        """
        world = fixtures.grill_world_active_item(api)

        fixtures.retire_ingredient(api, world["cheddar"]["id"])

        rows, meta = validate_paginated(
            api.list_ingredient_prices(world["cheddar"]["id"])
        )
        assert meta["total_count"] == 1
        assert_ingredient_price(
            single_row(rows),
            status=IngredientPriceStatus.PUBLISHED,
            pack_cost_micros=22_000_000,
            effective_to=None,
        )
        assert_prep_guide(
            fixtures.sole_prep_guide(api, world["recipe"]["id"]),
            revision_no=1,
            sync_state=SyncState.CURRENT,
        )


class TestIngredientRetirementIsTerminal:
    """The second attempt is an error, not a harmless repeat."""

    @staticmethod
    def _retired_then_clock_advanced(api: ApiClient):
        """One retired ingredient, with the clock moved nine days past the write."""
        cheddar = fixtures.create_cheddar(api)
        retired = fixtures.retire_ingredient(api, cheddar["id"])
        fixtures.set_clock(api, "2026-08-10T00:00:00.000Z")
        return retired

    def test_a_second_retirement_is_refused_from_the_terminal_state(
        self, api: ApiClient
    ) -> None:
        """RETIRED admits no further transition, not even an idempotent one.

        PRD 3.1: "Because `RETIRED` is terminal, a second retirement attempt on an
        already retired ingredient is refused with `ERR_INGREDIENT_RETIRED` rather
        than treated as a harmless repeat."

        Design: Corner/state_machines/ingredient_retire_twice_is_rejected_from_the_terminal_state
        """
        retired = self._retired_then_clock_advanced(api)

        response = api.retire_ingredient(retired["id"], CULINARY_DIRECTOR)

        validate_error(response, ApiErrorId.INGREDIENT_RETIRED)

    def test_the_refusal_does_not_restamp_retired_at_from_the_new_clock(
        self, api: ApiClient
    ) -> None:
        """The instant stays at the reading of the write that succeeded.

        PRD 2.4: "Every timestamp the system writes itself (`retired_at`,
        `published_at`, `last_rollup_at`, `removed_at`, `approved_at`,
        `applied_at`, `closed_at`, `reviewed_at`, `last_price_change_at`) is the
        logical clock's reading at the moment of the write."

        Design: Corner/state_machines/ingredient_retire_twice_is_rejected_from_the_terminal_state
        """
        retired = self._retired_then_clock_advanced(api)

        api.retire_ingredient(retired["id"], CULINARY_DIRECTOR)

        after = get_success_data(api.get_ingredient(retired["id"]))
        assert_ingredient(
            after, status=IngredientStatus.RETIRED, retired_at=CLOCK_EPOCH
        )
        assert after["retired_at"] != "2026-08-10T00:00:00.000Z"

    def test_the_refused_repeat_persists_no_partial_mutation(
        self, api: ApiClient
    ) -> None:
        """The version is exactly where the first retirement left it.

        PRD 2.10: "Requests are validated in one fixed order, and the **first**
        rule that fails determines the response; no later rule is evaluated and no
        partial mutation is persisted."

        Design: Corner/state_machines/ingredient_retire_twice_is_rejected_from_the_terminal_state
        """
        retired = self._retired_then_clock_advanced(api)

        api.retire_ingredient(retired["id"], CULINARY_DIRECTOR)

        assert_ingredient(
            get_success_data(api.get_ingredient(retired["id"])),
            version=retired["version"],
        )


class TestPriceFeedPublicationIsOnceOnly:
    """One error identifier covers both the empty feed and the second publish."""

    @staticmethod
    def _one_empty_feed_and_one_loaded_feed(api: ApiClient):
        """A costed recipe, an empty PROTEIN feed and a staged 25000000 rise."""
        world = fixtures.grill_world_costed(api)
        world["empty_feed"] = fixtures.open_price_feed(
            api,
            distributor_code=DistributorCode.PROTEIN,
            feed_date="2026-07-10T00:00:00.000Z",
        )
        world["loaded_feed"] = fixtures.stage_price_feed(
            api,
            world["cheddar"]["id"],
            25_000_000,
            effective_from="2026-07-15T00:00:00.000Z",
        )
        return world

    def test_an_empty_feed_cannot_publish_and_reports_the_publication_error(
        self, api: ApiClient
    ) -> None:
        """Zero lines is refused under `ERR_FEED_ALREADY_PUBLISHED`.

        PRD 3.2: "The feed must still be `DRAFT` and must hold at least one line —
        an empty feed cannot publish, and that is reported as
        `ERR_FEED_ALREADY_PUBLISHED`."

        Design: Corner/state_machines/price_feed_publish_twice_is_rejected
        """
        world = self._one_empty_feed_and_one_loaded_feed(api)

        response = api.publish_price_feed(world["empty_feed"]["id"], COST_ANALYST)

        validate_error(response, ApiErrorId.FEED_ALREADY_PUBLISHED)
        assert_price_feed(
            get_success_data(api.get_price_feed(world["empty_feed"]["id"])),
            status=PriceFeedStatus.DRAFT,
            line_count=0,
            published_at=None,
        )

    def test_the_loaded_feed_publishes_once_and_records_its_cascade(
        self, api: ApiClient
    ) -> None:
        """One truncated incumbent and one recipe flipped stale.

        PRD 3.2: "The **first hop** flips the feed's `status` to `PUBLISHED`,
        stamps `published_at` from the logical clock, and moves every one of the
        feed's lines from `PENDING` to `PUBLISHED`."

        Design: Corner/state_machines/price_feed_publish_twice_is_rejected
        """
        world = self._one_empty_feed_and_one_loaded_feed(api)

        published = fixtures.publish_price_feed(api, world["loaded_feed"]["id"])

        assert_price_feed(
            published,
            status=PriceFeedStatus.PUBLISHED,
            published_at=CLOCK_EPOCH,
            superseded_price_count=1,
            affected_recipe_count=1,
            affected_menu_item_count=0,
            line_count=1,
        )

    def test_a_second_publication_of_the_same_feed_is_refused(
        self, api: ApiClient
    ) -> None:
        """PUBLISHED is not a republishable status.

        PRD 3.2: "Lines may only be added while the feed is `DRAFT`; adding one to
        an already published feed is refused with `ERR_FEED_ALREADY_PUBLISHED`, as
        is a second publication attempt on the same feed."

        Design: Corner/state_machines/price_feed_publish_twice_is_rejected
        """
        world = self._one_empty_feed_and_one_loaded_feed(api)
        fixtures.publish_price_feed(api, world["loaded_feed"]["id"])

        response = api.publish_price_feed(world["loaded_feed"]["id"], COST_ANALYST)

        validate_error(response, ApiErrorId.FEED_ALREADY_PUBLISHED)

    def test_the_refused_republication_re_runs_no_hop_of_the_cascade(
        self, api: ApiClient
    ) -> None:
        """The counters, the version and the price history all stand still.

        PRD 2.10: "Requests are validated in one fixed order, and the **first**
        rule that fails determines the response; no later rule is evaluated and no
        partial mutation is persisted."

        Design: Corner/state_machines/price_feed_publish_twice_is_rejected
        """
        world = self._one_empty_feed_and_one_loaded_feed(api)
        published = fixtures.publish_price_feed(api, world["loaded_feed"]["id"])

        api.publish_price_feed(world["loaded_feed"]["id"], COST_ANALYST)

        assert_price_feed(
            get_success_data(api.get_price_feed(world["loaded_feed"]["id"])),
            version=published["version"],
            superseded_price_count=1,
            affected_recipe_count=1,
            published_at=CLOCK_EPOCH,
        )
        rows, meta = validate_paginated(
            api.list_ingredient_prices(
                world["cheddar"]["id"],
                {"status": IngredientPriceStatus.PUBLISHED},
            )
        )
        assert meta["total_count"] == 1
        assert_ingredient_price(single_row(rows), pack_cost_micros=25_000_000)


class TestPricePublicationDecostsACampaign:
    """A price rise five hops away pulls a COSTED promotion back to PLANNED."""

    @staticmethod
    def _costed_campaign_and_a_staged_rise(api: ApiClient):
        """A live item with a COSTED campaign, and a 25000000 feed still DRAFT."""
        world = fixtures.grill_world_active_item(api)
        planned = fixtures.plan_lto(api, world["menu_item"]["id"])
        costed = fixtures.cost_lto(api, planned["id"])
        world["rise"] = fixtures.stage_price_feed(
            api,
            world["cheddar"]["id"],
            25_000_000,
            effective_from="2026-07-15T00:00:00.000Z",
        )
        world.update({"planned": planned, "costed": costed})
        return world

    def test_the_campaign_costs_off_the_items_region_and_plate_cost(
        self, api: ApiClient
    ) -> None:
        """100 cents frozen, 2632 basis points, 140000 cents forecast.

        PRD 3.9: "The run freezes `promo_plate_cost_cents` from the item's
        `plate_cost_cents`; computes `promo_food_cost_bps` as
        `promo_plate_cost_cents` multiplied by 10000, divided by
        `promo_price_cents`, rounded half up; and computes
        `forecast_contribution_cents` as `forecast_units` multiplied by the
        difference between `promo_price_cents` and `promo_plate_cost_cents`."

        Design: Corner/state_machines/price_feed_publication_reverts_a_costed_campaign_to_planned
        """
        world = self._costed_campaign_and_a_staged_rise(api)

        assert_lto_campaign(
            world["costed"],
            status=LtoStatus.COSTED,
            region_code=RegionCode.MW,
            promo_plate_cost_cents=100,
            promo_food_cost_bps=round_half_up(100 * 10_000, 380),
            forecast_contribution_cents=500 * (380 - 100),
        )
        assert_lto_campaign(
            world["costed"],
            promo_food_cost_bps=2632,
            forecast_contribution_cents=140_000,
        )

    def test_the_publication_reaches_the_menu_item_on_its_fourth_hop(
        self, api: ApiClient
    ) -> None:
        """One recipe and one menu item counted by the feed.

        PRD 3.2: "The **fourth hop** exists because plated recipes went stale.
        Every menu item whose backing recipe is one of them, and whose
        `plate_cost_state` is currently `FRESH`, flips to `STALE`; the feed's
        `affected_menu_item_count` records how many."

        Design: Corner/state_machines/price_feed_publication_reverts_a_costed_campaign_to_planned
        """
        world = self._costed_campaign_and_a_staged_rise(api)

        published = fixtures.publish_price_feed(api, world["rise"]["id"])

        assert_price_feed(
            published,
            status=PriceFeedStatus.PUBLISHED,
            superseded_price_count=1,
            affected_recipe_count=1,
            affected_menu_item_count=1,
        )

    def test_the_campaign_falls_back_to_planned_with_its_three_figures_cleared(
        self, api: ApiClient
    ) -> None:
        """A reverse edge nobody requested, driven by the item going stale.

        PRD 3.9: "It clears `promo_plate_cost_cents`, `promo_food_cost_bps` and
        `forecast_contribution_cents` back to 0 and increments the campaign's
        `version`, so a campaign can never be launched on figures nobody has
        recomputed."

        Design: Corner/state_machines/price_feed_publication_reverts_a_costed_campaign_to_planned
        """
        world = self._costed_campaign_and_a_staged_rise(api)

        fixtures.publish_price_feed(api, world["rise"]["id"])

        assert_lto_campaign(
            get_success_data(api.get_lto_campaign(world["planned"]["id"])),
            status=LtoStatus.PLANNED,
            promo_plate_cost_cents=0,
            promo_food_cost_bps=0,
            forecast_contribution_cents=0,
            version=world["costed"]["version"] + 1,
        )

    def test_the_de_costed_campaign_can_no_longer_be_launched(
        self, api: ApiClient
    ) -> None:
        """PLANNED is not a launchable status.

        PRD 2.10: "The promotion campaign is in a status the operation allows —
        `ERR_LTO_INVALID_STATE`, 409 — on campaign costing, launch, close-review
        and decision."

        Design: Corner/state_machines/price_feed_publication_reverts_a_costed_campaign_to_planned
        """
        world = self._costed_campaign_and_a_staged_rise(api)
        fixtures.publish_price_feed(api, world["rise"]["id"])

        response = api.launch_lto_campaign(
            world["planned"]["id"], CULINARY_DIRECTOR
        )

        validate_error(response, ApiErrorId.LTO_INVALID_STATE)

    def test_the_item_keeps_its_stale_plate_cost_and_its_open_campaign(
        self, api: ApiClient
    ) -> None:
        """100 cents retained, margin class reset, promotion still counted open.

        PRD 3.2: "The **fifth hop** exists because those menu items' plate costs
        went stale: each of them has its `margin_class` reset to `UNCLASSIFIED`."

        Design: Corner/state_machines/price_feed_publication_reverts_a_costed_campaign_to_planned
        """
        world = self._costed_campaign_and_a_staged_rise(api)

        fixtures.publish_price_feed(api, world["rise"]["id"])

        assert_menu_item(
            get_success_data(api.get_menu_item(world["menu_item"]["id"])),
            status=MenuItemStatus.ACTIVE,
            plate_cost_state=CostState.STALE,
            plate_cost_cents=100,
            margin_class=MarginClass.UNCLASSIFIED,
            is_lto=False,
            open_lto_count=1,
        )


class TestThirdPublicationStopsAtAnAlreadyStaleRecipe:
    """The cascade counts flips, not memberships, so a stale target counts zero."""

    @staticmethod
    def _two_staged_rises_over_a_live_item(api: ApiClient):
        """25000000 and then 26000000 waiting in two separate DRAFT feeds."""
        world = fixtures.grill_world_active_item(api)
        world["second"] = fixtures.stage_price_feed(
            api,
            world["cheddar"]["id"],
            25_000_000,
            effective_from="2026-07-15T00:00:00.000Z",
        )
        world["third"] = fixtures.stage_price_feed(
            api,
            world["cheddar"]["id"],
            26_000_000,
            effective_from="2026-07-20T00:00:00.000Z",
        )
        return world

    def test_the_founding_publication_predates_every_recipe_so_counts_nothing(
        self, api: ApiClient
    ) -> None:
        """No recipe existed to flip when the first price became real.

        PRD 3.2: "The **second hop** exists because a price for some ingredient
        became published. Every recipe that holds an active ingredient component
        pointing at that ingredient, and whose `cost_state` is currently `FRESH`,
        flips to `STALE`."

        Design: Corner/state_machines/third_feed_publication_counts_no_affected_recipe_because_it_is_already_stale
        """
        world = self._two_staged_rises_over_a_live_item(api)

        assert_price_feed(
            world["feed"],
            status=PriceFeedStatus.PUBLISHED,
            affected_recipe_count=0,
            affected_menu_item_count=0,
            superseded_price_count=0,
        )

    def test_the_second_publication_flips_the_fresh_recipe_and_its_item(
        self, api: ApiClient
    ) -> None:
        """One superseded row, one recipe, one menu item.

        PRD 3.2: "The feed's `affected_recipe_count` records the number of
        distinct recipes flipped across the second and third hops together"

        Design: Corner/state_machines/third_feed_publication_counts_no_affected_recipe_because_it_is_already_stale
        """
        world = self._two_staged_rises_over_a_live_item(api)

        published = fixtures.publish_price_feed(api, world["second"]["id"])

        assert_price_feed(
            published,
            superseded_price_count=1,
            affected_recipe_count=1,
            affected_menu_item_count=1,
        )

    def test_the_third_publication_supersedes_a_row_but_counts_no_recipe(
        self, api: ApiClient
    ) -> None:
        """Already STALE means neither counted nor propagated from.

        PRD 3.2: "a recipe that was already `STALE` is neither counted nor used as
        a starting point for further propagation"

        Design: Corner/state_machines/third_feed_publication_counts_no_affected_recipe_because_it_is_already_stale
        """
        world = self._two_staged_rises_over_a_live_item(api)
        fixtures.publish_price_feed(api, world["second"]["id"])

        third = fixtures.publish_price_feed(api, world["third"]["id"])

        assert_price_feed(
            third,
            status=PriceFeedStatus.PUBLISHED,
            superseded_price_count=1,
            affected_recipe_count=0,
            affected_menu_item_count=0,
        )

    def test_the_recipe_still_carries_the_figures_its_only_roll_up_wrote(
        self, api: ApiClient
    ) -> None:
        """3880071 survives two price rises, because nothing recomputed it.

        PRD 2.6: "A recipe that flips from `FRESH` to `STALE` keeps the
        `batch_cost_micros` and `portion_cost_micros` the last roll-up wrote, and
        every component keeps the `unit_cost_micros_used`,
        `pack_base_units_snapshot` and `extended_cost_micros` it was last given."

        Design: Corner/state_machines/third_feed_publication_counts_no_affected_recipe_because_it_is_already_stale
        """
        world = self._two_staged_rises_over_a_live_item(api)
        fixtures.publish_price_feed(api, world["second"]["id"])
        fixtures.publish_price_feed(api, world["third"]["id"])

        assert_recipe(
            get_success_data(api.get_recipe(world["recipe"]["id"])),
            cost_state=CostState.STALE,
            batch_cost_micros=3_880_071,
            portion_cost_micros=970_018,
        )
        assert_recipe_component(
            get_success_data(api.get_recipe_component(world["component"]["id"])),
            unit_cost_micros_used=22_000_000,
            extended_cost_micros=3_880_071,
        )
        rows, meta = validate_paginated(
            api.list_ingredient_prices(
                world["cheddar"]["id"],
                {"status": IngredientPriceStatus.PUBLISHED},
            )
        )
        assert meta["total_count"] == 1
        assert_ingredient_price(single_row(rows), pack_cost_micros=26_000_000)


class TestReviewAutoAdvancesOnItsFirstMixLine:
    """A transition nobody requests, fired by the arrival of the first line."""

    @staticmethod
    def _open_review_over_two_live_items(api: ApiClient):
        """Two ACTIVE items at 100 cents a plate and one OPEN sales-mix review."""
        world = fixtures.grill_world_active_item(api)
        world["side"] = fixtures.add_menu_item_to_world(
            api,
            world,
            code="MI-SIDE-MW",
            name="Cheese Side",
            current_price_cents=500,
        )
        world["unit"] = fixtures.create_unit(api)
        world["review"] = fixtures.open_review(api, world["unit"]["id"])
        return world

    def test_the_review_opens_with_seven_zeroed_aggregates_and_no_close_instant(
        self, api: ApiClient
    ) -> None:
        """OPEN, everything at 0, `closed_at` null.

        PRD 3.8: "The review opens in `status` `OPEN` with `total_units_sold`,
        `total_gross_sales_cents`, `popularity_threshold_bps`,
        `margin_threshold_cents`, `theoretical_food_cost_cents`,
        `actual_food_cost_cents` and `variance_bps` all 0, `variance_flag` unset
        until close, and a null `closed_at`."

        Design: Corner/state_machines/review_auto_advances_to_mix_loaded_on_its_first_mix_line
        """
        world = self._open_review_over_two_live_items(api)

        assert_period_review(
            world["review"],
            status=ReviewStatus.OPEN,
            basis=ReviewBasis.SALES_MIX_BASED,
            total_units_sold=0,
            total_gross_sales_cents=0,
            popularity_threshold_bps=0,
            margin_threshold_cents=0,
            theoretical_food_cost_cents=0,
            actual_food_cost_cents=0,
            variance_bps=0,
            closed_at=None,
        )

    def test_the_first_line_freezes_the_items_plate_cost_at_loading_time(
        self, api: ApiClient
    ) -> None:
        """100 cents copied onto the line, not read live at close.

        PRD 3.8: "The line freezes `plate_cost_cents_snapshot` from the item's
        `plate_cost_cents` at the moment of loading, and every later
        classification and close values that line with the snapshot rather than
        with the item's live plate cost."

        Design: Corner/state_machines/review_auto_advances_to_mix_loaded_on_its_first_mix_line
        """
        world = self._open_review_over_two_live_items(api)

        first = fixtures.load_mix_line(
            api, world["review"]["id"], world["menu_item"]["id"]
        )

        assert_mix_line(
            first,
            period_review_id=world["review"]["id"],
            menu_item_id=world["menu_item"]["id"],
            units_sold=100,
            gross_sales_cents=40_000,
            plate_cost_cents_snapshot=100,
        )

    def test_the_first_line_advances_the_review_without_an_explicit_request(
        self, api: ApiClient
    ) -> None:
        """OPEN becomes MIX_LOADED, and the two totals follow the line.

        PRD 3.8: "The **first** line auto-advances the review from `OPEN` to
        `MIX_LOADED` without any explicit request; later lines leave it in
        `MIX_LOADED`."

        Design: Corner/state_machines/review_auto_advances_to_mix_loaded_on_its_first_mix_line
        """
        world = self._open_review_over_two_live_items(api)

        fixtures.load_mix_line(api, world["review"]["id"], world["menu_item"]["id"])

        assert_period_review(
            get_success_data(api.get_period_review(world["review"]["id"])),
            status=ReviewStatus.MIX_LOADED,
            total_units_sold=100,
            total_gross_sales_cents=40_000,
            version=world["review"]["version"] + 1,
        )

    def test_the_second_line_recomputes_the_totals_and_holds_the_status(
        self, api: ApiClient
    ) -> None:
        """140 units and 60000 cents, still MIX_LOADED.

        PRD 3.8: "Loading a line recomputes the review's `total_units_sold` and
        `total_gross_sales_cents` from all of its mix lines and increments the
        review's `version`."

        Design: Corner/state_machines/review_auto_advances_to_mix_loaded_on_its_first_mix_line
        """
        world = self._open_review_over_two_live_items(api)
        fixtures.load_mix_line(api, world["review"]["id"], world["menu_item"]["id"])

        second = fixtures.load_mix_line(
            api,
            world["review"]["id"],
            world["side"]["id"],
            units_sold=40,
            gross_sales_cents=20_000,
        )

        assert_mix_line(second, plate_cost_cents_snapshot=100)
        assert_period_review(
            get_success_data(api.get_period_review(world["review"]["id"])),
            status=ReviewStatus.MIX_LOADED,
            total_units_sold=140,
            total_gross_sales_cents=60_000,
            version=world["review"]["version"] + 2,
        )

    def test_the_lines_are_listed_in_loading_order(self, api: ApiClient) -> None:
        """Two rows, the auto-advancing one first.

        PRD 3.8: "Mix lines are listed per review in `created_at` ascending
        order."

        Design: Corner/state_machines/review_auto_advances_to_mix_loaded_on_its_first_mix_line
        """
        world = self._open_review_over_two_live_items(api)
        first = fixtures.load_mix_line(
            api, world["review"]["id"], world["menu_item"]["id"]
        )
        second = fixtures.load_mix_line(
            api,
            world["review"]["id"],
            world["side"]["id"],
            units_sold=40,
            gross_sales_cents=20_000,
        )

        rows, meta = validate_paginated(api.list_mix_lines(world["review"]["id"]))

        assert meta["total_count"] == 2
        assert ids_of(rows) == [first["id"], second["id"]]


class TestSpecChangeRejectionIsTheNullEffectArm:
    """The only thing a rejected order costs the recipe is version numbers."""

    @staticmethod
    def _pending_quantity_change(api: ApiClient):
        """An ACTIVE recipe at version 5 carrying one PENDING order to 600 grams."""
        world = fixtures.grill_world_active_recipe(api)
        order = fixtures.open_qty_change(
            api,
            world["recipe"]["id"],
            world["component"]["id"],
            new_ep_quantity_base_units=600,
        )
        world["order"] = fixtures.submit_change_order(api, order["id"])
        return world

    def test_submission_records_its_author_and_leaves_the_order_pending(
        self, api: ApiClient
    ) -> None:
        """The submitter is stamped from the caller's identity.

        PRD 3.6: "Submission records the caller as `submitted_by_user_id` and
        increments the order's `version`."

        Design: Corner/state_machines/spec_change_order_reject_leaves_the_specification_untouched
        """
        world = self._pending_quantity_change(api)

        assert_spec_change_order(
            world["order"],
            approval_status=ApprovalStatus.PENDING,
            propagation_status=PropagationStatus.NOT_STARTED,
            submitted_by_user_id=SUBMITTER_USER_ID,
            new_ep_quantity_base_units=600,
        )

    def test_opening_the_order_already_charged_the_recipe_one_version(
        self, api: ApiClient
    ) -> None:
        """Version 6 and one open order, before any decision is taken.

        PRD 2.4: "When a specification change order opens against a recipe and
        pushes that recipe's `open_spec_change_count` up by one, the recipe's
        `version` increments"

        Design: Corner/state_machines/spec_change_order_reject_leaves_the_specification_untouched
        """
        world = self._pending_quantity_change(api)

        assert_recipe(
            get_success_data(api.get_recipe(world["recipe"]["id"])),
            status=RecipeStatus.ACTIVE,
            open_spec_change_count=1,
            version=world["recipe"]["version"] + 1,
        )

    def test_rejection_stores_the_reason_and_releases_the_open_counter(
        self, api: ApiClient
    ) -> None:
        """REJECTED with the supplied reason, and the recipe at version 7.

        PRD 3.6: "**Rejection** moves `PENDING` to `REJECTED` and is the
        `CulinaryDirector`'s. It stores the supplied `rejection_reason`, decrements
        the recipe's `open_spec_change_count` and increments the recipe's
        `version`."

        Design: Corner/state_machines/spec_change_order_reject_leaves_the_specification_untouched
        """
        world = self._pending_quantity_change(api)

        rejected = get_success_data(
            api.reject_spec_change_order(
                world["order"]["id"],
                make_culinary_director_headers(APPROVER_USER_ID),
                {"rejection_reason": "portion size stays at 400"},
            )
        )

        assert_spec_change_order(
            rejected,
            approval_status=ApprovalStatus.REJECTED,
            rejection_reason="portion size stays at 400",
        )
        assert_recipe(
            get_success_data(api.get_recipe(world["recipe"]["id"])),
            open_spec_change_count=0,
            version=world["recipe"]["version"] + 2,
        )

    def test_rejection_takes_no_snapshot_and_names_no_approver(
        self, api: ApiClient
    ) -> None:
        """The fields an approval would have filled stay exactly as they opened.

        PRD 3.6: "The new order opens with `approval_status` `DRAFT`,
        `propagation_status` `NOT_STARTED`, and null `submitted_by_user_id`,
        `approved_by_user_id`, `rejection_reason`, `created_component_id`,
        `approved_at` and every `pre_change_` snapshot."

        Design: Corner/state_machines/spec_change_order_reject_leaves_the_specification_untouched
        """
        world = self._pending_quantity_change(api)

        api.reject_spec_change_order(
            world["order"]["id"],
            make_culinary_director_headers(APPROVER_USER_ID),
            {"rejection_reason": "portion size stays at 400"},
        )

        rejected = get_success_data(
            api.get_spec_change_order(world["order"]["id"])
        )
        assert rejected["approved_by_user_id"] is None
        assert rejected["approved_at"] is None
        assert rejected["created_component_id"] is None
        assert rejected["pre_change_batch_cost_micros"] is None
        assert rejected["pre_change_ep_quantity_base_units"] is None
        assert rejected["pre_change_allergen_mask"] is None
        assert rejected["pre_change_recipe_version"] is None

    def test_the_specification_and_the_cost_state_come_through_unchanged(
        self, api: ApiClient
    ) -> None:
        """Still 400 grams, still 3880071 micros, still FRESH.

        PRD 3.6: "Critically it leaves the recipe specification completely
        untouched and the recipe's `cost_state` exactly as it was — a rejected
        order costs the recipe nothing but a version bump"

        Design: Corner/state_machines/spec_change_order_reject_leaves_the_specification_untouched
        """
        world = self._pending_quantity_change(api)

        api.reject_spec_change_order(
            world["order"]["id"],
            make_culinary_director_headers(APPROVER_USER_ID),
            {"rejection_reason": "portion size stays at 400"},
        )

        assert_recipe_component(
            get_success_data(api.get_recipe_component(world["component"]["id"])),
            status=ComponentStatus.ACTIVE,
            ep_quantity_base_units=400,
            ap_quantity_base_units=400,
            extended_cost_micros=3_880_071,
        )
        assert_recipe(
            get_success_data(api.get_recipe(world["recipe"]["id"])),
            cost_state=CostState.FRESH,
            batch_cost_micros=3_880_071,
            component_count=1,
        )

    def test_the_rejected_order_is_filterable_and_never_propagates(
        self, api: ApiClient
    ) -> None:
        """One REJECTED row, NOT_STARTED forever, prep guide untouched.

        PRD 3.6: "it leaves `propagation_status` at `NOT_STARTED` forever, since
        there is nothing to propagate"

        Design: Corner/state_machines/spec_change_order_reject_leaves_the_specification_untouched
        """
        world = self._pending_quantity_change(api)
        api.reject_spec_change_order(
            world["order"]["id"],
            make_culinary_director_headers(APPROVER_USER_ID),
            {"rejection_reason": "portion size stays at 400"},
        )

        rows, meta = validate_paginated(
            api.list_spec_change_orders(
                {"approval_status": ApprovalStatus.REJECTED}
            )
        )

        assert meta["total_count"] == 1
        assert_spec_change_order(
            single_row(rows),
            id=world["order"]["id"],
            propagation_status=PropagationStatus.NOT_STARTED,
        )
        assert_prep_guide(
            fixtures.sole_prep_guide(api, world["recipe"]["id"]),
            revision_no=1,
            sync_state=SyncState.CURRENT,
        )


class TestPromotionRetirementSuspendsAndReactivates:
    """RETIRE suspends the item whatever the verdict, and activation closes the loop."""

    @staticmethod
    def _launched_campaign_at_its_window_end(api: ApiClient):
        """A LAUNCHED campaign forecast at 100 units, with the clock at window end."""
        world = fixtures.grill_world_active_item(api)
        planned = fixtures.plan_lto(
            api, world["menu_item"]["id"], forecast_units=100
        )
        fixtures.cost_lto(api, planned["id"])
        world["launched"] = fixtures.launch_lto(api, planned["id"])
        fixtures.set_clock(api, "2026-08-15T00:00:00.000Z")
        world["campaign"] = planned
        return world

    def test_launching_flags_the_item_as_promoting(self, api: ApiClient) -> None:
        """LAUNCHED on the campaign, `is_lto` true on the item.

        PRD 3.9: "Launching sets the item's `is_lto` to true and increments the
        item's `version`, and increments the campaign's `version`."

        Design: Corner/state_machines/menu_item_suspended_by_lto_retire_then_reactivated_closes_the_cycle
        """
        world = self._launched_campaign_at_its_window_end(api)

        assert_lto_campaign(
            world["launched"],
            status=LtoStatus.LAUNCHED,
            promo_plate_cost_cents=100,
            forecast_units=100,
        )
        assert_menu_item(
            get_success_data(api.get_menu_item(world["menu_item"]["id"])),
            is_lto=True,
            open_lto_count=1,
            status=MenuItemStatus.ACTIVE,
        )

    def test_the_post_promotion_review_values_the_run_at_the_frozen_plate_cost(
        self, api: ApiClient
    ) -> None:
        """1140 cents of support against 26860 cents of contribution.

        PRD 3.9: "`promo_contribution_cents` is `actual_gross_sales_cents`, minus
        `actual_units` multiplied by `promo_plate_cost_cents`, minus
        `promo_support_cost_cents`; note that it is valued at the plate cost the
        *costing run froze*, not at whatever the item's plate cost is today."

        Design: Corner/state_machines/menu_item_suspended_by_lto_retire_then_reactivated_closes_the_cycle
        """
        world = self._launched_campaign_at_its_window_end(api)

        closed = fixtures.close_lto_review(api, world["campaign"]["id"], 100, 38_000)

        assert_lto_campaign(
            closed,
            status=LtoStatus.CLOSED,
            actual_units=100,
            actual_gross_sales_cents=38_000,
            promo_support_cost_cents=round_half_up(38_000 * 300, 10_000),
            promo_contribution_cents=38_000 - 100 * 100 - 1140,
        )
        assert_lto_campaign(
            closed, promo_support_cost_cents=1140, promo_contribution_cents=26_860
        )
        assert closed["reviewed_at"] is not None

    def test_both_thresholds_are_met_so_the_verdict_is_profitable(
        self, api: ApiClient
    ) -> None:
        """Contribution above zero and attainment at exactly 10000 basis points.

        PRD 3.9: "The `verdict` becomes `PROFITABLE` only when **both** conditions
        hold: `promo_contribution_cents` is at least the minimum contribution of 0
        cents, and `forecast_attainment_bps` is at least the minimum attainment of
        8000 basis points."

        Design: Corner/state_machines/menu_item_suspended_by_lto_retire_then_reactivated_closes_the_cycle
        """
        world = self._launched_campaign_at_its_window_end(api)

        closed = fixtures.close_lto_review(api, world["campaign"]["id"], 100, 38_000)

        assert_lto_campaign(
            closed,
            forecast_attainment_bps=round_half_up(100 * 10_000, 100),
            verdict=LtoVerdict.PROFITABLE,
        )
        assert closed["forecast_attainment_bps"] == 10_000
        assert_menu_item(
            get_success_data(api.get_menu_item(world["menu_item"]["id"])),
            is_lto=False,
            open_lto_count=0,
        )

    def test_the_retire_arm_mints_no_successor_campaign(
        self, api: ApiClient
    ) -> None:
        """RETIRED and exactly one campaign against this item, ever.

        PRD 3.9: "It moves the campaign to `RETIRED`, mints no successor campaign
        whatsoever, and instead sets the backing menu item's `status` to
        `SUSPENDED`, resets its `margin_class` to `UNCLASSIFIED`, sets its `is_lto`
        to false and increments its `version`."

        Design: Corner/state_machines/menu_item_suspended_by_lto_retire_then_reactivated_closes_the_cycle
        """
        world = self._launched_campaign_at_its_window_end(api)
        fixtures.close_lto_review(api, world["campaign"]["id"], 100, 38_000)

        retired = fixtures.decide_lto(
            api, world["campaign"]["id"], decision=LtoDecision.RETIRE
        )

        # PRD 3.9 enumerates the campaign's persisted attributes and never lists
        # `decision`: it is a request-body input on /decide, and the fork it
        # selects is recorded in `status` (RENEWED vs RETIRED).  Only the
        # PRD-covered status transition is asserted here.
        assert_lto_campaign(retired, status=LtoStatus.RETIRED)
        rows, meta = validate_paginated(
            api.list_lto_campaigns({"menu_item_id": world["menu_item"]["id"]})
        )
        assert meta["total_count"] == 1
        assert ids_of(rows) == [world["campaign"]["id"]]

    def test_a_profitable_promotion_suspends_the_item_exactly_as_a_losing_one_would(
        self, api: ApiClient
    ) -> None:
        """SUSPENDED and UNCLASSIFIED despite the PROFITABLE verdict.

        PRD 3.9: "The suspension follows the `RETIRE` arm itself and never consults
        the `verdict`: retiring a `PROFITABLE` campaign suspends the item exactly
        as retiring an `UNPROFITABLE` one does."

        Design: Corner/state_machines/menu_item_suspended_by_lto_retire_then_reactivated_closes_the_cycle
        """
        world = self._launched_campaign_at_its_window_end(api)
        closed = fixtures.close_lto_review(api, world["campaign"]["id"], 100, 38_000)
        assert closed["verdict"] == LtoVerdict.PROFITABLE

        fixtures.decide_lto(
            api, world["campaign"]["id"], decision=LtoDecision.RETIRE
        )

        assert_menu_item(
            get_success_data(api.get_menu_item(world["menu_item"]["id"])),
            status=MenuItemStatus.SUSPENDED,
            margin_class=MarginClass.UNCLASSIFIED,
            is_lto=False,
            plate_cost_state=CostState.FRESH,
            plate_cost_cents=100,
            open_lto_count=0,
        )

    def test_reactivation_from_suspended_closes_the_cycle_back_to_active(
        self, api: ApiClient
    ) -> None:
        """The campaign is terminal, but the item goes round again.

        PRD 3.5: "**Activation** belongs to the `CulinaryDirector` and admits an
        item to the menu from either `DRAFT` or `SUSPENDED` — the `SUSPENDED` arm
        is what closes the cycle back to `ACTIVE` after a retired promotion."

        Design: Corner/state_machines/menu_item_suspended_by_lto_retire_then_reactivated_closes_the_cycle
        """
        world = self._launched_campaign_at_its_window_end(api)
        fixtures.close_lto_review(api, world["campaign"]["id"], 100, 38_000)
        fixtures.decide_lto(
            api, world["campaign"]["id"], decision=LtoDecision.RETIRE
        )
        suspended = get_success_data(api.get_menu_item(world["menu_item"]["id"]))

        repeat = api.decide_lto_campaign(
            world["campaign"]["id"],
            factories.decide_payload(LtoDecision.RENEW),
            CULINARY_DIRECTOR,
        )
        reactivated = fixtures.activate_menu_item(api, world["menu_item"]["id"])

        validate_error(repeat, ApiErrorId.LTO_INVALID_STATE)
        assert_menu_item(
            reactivated,
            status=MenuItemStatus.ACTIVE,
            version=suspended["version"] + 1,
            plate_cost_state=CostState.FRESH,
            plate_cost_cents=100,
            is_lto=False,
        )
