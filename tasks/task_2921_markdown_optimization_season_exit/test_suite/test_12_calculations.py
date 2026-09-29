"""Computed quantities whose exact value depends on where the rounding happens
and on which rows the sum is allowed to admit.
"""

import pytest

from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers import fixtures as fx
from test_helpers.factories import (
    donation_order_payload,
    elasticity_estimate_payload,
    jobber_order_payload,
    markdown_plan_payload,
    markdown_step_payload,
    roll_back_payload,
    salvage_order_payload,
)


class TestItemAggregatesRoundHalfUp:
    """Sell-through and weeks of supply are exact-quotient traps."""

    def test_the_four_week_history_lands_on_two_decimal_aggregates(self, api, analyst):
        """PRD 3.2: "Posting a week moves several item aggregates at once.
        `units_sold_total` grows by the week's `units_sold` and the on-hand count
        falls by the same amount; `sample_weeks` grows by one; `sell_through_pct` is
        recomputed as units sold as a percentage of units received, rounded half up
        to two decimals; and `weeks_of_supply` is recomputed as the on-hand units
        divided by the average weekly sales rate, rounded half up to two decimals,
        where that average rate is itself `units_sold_total` divided by
        `sample_weeks` rounded half up to four decimals." PRD 2.8 fixes the method:
        "Wherever this document says a value is rounded, the method is round half up:
        a tie at exactly half a unit rounds away from zero, so 1624.5 cents becomes
        1625 and 32.455 percent becomes 32.46."

        Design: Corner/calculations/sell_through_and_weeks_of_supply_round_half_up_at_two_decimals
        """
        sc = fx.base_scenario(api)

        item = fx.read_item(api, sc.item["id"])

        assert item["units_sold_total"] == 257
        assert item["sample_weeks"] == 4
        assert item["on_hand_units"] == 343
        assert item["sell_through_pct"] == pytest.approx(42.83, abs=1e-9)
        assert item["weeks_of_supply"] == pytest.approx(5.34, abs=1e-9)

    def test_the_posted_history_reads_back_in_week_ending_order(self, api, analyst):
        """PRD 2.9: "Every collection is also exposed as a flat top-level list with
        the parent identifier available as a filter, so the same rows are reachable
        both ways; the flat list of exit reviews is ordered by `generated_at`
        ascending, an item's sales weeks by `week_ending_date` ascending with
        `created_at` ascending as the tie-break, and a plan's ladder by `step_index`
        ascending."

        Design: Corner/calculations/sell_through_and_weeks_of_supply_round_half_up_at_two_decimals
        """
        sc = fx.base_scenario(api)

        weeks, meta = validate_paginated(
            api.list_item_sales_weeks(sc.item["id"], analyst)
        )

        assert meta["total_count"] == 4
        assert [week["week_ending_date"] for week in weeks] == [
            "2026-09-05",
            "2026-09-12",
            "2026-09-19",
            "2026-09-26",
        ]
        assert [week["units_sold"] for week in weeks] == [60, 55, 68, 74]


