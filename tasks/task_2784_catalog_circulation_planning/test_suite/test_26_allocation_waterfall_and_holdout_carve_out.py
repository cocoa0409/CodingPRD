"""The budget waterfall, and the two cost bases a holdout line splits apart.

Three lines are arranged so each of the three clamps binds on a different one:
the top-priority line runs out of audience, the middle line gets its whole
request, and the last line runs out of budget mid-book. The rental line is also
the only one carrying a per-name surcharge, so a handler that prices the whole
drop at one unit cost lands on a different remainder. The holdout half then pins
the deliberate asymmetry: the commitment is charged on every allocated book, but
profitability is charged only on the books that will actually be mailed.
"""
from test_helpers import (
    BROKER,
    CLOCK_START,
    REFERENCE,
    allocate,
    assert_circulation_line,
    assert_plan_budget_conserved,
    create_merge_purge_run_payload,
    fetch_line,
    fetch_plan,
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
    validate_success,
)

HI_SCORING = {
    "recency_days": 45,
    "orders_12mo": 7,
    "ltv_cents": 62000,
    "avg_order_value_cents": 18500,
    "historical_response_rate_bps": 620,
}

LO_SCORING = {
    "recency_days": 150,
    "orders_12mo": 3,
    "ltv_cents": 13000,
    "avg_order_value_cents": 12000,
    "historical_response_rate_bps": 400,
}


