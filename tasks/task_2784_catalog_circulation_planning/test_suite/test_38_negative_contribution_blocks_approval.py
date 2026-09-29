"""Approval reads the current roll-up, not a verdict cached at costing.

The plan is legal in every other respect — budget intact, universe complete,
approver a third person — and is refused purely on the sign of
planned_contribution_cents. It is then repaired through the revision back-edge rather
than replaced, and the identical approve call succeeds, which is only possible if the
guard re-reads the roll-up after the unprofitable line has been retired.
"""
from test_helpers import (
    BROKER,
    CLOCK_START,
    DIRECTOR_9,
    PLANNER_1,
    allocate,
    assert_plan_budget_conserved,
    cost_plan,
    create_merge_purge_run_payload,
    fetch_line,
    fetch_plan,
    iso_utc,
    new_drop,
    new_housefile_line,
    new_plan,
    new_season,
    new_segment,
    set_clock,
    submit_plan,
    validate_error,
    validate_success,
)

POOR_SCORING = {
    "recency_days": 45,
    "orders_12mo": 7,
    "ltv_cents": 62000,
    "housefile_count": 30000,
    "avg_order_value_cents": 1000,
    "historical_response_rate_bps": 10,
}

GOOD_SCORING = {
    "recency_days": 45,
    "orders_12mo": 7,
    "ltv_cents": 62000,
    "housefile_count": 30000,
    "avg_order_value_cents": 18500,
    "historical_response_rate_bps": 620,
}


