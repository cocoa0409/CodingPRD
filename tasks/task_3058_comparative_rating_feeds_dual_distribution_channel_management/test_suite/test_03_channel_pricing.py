"""Channel pricing: per-line rounding order, post-sum floor, the conditional
channel/bundle branches, and the direct-channel anti-conflict premium cap."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_product,
    create_agent_quote,
    create_appointed_agent,
    create_consumer,
    create_direct_quote,
    create_published_feed,
    create_rater,
    make_agent_headers,
    make_consumer_headers,
    set_clock,
    setup_product_with_feed,
    validate_error,
    validate_success,
)


class TestPremiumRoundingOrder:
    def test_premium_per_line_rounding_order_pinned(self, api):
        """PRD §2.6: "Quote premiums are rounded **per coverage line first**, then
        summed; the premium floor is applied only after the sum of rounded lines."

        Design: Corner/calculations/premium_per_line_rounding_order_pinned
        """
        set_clock("2026-01-01T00:00:00Z")
        product = create_active_product(
            product_code="P-ODD",
            channel_availability="DIRECT",
            coverage_rates={"ODD": {"STD": 33333}},
            direct_discount_pct=0.10,
            min_premium_cents=0,
        )
        consumer = create_consumer()
        quote = create_direct_quote(
            consumer, product["id"],
            coverages=[
                {"coverage_code": "ODD", "tier": "STD"},
                {"coverage_code": "ODD", "tier": "STD"},
            ],
        )
        submitted = validate_success(
            api.submit_quote(quote["id"], make_consumer_headers(consumer["id"]))
        )
        # 33333 * 0.90 = 29999.7 -> round_half_up -> 30000 per line, then summed
        assert submitted["quoted_premium_cents"] == 60000
        assert submitted["quoted_premium_cents"] != 59999


class TestPremiumFloor:
    def test_premium_floor_applied_after_sum(self, api):
        """PRD §3.1: "A `min_premium_cents` floor applies to every quoted premium
        after line-level rounding and summation."

        Design: Corner/calculations/premium_floor_applied_after_sum
        """
        set_clock("2026-01-01T00:00:00Z")
        product = create_active_product(
            product_code="P-MIN",
            channel_availability="DIRECT",
            coverage_rates={"TINY": {"STD": 10000}},
            direct_discount_pct=0.10,
            min_premium_cents=40000,
        )
        consumer = create_consumer()
        quote = create_direct_quote(
            consumer, product["id"],
            coverages=[{"coverage_code": "TINY", "tier": "STD"}],
        )
        submitted = validate_success(
            api.submit_quote(quote["id"], make_consumer_headers(consumer["id"]))
        )
        # raw sum 10000 * 0.90 = 9000, raised to the 40000 floor after summing
        assert submitted["quoted_premium_cents"] == 40000


class TestChannelBranchAndBundleCredit:
    COVERAGES = [
        {"coverage_code": "LIABILITY", "tier": "BASIC"},
        {"coverage_code": "COLLISION", "tier": "STANDARD"},
    ]

    def _setup(self, api):
        set_clock("2026-01-01T00:00:00Z")
        ctx = setup_product_with_feed(
            product_overrides={
                "coverage_rates": {"LIABILITY": {"BASIC": 50000},
                                   "COLLISION": {"STANDARD": 90000}},
                "direct_discount_pct": 0.10,
                "agent_load_pct": 0.15,
                "bundle_credit_pct": 0.05,
                "min_premium_cents": 40000,
            }
        )
        agent = create_appointed_agent()
        consumer = create_consumer()
        return ctx, agent, consumer

    def test_direct_branch_prices_at_discount_factor(self, api):
        """PRD §3.3: "a channel factor is chosen first (for `DIRECT`, one minus
        `direct_discount_pct`; for `AGENT`, one plus `agent_load_pct`, less
        `bundle_credit_pct` when `bundled_home_intended` is true)"

        Design: Difficulty/combinatorial_formula/channel_quote_premium_multi_input_branch_and_floor_mode_a
        """
        ctx, agent, consumer = self._setup(api)
        quote = create_direct_quote(consumer, ctx["product"]["id"], coverages=self.COVERAGES)
        submitted = validate_success(
            api.submit_quote(quote["id"], make_consumer_headers(consumer["id"]))
        )
        # 50000 * 0.90 + 90000 * 0.90 = 45000 + 81000
        assert submitted["quoted_premium_cents"] == 126000

    def test_agent_branch_prices_at_load_factor_and_bundle_credit_subtracts(self, api):
        """PRD §3.3: "a channel factor is chosen first (for `DIRECT`, one minus
        `direct_discount_pct`; for `AGENT`, one plus `agent_load_pct`, less
        `bundle_credit_pct` when `bundled_home_intended` is true)"
        PRD §3.1: "When a consumer intends to bundle a home placement,
        `bundle_credit_pct` (default 0) is subtracted from the agent load for that
        quote."

        Design: Difficulty/combinatorial_formula/channel_quote_premium_multi_input_branch_and_floor_mode_a
        """
        ctx, agent, consumer = self._setup(api)
        agent_headers = make_agent_headers(agent["id"])

        quote_plain = create_agent_quote(
            consumer, agent, ctx["product"]["id"], coverages=self.COVERAGES
        )
        submitted_plain = validate_success(api.submit_quote(quote_plain["id"], agent_headers))
        # 50000 * 1.15 + 90000 * 1.15 = 57500 + 103500
        assert submitted_plain["quoted_premium_cents"] == 161000

        quote_bundle = create_agent_quote(
            consumer, agent, ctx["product"]["id"],
            coverages=self.COVERAGES, bundled_home_intended=True,
        )
        submitted_bundle = validate_success(api.submit_quote(quote_bundle["id"], agent_headers))
        # factor 1.15 - 0.05 = 1.10 -> 55000 + 99000
        assert submitted_bundle["quoted_premium_cents"] == 154000


class TestDirectPremiumCap:
    def test_premium_cap_exceeded_on_direct_submit(self, api):
        """PRD §3.1: "The anti-conflict lever is
        `direct_channel_max_premium_cents` (default null): when set, a
        direct-channel submission whose computed premium exceeds the cap is
        refused."
        PRD §3.3: "when the product carries a
        `direct_channel_max_premium_cents` cap, a direct-channel premium above
        the cap is refused with `ERR_PREMIUM_CAP_EXCEEDED`."

        Design: Corner/validations/premium_cap_exceeded_on_direct_submit
        """
        set_clock("2026-01-01T00:00:00Z")
        ctx = setup_product_with_feed(
            product_overrides={
                "coverage_rates": {"LIABILITY": {"BASIC": 50000},
                                   "COLLISION": {"STANDARD": 90000}},
                "direct_discount_pct": 0.10,
                "agent_load_pct": 0.15,
                "min_premium_cents": 0,
                "direct_channel_max_premium_cents": 100000,
            }
        )
        agent = create_appointed_agent()
        consumer = create_consumer()
        coverages = [
            {"coverage_code": "LIABILITY", "tier": "BASIC"},
            {"coverage_code": "COLLISION", "tier": "STANDARD"},
        ]

        direct_quote = create_direct_quote(consumer, ctx["product"]["id"], coverages=coverages)
        resp = api.submit_quote(direct_quote["id"], make_consumer_headers(consumer["id"]))
        validate_error(resp, ApiErrorId.ERR_PREMIUM_CAP_EXCEEDED, 409)

        agent_quote = create_agent_quote(consumer, agent, ctx["product"]["id"], coverages=coverages)
        submitted = validate_success(
            api.submit_quote(agent_quote["id"], make_agent_headers(agent["id"]))
        )
        assert submitted["quoted_premium_cents"] == 161000
