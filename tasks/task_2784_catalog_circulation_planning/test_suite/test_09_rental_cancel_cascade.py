"""Cancelling a rental, four hops deep.

The unwind enters the graph from the procurement side: the rental's names go
to zero, the completed merge-purge run goes stale and recomputes, the rental
line is voided and refunds its commitment, the drop's quantities fall, and the
costed plan drops back to DRAFT.
"""
from test_helpers import (
    BROKER,
    CLOCK_START,
    PLANNER_1,
    allocate,
    assert_circulation_plan,
    assert_line_zeroed,
    assert_merge_purge_names_conserved,
    assert_plan_budget_conserved,
    cost_plan,
    fetch_drop,
    fetch_line,
    fetch_plan,
    fetch_rental,
    get_success_data,
    iso_utc,
    new_drop,
    new_housefile_line,
    new_plan,
    new_rental_in_state,
    new_rental_line,
    new_season,
    new_segment,
    run_merge_purge,
    set_clock,
    validate_paginated,
)


def _costed_plan_with_a_rental_line() -> dict:
    """A COSTED plan whose only drop carries a housefile line for 10000 books
    and a rental line for the 20000 names the merge-purge netted."""
    set_clock(CLOCK_START)
    season = new_season()
    segment = new_segment(season["id"], segment_code="S_PREMIUM")
    rental = new_rental_in_state(
        season["id"],
        coop_model_score=640,
        delivered_gross_names=25000,
        list_source_name="COOP-A",
        requested_gross_names=25000,
        cost_per_thousand_cents=8500,
        housefile_overlap_bps=2000,
        inter_list_overlap_bps=0,
    )
    plan = new_plan(season["id"], plan_code="P1")
    run = run_merge_purge(plan["id"], [rental["id"]])
    drop = new_drop(plan["id"], drop_number=1, in_home_date=iso_utc("2026-09-15"))
    housefile_line = new_housefile_line(
        drop["id"], segment["id"], requested_quantity=10000
    )
    rental_line = new_rental_line(
        drop["id"], rental["id"], requested_quantity=25000
    )
    allocate(drop["id"])
    cost_plan(plan["id"], PLANNER_1)
    return {
        "season": season,
        "segment": segment,
        "rental": rental,
        "plan": plan,
        "merge_purge_run": run,
        "drop": drop,
        "housefile_line": housefile_line,
        "rental_line": rental_line,
    }


def _run_by_id(api, plan_id, run_id) -> dict:
    runs, _meta = validate_paginated(api.list_merge_purge_runs(plan_id, BROKER))
    return next(row for row in runs if row["id"] == run_id)


class TestRentalCancelCascade:
    def test_cancelling_zeroes_the_names_and_drags_the_run_to_stale(self, api):
        """PRD §3.2: "First, the rental's `gross_names` and `net_names_delivered`
        are both set to 0. Second, every merge-purge run in `COMPLETED` status
        whose input set contains this rental moves to `STALE` and recomputes its
        name aggregates with the cancelled rental excluded from both the input set
        and the pinned processing order."

        Design: Difficulty/transitive_cascade/rental_cancel_cascades_four_hops_and_makes_merge_purge_run_stale
        """
        world = _costed_plan_with_a_rental_line()
        rental_id = world["rental"]["id"]
        plan_id = world["plan"]["id"]

        assert world["rental"]["expected_response_rate_bps"] == 132
        assert world["rental"]["unit_cost_cents_per_name"] == 9

        before = world["merge_purge_run"]
        assert before["gross_input_names"] == 55000
        assert before["duplicates_removed"] == 5000
        assert before["net_mailable_names"] == 50000
        assert fetch_rental(rental_id)["net_names_delivered"] == 20000

        rental_line = fetch_line(world["rental_line"]["id"])
        assert rental_line["unit_cost_cents"] == 245
        assert rental_line["allocated_quantity"] == 20000
        assert rental_line["committed_cost_cents"] == 4900000

        plan = fetch_plan(plan_id)
        assert plan["status"] == "COSTED"
        assert plan["committed_cost_cents"] == 7260000
        assert plan["planned_contribution_cents"] == -1134216

        get_success_data(
            api.cancel_rental(
                rental_id, BROKER, {"reason": "broker withdrew the list"}
            )
        )

        cancelled = fetch_rental(rental_id)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["gross_names"] == 0
        assert cancelled["net_names_delivered"] == 0

        run = _run_by_id(api, plan_id, before["id"])
        assert run["status"] == "STALE"
        assert run["gross_input_names"] == 30000
        assert run["suppressed_names"] == 0
        assert run["duplicates_removed"] == 0
        assert run["net_mailable_names"] == 30000
        assert_merge_purge_names_conserved(run)

    def test_the_voided_rental_line_refunds_the_plan_and_reopens_it(self, api):
        """PRD §3.2: "Fourth — because each of those lines has left `ALLOCATED` —
        each line's `committed_cost_cents` is credited back to its plan's
        `committed_cost_cents` and then zeroed on the line, and the plan's
        `uncommitted_budget_cents` is recomputed."

        Design: Difficulty/transitive_cascade/rental_cancel_cascades_four_hops_and_makes_merge_purge_run_stale
        """
        world = _costed_plan_with_a_rental_line()
        get_success_data(
            api.cancel_rental(
                world["rental"]["id"], BROKER, {"reason": "broker withdrew the list"}
            )
        )

        rental_line = fetch_line(world["rental_line"]["id"])
        assert rental_line["status"] == "VOIDED"
        assert_line_zeroed(rental_line)

        plan = fetch_plan(world["plan"]["id"])
        assert_circulation_plan(plan)
        assert plan["committed_cost_cents"] == 2360000
        assert plan["uncommitted_budget_cents"] == 17640000
        assert_plan_budget_conserved(plan)
        assert plan["planned_cost_cents"] == 2360000
        assert plan["planned_demand_cents"] == 11470000
        assert plan["planned_contribution_cents"] == 2457400
        assert plan["status"] == "DRAFT"

        drop = fetch_drop(world["drop"]["id"])
        assert drop["requested_quantity_total"] == 10000
        assert drop["planned_quantity"] == 10000
        assert drop["cost_per_book_cents"] == 236
        assert drop["cost_basis"] == "ESTIMATED_POSTAGE"

        housefile_line = fetch_line(world["housefile_line"]["id"])
        assert housefile_line["status"] == "ALLOCATED"
        assert housefile_line["committed_cost_cents"] == 2360000
