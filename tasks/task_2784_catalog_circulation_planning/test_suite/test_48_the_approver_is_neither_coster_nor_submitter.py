"""Two plans separate the two forbidden identities, and the role header is right every time.

On P1 the refused approver is the operator who costed; on P2 it is the operator who
submitted. Every approve call below carries the `CirculationDirector` role, so a correct
role is demonstrably not sufficient — only `X-User-ID` varies. A third operator then
clears both plans, and the revision back-edge is shown to wipe the two recorded
identities that the guard reads.
"""
from test_helpers import (
    BROKER,
    CLOCK_START,
    DIRECTOR_9,
    PLANNER,
    PLANNER_1,
    PLANNER_2,
    PLANNER_3,
    PLANNER_4,
    allocate,
    cost_plan,
    fetch_plan,
    iso_utc,
    make_circulation_director_headers,
    new_drop,
    new_housefile_line,
    new_plan,
    new_season,
    new_segment,
    run_merge_purge,
    set_clock,
    submit_plan,
    validate_error,
    validate_success,
)

SCORING = {
    "recency_days": 45,
    "orders_12mo": 7,
    "ltv_cents": 62000,
    "housefile_count": 30000,
    "avg_order_value_cents": 18500,
    "historical_response_rate_bps": 620,
}

# The same director role, worn by five different operator identities.
AS_PLANNER_1 = make_circulation_director_headers("u-planner-1")
AS_PLANNER_2 = make_circulation_director_headers("u-planner-2")
AS_PLANNER_3 = make_circulation_director_headers("u-planner-3")
AS_PLANNER_4 = make_circulation_director_headers("u-planner-4")


