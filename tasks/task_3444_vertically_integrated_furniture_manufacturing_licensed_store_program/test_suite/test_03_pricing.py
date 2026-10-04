"""Pricing: clearance-base wholesale tiers, per-order royalty rounding, tier
boundaries, and submit-time repricing (PRD §2.6, §3.1, §3.5)."""
from test_helpers import (
    assert_licensee_ledger_consistent,
    create_licensee_order,
    create_product_line,
    create_retail_order,
    create_retail_account,
    deliver_freight_order,
    get_licensee,
    advance_product_line,
    run_cycle,
    setup_catalog,
    setup_open_cycle,
    submit_order,
    validate_success,
)


class TestClearanceBaseTimesWholesaleTier:
    """Difficulty instance: order_pricing_clearance_base_times_wholesale_tier."""

    def _setup(self):
        ctx = setup_open_cycle()
        # Advance ACTIVE -> CLEARANCE.
        line = advance_product_line(ctx["line"]["id"])
        ctx["line"] = line
        account = create_retail_account(
            business_name="Metro Discount Furniture", credit_limit_cents=5_000_000
        )
        ctx["account"] = account
        return ctx

    def test_clearance_base_and_tier2_unit_price(self, api, platform_admin_headers):
        """PRD §3.1: "Its `clearance_price_cents` is computed as the price point times
        the clearance keep `CLEARANCE_MARKDOWN_KEEP` of 0.75, rounded half-up to cents"
        PRD §3.5: "0.09 when it reaches the `TIER2_QTY` threshold of 25 or more but
        under 50"
        PRD §3.5: "the unit price is the base times (1 − rate), rounded half-up to cents"

        Design: Difficulty/combinatorial_formula/order_pricing_clearance_base_times_wholesale_tier
        """
        ctx = self._setup()
        assert ctx["line"]["lifecycle"] == "CLEARANCE"
        # round_half_up(89900 * 0.75) == 67425.
        assert ctx["line"]["clearance_price_cents"] == 67425
        resp_order = create_retail_order(
            ctx["account"], ctx["cycle"], ctx["line"], quantity=25
        )
        # round_half_up(67425 * (1 - 0.09)) == round_half_up(61356.75) == 61357.
        assert resp_order["unit_price_cents"] == 61357, (
            f"expected unit 61357, got {resp_order['unit_price_cents']}"
        )

    def test_clearance_total_rounds_unit_before_multiplying(self, api, platform_admin_headers):
        """PRD §3.5: "In both branches the rounding order is pinned: the unit is rounded
        half-up first, and the order total is that rounded unit multiplied by the
        quantity."

        Design: Difficulty/combinatorial_formula/order_pricing_clearance_base_times_wholesale_tier
        """
        ctx = self._setup()
        order = create_retail_order(
            ctx["account"], ctx["cycle"], ctx["line"], quantity=25
        )
        # 61357 * 25 == 1533925 (unit rounded BEFORE the multiply).
        assert order["provisional_total_cents"] == 1_533_925, (
            f"expected provisional total 1533925, got {order['provisional_total_cents']}"
        )


