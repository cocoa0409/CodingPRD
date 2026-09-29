"""Two state machines that are not simple forward chains.

A price change proposal has one status field carrying a bounded self-loop: the
same revision request is a loop edge twice and a terminal edge the third time.
A specification change order has two status fields on one row that advance
independently, so the approval axis can stand still while the propagation axis
walks and vice versa.
"""

from test_helpers import (
    APPROVER_USER_ID,
    ApiClient,
    ApiErrorId,
    ApprovalStatus,
    COST_ANALYST,
    CostState,
    MarginClass,
    MenuItemStatus,
    PropagationStatus,
    PropagationTarget,
    ProposalStatus,
    ReviewBasis,
    SyncState,
    assert_count_line,
    assert_fields,
    assert_menu_item,
    assert_prep_guide,
    assert_proposal,
    assert_recipe,
    assert_recipe_component,
    assert_spec_change_order,
    fixtures,
    get_success_data,
    make_culinary_director_headers,
    round_half_up,
    single_row,
    validate_error,
)


class TestProposalRevisionCycleTerminates:
    """One status field, two loop edges, then a terminal edge."""

    @staticmethod
    def _live_proposal(api: ApiClient):
        """An ACTIVE 400-cent item and a DRAFT proposal at 420 cents."""
        world = fixtures.grill_world_active_item(api)
        proposal = fixtures.open_proposal(
            api, world["menu_item"]["id"], proposed_price_cents=420
        )
        return world, proposal

    def test_the_first_submission_projects_against_an_unrelieved_cap(
        self, api: ApiClient
    ) -> None:
        """2381 basis points is below the 3000 target, so the cap stays at 448.

        PRD 3.7: "the relief is 300 basis points when `projected_food_cost_bps`
        is strictly greater than the item's `target_food_cost_bps` and zero
        otherwise"

        Design: Difficulty/non_linear_state_machine/proposal_revision_cycle_terminates_at_two_rounds
        """
        world, proposal = self._live_proposal(api)
        assert world["menu_item"]["plate_cost_cents"] == 100
        assert proposal["revision_round"] == 0

        submitted = fixtures.submit_proposal(api, proposal["id"])

        assert_proposal(
            submitted,
            status=ProposalStatus.SUBMITTED,
            revision_round=0,
            projected_food_cost_bps=round_half_up(100 * 10_000, 420),
            market_cap_price_cents=448,
            effective_cap_price_cents=448,
        )
        assert_fields(submitted, projected_food_cost_bps=2381)

    def test_the_first_two_revision_requests_are_loop_edges(
        self, api: ApiClient
    ) -> None:
        """Round one and round two return the proposal to its author.

        PRD 3.7: "While `revision_round` is strictly below the two-round
        ceiling, the call moves the proposal to `REVISION_REQUESTED`, increments
        `revision_round` by one, stores `last_revision_reason` and increments
        `version`"

        Design: Difficulty/non_linear_state_machine/proposal_revision_cycle_terminates_at_two_rounds
        """
        _, proposal = self._live_proposal(api)
        fixtures.submit_proposal(api, proposal["id"])

        first = fixtures.request_revision(
            api, proposal["id"], reason="trim the increase"
        )
        second_submit = fixtures.submit_proposal(api, proposal["id"])
        second = fixtures.request_revision(
            api, proposal["id"], reason="still too steep"
        )
        third_submit = fixtures.submit_proposal(api, proposal["id"])

        assert_proposal(
            first,
            status=ProposalStatus.REVISION_REQUESTED,
            revision_round=1,
            last_revision_reason="trim the increase",
        )
        assert_proposal(
            second_submit, status=ProposalStatus.SUBMITTED, revision_round=1
        )
        assert_proposal(
            second,
            status=ProposalStatus.REVISION_REQUESTED,
            revision_round=2,
            last_revision_reason="still too steep",
        )
        assert_proposal(
            third_submit, status=ProposalStatus.SUBMITTED, revision_round=2
        )

    def test_the_third_revision_request_rejects_instead_of_reopening(
        self, api: ApiClient
    ) -> None:
        """The same call takes the terminal branch at round two.

        PRD 3.7: "When `revision_round` has already reached two, the very same
        call instead moves the proposal to `REJECTED`, stores
        `last_revision_reason`, leaves `revision_round` unchanged and increments
        `version` — the revision loop is bounded, and the third revision request
        terminates the proposal rather than reopening it."

        Design: Difficulty/non_linear_state_machine/proposal_revision_cycle_terminates_at_two_rounds
        """
        _, proposal = self._live_proposal(api)
        fixtures.submit_proposal(api, proposal["id"])
        fixtures.request_revision(api, proposal["id"], reason="trim the increase")
        fixtures.submit_proposal(api, proposal["id"])
        fixtures.request_revision(api, proposal["id"], reason="still too steep")
        fixtures.submit_proposal(api, proposal["id"])

        third = fixtures.request_revision(
            api, proposal["id"], reason="out of patience"
        )

        assert_proposal(
            third,
            status=ProposalStatus.REJECTED,
            revision_round=2,
            last_revision_reason="out of patience",
        )

    def test_a_fourth_revision_request_is_a_plain_state_violation(
        self, api: ApiClient
    ) -> None:
        """The rejected proposal refuses the identical trigger a fourth time.

        PRD 3.7: "Any further revision request against the now-rejected proposal
        is a plain state violation reported as `ERR_PROPOSAL_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/proposal_revision_cycle_terminates_at_two_rounds
        """
        _, proposal = self._live_proposal(api)
        fixtures.submit_proposal(api, proposal["id"])
        for reason in ("trim the increase", "still too steep"):
            fixtures.request_revision(api, proposal["id"], reason=reason)
            fixtures.submit_proposal(api, proposal["id"])
        fixtures.request_revision(api, proposal["id"], reason="out of patience")

        response = api.request_proposal_revision(
            proposal["id"],
            {"last_revision_reason": "one more time"},
            make_culinary_director_headers(APPROVER_USER_ID),
        )

        validate_error(response, ApiErrorId.PROPOSAL_INVALID_STATE)

    def test_a_rejected_proposal_never_moves_the_menu_price(
        self, api: ApiClient
    ) -> None:
        """The item is still selling at 400 cents when the loop terminates.

        PRD 3.7: "Menu prices are not edited in place."

        Design: Difficulty/non_linear_state_machine/proposal_revision_cycle_terminates_at_two_rounds
        """
        world, proposal = self._live_proposal(api)
        fixtures.submit_proposal(api, proposal["id"])
        for reason in ("trim the increase", "still too steep"):
            fixtures.request_revision(api, proposal["id"], reason=reason)
            fixtures.submit_proposal(api, proposal["id"])
        fixtures.request_revision(api, proposal["id"], reason="out of patience")

        assert_menu_item(
            get_success_data(api.get_menu_item(world["menu_item"]["id"])),
            current_price_cents=400,
            status=MenuItemStatus.ACTIVE,
            last_price_change_at=None,
        )