class TestLadderPricesRoundTheDiscountFirst:
    """A rung's discount is rounded before it is subtracted, never after."""

    def test_a_four_rung_ladder_prices_every_rung_off_the_original_ticket(
        self, api, analyst
    ):
        """PRD 2.8: "Two rounding orders are pinned, because the alternatives are
        observably different and only one is correct. When a ladder rung's price is
        computed, the discount amount is rounded to a whole cent first and only then
        subtracted from the original ticket; the resulting price is never rounded
        again." PRD 3.5 says which ticket the depth is measured off: "Depth is always
        measured off the original ticket, never off the live one, so the rung's
        `price_cents` is the item's `original_retail_cents` less the discount, where
        the discount is `original_retail_cents` multiplied by `depth_pct` divided by
        100 and rounded half up to a whole cent before the subtraction."

        Design: Corner/calculations/ladder_prices_round_the_discount_before_subtracting
        """
        sc = fx.planned_scenario(api)
        assert sc.item["original_retail_cents"] == 4999

        rungs = [
            (1, "2026-11-16", 22.57, 3871),
            (2, "2026-11-30", 32.50, 3374),
            (3, "2026-12-14", 35.00, 3249),
            (4, "2026-12-28", 50.00, 2499),
        ]
        for step_index, effective_date, depth_pct, expected_price in rungs:
            step = validate_success(
                api.create_markdown_step(
                    sc.plan["id"],
                    markdown_step_payload(step_index, effective_date, depth_pct),
                    analyst,
                ),
                201,
            )
            assert step["price_cents"] == expected_price

    def test_appending_rungs_retiles_the_occupancy_calendar(self, api, analyst):
        """PRD 3.5: "Each new rung also fixes the ladder's occupancy calendar: a
        rung's `window_end_date_exclusive` is set to the plan's `exit_date_target`
        when it is the last rung, and appending a further rung rewrites the previous
        rung's `window_end_date_exclusive` to the new rung's `effective_date`, so the
        rungs tile the plan's calendar as half-open windows." And: "Appending a rung
        increments the plan's `ladder_step_count`, recomputes the plan's
        `projected_exit_units`, and bumps the plan's `version`. Rungs open in
        `PLANNED`."

        Design: Corner/calculations/ladder_prices_round_the_discount_before_subtracting
        """
        sc = fx.planned_scenario(api)
        for step_index, effective_date, depth_pct in (
            (1, "2026-11-16", 22.57),
            (2, "2026-11-30", 32.50),
            (3, "2026-12-14", 35.00),
            (4, "2026-12-28", 50.00),
        ):
            fx.add_rung(api, sc.plan["id"], step_index, effective_date, depth_pct)

        ladder, meta = validate_paginated(api.list_plan_steps(sc.plan["id"], analyst))

        assert meta["total_count"] == 4
        assert [rung["window_end_date_exclusive"] for rung in ladder] == [
            "2026-11-30",
            "2026-12-14",
            "2026-12-28",
            "2027-01-15",
        ]
        assert [rung["status"] for rung in ladder] == ["PLANNED"] * 4
        assert fx.read_plan(api, sc.plan["id"])["ladder_step_count"] == 4


def _plan_with_one_applied_and_one_scheduled(api):
    """A permanent plan holding two rungs, the first applied on its effective
    date and the second still scheduled with unposted signage.
    """
    sc = fx.planned_scenario(api)
    sc["step1"] = fx.add_rung(api, sc.plan["id"], 1, "2026-10-19", 22.57)
    sc["step2"] = fx.add_rung(api, sc.plan["id"], 2, "2026-11-02", 32.50)
    fx.submit_plan(api, sc.plan["id"])
    sc["plan"] = fx.approve_plan(api, sc.plan["id"])
    sc["execution"] = fx.schedule_execution(
        api, sc.plan["id"], sc.step1["id"], sc.west_zone["id"], "ZONE", "2026-10-19", 200
    )
    sc["execution_two"] = fx.schedule_execution(
        api, sc.plan["id"], sc.step2["id"], sc.west_zone["id"], "ZONE", "2026-11-02", 100
    )
    fx.post_signage(api, sc.execution["id"], sc.store_0101["id"])
    fx.verify_signage(api, sc.execution["id"])
    fx.set_clock(api, "2026-10-19T00:00:00Z")
    sc["execution"] = fx.apply_execution(api, sc.execution["id"])
    return sc


