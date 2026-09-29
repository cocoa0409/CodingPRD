"""Errors whose interest is which code the caller is told, and in what order.

Five 404s that a single generic not-found would collapse into one, the top four
rungs of the priority ladder probed where two rules break at once, and one status
that answers three different ways on the same row.
"""

from test_helpers import (
    MISSING_UUID,
    MISSING_UUID_ALT,
    MISSING_UUID_BEEF,
    NON_EXISTENT_UUID,
    NO_HEADERS,
    ApiClient,
    ApiErrorId,
    CostState,
    MenuItemStatus,
    ProposalStatus,
    assert_fields,
    assert_menu_item,
    assert_mix_line,
    assert_projections_unset,
    assert_proposal,
    factories,
    fixtures,
    get_success_data,
    round_half_up,
    validate_error,
    COST_ANALYST,
    PLATFORM_ADMIN,
    RECIPE_DEVELOPER,
    SUBMITTER_USER_ID,
    headers_with_empty_role,
    headers_with_empty_user_id,
    headers_with_unknown_role,
    make_recipe_developer_headers,
    micros_to_cents,
    plate_cost_micros,
    RegionCode,
)


class TestEveryNotFoundNamesItsOwnResource:
    """Five resource types, five codes, and existence scoped per type."""

    @staticmethod
    def _one_store_and_one_draft_feed(api: ApiClient):
        """Two real ids to push down the wrong paths, and nothing else at all."""
        unit = fixtures.create_unit(api, code="STORE-001", name="Downtown")
        feed = fixtures.open_price_feed(api)
        return unit, feed

    def test_an_absent_store_reports_the_store_code(self, api: ApiClient) -> None:
        """Position four owns the store lookup.

        PRD 2.10: "A `unit_id` in the path or body identifies an existing store —
        `ERR_UNIT_NOT_FOUND`, 404. This applies to the single-store read and to
        period-review creation."

        Design: Corner/errors/every_not_found_names_the_resource_the_path_addresses
        """
        self._one_store_and_one_draft_feed(api)

        validate_error(
            api.get_unit(MISSING_UUID, PLATFORM_ADMIN), ApiErrorId.UNIT_NOT_FOUND, 404
        )

    def test_an_absent_feed_reports_the_feed_code(self, api: ApiClient) -> None:
        """Position six owns every feed-scoped path.

        PRD 2.10: "A `price_feed_id` in the path identifies an existing feed —
        `ERR_PRICE_FEED_NOT_FOUND`, 404, on every feed-scoped endpoint."

        Design: Corner/errors/every_not_found_names_the_resource_the_path_addresses
        """
        self._one_store_and_one_draft_feed(api)

        validate_error(
            api.get_price_feed(MISSING_UUID_ALT, COST_ANALYST),
            ApiErrorId.PRICE_FEED_NOT_FOUND,
            404,
        )

    def test_an_absent_proposal_reports_the_proposal_code(
        self, api: ApiClient
    ) -> None:
        """Position ten, and no proposal exists anywhere in the system.

        PRD 2.10: "A `proposal_id` in the path identifies an existing price change
        proposal — `ERR_PROPOSAL_NOT_FOUND`, 404."

        Design: Corner/errors/every_not_found_names_the_resource_the_path_addresses
        """
        self._one_store_and_one_draft_feed(api)

        validate_error(
            api.get_proposal(MISSING_UUID_BEEF, COST_ANALYST),
            ApiErrorId.PROPOSAL_NOT_FOUND,
            404,
        )

    def test_an_absent_change_order_reports_the_order_code(
        self, api: ApiClient
    ) -> None:
        """Position eleven, distinct from the component code above it.

        PRD 2.10: "A `spec_change_order_id` in the path identifies an existing
        specification change order — `ERR_SPEC_CHANGE_ORDER_NOT_FOUND`, 404."

        Design: Corner/errors/every_not_found_names_the_resource_the_path_addresses
        """
        self._one_store_and_one_draft_feed(api)

        validate_error(
            api.get_spec_change_order(NON_EXISTENT_UUID, RECIPE_DEVELOPER),
            ApiErrorId.SPEC_CHANGE_ORDER_NOT_FOUND,
            404,
        )

    def test_an_absent_campaign_reports_the_campaign_code(
        self, api: ApiClient
    ) -> None:
        """Position thirteen closes the not-found block.

        PRD 2.10: "An `lto_campaign_id` in the path identifies an existing
        promotion campaign — `ERR_LTO_NOT_FOUND`, 404."

        Design: Corner/errors/every_not_found_names_the_resource_the_path_addresses
        """
        self._one_store_and_one_draft_feed(api)

        validate_error(
            api.get_lto_campaign(MISSING_UUID, COST_ANALYST),
            ApiErrorId.LTO_NOT_FOUND,
            404,
        )

    def test_a_real_store_id_is_still_an_absent_feed_and_an_absent_order(
        self, api: ApiClient
    ) -> None:
        """Existence is scoped per entity type, so the wrong type is absent.

        PRD 2.10: "A `price_feed_id` in the path identifies an existing feed —
        `ERR_PRICE_FEED_NOT_FOUND`, 404, on every feed-scoped endpoint."

        Design: Corner/errors/every_not_found_names_the_resource_the_path_addresses
        """
        unit, _ = self._one_store_and_one_draft_feed(api)

        validate_error(
            api.get_price_feed(unit["id"], COST_ANALYST),
            ApiErrorId.PRICE_FEED_NOT_FOUND,
            404,
        )
        validate_error(
            api.get_spec_change_order(unit["id"], RECIPE_DEVELOPER),
            ApiErrorId.SPEC_CHANGE_ORDER_NOT_FOUND,
            404,
        )

    def test_a_real_feed_id_is_still_an_absent_proposal_and_an_absent_campaign(
        self, api: ApiClient
    ) -> None:
        """A shared lookup table would answer 200 to at least one of these.

        PRD 2.10: "A `proposal_id` in the path identifies an existing price change
        proposal — `ERR_PROPOSAL_NOT_FOUND`, 404."

        Design: Corner/errors/every_not_found_names_the_resource_the_path_addresses
        """
        _, feed = self._one_store_and_one_draft_feed(api)

        validate_error(
            api.get_proposal(feed["id"], COST_ANALYST),
            ApiErrorId.PROPOSAL_NOT_FOUND,
            404,
        )
        validate_error(
            api.get_lto_campaign(feed["id"], COST_ANALYST),
            ApiErrorId.LTO_NOT_FOUND,
            404,
        )

    def test_the_same_path_with_the_right_identifier_answers_normally(
        self, api: ApiClient
    ) -> None:
        """The sweep is not passing by refusing everything.

        PRD 2.10: "A `unit_id` in the path or body identifies an existing store —
        `ERR_UNIT_NOT_FOUND`, 404."

        Design: Corner/errors/every_not_found_names_the_resource_the_path_addresses
        """
        unit, _ = self._one_store_and_one_draft_feed(api)

        stored = get_success_data(api.get_unit(unit["id"], PLATFORM_ADMIN))

        assert_fields(stored, id=unit["id"], code="STORE-001", region_code="MW")


