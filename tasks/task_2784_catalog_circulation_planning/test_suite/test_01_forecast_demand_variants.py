"""Both variants of a circulation line's forecast demand.

A line persists a pre-merge gross forecast alongside the committed net
forecast. The two figures coincide only when a line was allocated its full
request with no holdout carved out, so a clamped holdout line is where they
pull apart.
"""
from test_helpers import (
    CLOCK_START,
    allocate,
    assert_circulation_line,
    assert_circulation_plan,
    assert_drop,
    assert_plan_budget_conserved,
    fetch_drop,
    fetch_line,
    fetch_plan,
    iso_utc,
    set_clock,
    setup_drop_with_proposed_line,
)


def _clamped_holdout_world() -> dict:
    """A 94-page drop carrying one PROPOSED housefile line that asks for 95000
    books out of a 30000-name segment and reserves ten percent as a holdout."""
    set_clock(CLOCK_START)
    return setup_drop_with_proposed_line(
        segment_overrides={"segment_code": "S_PREMIUM"},
        plan_overrides={"plan_code": "P1"},
        drop_overrides={"page_count": 94, "in_home_date": iso_utc("2026-09-15")},
        line_overrides={
            "requested_quantity": 95000,
            "is_holdout": True,
            "holdout_pct_bps": 1000,
        },
    )


class TestForecastDemandVariants:
    def test_gross_variant_prices_the_requested_universe_and_survives_allocation(self):
        """PRD §3.5: "The gross order count is `requested_quantity` multiplied by
        `effective_response_bps`, divided by ten thousand, floored to a whole
        number of orders, and `gross_forecast_demand_cents` is that order count
        multiplied by the resolved average order value."

        Design: Difficulty/dual_variant_calc/line_demand_forecast_gross_vs_net_diverge_on_holdout_line
        """
        world = _clamped_holdout_world()

        run = world["merge_purge_run"]
        assert run["status"] == "COMPLETED"
        assert run["gross_input_names"] == 30000
        assert run["net_mailable_names"] == 30000

        at_create = world["line"]
        assert_circulation_line(at_create)
        assert at_create["status"] == "PROPOSED"
        assert at_create["effective_response_bps"] == 620
        assert at_create["gross_forecast_demand_cents"] == 108965000
        assert at_create["forecast_demand_cents"] == 0
        assert at_create["allocated_quantity"] == 0

        allocate(world["drop"]["id"])
        line = fetch_line(at_create["id"])
        assert_circulation_line(line)
        assert line["status"] == "ALLOCATED"
        assert line["gross_forecast_demand_cents"] == 108965000
        assert line["allocated_quantity"] == 30000
        assert line["holdout_quantity"] == 3000
        assert line["mailable_quantity"] == 27000
        assert line["forecast_demand_cents"] == 30969000
        assert line["gross_forecast_demand_cents"] != line["forecast_demand_cents"]

    def test_holdout_line_commits_on_allocated_books_but_earns_on_mailable_books(self):
        """PRD §3.5: "There is a deliberate asymmetry here worth internalising:
        the budget was committed at the *provisional* cost per book on the
        *allocated* quantity including the holdout, while profitability is
        measured at the *final* cost per book on the *mailable* quantity only."

        Design: Difficulty/dual_variant_calc/line_demand_forecast_gross_vs_net_diverge_on_holdout_line
        """
        world = _clamped_holdout_world()
        allocate(world["drop"]["id"])

        drop = fetch_drop(world["drop"]["id"])
        line = fetch_line(world["line"]["id"])
        plan = fetch_plan(world["plan"]["id"])
        assert_drop(drop)
        assert_circulation_line(line)
        assert_circulation_plan(plan)

        assert drop["provisional_cost_per_book_cents"] == 309
        assert drop["planned_quantity"] == 30000
        assert drop["print_rebate_bps"] == 0
        assert drop["cost_per_book_cents"] == 321

        assert line["unit_cost_cents"] == 309
        assert line["committed_cost_cents"] == 9270000
        assert line["gross_margin_cents"] == 13006980
        assert line["circulation_cost_cents"] == 8667000
        assert line["contribution_cents"] == 4339980

        assert plan["planned_demand_cents"] == 30969000
        assert plan["committed_cost_cents"] == 9270000
        assert plan["uncommitted_budget_cents"] == 10730000
        assert_plan_budget_conserved(plan)