class TestSpecChangeOrderDimensionsAdvanceIndependently:
    """One row, two status fields, one endpoint per axis."""

    @staticmethod
    def _order_and_world(api: ApiClient):
        """An ACTIVE world, an open USAGE_BASED review and a DRAFT quantity change."""
        world = fixtures.grill_world_active_item(api)
        unit = fixtures.create_unit(api, code="UNIT-MW-01", name="Downtown MW")
        review = fixtures.open_review(
            api, unit["id"], basis=ReviewBasis.USAGE_BASED
        )
        fixtures.load_mix_line(
            api,
            review["id"],
            world["menu_item"]["id"],
            units_sold=50,
            gross_sales_cents=20_000,
        )
        count_line = fixtures.record_count_line(
            api,
            review["id"],
            world["cheddar"]["id"],
            opening_base_units=5300,
            received_base_units=0,
            counted_base_units=41,
        )
        order = fixtures.open_qty_change(
            api,
            world["recipe"]["id"],
            world["component"]["id"],
            new_ep_quantity_base_units=600,
        )
        world.update({"review": review, "count_line": count_line, "order": order})
        return world

    def test_the_approval_axis_moves_three_times_while_propagation_stands_still(
        self, api: ApiClient
    ) -> None:
        """DRAFT, PENDING and APPROVED all read NOT_STARTED.

        PRD 3.6: "The propagation dimension only ever advances while
        `approval_status` is `APPROVED`, and a rollback resets the propagation
        dimension to `NOT_STARTED` without disturbing the approval dimension's
        terminal value."

        Design: Difficulty/non_linear_state_machine/spec_change_order_approval_and_propagation_dimensions_advance_independently
        """
        world = self._order_and_world(api)

        submitted = fixtures.submit_change_order(api, world["order"]["id"])
        approved = fixtures.approve_change_order(api, world["order"]["id"])

        assert_spec_change_order(
            world["order"],
            approval_status=ApprovalStatus.DRAFT,
            propagation_status=PropagationStatus.NOT_STARTED,
        )
        assert_spec_change_order(
            submitted,
            approval_status=ApprovalStatus.PENDING,
            propagation_status=PropagationStatus.NOT_STARTED,
        )
        assert_spec_change_order(
            approved,
            approval_status=ApprovalStatus.APPROVED,
            propagation_status=PropagationStatus.NOT_STARTED,
        )

    def test_approval_snapshots_the_cost_and_quantity_it_is_about_to_invalidate(
        self, api: ApiClient
    ) -> None:
        """3880071 micros and 400 base units are frozen onto the order.

        PRD 3.6: "approval takes its snapshots: `pre_change_batch_cost_micros`
        from the recipe's `batch_cost_micros`, `pre_change_allergen_mask` from
        the recipe's `allergen_mask`, `pre_change_recipe_version` from the
        recipe's `version`, and `pre_change_ep_quantity_base_units` from the
        target component's `ep_quantity_base_units`"

        Design: Difficulty/non_linear_state_machine/spec_change_order_approval_and_propagation_dimensions_advance_independently
        """
        world = self._order_and_world(api)
        fixtures.submit_change_order(api, world["order"]["id"])

        approved = fixtures.approve_change_order(api, world["order"]["id"])

        assert_spec_change_order(
            approved,
            pre_change_batch_cost_micros=3_880_071,
            pre_change_ep_quantity_base_units=400,
            pre_change_allergen_mask=1,
        )

    def test_the_specification_edit_moves_no_money(self, api: ApiClient) -> None:
        """The line now reads 600 base units at the old extended cost.

        PRD 3.6: "**No cost figure is recomputed by this transition.** The
        `extended_cost_micros` of every existing line and the recipe's
        `batch_cost_micros` are left exactly as the last roll-up wrote them."

        Design: Difficulty/non_linear_state_machine/spec_change_order_approval_and_propagation_dimensions_advance_independently
        """
        world = self._order_and_world(api)
        fixtures.submit_change_order(api, world["order"]["id"])

        fixtures.approve_change_order(api, world["order"]["id"])

        assert_recipe_component(
            get_success_data(api.get_recipe_component(world["component"]["id"])),
            ep_quantity_base_units=600,
            ap_quantity_base_units=600,
            extended_cost_micros=3_880_071,
        )

    def test_approval_restates_the_nutrition_but_leaves_the_cost_stale(
        self, api: ApiClient
    ) -> None:
        """Kilocalories and sodium are recomputed; the batch cost is not.

        PRD 3.6: "the owning recipe recomputes `component_count`,
        `allergen_mask`, `kcal_per_portion_micros`, `sodium_mcg_per_portion` and
        `depth` from the new component set, flips `cost_state` to `STALE`,
        decrements `open_spec_change_count` and increments `version`"

        Design: Difficulty/non_linear_state_machine/spec_change_order_approval_and_propagation_dimensions_advance_independently
        """
        world = self._order_and_world(api)
        fixtures.submit_change_order(api, world["order"]["id"])

        fixtures.approve_change_order(api, world["order"]["id"])

        assert_recipe(
            get_success_data(api.get_recipe(world["recipe"]["id"])),
            cost_state=CostState.STALE,
            batch_cost_micros=3_880_071,
            kcal_per_portion_micros=600 * 4_000_000 // 4,
            sodium_mcg_per_portion=600 * 6200 // 4,
            allergen_mask=1,
            component_count=1,
            open_spec_change_count=0,
        )
        assert_fields(
            get_success_data(api.get_recipe(world["recipe"]["id"])),
            kcal_per_portion_micros=600_000_000,
            sodium_mcg_per_portion=930_000,
        )

    def test_the_menu_item_is_left_stale_and_unclassified(
        self, api: ApiClient
    ) -> None:
        """The plate cost survives as a figure but not as a claim.

        PRD 3.6: "every menu item whose `recipe_id` is this recipe copies the
        recipe's new `allergen_mask` and new `sodium_mcg_per_portion`, flips
        `plate_cost_state` to `STALE`, resets `margin_class` to `UNCLASSIFIED`
        and increments `version`"

        Design: Difficulty/non_linear_state_machine/spec_change_order_approval_and_propagation_dimensions_advance_independently
        """
        world = self._order_and_world(api)
        fixtures.submit_change_order(api, world["order"]["id"])

        fixtures.approve_change_order(api, world["order"]["id"])

        assert_menu_item(
            get_success_data(api.get_menu_item(world["menu_item"]["id"])),
            plate_cost_state=CostState.STALE,
            plate_cost_cents=100,
            margin_class=MarginClass.UNCLASSIFIED,
            sodium_mcg_per_portion=930_000,
        )

    def test_draining_the_prep_guide_target_moves_only_the_propagation_axis(
        self, api: ApiClient
    ) -> None:
        """The approval axis sits at APPROVED while propagation advances.

        PRD 3.6: "from `NOT_STARTED`, a `PREP_GUIDE` target advances to
        `PREP_GUIDE_SYNCED` and a `COUNT_SHEETS` target advances to
        `COUNTS_SYNCED`"

        Design: Difficulty/non_linear_state_machine/spec_change_order_approval_and_propagation_dimensions_advance_independently
        """
        world = self._order_and_world(api)
        fixtures.submit_change_order(api, world["order"]["id"])
        fixtures.approve_change_order(api, world["order"]["id"])

        drained = fixtures.propagate_change_order(
            api, world["order"]["id"], target=PropagationTarget.PREP_GUIDE
        )

        assert_spec_change_order(
            drained,
            approval_status=ApprovalStatus.APPROVED,
            propagation_status=PropagationStatus.PREP_GUIDE_SYNCED,
        )

    def test_draining_the_second_target_reaches_fully_propagated(
        self, api: ApiClient
    ) -> None:
        """Two targets, one endpoint, discriminated only by the body.

        PRD 3.6: "from `PREP_GUIDE_SYNCED`, a `COUNT_SHEETS` target advances to
        `FULLY_PROPAGATED`"

        Design: Difficulty/non_linear_state_machine/spec_change_order_approval_and_propagation_dimensions_advance_independently
        """
        world = self._order_and_world(api)
        fixtures.submit_change_order(api, world["order"]["id"])
        fixtures.approve_change_order(api, world["order"]["id"])
        fixtures.propagate_change_order(
            api, world["order"]["id"], target=PropagationTarget.PREP_GUIDE
        )

        drained = fixtures.propagate_change_order(
            api, world["order"]["id"], target=PropagationTarget.COUNT_SHEETS
        )

        assert_spec_change_order(
            drained,
            approval_status=ApprovalStatus.APPROVED,
            propagation_status=PropagationStatus.FULLY_PROPAGATED,
        )

    def test_re_draining_an_absorbed_target_is_refused_not_ignored(
        self, api: ApiClient
    ) -> None:
        """The second PREP_GUIDE request is a state violation.

        PRD 3.6: "The named target must not already be reflected in
        `propagation_status`, otherwise `ERR_PROPAGATION_ALREADY_SYNCED` — each
        target may be drained exactly once per order."

        Design: Difficulty/non_linear_state_machine/spec_change_order_approval_and_propagation_dimensions_advance_independently
        """
        world = self._order_and_world(api)
        fixtures.submit_change_order(api, world["order"]["id"])
        fixtures.approve_change_order(api, world["order"]["id"])
        fixtures.propagate_change_order(
            api, world["order"]["id"], target=PropagationTarget.PREP_GUIDE
        )
        fixtures.propagate_change_order(
            api, world["order"]["id"], target=PropagationTarget.COUNT_SHEETS
        )

        response = api.propagate_spec_change_order(
            world["order"]["id"],
            {"target": PropagationTarget.PREP_GUIDE},
            COST_ANALYST,
        )

        validate_error(response, ApiErrorId.PROPAGATION_ALREADY_SYNCED)

    def test_the_prep_guide_target_reissues_the_kitchen_document(
        self, api: ApiClient
    ) -> None:
        """Revision two, current again, snapshotting one component.

        PRD 3.6: "the recipe's prep guide has its `sync_state` set to `CURRENT`,
        its `revision_no` incremented by one, its
        `batch_yield_base_units_snapshot`, `portions_per_batch_snapshot` and
        `component_count_snapshot` refreshed from the recipe as it now stands"

        Design: Difficulty/non_linear_state_machine/spec_change_order_approval_and_propagation_dimensions_advance_independently
        """
        world = self._order_and_world(api)
        fixtures.submit_change_order(api, world["order"]["id"])
        fixtures.approve_change_order(api, world["order"]["id"])
        stale_guide = fixtures.sole_prep_guide(api, world["recipe"]["id"])
        assert_prep_guide(
            stale_guide, revision_no=1, sync_state=SyncState.OUT_OF_DATE
        )

        fixtures.propagate_change_order(
            api, world["order"]["id"], target=PropagationTarget.PREP_GUIDE
        )

        assert_prep_guide(
            fixtures.sole_prep_guide(api, world["recipe"]["id"]),
            revision_no=2,
            sync_state=SyncState.CURRENT,
            component_count_snapshot=1,
            batch_yield_base_units_snapshot=4,
            portions_per_batch_snapshot=4,
        )

    def test_the_count_sheet_target_re_explodes_the_expected_usage(
        self, api: ApiClient
    ) -> None:
        """5000 base units become 7500 and the variance turns negative.

        PRD 3.6: "`expected_base_units` is recomputed by the expected-usage
        explosion of §3.8 against the current specification, `sync_state` is set
        to `CURRENT`, `variance_base_units` is recomputed as `used_base_units`
        minus the new `expected_base_units`"

        Design: Difficulty/non_linear_state_machine/spec_change_order_approval_and_propagation_dimensions_advance_independently
        """
        world = self._order_and_world(api)
        assert_count_line(
            world["count_line"],
            used_base_units=5259,
            expected_base_units=5000,
            variance_base_units=259,
            sync_state=SyncState.CURRENT,
        )
        fixtures.submit_change_order(api, world["order"]["id"])
        fixtures.approve_change_order(api, world["order"]["id"])
        assert_fields(
            single_row(fixtures.count_line_rows(api, world["review"]["id"])),
            sync_state=SyncState.OUT_OF_DATE,
            expected_base_units=5000,
        )

        fixtures.propagate_change_order(
            api, world["order"]["id"], target=PropagationTarget.COUNT_SHEETS
        )

        assert_count_line(
            single_row(fixtures.count_line_rows(api, world["review"]["id"])),
            used_base_units=5259,
            expected_base_units=7500,
            variance_base_units=-2241,
            sync_state=SyncState.CURRENT,
        )

    def test_draining_one_target_never_performs_the_other_target_work(
        self, api: ApiClient
    ) -> None:
        """The prep guide refresh leaves the count sheet out of date.

        PRD 3.6: "Either order of draining reaches `FULLY_PROPAGATED`, and the
        two targets are genuinely independent — draining one never performs the
        other's work."

        Design: Difficulty/non_linear_state_machine/spec_change_order_approval_and_propagation_dimensions_advance_independently
        """
        world = self._order_and_world(api)
        fixtures.submit_change_order(api, world["order"]["id"])
        fixtures.approve_change_order(api, world["order"]["id"])

        fixtures.propagate_change_order(
            api, world["order"]["id"], target=PropagationTarget.PREP_GUIDE
        )

        assert_count_line(
            single_row(fixtures.count_line_rows(api, world["review"]["id"])),
            expected_base_units=5000,
            variance_base_units=259,
            sync_state=SyncState.OUT_OF_DATE,
        )
