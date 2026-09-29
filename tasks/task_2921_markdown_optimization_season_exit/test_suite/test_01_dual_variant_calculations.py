"""Two calculations that return genuinely different numbers from the same
stored rows: the two elasticity paths, and the two exit-review variants.
"""

import pytest

from test_helpers import fixtures as fx
from test_helpers import validate_paginated, validate_success
from test_helpers.factories import elasticity_estimate_payload


class TestElasticityPathsDiverge:
    """The own-history and cluster-pooled paths read the same stored data."""

    def test_own_history_path_reports_the_two_point_log_log_slope(self, api, analyst):
        """PRD 3.4: "Where the history qualifies, the coefficient is the two-point
        log-log slope: the natural logarithm of the latest week's `units_sold`
        divided by the earliest week's `units_sold`, divided in turn by the
        natural logarithm of the latest week's `ticket_price_cents` divided by
        the earliest week's `ticket_price_cents`." And: "On this path
        `resolved_method` is `OWN_HISTORY`, `sample_weeks_used` is the number of
        weeks in the history and `peer_items_used` is 0."

        Design: Difficulty/dual_variant_calc/elasticity_own_history_versus_cluster_pooled_diverge
        """
        sc = fx.dual_estimate_scenario(api)

        response = api.create_elasticity_estimate(
            elasticity_estimate_payload(sc.item["id"], method="AUTO"), analyst
        )
        own = validate_success(response, 201)

        assert own["resolved_method"] == "OWN_HISTORY"
        assert own["elasticity_coefficient"] == pytest.approx(-1.9901, abs=1e-9)
        assert own["sample_weeks_used"] == 4
        assert own["peer_items_used"] == 0
        assert own["confidence"] == "HIGH"

    def test_cluster_pooled_path_reports_the_units_weighted_peer_mean(
        self, api, analyst
    ):
        """PRD 3.4: "The pooled coefficient is the units-weighted mean of those
        peers' coefficients: each peer's coefficient multiplied by that peer's
        `units_sold_total`, summed across the peers, then divided by the sum of
        those same `units_sold_total` weights." And: "On this path
        `resolved_method` is `CLUSTER_POOLED`, `sample_weeks_used` is 0,
        `peer_items_used` is the number of peers that entered the average, and
        `confidence` is always `LOW`."

        Design: Difficulty/dual_variant_calc/elasticity_own_history_versus_cluster_pooled_diverge
        """
        sc = fx.dual_estimate_scenario(api)

        response = api.create_elasticity_estimate(
            elasticity_estimate_payload(sc.item["id"], method="CLUSTER_POOLED"), analyst
        )
        pooled = validate_success(response, 201)

        assert pooled["resolved_method"] == "CLUSTER_POOLED"
        assert pooled["elasticity_coefficient"] == pytest.approx(-3.0217, abs=1e-9)
        assert pooled["sample_weeks_used"] == 0
        assert pooled["peer_items_used"] == 1
        assert pooled["confidence"] == "LOW"
        assert pooled["status"] == "DRAFT"

    def test_the_two_methods_report_different_coefficients_for_one_item(
        self, api, analyst
    ):
        """PRD 3.4: "An item that both qualifies for own history and has pooled
        peers will therefore report a different coefficient depending on which
        method was asked for, and that difference propagates straight into the
        recommended first-step depth of any plan built on the estimate."

        Design: Difficulty/dual_variant_calc/elasticity_own_history_versus_cluster_pooled_diverge
        """
        sc = fx.dual_estimate_scenario(api)

        own = validate_success(
            api.create_elasticity_estimate(
                elasticity_estimate_payload(sc.item["id"], method="OWN_HISTORY"), analyst
            ),
            201,
        )
        pooled = validate_success(
            api.create_elasticity_estimate(
                elasticity_estimate_payload(sc.item["id"], method="CLUSTER_POOLED"),
                analyst,
            ),
            201,
        )

        difference = pooled["elasticity_coefficient"] - own["elasticity_coefficient"]
        assert difference == pytest.approx(-1.0316, abs=1e-9)

        weeks, _meta = validate_paginated(
            api.list_item_sales_weeks(sc.item["id"], analyst, {"limit": 100})
        )
        assert [w["units_sold"] for w in weeks] == [60, 55, 68, 74]
        assert [w["ticket_price_cents"] for w in weeks] == [4999, 4999, 4499, 4499]


