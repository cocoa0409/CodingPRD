"""Which rejection a doubly-invalid request receives.

Each pair below builds one call that genuinely violates two rules at once,
proves the earlier check short-circuits the later one, and then removes the
earlier violation so the identical call proves the later rule was live all
along.
"""
from test_helpers import (
    ANALYST,
    CLOCK_START,
    DIRECTOR_9,
    PLANNER,
    PLANNER_1,
    ApiErrorId,
    NON_EXISTENT_UUID,
    allocate,
    cost_plan,
    create_housefile_line_payload,
    fetch_line,
    fetch_plan,
    get_success_data,
    iso_utc,
    new_drop,
    new_housefile_line,
    new_plan,
    new_season,
    new_segment,
    run_merge_purge,
    set_clock,
    submit_plan,
    validate_error,
    validate_paginated,
)


def _plan_under_review_with_one_hundred_cents_left() -> dict:
    """A plan whose first drop consumed all but 100 cents of a 4720100-cent
    budget, whose second drop still holds a PROPOSED line, and which has been
    costed and submitted so it sits in UNDER_REVIEW."""
    set_clock(CLOCK_START)
    season = new_season()
    seg_a = new_segment(season["id"], segment_code="S_A")
    seg_b = new_segment(season["id"], segment_code="S_B")
    plan = new_plan(season["id"], plan_code="P1", budget_cents=4720100)
    run_merge_purge(plan["id"])

    drop_one = new_drop(
        plan["id"], drop_number=1, in_home_date=iso_utc("2026-09-15")
    )
    new_housefile_line(drop_one["id"], seg_a["id"], requested_quantity=20000)
    allocate(drop_one["id"])

    drop_two = new_drop(
        plan["id"], drop_number=2, in_home_date=iso_utc("2026-10-20")
    )
    line_two = new_housefile_line(
        drop_two["id"], seg_b["id"], requested_quantity=20000
    )

    cost_plan(plan["id"], PLANNER_1)
    submit_plan(plan["id"], PLANNER_1)
    return {
        "season": season,
        "seg_a": seg_a,
        "seg_b": seg_b,
        "plan": plan,
        "drop_one": drop_one,
        "drop_two": drop_two,
        "line_two": line_two,
    }


class TestPlanStateBeatsPlanBudget:
    def test_an_uneditable_plan_reports_its_state_not_its_empty_budget(self, api):
        """PRD §2.10: "When a request violates more than one rule, exactly one
        rejection is returned, and which one is fully determined. Checks run in
        the fixed order below; the first violated check wins and short-circuits
        every later check."

        Design: Difficulty/priority_pair_validation_conflict/plan_not_editable_at_40_wins_over_budget_exhausted_at_92
        """
        world = _plan_under_review_with_one_hundred_cents_left()
        plan_id = world["plan"]["id"]

        before = fetch_plan(plan_id)
        assert before["status"] == "UNDER_REVIEW"
        assert before["committed_cost_cents"] == 4720000
        assert before["uncommitted_budget_cents"] == 100

        error = validate_error(
            api.allocate_drop(world["drop_two"]["id"], PLANNER),
            ApiErrorId.ERR_PLAN_NOT_EDITABLE.value,
            409,
        )
        assert error["error_id"] != ApiErrorId.ERR_PLAN_BUDGET_EXHAUSTED.value

        line_two = fetch_line(world["line_two"]["id"])
        assert line_two["status"] == "PROPOSED"
        assert line_two["allocated_quantity"] == 0
        assert line_two["committed_cost_cents"] == 0

        after = fetch_plan(plan_id)
        assert after["committed_cost_cents"] == 4720000

    def test_reopening_the_plan_exposes_the_budget_rejection_underneath(self, api):
        """PRD §3.5: "When the highest-priority `PROPOSED` line cannot afford even
        one book out of the plan's `uncommitted_budget_cents`, the whole
        allocation request is rejected with `ERR_PLAN_BUDGET_EXHAUSTED` rather
        than committing nothing and reporting success."

        Design: Difficulty/priority_pair_validation_conflict/plan_not_editable_at_40_wins_over_budget_exhausted_at_92
        """
        world = _plan_under_review_with_one_hundred_cents_left()
        plan_id = world["plan"]["id"]
        drop_two_id = world["drop_two"]["id"]

        validate_error(
            api.allocate_drop(drop_two_id, PLANNER),
            ApiErrorId.ERR_PLAN_NOT_EDITABLE.value,
            409,
        )

        reopened = get_success_data(
            api.request_plan_revision(plan_id, DIRECTOR_9, {"note": "trim drop 2"})
        )
        assert reopened["status"] == "DRAFT"
        assert reopened["revision_round"] == 1

        validate_error(
            api.allocate_drop(drop_two_id, PLANNER),
            ApiErrorId.ERR_PLAN_BUDGET_EXHAUSTED.value,
            422,
        )

        line_two = fetch_line(world["line_two"]["id"])
        assert line_two["status"] == "PROPOSED"
        assert fetch_plan(plan_id)["uncommitted_budget_cents"] == 100


