"""Contingent bonus pools: pinned evaluation order, floor-remainder retention,
and the strict loss-ratio gate boundary."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    bind_agent_policy_via_referral,
    create_agent_quote,
    create_appointed_agent,
    create_bonus_pool,
    create_consumer,
    create_schedule,
    get_success_data,
    report_claim,
    set_clock,
    setup_product_with_feed,
    submit_agent_quote,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["carrier_admin_headers"]

POOL_PRODUCT = {
    "coverage_rates": {
        "FLAT": {
            "TIER_A": 800000,
            "TIER_B": 500000,
            "TIER_C": 99995,
            "TIER_D": 730000,
            "TIER_E": 1095000,
            "TIER_F": 1825000,
        }
    },
    "min_premium_cents": 0,
}


def _setup_pool_agent(consumer, product_id, tier, claim_cents=None):
    """Appointed agent with a contingent-eligible schedule + one bound policy."""
    agent = create_appointed_agent()
    create_schedule(agent["id"], contingent_bonus_eligible=True)
    policy = bind_agent_policy_via_referral(
        consumer, agent, product_id,
        coverages=[{"coverage_code": "FLAT", "tier": tier}],
    )["policy"]
    if claim_cents is not None:
        report_claim(policy["id"], incurred_amount_cents=claim_cents)
    return agent, policy


def _payouts_by_agent(api, pool_id):
    payouts, _ = validate_paginated(api.list_pool_bonus_payouts(pool_id, ADMIN))
    return {p["agent_id"]: p for p in payouts}


class TestPoolSettlementOrder:
    def test_contingent_bonus_evaluation_order_and_remainder_mode_c(self, api):
        """PRD §3.7: "Settlement evaluates agents in a pinned order that resolves
        what would otherwise look like a circular dependency — eligibility gates
        are computed **first**, excluding any bonus accrual. The loss gate: the
        agent's trailing loss ratio at settle time must be **strictly** less than
        `loss_ratio_threshold`; an agent exactly at the threshold fails."
        PRD §3.7: "Each eligible agent's `payout_cents` is the pool total
        multiplied by the agent's earned premium and divided by the total eligible
        earned premium, **floor-rounded** to integer cents; the
        `undistributed_cents` remainder — pool total minus the sum of payouts —
        is retained by the carrier and never redistributed."

        Design: Difficulty/combinatorial_formula/contingent_bonus_evaluation_order_and_remainder_mode_c
        """
        set_clock("2026-01-01T00:00:00Z")
        ctx = setup_product_with_feed(product_overrides=POOL_PRODUCT)
        consumer = create_consumer()

        e1, _ = _setup_pool_agent(consumer, ctx["product"]["id"], "TIER_D", 100000)
        e2, _ = _setup_pool_agent(consumer, ctx["product"]["id"], "TIER_E", 120000)
        e3, _ = _setup_pool_agent(consumer, ctx["product"]["id"], "TIER_F", 350000)

        set_clock("2026-04-11T00:00:00Z")
        pool = create_bonus_pool(pool_total_cents=999999)
        settled = validate_success(api.settle_bonus_pool(pool["id"], ADMIN))
        assert settled["status"] == "SETTLED"
        assert settled["undistributed_cents"] == 1

        by_agent = _payouts_by_agent(api, pool["id"])
        p1 = by_agent[e1["id"]]
        assert p1["eligible"] is True
        assert p1["earned_premium_cents"] == 200000
        assert p1["payout_cents"] == 399999

        p2 = by_agent[e2["id"]]
        assert p2["eligible"] is True
        assert p2["earned_premium_cents"] == 300000
        assert p2["payout_cents"] == 599999

        p3 = by_agent[e3["id"]]
        assert p3["eligible"] is False
        assert p3["ineligibility_reason"] == "LOSS_RATIO"
        assert p3["payout_cents"] == 0

        total = sum(p["payout_cents"] for p in by_agent.values())
        assert total + settled["undistributed_cents"] == 999999

    def test_contingent_bonus_gates_first_then_prorata_allocation(self, api):
        """PRD §3.7: "An agent enters the eligible pool only by passing both gates
        and having positive trailing twelve-month earned premium."
        PRD §3.7: "Each eligible agent's `payout_cents` is the pool total
        multiplied by the agent's earned premium and divided by the total eligible
        earned premium, **floor-rounded** to integer cents; the
        `undistributed_cents` remainder — pool total minus the sum of payouts —
        is retained by the carrier and never redistributed."

        Design: Difficulty/combinatorial_formula/contingent_bonus_evaluation_order_and_remainder_mode_c
        """
        set_clock("2026-01-01T00:00:00Z")
        ctx = setup_product_with_feed(product_overrides=POOL_PRODUCT)
        consumer = create_consumer()

        e1, _ = _setup_pool_agent(consumer, ctx["product"]["id"], "TIER_D", 100000)
        e2, _ = _setup_pool_agent(consumer, ctx["product"]["id"], "TIER_E", 120000)
        e3, _ = _setup_pool_agent(consumer, ctx["product"]["id"], "TIER_F", 350000)

        set_clock("2026-04-11T00:00:00Z")
        pool = create_bonus_pool(pool_total_cents=999999)
        validate_success(api.settle_bonus_pool(pool["id"], ADMIN))
        by_agent = _payouts_by_agent(api, pool["id"])

        # Ineligible e3 (earned 500000) neither dilutes nor receives:
        # eligible denominator is 200000 + 300000 only.
        assert by_agent[e3["id"]]["payout_cents"] == 0
        assert by_agent[e1["id"]]["payout_cents"] == 399999
        assert by_agent[e2["id"]]["payout_cents"] == 599999


class TestLossRatioGateBoundary:
    def test_loss_ratio_strict_threshold_boundary_on_bonus_gate(self, api):
        """PRD §3.7: "The loss gate: the agent's trailing loss ratio at settle
        time must be **strictly** less than `loss_ratio_threshold`; an agent
        exactly at the threshold fails."
        PRD §3.7: "when the prior twelve months' earned is zero, growth is
        **defined** as 1.0, so first-year agents pass."

        Design: Difficulty/boundary_precision_check/loss_ratio_strict_threshold_boundary_on_bonus_gate
        """
        set_clock("2026-01-01T00:00:00Z")
        ctx = setup_product_with_feed(product_overrides=POOL_PRODUCT)
        consumer = create_consumer()

        # 140000 / 200000 = 0.7000 exactly -> NOT strictly < 0.70 -> ineligible
        b1, _ = _setup_pool_agent(consumer, ctx["product"]["id"], "TIER_D", 140000)
        # 139980 / 200000 = 0.6999 -> strictly < 0.70 -> eligible
        b2, _ = _setup_pool_agent(consumer, ctx["product"]["id"], "TIER_D", 139980)

        set_clock("2026-04-11T00:00:00Z")
        pool = create_bonus_pool(pool_total_cents=1000000)
        settled = validate_success(api.settle_bonus_pool(pool["id"], ADMIN))
        assert settled["undistributed_cents"] == 0

        by_agent = _payouts_by_agent(api, pool["id"])
        p_b1 = by_agent[b1["id"]]
        assert p_b1["eligible"] is False
        assert p_b1["ineligibility_reason"] == "LOSS_RATIO"

        p_b2 = by_agent[b2["id"]]
        assert p_b2["eligible"] is True
        assert p_b2["earned_premium_cents"] == 200000
        # sole eligible agent takes the whole pool: floor(1000000 * 200000/200000)
        assert p_b2["payout_cents"] == 1000000

    def test_loss_ratio_just_below_threshold_is_eligible(self, api):
        """PRD §3.7: "The loss gate: the agent's trailing loss ratio at settle
        time must be **strictly** less than `loss_ratio_threshold`; an agent
        exactly at the threshold fails."

        Design: Difficulty/boundary_precision_check/loss_ratio_strict_threshold_boundary_on_bonus_gate
        """
        set_clock("2026-01-01T00:00:00Z")
        ctx = setup_product_with_feed(product_overrides=POOL_PRODUCT)
        consumer = create_consumer()

        b1, _ = _setup_pool_agent(consumer, ctx["product"]["id"], "TIER_D", 140000)
        b2, _ = _setup_pool_agent(consumer, ctx["product"]["id"], "TIER_D", 139980)

        set_clock("2026-04-11T00:00:00Z")
        pool = create_bonus_pool(pool_total_cents=1000000)
        validate_success(api.settle_bonus_pool(pool["id"], ADMIN))
        by_agent = _payouts_by_agent(api, pool["id"])

        assert by_agent[b1["id"]]["eligible"] is False
        assert by_agent[b1["id"]]["ineligibility_reason"] == "LOSS_RATIO"
        assert by_agent[b2["id"]]["eligible"] is True


class TestLossRatioEmptyBook:
    def test_loss_ratio_with_zero_earned_premium_defined_as_zero(self, api, underwriting_reviewer_headers):
        """PRD §3.7: "When the earned total is zero the ratio is defined as
        0.0000 — the empty-book rule — and otherwise it is incurred divided by
        earned, rounded half-up at 4 decimal places."
        PRD §3.8: "An `UnderwritingReviewer` opens a portfolio review on an agent
        with a `reason`; the platform records the caller's `X-User-ID` as
        `opened_by_user_id`, computes the `trailing_loss_ratio` (4 decimal places)
        and `earned_premium_trailing_cents` (zero when the agent has no policies)
        at open, and refuses to open a second review while one is already `OPEN`
        for the same agent (`ERR_REVIEW_ALREADY_OPEN`)."

        Design: Corner/calculations/loss_ratio_with_zero_earned_premium_defined_as_zero
        """
        set_clock("2026-01-01T00:00:00Z")
        agent = create_appointed_agent()
        review = get_success_data(api.create_portfolio_review(
            agent["id"], {"reason": "scheduled review"}, underwriting_reviewer_headers
        ))
        assert review["trailing_loss_ratio"] == 0.0000
        assert review["earned_premium_trailing_cents"] == 0
        assert review["status"] == "OPEN"
        assert review["opened_by_user_id"] == "test-underwriting-reviewer-1"
