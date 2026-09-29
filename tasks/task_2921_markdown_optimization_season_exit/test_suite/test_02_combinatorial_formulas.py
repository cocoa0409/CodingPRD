"""Formulas whose inputs interact, where a single misplaced rounding or a
dropped term produces a different, observably wrong number.
"""

import pytest

from test_helpers import fixtures as fx
from test_helpers import validate_success
from test_helpers.factories import markdown_plan_payload
from test_helpers.test_users import CONTROLLER_ONE_ID


class TestRecommendedDepthInteraction:
    """Base, urgency, inventory pressure and elasticity all feed one number."""

    def test_recommended_depth_multiplies_the_summed_addends_exactly_once(
        self, api, analyst
    ):
        """PRD 3.5: "The three percentage addends are summed first and the sum is
        multiplied by the elasticity multiplier exactly once; that product is then
        clamped to no less than 10.00 percent and no more than 70.00 percent and
        rounded half up to two decimals to give `recommended_depth_pct`." The
        multiplier itself is pinned: "The elasticity multiplier is the absolute
        value of the estimate's `elasticity_coefficient` divided by a pivot of
        1.50, clamped into the range 0.60 through 1.40 and rounded half up to
        four decimals — an item twice as price-responsive as the pivot is pushed
        deeper, an inelastic one is held back".

        Design: Difficulty/combinatorial_formula/recommended_depth_pins_four_input_interaction
        """
        sc = fx.certified_scenario(api)
        item = fx.read_item(api, sc.item["id"])

        response = api.create_markdown_plan(
            markdown_plan_payload(
                sc.season["id"], sc.item["id"], sc.estimate["id"], item["version"]
            ),
            analyst,
        )
        plan = validate_success(response, 201)

        assert plan["recommended_depth_pct"] == pytest.approx(22.57, abs=0.001)
        assert plan["recommended_depth_pct"] != pytest.approx(22.62, abs=0.001)
        assert plan["recommended_depth_pct"] != pytest.approx(19.90, abs=0.001)

    def test_the_item_inputs_that_feed_the_recommendation(self, api):
        """PRD 3.2: "`sell_through_pct` is recomputed as units sold as a percentage
        of units received, rounded half up to two decimals; and `weeks_of_supply`
        is recomputed as the on-hand units divided by the average weekly sales
        rate, rounded half up to two decimals, where that average rate is itself
        `units_sold_total` divided by `sample_weeks` rounded half up to four
        decimals." PRD 3.3 rule 5: "Otherwise it is `AGING` when weeks on hand is
        ten or more, or when the item qualifies as a slow seller."

        Design: Difficulty/combinatorial_formula/recommended_depth_pins_four_input_interaction
        """
        sc = fx.certified_scenario(api)

        item = fx.read_item(api, sc.item["id"])

        assert item["lifecycle_stage"] == "AGING"
        assert item["units_sold_total"] == 257
        assert item["on_hand_units"] == 343
        assert item["sell_through_pct"] == pytest.approx(42.83, abs=0.01)
        assert item["weeks_of_supply"] == pytest.approx(5.34, abs=0.01)

    def test_opening_a_plan_leaves_it_in_draft_and_bumps_the_item_version(
        self, api, analyst
    ):
        """PRD 3.5: "On creation the plan stamps `created_by_user_id` from
        `X-User-ID`, leaves `approved_by_user_id` null, opens in `DRAFT` with
        `revision_round` 0 and `ladder_step_count` 0, computes and stores
        `recommended_depth_pct`, and increments the item's `version`."

        Design: Difficulty/combinatorial_formula/recommended_depth_pins_four_input_interaction
        """
        sc = fx.certified_scenario(api)
        before = fx.read_item(api, sc.item["id"])

        plan = validate_success(
            api.create_markdown_plan(
                markdown_plan_payload(
                    sc.season["id"], sc.item["id"], sc.estimate["id"], before["version"]
                ),
                analyst,
            ),
            201,
        )

        assert plan["status"] == "DRAFT"
        assert plan["ladder_step_count"] == 0
        assert plan["revision_round"] == 0
        assert plan["approved_by_user_id"] is None

        after = fx.read_item(api, sc.item["id"])
        assert after["version"] == before["version"] + 1


