"""
Two-variant reporting: the crush margin's mark-to-market and realized views,
and the co-product settlement price under a flat quote versus an index restrike.
"""

import pytest

from test_helpers import fixtures as fx
from test_helpers import get_success_data, validate_success
from test_helpers.assertions import (
    assert_2dp,
    assert_3dp,
    assert_null,
    assert_integer_cents,
)
from test_helpers.test_users import (
    GRAIN_BUYER,
    LOGISTICS_COORDINATOR,
    PLANT_MANAGER,
    PROCESS_OPERATOR,
    RISK_MANAGER,
)

CONVERSION_COST = 32.50
NATGAS_COST = 21.26


def _margin_scenario(api):
    """
    One plant month carried all the way through: a discounted settled load, a
    completed 90000.00-bushel batch, an invoiced unit train and a shipped index
    DDGS sale, with the soybean meal mark restored to 330.00 at the end.
    """
    plant = fx.commission_plant(
        api,
        base_grind_cap_bushels=120000,
        coverage_floor_bushels=5000,
        baseline_ci_g_per_mj=60.0,
        rin_generation_enabled=True,
    )
    fx.advance_clock(api, "2026-09-01T00:00:00Z")
    fx.post_marks(api, plant["id"])

    neat = fx.commission_tank(api, "T-101", "ETHANOL_200_PROOF", 1000000.00, opening_gallons=0.00)
    denaturant = fx.commission_tank(
        api, "T-201", "DENATURANT", 600000.00, opening_gallons=500000.00
    )
    e100 = fx.commission_tank(
        api,
        "T-301",
        "DENATURED_E100",
        1000000.00,
        opening_gallons=0.00,
        settling_buffer_minutes=120,
    )

    contract = fx.priced_contract(api, 458.0, bushels_contracted=200000.00)
    delivery = fx.book_delivery(
        api, contract["id"], gross_weight_lbs=5500000, tare_weight_lbs=300000.00
    )
    fx.grade_delivery(
        api,
        delivery["id"],
        moisture_pct=16.50,
        test_weight_lb_per_bu=53.2,
        foreign_material_pct=3.40,
        damaged_kernels_pct=6.00,
        aflatoxin_ppb=4,
    )
    settled = fx.settle_delivery(api, delivery["id"])

    fx.advance_clock(api, "2026-09-03T00:00:00Z")
    batch = fx.charge_batch(
        api,
        neat["id"],
        batch_code="FB-1001",
        corn_bushels_charged=90000.00,
        charge_test_weight_lb_per_bu=56.5,
    )
    fx.append_health_reading(api, batch["id"])
    get_success_data(api.distill_batch(batch["id"], PROCESS_OPERATOR))
    completed = get_success_data(api.complete_batch(batch["id"], PROCESS_OPERATOR))

    fx.advance_clock(api, "2026-09-04T06:00:00Z")
    e100_now = get_success_data(api.get_tank(e100["id"], PROCESS_OPERATOR))
    fx.executed_blend(
        api,
        neat["id"],
        denaturant["id"],
        e100["id"],
        e100_now["version"],
        blend_code="BL-2001",
        neat_gallons=259920.00,
        denaturant_gallons=5990.00,
        window_start="2026-09-04T08:00:00Z",
        window_end="2026-09-04T12:00:00Z",
    )

    track = fx.commission_track(api, loading_rate_cars_per_hour=20.0, is_active=True)
    fx.advance_clock(api, "2026-09-05T05:00:00Z")
    shipment = fx.invoiced_shipment(
        api,
        track["id"],
        e100["id"],
        track["version"],
        shipment_code="UT-3001",
        railcar_count=100,
        gallons_per_railcar=2659.00,
        window_start="2026-09-05T06:00:00Z",
        window_end="2026-09-05T12:00:00Z",
        price_cents_per_gallon=181.50,
    )

    sale = fx.quote_index_sale(
        api,
        sale_code="CS-4001",
        buyer_name="Heartland Feeds",
        product="DDGS_DRY",
        quantity=750.000,
        index_pct=0.92,
        freight_rate_per_unit=3.25,
        quote_expires_at="2026-09-10T00:00:00Z",
    )
    fx.post_marks(api, plant["id"], RISK_MANAGER, mark_soybean_meal_usd_per_ton=362.50)
    fx.accept_sale(api, sale["id"])
    fx.shipped_sale(api, sale["id"])
    fx.post_marks(api, plant["id"], PLANT_MANAGER, mark_soybean_meal_usd_per_ton=330.00)

    return {
        "plant": plant,
        "delivery": settled,
        "batch": completed,
        "shipment": shipment,
        "sale": sale,
    }


