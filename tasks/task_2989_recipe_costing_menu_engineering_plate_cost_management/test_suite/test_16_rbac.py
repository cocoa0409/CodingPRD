"""Five peer roles, none of them a superset of another.

Each role probed positively on one operation it exclusively owns and negatively
on another role's, the duties rule shown to bind the operator rather than the
role, and the one entity-backed identity checked on both sides of its scope.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    CULINARY_DIRECTOR,
    CostState,
    IngredientStatus,
    PLATFORM_ADMIN,
    PriceFeedStatus,
    ProposalStatus,
    RECIPE_DEVELOPER,
    RegionCode,
    ReviewBasis,
    SyncState,
    APPROVER_USER_ID,
    SUBMITTER_USER_ID,
    assert_count_line,
    assert_fields,
    assert_ingredient,
    assert_menu_item,
    assert_page_meta,
    assert_proposal,
    assert_recipe,
    factories,
    fixtures,
    get_success_data,
    ids_of,
    make_culinary_director_headers,
    make_unit_manager_headers,
    micros_to_cents,
    plate_cost_micros,
    validate_error,
    validate_paginated,
)


class TestEachRoleOwnsItsExclusiveSurface:
    """Ten probes, each one decided before any domain state is read."""

    @staticmethod
    def _catalogue(api: ApiClient):
        """A store, an ingredient and a DRAFT recipe, each by its owning role."""
        unit = fixtures.create_unit(api, code="STORE-001", name="Downtown")
        cheddar = fixtures.create_cheddar(api)
        recipe = fixtures.create_recipe(api)
        return {"unit": unit, "cheddar": cheddar, "recipe": recipe}

    @staticmethod
    def _salt_payload(sku: str, name: str):
        """A second ingredient body, so the shared creation surface has a subject."""
        return factories.ingredient_payload(
            sku=sku,
            name=name,
            pack_base_units=1_000,
            allergen_mask=0,
            kcal_per_base_unit_micros=0,
            sodium_mcg_per_base_unit=380_000,
        )

    def test_the_logical_clock_is_the_platform_admins_alone(
        self, api: ApiClient
    ) -> None:
        """The admin drives it; the approval authority cannot.

        PRD 2.1: "`PlatformAdmin` is the platform operator: it owns the store
        registry, shares the ingredient-catalogue creation surface with culinary
        R&D, and is the only role permitted to drive the logical clock."

        Design: Corner/rbac/each_role_owns_its_exclusive_surface_and_is_refused_on_every_other
        """
        self._catalogue(api)

        fixtures.set_clock(api, "2026-08-03T00:00:00.000Z")

        validate_error(
            api.set_clock(
                factories.clock_payload("2026-08-04T00:00:00.000Z"), CULINARY_DIRECTOR
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )

    def test_store_registration_is_the_platform_admins_alone(
        self, api: ApiClient
    ) -> None:
        """Culinary R&D authors recipes, not stores.

        PRD 4: "| POST | `/culinary/units` | Register a store | PlatformAdmin |"

        Design: Corner/rbac/each_role_owns_its_exclusive_surface_and_is_refused_on_every_other
        """
        self._catalogue(api)

        validate_error(
            api.create_unit(
                factories.unit_payload(
                    code="STORE-009", name="Suburb", region_code=RegionCode.SE
                ),
                RECIPE_DEVELOPER,
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )

    def test_the_platform_admin_cannot_author_a_recipe(self, api: ApiClient) -> None:
        """The platform role is not a superset of the culinary one.

        PRD 2.1: "It has no authority over recipes, costs, menus or approvals."

        Design: Corner/rbac/each_role_owns_its_exclusive_surface_and_is_refused_on_every_other
        """
        self._catalogue(api)

        validate_error(
            api.create_recipe(
                factories.recipe_payload(code="PLATE-ADMIN", name="Admin Plate"),
                PLATFORM_ADMIN,
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )

    def test_ingredient_creation_is_shared_by_two_roles_and_excludes_the_approver(
        self, api: ApiClient
    ) -> None:
        """The admin shares the catalogue surface; the director does not.

        PRD 4: "| POST | `/culinary/ingredients` | Register a purchasable
        Ingredient | RecipeDeveloper, PlatformAdmin |"

        Design: Corner/rbac/each_role_owns_its_exclusive_surface_and_is_refused_on_every_other
        """
        self._catalogue(api)

        validate_error(
            api.create_ingredient(
                self._salt_payload("DIRECTOR-SALT", "Director Salt"), CULINARY_DIRECTOR
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )
        minted = get_success_data(
            api.create_ingredient(
                self._salt_payload("ADMIN-SALT", "Admin Salt"), PLATFORM_ADMIN
            ),
            201,
        )

        assert_ingredient(minted, sku="ADMIN-SALT", status=IngredientStatus.ACTIVE)

    def test_the_approver_owns_ingredient_retirement(self, api: ApiClient) -> None:
        """Authority over lifecycle transitions, not over the catalogue itself.

        PRD 2.1: "`CulinaryDirector` is the approval authority: it activates and
        retires recipes, ingredients and menu items"

        Design: Corner/rbac/each_role_owns_its_exclusive_surface_and_is_refused_on_every_other
        """
        world = self._catalogue(api)

        retired = fixtures.retire_ingredient(api, world["cheddar"]["id"])

        assert_ingredient(retired, status=IngredientStatus.RETIRED)

    def test_roll_ups_are_the_cost_analysts_alone(self, api: ApiClient) -> None:
        """The approver cannot manufacture the cost figures it approves.

        PRD 2.1: "`CostAnalyst` owns cost and menu engineering: it loads and
        publishes distributor feeds, runs every roll-up and plate-cost
        recomputation"

        Design: Corner/rbac/each_role_owns_its_exclusive_surface_and_is_refused_on_every_other
        """
        world = self._catalogue(api)

        validate_error(
            api.cost_rollup_recipe(
                world["recipe"]["id"],
                factories.rollup_payload(),
                CULINARY_DIRECTOR,
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )

    def test_opening_a_distributor_feed_is_the_cost_analysts_alone(
        self, api: ApiClient
    ) -> None:
        """The analyst mints it; the author of recipes may not.

        PRD 4: "| POST | `/culinary/price-feeds` | Open a DRAFT distributor Price
        Feed for one region | CostAnalyst |"

        Design: Corner/rbac/each_role_owns_its_exclusive_surface_and_is_refused_on_every_other
        """
        self._catalogue(api)

        minted = fixtures.open_price_feed(api, feed_date="2026-08-03T00:00:00.000Z")

        assert_fields(minted, distributor_code="BROADLINE")
        validate_error(
            api.create_price_feed(
                factories.price_feed_payload(
                    distributor_code="SPECIALTY", feed_date="2026-08-03T00:00:00.000Z"
                ),
                RECIPE_DEVELOPER,
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )

    def test_the_unit_manager_cannot_open_the_review_that_holds_its_counts(
        self, api: ApiClient
    ) -> None:
        """The store role's exclusive set is empty: it may only write counts.

        PRD 2.1: "`UnitManager` is a store manager whose only write capability is
        recording physical inventory counts for their own store's period reviews."

        Design: Corner/rbac/each_role_owns_its_exclusive_surface_and_is_refused_on_every_other
        """
        world = self._catalogue(api)

        validate_error(
            api.create_period_review(
                factories.period_review_payload(world["unit"]["id"]),
                make_unit_manager_headers(world["unit"]["id"]),
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )

    def test_the_author_cannot_activate_its_own_recipe(self, api: ApiClient) -> None:
        """The structural half of segregation of duties, enforced by role alone.

        PRD 2.1: "it submits work for approval and can never approve it"

        Design: Corner/rbac/each_role_owns_its_exclusive_surface_and_is_refused_on_every_other
        """
        world = self._catalogue(api)

        validate_error(
            api.activate_recipe(world["recipe"]["id"], RECIPE_DEVELOPER),
            ApiErrorId.UNAUTHORIZED,
            403,
        )

    def test_every_role_including_the_store_manager_can_read(
        self, api: ApiClient
    ) -> None:
        """No exclusive operations does not mean no access.

        PRD 2.1: "Every role in the system may read: all five roles are authorised
        on every read endpoint."

        Design: Corner/rbac/each_role_owns_its_exclusive_surface_and_is_refused_on_every_other
        """
        world = self._catalogue(api)

        by_manager = get_success_data(
            api.get_recipe(
                world["recipe"]["id"], make_unit_manager_headers(world["unit"]["id"])
            )
        )
        by_admin = get_success_data(
            api.get_recipe(world["recipe"]["id"], PLATFORM_ADMIN)
        )

        assert_recipe(by_manager, code="PLATE-GRILL")
        assert_fields(by_admin, code=by_manager["code"], id=by_manager["id"])


class TestSegregationOfDutiesBindsTheOperatorNotTheRole:
    """The duties rule ranks below the cost gate, and compares identities."""

    @staticmethod
    def _submitted_then_driven_stale(api: ApiClient):
        """A SUBMITTED proposal whose item then loses its fresh plate cost."""
        world = fixtures.grill_world_active_item(api)
        proposal = fixtures.open_proposal(api, world["menu_item"]["id"])
        world["submitted"] = fixtures.submit_proposal(api, proposal["id"])
        world["second_feed"] = fixtures.publish_price(
            api,
            world["cheddar"]["id"],
            33_000_000,
            effective_from="2026-07-15T00:00:00.000Z",
            feed_date="2026-07-15T00:00:00.000Z",
        )
        return world

    @staticmethod
    def _reconcile_the_cost(api: ApiClient, world) -> None:
        """Roll the recipe up again and recost the plate, in that order."""
        fixtures.rollup(api, world["recipe"]["id"])
        fixtures.plate_cost(api, world["menu_item"]["id"])

    def test_the_submitters_user_id_is_recorded_on_the_record(
        self, api: ApiClient
    ) -> None:
        """The audit trail names the operator, not merely the role.

        PRD 2.1: "Whenever an operator submits a price change proposal or a
        specification change order, their `X-User-ID` is recorded on the record as
        `submitted_by_user_id`."

        Design: Corner/rbac/segregation_of_duties_binds_the_user_id_not_the_role_and_ranks_below_the_state_checks
        """
        world = self._submitted_then_driven_stale(api)

        assert_proposal(
            world["submitted"],
            status=ProposalStatus.SUBMITTED,
            submitted_by_user_id=SUBMITTER_USER_ID,
            approved_by_user_id=None,
        )
        assert_menu_item(
            world["menu_item"],
            plate_cost_cents=micros_to_cents(plate_cost_micros(970_018, RegionCode.MW)),
        )
        assert_fields(world["menu_item"], plate_cost_cents=100)

    def test_the_publication_cascade_invalidates_without_recomputing(
        self, api: ApiClient
    ) -> None:
        """The stale figure is left standing where it was.

        PRD 2.6: "The system never recomputes a cost behind the client's back."

        Design: Corner/rbac/segregation_of_duties_binds_the_user_id_not_the_role_and_ranks_below_the_state_checks
        """
        world = self._submitted_then_driven_stale(api)

        item = get_success_data(api.get_menu_item(world["menu_item"]["id"]))

        assert_fields(world["second_feed"], status=PriceFeedStatus.PUBLISHED)
        assert_menu_item(
            item, plate_cost_state=CostState.STALE, plate_cost_cents=100
        )

    def test_the_stale_cost_error_masks_the_duties_error(
        self, api: ApiClient
    ) -> None:
        """The approver is the submitter and would be refused anyway.

        PRD 3.7: "A self-approval of a proposal whose item has gone stale therefore
        reports the stale-cost error, not the duties error."

        Design: Corner/rbac/segregation_of_duties_binds_the_user_id_not_the_role_and_ranks_below_the_state_checks
        """
        world = self._submitted_then_driven_stale(api)

        refused = api.approve_proposal(
            world["submitted"]["id"], make_culinary_director_headers(SUBMITTER_USER_ID)
        )

        validate_error(refused, ApiErrorId.COST_STALE, 409)

    def test_reconciling_the_cost_reopens_the_gate_beneath_it(
        self, api: ApiClient
    ) -> None:
        """The mid-period price lands, and the plate cost moves with it.

        PRD 3.7: "the item's `plate_cost_state` must still be `FRESH`, otherwise
        `ERR_COST_STALE`, because a plate-cost invalidation since submission voids
        the whole projection"

        Design: Corner/rbac/segregation_of_duties_binds_the_user_id_not_the_role_and_ranks_below_the_state_checks
        """
        world = self._submitted_then_driven_stale(api)

        rolled = fixtures.rollup(api, world["recipe"]["id"])
        recosted = fixtures.plate_cost(api, world["menu_item"]["id"])

        assert_recipe(rolled, portion_cost_micros=1_455_027)
        assert_menu_item(
            recosted,
            plate_cost_state=CostState.FRESH,
            plate_cost_cents=micros_to_cents(
                plate_cost_micros(1_455_027, RegionCode.MW)
            ),
        )
        assert_fields(recosted, plate_cost_cents=151)

    def test_switching_role_does_not_launder_the_conflict(
        self, api: ApiClient
    ) -> None:
        """Same person, different role, and the comparison is on the user id.

        PRD 2.1: "if the approver's `X-User-ID` equals the recorded
        `submitted_by_user_id`, the approval is refused with
        `ERR_SEGREGATION_OF_DUTIES` and HTTP 403, even when that operator
        legitimately holds the `CulinaryDirector` role."

        Design: Corner/rbac/segregation_of_duties_binds_the_user_id_not_the_role_and_ranks_below_the_state_checks
        """
        world = self._submitted_then_driven_stale(api)
        self._reconcile_the_cost(api, world)

        refused = api.approve_proposal(
            world["submitted"]["id"], make_culinary_director_headers(SUBMITTER_USER_ID)
        )

        validate_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES, 403)

    def test_the_refused_approval_wrote_nothing(self, api: ApiClient) -> None:
        """No partial mutation survives a rejected request.

        PRD 2.10: "no later rule is evaluated and no partial mutation is persisted"

        Design: Corner/rbac/segregation_of_duties_binds_the_user_id_not_the_role_and_ranks_below_the_state_checks
        """
        world = self._submitted_then_driven_stale(api)
        self._reconcile_the_cost(api, world)
        validate_error(
            api.approve_proposal(
                world["submitted"]["id"],
                make_culinary_director_headers(SUBMITTER_USER_ID),
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES,
            403,
        )

        stored = get_success_data(
            api.get_proposal(world["submitted"]["id"], CULINARY_DIRECTOR)
        )

        assert_proposal(
            stored,
            status=ProposalStatus.SUBMITTED,
            approved_by_user_id=None,
            version=world["submitted"]["version"],
        )

    def test_a_different_operator_in_the_same_role_succeeds(
        self, api: ApiClient
    ) -> None:
        """Holding the role is necessary; not having authored it is the second half.

        PRD 2.1: "Holding an approving role is necessary but not sufficient; not
        having authored the record is the second condition."

        Design: Corner/rbac/segregation_of_duties_binds_the_user_id_not_the_role_and_ranks_below_the_state_checks
        """
        world = self._submitted_then_driven_stale(api)
        self._reconcile_the_cost(api, world)

        approved = fixtures.approve_proposal(api, world["submitted"]["id"])

        assert_proposal(
            approved,
            status=ProposalStatus.APPROVED,
            approved_by_user_id=APPROVER_USER_ID,
            submitted_by_user_id=SUBMITTER_USER_ID,
        )


class TestAUnitManagerMayOnlyCountForItsOwnStore:
    """The one entity-backed identity: the header is a store id."""

    @staticmethod
    def _two_stores_with_open_reviews(api: ApiClient):
        """Two MW stores, one USAGE_BASED review each, and no mix loaded at all."""
        store_a = fixtures.create_unit(api, code="STORE-A", name="Store A")
        store_b = fixtures.create_unit(api, code="STORE-B", name="Store B")
        cheddar = fixtures.create_cheddar(api)
        return {
            "store_a": store_a,
            "store_b": store_b,
            "cheddar": cheddar,
            "review_a": fixtures.open_review(
                api, store_a["id"], basis=ReviewBasis.USAGE_BASED
            ),
            "review_b": fixtures.open_review(
                api, store_b["id"], basis=ReviewBasis.USAGE_BASED
            ),
        }

    def test_a_manager_writes_into_its_own_stores_review(
        self, api: ApiClient
    ) -> None:
        """No mix is loaded, so the whole usage is variance.

        PRD 3.8: "`used_base_units` is `opening_base_units` plus
        `received_base_units` minus `counted_base_units`, floored at zero so an
        impossible count never reports negative consumption."

        Design: Corner/rbac/a_unit_manager_may_only_count_for_its_own_store
        """
        world = self._two_stores_with_open_reviews(api)

        line = fixtures.record_count_line(
            api,
            world["review_a"]["id"],
            world["cheddar"]["id"],
            unit_id=world["store_a"]["id"],
            opening_base_units=1_000,
            received_base_units=0,
            counted_base_units=400,
        )

        assert_count_line(
            line,
            used_base_units=1_000 + 0 - 400,
            expected_base_units=0,
            variance_base_units=1_000 + 0 - 400,
            sync_state=SyncState.CURRENT,
        )
        assert_fields(line, used_base_units=600, variance_base_units=600)

    def test_the_same_role_and_payload_is_refused_on_another_stores_review(
        self, api: ApiClient
    ) -> None:
        """Only the review's owning store differs, and that is enough.

        PRD 2.1: "a `UnitManager` writing a count line into a period review is
        permitted only when that review's `unit_id` equals the caller's
        `X-User-ID`, and a mismatch is rejected with `ERR_UNIT_SCOPE_VIOLATION` and
        HTTP 403."

        Design: Corner/rbac/a_unit_manager_may_only_count_for_its_own_store
        """
        world = self._two_stores_with_open_reviews(api)

        refused = api.add_count_line(
            world["review_b"]["id"],
            factories.count_line_payload(
                world["cheddar"]["id"],
                opening_base_units=1_000,
                received_base_units=0,
                counted_base_units=400,
            ),
            make_unit_manager_headers(world["store_a"]["id"]),
        )

        validate_error(refused, ApiErrorId.UNIT_SCOPE_VIOLATION, 403)

    def test_the_guard_is_per_request_identity_and_not_a_per_role_ban(
        self, api: ApiClient
    ) -> None:
        """The very review just refused accepts its own store's manager.

        PRD 2.1: "When `X-User-Role` is `UnitManager`, `X-User-ID` is the `id` of
        the acting `Unit`; ownership checks on any resource that references a `Unit`
        compare the resource's own unit reference to `X-User-ID`."

        Design: Corner/rbac/a_unit_manager_may_only_count_for_its_own_store
        """
        world = self._two_stores_with_open_reviews(api)
        validate_error(
            api.add_count_line(
                world["review_b"]["id"],
                factories.count_line_payload(world["cheddar"]["id"]),
                make_unit_manager_headers(world["store_a"]["id"]),
            ),
            ApiErrorId.UNIT_SCOPE_VIOLATION,
            403,
        )

        line = fixtures.record_count_line(
            api,
            world["review_b"]["id"],
            world["cheddar"]["id"],
            unit_id=world["store_b"]["id"],
            opening_base_units=2_000,
            received_base_units=500,
            counted_base_units=900,
        )

        assert_count_line(line, used_base_units=2_000 + 500 - 900)
        assert_fields(line, used_base_units=1_600)

    def test_the_cost_analyst_shares_the_endpoint_without_the_scope_check(
        self, api: ApiClient
    ) -> None:
        """The same path, written freely into a store the caller does not own.

        PRD 2.1: "A `CostAnalyst` may write count lines into any store's review and
        is not subject to that comparison."

        Design: Corner/rbac/a_unit_manager_may_only_count_for_its_own_store
        """
        world = self._two_stores_with_open_reviews(api)

        line = fixtures.record_count_line(
            api,
            world["review_b"]["id"],
            world["cheddar"]["id"],
            opening_base_units=100,
            received_base_units=0,
            counted_base_units=40,
        )

        assert_count_line(line, used_base_units=100 + 0 - 40)
        assert_fields(line, used_base_units=60)

    def test_the_scope_rule_guards_the_write_and_never_the_read(
        self, api: ApiClient
    ) -> None:
        """Store A's manager reads Store B's count lines without complaint.

        PRD 2.1: "Every role in the system may read: all five roles are authorised
        on every read endpoint."

        Design: Corner/rbac/a_unit_manager_may_only_count_for_its_own_store
        """
        world = self._two_stores_with_open_reviews(api)
        by_manager = fixtures.record_count_line(
            api,
            world["review_b"]["id"],
            world["cheddar"]["id"],
            unit_id=world["store_b"]["id"],
            opening_base_units=2_000,
            received_base_units=500,
            counted_base_units=900,
        )
        by_analyst = fixtures.record_count_line(
            api,
            world["review_b"]["id"],
            world["cheddar"]["id"],
            opening_base_units=100,
            received_base_units=0,
            counted_base_units=40,
        )

        rows, meta = validate_paginated(
            api.list_count_lines(
                world["review_b"]["id"],
                {"limit": 10, "offset": 0},
                make_unit_manager_headers(world["store_a"]["id"]),
            )
        )

        assert_page_meta(meta, total_count=2, limit=10, offset=0, has_more=False)
        assert ids_of(rows) == [by_manager["id"], by_analyst["id"]]

    def test_an_operation_outside_the_shared_set_is_refused_by_role_first(
        self, api: ApiClient
    ) -> None:
        """The role rung sits far above the unit-scope rung.

        PRD 2.10: "Requests are validated in one fixed order, and the **first**
        rule that fails determines the response; no later rule is evaluated and no
        partial mutation is persisted."

        Design: Corner/rbac/a_unit_manager_may_only_count_for_its_own_store
        """
        world = self._two_stores_with_open_reviews(api)

        refused = api.classify_period_review(
            world["review_a"]["id"], make_unit_manager_headers(world["store_a"]["id"])
        )

        validate_error(refused, ApiErrorId.UNAUTHORIZED, 403)
