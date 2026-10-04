"""Lot evaluation: landed cost, deal quality score, and the re-evaluation loop."""
import pytest

from test_helpers import (
    TEST_DEFAULTS,
    TEST_USERS,
    accept_lot,
    create_lot_payload,
    evaluate_lot,
    get_lot,
    get_season,
    make_lot,
    make_lot_line,
    open_season,
    set_clock,
    setup_base,
    validate_success,
)

BUYER = TEST_USERS["buyer_headers"]
PLANNER = TEST_USERS["planning_lead_headers"]


class TestDealQualityScore:
    def test_deal_quality_score_weighted_blend(self, api):
        """PRD §3.2: "The raw score is 100 times the blend of six-tenths margin
        fraction and four-tenths sell-through, minus a discretion penalty of 15
        points for a `CONFIDENTIAL` vendor or 25 points for a `QUIET` vendor (none
        for `STANDARD`), plus a lot-type bonus of 10 for `CLOSEOUT`, 5 for
        `CANCELLATION`, or 0 for `PACKAWAY`."

        Design: Difficulty/combinatorial_formula/deal_quality_score_three_input_clamped_weighted_blend
        """
        base = setup_base()
        lot = make_lot(
            base["vendor"]["id"], base["season"]["id"],
            asking_price_cents=50_000, unit_count=10,
            expected_sell_through_pct=0.8, estimated_unit_retail_cents=20_000,
        )
        make_lot_line(lot["id"], quantity=10, unit_cost_cents=5_000,
                      compare_at_claim_cents=40_000, target_retail_cents=20_000)
        evaluated = evaluate_lot(lot["id"], negotiated_price_cents=48_000)
        assert evaluated["landed_cost_cents"] == 198_000
        assert evaluated["deal_quality_score"] == pytest.approx(42.6, abs=0.005)
        assert evaluated["status"] == "EVALUATED"
        assert evaluated["version"] == 2

    def test_landed_cost_includes_flat_freight_surcharge(self, api):
        """PRD §3.2: "First, **landed cost**: the negotiated price when supplied,
        otherwise the asking price, plus a flat freight surcharge of 150,000 cents
        per lot — recorded on the lot as `landed_cost_cents`."

        Design: Difficulty/combinatorial_formula/deal_quality_score_three_input_clamped_weighted_blend
        """
        base = setup_base()
        lot = make_lot(base["vendor"]["id"], base["season"]["id"], asking_price_cents=500_000)
        evaluated = evaluate_lot(lot["id"])
        assert evaluated["landed_cost_cents"] == 500_000 + 150_000
        re_evaluated = evaluate_lot(lot["id"], negotiated_price_cents=480_000)
        assert re_evaluated["landed_cost_cents"] == 480_000 + 150_000


class TestReevaluationLoop:
    def test_reevaluate_cycle_then_accept_commits_final_terms(self, api):
        """PRD §3.2: "Evaluation is the `Buyer`'s exclusive call and turns
        `OFFERED → EVALUATED`; it may be repeated while the lot is `EVALUATED`,
        forming a re-evaluation loop that revises score and landed cost as
        negotiations move."

        Design: Difficulty/non_linear_state_machine/lot_evaluate_reevaluate_cycle_before_terminal_decision
        """
        base = setup_base()
        open_season(base["season"])
        lot = make_lot(
            base["vendor"]["id"], base["season"]["id"],
            asking_price_cents=6_000_000, unit_count=40,
            expected_sell_through_pct=0.8, estimated_unit_retail_cents=20_000,
        )
        make_lot_line(lot["id"], quantity=40, unit_cost_cents=150_000,
                      compare_at_claim_cents=40_000, target_retail_cents=20_000)
        eval1 = evaluate_lot(lot["id"], negotiated_price_cents=6_000_000)
        eval2 = evaluate_lot(lot["id"], negotiated_price_cents=5_900_000)
        assert eval2["version"] == eval1["version"] + 1
        accepted = accept_lot(lot["id"], base["season"]["id"])
        assert accepted["status"] == "ACCEPTED"
        season = get_season(base["season"]["id"])
        assert season["committed_forward_cents"] == 6_050_000

    def test_reevaluation_revises_score_and_landed_cost(self, api):
        """PRD §3.2: "forming a re-evaluation loop that revises score and landed
        cost as negotiations move." PRD §3.2: "Each evaluation or re-evaluation
        bumps the lot's `version`."

        Design: Difficulty/non_linear_state_machine/lot_evaluate_reevaluate_cycle_before_terminal_decision
        """
        base = setup_base()
        open_season(base["season"])
        lot = make_lot(
            base["vendor"]["id"], base["season"]["id"],
            asking_price_cents=6_000_000, unit_count=40,
            expected_sell_through_pct=0.5, estimated_unit_retail_cents=20_000,
        )
        eval1 = evaluate_lot(lot["id"], negotiated_price_cents=6_000_000)
        eval2 = evaluate_lot(lot["id"], negotiated_price_cents=500_000)
        assert eval2["landed_cost_cents"] == 650_000
        assert eval2["deal_quality_score"] != eval1["deal_quality_score"]
        assert eval2["status"] == "EVALUATED"