def _three_lines_each_clamped_by_a_different_ceiling(api) -> dict:
    """S_HI owns only 8000 names while 12000 are asked of it, S_LO can supply its
    whole 30000-name request, and the rental line asks for 9000 names out of a
    budget that can only fund 5637 of them at its surcharged unit cost. The lines
    are created low-priority first so creation order cannot pass for rank."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    hi = new_segment(
        season["id"], segment_code="S_HI", housefile_count=8000, **HI_SCORING
    )
    lo = new_segment(
        season["id"], segment_code="S_LO", housefile_count=30000, **LO_SCORING
    )
    rental = new_rental_in_state(
        season["id"],
        "DELIVERED",
        coop_model_score=640,
        delivered_gross_names=10000,
        list_source_name="COOP-A",
        requested_gross_names=10000,
        cost_per_thousand_cents=8500,
        housefile_overlap_bps=1000,
        inter_list_overlap_bps=0,
    )
    plan = new_plan(season["id"], plan_code="P1", budget_cents=10000000)
    validate_success(
        api.create_merge_purge_run(
            plan["id"],
            create_merge_purge_run_payload(plan["version"], [rental["id"]]),
            BROKER,
        ),
        201,
    )
    drop = new_drop(
        plan["id"], drop_number=1, in_home_date=iso_utc("2026-09-15"), page_count=64
    )
    line_lo = new_housefile_line(drop["id"], lo["id"], requested_quantity=30000)
    line_r = new_rental_line(drop["id"], rental["id"], requested_quantity=9000)
    line_hi = new_housefile_line(drop["id"], hi["id"], requested_quantity=12000)

    allocated = allocate(drop["id"])
    return {
        "season": season,
        "plan": fetch_plan(plan["id"]),
        "rental": rental,
        "drop": allocated,
        "line_lo": fetch_line(line_lo["id"]),
        "line_r": fetch_line(line_r["id"]),
        "line_hi": fetch_line(line_hi["id"]),
    }


class TestProvisionalPricingOffTheRequestedUniverse:
    def test_the_rebate_band_comes_from_the_requested_total(self, api):
        """PRD §3.5: "The provisional rebate band is selected from
        `requested_quantity_total`: 800 basis points at 100000 books or more, 500
        basis points at 40000 or more, and no rebate below that. The provisional
        printing component is the drop's `page_count` multiplied by the season's
        `print_cost_per_page_per_thousand_cents`, divided by one thousand, then
        multiplied by ten thousand less the rebate basis points and divided by ten
        thousand, with the result rounded half up to whole cents."

        Design: Corner/calculations/the_waterfall_fills_by_priority_and_clamps_on_audience_then_budget
        """
        world = _three_lines_each_clamped_by_a_different_ceiling(api)
        drop = world["drop"]

        assert drop["requested_quantity_total"] == 51000
        assert drop["provisional_cost_per_book_cents"] == 228
        assert drop["provisional_cost_per_book_cents"] < REFERENCE[
            "estimated_cost_per_book_cents"
        ]
        assert world["rental"]["unit_cost_cents_per_name"] == 9


class TestTheWaterfallWalksInPriorityOrder:
    def test_housefile_outranks_rental_and_rfm_orders_the_housefile(self, api):
        """PRD §3.5: "The waterfall then walks the drop's `PROPOSED` lines in a
        pinned priority order: every `HOUSEFILE` line before every `RENTAL` line;
        within the housefile lines, by the segment's `rfm_score` descending; within
        the rental lines, by the rental's `coop_model_score` descending; and, as the
        final tie-break in every case, by the line's own `created_at` ascending."

        Design: Corner/calculations/the_waterfall_fills_by_priority_and_clamps_on_audience_then_budget
        """
        world = _three_lines_each_clamped_by_a_different_ceiling(api)

        assert world["line_hi"]["allocation_rank"] == 1
        assert world["line_lo"]["allocation_rank"] == 2
        assert world["line_r"]["allocation_rank"] == 3

        for line in (world["line_hi"], world["line_lo"], world["line_r"]):
            assert_circulation_line(line)
            assert line["status"] == "ALLOCATED"
            assert line["holdout_quantity"] == 0
            assert line["mailable_quantity"] == line["allocated_quantity"]

    def test_each_line_is_clamped_by_a_different_one_of_the_three_ceilings(self, api):
        """PRD §3.5: "It sets the line's `unit_cost_cents` to the drop's
        `provisional_cost_per_book_cents` plus, for a rental line only, that rental's
        `unit_cost_cents_per_name`; a housefile line adds nothing. It computes an
        audience cap — the segment's `housefile_count` for a housefile line, the
        rental's `net_names_delivered` for a rental line — and a budget cap, which is
        the remaining budget divided by the line's `unit_cost_cents` and floored,
        because a partial book cannot be printed."

        Design: Corner/calculations/the_waterfall_fills_by_priority_and_clamps_on_audience_then_budget
        """
        world = _three_lines_each_clamped_by_a_different_ceiling(api)

        hi = world["line_hi"]
        assert hi["unit_cost_cents"] == 228
        assert hi["allocated_quantity"] == 8000
        assert hi["committed_cost_cents"] == 1824000

        lo = world["line_lo"]
        assert lo["unit_cost_cents"] == 228
        assert lo["allocated_quantity"] == 30000
        assert lo["committed_cost_cents"] == 6840000

        rental_line = world["line_r"]
        assert rental_line["unit_cost_cents"] == 237
        assert rental_line["allocated_quantity"] == 5637
        assert rental_line["committed_cost_cents"] == 1335969

    def test_the_planned_quantity_and_the_budget_close_on_a_floored_remainder(
        self, api
    ):
        """PRD §3.5: "The drop's `planned_quantity` becomes the sum of
        `allocated_quantity` over its `ALLOCATED` lines. The plan's
        `committed_cost_cents` grows by the total newly frozen, and
        `uncommitted_budget_cents` is recomputed as `budget_cents` less
        `committed_cost_cents`."

        Design: Corner/calculations/the_waterfall_fills_by_priority_and_clamps_on_audience_then_budget
        """
        world = _three_lines_each_clamped_by_a_different_ceiling(api)
        plan = world["plan"]

        assert world["drop"]["planned_quantity"] == 43637
        assert world["drop"]["planned_quantity"] == 8000 + 30000 + 5637

        assert plan["committed_cost_cents"] == 9999969
        assert plan["uncommitted_budget_cents"] == 31
        assert_plan_budget_conserved(plan)


def _one_holdout_line_of_eight_thousand_books() -> dict:
    """A single 8000-name line withholding 1234 basis points of its allocation
    from the mail, on a drop small enough to miss the printer's rebate band."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    segment = new_segment(
        season["id"], segment_code="S_A", housefile_count=30000, **HI_SCORING
    )
    plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)
    run_merge_purge(plan["id"])
    drop = new_drop(
        plan["id"], drop_number=1, in_home_date=iso_utc("2026-09-15"), page_count=64
    )
    line = new_housefile_line(
        drop["id"],
        segment["id"],
        requested_quantity=8000,
        is_holdout=True,
        holdout_pct_bps=1234,
    )
    allocated = allocate(drop["id"])
    return {
        "plan": fetch_plan(plan["id"]),
        "drop": allocated,
        "line": fetch_line(line["id"]),
    }