class TestGrossMarkdownAdmitsAppliedRowsOnly:
    """Two sums over the same executions admit different statuses."""

    def test_the_gross_counts_the_applied_line_while_projected_units_count_both(
        self, api, analyst
    ):
        """PRD 3.5: "A plan's money fields follow from its executions and claims:
        `gross_markdown_cents` is the sum of `line_markdown_cents` over its `APPLIED`
        executions accumulated in `created_at` ascending order, `vendor_funded_cents`
        is the sum of `recognized_cents` over its `RECOGNIZED` claims,
        `net_markdown_cents` is the gross less the vendor-funded amount, and
        `projected_exit_units` is the sum of `units_in_scope` over its executions that
        are `SCHEDULED` or `APPLIED`." PRD 3.6 fixes the applied line itself: "Under a
        `PERMANENT` plan whose rung depth is below 50.00 percent, an item at
        `FULL_PRICE` moves `FULL_PRICE → PERM_MARKED` and an item already at
        `PROMO_ACTIVE` moves `PROMO_ACTIVE → PERM_MARKED`; in both cases
        `current_retail_cents` becomes the rung price, the full `line_markdown_cents`
        is added to the item's `permanent_markdown_reserve_cents` immediately at
        execution time on every unit in scope, and the item's `lifecycle_stage` is
        reclassified."

        Design: Corner/calculations/gross_markdown_counts_applied_executions_only
        """
        sc = _plan_with_one_applied_and_one_scheduled(api)

        plan = fx.read_plan(api, sc.plan["id"])
        assert plan["gross_markdown_cents"] == 225600
        assert plan["net_markdown_cents"] == 225600
        assert plan["projected_exit_units"] == 300

        assert (
            fx.read_item(api, sc.item["id"])["permanent_markdown_reserve_cents"]
            == 225600
        )
        assert fx.read_execution(api, sc.execution_two["id"])["line_markdown_cents"] == 0

    def test_a_rolled_back_execution_is_excluded_exactly_like_a_scheduled_one(
        self, api, analyst
    ):
        """PRD 3.6: "The plan's `gross_markdown_cents` is reduced by the rolled-back
        `line_markdown_cents` and `net_markdown_cents` is recomputed." And: "On the
        accounting side, a `PERMANENT` plan's reversal subtracts the same
        `line_markdown_cents` from the item's `permanent_markdown_reserve_cents`,
        while a `PROMOTIONAL` plan's reversal subtracts the accrued contra-revenue
        from `promo_discount_cents`; either way the item's total markdown exposure
        returns to its pre-apply value."

        Design: Corner/calculations/gross_markdown_counts_applied_executions_only
        """
        sc = _plan_with_one_applied_and_one_scheduled(api)

        rolled_back = validate_success(
            api.roll_back_zone_execution(
                sc.execution["id"], roll_back_payload(), analyst
            )
        )
        assert rolled_back["status"] == "ROLLED_BACK"

        plan = fx.read_plan(api, sc.plan["id"])
        assert plan["gross_markdown_cents"] == 0
        assert plan["net_markdown_cents"] == 0
        assert plan["projected_exit_units"] == 100

        item = fx.read_item(api, sc.item["id"])
        assert item["permanent_markdown_reserve_cents"] == 0
        assert item["current_retail_cents"] == 4999

        executions, meta = validate_paginated(
            api.list_zone_executions(analyst, {"markdown_plan_id": sc.plan["id"]})
        )
        assert meta["total_count"] == 2
        assert sorted(row["status"] for row in executions) == [
            "ROLLED_BACK",
            "SCHEDULED",
        ]