def _two_plans_under_review_costed_and_submitted_by_four_planners() -> dict:
    """Each plan carries one drop with a single allocated 20000-book S_A line, so each
    plan's `planned_contribution_cents` is a positive 4914800 and the contribution guard
    stays out of the way. The two in-home dates sit 30 days apart so the shared segment's
    21-day spacing buffer is respected."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    segment = new_segment(season["id"], segment_code="S_A", **SCORING)
    first = new_plan(season["id"], plan_code="P1", budget_cents=20000000)
    second = new_plan(season["id"], plan_code="P2", budget_cents=20000000)
    run_merge_purge(first["id"], headers=BROKER)
    run_merge_purge(second["id"], headers=BROKER)

    first_drop = new_drop(
        first["id"], drop_number=1, in_home_date=iso_utc("2026-09-15"), page_count=64
    )
    second_drop = new_drop(
        second["id"], drop_number=1, in_home_date=iso_utc("2026-10-15"), page_count=64
    )
    new_housefile_line(first_drop["id"], segment["id"], requested_quantity=20000)
    new_housefile_line(second_drop["id"], segment["id"], requested_quantity=20000)
    allocate(first_drop["id"])
    allocate(second_drop["id"])

    cost_plan(first["id"], PLANNER_1)
    first = submit_plan(first["id"], PLANNER_2)
    cost_plan(second["id"], PLANNER_3)
    second = submit_plan(second["id"], PLANNER_4)
    return {"season": season, "segment": segment, "first": first, "second": second}


class TestTheTwoIdentitiesTheGuardReads:
    def test_costing_and_submitting_each_stamp_their_own_operator(self, api):
        """PRD §3.6: "Costing then stamps `costed_by_user_id` with the acting operator's
        `X-User-ID` and increments the plan's `version` by one."
        PRD §3.6: "Submitting for review takes the plan `COSTED → UNDER_REVIEW` and stamps
        `submitted_by_user_id` with the acting operator's `X-User-ID`, incrementing
        `version` by one."

        Design: Corner/rbac/the_operator_who_costs_or_submits_a_plan_cannot_approve_it
        """
        world = _two_plans_under_review_costed_and_submitted_by_four_planners()
        first = world["first"]

        assert first["status"] == "UNDER_REVIEW"
        assert first["costed_by_user_id"] == "u-planner-1"
        assert first["submitted_by_user_id"] == "u-planner-2"
        assert first["approved_by_user_id"] is None
        assert first["planned_contribution_cents"] == 4914800


class TestTheCosterMayNotApprove:
    def test_approving_as_the_operator_who_costed_is_a_segregation_failure(self, api):
        """PRD §3.6: "Segregation of duties requires the acting `X-User-ID` to differ from
        *both* `costed_by_user_id` and `submitted_by_user_id`; matching either one is
        rejected with `ERR_SEGREGATION_OF_DUTIES`."
        PRD §2.1: "Those three fields hold raw `X-User-ID` strings, and the
        segregation-of-duties guard on approval compares the incoming `X-User-ID` against
        the first two of them."

        Design: Corner/rbac/the_operator_who_costs_or_submits_a_plan_cannot_approve_it
        """
        world = _two_plans_under_review_costed_and_submitted_by_four_planners()

        refused = api.approve_plan(world["first"]["id"], AS_PLANNER_1)
        validate_error(refused, "ERR_SEGREGATION_OF_DUTIES", 403)

        plan = fetch_plan(world["first"]["id"], PLANNER)
        assert plan["status"] == "UNDER_REVIEW"
        assert plan["approved_by_user_id"] is None

    def test_the_second_plans_coster_is_blocked_the_same_way(self, api):
        """PRD §3.6: "Segregation of duties requires the acting `X-User-ID` to differ from
        *both* `costed_by_user_id` and `submitted_by_user_id`; matching either one is
        rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/the_operator_who_costs_or_submits_a_plan_cannot_approve_it
        """
        world = _two_plans_under_review_costed_and_submitted_by_four_planners()

        refused = api.approve_plan(world["second"]["id"], AS_PLANNER_3)
        validate_error(refused, "ERR_SEGREGATION_OF_DUTIES", 403)
        assert fetch_plan(world["second"]["id"], PLANNER)["status"] == "UNDER_REVIEW"


class TestTheSubmitterMayNotApproveEither:
    def test_approving_as_the_operator_who_submitted_is_a_segregation_failure(
        self, api
    ):
        """PRD §3.6: "Segregation of duties requires the acting `X-User-ID` to differ from
        *both* `costed_by_user_id` and `submitted_by_user_id`; matching either one is
        rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/the_operator_who_costs_or_submits_a_plan_cannot_approve_it
        """
        world = _two_plans_under_review_costed_and_submitted_by_four_planners()

        refused = api.approve_plan(world["first"]["id"], AS_PLANNER_2)
        validate_error(refused, "ERR_SEGREGATION_OF_DUTIES", 403)

        second_refusal = api.approve_plan(world["second"]["id"], AS_PLANNER_4)
        validate_error(second_refusal, "ERR_SEGREGATION_OF_DUTIES", 403)
        assert fetch_plan(world["second"]["id"], PLANNER)["approved_by_user_id"] is None


class TestTheGuardIsIdentityBasedNotRoleBased:
    def test_a_third_operator_in_the_same_role_clears_both_plans(self, api):
        """PRD §3.6: "On success the director's `X-User-ID` is recorded in
        `approved_by_user_id` and the plan's `version` increments by one."
        PRD §2.1: "There is no user entity in this domain."

        Design: Corner/rbac/the_operator_who_costs_or_submits_a_plan_cannot_approve_it
        """
        world = _two_plans_under_review_costed_and_submitted_by_four_planners()
        validate_error(
            api.approve_plan(world["first"]["id"], AS_PLANNER_1),
            "ERR_SEGREGATION_OF_DUTIES",
            403,
        )

        first = validate_success(
            api.approve_plan(world["first"]["id"], DIRECTOR_9), 200
        )
        assert first["status"] == "APPROVED"
        assert first["approved_by_user_id"] == "u-director-9"
        assert first["version"] == world["first"]["version"] + 1

        second = validate_success(
            api.approve_plan(world["second"]["id"], DIRECTOR_9), 200
        )
        assert second["status"] == "APPROVED"
        assert second["approved_by_user_id"] == "u-director-9"


class TestTheRevisionEdgeClearsTheRecordedIdentities:
    def test_sending_an_approved_plan_back_wipes_all_three_stamps(self, api):
        """PRD §3.6: "When it is legal, it increments `revision_round`, clears
        `costed_by_user_id`, `submitted_by_user_id` *and* `approved_by_user_id`, and
        additionally unwinds every presorted drop: each drop of the plan whose
        `production_status` is `PRESORTED` reverts `PRESORTED → PLANNED`, its presort batch
        rows are deleted, its `postage_total_cents` and `automation_share_bps` reset to 0
        with `automation_qualified` reset to false, and its cost per book is recomputed
        under the estimated-postage reading with `cost_basis` set to `ESTIMATED_POSTAGE`;
        each such drop's `version` increments by one."
        PRD §3.6: "Clearing both operator identities matters: it means the
        segregation-of-duties check on the *next* approval is evaluated only against the
        operators of the new cost-and-submit pair."

        Design: Corner/rbac/the_operator_who_costs_or_submits_a_plan_cannot_approve_it
        """
        world = _two_plans_under_review_costed_and_submitted_by_four_planners()
        plan_id = world["first"]["id"]
        approved = validate_success(api.approve_plan(plan_id, DIRECTOR_9), 200)
        assert approved["revision_round"] == 0

        reverted = validate_success(
            api.request_plan_revision(plan_id, DIRECTOR_9, {"note": "re-plan"}), 200
        )
        assert reverted["status"] == "DRAFT"
        assert reverted["revision_round"] == 1
        assert reverted["costed_by_user_id"] is None
        assert reverted["submitted_by_user_id"] is None
        assert reverted["approved_by_user_id"] is None
