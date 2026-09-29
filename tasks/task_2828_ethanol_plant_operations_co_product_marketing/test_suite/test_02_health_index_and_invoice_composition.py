"""
Multi-stage composite formulas where the rounding order is load-bearing.

Two composites are exercised here: the fermentation health index, which caps and
rounds each reading's own score before the weighted mean is taken, and the
co-product invoice, whose four steps compose a unit divisor, an inclusive rebate
tier ladder and an inclusive freight cap in a fixed order.
"""

import pytest

from test_helpers import fixtures as fx
from test_helpers import get_success_data, validate_success
from test_helpers.assertions import assert_2dp, assert_integer_cents
from test_helpers.test_users import GRAIN_BUYER, PROCESS_OPERATOR


def _batch_on_two_readings(api):
    """
    FB-2001 charged with 900.00 bushels of exactly-basis corn, carrying the two
    earlier readings that scored 68.07 and 94.12.
    """
    fx.commission_plant(
        api,
        base_grind_cap_bushels=120000,
        coverage_floor_bushels=5000,
        baseline_ci_g_per_mj=60.0,
        rin_generation_enabled=True,
    )
    fx.advance_clock(api, "2026-09-01T00:00:00Z")
    tank = fx.commission_tank(api, "T-101", "ETHANOL_200_PROOF", 1000000.00, opening_gallons=0.00)
    contract = fx.priced_contract(api, 458.0, supplier_name="Cedar Ridge Elevator")
    fx.settled_load(api, contract["id"])
    batch = fx.charge_batch(
        api,
        tank["id"],
        batch_code="FB-2001",
        corn_bushels_charged=900.00,
        charge_test_weight_lb_per_bu=54.0,
    )
    first = fx.append_health_reading(
        api, batch["id"], hours_elapsed=12, lactic_acid_ppm=1163,
        acetic_acid_ppm=344, temperature_c=35.4,
    )
    second = fx.append_health_reading(
        api, batch["id"], hours_elapsed=24, lactic_acid_ppm=820,
        acetic_acid_ppm=361, temperature_c=31.8,
    )
    return {"batch": batch, "first": first, "second": second}


def _capped_freight_sale(api):
    """CS-6001: 200.000 tons at 251.00 with freight landing exactly on the cap."""
    plant = fx.commission_plant(
        api,
        base_grind_cap_bushels=120000,
        coverage_floor_bushels=5000,
        baseline_ci_g_per_mj=60.0,
        rin_generation_enabled=True,
    )
    fx.advance_clock(api, "2026-09-01T00:00:00Z")
    fx.post_marks(api, plant["id"])
    sale = fx.quote_flat_sale(
        api,
        sale_code="CS-6001",
        buyer_name="Prairie Dairy Co-op",
        product="DDGS_DRY",
        quantity=200.000,
        quoted_price=251.00,
        freight_rate_per_unit=12.50,
        quote_expires_at="2026-09-10T00:00:00Z",
    )
    return sale