def _a_plan_under_review_that_loses_money(api) -> dict:
    """S_POOR scores BEST on recency-frequency-monetary — so it is never suppressed —
    but responds at 10 basis points into a 1000-cent order, which cannot cover 236
    cents a book. u-planner-1 costs and submits; u-director-9 will approve, so
    segregation of duties cannot fire."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    poor = new_segment(season["id"], segment_code="S_POOR", **POOR_SCORING)
    good = new_segment(season["id"], segment_code="S_GOOD", **GOOD_SCORING)
    plan = new_plan(
        season["id"], headers=PLANNER_1, plan_code="P1", budget_cents=20000000
    )
    validate_success(
        api.create_merge_purge_run(
            plan["id"], create_merge_purge_run_payload(plan["version"], []), BROKER
        ),
        201,
    )
    drop = new_drop(
        plan["id"],
        headers=PLANNER_1,
        drop_number=1,
        in_home_date=iso_utc("2026-09-15"),
        page_count=64,
    )
    poor_line = new_housefile_line(
        drop["id"], poor["id"], headers=PLANNER_1, requested_quantity=20000
    )
    allocated_drop = allocate(drop["id"], PLANNER_1)
    costed = cost_plan(plan["id"])
    under_review = submit_plan(plan["id"], PLANNER_1)
    return {
        "season": season,
        "poor": poor,
        "good": good,
        "plan": plan,
        "drop": allocated_drop,
        "poor_line": fetch_line(poor_line["id"], PLANNER_1),
        "costed": costed,
        "under_review": under_review,
    }


def _the_same_plan_repaired_through_the_back_edge(api) -> dict:
    """The refused approval, the director's revision request, the void of the
    unprofitable line, a replacement S_GOOD line, and a second cost-submit-approve
    cycle by the same two operators."""
    world = _a_plan_under_review_that_loses_money(api)
    plan_id = world["plan"]["id"]

    world["refused"] = api.approve_plan(plan_id, DIRECTOR_9)
    validate_error(world["refused"], "ERR_PLAN_CONTRIBUTION_NEGATIVE", 422)

    world["revised"] = validate_success(
        api.request_plan_revision(
            plan_id, DIRECTOR_9, {"note": "kill the unprofitable segment"}
        ),
        200,
    )
    validate_success(
        api.void_line(
            world["poor_line"]["id"], PLANNER_1, {"reason": "negative contribution"}
        ),
        200,
    )
    world["plan_after_void"] = fetch_plan(plan_id, PLANNER_1)
    world["good_line"] = new_housefile_line(
        world["drop"]["id"],
        world["good"]["id"],
        headers=PLANNER_1,
        requested_quantity=20000,
    )
    allocate(world["drop"]["id"], PLANNER_1)
    world["recosted"] = cost_plan(plan_id)
    submit_plan(plan_id, PLANNER_1)
    world["approved"] = validate_success(api.approve_plan(plan_id, DIRECTOR_9), 200)
    return world


class TestFiscalResponsibilityStandsInFrontOfApproval:
    def test_a_negative_roll_up_is_refused_though_every_other_guard_passes(self, api):
        """PRD §3.6: "Segregation of duties requires the acting `X-User-ID` to differ
        from *both* `costed_by_user_id` and `submitted_by_user_id`; matching either one
        is rejected with `ERR_SEGREGATION_OF_DUTIES`. Fiscal responsibility requires
        `planned_contribution_cents` to be zero or greater; a negative figure is
        rejected with `ERR_PLAN_CONTRIBUTION_NEGATIVE`, so a single deeply unprofitable
        rental line can block approval of an otherwise healthy plan."

        Design: Corner/validations/a_plan_with_negative_contribution_cannot_be_approved
        """
        world = _a_plan_under_review_that_loses_money(api)

        assert world["drop"]["planned_quantity"] == 20000
        assert world["drop"]["cost_per_book_cents"] == 236
        assert world["costed"]["planned_cost_cents"] == 4720000
        assert world["costed"]["planned_demand_cents"] == 20000
        assert world["costed"]["planned_contribution_cents"] == -4711600
        assert world["under_review"]["status"] == "UNDER_REVIEW"

        response = api.approve_plan(world["plan"]["id"], DIRECTOR_9)
        validate_error(response, "ERR_PLAN_CONTRIBUTION_NEGATIVE", 422)

        plan = fetch_plan(world["plan"]["id"], PLANNER_1)
        assert plan["status"] == "UNDER_REVIEW"
        assert plan["approved_by_user_id"] is None


class TestTheBackEdgeRepairsTheSamePlan:
    def test_the_revision_request_clears_both_operator_identities(self, api):
        """PRD §3.6: "From `UNDER_REVIEW → DRAFT` it increments `revision_round` by
        one and sets both `costed_by_user_id` and `submitted_by_user_id` back to null,
        incrementing `version` by one. Clearing both operator identities matters: it
        means the segregation-of-duties check on the *next* approval is evaluated only
        against the operators of the new cost-and-submit pair."

        Design: Corner/validations/a_plan_with_negative_contribution_cannot_be_approved
        """
        world = _the_same_plan_repaired_through_the_back_edge(api)
        revised = world["revised"]

        assert revised["status"] == "DRAFT"
        assert revised["revision_round"] == 1
        assert revised["costed_by_user_id"] is None
        assert revised["submitted_by_user_id"] is None
        assert revised["version"] == world["under_review"]["version"] + 1

    def test_voiding_the_unprofitable_line_releases_its_commitment(self, api):
        """PRD §3.5: "Retiring an allocated line takes it `ALLOCATED → VOIDED` and
        credits the plan's `committed_cost_cents` back by *exactly* the line's
        `committed_cost_cents` before zeroing that field on the line, then recomputes
        `uncommitted_budget_cents`; the compensation is exact in both directions, so the
        budget identity of §2.7 holds before and after with no drift."

        Design: Corner/validations/a_plan_with_negative_contribution_cannot_be_approved
        """
        world = _the_same_plan_repaired_through_the_back_edge(api)

        assert fetch_line(world["poor_line"]["id"], PLANNER_1)["status"] == "VOIDED"
        assert world["plan_after_void"]["committed_cost_cents"] == 0
        assert world["plan_after_void"]["uncommitted_budget_cents"] == 20000000
        assert_plan_budget_conserved(world["plan_after_void"])

    def test_the_identical_approve_passes_on_the_re_read_roll_up(self, api):
        """PRD §3.6: "Fiscal responsibility requires `planned_contribution_cents` to
        be zero or greater; a negative figure is rejected with
        `ERR_PLAN_CONTRIBUTION_NEGATIVE`, so a single deeply unprofitable rental line
        can block approval of an otherwise healthy plan. On success the director's
        `X-User-ID` is recorded in `approved_by_user_id` and the plan's `version`
        increments by one."

        Design: Corner/validations/a_plan_with_negative_contribution_cannot_be_approved
        """
        world = _the_same_plan_repaired_through_the_back_edge(api)

        assert world["recosted"]["planned_contribution_cents"] == 4914800
        assert world["approved"]["status"] == "APPROVED"
        assert world["approved"]["revision_round"] == 1
        assert world["approved"]["approved_by_user_id"] == "u-director-9"
        assert fetch_line(world["good_line"]["id"], PLANNER_1)["status"] == "ALLOCATED"
