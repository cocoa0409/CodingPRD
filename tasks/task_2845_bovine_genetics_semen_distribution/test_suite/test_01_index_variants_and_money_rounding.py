"""Dual-variant genetic scoring, lot valuation bases and the pinned money order."""

import pytest

from test_helpers import (
    assert_buckets,
    assert_settlement,
    expected_settlement,
    fixtures as fx,
)

REG_A_PROOF = {
    "milk_kg": 900,
    "fat_kg": 40,
    "protein_kg": 30,
    "somatic_cell_score": 2.85,
    "fertility_pct": 1.5,
    "longevity_months": 2.0,
    "reliability_pct": 75,
    "progeny_daughter_count": 120,
    "effective_at": "2026-07-01T00:00:00Z",
}

CHILD_TRAITS = {
    "milk_kg": 1100,
    "fat_kg": 45,
    "protein_kg": 36,
    "somatic_cell_score": 2.90,
    "fertility_pct": 2.0,
    "longevity_months": 3.0,
    "reliability_pct": 68,
    "effective_at": "2026-07-15T00:00:00Z",
}


class TestSireIndexVariantBoundary:
    """The daughter-count boundary selects the evaluation basis and the weight."""

    def test_identical_traits_score_differently_under_the_two_bases(self, api):
        """When `progeny_daughter_count` is at least 50, `evaluation_basis` is
        `PROGENY_BLENDED`; when it is 49 or fewer, `evaluation_basis` is
        `GENOMIC_ONLY`.

        Design: Difficulty/dual_variant_calc/sire_index_genomic_only_vs_progeny_blended
        """
        parent = fx.register_sire(
            api,
            registration_code="REG-A",
            birth_date="2020-03-01",
            acquisition_cost_cents=0,
        )
        parent_proof = fx.published_proof(api, parent["id"], **REG_A_PROOF)
        assert parent_proof["composite_index"] == pytest.approx(62.37, abs=0.01)

        blended_bull = fx.register_sire(
            api,
            registration_code="REG-C",
            birth_date="2023-05-01",
            sire_id=parent["id"],
            acquisition_cost_cents=1500000,
        )
        genomic_bull = fx.register_sire(
            api,
            registration_code="REG-D",
            birth_date="2023-05-02",
            sire_id=parent["id"],
            acquisition_cost_cents=1500000,
        )

        blended = fx.file_evaluation(
            api, blended_bull["id"], progeny_daughter_count=50, **CHILD_TRAITS
        )
        genomic = fx.file_evaluation(
            api, genomic_bull["id"], progeny_daughter_count=49, **CHILD_TRAITS
        )

        assert blended["evaluation_basis"] == "PROGENY_BLENDED"
        assert blended["parent_average_weight"] == pytest.approx(0.30, abs=0.01)
        assert blended["parent_average_index"] == pytest.approx(31.19, abs=0.01)
        assert blended["composite_index"] == pytest.approx(49.95, abs=0.01)

        assert genomic["evaluation_basis"] == "GENOMIC_ONLY"
        assert genomic["parent_average_weight"] == pytest.approx(0.50, abs=0.01)
        assert genomic["parent_average_index"] == pytest.approx(31.19, abs=0.01)
        assert genomic["composite_index"] == pytest.approx(44.59, abs=0.01)

        for row in (blended, genomic):
            assert row["production_index"] == pytest.approx(52.90, abs=0.01)
            assert row["health_index"] == pytest.approx(65.62, abs=0.01)

    def test_draft_evaluation_leaves_the_published_snapshot_untouched(self, api):
        """Filing also increments the bull's own `version`, but touches none of
        his published index fields — those move only on publication.

        Design: Difficulty/dual_variant_calc/sire_index_genomic_only_vs_progeny_blended
        """
        parent = fx.register_sire(
            api,
            registration_code="REG-A",
            birth_date="2020-03-01",
            acquisition_cost_cents=0,
        )
        fx.published_proof(api, parent["id"], **REG_A_PROOF)
        child = fx.register_sire(
            api,
            registration_code="REG-C",
            birth_date="2023-05-01",
            sire_id=parent["id"],
            acquisition_cost_cents=1500000,
        )

        draft = fx.file_evaluation(
            api, child["id"], progeny_daughter_count=50, **CHILD_TRAITS
        )
        assert draft["status"] == "DRAFT"

        after = fx.read_sire(api, child["id"])
        assert after["published_composite_index"] == pytest.approx(0.00, abs=0.01)
        assert after["published_production_index"] == pytest.approx(0.00, abs=0.01)
        assert after["published_health_index"] == pytest.approx(0.00, abs=0.01)
        assert after["published_evaluation_effective_at"] is None
        assert after["version"] == child["version"] + 1