class TestFermentationHealthIndexComposition:
    """Per-reading capping and rounding, then the weighted mean over three readings."""

    def test_each_reading_scores_itself_from_three_capped_penalties(self, api):
        """Every reading persists its own score, rounded before it is ever weighted.

        PRD 3.4: "The `reading_score` is 100 less the three capped penalties,
        clamped into the range 0 through 100, and rounded half up to two
        decimals."

        Design: Difficulty/combinatorial_formula/health_index_per_reading_rounding_beats_weight_then_round
        """
        scenario = _batch_on_two_readings(api)

        assert_2dp(scenario["first"]["reading_score"], 68.07, "reading_score")
        assert_2dp(scenario["second"]["reading_score"], 94.12, "reading_score")

        third = validate_success(
            api.create_health_reading(
                scenario["batch"]["id"],
                {
                    "hours_elapsed": 36,
                    "lactic_acid_ppm": 1237,
                    "acetic_acid_ppm": 552,
                    "temperature_c": 36.9,
                },
                PROCESS_OPERATOR,
            ),
            201,
        )
        assert_2dp(third["reading_score"], 41.89, "reading_score")

    def test_index_weights_the_already_rounded_scores_and_lands_on_health_watch(self, api):
        """Weighting the rounded scores gives 62.80, where the raw scores give 62.79.

        PRD 3.4: "The rounding order here is pinned and load-bearing: weighting
        the unrounded raw scores and rounding only the final mean is a different
        and wrong answer that can differ by one hundredth."

        Design: Difficulty/combinatorial_formula/health_index_per_reading_rounding_beats_weight_then_round
        """
        scenario = _batch_on_two_readings(api)
        fx.append_health_reading(
            api, scenario["batch"]["id"], hours_elapsed=36, lactic_acid_ppm=1237,
            acetic_acid_ppm=552, temperature_c=36.9,
        )

        batch = get_success_data(api.get_batch(scenario["batch"]["id"], PROCESS_OPERATOR))
        assert_2dp(batch["fermentation_health_index"], 62.80, "fermentation_health_index")
        assert batch["fermentation_health_index"] != pytest.approx(62.79, abs=0.001), (
            "weighting the unrounded 68.065 / 94.119 / 41.889 scores would give 62.79"
        )
        assert batch["status"] == "HEALTH_WATCH", batch["status"]


class TestCoProductInvoiceComposition:
    """The four fixed invoice steps over a subtotal sitting exactly on a tier edge."""

    def test_rebate_tier_is_selected_on_the_subtotal_before_any_deduction(self, api):
        """A 50200.00 subtotal earns the high tier even though freight would drop it.

        PRD 3.7: "The rate is 0.0150 when `subtotal_usd` is at least 50000.00;
        failing that, 0.0075 when it is at least 20000.00; otherwise 0.0000."

        Design: Difficulty/combinatorial_formula/co_product_invoice_rebate_tier_keyed_on_subtotal_not_net
        """
        sale = _capped_freight_sale(api)
        accepted = validate_success(
            api.respond_to_sale(sale["id"], {"decision": "ACCEPT"}, GRAIN_BUYER), 200
        )

        assert_2dp(accepted["settlement_price"], 251.00, "settlement_price")
        assert_2dp(accepted["subtotal_usd"], 50200.00, "subtotal_usd")
        assert_2dp(accepted["volume_rebate_usd"], 753.00, "volume_rebate_usd")
        assert_integer_cents(accepted["invoice_amount_cents"], "invoice_amount_cents")
        assert accepted["invoice_amount_cents"] == 4694700, accepted["invoice_amount_cents"]
        assert accepted["invoice_amount_cents"] != 4732350, (
            "keying the tier on the freight-net 47700.00 would drop to the 0.75% tier"
        )

    def test_freight_landing_exactly_on_the_cap_is_charged_in_full(self, api):
        """200.000 tons at 12.50 is exactly 2500.00, and the inclusive cap does not trim it.

        PRD 3.7: "The cap is inclusive, meaning freight computing to exactly
        2500.00 is charged in full at 2500.00 and only amounts above it are
        trimmed."

        Design: Difficulty/combinatorial_formula/co_product_invoice_rebate_tier_keyed_on_subtotal_not_net
        """
        sale = _capped_freight_sale(api)
        accepted = validate_success(
            api.respond_to_sale(sale["id"], {"decision": "ACCEPT"}, GRAIN_BUYER), 200
        )

        assert accepted["status"] == "ACCEPTED", accepted["status"]
        assert_2dp(accepted["freight_usd"], 2500.00, "freight_usd")
        assert accepted["invoice_amount_cents"] == round(
            (accepted["subtotal_usd"] - accepted["volume_rebate_usd"] - accepted["freight_usd"]) * 100
        ), "the invoice must be the subtotal less both the rebate and the freight"
