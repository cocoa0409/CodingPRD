"""The concurrency guards and the derived counters they move.

All three recipe-parented writes and the one menu-item-parented write are probed
with the version their caller legitimately held exactly one write ago, and the
open-order counter is followed up through two creates and back down through a
rejection and an approval.
"""

from test_helpers import (
    ALLERGEN_GLUTEN,
    ApiClient,
    ApiErrorId,
    ApprovalStatus,
    COST_ANALYST,
    ComponentStatus,
    CostState,
    LtoStatus,
    MarginClass,
    PropagationStatus,
    RECIPE_DEVELOPER,
    RegionCode,
    APPROVER_USER_ID,
    assert_fields,
    assert_lto_campaign,
    assert_menu_item,
    assert_recipe,
    assert_recipe_component,
    assert_spec_change_order,
    factories,
    fixtures,
    get_success_data,
    make_culinary_director_headers,
    micros_to_cents,
    plate_cost_micros,
    round_half_up,
    validate_error,
)


class TestEveryRecipeParentedWriteRejectsAStaleVersion:
    """One integer apart: the same request, informed or blind."""

    @staticmethod
    def _two_recipes(api: ApiClient):
        """A DRAFT recipe one write past its create, and an ACTIVE one beside it."""
        cheddar = fixtures.create_cheddar(api)
        flour = fixtures.create_ingredient(
            api,
            sku="WHEAT-FLOUR",
            name="Bread Flour",
            pack_base_units=22_680,
            allergen_mask=ALLERGEN_GLUTEN,
            kcal_per_base_unit_micros=3_500_000,
            sodium_mcg_per_base_unit=20,
        )
        feed = fixtures.open_price_feed(api)
        fixtures.add_price_line(api, feed["id"], cheddar["id"], pack_cost_micros=22_000_000)
        fixtures.add_price_line(api, feed["id"], flour["id"], pack_cost_micros=12_000_000)
        fixtures.publish_price_feed(api, feed["id"])

        draft = fixtures.create_recipe(api, code="PLATE-DRAFT", name="Draft Plate")
        draft_version_at_create = draft["version"]
        fixtures.add_ingredient_component(api, draft["id"], cheddar["id"])

        live = fixtures.create_recipe(api, code="PLATE-LIVE", name="Live Plate")
        live_component = fixtures.add_ingredient_component(
            api, live["id"], cheddar["id"]
        )
        fixtures.rollup(api, live["id"])
        live = fixtures.review_and_activate_recipe(api, live["id"])

        return {
            "cheddar": cheddar,
            "flour": flour,
            "draft": draft,
            "draft_version_at_create": draft_version_at_create,
            "draft_version_now": fixtures.recipe_version(api, draft["id"]),
            "live": live,
            "live_component": live_component,
        }

    @staticmethod
    def _second_component_payload(world, expected_recipe_version: int):
        """A flour line at sequence two — a perfectly legitimate second append."""
        return factories.ingredient_component_payload(
            world["flour"]["id"],
            expected_recipe_version,
            ep_quantity_base_units=200,
            sequence_no=2,
        )

    def test_appending_with_the_version_from_one_write_ago_is_refused(
        self, api: ApiClient
    ) -> None:
        """Only the version can tell an informed append from a blind one.

        PRD 2.7: "A state precondition cannot substitute here: appending a second,
        different component to a recipe is entirely legitimate product behaviour,
        so the only thing distinguishing an informed append from one authored
        against a specification the client can no longer see is whether the
        expected version still matches."

        Design: Corner/cross_cutting_complexity_layers/every_recipe_parented_write_rejects_a_stale_expected_recipe_version
        """
        world = self._two_recipes(api)

        refused = api.add_recipe_component(
            world["draft"]["id"],
            self._second_component_payload(world, world["draft_version_at_create"]),
            RECIPE_DEVELOPER,
        )

        validate_error(refused, ApiErrorId.STALE_RECIPE_VERSION, 412)

    def test_the_refused_append_left_neither_version_nor_component_set_touched(
        self, api: ApiClient
    ) -> None:
        """A 412 leaves no residue behind it.

        PRD 2.10: "no later rule is evaluated and no partial mutation is persisted"

        Design: Corner/cross_cutting_complexity_layers/every_recipe_parented_write_rejects_a_stale_expected_recipe_version
        """
        world = self._two_recipes(api)
        validate_error(
            api.add_recipe_component(
                world["draft"]["id"],
                self._second_component_payload(world, world["draft_version_at_create"]),
                RECIPE_DEVELOPER,
            ),
            ApiErrorId.STALE_RECIPE_VERSION,
            412,
        )

        stored = get_success_data(api.get_recipe(world["draft"]["id"]))

        assert_recipe(
            stored, version=world["draft_version_now"], component_count=1
        )

    def test_the_retry_with_the_current_version_succeeds(
        self, api: ApiClient
    ) -> None:
        """The same request, one integer different.

        PRD 2.7: "If it does not equal the recipe's stored `version`, the request is
        rejected with `ERR_STALE_RECIPE_VERSION` and HTTP 412."

        Design: Corner/cross_cutting_complexity_layers/every_recipe_parented_write_rejects_a_stale_expected_recipe_version
        """
        world = self._two_recipes(api)

        get_success_data(
            api.add_recipe_component(
                world["draft"]["id"],
                self._second_component_payload(world, world["draft_version_now"]),
                RECIPE_DEVELOPER,
            ),
            201,
        )

        stored = get_success_data(api.get_recipe(world["draft"]["id"]))
        assert_recipe(
            stored, component_count=2, version=world["draft_version_now"] + 1
        )

    def test_the_delete_guard_rejects_the_version_the_add_invalidated(
        self, api: ApiClient
    ) -> None:
        """The successful append is what made the caller's read obsolete.

        PRD 2.7: "Removing a second, different component is likewise legitimate, so
        the stale-version comparison is the only way to detect that the caller
        decided against a specification they are no longer looking at."

        Design: Corner/cross_cutting_complexity_layers/every_recipe_parented_write_rejects_a_stale_expected_recipe_version
        """
        world = self._two_recipes(api)
        second = get_success_data(
            api.add_recipe_component(
                world["draft"]["id"],
                self._second_component_payload(world, world["draft_version_now"]),
                RECIPE_DEVELOPER,
            ),
            201,
        )

        refused = api.delete_recipe_component(
            second["id"],
            factories.component_delete_params(world["draft_version_now"]),
            RECIPE_DEVELOPER,
        )

        validate_error(refused, ApiErrorId.STALE_RECIPE_VERSION, 412)
        assert_recipe_component(
            get_success_data(api.get_recipe_component(second["id"])),
            status=ComponentStatus.ACTIVE,
        )

    def test_the_delete_succeeds_once_the_current_version_is_supplied(
        self, api: ApiClient
    ) -> None:
        """The removal itself was never in question.

        PRD 2.7: "`DELETE /culinary/recipe-components/{recipe_component_id}`
        requires `expected_recipe_version` as a non-optional body field, carrying
        the client's last observed `version` of the `Recipe` that owns the
        component."

        Design: Corner/cross_cutting_complexity_layers/every_recipe_parented_write_rejects_a_stale_expected_recipe_version
        """
        world = self._two_recipes(api)
        second = get_success_data(
            api.add_recipe_component(
                world["draft"]["id"],
                self._second_component_payload(world, world["draft_version_now"]),
                RECIPE_DEVELOPER,
            ),
            201,
        )

        removed = get_success_data(
            api.delete_recipe_component(
                second["id"],
                factories.component_delete_params(
                    fixtures.recipe_version(api, world["draft"]["id"])
                ),
                RECIPE_DEVELOPER,
            )
        )

        assert_recipe_component(removed, status=ComponentStatus.REMOVED)

    def test_opening_an_order_moves_the_recipes_own_counter_and_version(
        self, api: ApiClient
    ) -> None:
        """The create's own side effect is what will invalidate the next one.

        PRD 3.6: "Creating the order increments the recipe's
        `open_spec_change_count` and its `version` — which is exactly why a second
        order authored against the same read of the recipe is rejected by the
        version guard."

        Design: Corner/cross_cutting_complexity_layers/every_recipe_parented_write_rejects_a_stale_expected_recipe_version
        """
        world = self._two_recipes(api)
        assert_recipe(world["live"], open_spec_change_count=0)

        fixtures.open_qty_change(
            api,
            world["live"]["id"],
            world["live_component"]["id"],
            new_ep_quantity_base_units=500,
        )

        stored = get_success_data(api.get_recipe(world["live"]["id"]))
        assert_recipe(
            stored,
            open_spec_change_count=1,
            version=world["live"]["version"] + 1,
        )

    def test_a_second_order_from_the_same_read_of_the_recipe_is_refused(
        self, api: ApiClient
    ) -> None:
        """A client that never re-reads the recipe can never file two orders.

        PRD 2.7: "Because opening an order itself increments the recipe's `version`
        (it moves `open_spec_change_count`), a second order authored from the same
        read of the recipe is guaranteed to be caught by this guard; a genuinely
        sequential second order, authored after re-reading the recipe, passes."

        Design: Corner/cross_cutting_complexity_layers/every_recipe_parented_write_rejects_a_stale_expected_recipe_version
        """
        world = self._two_recipes(api)
        fixtures.open_qty_change(
            api,
            world["live"]["id"],
            world["live_component"]["id"],
            new_ep_quantity_base_units=500,
        )

        refused = api.create_spec_change_order(
            factories.component_qty_change_payload(
                world["live"]["id"],
                world["live_component"]["id"],
                world["live"]["version"],
                new_ep_quantity_base_units=600,
            ),
            RECIPE_DEVELOPER,
        )

        validate_error(refused, ApiErrorId.STALE_RECIPE_VERSION, 412)

    def test_the_refused_order_create_incremented_no_counter(
        self, api: ApiClient
    ) -> None:
        """The counter is not driven by attempts.

        PRD 3.6: "Creating the order increments the recipe's
        `open_spec_change_count` and its `version`"

        Design: Corner/cross_cutting_complexity_layers/every_recipe_parented_write_rejects_a_stale_expected_recipe_version
        """
        world = self._two_recipes(api)
        fixtures.open_qty_change(
            api,
            world["live"]["id"],
            world["live_component"]["id"],
            new_ep_quantity_base_units=500,
        )
        after_first = fixtures.recipe_version(api, world["live"]["id"])
        validate_error(
            api.create_spec_change_order(
                factories.component_qty_change_payload(
                    world["live"]["id"],
                    world["live_component"]["id"],
                    world["live"]["version"],
                    new_ep_quantity_base_units=600,
                ),
                RECIPE_DEVELOPER,
            ),
            ApiErrorId.STALE_RECIPE_VERSION,
            412,
        )

        stored = get_success_data(api.get_recipe(world["live"]["id"]))

        assert_recipe(stored, version=after_first, open_spec_change_count=1)

    def test_the_refreshed_version_files_the_second_order(
        self, api: ApiClient
    ) -> None:
        """A genuinely sequential second order passes the same guard.

        PRD 3.6: "A `RecipeDeveloper` opens an order against a recipe that must be
        `ACTIVE` — any other status is refused with `ERR_RECIPE_INVALID_STATE` — and
        must supply `expected_recipe_version`, because the whole point of an order
        is that it targets a specification the author has actually read."

        Design: Corner/cross_cutting_complexity_layers/every_recipe_parented_write_rejects_a_stale_expected_recipe_version
        """
        world = self._two_recipes(api)
        fixtures.open_qty_change(
            api,
            world["live"]["id"],
            world["live_component"]["id"],
            new_ep_quantity_base_units=500,
        )

        second = fixtures.open_qty_change(
            api,
            world["live"]["id"],
            world["live_component"]["id"],
            new_ep_quantity_base_units=600,
        )

        assert_spec_change_order(
            second,
            approval_status=ApprovalStatus.DRAFT,
            propagation_status=PropagationStatus.NOT_STARTED,
        )
        assert_recipe(
            get_success_data(api.get_recipe(world["live"]["id"])),
            open_spec_change_count=2,
        )