def _released_lot_under_a_published_parent(api):
    """A RELEASED CONVENTIONAL lot of 200 straws cut from REG-A's son REG-C."""
    facility = fx.register_facility(
        api,
        code="F-IA-01",
        housing_capacity=4,
        bench_capacity=1,
        approved_export_countries=["CA", "MX"],
    )
    parent = fx.register_sire(
        api,
        registration_code="REG-A",
        birth_date="2020-03-01",
        acquisition_cost_cents=0,
    )
    fx.published_proof(api, parent["id"], **REG_A_PROOF)
    context = fx.released_lot(
        api,
        facility=facility,
        registration_code="REG-C",
        sire_overrides={
            "sire_id": parent["id"],
            "birth_date": "2023-05-01",
            "acquisition_cost_cents": 1500000,
        },
        product_line="CONVENTIONAL",
        straw_count=200,
        processing_cost_cents=250000,
    )
    return context


class TestLotValuationBasisVariant:
    """One physical lot carries two different unit values under the two bases."""

    def test_publication_switches_the_lot_from_standard_cost_to_market(self, api):
        """Its carrying value is struck on the **standard-cost** basis:
        `unit_book_value_cents` is the lot's `processing_cost_cents` divided by
        its `straw_count`, rounded half up to a whole number of cents *per
        straw*, with `valuation_basis` set to `STANDARD_COST` and
        `pre_revaluation_unit_value_cents` left null.

        Design: Difficulty/dual_variant_calc/lot_value_standard_cost_vs_market_revalued
        """
        context = _released_lot_under_a_published_parent(api)
        lot = fx.read_lot(api, context["lot"]["id"])
        assert lot["unit_book_value_cents"] == 1250
        assert lot["valuation_basis"] == "STANDARD_COST"
        assert lot["pre_revaluation_unit_value_cents"] is None

        before = fx.read_valuation(api)
        assert before["plant_inventory_value_cents"] == 250000
        assert before["released_value_cents"] == 250000
        assert before["lot_count"] == 1

        draft = fx.file_evaluation(
            api,
            context["sire"]["id"],
            progeny_daughter_count=50,
            **dict(CHILD_TRAITS, effective_at="2026-08-15T00:00:00Z"),
        )
        assert draft["composite_index"] == pytest.approx(49.95, abs=0.01)
        published = fx.publish_evaluation(api, draft["id"])

        revalued = fx.read_lot(api, context["lot"]["id"])
        assert revalued["unit_book_value_cents"] == 2248
        assert revalued["valuation_basis"] == "MARKET_REVALUED"
        assert revalued["pre_revaluation_unit_value_cents"] == 1250

        after = fx.read_valuation(api)
        assert after["plant_inventory_value_cents"] == 449600
        assert after["released_value_cents"] == 449600
        assert published["revaluation_delta_cents"] == 199600

    def test_revaluation_moves_money_without_moving_a_dose(self, api):
        """The same physical lot therefore carries two different unit values
        before and after a proof update, and the difference flows onward into
        `carried_value_cents` and into each distributor's
        `consignment_value_cents`.

        Design: Difficulty/dual_variant_calc/lot_value_standard_cost_vs_market_revalued
        """
        context = _released_lot_under_a_published_parent(api)
        draft = fx.file_evaluation(
            api,
            context["sire"]["id"],
            progeny_daughter_count=50,
            **dict(CHILD_TRAITS, effective_at="2026-08-15T00:00:00Z"),
        )
        fx.publish_evaluation(api, draft["id"])

        lot = fx.read_lot(api, context["lot"]["id"])
        assert lot["straw_count"] == 200
        assert_buckets(lot, 200, 0, 0, 0, 0)
        assert lot["distribution_status"] == "RELEASED"


ROOT_TRAITS = {
    "milk_kg": 700,
    "fat_kg": 30,
    "protein_kg": 24,
    "somatic_cell_score": 2.95,
    "fertility_pct": 1.0,
    "longevity_months": 1.0,
    "effective_at": "2026-07-01T00:00:00Z",
}


