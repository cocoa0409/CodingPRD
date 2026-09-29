"""Multi-step formulas whose evaluation order is observable in the result.

Three of them: the per-component exposure rounding, the settlement money
waterfall, and the seven-step assembly of warning content.
"""

import pytest

from prd_bench_local_runner.testing import get_success_data

from test_helpers.assertions import (
    assert_assessment_verdict,
    assert_cents,
    assert_exposure,
    assert_margin,
    assert_money_waterfall,
    assert_shares_reconcile,
    assert_status,
    assert_warning_content,
)
from test_helpers.constants import (
    CATEGORY_FOOD,
    CHANNEL_CATALOG,
    CHANNEL_RETAIL,
    DEFAULT_CLOCK,
    DISCLOSURE_VERIFIED,
    METHOD_MODELED,
    OCCUPANCY_ENCLOSED_PARKING_FACILITY,
    REQUIRED_CHANNEL_CATALOG,
    REQUIRED_CHANNEL_LABEL,
    REQUIRED_CHANNEL_POSTED_SIGN,
    RESULT_AT_OR_ABOVE,
    ROUTE_ORAL,
    SETTLEMENT_PROPOSED,
    WARNING_TYPE_OCCUPANCY,
    WARNING_WEBSITE_PLACES,
)
from test_helpers.fixtures import (
    add_component,
    advance_disclosure,
    escalate_notice_to_negotiation,
    link_chemical,
    make_assessment,
    make_benzene,
    make_bpa,
    make_determination,
    make_final_assessment,
    make_material,
    make_notice,
    make_product,
    make_supplier,
    propose_settlement,
    set_clock,
)
from test_helpers.test_users import COMPLIANCE_ANALYST


# ─────────────────────────────────────────────────────────────────────────────
# Setups
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def two_component_product(api):
    """Two materials at 12.345 ppm, each 0.1 g at full contact: raw 1.2345 ug apiece."""
    set_clock(api, DEFAULT_CLOCK)
    chemical = make_bpa(api)
    supplier = make_supplier(api, "Northgate Polymers")
    materials = []
    for code in ("RM-A", "RM-B"):
        material = make_material(api, code, supplier["id"])
        link_chemical(api, material["id"], chemical["id"], 12.345)
        material = advance_disclosure(api, material["id"], DISCLOSURE_VERIFIED)
        materials.append(material)
    product = make_product(
        api, "SKU-CF1", product_name="Blend Cup", annual_units=50000
    )
    for material in materials:
        add_component(api, product["id"], material["id"], 0.1, 1.0)
    return {"chemical": chemical, "materials": materials, "product": product}