class TestAPromotionPlannedAgainstAnObsoleteItemRead:
    """The version tracks writes, not value changes.

    Several campaigns on disjoint windows are expected, so nothing but the
    expected version can reject a plan authored against a price that has moved.
    """

    @staticmethod
    def _item_recosted_to_the_identical_figure(api: ApiClient):
        """An ACTIVE item whose plate cost is re-run and lands on the same cents."""
        world = fixtures.grill_world_active_item(api)
        world["version_at_activation"] = world["menu_item"]["version"]
        world["recosted"] = fixtures.plate_cost(api, world["menu_item"]["id"])
        return world

    @staticmethod
    def _campaign_payload(world, expected_menu_item_version: int, month: str):
        """A fortnight-long promotion at 380 cents in the named month."""
        return factories.lto_campaign_payload(
            world["menu_item"]["id"],
            expected_menu_item_version,
            window_start=f"2026-{month}-01T00:00:00.000Z",
            window_end=f"2026-{month}-15T00:00:00.000Z",
        )

    def test_a_recomputation_that_changes_nothing_still_bumps_the_version(
        self, api: ApiClient
    ) -> None:
        """The same 100 cents, and a version one higher for having said so.

        PRD 3.5: "sets `plate_cost_state` to `FRESH` and increments the item's
        `version`"

        Design: Corner/cross_cutting_complexity_layers/an_lto_campaign_planned_against_an_obsolete_menu_item_read_is_rejected
        """
        world = self._item_recosted_to_the_identical_figure(api)

        assert_menu_item(
            world["recosted"],
            plate_cost_cents=micros_to_cents(plate_cost_micros(970_018, RegionCode.MW)),
            version=world["version_at_activation"] + 1,
        )
        assert_fields(world["recosted"], plate_cost_cents=100)
        assert world["menu_item"]["plate_cost_cents"] == 100

    def test_the_obsolete_read_is_a_precondition_failure_and_not_a_state_error(
        self, api: ApiClient
    ) -> None:
        """The item is ACTIVE and perfectly eligible for a promotion.

        PRD 2.7: "A mismatch with the menu item's stored `version` is rejected with
        `ERR_STALE_MENU_ITEM_VERSION` and HTTP 412."

        Design: Corner/cross_cutting_complexity_layers/an_lto_campaign_planned_against_an_obsolete_menu_item_read_is_rejected
        """
        world = self._item_recosted_to_the_identical_figure(api)

        refused = api.create_lto_campaign(
            self._campaign_payload(world, world["version_at_activation"], "09"),
            RECIPE_DEVELOPER,
        )

        validate_error(refused, ApiErrorId.STALE_MENU_ITEM_VERSION, 412)

    def test_the_refused_plan_incremented_no_counter(self, api: ApiClient) -> None:
        """The item is exactly where the recosting left it.

        PRD 2.10: "no later rule is evaluated and no partial mutation is persisted"

        Design: Corner/cross_cutting_complexity_layers/an_lto_campaign_planned_against_an_obsolete_menu_item_read_is_rejected
        """
        world = self._item_recosted_to_the_identical_figure(api)
        validate_error(
            api.create_lto_campaign(
                self._campaign_payload(world, world["version_at_activation"], "09"),
                RECIPE_DEVELOPER,
            ),
            ApiErrorId.STALE_MENU_ITEM_VERSION,
            412,
        )

        stored = get_success_data(api.get_menu_item(world["menu_item"]["id"]))

        assert_menu_item(
            stored, open_lto_count=0, version=world["recosted"]["version"]
        )

    def test_the_same_request_with_the_current_version_succeeds(
        self, api: ApiClient
    ) -> None:
        """The region is copied from the item, and the counter moves.

        PRD 2.7: "`POST /culinary/lto-campaigns` requires
        `expected_menu_item_version` as a non-optional body field, carrying the
        client's last observed `version` of the target `MenuItem`."

        Design: Corner/cross_cutting_complexity_layers/an_lto_campaign_planned_against_an_obsolete_menu_item_read_is_rejected
        """
        world = self._item_recosted_to_the_identical_figure(api)

        campaign = get_success_data(
            api.create_lto_campaign(
                self._campaign_payload(world, world["recosted"]["version"], "09"),
                RECIPE_DEVELOPER,
            ),
            201,
        )

        assert_lto_campaign(
            campaign, status=LtoStatus.PLANNED, region_code=RegionCode.MW
        )
        assert_menu_item(
            get_success_data(api.get_menu_item(world["menu_item"]["id"])),
            open_lto_count=1,
            version=world["recosted"]["version"] + 1,
        )

    def test_a_second_campaign_on_a_disjoint_window_is_refused_only_by_the_version(
        self, api: ApiClient
    ) -> None:
        """Legitimate business behaviour, caught by the first campaign's own bump.

        PRD 2.7: "A single menu item may legitimately carry several campaigns over
        disjoint windows, so the create cannot be gated on a state precondition; the
        stale expected version is what proves the promotion was planned against a
        price or a plate cost that has since moved."

        Design: Corner/cross_cutting_complexity_layers/an_lto_campaign_planned_against_an_obsolete_menu_item_read_is_rejected
        """
        world = self._item_recosted_to_the_identical_figure(api)
        get_success_data(
            api.create_lto_campaign(
                self._campaign_payload(world, world["recosted"]["version"], "09"),
                RECIPE_DEVELOPER,
            ),
            201,
        )

        refused = api.create_lto_campaign(
            self._campaign_payload(world, world["recosted"]["version"], "10"),
            RECIPE_DEVELOPER,
        )

        validate_error(refused, ApiErrorId.STALE_MENU_ITEM_VERSION, 412)

    def test_two_campaigns_coexist_once_the_version_is_refreshed(
        self, api: ApiClient
    ) -> None:
        """Proof the 412 was never a duplicate-campaign rule in disguise.

        PRD 2.7: "a genuinely sequential second order, authored after re-reading the
        recipe, passes."

        Design: Corner/cross_cutting_complexity_layers/an_lto_campaign_planned_against_an_obsolete_menu_item_read_is_rejected
        """
        world = self._item_recosted_to_the_identical_figure(api)
        get_success_data(
            api.create_lto_campaign(
                self._campaign_payload(world, world["recosted"]["version"], "09"),
                RECIPE_DEVELOPER,
            ),
            201,
        )

        second = get_success_data(
            api.create_lto_campaign(
                self._campaign_payload(
                    world,
                    fixtures.menu_item_version(api, world["menu_item"]["id"]),
                    "10",
                ),
                RECIPE_DEVELOPER,
            ),
            201,
        )

        assert_lto_campaign(second, status=LtoStatus.PLANNED)
        assert_menu_item(
            get_success_data(api.get_menu_item(world["menu_item"]["id"])),
            open_lto_count=2,
        )


