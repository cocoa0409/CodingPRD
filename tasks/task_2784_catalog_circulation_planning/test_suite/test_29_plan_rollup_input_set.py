"""Which lines the plan's profitability roll-up is allowed to count.

The plan deliberately holds one allocated line, one retired line and one line
still proposed on a second drop, so all three exclusions are exercised at once and
the plan totals have to equal the single surviving line's own already-rounded
figures. The on-demand profitability read is then held to being a read: same
numbers, same status, same version.
"""
from test_helpers import (
    BROKER,
    CLOCK_START,
    DIRECTOR,
    PLANNER_1,
    allocate,
    assert_circulation_line,
    cost_plan,
    create_merge_purge_run_payload,
    fetch_drop,
    fetch_line,
    iso_utc,
    new_drop,
    new_housefile_line,
    new_plan,
    new_season,
    new_segment,
    set_clock,
    validate_success,
)

A_SCORING = {
    "recency_days": 45,
    "orders_12mo": 7,
    "ltv_cents": 62000,
    "housefile_count": 30000,
    "avg_order_value_cents": 18500,
    "historical_response_rate_bps": 620,
}

B_SCORING = {
    "recency_days": 150,
    "orders_12mo": 3,
    "ltv_cents": 13000,
    "housefile_count": 30000,
    "avg_order_value_cents": 12000,
    "historical_response_rate_bps": 400,
}


def _one_allocated_one_voided_and_one_proposed_line(api) -> dict:
    """Drop 1 carries lines A and B, both allocated at 236 before B is retired;
    drop 2 carries line C, which is never allocated at all. The plan is then costed
    by u-planner-1 so the roll-up is materialised on the row."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    segment_a = new_segment(season["id"], segment_code="S_A", **A_SCORING)
    segment_b = new_segment(season["id"], segment_code="S_B", **B_SCORING)
    plan = new_plan(
        season["id"], headers=PLANNER_1, plan_code="P1", budget_cents=20000000
    )
    validate_success(
        api.create_merge_purge_run(
            plan["id"], create_merge_purge_run_payload(plan["version"], []), BROKER
        ),
        201,
    )
    drop_one = new_drop(
        plan["id"],
        headers=PLANNER_1,
        drop_number=1,
        in_home_date=iso_utc("2026-09-15"),
        page_count=64,
    )
    drop_two = new_drop(
        plan["id"],
        headers=PLANNER_1,
        drop_number=2,
        in_home_date=iso_utc("2026-10-20"),
        page_count=64,
    )
    line_a = new_housefile_line(
        drop_one["id"], segment_a["id"], headers=PLANNER_1, requested_quantity=20000
    )
    line_b = new_housefile_line(
        drop_one["id"], segment_b["id"], headers=PLANNER_1, requested_quantity=10000
    )
    line_c = new_housefile_line(
        drop_two["id"], segment_a["id"], headers=PLANNER_1, requested_quantity=5000
    )
    allocate(drop_one["id"], PLANNER_1)
    validate_success(api.void_line(line_b["id"], PLANNER_1), 200)
    costed = cost_plan(plan["id"])

    return {
        "plan": costed,
        "drop_one": fetch_drop(drop_one["id"]),
        "drop_two": fetch_drop(drop_two["id"]),
        "line_a": fetch_line(line_a["id"]),
        "line_b": fetch_line(line_b["id"]),
        "line_c": fetch_line(line_c["id"]),
    }


class TestTheRollUpInputSet:
    def test_the_retired_line_and_the_unallocated_line_are_both_excluded(self, api):
        """PRD §3.6: "The roll-up's input set is the whole difficulty: it takes every
        line in status `ALLOCATED` that belongs to a drop of the plan whose
        `production_status` is not `CANCELLED`, and it excludes `VOIDED` lines,
        `SUPPRESSED` lines, lines still sitting in `PROPOSED`, and every line of a
        cancelled drop."

        Design: Corner/calculations/plan_rollup_counts_only_allocated_lines_of_live_drops
        """
        world = _one_allocated_one_voided_and_one_proposed_line(api)

        line_a = world["line_a"]
        assert_circulation_line(line_a)
        assert line_a["status"] == "ALLOCATED"
        assert line_a["mailable_quantity"] == 20000
        assert line_a["forecast_demand_cents"] == 22940000
        assert line_a["gross_margin_cents"] == 9634800
        assert line_a["circulation_cost_cents"] == 4720000
        assert line_a["contribution_cents"] == 4914800

        assert world["line_b"]["status"] == "VOIDED"
        assert world["line_b"]["contribution_cents"] == 0
        assert world["line_c"]["status"] == "PROPOSED"
        assert world["line_c"]["contribution_cents"] == 0

        assert world["drop_two"]["planned_quantity"] == 0
        assert world["drop_two"]["cost_basis"] == "ESTIMATED_POSTAGE"

    def test_the_plan_totals_are_the_sum_of_the_surviving_line_alone(self, api):
        """PRD §3.6: "`planned_cost_cents` is the sum of `circulation_cost_cents`
        across that set, `planned_demand_cents` the sum of `forecast_demand_cents`, and
        `planned_contribution_cents` the sum of `contribution_cents`. Because it sums
        already-rounded per-line contributions, `planned_contribution_cents` is
        deliberately *not* the same number a contribution recomputed from summed demand
        would produce; the per-line reading is the pinned one."

        Design: Corner/calculations/plan_rollup_counts_only_allocated_lines_of_live_drops
        """
        world = _one_allocated_one_voided_and_one_proposed_line(api)
        plan = world["plan"]

        assert plan["status"] == "COSTED"
        assert plan["costed_by_user_id"] == "u-planner-1"
        assert plan["planned_cost_cents"] == 4720000
        assert plan["planned_demand_cents"] == 22940000
        assert plan["planned_contribution_cents"] == 4914800
        assert plan["planned_contribution_cents"] == world["line_a"][
            "contribution_cents"
        ]

    def test_the_profitability_read_recomputes_without_mutating_the_plan(self, api):
        """PRD §3.6: "That read recomputes the roll-up from the plan's currently
        allocated lines and returns the plan with `planned_cost_cents`,
        `planned_demand_cents` and `planned_contribution_cents` refreshed. It is a pure
        read: it does not change the plan's `status` and it does not increment the
        plan's `version`."

        Design: Corner/calculations/plan_rollup_counts_only_allocated_lines_of_live_drops
        """
        world = _one_allocated_one_voided_and_one_proposed_line(api)
        plan = world["plan"]

        read = validate_success(api.get_plan_profitability(plan["id"], DIRECTOR), 200)

        assert read["planned_cost_cents"] == plan["planned_cost_cents"]
        assert read["planned_demand_cents"] == plan["planned_demand_cents"]
        assert read["planned_contribution_cents"] == plan["planned_contribution_cents"]
        assert read["status"] == "COSTED"
        assert read["version"] == plan["version"]