class TestIndexNestedClampsAndWeightDecay:
    """Two nested clamps interact non-linearly on one trait set."""

    def test_reliability_shrink_clamps_at_the_floor_and_at_the_ceiling(self, api):
        """Second, the reliability shrink factor: take `reliability_pct` divided
        by 100, then clamp it to a floor of 0.30 and a ceiling of 0.95 — values
        below the floor become 0.30 and values above the ceiling become 0.95.

        Design: Difficulty/combinatorial_formula/sire_index_nested_clamp_and_paw_decay_nonlinearity
        """
        floored_bull = fx.register_sire(
            api,
            registration_code="REG-E1",
            breed="JERSEY",
            birth_date="2022-01-10",
            acquisition_cost_cents=0,
        )
        capped_bull = fx.register_sire(
            api,
            registration_code="REG-E2",
            breed="JERSEY",
            birth_date="2022-01-11",
            acquisition_cost_cents=0,
        )

        floored = fx.file_evaluation(
            api,
            floored_bull["id"],
            reliability_pct=20,
            progeny_daughter_count=0,
            **ROOT_TRAITS,
        )
        capped = fx.file_evaluation(
            api,
            capped_bull["id"],
            reliability_pct=98,
            progeny_daughter_count=100,
            **ROOT_TRAITS,
        )

        assert floored["production_index"] == pytest.approx(15.36, abs=0.01)
        assert floored["health_index"] == pytest.approx(14.25, abs=0.01)
        assert floored["composite_index"] == pytest.approx(7.46, abs=0.01)
        assert floored["parent_average_weight"] == pytest.approx(0.50, abs=0.01)
        assert floored["evaluation_basis"] == "GENOMIC_ONLY"

        assert capped["production_index"] == pytest.approx(48.64, abs=0.01)
        assert capped["health_index"] == pytest.approx(45.13, abs=0.01)
        assert capped["composite_index"] == pytest.approx(42.51, abs=0.01)

    def test_daughter_count_is_capped_at_one_hundred_for_weighting(self, api):
        """Under `PROGENY_BLENDED`, `parent_average_weight` is 0.50 minus 0.004
        multiplied by the smaller of `progeny_daughter_count` and 100, with the
        result floored at 0.10.

        Design: Difficulty/combinatorial_formula/sire_index_nested_clamp_and_paw_decay_nonlinearity
        """
        at_cap_bull = fx.register_sire(
            api,
            registration_code="REG-E2",
            breed="JERSEY",
            birth_date="2022-01-11",
            acquisition_cost_cents=0,
        )
        beyond_cap_bull = fx.register_sire(
            api,
            registration_code="REG-E3",
            breed="JERSEY",
            birth_date="2022-01-12",
            acquisition_cost_cents=0,
        )

        at_cap = fx.file_evaluation(
            api,
            at_cap_bull["id"],
            reliability_pct=98,
            progeny_daughter_count=100,
            **ROOT_TRAITS,
        )
        beyond_cap = fx.file_evaluation(
            api,
            beyond_cap_bull["id"],
            reliability_pct=98,
            progeny_daughter_count=200,
            **ROOT_TRAITS,
        )

        assert at_cap["parent_average_weight"] == pytest.approx(0.10, abs=0.01)
        assert beyond_cap["parent_average_weight"] == pytest.approx(0.10, abs=0.01)
        assert at_cap["composite_index"] == pytest.approx(42.51, abs=0.01)
        assert beyond_cap["composite_index"] == at_cap["composite_index"]
        assert beyond_cap["evaluation_basis"] == "PROGENY_BLENDED"


class TestPerStrawRoundingOrder:
    """The per-straw rounding order is visible one cent at a time."""

    def test_unit_value_rounds_per_straw_before_it_is_multiplied(self, api):
        """Second, a lot's carrying value is rounded to whole cents *per straw*
        first, and any lot-level figure is that already-rounded per-straw value
        multiplied by a dose count; summing an unrounded total and rounding at
        the end is wrong here.

        Design: Difficulty/combinatorial_formula/lot_value_rounds_per_straw_before_multiplying
        """
        context = fx.quarantine_lot(
            api,
            facility_overrides={
                "code": "F-IA-02",
                "housing_capacity": 2,
                "bench_capacity": 1,
                "approved_export_countries": ["CA"],
            },
            registration_code="REG-B",
            sire_overrides={
                "breed": "ANGUS",
                "birth_date": "2022-06-01",
                "acquisition_cost_cents": 900000,
            },
            product_line="CONVENTIONAL",
            straw_count=3,
            processing_cost_cents=100000,
        )
        lot = fx.read_lot(api, context["lot"]["id"])
        assert lot["unit_book_value_cents"] == 33333
        assert lot["valuation_basis"] == "STANDARD_COST"

        valuation = fx.read_valuation(api)
        assert valuation["plant_inventory_value_cents"] == 99999
        assert valuation["quarantine_value_cents"] == 99999
        assert valuation["released_value_cents"] == 0
        assert valuation["lot_count"] == 1

    def test_theoretical_dose_yield_is_floored_on_the_ejaculate(self, api):
        """Its `total_doses_theoretical` is the volume in millilitres multiplied
        by the concentration in millions per millilitre, divided by the 15
        million sperm cells that make up one insemination dose, with the
        quotient floored to a whole number of doses.

        Design: Difficulty/combinatorial_formula/lot_value_rounds_per_straw_before_multiplying
        """
        context = fx.accepted_ejaculate(
            api,
            registration_code="REG-B",
            sire_overrides={
                "breed": "ANGUS",
                "birth_date": "2022-06-01",
                "acquisition_cost_cents": 900000,
            },
            volume_ml=6.0,
            concentration_m_per_ml=1200,
        )
        ejaculate = fx.read_ejaculate(api, context["ejaculate"]["id"])
        assert ejaculate["total_doses_theoretical"] == 480
        assert ejaculate["qc_status"] == "ACCEPTED"