def _collar_scenario(api):
    """
    Two 750.000-ton DDGS_DRY quotes that both carry a quoted price of 303.60 —
    one struck FLAT by the buyer, one struck by the system off a 330.00 soybean
    meal mark — answered only after the mark has rallied to 362.50.
    """
    plant = fx.commission_plant(
        api,
        base_grind_cap_bushels=120000,
        coverage_floor_bushels=5000,
        baseline_ci_g_per_mj=60.0,
        rin_generation_enabled=True,
    )
    fx.advance_clock(api, "2026-09-01T00:00:00Z")
    fx.post_marks(api, plant["id"])

    flat = fx.quote_flat_sale(
        api,
        sale_code="CS-5001",
        buyer_name="Heartland Feeds",
        product="DDGS_DRY",
        quantity=750.000,
        quoted_price=303.60,
        freight_rate_per_unit=3.25,
        quote_expires_at="2026-09-10T00:00:00Z",
    )
    index = fx.quote_index_sale(
        api,
        sale_code="CS-5002",
        buyer_name="Heartland Feeds",
        product="DDGS_DRY",
        quantity=750.000,
        index_pct=0.92,
        freight_rate_per_unit=3.25,
        quote_expires_at="2026-09-10T00:00:00Z",
    )
    fx.post_marks(api, plant["id"], RISK_MANAGER, mark_soybean_meal_usd_per_ton=362.50)
    return {"plant": plant, "flat": flat, "index": index}


class TestCrushMarginVariants:
    """The two crush-margin variants over one identical plant month."""

    def test_mark_to_market_leg_prices_every_revenue_stream_at_the_posted_marks(self, api):
        """The forward view values ethanol, distillers grains and corn oil at the marks.

        PRD 3.9: "Its ethanol leg is `mark_ethanol_cents_per_gallon` multiplied
        by the plant's `rolling_yield_gal_per_bushel`."
        PRD 3.9: "Its corn cost is `mark_corn_cents_per_bushel` exactly as
        posted — the futures mark, ignoring what the plant actually paid."

        Design: Difficulty/dual_variant_calc/crush_margin_mark_to_market_vs_realized_diverge_on_same_month
        """
        scenario = _margin_scenario(api)
        margin = validate_success(
            api.get_crush_margin(scenario["plant"]["id"], RISK_MANAGER), 200
        )
        mtm = margin["mark_to_market"]

        assert_2dp(mtm["ethanol_cents_per_bushel"], 514.06, "mark_to_market.ethanol_cents_per_bushel")
        assert_2dp(mtm["ddgs_cents_per_bushel"], 258.06, "mark_to_market.ddgs_cents_per_bushel")
        assert_2dp(mtm["corn_oil_cents_per_bushel"], 22.46, "mark_to_market.corn_oil_cents_per_bushel")
        assert_2dp(mtm["gross_cents_per_bushel"], 794.58, "mark_to_market.gross_cents_per_bushel")
        assert_2dp(mtm["corn_cost_cents_per_bushel"], 440.00, "mark_to_market.corn_cost_cents_per_bushel")
        assert_2dp(mtm["net_cents_per_bushel"], 300.82, "mark_to_market.net_cents_per_bushel")
        assert mtm["gross_cents_per_bushel"] - mtm["corn_cost_cents_per_bushel"] - NATGAS_COST - CONVERSION_COST == pytest.approx(
            mtm["net_cents_per_bushel"], abs=0.01
        ), "the mark-to-market net must be the gross less corn, natural gas and conversion"

    def test_realized_leg_prices_corn_at_the_volume_weighted_settled_price(self, api):
        """The backward view reads only invoiced and shipped history, at actual prices.

        PRD 3.9: "Its ethanol leg is the sum of `invoice_amount_cents` over
        shipments whose `billing_status` is `INVOICED`, divided by those
        bushels."

        Design: Difficulty/dual_variant_calc/crush_margin_mark_to_market_vs_realized_diverge_on_same_month
        """
        scenario = _margin_scenario(api)
        margin = validate_success(
            api.get_crush_margin(scenario["plant"]["id"], RISK_MANAGER), 200
        )
        realized = margin["realized"]

        assert_2dp(realized["ethanol_cents_per_bushel"], 536.23, "realized.ethanol_cents_per_bushel")
        assert_2dp(realized["coproduct_cents_per_bushel"], 265.19, "realized.coproduct_cents_per_bushel")
        assert_2dp(realized["corn_cost_cents_per_bushel"], 411.20, "realized.corn_cost_cents_per_bushel")
        assert_2dp(realized["net_cents_per_bushel"], 336.46, "realized.net_cents_per_bushel")
        assert realized["corn_cost_cents_per_bushel"] != pytest.approx(440.00, abs=0.005), (
            "the realized corn cost must carry the quality discounts, not the futures mark"
        )

    def test_both_variants_and_their_delta_arrive_in_the_same_response(self, api):
        """One GET reports the forward view, the backward view and the gap between them.

        PRD 3.9: "The response names the plant's `rolling_yield`, the two shared
        cost legs, a `mark_to_market` object carrying `ethanol_cents_per_bushel`,
        `ddgs_cents_per_bushel`, `corn_oil_cents_per_bushel`,
        `corn_cost_cents_per_bushel`, `gross_cents_per_bushel` and
        `net_cents_per_bushel`, a `realized` object carrying
        `ethanol_cents_per_bushel`, `coproduct_cents_per_bushel`,
        `corn_cost_cents_per_bushel` and `net_cents_per_bushel`, and finally
        `variant_delta_cents_per_bushel`, which is the realized net figure less
        the mark-to-market net figure, rounded half up to two decimals — a
        positive delta meaning the plant has done better than the marks suggest."

        Design: Difficulty/dual_variant_calc/crush_margin_mark_to_market_vs_realized_diverge_on_same_month
        """
        scenario = _margin_scenario(api)
        margin = validate_success(
            api.get_crush_margin(scenario["plant"]["id"], RISK_MANAGER), 200
        )

        assert_3dp(margin["rolling_yield"], 2.888, "rolling_yield")
        assert_2dp(margin["variant_delta_cents_per_bushel"], 35.64, "variant_delta_cents_per_bushel")
        assert margin["variant_delta_cents_per_bushel"] == pytest.approx(
            margin["realized"]["net_cents_per_bushel"]
            - margin["mark_to_market"]["net_cents_per_bushel"],
            abs=0.01,
        ), "the delta must be the realized net less the mark-to-market net"

        plant = fx.read_plant(api, scenario["plant"]["id"])
        assert_3dp(plant["rolling_yield_gal_per_bushel"], 2.888, "rolling_yield_gal_per_bushel")


