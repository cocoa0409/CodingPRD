"""Difficulty rule: combinatorial_formula.

Offer pricing composes a two-slab mileage deduction, a capped options credit
and a reference-derived floor; each instance pins the branch combination.
"""
from test_helpers import (
    api_client, validate_success,
    make_region, make_config, make_source, make_consumer, make_series,
    make_edition, make_option, submit_accepted_batch,
    create_batch_item_payload, create_cash_offer_payload,
    make_dealer_headers,
)
from test_helpers.fixtures import ADMIN, DATAOPS


def _setup_edition(segment, region_code, price_cents, model, trim):
    region = make_region(region_code=region_code)
    config = make_config(segment=segment, make="Acme", model=model, trim=trim)
    source = make_source(region["id"])
    submit_accepted_batch(source["id"], [
        create_batch_item_payload(config["id"], region["id"],
                                  sold_price_cents=price_cents,
                                  sale_date="2026-08-20", mileage=20000),
    ])
    series = make_series(config["id"], region["id"])
    edition = make_edition(series["id"], publish=True)
    return region, config, source, series, edition


class TestMileageOptionAdjustmentThreeInputNonlinear:
    def test_two_slab_deduction_and_capped_options_credit(self, api):
        """PRD §3.6: "The first 10000 miles of excess are charged at 0.15
        cents per excess mile; any excess beyond 10000 miles is charged at
        0.10 cents per excess mile. Option credit is the sum of the
        credit_cents of the named option packages, capped at 8 percent of the
        edition's reference_price_cents (the cap itself rounded half-up to
        whole cents)."

        reference 3040000 -> private_party 2888000; excess = 50000-3*10000
        = 20000 -> deduction 10000*0.15 + 10000*0.10 = 250000 cents; options
        credit min(140000, round_half_up(3040000*0.08)=243200) = 140000;
        2888000 - 250000 + 140000 = 2778000.

        Design: Difficulty/combinatorial_formula/mileage_option_adjustment_three_input_nonlinear
        """
        region, config, source, series, edition = _setup_edition(
            "TRUCK", "EAST", 3040000, "Truck", "XLT")
        opt_tow = make_option(config["id"], "TOW", 80000)
        opt_bed = make_option(config["id"], "BED", 60000)
        consumer = make_consumer(email="cf1@x.com", full_name="Cf One")

        offer = validate_success(api.create_cash_offer(
            create_cash_offer_payload(
                edition["id"], source["id"], consumer["id"],
                mileage=50000, age_years=3, declared_condition_tier="GOOD",
                option_ids=[opt_tow["id"], opt_bed["id"]]),
            make_dealer_headers(source["id"])), 201)
        assert offer["offer_amount_cents"] == 2778000
        assert offer["status"] == "QUOTED"

    def test_offer_expires_at_published_at_plus_seven_days(self, api):
        """PRD §3.6: "The offer starts QUOTED, and its expires_at is the
        pinned edition's published_at plus 7 days."

        Design: Difficulty/combinatorial_formula/mileage_option_adjustment_three_input_nonlinear
        """
        region, config, source, series, edition = _setup_edition(
            "TRUCK", "EAST", 3040000, "Truck", "XLT")
        opt_tow = make_option(config["id"], "TOW", 80000)
        opt_bed = make_option(config["id"], "BED", 60000)
        consumer = make_consumer(email="cf1b@x.com", full_name="Cf One B")

        offer = validate_success(api.create_cash_offer(
            create_cash_offer_payload(
                edition["id"], source["id"], consumer["id"],
                mileage=50000, age_years=3, declared_condition_tier="GOOD",
                option_ids=[opt_tow["id"], opt_bed["id"]]),
            make_dealer_headers(source["id"])), 201)
        assert offer["offer_amount_cents"] == 2778000
        published_at = edition["published_at"]
        assert published_at is not None
        # expires_at == published_at + 7 days (same time-of-day)
        from datetime import datetime, timedelta, timezone
        pub = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        exp = datetime.fromisoformat(offer["expires_at"].replace("Z", "+00:00"))
        assert exp - pub == timedelta(days=7), (
            f"expires_at must be published_at + 7 days: {published_at} -> {offer['expires_at']}")


class TestOfferFloorAndCapEvaluationOrderPinned:
    def test_options_cap_and_floor_are_computed_from_reference(self, api):
        """PRD §3.6: "Option credit is the sum of the credit_cents of the
        named option packages, capped at 8 percent of the edition's
        reference_price_cents (the cap itself rounded half-up to whole
        cents). The adjusted amount is the tier-multiplied private-party
        value, rounded half-up to whole cents, minus the mileage deduction,
        plus the option credit — but never less than a floor of 20 percent of
        the edition's reference_price_cents, that floor also rounded half-up."

        reference 3040000 -> private_party 2888000; POOR tier raw =
        2888000*0.70 = 2021600; deduction = 10000*0.15 + 290000*0.10 = 3050000
        cents; options credit = min(500000, 243200) = 243200;
        2021600 - 3050000 + 243200 = -786200 < floor 608000 -> floor binds.

        Design: Difficulty/combinatorial_formula/offer_floor_and_cap_evaluation_order_pinned
        """
        region, config, source, series, edition = _setup_edition(
            "SEDAN", "EAST", 3040000, "Sedan", "S")
        opt_lux = make_option(config["id"], "LUX", 500000)
        consumer = make_consumer(email="cf2@x.com", full_name="Cf Two")

        offer = validate_success(api.create_cash_offer(
            create_cash_offer_payload(
                edition["id"], source["id"], consumer["id"],
                mileage=320000, age_years=2, declared_condition_tier="POOR",
                option_ids=[opt_lux["id"]]),
            make_dealer_headers(source["id"])), 201)
        assert offer["offer_amount_cents"] == 608000

    def test_floor_is_twenty_percent_of_reference_not_of_conditioned_base(self, api):
        """PRD §3.6: "The adjusted amount is the tier-multiplied private-party
        value, rounded half-up to whole cents, minus the mileage deduction,
        plus the option credit — but never less than a floor of 20 percent of
        the edition's reference_price_cents, that floor also rounded half-up."

        Computing the floor from the conditioned base instead of the
        reference would yield 20% * 2021600 = 404320; the pinned floor is
        20% * 3040000 = 608000.

        Design: Difficulty/combinatorial_formula/offer_floor_and_cap_evaluation_order_pinned
        """
        region, config, source, series, edition = _setup_edition(
            "SEDAN", "EAST", 3040000, "Sedan", "S")
        opt_lux = make_option(config["id"], "LUX", 500000)
        consumer = make_consumer(email="cf2b@x.com", full_name="Cf Two B")

        offer = validate_success(api.create_cash_offer(
            create_cash_offer_payload(
                edition["id"], source["id"], consumer["id"],
                mileage=320000, age_years=2, declared_condition_tier="POOR",
                option_ids=[opt_lux["id"]]),
            make_dealer_headers(source["id"])), 201)
        assert offer["offer_amount_cents"] == 608000
        assert offer["offer_amount_cents"] != 404320, (
            "floor must be 20% of reference_price_cents, not of the conditioned base")
