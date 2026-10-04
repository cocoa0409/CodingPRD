"""Difficulty rule: dual_variant_calc.

Two readings of the same inputs produce different outcomes depending on which
variant or which blending rule is applied; the PRD pins exactly one.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    make_region, make_config, make_source, make_consumer, make_series,
    make_edition, submit_accepted_batch, create_batch_item_payload,
    create_market_shift_payload, create_cash_offer_payload,
    make_dealer_headers, get_offer, get_edition,
)

from test_helpers.fixtures import ADMIN, DATAOPS


class TestOfferSelfDeclaredGoodVsInspectedFairReprice:
    def test_good_quote_amount_and_frozen_at_creation(self, api):
        """PRD §3.6: "The quoted offer_amount_cents is computed once at
        creation, frozen, and never recomputed. The computation starts from
        the pinned edition's private_party_cents multiplied by the catalog
        multiplier of the declared condition tier, then applies the
        mileage-and-option adjustment."

        With reference 2001000: private_party = round_half_up(2001000*0.95)
        = 1900950; tier GOOD multiplier 1.00 -> base 1900950; excess
        40000 - 2*10000 = 20000 -> deduction 10000*0.15 + 10000*0.10 = 2500.00
        = 250000 cents; no options -> 1900950 - 250000 = 1650950.

        Design: Difficulty/dual_variant_calc/offer_self_declared_good_vs_inspected_fair_reprice
        """
        region = make_region(region_code="WEST", name="West Region")
        config = make_config(segment="SUV", make="Acme", model="CUV",
                             year=2022, trim="LX")
        source = make_source(region["id"])
        submit_accepted_batch(source["id"], [
            create_batch_item_payload(config["id"], region["id"],
                                      sold_price_cents=2001000,
                                      sale_date="2026-08-20", mileage=30000),
        ])
        series = make_series(config["id"], region["id"])
        edition = make_edition(series["id"], publish=True)
        consumer = make_consumer(email="dv1@x.com", full_name="Dv One")

        offer = validate_success(api.create_cash_offer(
            create_cash_offer_payload(
                edition["id"], source["id"], consumer["id"],
                mileage=40000, age_years=2, declared_condition_tier="GOOD",
                option_ids=[]),
            make_dealer_headers(source["id"])), 201)
        assert offer["offer_amount_cents"] == 1650950
        assert offer["status"] == "QUOTED"

    def test_inspected_fair_reprices_but_ninety_percent_floor_binds(self, api):
        """PRD §3.6: "the offer moves QUOTED -> INSPECTED and
        final_amount_cents is computed by the same formula as the quote, but
        at the inspected tier rather than the declared tier, and then capped
        below at 90 percent of the frozen offer_amount_cents (the cap computed
        by multiplying the quote by 0.90 and rounding half-up) — so a
        consumer-declared GOOD that inspects as FAIR re-prices downward but
        the final amount cannot fall below that 90 percent floor."

        Raw FAIR re-price = round_half_up(1900950*0.85) - 250000 = 1365808
        (below the floor); the floor round_half_up(1650950*0.90) = 1485855
        binds.

        Design: Difficulty/dual_variant_calc/offer_self_declared_good_vs_inspected_fair_reprice
        """
        region = make_region(region_code="WEST", name="West Region")
        config = make_config(segment="SUV", make="Acme", model="CUV",
                             year=2022, trim="LX")
        source = make_source(region["id"])
        submit_accepted_batch(source["id"], [
            create_batch_item_payload(config["id"], region["id"],
                                      sold_price_cents=2001000,
                                      sale_date="2026-08-20", mileage=30000),
        ])
        series = make_series(config["id"], region["id"])
        edition = make_edition(series["id"], publish=True)
        consumer = make_consumer(email="dv1b@x.com", full_name="Dv One B")

        offer = validate_success(api.create_cash_offer(
            create_cash_offer_payload(
                edition["id"], source["id"], consumer["id"],
                mileage=40000, age_years=2, declared_condition_tier="GOOD",
                option_ids=[]),
            make_dealer_headers(source["id"])), 201)

        inspected = validate_success(api.inspect_cash_offer(
            offer["id"], {"inspected_condition_tier": "FAIR"},
            make_dealer_headers(source["id"])), 200)
        assert inspected["status"] == "INSPECTED"
        assert inspected["offer_amount_cents"] == 1650950
        assert inspected["final_amount_cents"] == 1485855
        assert inspected["final_amount_cents"] != 1365808, (
            "raw FAIR re-price must lose to the 90%-of-quote floor")


class TestMarketShiftAdditiveVsCompoundedBlending:
    def _setup(self):
        region = make_region(region_code="EAST", name="East Region")
        config = make_config(segment="TRUCK", make="Acme", model="Truck",
                             year=2023, trim="XLT")
        dealer = make_source(region["id"], source_type="DEALER",
                             external_key="src-dv2a", name="D1")
        auction = make_source(region["id"], source_type="AUCTION",
                              external_key="src-dv2b", name="A1")
        lender = make_source(region["id"], source_type="LENDER",
                             external_key="src-dv2c", name="L1")
        submit_accepted_batch(dealer["id"], [
            create_batch_item_payload(config["id"], region["id"],
                                      sold_price_cents=3000000,
                                      sale_date="2026-08-20", mileage=20000),
        ], submission_ref="b-dv2a")
        submit_accepted_batch(auction["id"], [
            create_batch_item_payload(config["id"], region["id"],
                                      sold_price_cents=2800000,
                                      sale_date="2026-07-10", mileage=25000),
        ], submission_ref="b-dv2b")
        submit_accepted_batch(lender["id"], [
            create_batch_item_payload(config["id"], region["id"],
                                      sold_price_cents=3200000,
                                      sale_date="2026-08-25", mileage=18000),
        ], submission_ref="b-dv2c")
        # Region-scoped shift + global shift, both +2% and ACTIVE.
        sh_a = validate_success(api_client.create_market_shift(
            create_market_shift_payload(region_id=region["id"], segment=None,
                                        effective_at="2026-09-01T00:00:00Z",
                                        pct_adjustment=0.02),
            ADMIN), 201)
        sh_b = validate_success(api_client.create_market_shift(
            create_market_shift_payload(region_id=None, segment=None,
                                        effective_at="2026-09-01T00:00:00Z",
                                        pct_adjustment=0.02),
            ADMIN), 201)
        validate_success(api_client.activate_market_shift(sh_a["id"], ADMIN), 200)
        validate_success(api_client.activate_market_shift(sh_b["id"], ADMIN), 200)
        series = make_series(config["id"], region["id"],
                             external_key="ser-dv2")
        return series

    def test_two_matching_shifts_sum_additively(self, api):
        """PRD §3.4: "The matching adjustments are summed additively (never
        compounded), and the blended reference is the raw weighted average
        multiplied by one plus that sum, rounded half-up to whole cents."

        Raw weighted average: (3000000*2 + 2800000*1 + 3200000*2) / (2+1+2)
        = 3040000. Two +2% shifts sum to +4%: round_half_up(3040000*1.04)
        = 3161600; compounding would give 3162816.

        Design: Difficulty/dual_variant_calc/market_shift_additive_vs_compounded_blending
        """
        series = self._setup()
        edition = validate_success(api.create_valuation_edition(
            {"series_id": series["id"], "effective_at": "2026-09-01T00:00:00Z"},
            ADMIN), 201)
        assert edition["reference_price_cents"] == 3161600
        assert edition["reference_price_cents"] != 3162816, (
            "compounded blending (1.02*1.02) is not the documented rule")

    def test_blended_reference_feeds_tier_values(self, api):
        """PRD §3.4: "From the final reference, the three tier values are
        derived and frozen at publication: trade_in_cents is the reference
        times 0.87, private_party_cents is the reference times 0.95, and
        retail_cents is the reference times 1.08, each rounded half-up to
        whole cents."

        reference 3161600 -> trade_in round_half_up(3161600*0.87) = 2750592;
        retail round_half_up(3161600*1.08) = 3414528.

        Design: Difficulty/dual_variant_calc/market_shift_additive_vs_compounded_blending
        """
        series = self._setup()
        edition = validate_success(api.create_valuation_edition(
            {"series_id": series["id"], "effective_at": "2026-09-01T00:00:00Z"},
            ADMIN), 201)
        assert edition["trade_in_cents"] == 2750592
        assert edition["retail_cents"] == 3414528