class TestMarkdownLiabilityRoundingOrder:
    """The per-unit amount is fixed first, then multiplied by the unit count."""

    def test_the_rung_price_rounds_the_discount_before_subtracting(self, api):
        """PRD 3.5: "Depth is always measured off the original ticket, never off
        the live one, so the rung's `price_cents` is the item's
        `original_retail_cents` less the discount, where the discount is
        `original_retail_cents` multiplied by `depth_pct` divided by 100 and
        rounded half up to a whole cent before the subtraction."

        Design: Difficulty/combinatorial_formula/markdown_liability_line_pins_rounding_order
        """
        sc = fx.approved_plan_scenario(api)

        step = fx.read_step(api, sc.step1["id"])

        assert step["depth_pct"] == pytest.approx(22.57, abs=0.001)
        assert step["price_cents"] == 3871

    def test_the_line_multiplies_an_already_integral_per_unit_amount(self, api):
        """PRD 2.8: "When an execution's markdown liability is computed, the
        per-unit markdown — already an integral number of cents, because the rung
        price was rounded at authoring time — is established first, then
        multiplied by the units in scope, and only then are the resulting line
        amounts summed across executions. Multiplying an unrounded per-unit amount
        by the unit count and rounding the product is explicitly not how this
        system computes a markdown line."

        Design: Difficulty/combinatorial_formula/markdown_liability_line_pins_rounding_order
        """
        sc = fx.applied_execution_scenario(api)

        execution = sc.execution
        assert execution["units_in_scope"] == 200
        assert execution["per_unit_markdown_cents"] == 1128
        assert execution["line_markdown_cents"] == 225600
        assert execution["line_markdown_cents"] != 225655
        assert execution["price_cents_applied"] == 3871

    def test_the_applied_line_lands_on_the_plan_and_the_item(self, api):
        """PRD 3.6: "`per_unit_markdown_cents` is the item's
        `current_retail_cents` less the rung's `price_cents`,
        `line_markdown_cents` is that per-unit amount multiplied by
        `units_in_scope`, and `price_cents_applied` records the rung price written
        onto the item."

        Design: Difficulty/combinatorial_formula/markdown_liability_line_pins_rounding_order
        """
        sc = fx.applied_execution_scenario(api)

        assert sc.execution["status"] == "APPLIED"
        assert fx.read_step(api, sc.step1["id"])["status"] == "EXECUTED"

        assert sc.plan["status"] == "COMPLETED"
        assert sc.plan["gross_markdown_cents"] == 225600
        assert sc.plan["vendor_funded_cents"] == 0
        assert sc.plan["net_markdown_cents"] == 225600

        assert sc.item["current_retail_cents"] == 3871
        assert sc.item["permanent_markdown_reserve_cents"] == 225600
        assert sc.item["promo_discount_cents"] == 0


class TestVendorFundingTakenOnGross:
    """Recognition works off the funding-blind gross, never off net markdown."""

    def test_recognition_takes_the_share_on_the_funding_blind_gross(self, api):
        """PRD 3.8: "First the funding-blind gross is taken: the plan's
        `gross_markdown_cents`, which counts applied executions only. Second, the
        total the vendor could ever owe on this plan is the agreement's
        `agreed_share_pct` divided by 100 and multiplied by that gross, rounded
        half up to a whole cent." And: "Net markdown is never an input."

        Design: Difficulty/combinatorial_formula/vendor_funding_share_taken_on_gross_not_net
        """
        sc = fx.executing_plan_with_agreement(
            api, share_pct=12.35, cap_cents=100000
        )
        claim = fx.create_claim(api, sc.agreement["id"], sc.plan["id"], 30000)

        recognized = fx.recognize_claim(api, claim["id"])

        assert recognized["status"] == "RECOGNIZED"
        assert recognized["recognized_cents"] == 27862
        assert recognized["recognized_cents"] != 30000
        assert recognized["recognized_cents"] != 24799
        assert recognized["recognized_by_user_id"] == CONTROLLER_ONE_ID

    def test_net_markdown_is_restated_only_after_the_amount_is_fixed(self, api):
        """PRD 3.8: "Only then is net markdown restated: the recognised amount is
        added to the plan's `vendor_funded_cents` and the plan's
        `net_markdown_cents` becomes gross less that funded total, while the
        agreement's `recognized_total_cents` grows by the same amount and its
        `remaining_cap_cents` becomes `funding_cap_cents` less
        `recognized_total_cents`."

        Design: Difficulty/combinatorial_formula/vendor_funding_share_taken_on_gross_not_net
        """
        sc = fx.executing_plan_with_agreement(
            api, share_pct=12.35, cap_cents=100000
        )
        claim = fx.create_claim(api, sc.agreement["id"], sc.plan["id"], 30000)
        fx.recognize_claim(api, claim["id"])

        plan = fx.read_plan(api, sc.plan["id"])

        assert plan["gross_markdown_cents"] == 225600
        assert plan["vendor_funded_cents"] == 27862
        assert plan["net_markdown_cents"] == 197738

    def test_the_agreement_headroom_falls_but_the_agreement_stays_agreed(self, api):
        """PRD 3.8: "Hop three fires when that remaining cap has reached exactly 0:
        the agreement moves `AGREED → FUNDED`."

        Design: Difficulty/combinatorial_formula/vendor_funding_share_taken_on_gross_not_net
        """
        sc = fx.executing_plan_with_agreement(
            api, share_pct=12.35, cap_cents=100000
        )
        claim = fx.create_claim(api, sc.agreement["id"], sc.plan["id"], 30000)
        fx.recognize_claim(api, claim["id"])

        agreement = fx.read_agreement(api, sc.agreement["id"])

        assert agreement["recognized_total_cents"] == 27862
        assert agreement["remaining_cap_cents"] == 72138
        assert agreement["status"] == "AGREED"