class TestSlowSellerThresholdIsStrict:
    """Exactly 45.00 percent sell-through is not below the threshold."""

    @staticmethod
    def _twin_items(api):
        season = fx.create_season(api)
        item_c = fx.create_item(
            api, season["id"], sku="C-3003", units_received_total=400
        )
        item_d = fx.create_item(
            api, season["id"], sku="D-4004", units_received_total=400
        )
        fx.transition_season(api, season["id"], "ACTIVE")
        fx.post_history(
            api,
            item_c["id"],
            [
                ("2026-09-05", 45, 4999),
                ("2026-09-12", 45, 4999),
                ("2026-09-19", 45, 4499),
                ("2026-09-26", 45, 4499),
            ],
        )
        fx.post_history(
            api,
            item_d["id"],
            [
                ("2026-09-05", 45, 4999),
                ("2026-09-12", 45, 4999),
                ("2026-09-19", 45, 4499),
                ("2026-09-26", 44, 4499),
            ],
        )
        fx.set_clock(api, "2026-10-10T00:00:00Z")
        return season, item_c, item_d

    def test_an_item_at_exactly_the_threshold_stays_core(self, api, analyst):
        """PRD 3.3: "An item counts as a slow seller when its `sell_through_pct` is
        strictly below 45.00 percent and it has been on hand for at least six weeks."
        Rules 5 and 6 then decide: "Otherwise it is `AGING` when weeks on hand is ten
        or more, or when the item qualifies as a slow seller." Failing that,
        "Otherwise it is `CORE`."

        Design: Corner/calculations/slow_seller_threshold_at_forty_five_percent_keeps_the_item_core
        """
        _season, item_c, _item_d = self._twin_items(api)

        item = fx.read_item(api, item_c["id"])

        assert item["units_sold_total"] == 180
        assert item["sell_through_pct"] == pytest.approx(45.00, abs=1e-9)
        assert item["lifecycle_stage"] == "CORE"

    def test_one_unit_less_makes_the_twin_a_slow_seller(self, api, analyst):
        """PRD 3.3: "An item counts as a slow seller when its `sell_through_pct` is
        strictly below 45.00 percent and it has been on hand for at least six weeks."
        And the aging rule: "Otherwise it is `AGING` when weeks on hand is ten or
        more, or when the item qualifies as a slow seller."

        Design: Corner/calculations/slow_seller_threshold_at_forty_five_percent_keeps_the_item_core
        """
        season, _item_c, item_d = self._twin_items(api)

        item = fx.read_item(api, item_d["id"])
        assert item["units_sold_total"] == 179
        assert item["sell_through_pct"] == pytest.approx(44.75, abs=1e-9)
        assert item["lifecycle_stage"] == "AGING"

        core, meta = validate_paginated(
            api.list_items(
                analyst, {"season_id": season["id"], "lifecycle_stage": "CORE"}
            )
        )
        assert meta["total_count"] == 1
        assert core[0]["sku"] == "C-3003"


class TestAutoResolvesToTheAvailablePath:
    """`AUTO` is not a synonym for the own-history path."""

    def test_a_flat_ticket_history_sends_auto_down_the_pooled_path(self, api, analyst):
        """PRD 3.4: "Ordering the item's sales weeks by `week_ending_date` ascending
        with `created_at` ascending as the tie-break, the history qualifies when there
        are at least four weeks, when at least two distinct `ticket_price_cents`
        values appear across them, when the earliest week's ticket price differs from
        the latest week's ticket price, and when both the earliest and the latest week
        sold at least one unit." And: "When `method` is `AUTO`, the system uses the
        own-history path if the qualifying conditions above hold and otherwise falls
        through to the cluster-pooled path." The pooled figure is "the units-weighted
        mean of those peers' coefficients: each peer's coefficient multiplied by that
        peer's `units_sold_total`, summed across the peers, then divided by the sum of
        those same `units_sold_total` weights." And: "On this path `resolved_method` is
        `CLUSTER_POOLED`, `sample_weeks_used` is 0, `peer_items_used` is the number of
        peers that entered the average, and `confidence` is always `LOW`."

        Design: Corner/calculations/auto_method_falls_back_to_cluster_pooled_when_price_never_moved
        """
        sc = fx.certified_scenario(api)
        item_f = fx.create_item(
            api,
            sc.season["id"],
            sku="F-6006",
            original_retail_cents=3999,
            unit_cost_cents=1500,
            units_received_total=200,
        )
        fx.post_history(
            api,
            item_f["id"],
            [
                ("2026-09-05", 20, 3999),
                ("2026-09-12", 20, 3999),
                ("2026-09-19", 20, 3999),
                ("2026-09-26", 20, 3999),
            ],
        )

        pooled = validate_success(
            api.create_elasticity_estimate(
                elasticity_estimate_payload(item_f["id"], method="AUTO"), analyst
            ),
            201,
        )

        assert pooled["resolved_method"] == "CLUSTER_POOLED"
        assert pooled["elasticity_coefficient"] == pytest.approx(-1.9901, abs=1e-9)
        assert pooled["sample_weeks_used"] == 0
        assert pooled["peer_items_used"] == 1
        assert pooled["confidence"] == "LOW"

    def test_the_same_auto_request_on_a_moving_ticket_stays_on_own_history(
        self, api, analyst
    ):
        """PRD 3.4: "On this path `resolved_method` is `OWN_HISTORY`,
        `sample_weeks_used` is the number of weeks in the history and
        `peer_items_used` is 0." And: "Confidence is `HIGH` only when the resolved
        path was `OWN_HISTORY` and at least four of the item's own weeks entered the
        calculation; in every other case, including every pooled estimate, it is
        `LOW`."

        Design: Corner/calculations/auto_method_falls_back_to_cluster_pooled_when_price_never_moved
        """
        sc = fx.certified_scenario(api)

        assert sc.estimate["resolved_method"] == "OWN_HISTORY"
        assert sc.estimate["sample_weeks_used"] == 4
        assert sc.estimate["peer_items_used"] == 0
        assert sc.estimate["confidence"] == "HIGH"
        assert sc.estimate["elasticity_coefficient"] == pytest.approx(
            -1.9901, abs=1e-9
        )