class TestTheOpenSpecChangeCounterReconciles:
    """Two creates up, a rejection and an approval down, and exactly zero."""

    @staticmethod
    def _two_orders(api: ApiClient):
        """Two COMPONENT_QTY orders on the same line, filed sequentially."""
        world = fixtures.grill_world_active_item(api)
        world["version_at_activation"] = world["recipe"]["version"]
        world["order_a"] = fixtures.open_qty_change(
            api,
            world["recipe"]["id"],
            world["component"]["id"],
            new_ep_quantity_base_units=500,
        )
        world["version_after_a"] = fixtures.recipe_version(api, world["recipe"]["id"])
        world["order_b"] = fixtures.open_qty_change(
            api,
            world["recipe"]["id"],
            world["component"]["id"],
            new_ep_quantity_base_units=600,
        )
        world["version_after_b"] = fixtures.recipe_version(api, world["recipe"]["id"])
        return world

    @staticmethod
    def _reject(api: ApiClient, order_id: str, reason: str):
        """Reject with a stated reason, as an operator who is not the submitter."""
        return api.reject_spec_change_order(
            order_id,
            make_culinary_director_headers(APPROVER_USER_ID),
            {"rejection_reason": reason},
        )

    def test_an_active_recipe_carries_no_open_orders(self, api: ApiClient) -> None:
        """The starting point: nothing outstanding and the item fully costed.

        PRD 3.6: "Once a recipe is `ACTIVE`, its component set is frozen against
        direct edits."

        Design: Corner/cross_cutting_complexity_layers/the_open_spec_change_counter_reconciles_across_create_reject_and_approve
        """
        world = fixtures.grill_world_active_item(api)

        assert_recipe(world["recipe"], open_spec_change_count=0)
        assert_menu_item(
            world["menu_item"],
            sodium_mcg_per_portion=620_000,
            plate_cost_state=CostState.FRESH,
        )

    def test_each_create_increments_the_counter_and_the_version_exactly_once(
        self, api: ApiClient
    ) -> None:
        """Two creates, two increments on each of the two figures.

        PRD 3.6: "Creating the order increments the recipe's
        `open_spec_change_count` and its `version`"

        Design: Corner/cross_cutting_complexity_layers/the_open_spec_change_counter_reconciles_across_create_reject_and_approve
        """
        world = self._two_orders(api)

        assert world["version_after_a"] == world["version_at_activation"] + 1
        assert world["version_after_b"] == world["version_after_a"] + 1
        assert_recipe(
            get_success_data(api.get_recipe(world["recipe"]["id"])),
            open_spec_change_count=2,
            version=world["version_at_activation"] + 2,
        )

    def test_submission_moves_the_orders_dimension_and_nothing_else(
        self, api: ApiClient
    ) -> None:
        """The recipe is left entirely alone, counter included.

        PRD 3.6: "Submission records the caller as `submitted_by_user_id` and
        increments the order's `version`."

        Design: Corner/cross_cutting_complexity_layers/the_open_spec_change_counter_reconciles_across_create_reject_and_approve
        """
        world = self._two_orders(api)

        submitted = fixtures.submit_change_order(api, world["order_b"]["id"])

        assert_spec_change_order(submitted, approval_status=ApprovalStatus.PENDING)
        assert_recipe(
            get_success_data(api.get_recipe(world["recipe"]["id"])),
            open_spec_change_count=2,
            version=world["version_after_b"],
        )

    def test_a_rejection_decrements_the_counter_and_costs_only_a_version(
        self, api: ApiClient
    ) -> None:
        """The specification and the cost state come through untouched.

        PRD 3.6: "It stores the supplied `rejection_reason`, decrements the recipe's
        `open_spec_change_count` and increments the recipe's `version`."

        Design: Corner/cross_cutting_complexity_layers/the_open_spec_change_counter_reconciles_across_create_reject_and_approve
        """
        world = self._two_orders(api)
        fixtures.submit_change_order(api, world["order_b"]["id"])

        rejected = get_success_data(
            self._reject(
                api, world["order_b"]["id"], "Portion too large for the kids menu"
            )
        )

        assert_spec_change_order(
            rejected,
            approval_status=ApprovalStatus.REJECTED,
            rejection_reason="Portion too large for the kids menu",
            propagation_status=PropagationStatus.NOT_STARTED,
        )
        assert_recipe(
            get_success_data(api.get_recipe(world["recipe"]["id"])),
            open_spec_change_count=1,
            version=world["version_after_b"] + 1,
            component_count=1,
            sodium_mcg_per_portion=620_000,
            cost_state=CostState.FRESH,
        )

    def test_the_counter_cannot_be_driven_negative_by_replaying_a_rejection(
        self, api: ApiClient
    ) -> None:
        """The second rejection is a plain state violation.

        PRD 3.6: "`approval_status` runs `DRAFT`, `PENDING`, `APPROVED` and then
        either `REJECTED` or `ROLLED_BACK`, both terminal."

        Design: Corner/cross_cutting_complexity_layers/the_open_spec_change_counter_reconciles_across_create_reject_and_approve
        """
        world = self._two_orders(api)
        fixtures.submit_change_order(api, world["order_b"]["id"])
        get_success_data(
            self._reject(
                api, world["order_b"]["id"], "Portion too large for the kids menu"
            )
        )

        refused = self._reject(api, world["order_b"]["id"], "Rejecting it twice")

        validate_error(refused, ApiErrorId.SCO_INVALID_STATE, 409)
        assert_recipe(
            get_success_data(api.get_recipe(world["recipe"]["id"])),
            open_spec_change_count=1,
        )

    def test_the_approval_decrements_the_other_unit_and_snapshots_first(
        self, api: ApiClient
    ) -> None:
        """The counter reaches exactly zero, and the snapshots predate the edit.

        PRD 3.6: "Before it changes anything, approval takes its snapshots:
        `pre_change_batch_cost_micros` from the recipe's `batch_cost_micros`,
        `pre_change_allergen_mask` from the recipe's `allergen_mask`,
        `pre_change_recipe_version` from the recipe's `version`, and
        `pre_change_ep_quantity_base_units` from the target component's
        `ep_quantity_base_units`"

        Design: Corner/cross_cutting_complexity_layers/the_open_spec_change_counter_reconciles_across_create_reject_and_approve
        """
        world = self._two_orders(api)
        fixtures.submit_change_order(api, world["order_b"]["id"])
        get_success_data(
            self._reject(
                api, world["order_b"]["id"], "Portion too large for the kids menu"
            )
        )
        fixtures.submit_change_order(api, world["order_a"]["id"])

        approved = fixtures.approve_change_order(api, world["order_a"]["id"])

        assert_spec_change_order(
            approved,
            approval_status=ApprovalStatus.APPROVED,
            pre_change_ep_quantity_base_units=400,
            pre_change_batch_cost_micros=3_880_071,
            pre_change_allergen_mask=1,
        )
        assert_recipe(
            get_success_data(api.get_recipe(world["recipe"]["id"])),
            open_spec_change_count=0,
        )

    def test_the_approval_restates_the_nutrition_without_recosting(
        self, api: ApiClient
    ) -> None:
        """A quantity change adds no component, and the money goes unknown.

        PRD 3.6: "The `extended_cost_micros` of every existing line and the recipe's
        `batch_cost_micros` are left exactly as the last roll-up wrote them."

        Design: Corner/cross_cutting_complexity_layers/the_open_spec_change_counter_reconciles_across_create_reject_and_approve
        """
        world = self._two_orders(api)
        fixtures.submit_change_order(api, world["order_a"]["id"])
        fixtures.approve_change_order(api, world["order_a"]["id"])

        stored = get_success_data(api.get_recipe(world["recipe"]["id"]))

        assert_recipe(
            stored,
            component_count=1,
            sodium_mcg_per_portion=round_half_up(500 * 6_200, 4),
            kcal_per_portion_micros=round_half_up(500 * 4_000_000, 4),
            cost_state=CostState.STALE,
            batch_cost_micros=3_880_071,
        )
        assert_fields(
            stored, sodium_mcg_per_portion=775_000, kcal_per_portion_micros=500_000_000
        )

    def test_the_cascade_and_the_reconciliation_are_independent_effects(
        self, api: ApiClient
    ) -> None:
        """The same call that released the counter also restated the item.

        PRD 3.6: "every menu item whose `recipe_id` is this recipe copies the
        recipe's new `allergen_mask` and new `sodium_mcg_per_portion`, flips
        `plate_cost_state` to `STALE`, resets `margin_class` to `UNCLASSIFIED` and
        increments `version`."

        Design: Corner/cross_cutting_complexity_layers/the_open_spec_change_counter_reconciles_across_create_reject_and_approve
        """
        world = self._two_orders(api)
        fixtures.submit_change_order(api, world["order_a"]["id"])
        fixtures.approve_change_order(api, world["order_a"]["id"])

        item = get_success_data(api.get_menu_item(world["menu_item"]["id"], COST_ANALYST))

        assert_menu_item(
            item,
            sodium_mcg_per_portion=round_half_up(500 * 6_200, 4),
            plate_cost_state=CostState.STALE,
            margin_class=MarginClass.UNCLASSIFIED,
        )
        assert_fields(item, sodium_mcg_per_portion=775_000)
