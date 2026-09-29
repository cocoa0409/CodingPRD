"""The provisional rebate band and the final one, in that pinned order.

The unit cost depends on the print rebate band, the band depends on the
quantity, and the quantity depends on the unit cost. The service breaks the
loop by pricing provisionally off the requested universe, running the
waterfall, and only then re-deriving the band from the planned quantity —
never re-basing the provisional rate.
"""
from test_helpers import (
    CLOCK_START,
    allocate,
    assert_circulation_line,
    assert_drop,
    assert_plan_budget_conserved,
    fetch_drop,
    fetch_line,
    fetch_plan,
    iso_utc,
    new_drop,
    new_housefile_line,
    new_plan,
    new_season,
    new_segment,
    run_merge_purge,
    set_clock,
)


def _two_line_drop() -> dict:
    """One 94-page drop with two PROPOSED housefile lines asking for 125000
    books in total against a 20000000-cent budget."""
    set_clock(CLOCK_START)
    season = new_season()
    big = new_segment(season["id"], segment_code="S_BIG", housefile_count=50000)
    second = new_segment(
        season["id"],
        segment_code="S_SECOND",
        recency_days=200,
        orders_12mo=3,
        ltv_cents=26000,
        housefile_count=30000,
        avg_order_value_cents=9000,
        historical_response_rate_bps=300,
    )
    plan = new_plan(season["id"], plan_code="P1")
    run_merge_purge(plan["id"])
    drop = new_drop(
        plan["id"], page_count=94, in_home_date=iso_utc("2026-09-15")
    )
    line_big = new_housefile_line(drop["id"], big["id"], requested_quantity=95000)
    line_second = new_housefile_line(
        drop["id"], second["id"], requested_quantity=30000
    )
    return {
        "season": season,
        "big": big,
        "second": second,
        "plan": plan,
        "drop": fetch_drop(drop["id"]),
        "line_big": line_big,
        "line_second": line_second,
    }


class TestProvisionalThenFinalRebateBand:
    def test_the_waterfall_spends_at_the_provisional_rate_in_priority_order(self):
        """PRD §3.5: "The provisional rebate band is selected from
        `requested_quantity_total`: 800 basis points at 100000 books or more, 500
        basis points at 40000 or more, and no rebate below that."

        Design: Difficulty/combinatorial_formula/provisional_then_final_rebate_band_evaluation_order_pinned
        """
        world = _two_line_drop()
        assert world["big"]["rfm_score"] == 1000
        assert world["second"]["rfm_score"] == 620
        assert world["drop"]["requested_quantity_total"] == 125000

        allocate(world["drop"]["id"])
        drop = fetch_drop(world["drop"]["id"])
        big = fetch_line(world["line_big"]["id"])
        second = fetch_line(world["line_second"]["id"])
        assert_drop(drop)
        assert_circulation_line(big)
        assert_circulation_line(second)

        assert drop["provisional_cost_per_book_cents"] == 302
        assert big["allocation_rank"] == 1
        assert second["allocation_rank"] == 2
        assert big["unit_cost_cents"] == 302
        assert second["unit_cost_cents"] == 302
        assert big["allocated_quantity"] == 50000
        assert big["committed_cost_cents"] == 15100000
        assert second["allocated_quantity"] == 16225
        assert second["committed_cost_cents"] == 4899950
        assert second["status"] == "ALLOCATED"

        plan = fetch_plan(world["plan"]["id"])
        assert plan["committed_cost_cents"] == 19999950
        assert plan["uncommitted_budget_cents"] == 50
        assert_plan_budget_conserved(plan)

    def test_the_final_band_is_re_derived_from_the_allocated_universe_only(self):
        """PRD §3.6: "Because the rebate band comes from the allocated universe,
        which is generally smaller than the requested universe, the final figure
        normally *exceeds* the provisional figure the budget was actually spent
        at."

        Design: Difficulty/combinatorial_formula/provisional_then_final_rebate_band_evaluation_order_pinned
        """
        world = _two_line_drop()
        allocate(world["drop"]["id"])

        drop = fetch_drop(world["drop"]["id"])
        assert drop["planned_quantity"] == 66225
        assert drop["print_rebate_bps"] == 500
        assert drop["printing_cents_per_book"] == 232
        assert drop["cost_per_book_cents"] == 309
        assert drop["provisional_cost_per_book_cents"] == 302
        assert drop["cost_per_book_cents"] > drop["provisional_cost_per_book_cents"]

        big = fetch_line(world["line_big"]["id"])
        second = fetch_line(world["line_second"]["id"])
        assert big["circulation_cost_cents"] == 15450000
        assert big["contribution_cents"] == 8637000
        assert second["circulation_cost_cents"] == 5013525
        assert second["contribution_cents"] == -3176445

        plan = fetch_plan(world["plan"]["id"])
        assert plan["planned_cost_cents"] == 20463525
        assert plan["planned_demand_cents"] == 61724000
        assert plan["planned_contribution_cents"] == 5460555
