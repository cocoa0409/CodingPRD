"""Contractor tier boundaries, tiered unit pricing, and point redemption."""
from test_helpers import (
    CLA,
    RM,
    api_client,
    get_success_data,
    make_dealer_principal_headers,
    post_purchase,
    set_clock,
    setup_contractor,
    setup_onboarded_dealer,
    validate_success,
)


class TestTierBoundary:
    def test_rolling_spend_999999_is_standard(self, api):
        """PRD section 3.6: "The tier thresholds are inclusive: spend of at
        least 10000000 cents is `PLATINUM`; at least 4000000 cents is `GOLD`;
        at least 1000000 cents is `SILVER`; anything below is `STANDARD`.
        Exactly 1000000 cents is therefore `SILVER`, while 999999 cents is
        `STANDARD`."

        Design: Difficulty/boundary_precision_check/tier_boundary_999999_vs_1000000_cents
        """
        ctx = setup_onboarded_dealer()
        contractor = setup_contractor(ctx["dealer"]["id"], company_name="Boundary A")
        # Seed: 10000 units at flat 100 cents = 1000000 gross, minus 1 point
        # redeemed -> net rolling spend 999999.
        post_purchase(
            ctx["dealer"]["id"], contractor["id"], ctx["line"]["id"],
            units=10000, reward_points_redeemed=1,
        )
        # Advance past the purchase month so the seed enters the trailing
        # twelve-full-calendar-month window of PRD section 2.6.
        set_clock("2026-10-01T00:00:00Z")
        purchase = post_purchase(
            ctx["dealer"]["id"], contractor["id"], ctx["line"]["id"], units=1,
        )
        assert purchase["tier_at_post"] == "STANDARD"
        assert purchase["unit_price_cents"] == 100

    def test_rolling_spend_1000000_is_silver(self, api):
        """PRD section 3.6: "The tier thresholds are inclusive: spend of at
        least 10000000 cents is `PLATINUM`; at least 4000000 cents is `GOLD`;
        at least 1000000 cents is `SILVER`; anything below is `STANDARD`.
        Exactly 1000000 cents is therefore `SILVER`, while 999999 cents is
        `STANDARD`."

        Design: Difficulty/boundary_precision_check/tier_boundary_999999_vs_1000000_cents
        """
        ctx = setup_onboarded_dealer()
        contractor = setup_contractor(ctx["dealer"]["id"], company_name="Boundary B")
        post_purchase(
            ctx["dealer"]["id"], contractor["id"], ctx["line"]["id"], units=10000,
        )
        # Advance past the purchase month so the seed enters the trailing
        # twelve-full-calendar-month window of PRD section 2.6.
        set_clock("2026-10-01T00:00:00Z")
        purchase = post_purchase(
            ctx["dealer"]["id"], contractor["id"], ctx["line"]["id"], units=1,
        )
        assert purchase["tier_at_post"] == "SILVER"
        assert purchase["unit_price_cents"] == 95


class TestPerUnitRoundingOrder:
    def test_gold_discount_rounds_per_unit_before_multiplying(self, api):
        """PRD section 3.6: "The per-unit price is computed first: the line's
        `base_price_cents` is multiplied by one minus the discount and rounded
        half-up to integer cents to produce `unit_price_cents`; only then is
        `invoice_cents` computed as `units` multiplied by that rounded
        per-unit price. Applying the discount to the order total and rounding
        once is a different, wrong calculation — for example, 7 units at a
        base of 333 cents under `GOLD` yield a per-unit price of 300 cents
        and an invoice of 2100 cents, whereas summing first and rounding
        would produce 2098 cents."

        Design: Difficulty/combinatorial_formula/contractor_unit_price_per_unit_rounding_order
        """
        ctx = setup_onboarded_dealer(
            line_overrides={"code": "S7", "name": "Specialty Seven", "base_price_cents": 333},
        )
        line1000 = get_success_data(
            api_client.create_product_line(
                {
                    "colorant_system_id": ctx["system"]["id"],
                    "code": "S1000",
                    "name": "Specialty Thousand",
                    "channel_class": "SPECIALTY",
                    "base_price_cents": 1000,
                },
                CLA,
            )
        )
        contractor = setup_contractor(ctx["dealer"]["id"])
        # Seed to GOLD: 4004 units at flat 1000 -> rolling spend 4004000.
        seed = post_purchase(
            ctx["dealer"]["id"], contractor["id"], line1000["id"], units=4004,
        )
        assert seed["invoice_cents"] == 4_004_000
        # Advance past the purchase month so the seed enters the trailing
        # twelve-full-calendar-month window of PRD section 2.6.
        set_clock("2026-10-01T00:00:00Z")
        purchase = post_purchase(
            ctx["dealer"]["id"], contractor["id"], ctx["line"]["id"], units=7,
        )
        assert purchase["tier_at_post"] == "GOLD"
        assert purchase["unit_price_cents"] == 300
        assert purchase["invoice_cents"] == 2100

    def test_silver_discount_rounds_per_unit(self, api):
        """PRD section 3.6: "The discount is 0.00 for `STANDARD`, 0.05 for
        `SILVER`, 0.10 for `GOLD`, and 0.15 for `PLATINUM`. The per-unit
        price is computed first: the line's `base_price_cents` is multiplied
        by one minus the discount and rounded half-up to integer cents to
        produce `unit_price_cents`; only then is `invoice_cents` computed as
        `units` multiplied by that rounded per-unit price."

        Design: Difficulty/combinatorial_formula/contractor_unit_price_per_unit_rounding_order
        """
        ctx = setup_onboarded_dealer()
        contractor = setup_contractor(ctx["dealer"]["id"])
        # Seed to SILVER exactly: 10000 units at 100 = 1000000.
        post_purchase(ctx["dealer"]["id"], contractor["id"], ctx["line"]["id"], units=10000)
        # Advance past the purchase month so the seed enters the trailing
        # twelve-full-calendar-month window of PRD section 2.6.
        set_clock("2026-10-01T00:00:00Z")
        # 3 units at SILVER: round_half_up(100 * 0.95) = 95 -> 285.
        purchase = post_purchase(
            ctx["dealer"]["id"], contractor["id"], ctx["line"]["id"], units=3,
        )
        assert purchase["tier_at_post"] == "SILVER"
        assert purchase["unit_price_cents"] == 95
        assert purchase["invoice_cents"] == 285