class TestHoldoutCarveOut:
    def test_the_withheld_share_floors_and_is_still_paid_for(self, api):
        """PRD §3.5: "Otherwise the line moves `PROPOSED → ALLOCATED`, and four
        figures are frozen: `holdout_quantity` becomes `allocated_quantity`
        multiplied by `holdout_pct_bps`, divided by ten thousand, floored;
        `mailable_quantity` becomes `allocated_quantity` less `holdout_quantity`; and
        `committed_cost_cents` becomes `allocated_quantity` multiplied by
        `unit_cost_cents`."

        Design: Corner/calculations/holdout_carve_out_floors_and_splits_the_cost_bases
        """
        world = _one_holdout_line_of_eight_thousand_books()
        line = world["line"]

        assert line["allocated_quantity"] == 8000
        assert line["holdout_quantity"] == 987
        assert line["holdout_quantity"] != 988
        assert line["mailable_quantity"] == 7013
        assert line["mailable_quantity"] == 8000 - 987
        assert line["unit_cost_cents"] == 236
        assert line["committed_cost_cents"] == 1888000

        assert world["drop"]["planned_quantity"] == 8000
        assert world["drop"]["cost_per_book_cents"] == 236

    def test_the_committed_demand_prices_only_the_books_that_will_be_mailed(
        self, api
    ):
        """PRD §3.5: "The drop's cost per book is then re-derived from the new
        `planned_quantity` as described in §3.6, and every allocated line gets its
        **committed view** of demand: `forecast_orders` is the line's
        `mailable_quantity` multiplied by `effective_response_bps`, divided by ten
        thousand, floored, and `forecast_demand_cents` is that order count multiplied
        by the resolved average order value."

        Design: Corner/calculations/holdout_carve_out_floors_and_splits_the_cost_bases
        """
        world = _one_holdout_line_of_eight_thousand_books()
        line = world["line"]

        assert line["forecast_demand_cents"] == 8029000
        assert line["forecast_demand_cents"] < line["gross_forecast_demand_cents"]

    def test_the_two_cost_bases_differ_by_exactly_the_holdout(self, api):
        """PRD §3.5: "`gross_margin_cents` is `forecast_demand_cents` multiplied by
        ten thousand less the season's `cogs_rate_bps`, divided by ten thousand,
        rounded half up. `circulation_cost_cents` is the line's `mailable_quantity`
        multiplied by the drop's *current* `cost_per_book_cents` plus, for a rental
        line, that rental's `unit_cost_cents_per_name`."

        Design: Corner/calculations/holdout_carve_out_floors_and_splits_the_cost_bases
        """
        world = _one_holdout_line_of_eight_thousand_books()
        line = world["line"]

        assert line["gross_margin_cents"] == 3372180
        assert line["circulation_cost_cents"] == 1655068
        assert line["contribution_cents"] == 1717112
        assert line["committed_cost_cents"] - line["circulation_cost_cents"] == 232932
        assert 232932 == 987 * 236
