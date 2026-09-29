"""Annual farming-plan budgets, the bounded review loop and the approval cascade."""
from test_helpers import (
    DUAL_ROLE_USER_IDS,
    ApiErrorId,
    assert_farming_plan,
    assert_money,
    assert_version,
    make_controller_headers,
    make_vineyard_manager_headers,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


class TestPlanBudgetAtDraftTime:
    """PRD §3.3 — the budget is computed once from the four per-acre lines."""

    def test_plan_total_budget_sums_the_four_per_acre_lines_over_planted_acres(self, api):
        """The plan's `total_budget` is computed once at draft time and never revised: add the four per-acre lines together and multiply the sum by the block's planted `acres` — the block's planted acreage, deliberately not its contracted acreage — then round to two decimal places. Per-acre lines of 420.00, 310.00, 180.00 and 265.00 on a 12.5-acre block therefore give a `total_budget` of 14,687.50.

        Design: Corner/calculations/plan_total_budget_sums_four_per_acre_budgets
        """
        s = fx.setup_ranch_with_block(api)

        data = validate_success(
            api.create_farming_plan(f.farming_plan_payload(s.block["id"]), fx.VM), 201
        )

        assert_farming_plan(data)
        assert_money(data["total_budget"], 14687.50, "total_budget")
        assert_money(data["committed_cost"], 0.00, "committed_cost")
        assert_money(data["remaining_budget"], 14687.50, "remaining_budget")
        assert data["budget_posture"] == "WITHIN_BUDGET"
        assert data["plan_status"] == "DRAFT"
        assert data["revision_count"] == 0
        assert data["submitted_by_user_id"] is None
        assert data["approved_by_user_id"] is None

    def test_a_second_plan_for_the_same_block_and_year_is_refused(self, api):
        """Only one plan may exist for a given block and crop year: a second draft for the same pairing is refused with `ERR_DUPLICATE_PLAN_FOR_BLOCK_YEAR`.

        Design: Corner/validations/duplicate_plan_for_block_and_year_rejected
        """
        s = fx.setup_ranch_with_block(api)
        first = fx.create_farming_plan(api, s.block["id"])

        validate_error(
            api.create_farming_plan(f.farming_plan_payload(s.block["id"]), fx.VM),
            ApiErrorId.ERR_DUPLICATE_PLAN_FOR_BLOCK_YEAR,
        )

        first = fx.read_plan(api, first["id"])
        assert first["quality_target"] == "PREMIUM"
        assert_money(first["total_budget"], 14687.50, "total_budget")

        next_year = validate_success(
            api.create_farming_plan(
                f.farming_plan_payload(
                    s.block["id"], plan_year=2027,
                    pruning_budget_per_acre=300.00, canopy_budget_per_acre=200.00,
                    irrigation_budget_per_acre=150.00, pest_budget_per_acre=200.00,
                ),
                fx.VM,
            ),
            201,
        )
        assert_money(next_year["total_budget"], 10625.00, "total_budget")


class TestPlanReviewGuards:
    """PRD §3.3 — either review answer requires the plan to be `SUBMITTED`."""

    def test_return_for_revision_on_a_draft_plan_is_refused(self, api):
        """Either answer requires the plan to be in `SUBMITTED` to begin with; a plan in `DRAFT` or `APPROVED` yields `ERR_PLAN_NOT_SUBMITTED`.

        Design: Corner/state_machines/plan_return_for_revision_from_draft_rejected
        """
        s = fx.setup_ranch_with_block(api)
        plan = fx.create_farming_plan(api, s.block["id"])

        validate_error(
            api.return_farming_plan_for_revision(plan["id"], f.return_plan_payload(),
                                                 fx.CTL),
            ApiErrorId.ERR_PLAN_NOT_SUBMITTED,
        )

        plan = fx.read_plan(api, plan["id"])
        assert plan["plan_status"] == "DRAFT"
        assert plan["revision_count"] == 0
        assert plan["submitted_by_user_id"] is None
        assert_version(plan, 1, "plan")
        assert_money(plan["total_budget"], 14687.50, "total_budget")

    def test_submitting_an_approved_plan_again_is_refused(self, api):
        """`APPROVED` is terminal — submission, return and approval are all refused afterwards — and it is the gate everything operational waits on.

        Design: Corner/state_machines/plan_submit_after_approval_rejected
        """
        s = fx.setup_ranch_with_block(api)
        plan = fx.create_farming_plan(api, s.block["id"])
        fx.submit_farming_plan(api, plan["id"])
        approved = fx.approve_farming_plan(api, plan["id"])
        assert_version(approved, 3, "plan")

        validate_error(
            api.submit_farming_plan(plan["id"], f.submit_plan_payload(), fx.VM),
            ApiErrorId.ERR_PLAN_NOT_DRAFT,
        )

        plan = fx.read_plan(api, plan["id"])
        assert plan["plan_status"] == "APPROVED"
        assert plan["submitted_by_user_id"] == "u-vm-1"
        assert plan["approved_by_user_id"] == "u-ctl-1"
        assert_version(plan, 3, "plan")

    def test_plan_approval_by_the_submitter_is_refused(self, api):
        """The approving `Controller`'s `X-User-ID` must differ from the plan's `submitted_by_user_id`; a self-approval is refused with `ERR_SEGREGATION_OF_DUTIES`.

        Design: Corner/rbac/plan_approval_by_the_submitting_user_rejected
        """
        dual = DUAL_ROLE_USER_IDS["PLAN_SUBMITTER_AND_APPROVER"]
        s = fx.setup_ranch_with_block(api)
        plan = fx.create_farming_plan(api, s.block["id"])
        submitted = fx.submit_farming_plan(
            api, plan["id"], make_vineyard_manager_headers(dual)
        )
        assert submitted["submitted_by_user_id"] == dual
        assert submitted["plan_status"] == "SUBMITTED"

        validate_error(
            api.approve_farming_plan(plan["id"], f.approve_plan_payload(),
                                     make_controller_headers(dual)),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        )

        plan = fx.read_plan(api, plan["id"])
        assert plan["plan_status"] == "SUBMITTED"
        assert plan["approved_by_user_id"] is None

        approved = validate_success(
            api.approve_farming_plan(plan["id"], f.approve_plan_payload(), fx.CTL)
        )
        assert approved["plan_status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "u-ctl-1"
        assert_money(approved["total_budget"], 14687.50, "total_budget")
        assert fx.read_block(api, s.block["id"])["farming_status"] == "BEARING"


class TestApprovalCascadeIntoTheBlock:
    """PRD §3.3 — the third-leaf guard decides whether the block starts bearing."""

    def test_approval_leaves_a_young_block_establishing(self, api):
        """Approval also carries a guarded cascade into the block itself: a young block bears fruit in its third leaf, so when the plan's `plan_year` is at least three greater than the block's `planting_year`, the block is driven `ESTABLISHING → BEARING` and the block's `version` is incremented by 1. When the plan year falls short of that mark the block stays `ESTABLISHING` and its `version` is not touched at all.

        Design: Corner/state_machines/plan_approval_leaves_young_block_establishing
        """
        ranch = fx.create_vineyard(api)
        young_block = fx.create_block(
            api, ranch["id"], block_code="B-30", variety="PINOT_NOIR",
            clone="FPS-23", rootstock="ROOTSTOCK_SO4", trellis_system="VSP",
            planting_year=2024, vine_spacing_ft=6.0, row_spacing_ft=10.0, acres=4.0,
        )
        mature_block = fx.create_block(api, ranch["id"])

        young_plan = fx.create_farming_plan(
            api, young_block["id"], quality_target="STANDARD",
            pruning_budget_per_acre=100.00, canopy_budget_per_acre=60.00,
            irrigation_budget_per_acre=37.00, pest_budget_per_acre=60.00,
            seasonal_water_cap_inches=12.000,
        )
        fx.submit_farming_plan(api, young_plan["id"],
                               submission_note="Young block program")
        mature_plan = fx.create_farming_plan(api, mature_block["id"])
        fx.submit_farming_plan(api, mature_plan["id"],
                               submission_note="Mature block program")

        young_plan = fx.approve_farming_plan(api, young_plan["id"])
        young_after = fx.read_block(api, young_block["id"])
        assert young_after["farming_status"] == "ESTABLISHING"
        assert_version(young_after, 1, "young block")

        mature_plan = fx.approve_farming_plan(api, mature_plan["id"])
        mature_after = fx.read_block(api, mature_block["id"])
        assert mature_after["farming_status"] == "BEARING"
        assert_version(mature_after, 2, "mature block")

        assert young_plan["plan_status"] == "APPROVED"
        assert mature_plan["plan_status"] == "APPROVED"
        assert_money(young_plan["total_budget"], 1028.00, "total_budget")
        assert_money(mature_plan["total_budget"], 14687.50, "total_budget")


class TestBoundedRevisionLoop:
    """PRD §3.3 — the `SUBMITTED → DRAFT → SUBMITTED` cycle is capped at two rounds."""

    def test_first_return_for_revision_clears_the_submitter_and_counts_the_round(self, api):
        """Sending the plan back for rework requires a `revision_note` and moves it `SUBMITTED → DRAFT`, incrementing `revision_count` by 1 and clearing `submitted_by_user_id` back to null so that the next submission records whoever actually resubmits.

        Design: Difficulty/non_linear_state_machine/farming_plan_revision_loop_terminates_at_two_rounds
        """
        s = fx.setup_ranch_with_block(api)
        plan = fx.create_farming_plan(api, s.block["id"])
        assert plan["revision_count"] == 0
        assert_version(plan, 1, "plan")

        submitted = fx.submit_farming_plan(api, plan["id"])
        assert submitted["plan_status"] == "SUBMITTED"
        assert submitted["submitted_by_user_id"] == "u-vm-1"
        assert_version(submitted, 2, "plan")

        returned = fx.return_farming_plan(api, plan["id"])
        assert returned["plan_status"] == "DRAFT"
        assert returned["revision_count"] == 1
        assert returned["submitted_by_user_id"] is None
        assert_version(returned, 3, "plan")

    def test_third_return_for_revision_is_refused_at_the_revision_cap(self, api):
        """The loop is capped at two completed rounds: a return attempt made when `revision_count` has already reached 2 is refused with `ERR_REVISION_LIMIT_REACHED` and the plan remains `SUBMITTED`, which is what forces the review cycle to terminate.

        Design: Difficulty/non_linear_state_machine/farming_plan_revision_loop_terminates_at_two_rounds
        """
        s = fx.setup_ranch_with_block(api)
        plan = fx.create_farming_plan(api, s.block["id"])

        fx.submit_farming_plan(api, plan["id"])
        fx.return_farming_plan(api, plan["id"])
        fx.submit_farming_plan(api, plan["id"])
        second_return = fx.return_farming_plan(api, plan["id"])
        assert second_return["revision_count"] == 2
        third_submit = fx.submit_farming_plan(api, plan["id"])
        assert_version(third_submit, 6, "plan")

        validate_error(
            api.return_farming_plan_for_revision(plan["id"], f.return_plan_payload(),
                                                 fx.CTL),
            ApiErrorId.ERR_REVISION_LIMIT_REACHED,
        )

        plan = fx.read_plan(api, plan["id"])
        assert plan["plan_status"] == "SUBMITTED"
        assert plan["revision_count"] == 2
        assert_version(plan, 6, "plan")

    def test_a_plan_at_the_revision_cap_remains_approvable(self, api):
        """On success the approver's identifier is stored as `approved_by_user_id` and the plan's `version` is incremented by 1.

        Design: Difficulty/non_linear_state_machine/farming_plan_revision_loop_terminates_at_two_rounds
        """
        s = fx.setup_ranch_with_block(api)
        plan = fx.create_farming_plan(api, s.block["id"])

        fx.submit_farming_plan(api, plan["id"])
        fx.return_farming_plan(api, plan["id"])
        fx.submit_farming_plan(api, plan["id"])
        fx.return_farming_plan(api, plan["id"])
        fx.submit_farming_plan(api, plan["id"])
        validate_error(
            api.return_farming_plan_for_revision(plan["id"], f.return_plan_payload(),
                                                 fx.CTL),
            ApiErrorId.ERR_REVISION_LIMIT_REACHED,
        )

        approved = fx.approve_farming_plan(api, plan["id"])
        assert approved["plan_status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "u-ctl-1"
        assert approved["revision_count"] == 2
        assert_version(approved, 7, "plan")

        block = fx.read_block(api, s.block["id"])
        assert block["farming_status"] == "BEARING"
        assert_version(block, 2, "block")
