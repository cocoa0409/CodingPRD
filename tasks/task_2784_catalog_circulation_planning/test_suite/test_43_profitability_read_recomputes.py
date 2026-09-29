"""The profitability read is taken exactly when the stored roll-up is stale.

Retiring the unprofitable line knocks the plan out of COSTED without re-costing it,
so the read has to recompute from the one line still allocated: an implementation that
hands back the stored columns reports the pre-void totals, and one that re-costs as a
side effect drags the plan back into COSTED and moves its version. The read is then
taken twice to show it is idempotent, and once against an identifier that resolves to
nothing.
"""
from test_helpers import (
    ANALYST,
    BROKER,
    CLOCK_START,
    DIRECTOR,
    NON_EXISTENT_UUID,
    PLANNER_1,
    allocate,
    assert_plan_budget_conserved,
    cost_plan,
    create_merge_purge_run_payload,
    fetch_plan,
    iso_utc,
    new_drop,
    new_housefile_line,
    new_plan,
    new_season,
    new_segment,
    set_clock,
    validate_error,
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


def _a_costed_plan_carrying_one_good_and_one_bad_line(api) -> dict:
    """Drop 1 asks for 30000 books, below the 40000-book rebate band, so every book
    costs 236 cents. Line A returns 22940000 cents of demand against 4720000 of cost;
    line B returns 4800000 against 2360000 and therefore loses money."""
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
    drop = new_drop(
        plan["id"],
        headers=PLANNER_1,
        drop_number=1,
        in_home_date=iso_utc("2026-09-15"),
        page_count=64,
    )
    line_a = new_housefile_line(
        drop["id"], segment_a["id"], headers=PLANNER_1, requested_quantity=20000
    )
    line_b = new_housefile_line(
        drop["id"], segment_b["id"], headers=PLANNER_1, requested_quantity=10000
    )
    allocate(drop["id"], PLANNER_1)
    costed = cost_plan(plan["id"])
    return {
        "season": season,
        "plan": plan,
        "drop": drop,
        "line_a": line_a,
        "line_b": line_b,
        "costed": costed,
    }


def _the_same_plan_after_the_bad_line_is_retired(api) -> dict:
    """Voiding line B is a structural mutation, so the plan's own roll-up columns
    stop being a costed quotation and the plan falls back to DRAFT."""
    world = _a_costed_plan_carrying_one_good_and_one_bad_line(api)
    validate_success(
        api.void_line(world["line_b"]["id"], PLANNER_1, {"reason": "loses money"}),
        200,
    )
    world["after_void"] = fetch_plan(world["plan"]["id"], PLANNER_1)
    return world


class TestTheReadAgreesWithAFreshCosting:
    def test_the_read_returns_the_costed_figures_without_moving_the_plan(self, api):
        """PRD §3.6: "That read recomputes the roll-up from the plan's currently
        allocated lines and returns the plan with `planned_cost_cents`,
        `planned_demand_cents` and `planned_contribution_cents` refreshed. It is a pure
        read: it does not change the plan's `status` and it does not increment the plan's
        `version`."

        Design: Corner/endpoints/the_profitability_read_recomputes_and_never_writes
        """
        world = _a_costed_plan_carrying_one_good_and_one_bad_line(api)
        costed = world["costed"]
        assert costed["status"] == "COSTED"

        read = validate_success(
            api.get_plan_profitability(world["plan"]["id"], ANALYST), 200
        )
        assert read["planned_cost_cents"] == costed["planned_cost_cents"]
        assert read["planned_demand_cents"] == costed["planned_demand_cents"]
        assert read["planned_contribution_cents"] == costed[
            "planned_contribution_cents"
        ]
        assert read["status"] == "COSTED"
        assert read["version"] == costed["version"]
        assert fetch_plan(world["plan"]["id"], PLANNER_1)["version"] == costed[
            "version"
        ]

    def test_the_costed_roll_up_sums_both_allocated_lines(self, api):
        """PRD §3.6: "`planned_cost_cents` is the sum of `circulation_cost_cents`
        across that set, `planned_demand_cents` the sum of `forecast_demand_cents`, and
        `planned_contribution_cents` the sum of `contribution_cents`."

        Design: Corner/endpoints/the_profitability_read_recomputes_and_never_writes
        """
        world = _a_costed_plan_carrying_one_good_and_one_bad_line(api)

        read = validate_success(
            api.get_plan_profitability(world["plan"]["id"], ANALYST), 200
        )
        assert read["planned_cost_cents"] == 7080000
        assert read["planned_cost_cents"] == 4720000 + 2360000
        assert read["planned_demand_cents"] == 27740000
        assert read["planned_demand_cents"] == 22940000 + 4800000
        assert read["planned_contribution_cents"] == 4570800
        assert read["planned_contribution_cents"] == 4914800 - 344000


class TestTheVoidInvalidatesTheStoredQuotation:
    def test_retiring_the_line_returns_the_plan_to_draft_and_credits_the_budget(
        self, api
    ):
        """PRD §3.5: "Either way the drop's `requested_quantity_total`, its
        `planned_quantity` and its cost per book are recomputed, then the plan's roll-up
        figures, with a `COSTED` plan falling back to `DRAFT`; the line's `version` and
        the drop's `version` each increment by one."

        Design: Corner/endpoints/the_profitability_read_recomputes_and_never_writes
        """
        world = _the_same_plan_after_the_bad_line_is_retired(api)
        plan = world["after_void"]

        assert plan["status"] == "DRAFT"
        assert plan["committed_cost_cents"] == 4720000
        assert plan["uncommitted_budget_cents"] == 15280000
        assert_plan_budget_conserved(plan)


class TestTheReadRecomputesFromWhatIsStillAllocated:
    def test_the_figures_fall_to_the_single_surviving_line(self, api):
        """PRD §3.6: "That read recomputes the roll-up from the plan's currently
        allocated lines and returns the plan with `planned_cost_cents`,
        `planned_demand_cents` and `planned_contribution_cents` refreshed. It is a pure
        read: it does not change the plan's `status` and it does not increment the plan's
        `version`."

        Design: Corner/endpoints/the_profitability_read_recomputes_and_never_writes
        """
        world = _the_same_plan_after_the_bad_line_is_retired(api)

        read = validate_success(
            api.get_plan_profitability(world["plan"]["id"], ANALYST), 200
        )
        assert read["planned_cost_cents"] == 4720000
        assert read["planned_demand_cents"] == 22940000
        assert read["planned_contribution_cents"] == 4914800
        assert read["status"] == "DRAFT"
        assert read["version"] == world["after_void"]["version"]

    def test_a_second_identical_read_changes_nothing(self, api):
        """PRD §3.6: "It is a pure read: it does not change the plan's `status` and it
        does not increment the plan's `version`."

        Design: Corner/endpoints/the_profitability_read_recomputes_and_never_writes
        """
        world = _the_same_plan_after_the_bad_line_is_retired(api)
        plan_id = world["plan"]["id"]

        first = validate_success(api.get_plan_profitability(plan_id, ANALYST), 200)
        second = validate_success(api.get_plan_profitability(plan_id, DIRECTOR), 200)

        assert second["planned_cost_cents"] == first["planned_cost_cents"]
        assert second["planned_demand_cents"] == first["planned_demand_cents"]
        assert second["planned_contribution_cents"] == first[
            "planned_contribution_cents"
        ]
        assert second["status"] == first["status"]
        assert second["version"] == first["version"]
        assert fetch_plan(plan_id, PLANNER_1)["version"] == world["after_void"][
            "version"
        ]

    def test_an_identifier_that_resolves_to_nothing_is_a_plan_not_found(self, api):
        """PRD §2.8: "Each entity family has its own 404 code:
        `ERR_SEASON_NOT_FOUND` for a catalog season, `ERR_SEGMENT_NOT_FOUND` for a
        housefile segment, `ERR_RENTAL_NOT_FOUND` for a prospect list rental,
        `ERR_PLAN_NOT_FOUND` for a circulation plan, `ERR_DROP_NOT_FOUND` for a drop,
        `ERR_LINE_NOT_FOUND` for a circulation line, `ERR_PLACEMENT_NOT_FOUND` for a page
        placement, `ERR_TEST_CELL_NOT_FOUND` for a test cell, and
        `ERR_MATCHBACK_RUN_NOT_FOUND` for a matchback run."

        Design: Corner/endpoints/the_profitability_read_recomputes_and_never_writes
        """
        _a_costed_plan_carrying_one_good_and_one_bad_line(api)

        response = api.get_plan_profitability(NON_EXISTENT_UUID, ANALYST)
        validate_error(response, "ERR_PLAN_NOT_FOUND", 404)