class TestSettlementRebateKeying:
    """The rebate tier is keyed on a subtotal that already carries the fee."""

    @staticmethod
    def _reconciled_consignment(api):
        context = fx.received_consignment(
            api,
            doses=150,
            unit_price_cents=4000,
            distributor_overrides={
                "name": "D-US",
                "country_code": "US",
                "credit_limit_cents": 100000000,
                "consignment_enabled": True,
            },
            tank_overrides={
                "serial": "TK-1",
                "capacity_straws": 500,
                "service_interval_days": 60,
                "initial_fill_pct": 95.0,
            },
            facility_overrides={
                "code": "F-IA-03",
                "housing_capacity": 2,
                "bench_capacity": 1,
                "approved_export_countries": ["CA"],
            },
            registration_code="REG-B",
            sire_overrides={
                "breed": "ANGUS",
                "birth_date": "2022-06-01",
                "acquisition_cost_cents": 900000,
            },
            product_line="CONVENTIONAL",
            straw_count=200,
            processing_cost_cents=250000,
        )
        assert context["transfer"]["tank_service_count_at_dispatch"] == 0
        fx.service_tank(
            api,
            context["tank"]["id"],
            fill_pct=99.0,
            headers=context["distributor_headers"],
        )
        context["transfer"] = fx.report_usage(
            api,
            context["transfer"]["id"],
            context["distributor"]["id"],
            doses_used=122,
            doses_returned=28,
        )
        return context

    def test_rebate_tier_reads_the_pre_rebate_subtotal_not_the_gross(self, api):
        """Step four: the volume rebate percentage is taken from the highest tier
        whose minimum subtotal is at or below that pre-rebate subtotal, where the
        tiers are 0 percent from a subtotal of 0, 3 percent from a subtotal of
        500000 cents, and 6 percent from a subtotal of 1500000 cents, each
        boundary inclusive.

        Design: Difficulty/combinatorial_formula/settlement_rebate_tier_keyed_on_pre_rebate_subtotal
        """
        context = self._reconciled_consignment(api)
        transfer = context["transfer"]
        assert transfer["status"] == "RECONCILED"
        assert_settlement(transfer, expected_settlement(122, 4000, 1))
        assert transfer["gross_cents"] == 488000
        assert transfer["service_fee_cents"] == 12000
        assert transfer["rebate_cents"] == 14640
        assert transfer["settlement_total_cents"] == 485360

        tank = fx.read_tank(api, context["tank"]["id"])
        assert tank["service_count"] == 1
        assert transfer["tank_service_count_at_dispatch"] == 0

    def test_reconciliation_moves_exposure_and_conserves_the_dose_ledger(self, api):
        """`outstanding_balance_cents` is the sum of `settlement_total_cents`
        over the partner's consignments whose `status` is `RECONCILED`, and
        `cumulative_doses_used` is the sum of `doses_used` over those same
        reconciled rows.

        Design: Difficulty/combinatorial_formula/settlement_rebate_tier_keyed_on_pre_rebate_subtotal
        """
        context = self._reconciled_consignment(api)
        distributor = fx.read_distributor(api, context["distributor"]["id"])
        assert distributor["outstanding_balance_cents"] == 485360
        assert distributor["cumulative_doses_used"] == 122
        assert distributor["consignment_value_cents"] == 0

        lot = fx.read_lot(api, context["lot"]["id"])
        assert_buckets(lot, 78, 0, 0, 122, 0)