class TestTwoEstimationFailuresAreDistinct:
    """One thin history yields two different refusals."""

    @staticmethod
    def _thin_footwear_item(api):
        season = fx.create_season(api, code="SS27-FOOTWEAR", category="FOOTWEAR")
        item_g = fx.create_item(
            api,
            season["id"],
            sku="G-7007",
            category="FOOTWEAR",
            cluster_code="CL-W9",
            units_received_total=300,
        )
        fx.transition_season(api, season["id"], "ACTIVE")
        fx.post_history(
            api,
            item_g["id"],
            [
                ("2026-09-05", 40, 4999),
                ("2026-09-12", 40, 4999),
                ("2026-09-19", 45, 4499),
            ],
        )
        return season, item_g

    def test_an_explicit_own_history_request_reports_the_thin_history(
        self, api, analyst
    ):
        """PRD 3.4: "When `method` is `OWN_HISTORY` explicitly and those conditions do
        not hold, the request is refused with `ERR_INSUFFICIENT_PRICE_HISTORY` rather
        than silently pooling."

        Design: Corner/calculations/min_sample_weeks_and_an_empty_pool_are_rejected_distinctly
        """
        _season, item_g = self._thin_footwear_item(api)

        response = api.create_elasticity_estimate(
            elasticity_estimate_payload(item_g["id"], method="OWN_HISTORY"), analyst
        )
        validate_error(response, "ERR_INSUFFICIENT_PRICE_HISTORY", 422)

        assert fx.read_item(api, item_g["id"])["sample_weeks"] == 3

    def test_the_same_item_under_auto_reports_the_empty_peer_pool(self, api, analyst):
        """PRD 3.4: "When the cluster-pooled path runs — whether requested outright or
        reached through `AUTO` — and no qualifying peer exists, the request is refused
        with `ERR_EMPTY_PEER_POOL`." The peer set is narrow: "Its peer set is every
        other item in the same season with the same `category` and the same
        `cluster_code`, whose `units_sold_total` is at least 1 and which holds a
        `CERTIFIED` elasticity estimate — and because certification supersedes an
        item's other estimates, an item can hold at most one."

        Design: Corner/calculations/min_sample_weeks_and_an_empty_pool_are_rejected_distinctly
        """
        _season, item_g = self._thin_footwear_item(api)

        response = api.create_elasticity_estimate(
            elasticity_estimate_payload(item_g["id"], method="AUTO"), analyst
        )
        validate_error(response, "ERR_EMPTY_PEER_POOL", 422)

        _rows, meta = validate_paginated(
            api.list_elasticity_estimates(analyst, {"item_id": item_g["id"]})
        )
        assert meta["total_count"] == 0


