"""Share pricing: tier boundaries, volume discount, quoted-vs-locked variants (PRD §3.3)."""
from test_helpers import (
    create_agent,
    create_brokerage,
    create_market,
    create_share_order,
    get_market,
    make_agent_headers,
    set_clock,
    setup_market_with_active_order,
    validate_success,
)


class TestQuotedVsLockedVariant:
    def test_locked_order_keeps_tier1_price_after_market_flips_to_tier2(self, api, marketplace_ops_headers):
        """PRD §3.3: "Crucially, the quote is demand-sensitive: if another buyer activates
        a large order between quote and payment, the tier that applies at activation may
        differ from what was quoted. The locked values on the order reflect the purchase
        instant; subsequent market changes do not reopen them."

        Design: Difficulty/dual_variant_calc/share_price_quoted_vs_locked_variant
        """
        set_clock()
        market, brokerage, agent1, order1 = setup_market_with_active_order(
            zip_code="90210", state_code="CA", share_bps=6000
        )
        agent2 = create_agent(brokerage["id"], license_state="CA")
        quote = validate_success(api.get_price_quote(market["id"], marketplace_ops_headers, 4000))
        assert quote["tier"] == 2
        assert quote["unit_price_cents"] == 11875
        order2 = validate_success(
            api.create_share_order(
                {"market_id": market["id"], "buyer_agent_id": agent2["id"],
                 "share_bps": 4000, "duration_days": 30},
                make_agent_headers(agent2["id"]),
            ),
            201,
        )
        assert order2["tier"] == 2
        assert order2["unit_price_cents"] == 11875
        assert order2["deposit_cents"] == 2375000
        fresh1 = validate_success(api.get_share_order(order1["id"], marketplace_ops_headers))
        assert fresh1["tier"] == 1
        assert fresh1["unit_price_cents"] == 9000, "locked variant must not reprice"

    def test_market_counters_reflect_first_activation(self, api, marketplace_ops_headers):
        """PRD §2.5: "When an order transitions into `ACTIVE`, its `share_bps` is added to
        `allocated_bps`; ... Each such mutation recomputes the market's
        `current_unit_price_cents` and increments the market's `version`."

        Design: Difficulty/dual_variant_calc/share_price_quoted_vs_locked_variant
        """
        set_clock()
        market, _, _, _ = setup_market_with_active_order(
            zip_code="90212", state_code="CA", share_bps=6000
        )
        fresh = get_market(market["id"])
        assert fresh["allocated_bps"] == 6000
        assert fresh["available_bps"] == 4000
        assert fresh["current_unit_price_cents"] == 12500


class TestTierVolumeCombinator:
    def test_tier2_volume_discount_boundary_2499_vs_2500(self, api, marketplace_ops_headers):
        """PRD §3.3: "The quote then applies a volume discount based on the requested
        `share_bps`: no discount below 2500 basis points, a 5 percent discount when the
        request is at least 2500 but less than 5000 basis points, and a 10 percent
        discount at 5000 basis points or more."
        PRD §2.11: "per-lead prices use floor division when a percentage adjustment is applied"

        Design: Difficulty/combinatorial_formula/share_price_tier_volume_combinator
        """
        set_clock()
        market, _, _, _ = setup_market_with_active_order(
            zip_code="98101", state_code="WA", share_bps=6000
        )
        quote_2499 = validate_success(api.get_price_quote(market["id"], marketplace_ops_headers, 2499))
        quote_2500 = validate_success(api.get_price_quote(market["id"], marketplace_ops_headers, 2500))
        assert quote_2499["unit_price_cents"] == 12500, "tier 2 x1.25, no discount below 2500"
        assert quote_2500["unit_price_cents"] == 11875, "tier 2 x1.25 x0.95"
        assert quote_2500["tier"] == 2

    def test_tier2_volume_discount_compounds_non_linearly(self, api, marketplace_ops_headers):
        """PRD §3.3: "The `unit_price_cents` is the market's `base_lead_price_cents`
        multiplied by one plus 25 percent per tier step above tier 1, then multiplied by
        one minus the volume discount, with the final value floored to integer cents."

        Design: Difficulty/combinatorial_formula/share_price_tier_volume_combinator
        """
        set_clock()
        market, _, _, _ = setup_market_with_active_order(
            zip_code="98102", state_code="WA", share_bps=6000
        )
        quote = validate_success(api.get_price_quote(market["id"], marketplace_ops_headers, 5000))
        assert quote["tier"] == 2
        assert quote["unit_price_cents"] == 11250, "floor(10000 * 1.25 * 0.90)"
        assert quote["deposit_cents"] == 2250000, "deposit = tier * 100 * unit"