class TestRewardRedemptionOrder:
    def test_redemption_clamps_at_invoice_and_excess_dropped(self, api):
        """PRD section 3.6: "Second, `reward_points_redemption_cents` is the
        smaller of `reward_points_redeemed` and `invoice_cents` — points are
        not a stored balance, redemption is capped per purchase at the
        invoice value, and any excess points are silently dropped rather than
        rejected."

        Design: Difficulty/combinatorial_formula/reward_redemption_evaluation_order
        """
        ctx = setup_onboarded_dealer()
        contractor = setup_contractor(ctx["dealer"]["id"])
        # Seed to exactly SILVER: 10000 units at flat 100 = 1000000.
        post_purchase(ctx["dealer"]["id"], contractor["id"], ctx["line"]["id"], units=10000)
        # Advance past the purchase month so the seed enters the trailing
        # twelve-full-calendar-month window of PRD section 2.6.
        set_clock("2026-10-01T00:00:00Z")
        # 50 units at SILVER price 95 -> invoice 4750; redeem 4999 points.
        purchase = post_purchase(
            ctx["dealer"]["id"], contractor["id"], ctx["line"]["id"],
            units=50, reward_points_redeemed=4999,
        )
        assert purchase["tier_at_post"] == "SILVER"
        assert purchase["invoice_cents"] == 4750
        assert purchase["reward_points_redemption_cents"] == 4750

    def test_redemption_feeds_net_rolling_spend(self, api):
        """PRD section 3.6: "Fourth, the account's rolling net spend — and
        therefore its next tier — uses the net values: `invoice_cents` minus
        `refund_cents` minus `reward_points_redemption_cents`."
        PRD section 3.6: "the sum, over the account's purchases that are not
        `VOIDED` and whose `created_at` falls inside the
        trailing-twelve-full-calendar-month window of §2.6, of each
        purchase's `invoice_cents` minus its `refund_cents` minus its
        `reward_points_redemption_cents`."

        Design: Difficulty/combinatorial_formula/reward_redemption_evaluation_order
        """
        ctx = setup_onboarded_dealer()
        contractor = setup_contractor(ctx["dealer"]["id"])
        # Post 10000 units at flat 100 = 1000000 gross, redeem 1 point ->
        # net rolling spend 999999, so the account stays STANDARD.
        post_purchase(
            ctx["dealer"]["id"], contractor["id"], ctx["line"]["id"],
            units=10000, reward_points_redeemed=1,
        )
        # Advance past the purchase month so the seed enters the trailing
        # twelve-full-calendar-month window of PRD section 2.6.
        set_clock("2026-10-01T00:00:00Z")
        account = validate_success(
            api_client.get_contractor(
                contractor["id"], make_dealer_principal_headers(ctx["dealer"]["id"])
            )
        )
        assert account["rolling_net_spend_cents"] == 999_999
        assert account["tier"] == "STANDARD"


class TestImmediateConsistency:
    def test_purchase_response_carries_derived_fields(self, api):
        """PRD section 3.6: "The tier applied is the contractor's tier
        evaluated before this purchase is added to rolling spend, recorded on
        the purchase as `tier_at_post`."
        PRD section 3.5: "At submission the server records `unit_price_cents`
        as the line's `base_price_cents` (dealer orders receive no tier
        discount) and `invoice_cents` as `units` multiplied by that unit
        price."
        PRD section 2.2: "Unless otherwise noted, operations that create or
        modify a resource will return the created or updated resource object
        in the data field."

        Design: Corner/consistency model/immediate_visibility_of_purchase_derived_fields
        """
        ctx = setup_onboarded_dealer()
        contractor = setup_contractor(ctx["dealer"]["id"])
        purchase = post_purchase(
            ctx["dealer"]["id"], contractor["id"], ctx["line"]["id"],
            units=3, reward_points_redeemed=50,
        )
        assert purchase["unit_price_cents"] == 100
        assert purchase["invoice_cents"] == 300
        assert purchase["reward_points_redemption_cents"] == 50
        assert purchase["tier_at_post"] == "STANDARD"