@pytest.fixture
def negotiating_notice(api):
    """A notice in SETTLEMENT_NEGOTIATION on a product with no components at all.

    Zero active components means the warranty defence cannot hold, and no cure
    was ever elected, so only a reformulation commitment can mitigate.
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    chemical = make_bpa(api)
    product = make_product(
        api, "SKU-CF2", product_name="Patio Mat", annual_units=500000
    )
    notice = make_notice(
        api,
        product["id"],
        chemical["id"],
        earliest_violation_date="2026-06-01T00:00:00Z",
        served_at="2026-06-01T00:00:00Z",
        noticing_party_name="Coastal Compliance Group",
    )
    notice = escalate_notice_to_negotiation(api, notice["id"])
    set_clock(api, DEFAULT_CLOCK)
    return {"chemical": chemical, "product": product, "notice": notice}


@pytest.fixture
def occupancy_food_product(api):
    """A FOOD product in an enclosed parking facility with a 3.0 square inch label.

    One material carries both a cancer chemical and a reproductive one at
    80.0 ppm, and each has a FINAL oral assessment at 10.000 ug/day.
    """
    set_clock(api, DEFAULT_CLOCK)
    benzene = make_benzene(api)
    bpa = make_bpa(api)
    supplier = make_supplier(api, "Northgate Polymers")
    material = make_material(api, "RM-DUAL", supplier["id"])
    link_chemical(api, material["id"], benzene["id"], 80.0)
    link_chemical(api, material["id"], bpa["id"], 80.0)
    advance_disclosure(api, material["id"], DISCLOSURE_VERIFIED)
    product = make_product(
        api,
        "SKU-CF3",
        product_name="Bulk Snack Bin",
        product_category=CATEGORY_FOOD,
        occupancy_type=OCCUPANCY_ENCLOSED_PARKING_FACILITY,
        distribution_channels=[CHANNEL_RETAIL, CHANNEL_CATALOG],
        label_area_sq_in=3.0,
        annual_units=50000,
    )
    add_component(api, product["id"], material["id"], 0.25, 0.5)
    benzene_assessment = make_final_assessment(
        api, product["id"], benzene["id"], METHOD_MODELED, ROUTE_ORAL, 1.0
    )
    bpa_assessment = make_final_assessment(
        api, product["id"], bpa["id"], METHOD_MODELED, ROUTE_ORAL, 1.0
    )
    return {
        "benzene": benzene,
        "bpa": bpa,
        "material": material,
        "product": product,
        "benzene_assessment": benzene_assessment,
        "bpa_assessment": bpa_assessment,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Daily exposure: round each contribution, then sum, then round
# ─────────────────────────────────────────────────────────────────────────────


class TestExposureRoundingOrder:
    def test_each_contribution_is_rounded_before_the_contributions_are_summed(
        self, api, two_component_product
    ):
        """Two raw 1.2345 ug contributions round to 1.235 each and sum to 2.470 ug/day.

        PRD: "**The order of these two roundings is pinned and is not interchangeable**: each contribution is rounded to three decimals first, the rounded contributions are then summed, and the sum is rounded to three decimals last."

        Design: Difficulty/combinatorial_formula/exposure_rounding_order_pinned_per_component
        """
        bundle = two_component_product
        assessment = make_assessment(
            api,
            bundle["product"]["id"],
            bundle["chemical"]["id"],
            METHOD_MODELED,
            ROUTE_ORAL,
            1.0,
        )
        assert_exposure(assessment["daily_exposure_ug"], 2.470)
        assert assessment["contribution_count"] == 2

    def test_the_sum_then_round_order_would_lose_the_third_decimal(
        self, api, two_component_product
    ):
        """The forbidden order gives 2.469; this system must not produce that figure.

        PRD: "Summing the raw products and rounding once at the end is explicitly not what this system does and produces a different figure whenever two or more components each carry a non-zero fourth decimal — two contributions that each come to 1.2345 before rounding give 2.470 under the pinned order and 2.469 under the forbidden one."

        Design: Difficulty/combinatorial_formula/exposure_rounding_order_pinned_per_component
        """
        bundle = two_component_product
        assessment = make_assessment(
            api,
            bundle["product"]["id"],
            bundle["chemical"]["id"],
            METHOD_MODELED,
            ROUTE_ORAL,
            1.0,
        )
        assert assessment["daily_exposure_ug"] != pytest.approx(2.469, abs=1e-9), (
            "2.469 is the forbidden sum-then-round result"
        )
        assert_exposure(assessment["daily_exposure_ug"], 2.470)

    def test_the_verdict_reads_the_three_decimal_total(
        self, api, two_component_product
    ):
        """2.470 against a 0.5 ug/day safe harbor gives a 4.9400 margin, above the level.

        PRD: "Otherwise `margin_ratio` is `daily_exposure_ug` divided by `safe_harbor_level_ug_per_day`, rounded half up to four decimal places, and `result` is `AT_OR_ABOVE_SAFE_HARBOR` when `daily_exposure_ug` is greater than or equal to the level and `BELOW_SAFE_HARBOR` when it is strictly less."

        Design: Difficulty/combinatorial_formula/exposure_rounding_order_pinned_per_component
        """
        bundle = two_component_product
        assessment = make_assessment(
            api,
            bundle["product"]["id"],
            bundle["chemical"]["id"],
            METHOD_MODELED,
            ROUTE_ORAL,
            1.0,
        )
        assert_assessment_verdict(assessment, 2.470, 4.94, RESULT_AT_OR_ABOVE, 2)


# ─────────────────────────────────────────────────────────────────────────────
# The settlement money waterfall: penalty, then cap, then fees
# ─────────────────────────────────────────────────────────────────────────────


class TestSettlementWaterfallOrder:
    def test_base_penalty_is_the_lesser_of_the_day_and_unit_measures(
        self, api, negotiating_notice
    ):
        """61 days would price 15,250,000 cents; 4000 alleged units caps it at 2,000,000.

        PRD: "Step two computes `base_penalty_cents` as the **lesser** of two statutory measures: a day-based measure of two hundred and fifty thousand cents (2,500 dollars) per day of violation multiplied by `violation_days`, and a unit-based measure of five hundred cents (5 dollars) per unit multiplied by the notice's `alleged_units`."

        Design: Difficulty/combinatorial_formula/settlement_pinned_penalty_then_cap_then_fees
        """
        bundle = negotiating_notice
        settlement = propose_settlement(
            api, bundle["notice"]["id"], 1200000, reformulation_commitment=True
        )
        assert settlement["violation_days"] == 61
        assert_cents(settlement["base_penalty_cents"], 2000000, "base_penalty_cents")
        assert_margin(settlement["mitigation_factor"], 0.75, "mitigation_factor")
        assert_cents(
            settlement["adjusted_penalty_cents"], 1500000, "adjusted_penalty_cents"
        )

    def test_the_fee_cap_tiers_on_the_adjusted_penalty_never_on_the_base(
        self, api, negotiating_notice
    ):
        """1,500,000 adjusted lands in the 0.60 tier: a 900,000 cap, not the base tier's 1,200,000.

        PRD: "Step five computes `fee_cap_cents`, a tiered statutory cap keyed on the **adjusted** penalty and never on the base penalty."

        Design: Difficulty/combinatorial_formula/settlement_pinned_penalty_then_cap_then_fees
        """
        bundle = negotiating_notice
        settlement = propose_settlement(
            api, bundle["notice"]["id"], 1200000, reformulation_commitment=True
        )
        assert_cents(settlement["fee_cap_cents"], 900000, "fee_cap_cents")
        assert settlement["fee_cap_cents"] != 1200000, (
            "Tiering the base penalty rather than the adjusted penalty is wrong"
        )
        assert_cents(settlement["allowed_fees_cents"], 900000, "allowed_fees_cents")

    def test_the_two_shares_partition_the_adjusted_penalty_exactly(
        self, api, negotiating_notice
    ):
        """1,125,000 to the state and 375,000 to the noticing party, plus 900,000 of fees.

        PRD: "`noticing_party_share_cents` is `adjusted_penalty_cents` minus `state_share_cents`, so it absorbs the flooring remainder and the two shares sum to exactly `adjusted_penalty_cents`."

        Design: Difficulty/combinatorial_formula/settlement_pinned_penalty_then_cap_then_fees
        """
        bundle = negotiating_notice
        settlement = propose_settlement(
            api, bundle["notice"]["id"], 1200000, reformulation_commitment=True
        )
        assert_money_waterfall(
            settlement,
            violation_days=61,
            base_penalty_cents=2000000,
            mitigation_factor=0.75,
            adjusted_penalty_cents=1500000,
            fee_cap_cents=900000,
            allowed_fees_cents=900000,
            state_share_cents=1125000,
            noticing_party_share_cents=375000,
            total_settlement_cents=2400000,
        )
        assert_shares_reconcile(settlement)
        assert_status(settlement, SETTLEMENT_PROPOSED)
        assert settlement["round_count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Warning content: seven interacting steps
# ─────────────────────────────────────────────────────────────────────────────

OCCUPANCY_TEXT = (
    "WARNING: Entering this area can expose you to chemicals including Benzene, "
    "Bisphenol A, which are known to the State of California to cause cancer and "
    "birth defects or other reproductive harm. For more information go to "
    "https://www.P65Warnings.ca.gov/places."
)


class TestWarningContentAssembly:
    def test_occupancy_wins_over_the_small_label_short_form(
        self, api, occupancy_food_product
    ):
        """A 3.0 square inch label would take the short form, but the occupancy branch runs first.

        PRD: "The second step selects `warning_type`, which is one of `NONE`, `PRODUCT_SPECIFIC_LONG`, `PRODUCT_SPECIFIC_SHORT` or `OCCUPANCY`, from a three-way branch taken in this order: if the product's `occupancy_type` is anything other than `NONE`, the type is `OCCUPANCY`; otherwise, if the product's `label_area_sq_in` is strictly less than five square inches, the type is `PRODUCT_SPECIFIC_SHORT`, the abbreviated format available to small labels; otherwise the type is `PRODUCT_SPECIFIC_LONG`."

        Design: Difficulty/combinatorial_formula/warning_content_occupancy_precedence_over_food_and_short_form
        """
        bundle = occupancy_food_product
        determination = make_determination(
            api, bundle["product"]["id"], bundle["bpa_assessment"]["id"]
        )
        assert determination["warning_type"] == WARNING_TYPE_OCCUPANCY
        assert determination["covered_channel_count"] == 0

    def test_occupancy_also_defeats_the_food_symbol_carve_out(
        self, api, occupancy_food_product
    ):
        """A FOOD product still needs the symbol once its warning type is OCCUPANCY.

        PRD: "It is false in exactly one situation — the product's `product_category` is `FOOD` **and** the `warning_type` is not `OCCUPANCY` — and true in every other situation."

        Design: Difficulty/combinatorial_formula/warning_content_occupancy_precedence_over_food_and_short_form
        """
        bundle = occupancy_food_product
        determination = make_determination(
            api, bundle["product"]["id"], bundle["bpa_assessment"]["id"]
        )
        assert determination["symbol_required"] is True
        assert determination["website_url"] == WARNING_WEBSITE_PLACES

    def test_the_occupancy_text_and_channel_list_are_assembled_exactly(
        self, api, occupancy_food_product
    ):
        """One name per harm class, the posted sign appended last, and a byte-exact sentence.

        PRD: "The sixth step assembles `warning_text`, and the assembly is byte-exact — including the trailing period on the long and occupancy formats, which the short format does not carry."

        Design: Difficulty/combinatorial_formula/warning_content_occupancy_precedence_over_food_and_short_form
        """
        bundle = occupancy_food_product
        assert_exposure(bundle["benzene_assessment"]["daily_exposure_ug"], 10.0)
        assert_margin(bundle["benzene_assessment"]["margin_ratio"], 1.5625)
        assert_exposure(bundle["bpa_assessment"]["daily_exposure_ug"], 10.0)
        assert_margin(bundle["bpa_assessment"]["margin_ratio"], 20.0)

        determination = make_determination(
            api, bundle["product"]["id"], bundle["bpa_assessment"]["id"]
        )
        assert_warning_content(
            determination,
            warning_type=WARNING_TYPE_OCCUPANCY,
            symbol_required=True,
            named_chemicals=["Benzene", "Bisphenol A"],
            website_url=WARNING_WEBSITE_PLACES,
            warning_text=OCCUPANCY_TEXT,
            required_channels=[
                REQUIRED_CHANNEL_LABEL,
                REQUIRED_CHANNEL_CATALOG,
                REQUIRED_CHANNEL_POSTED_SIGN,
            ],
        )

    def test_the_channel_list_follows_the_pinned_order(
        self, api, occupancy_food_product
    ):
        """RETAIL and CATALOG distribution plus an occupancy give LABEL, CATALOG, POSTED_SIGN.

        PRD: "The seventh step fills `required_channels`, the placement channels this determination must cover, in the pinned order `LABEL`, `CATALOG`, `INTERNET_POS`, `POSTED_SIGN`."

        Design: Difficulty/combinatorial_formula/warning_content_occupancy_precedence_over_food_and_short_form
        """
        bundle = occupancy_food_product
        determination = make_determination(
            api, bundle["product"]["id"], bundle["bpa_assessment"]["id"]
        )
        assert determination["required_channels"] == [
            REQUIRED_CHANNEL_LABEL,
            REQUIRED_CHANNEL_CATALOG,
            REQUIRED_CHANNEL_POSTED_SIGN,
        ]
        stored = get_success_data(
            api.get_determination(determination["id"], COMPLIANCE_ANALYST)
        )
        assert stored["required_channels"] == determination["required_channels"]