class TestTierThresholdBoundary:
    def test_tier_flips_at_exactly_5000_allocated_bps(self, api, marketplace_ops_headers):
        """PRD §3.3: "if the allocated share is less than 50 percent of capacity the
        demand `tier` is 1, otherwise if it is less than 80 percent the `tier` is 2,
        otherwise the `tier` is 3."

        Design: Difficulty/boundary_precision_check/tier_threshold_at_5000_bps
        """
        set_clock()
        market, brokerage, agent1, _ = setup_market_with_active_order(
            zip_code="10001", state_code="NY", share_bps=4999
        )
        agent2 = create_agent(brokerage["id"], license_state="NY")
        before = validate_success(api.get_price_quote(market["id"], marketplace_ops_headers, 100))
        assert before["tier"] == 1
        assert before["unit_price_cents"] == 10000
        order2 = create_share_order(market["id"], agent2["id"], share_bps=1)
        market_v = get_market(market["id"])["version"]
        validate_success(
            api.capture_payment(
                order2["id"],
                {"amount_cents": order2["deposit_cents"], "outcome": "SUCCEEDED",
                 "expected_market_version": market_v},
                make_agent_headers(agent2["id"]),
            ),
            201,
        )
        after = validate_success(api.get_price_quote(market["id"], marketplace_ops_headers, 100))
        assert after["tier"] == 2, "allocated 5000 hits the >= 50 percent boundary"
        assert after["unit_price_cents"] == 12500

    def test_tier_boundary_one_bps_below_stays_tier1(self, api, marketplace_ops_headers):
        """PRD §3.3: "if the allocated share is less than 50 percent of capacity the
        demand `tier` is 1".

        Design: Difficulty/boundary_precision_check/tier_threshold_at_5000_bps
        """
        set_clock()
        market, _, _, _ = setup_market_with_active_order(
            zip_code="10002", state_code="NY", share_bps=4999
        )
        quote = validate_success(api.get_price_quote(market["id"], marketplace_ops_headers, 100))
        assert quote["tier"] == 1
        assert quote["unit_price_cents"] == 10000
        assert get_market(market["id"])["allocated_bps"] == 4999


class TestTier3Constants:
    def test_price_constants_applied_at_tier3(self, api, marketplace_ops_headers):
        """PRD §3.3: "if the allocated share is less than 50 percent of capacity the
        demand `tier` is 1, otherwise if it is less than 80 percent the `tier` is 2,
        otherwise the `tier` is 3."
        PRD §3.3: "The `deposit_cents` required at activation is the `tier` multiplied by
        100, multiplied by the `unit_price_cents`."

        Design: Corner/calculations/price_constants_applied_at_tier3
        """
        set_clock()
        market, _, _, _ = setup_market_with_active_order(
            zip_code="97214", state_code="OR", share_bps=8000
        )
        quote = validate_success(api.get_price_quote(market["id"], marketplace_ops_headers, 1000))
        assert quote["tier"] == 3, "allocated 8000 is exactly the 80 percent boundary"
        assert quote["unit_price_cents"] == 15000, "base 10000 x 1.5"
        assert quote["deposit_cents"] == 4500000, "3 * 100 * 15000"