class TestExitScorecardVariantsDiverge:
    """The preliminary variant scores the season on projections, the final
    variant on realized facts only."""

    def test_preliminary_variant_admits_scheduled_submitted_and_unsettled_rows(
        self, api, controller
    ):
        """PRD 3.9: "In a `PRELIMINARY` review, `markdown_reserve_cents` sums,
        over the season's `PERMANENT` plans and over their executions that are
        either `SCHEDULED` or `APPLIED`, the frozen `line_markdown_cents` for
        each applied execution and, for each scheduled one, the difference
        between the item's `current_retail_cents` and the rung's `price_cents`
        multiplied by that execution's `units_in_scope`". And: "`vendor_funding_cents`
        counts both the `claimed_cents` of claims still `SUBMITTED` and the
        `recognized_cents` of claims already `RECOGNIZED`; and
        `disposition_recovery_cents` counts the `projected_recovery_cents` of
        orders in `DRAFT` and `APPROVED` plus the `settled_recovery_cents` of
        orders already `SETTLED`."

        Design: Difficulty/dual_variant_calc/exit_scorecard_preliminary_versus_final_diverge
        """
        sc = fx.scorecard_scenario(api)

        prelim = validate_success(
            api.create_exit_review(
                sc.season["id"], {"review_type": "PRELIMINARY"}, controller
            ),
            201,
        )

        assert prelim["revenue_cents"] == 1910758
        assert prelim["cogs_cents"] == 791500
        assert prelim["markdown_reserve_cents"] == 287800
        assert prelim["promo_discount_cents"] == 0
        assert prelim["vendor_funding_cents"] == 60000
        assert prelim["disposition_recovery_cents"] == 15000
        assert prelim["gross_margin_cents"] == 906458

    def test_final_variant_admits_only_realized_rows(self, api, controller):
        """PRD 3.9: "In a `FINAL` review, `markdown_reserve_cents` is the sum of
        `permanent_markdown_reserve_cents` across the season's items —
        equivalently the sum of `line_markdown_cents` over the applied executions
        of permanent plans; `promo_discount_cents` is the sum of the items' own
        `promo_discount_cents`, which counts only units actually sold on or after
        each execution's `effective_date`; `vendor_funding_cents` counts
        `recognized_cents` of `RECOGNIZED` claims only; and
        `disposition_recovery_cents` counts `settled_recovery_cents` of `SETTLED`
        orders only."

        Design: Difficulty/dual_variant_calc/exit_scorecard_preliminary_versus_final_diverge
        """
        sc = fx.scorecard_scenario(api)

        final = validate_success(
            api.create_exit_review(sc.season["id"], {"review_type": "FINAL"}, controller),
            201,
        )

        assert final["markdown_reserve_cents"] == 225600
        assert final["vendor_funding_cents"] == 0
        assert final["disposition_recovery_cents"] == 0
        assert final["gross_margin_cents"] == 893658

    def test_the_two_variants_differ_only_in_the_four_middle_terms(
        self, api, controller
    ):
        """PRD 3.9: "Both variants read identical stored rows, and they return
        different `gross_margin_cents` whenever any execution is still
        `SCHEDULED`, any claim still `SUBMITTED`, or any disposition order not
        yet `SETTLED`." The shared population is fixed: "Both variants aggregate
        the same population — every item of the season together with that item's
        posted sales weeks — and stamp the same fields."

        Design: Difficulty/dual_variant_calc/exit_scorecard_preliminary_versus_final_diverge
        """
        sc = fx.scorecard_scenario(api)

        prelim = validate_success(
            api.create_exit_review(
                sc.season["id"], {"review_type": "PRELIMINARY"}, controller
            ),
            201,
        )
        final = validate_success(
            api.create_exit_review(sc.season["id"], {"review_type": "FINAL"}, controller),
            201,
        )

        assert final["gross_margin_cents"] - prelim["gross_margin_cents"] == -12800

        for review in (prelim, final):
            assert review["units_received_total"] == 1000
            assert review["units_sold_total"] == 442
            assert review["sell_through_pct"] == pytest.approx(44.20, abs=0.01)
            assert review["sell_through_variance_pct"] == pytest.approx(-37.80, abs=0.01)
            assert review["exit_units_variance"] == -558