def _crowded_suppressed_segment_world() -> dict:
    """One segment already carrying a live line on a drop five days away, then
    patched to SUPPRESS_ONLY, plus an empty second drop inside the 21-day
    buffer."""
    set_clock(CLOCK_START)
    season = new_season()
    segment = new_segment(season["id"], segment_code="S_A")
    plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)
    run_merge_purge(plan["id"])

    drop_one = new_drop(
        plan["id"], drop_number=1, in_home_date=iso_utc("2026-09-15")
    )
    line_one = new_housefile_line(
        drop_one["id"], segment["id"], requested_quantity=20000
    )
    drop_two = new_drop(
        plan["id"], drop_number=2, in_home_date=iso_utc("2026-09-20")
    )
    return {
        "season": season,
        "segment": segment,
        "plan": plan,
        "drop_one": drop_one,
        "drop_two": drop_two,
        "line_one": line_one,
    }


class TestSegmentSuppressionBeatsInHomeSpacing:
    def test_a_suppressed_segment_reports_suppression_not_crowding(self, api):
        """PRD §3.5: "A housefile segment whose `contact_strategy` is
        `SUPPRESS_ONLY` may not be given circulation at all, and naming one is
        rejected with `ERR_SEGMENT_SUPPRESSED`."

        Design: Difficulty/priority_pair_validation_conflict/segment_suppressed_at_55_wins_over_inhome_spacing_at_74
        """
        world = _crowded_suppressed_segment_world()
        segment_id = world["segment"]["id"]
        assert world["segment"]["contact_strategy"] == "PREMIUM_FULL"

        patched = get_success_data(
            api.update_segment(
                segment_id, {"contact_strategy": "SUPPRESS_ONLY"}, PLANNER
            )
        )
        assert patched["contact_strategy"] == "SUPPRESS_ONLY"

        error = validate_error(
            api.create_line(
                world["drop_two"]["id"],
                create_housefile_line_payload(segment_id, requested_quantity=5000),
                PLANNER,
            ),
            ApiErrorId.ERR_SEGMENT_SUPPRESSED.value,
            422,
        )
        assert error["error_id"] != ApiErrorId.ERR_INHOME_SPACING_VIOLATION.value

        lines, meta = validate_paginated(
            api.list_lines(PLANNER, {"drop_id": world["drop_two"]["id"]})
        )
        assert meta["total_count"] == 0
        assert lines == []
        assert fetch_line(world["line_one"]["id"])["status"] == "PROPOSED"

    def test_lifting_the_suppression_exposes_the_spacing_rejection(self, api):
        """PRD §3.5: "And a single housefile segment may not be mailed by two
        drops whose in-home dates crowd each other: the whole-day distance
        between this drop's `in_home_date` and the `in_home_date` of any other
        drop that already carries a live line for the same segment must be at
        least the season's `min_inhome_gap_days`."

        Design: Difficulty/priority_pair_validation_conflict/segment_suppressed_at_55_wins_over_inhome_spacing_at_74
        """
        world = _crowded_suppressed_segment_world()
        segment_id = world["segment"]["id"]
        drop_two_id = world["drop_two"]["id"]

        get_success_data(
            api.update_segment(
                segment_id, {"contact_strategy": "SUPPRESS_ONLY"}, PLANNER
            )
        )
        validate_error(
            api.create_line(
                drop_two_id,
                create_housefile_line_payload(segment_id, requested_quantity=5000),
                PLANNER,
            ),
            ApiErrorId.ERR_SEGMENT_SUPPRESSED.value,
            422,
        )

        restored = get_success_data(
            api.update_segment(
                segment_id, {"contact_strategy": "STANDARD"}, PLANNER
            )
        )
        assert restored["contact_strategy"] == "STANDARD"

        validate_error(
            api.create_line(
                drop_two_id,
                create_housefile_line_payload(segment_id, requested_quantity=5000),
                PLANNER,
            ),
            ApiErrorId.ERR_INHOME_SPACING_VIOLATION.value,
            409,
        )

        _lines, meta = validate_paginated(
            api.list_lines(PLANNER, {"drop_id": drop_two_id})
        )
        assert meta["total_count"] == 0


class TestForbiddenRoleBeatsMissingLine:
    def test_an_unauthorised_caller_cannot_probe_which_line_ids_exist(self, api):
        """PRD §2.8: "Several endpoints address a resource through a parent, and
        path identifiers are resolved strictly left to right after the
        authentication and role checks have passed."

        Design: Difficulty/priority_pair_validation_conflict/auth_forbidden_role_at_20_wins_over_line_not_found_at_30
        """
        set_clock(CLOCK_START)
        new_season()

        error = validate_error(
            api.void_line(NON_EXISTENT_UUID, ANALYST, {"reason": "probe"}),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )
        assert error["error_id"] != ApiErrorId.ERR_LINE_NOT_FOUND.value

    def test_the_authorised_caller_then_receives_the_not_found(self, api):
        """PRD §2.10: "**Every path identifier resolves**, on every endpoint that
        has one — otherwise the matching 404 from §2.8."

        Design: Difficulty/priority_pair_validation_conflict/auth_forbidden_role_at_20_wins_over_line_not_found_at_30
        """
        set_clock(CLOCK_START)
        new_season()

        forbidden = api.void_line(NON_EXISTENT_UUID, ANALYST, {"reason": "probe"})
        validate_error(forbidden, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

        missing = api.void_line(NON_EXISTENT_UUID, PLANNER, {"reason": "probe"})
        validate_error(missing, ApiErrorId.ERR_LINE_NOT_FOUND.value, 404)

        assert forbidden.status_code == 403
        assert missing.status_code == 404
        assert forbidden.status_code != missing.status_code