class TestUrgencyTierBoundary:
    """One day of clock movement crosses the twelve-week urgency tier."""

    def test_thirteen_weeks_out_the_urgency_addend_is_nothing_at_all(
        self, api, analyst
    ):
        """PRD 3.5: "The urgency addend is selected by tier from the whole weeks
        remaining to the season's `exit_target_date`: nothing at all when more than
        twelve weeks remain, 5.00 percent when between eight and twelve weeks remain
        inclusive, 10.00 percent when between four and seven weeks remain inclusive,
        and 20.00 percent when fewer than four weeks remain." The three parts combine
        once: "The three percentage addends are summed first and the sum is multiplied
        by the elasticity multiplier exactly once; that product is then clamped to no
        less than 10.00 percent and no more than 70.00 percent and rounded half up to
        two decimals to give `recommended_depth_pct`."

        Design: Corner/calculations/urgency_tier_boundary_at_twelve_weeks_lifts_recommended_depth
        """
        sc = fx.certified_scenario(api)
        fx.set_clock(api, "2026-10-16T00:00:00Z")

        item = fx.read_item(api, sc.item["id"])
        plan_one = validate_success(
            api.create_markdown_plan(
                markdown_plan_payload(
                    sc.season["id"], sc.item["id"], sc.estimate["id"], item["version"]
                ),
                analyst,
            ),
            201,
        )

        assert plan_one["recommended_depth_pct"] == pytest.approx(22.57, abs=0.001)
        assert plan_one["ladder_step_count"] == 0
        assert plan_one["gross_markdown_cents"] == 0

    def test_one_day_later_twelve_weeks_remain_and_the_addend_appears(
        self, api, analyst
    ):
        """PRD 3.5: "The urgency addend is selected by tier from the whole weeks
        remaining to the season's `exit_target_date`: nothing at all when more than
        twelve weeks remain, 5.00 percent when between eight and twelve weeks remain
        inclusive, 10.00 percent when between four and seven weeks remain inclusive,
        and 20.00 percent when fewer than four weeks remain." The inventory-pressure
        term is unchanged across the two clocks: "The inventory-pressure addend charges
        1.50 percent for each week of supply above a four-week target: take the item's
        `weeks_of_supply` less 4.00, floor that difference at zero so a well-covered
        item contributes nothing, multiply by 1.50, round half up to two decimals, and
        cap the result at 15.00 percent."

        Design: Corner/calculations/urgency_tier_boundary_at_twelve_weeks_lifts_recommended_depth
        """
        sc = fx.certified_scenario(api)

        fx.set_clock(api, "2026-10-16T00:00:00Z")
        item = fx.read_item(api, sc.item["id"])
        plan_one = validate_success(
            api.create_markdown_plan(
                markdown_plan_payload(
                    sc.season["id"], sc.item["id"], sc.estimate["id"], item["version"]
                ),
                analyst,
            ),
            201,
        )

        fx.set_clock(api, "2026-10-17T00:00:00Z")
        item = fx.read_item(api, sc.item["id"])
        plan_two = validate_success(
            api.create_markdown_plan(
                markdown_plan_payload(
                    sc.season["id"], sc.item["id"], sc.estimate["id"], item["version"]
                ),
                analyst,
            ),
            201,
        )

        assert plan_one["recommended_depth_pct"] == pytest.approx(22.57, abs=0.001)
        assert plan_two["recommended_depth_pct"] == pytest.approx(29.20, abs=0.001)
        assert plan_two["ladder_step_count"] == 0
        assert plan_two["gross_markdown_cents"] == 0

    def test_the_second_create_sweeps_the_first_plan_aside(self, api, analyst):
        """PRD 3.5: "Any earlier plan for the same season and item whose status is
        `DRAFT`, `SUBMITTED`, `REVISION_REQUESTED` or `APPROVED` moves to `SUPERSEDED`;
        its `superseded_by_plan_id` is pointed at the new plan; every one of its ladder
        rungs still in `PLANNED` or `SCHEDULED` moves to `SUPERSEDED`, which recomputes
        its `ladder_step_count`; and every clearance reservation it held in `RESERVED`
        or `COMMITTED` moves to `RELEASED`."

        Design: Corner/calculations/urgency_tier_boundary_at_twelve_weeks_lifts_recommended_depth
        """
        sc = fx.certified_scenario(api)

        fx.set_clock(api, "2026-10-16T00:00:00Z")
        item = fx.read_item(api, sc.item["id"])
        plan_one = validate_success(
            api.create_markdown_plan(
                markdown_plan_payload(
                    sc.season["id"], sc.item["id"], sc.estimate["id"], item["version"]
                ),
                analyst,
            ),
            201,
        )

        fx.set_clock(api, "2026-10-17T00:00:00Z")
        item = fx.read_item(api, sc.item["id"])
        plan_two = validate_success(
            api.create_markdown_plan(
                markdown_plan_payload(
                    sc.season["id"], sc.item["id"], sc.estimate["id"], item["version"]
                ),
                analyst,
            ),
            201,
        )

        stale = fx.read_plan(api, plan_one["id"])
        assert stale["status"] == "SUPERSEDED"
        assert stale["superseded_by_plan_id"] == plan_two["id"]
        assert fx.read_plan(api, plan_two["id"])["status"] == "DRAFT"


