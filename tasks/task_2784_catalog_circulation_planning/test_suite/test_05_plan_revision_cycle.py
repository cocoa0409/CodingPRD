"""The plan's cycle back-edge from APPROVED and the second lap that follows.

Requesting revision on an approved plan reopens it in DRAFT, clears all three
operator stamps, unwinds every presorted drop, and leaves the allocation and
the committed budget alone. The same cost-submit-approve path then runs a
second time to completion.
"""
from test_helpers import (
    CLOCK_START,
    DIRECTOR_9,
    PLANNER,
    PLANNER_2,
    approve_plan,
    assert_circulation_plan,
    assert_drop,
    cost_plan,
    fetch_drop,
    fetch_line,
    fetch_plan,
    get_success_data,
    iso_utc,
    set_clock,
    setup_presorted_drop,
    submit_plan,
    validate_paginated,
)


def _presorted_approved_world() -> dict:
    """A 94-page drop of 50000 books, presorted over two batches, on a plan
    approved by a director who neither costed nor submitted it."""
    set_clock(CLOCK_START)
    return setup_presorted_drop(
        batches=[("FIVE_DIGIT", 20000), ("MIXED_AADC", 30000)],
        segment_overrides={"segment_code": "S_BIG", "housefile_count": 50000},
        plan_overrides={"plan_code": "P1"},
        drop_overrides={"page_count": 94, "in_home_date": iso_utc("2026-09-15")},
        line_overrides={"requested_quantity": 50000},
    )


class TestPlanRevisionBackEdge:
    def test_requesting_revision_on_an_approved_plan_unwinds_every_presorted_drop(
        self, api
    ):
        """PRD §3.6: "each drop of the plan whose `production_status` is
        `PRESORTED` reverts `PRESORTED → PLANNED`, its presort batch rows are
        deleted, its `postage_total_cents` and `automation_share_bps` reset to 0
        with `automation_qualified` reset to false, and its cost per book is
        recomputed under the estimated-postage reading with `cost_basis` set to
        `ESTIMATED_POSTAGE`; each such drop's `version` increments by one."

        Design: Difficulty/non_linear_state_machine/plan_revision_back_edge_reopens_approved_plan_and_unwinds_presort
        """
        world = _presorted_approved_world()
        plan_id = world["plan"]["id"]
        drop_id = world["drop"]["id"]

        plan = get_success_data(
            api.request_plan_revision(
                plan_id, DIRECTOR_9, {"note": "reprice the paper line"}
            )
        )
        assert_circulation_plan(plan)
        assert plan["status"] == "DRAFT"
        assert plan["revision_round"] == 1
        assert plan["costed_by_user_id"] is None
        assert plan["submitted_by_user_id"] is None
        assert plan["approved_by_user_id"] is None

        batches, meta = validate_paginated(api.list_presort_batches(drop_id, PLANNER))
        assert batches == []
        assert meta["total_count"] == 0

        drop = fetch_drop(drop_id)
        assert_drop(drop)
        assert drop["production_status"] == "PLANNED"
        assert drop["postage_total_cents"] == 0
        assert drop["automation_share_bps"] == 0
        assert drop["automation_qualified"] is False
        assert drop["cost_basis"] == "ESTIMATED_POSTAGE"
        assert drop["postage_cents_per_book"] == 55
        assert drop["cost_per_book_cents"] == 309

    def test_the_reopened_plan_keeps_its_allocation_and_completes_a_second_lap(
        self, api
    ):
        """PRD §3.6: "From `APPROVED → DRAFT` the same back-edge is legal only
        while no book has entered the mail stream — if any drop of the plan has
        `production_status` `MAILED` or `DELIVERED` the request is rejected with
        `ERR_INVALID_PLAN_STATE`."

        Design: Difficulty/non_linear_state_machine/plan_revision_back_edge_reopens_approved_plan_and_unwinds_presort
        """
        world = _presorted_approved_world()
        plan_id = world["plan"]["id"]
        drop_id = world["drop"]["id"]

        get_success_data(
            api.request_plan_revision(
                plan_id, DIRECTOR_9, {"note": "reprice the paper line"}
            )
        )

        line = fetch_line(world["line"]["id"])
        assert line["status"] == "ALLOCATED"
        assert line["circulation_cost_cents"] == 15450000
        assert line["contribution_cents"] == 8637000

        reopened = fetch_plan(plan_id)
        assert reopened["planned_cost_cents"] == 15450000
        assert reopened["planned_contribution_cents"] == 8637000
        assert reopened["committed_cost_cents"] == 15450000

        cost_plan(plan_id, PLANNER_2)
        submit_plan(plan_id, PLANNER_2)
        approved = approve_plan(plan_id, DIRECTOR_9)
        assert_circulation_plan(approved)
        assert approved["status"] == "APPROVED"
        assert approved["revision_round"] == 1
        assert approved["costed_by_user_id"] == "u-planner-2"
        assert approved["submitted_by_user_id"] == "u-planner-2"
        assert approved["approved_by_user_id"] == "u-director-9"

        drop = fetch_drop(drop_id)
        assert drop["production_status"] == "PLANNED"
        assert drop["cost_basis"] == "ESTIMATED_POSTAGE"