class TestTheTopOfTheValidationLadder:
    """Authentication, then authorization, then existence and schema."""

    @staticmethod
    def _one_store(api: ApiClient):
        """Nothing but a store: every arm below is refused before it reads state."""
        return fixtures.create_unit(api, code="STORE-001", name="Downtown")

    @staticmethod
    def _malformed_unit_body():
        """A body missing both required strings, so the schema gate has real work."""
        return {"region_code": RegionCode.MW}

    def test_both_headers_absent_is_an_authentication_failure(
        self, api: ApiClient
    ) -> None:
        """The first rung: nothing to identify the caller with.

        PRD 2.10: "Both auth headers present and non-empty —
        `ERR_UNAUTHENTICATED`, 401."

        Design: Corner/errors/authentication_outranks_authorization_and_both_outrank_existence_and_schema
        """
        unit = self._one_store(api)

        validate_error(
            api.get_unit(unit["id"], NO_HEADERS), ApiErrorId.UNAUTHENTICATED, 401
        )

    def test_a_header_sent_as_an_empty_string_is_not_a_header(
        self, api: ApiClient
    ) -> None:
        """Present is not enough on either header; non-empty is also demanded.

        PRD 2.1: "If either header is absent or present but empty, the request is
        rejected with `ERR_UNAUTHENTICATED` and HTTP 401."

        Design: Corner/errors/authentication_outranks_authorization_and_both_outrank_existence_and_schema
        """
        unit = self._one_store(api)

        validate_error(
            api.get_unit(unit["id"], headers_with_empty_role()),
            ApiErrorId.UNAUTHENTICATED,
            401,
        )
        validate_error(
            api.get_unit(unit["id"], headers_with_empty_user_id()),
            ApiErrorId.UNAUTHENTICATED,
            401,
        )

    def test_the_headers_are_checked_before_the_body_is_ever_parsed(
        self, api: ApiClient
    ) -> None:
        """Two rules broken at once, and the earlier position wins.

        PRD 2.10: "Requests are validated in one fixed order, and the **first**
        rule that fails determines the response; no later rule is evaluated and no
        partial mutation is persisted."

        Design: Corner/errors/authentication_outranks_authorization_and_both_outrank_existence_and_schema
        """
        self._one_store(api)

        validate_error(
            api.create_unit(self._malformed_unit_body(), NO_HEADERS),
            ApiErrorId.UNAUTHENTICATED,
            401,
        )

    def test_a_declared_role_off_the_endpoint_list_is_an_authorization_failure(
        self, api: ApiClient
    ) -> None:
        """Store creation lists only the platform administrator.

        PRD 2.10: "`X-User-Role` is one of the five declared roles and is
        authorised on the target endpoint — `ERR_UNAUTHORIZED`, 403."

        Design: Corner/errors/authentication_outranks_authorization_and_both_outrank_existence_and_schema
        """
        self._one_store(api)

        validate_error(
            api.create_unit(
                factories.unit_payload(code="STORE-002", name="Uptown"), COST_ANALYST
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )

    def test_the_role_check_still_beats_the_schema_check(
        self, api: ApiClient
    ) -> None:
        """The same malformed body, refused one rung higher up.

        PRD 2.10: "Request body and query string parse; every required field is
        present; every field has its declared type; every enum value is a declared
        member; every integer respects its declared range; every ISO 8601 instant
        is well formed; `limit` is within 1 through 100 and `offset` is not
        negative; and where both bounds of a window are present, `period_start` is
        strictly before `period_end` and `window_start` is strictly before
        `window_end` — `ERR_INVALID_REQUEST`, 400."

        Design: Corner/errors/authentication_outranks_authorization_and_both_outrank_existence_and_schema
        """
        self._one_store(api)

        validate_error(
            api.create_unit(self._malformed_unit_body(), COST_ANALYST),
            ApiErrorId.UNAUTHORIZED,
            403,
        )

    def test_a_forbidden_caller_learns_nothing_about_whether_the_id_exists(
        self, api: ApiClient
    ) -> None:
        """Activation is the culinary director's, so the developer never gets a 404.

        PRD 2.10: "`X-User-Role` is one of the five declared roles and is
        authorised on the target endpoint — `ERR_UNAUTHORIZED`, 403."

        Design: Corner/errors/authentication_outranks_authorization_and_both_outrank_existence_and_schema
        """
        self._one_store(api)

        validate_error(
            api.activate_menu_item(MISSING_UUID_BEEF, RECIPE_DEVELOPER),
            ApiErrorId.UNAUTHORIZED,
            403,
        )

    def test_an_unrecognised_role_string_is_an_authorization_failure_not_a_401(
        self, api: ApiClient
    ) -> None:
        """The header is present and non-empty; it simply names no declared role.

        PRD 2.1: "If `X-User-Role` carries a string that is not one of the five
        declared role names, or names a role that the targeted endpoint does not
        list as authorised, the request is rejected with `ERR_UNAUTHORIZED` and
        HTTP 403."

        Design: Corner/errors/authentication_outranks_authorization_and_both_outrank_existence_and_schema
        """
        unit = self._one_store(api)

        validate_error(
            api.get_unit(unit["id"], headers_with_unknown_role(role="SousChef")),
            ApiErrorId.UNAUTHORIZED,
            403,
        )

    def test_with_the_right_role_the_same_body_finally_reaches_the_schema_gate(
        self, api: ApiClient
    ) -> None:
        """Proof the earlier refusals were ordering and not blanket body rejection.

        PRD 2.10: "Request body and query string parse; every required field is
        present; every field has its declared type; every enum value is a declared
        member; every integer respects its declared range; every ISO 8601 instant
        is well formed; `limit` is within 1 through 100 and `offset` is not
        negative; and where both bounds of a window are present, `period_start` is
        strictly before `period_end` and `window_start` is strictly before
        `window_end` — `ERR_INVALID_REQUEST`, 400."

        Design: Corner/errors/authentication_outranks_authorization_and_both_outrank_existence_and_schema
        """
        self._one_store(api)

        validate_error(
            api.create_unit(self._malformed_unit_body(), PLATFORM_ADMIN),
            ApiErrorId.INVALID_REQUEST,
            400,
        )

    def test_a_zero_page_size_is_out_of_range_even_for_an_authorized_caller(
        self, api: ApiClient
    ) -> None:
        """The paging bounds live on the same rung as the body schema.

        PRD 2.10: "`limit` is within 1 through 100 and `offset` is not negative"

        Design: Corner/errors/authentication_outranks_authorization_and_both_outrank_existence_and_schema
        """
        self._one_store(api)

        validate_error(
            api.list_recipe_components({"limit": 0, "offset": 0}, PLATFORM_ADMIN),
            ApiErrorId.INVALID_REQUEST,
            400,
        )


class TestMenuItemStatusGatesOnlyTheSubmission:
    """One DRAFT item, three different answers, and one activation that flips them."""

    @staticmethod
    def _draft_world(api: ApiClient, plate_costed: bool):
        """A DRAFT MI-GRILL-MW at 400 cents beside an OPEN review for July."""
        world = fixtures.grill_world_draft_item(api, plate_costed=plate_costed)
        world["unit"] = fixtures.create_unit(api, code="STORE-001", name="Downtown")
        world["review"] = fixtures.open_review(api, world["unit"]["id"])
        return world

    @staticmethod
    def _plate_cost_cents() -> int:
        """The 400-gram cheddar plate over four portions, uplifted for MW."""
        return micros_to_cents(plate_cost_micros(970_018, RegionCode.MW))

    def test_a_new_item_opens_draft_with_no_plate_cost_at_all(
        self, api: ApiClient
    ) -> None:
        """The starting point of the whole sweep.

        PRD 3.5: "Every new item opens in `status` `DRAFT` with `plate_cost_state`
        `STALE`, `margin_class` `UNCLASSIFIED`, a null `cost_basis`, a null
        `last_price_change_at`, `is_lto` false"

        Design: Corner/errors/menu_item_status_gates_the_submission_but_not_the_plate_cost_or_the_draft
        """
        world = self._draft_world(api, plate_costed=False)

        assert_menu_item(
            world["menu_item"],
            status=MenuItemStatus.DRAFT,
            plate_cost_state=CostState.STALE,
            plate_cost_cents=0,
            cost_basis=None,
        )

    def test_the_plate_cost_recomputes_on_a_draft_item(self, api: ApiClient) -> None:
        """Costing an item is not selling it, so the status is no obstacle.

        PRD 3.5: "**Plate costing** is a `CostAnalyst` operation and it is
        deliberately *not* gated on the item's own status: a `DRAFT` item must be
        able to obtain a fresh plate cost, because a fresh plate cost is a
        precondition of activation."

        Design: Corner/errors/menu_item_status_gates_the_submission_but_not_the_plate_cost_or_the_draft
        """
        world = self._draft_world(api, plate_costed=False)

        costed = fixtures.plate_cost(api, world["menu_item"]["id"])

        assert_menu_item(
            costed,
            status=MenuItemStatus.DRAFT,
            plate_cost_state=CostState.FRESH,
            plate_cost_cents=self._plate_cost_cents(),
            food_cost_bps=round_half_up(self._plate_cost_cents() * 10_000, 400),
            contribution_margin_cents=400 - self._plate_cost_cents(),
        )
        assert_fields(
            costed,
            plate_cost_cents=100,
            food_cost_bps=2_500,
            contribution_margin_cents=300,
        )

    def test_a_draft_item_cannot_appear_in_a_periods_mix(self, api: ApiClient) -> None:
        """A DRAFT item was never on the menu, so it was never sold either.

        PRD 3.8: "The item must exist and its `status` must be `ACTIVE` or
        `SUSPENDED`, otherwise `ERR_MENU_ITEM_INVALID_STATE`"

        Design: Corner/errors/menu_item_status_gates_the_submission_but_not_the_plate_cost_or_the_draft
        """
        world = self._draft_world(api, plate_costed=True)

        refused = api.add_mix_line(
            world["review"]["id"],
            factories.mix_line_payload(world["menu_item"]["id"]),
            COST_ANALYST,
        )

        validate_error(refused, ApiErrorId.MENU_ITEM_INVALID_STATE, 409)

    def test_a_proposal_is_created_against_a_draft_item_without_complaint(
        self, api: ApiClient
    ) -> None:
        """The status rung does not cover the create.

        PRD 3.7: "Creation is also deliberately ungated on the item's own status: a
        proposal may be drafted against a `DRAFT` item and will simply fail at
        submission."

        Design: Corner/errors/menu_item_status_gates_the_submission_but_not_the_plate_cost_or_the_draft
        """
        world = self._draft_world(api, plate_costed=True)

        proposal = fixtures.open_proposal(api, world["menu_item"]["id"])

        assert_proposal(proposal, status=ProposalStatus.DRAFT, revision_round=0)
        assert_projections_unset(proposal)

    def test_the_submission_is_where_the_status_is_finally_checked(
        self, api: ApiClient
    ) -> None:
        """The refusal lands on the submit, and it leaves the proposal untouched.

        PRD 3.7: "The target item's `status` must be `ACTIVE`, otherwise
        `ERR_MENU_ITEM_INVALID_STATE`."

        Design: Corner/errors/menu_item_status_gates_the_submission_but_not_the_plate_cost_or_the_draft
        """
        world = self._draft_world(api, plate_costed=True)
        proposal = fixtures.open_proposal(api, world["menu_item"]["id"])

        refused = api.submit_proposal(
            proposal["id"], make_recipe_developer_headers(SUBMITTER_USER_ID)
        )

        validate_error(refused, ApiErrorId.MENU_ITEM_INVALID_STATE, 409)
        stored = get_success_data(api.get_proposal(proposal["id"], RECIPE_DEVELOPER))
        assert_proposal(
            stored,
            status=ProposalStatus.DRAFT,
            version=proposal["version"],
            submitted_by_user_id=None,
        )
        assert_projections_unset(stored)

    def test_activation_alone_makes_the_identical_resubmit_succeed(
        self, api: ApiClient
    ) -> None:
        """Nothing about the proposal changed, only the item's status.

        PRD 3.5: "**Activation** belongs to the `CulinaryDirector` and admits an
        item to the menu from either `DRAFT` or `SUSPENDED`"

        Design: Corner/errors/menu_item_status_gates_the_submission_but_not_the_plate_cost_or_the_draft
        """
        world = self._draft_world(api, plate_costed=True)
        proposal = fixtures.open_proposal(api, world["menu_item"]["id"])
        validate_error(
            api.submit_proposal(
                proposal["id"], make_recipe_developer_headers(SUBMITTER_USER_ID)
            ),
            ApiErrorId.MENU_ITEM_INVALID_STATE,
            409,
        )

        activated = fixtures.activate_menu_item(api, world["menu_item"]["id"])
        submitted = fixtures.submit_proposal(api, proposal["id"])

        assert_menu_item(activated, status=MenuItemStatus.ACTIVE)
        assert_proposal(
            submitted,
            status=ProposalStatus.SUBMITTED,
            price_delta_bps=round_half_up(abs(420 - 400) * 10_000, 400),
            projected_units=round_half_up(1_000 * (10_000 - 600), 10_000),
            projected_food_cost_bps=round_half_up(100 * 10_000, 420),
            projected_contribution_delta_cents=940 * (420 - 100)
            - 1_000 * (400 - 100),
        )
        assert_fields(
            submitted,
            price_delta_bps=500,
            projected_units=940,
            projected_food_cost_bps=2_381,
            effective_cap_price_cents=448,
            projected_contribution_delta_cents=800,
        )

    def test_the_refused_mix_line_load_now_succeeds_against_the_active_item(
        self, api: ApiClient
    ) -> None:
        """The same call, the same payload, and a frozen snapshot this time.

        PRD 3.8: "The line freezes `plate_cost_cents_snapshot` from the item's
        `plate_cost_cents` at the moment of loading"

        Design: Corner/errors/menu_item_status_gates_the_submission_but_not_the_plate_cost_or_the_draft
        """
        world = self._draft_world(api, plate_costed=True)
        payload = factories.mix_line_payload(world["menu_item"]["id"])
        validate_error(
            api.add_mix_line(world["review"]["id"], payload, COST_ANALYST),
            ApiErrorId.MENU_ITEM_INVALID_STATE,
            409,
        )
        fixtures.activate_menu_item(api, world["menu_item"]["id"])

        line = get_success_data(
            api.add_mix_line(world["review"]["id"], payload, COST_ANALYST), 201
        )

        assert_mix_line(
            line,
            menu_item_id=world["menu_item"]["id"],
            plate_cost_cents_snapshot=self._plate_cost_cents(),
        )
        assert_fields(line, plate_cost_cents_snapshot=100)