class TestDispositionRecoveryPerChannel:
    """Identical unit counts recover different money in each channel."""

    def test_each_channel_applies_its_own_recovery_formula(self, api, analyst):
        """PRD 3.9: "For `SALVAGE`, recovery is simply the unit count multiplied by
        `unit_recovery_cents`." And: "For `JOBBER`, the same product is reduced by an
        eight percent freight deduction — that is, multiplied by 92 and divided by 100
        — and rounded half up to a whole cent." And: "For `DONATION`, the tax credit is
        the unit count multiplied by the lesser of `fmv_cents` and the item's
        `unit_cost_cents`, because landed cost caps the donation basis, then multiplied
        by 21 and divided by 100 for the credit rate, and rounded half up to a whole
        cent."

        Design: Corner/calculations/disposition_recovery_differs_by_channel_on_identical_units
        """
        sc = fx.applied_execution_scenario(api)

        salvage = fx.create_disposition(
            api, salvage_order_payload(sc.season["id"], sc.item["id"], 50, 300)
        )
        jobber = fx.create_disposition(
            api, jobber_order_payload(sc.season["id"], sc.item["id"], 100, 500)
        )
        donation = fx.create_disposition(
            api, donation_order_payload(sc.season["id"], sc.item["id"], 50, 1000)
        )

        assert salvage["projected_recovery_cents"] == 15000
        assert jobber["projected_recovery_cents"] == 46000
        assert donation["projected_recovery_cents"] == 10500

        for order in (salvage, jobber, donation):
            assert order["status"] == "DRAFT"
            assert order["settled_units"] == 0
            assert order["settled_recovery_cents"] == 0

    def test_drafting_commits_units_without_moving_the_on_hand_count(
        self, api, analyst
    ):
        """PRD 3.9: "A drafted order stamps `created_by_user_id` from `X-User-ID`,
        leaves `approved_by_user_id` null, opens in `DRAFT` with `settled_units` and
        `settled_recovery_cents` at 0, computes and stores `projected_recovery_cents`,
        adds its `units` to the item's `units_committed_disposition` — so the item's
        uncommitted pool shrinks immediately, even before anything ships — and
        increments the item's `version`." The on-hand count is derived elsewhere: "The
        item's `on_hand_units` is always its `units_received_total` less
        `units_sold_total` and less `units_disposed_total`, and it is never written
        directly."

        Design: Corner/calculations/disposition_recovery_differs_by_channel_on_identical_units
        """
        sc = fx.applied_execution_scenario(api)

        fx.create_disposition(
            api, salvage_order_payload(sc.season["id"], sc.item["id"], 50, 300)
        )
        fx.create_disposition(
            api, jobber_order_payload(sc.season["id"], sc.item["id"], 100, 500)
        )
        fx.create_disposition(
            api, donation_order_payload(sc.season["id"], sc.item["id"], 50, 1000)
        )

        item = fx.read_item(api, sc.item["id"])
        assert item["units_committed_disposition"] == 200
        assert item["on_hand_units"] == 343
        assert item["units_disposed_total"] == 0