class TestCoProductSettlementBasisVariants:
    """Two identical 303.60 quotes, one FLAT and one INDEX, answered after a rally."""

    def test_flat_quote_ignores_the_rally_and_settles_at_its_stored_quoted_price(self, api):
        """A FLAT acceptance never restrikes and never publishes collar bounds.

        PRD 3.7: "For a `FLAT` sale the `settlement_price` is simply the stored
        `quoted_price` and both `collar_floor` and `collar_ceiling` remain null."
        PRD 3.7: "A `FLAT` sale leaves `quote_reference_mark` null."

        Design: Difficulty/dual_variant_calc/co_product_settlement_price_collar_diverges_from_quote_basis
        """
        scenario = _collar_scenario(api)
        accepted = validate_success(
            api.respond_to_sale(scenario["flat"]["id"], {"decision": "ACCEPT"}, GRAIN_BUYER),
            200,
        )

        assert accepted["status"] == "ACCEPTED", accepted["status"]
        assert_2dp(accepted["settlement_price"], 303.60, "settlement_price")
        assert_null(accepted["collar_floor"], "collar_floor")
        assert_null(accepted["collar_ceiling"], "collar_ceiling")
        assert_null(accepted["quote_reference_mark"], "quote_reference_mark")
        assert_2dp(accepted["subtotal_usd"], 227700.00, "subtotal_usd")
        assert_2dp(accepted["volume_rebate_usd"], 3415.50, "volume_rebate_usd")
        assert_2dp(accepted["freight_usd"], 2437.50, "freight_usd")
        assert_integer_cents(accepted["invoice_amount_cents"], "invoice_amount_cents")
        assert accepted["invoice_amount_cents"] == 22184700, accepted["invoice_amount_cents"]

    def test_index_restrike_is_clamped_to_a_ceiling_anchored_on_the_original_quote(self, api):
        """The rallied mark restrikes to 333.50 but settles at the 326.37 ceiling.

        PRD 3.7: "That restruck figure is then clamped into a symmetric band of
        seven and a half percent computed **from the original `quoted_price`,
        never from the restruck price** — `collar_floor` is `quoted_price`
        multiplied by 0.925 rounded half up to two decimals, and
        `collar_ceiling` is `quoted_price` multiplied by 1.075 rounded half up
        to two decimals."

        Design: Difficulty/dual_variant_calc/co_product_settlement_price_collar_diverges_from_quote_basis
        """
        scenario = _collar_scenario(api)
        assert_2dp(scenario["index"]["quoted_price"], 303.60, "quoted_price")
        assert_2dp(scenario["index"]["quote_reference_mark"], 330.00, "quote_reference_mark")

        flat = fx.accept_sale(api, scenario["flat"]["id"])
        index = validate_success(
            api.respond_to_sale(scenario["index"]["id"], {"decision": "ACCEPT"}, GRAIN_BUYER),
            200,
        )

        assert index["status"] == "ACCEPTED", index["status"]
        assert_2dp(index["collar_floor"], 280.83, "collar_floor")
        assert_2dp(index["collar_ceiling"], 326.37, "collar_ceiling")
        assert_2dp(index["settlement_price"], 326.37, "settlement_price")
        assert index["settlement_price"] != pytest.approx(333.50, abs=0.005), (
            "the unclamped restrike of 362.50 x 0.92 must not survive the collar"
        )
        assert_2dp(index["subtotal_usd"], 244777.50, "subtotal_usd")
        assert_2dp(index["volume_rebate_usd"], 3671.66, "volume_rebate_usd")
        assert index["invoice_amount_cents"] == 23866834, index["invoice_amount_cents"]
        assert index["invoice_amount_cents"] - flat["invoice_amount_cents"] == 1682134, (
            "the two bases must diverge by exactly 1682134 cents on identical tonnage"
        )