class TestRoyaltyPerOrderRounding:
    """Difficulty instance: royalty_per_order_rounding_beats_sum_then_round.
    Birch line at 59900, licensee default royalty 0.04: order A qty 1 totals
    41930 (royalty round_half_up(41930*0.04) == 1677), order B qty 2 totals
    83860 (royalty 3354); the ledger must read 5031, not the sum-first 5032."""

    def _setup_delivered_pair(self):
        ctx = setup_open_cycle()
        line_b = create_product_line(
            name="Birch Bedroom Set",
            category="CASEGOODS",
            price_point_cents=59900,
            style_code="BR-BED-01",
        )
        line_b = advance_product_line(line_b["id"])
        ctx["line"] = line_b
        o_a = create_licensee_order(ctx["licensee"], ctx["cycle"], line_b, quantity=1)
        o_b = create_licensee_order(ctx["licensee"], ctx["cycle"], line_b, quantity=2)
        submit_order(o_a)
        submit_order(o_b)
        run_cycle(ctx["cycle"]["id"])
        deliver_freight_order(o_a["id"])
        deliver_freight_order(o_b["id"])
        return ctx, o_a, o_b

    def test_per_order_totals_and_accrued_royalty(self, api, platform_admin_headers):
        """PRD §3.5: "For a licensee buyer, delivery also accrues royalty: the order's
        `final_total_cents` times the licensee's `royalty_rate`, rounded half-up to
        cents, with the rate read at delivery time"
        PRD §2.6: "In the licensee royalty ledger, each order's royalty and each claim's
        chargeback is rounded half-up to cents before any summation — round per line,
        then sum; summing first and rounding once is never correct."

        Design: Difficulty/combinatorial_formula/royalty_per_order_rounding_beats_sum_then_round
        """
        ctx, o_a, o_b = self._setup_delivered_pair()
        a = validate_success(api.get_order(o_a["id"], platform_admin_headers))
        b = validate_success(api.get_order(o_b["id"], platform_admin_headers))
        # round_half_up(59900 * 0.70) == 41930.
        assert a["final_total_cents"] == 41930
        assert b["final_total_cents"] == 83860
        licensee = get_licensee(ctx["licensee"]["id"])
        # 1677 + 3354 == 5031; sum-then-round would falsely give 5032.
        assert licensee["royalty_accrued_cents"] == 5031, (
            f"expected accrued 5031, got {licensee['royalty_accrued_cents']}"
        )

    def test_net_royalty_equals_accrued_minus_zero_chargebacks(self, api, platform_admin_headers):
        """PRD §3.2: "its computed ledger fields `royalty_accrued_cents` and
        `chargeback_cents` start at 0, with `net_royalty_cents` derived as accrued minus
        chargebacks"
        PRD §3.7: "`chargeback_cents` is the sum of the per-claim rounded chargebacks
        over the licensee's approved `DAMAGE_IN_TRANSIT` claims"

        Design: Difficulty/combinatorial_formula/royalty_per_order_rounding_beats_sum_then_round
        """
        ctx, _, _ = self._setup_delivered_pair()
        licensee = get_licensee(ctx["licensee"]["id"])
        assert licensee["chargeback_cents"] == 0
        assert licensee["net_royalty_cents"] == 5031
        assert_licensee_ledger_consistent(licensee)


class TestWholesaleTierBoundary:
    def test_wholesale_tier_boundary_qty9_full_price_qty10_five_pct(self, api, platform_admin_headers):
        """PRD §3.5: "For a retail buyer, a wholesale quantity tier sets the rate: 0.14
        when the order's `quantity` reaches the `TIER3_QTY` threshold of 50 units or
        more, 0.09 when it reaches the `TIER2_QTY` threshold of 25 or more but under 50,
        0.05 when it reaches the `TIER1_QTY` threshold of 10 or more but under 25, and
        no discount under 10"

        Design: Corner/calculations/wholesale_tier_boundary_qty9_full_price_qty10_five_pct
        """
        ctx = setup_open_cycle()
        account = create_retail_account(credit_limit_cents=5_000_000)
        o9 = create_retail_order(account, ctx["cycle"], ctx["line"], quantity=9)
        o10 = create_retail_order(account, ctx["cycle"], ctx["line"], quantity=10)
        # qty 9: no discount — unit 89900, total 809100.
        assert o9["unit_price_cents"] == 89900
        assert o9["provisional_total_cents"] == 809100
        # qty 10: 5% tier — unit round_half_up(89900 * 0.95) == 85405, total 854050.
        assert o10["unit_price_cents"] == 85405
        assert o10["provisional_total_cents"] == 854050


class TestSubmitRepricing:
    def test_submit_reprices_when_line_moves_to_clearance(self, api, platform_admin_headers):
        """PRD §3.5: "The base is the line's `price_point_cents` while the line is
        `ACTIVE`, or its `clearance_price_cents` — the 75-percent keep, rounded half-up
        — while the line is `CLEARANCE`; `CONCEPT` and `RETIRED` lines are not orderable
        at all."
        PRD §3.5: "The provisional variant prices off the line's lifecycle at the moment
        of pricing — at create, and again at submit if the lifecycle changed since
        create — and fills `unit_price_cents` and `provisional_total_cents`."

        Design: Corner/calculations/submit_reprices_when_line_moves_to_clearance
        """
        ctx = setup_open_cycle()
        order = create_licensee_order(
            ctx["licensee"], ctx["cycle"], ctx["line"], quantity=1
        )
        assert order["unit_price_cents"] == 62930  # ACTIVE base: 89900 * 0.70
        # Move the line ACTIVE -> CLEARANCE between create and submit.
        advance_product_line(ctx["line"]["id"])
        submitted = submit_order(order)
        # Clearance base 67425; licensee unit round_half_up(67425 * 0.70) == 47198.
        assert submitted["unit_price_cents"] == 47198, (
            f"expected repriced unit 47198, got {submitted['unit_price_cents']}"
        )
        assert submitted["provisional_total_cents"] == 47198
        assert submitted["allocation_state"] == "RESERVED"
