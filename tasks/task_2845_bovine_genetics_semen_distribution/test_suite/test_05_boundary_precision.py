"""Boundaries where one unit of the input decides the outcome."""

import pytest

from test_helpers import (
    ApiErrorId,
    expected_conception_rate,
    factories,
    fixtures as fx,
    validate_error,
    validate_paginated,
)

ANCHOR_PROOF = {
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

SON_TRAITS = {
    "milk_kg": 1100,
    "fat_kg": 45,
    "protein_kg": 36,
    "somatic_cell_score": 2.90,
    "fertility_pct": 2.0,
    "longevity_months": 3.0,
    "reliability_pct": 68,
}


class TestProgenyBlendThresholdAtFiftyDaughters:
    """One daughter either side of 50 on one bull's own two draft proofs."""

    @staticmethod
    def _son_of_a_published_anchor(api):
        anchor = fx.register_sire(
            api,
            registration_code="REG-A",
            birth_date="2020-03-01",
            acquisition_cost_cents=0,
        )
        proof = fx.published_proof(api, anchor["id"], **ANCHOR_PROOF)
        assert proof["composite_index"] == pytest.approx(62.37, abs=0.01)
        son = fx.register_sire(
            api,
            registration_code="REG-C",
            birth_date="2023-05-01",
            sire_id=anchor["id"],
            acquisition_cost_cents=1500000,
        )
        return son

    def test_forty_nine_daughters_stay_on_the_genomic_only_half_weight(self, api):
        """Under `GENOMIC_ONLY`, `parent_average_weight` is fixed at 0.50, so half
        the composite is inherited from the pedigree — the appropriate treatment
        for a young bull with no usable progeny data.

        Design: Difficulty/boundary_precision_check/progeny_blend_threshold_at_forty_nine_versus_fifty_daughters
        """
        son = self._son_of_a_published_anchor(api)

        genomic = fx.file_evaluation(
            api,
            son["id"],
            progeny_daughter_count=49,
            effective_at="2026-08-10T00:00:00Z",
            **SON_TRAITS,
        )
        assert genomic["evaluation_basis"] == "GENOMIC_ONLY"
        assert genomic["parent_average_weight"] == pytest.approx(0.50, abs=0.001)
        assert genomic["production_index"] == pytest.approx(52.90, abs=0.01)
        assert genomic["health_index"] == pytest.approx(65.62, abs=0.01)
        assert genomic["parent_average_index"] == pytest.approx(31.19, abs=0.01)
        assert genomic["composite_index"] == pytest.approx(44.59, abs=0.01)

    def test_the_fiftieth_daughter_switches_the_basis_and_decays_the_weight(self, api):
        """Under `PROGENY_BLENDED`, `parent_average_weight` is 0.50 minus 0.004
        multiplied by the smaller of `progeny_daughter_count` and 100, with the
        result floored at 0.10.

        Design: Difficulty/boundary_precision_check/progeny_blend_threshold_at_forty_nine_versus_fifty_daughters
        """
        son = self._son_of_a_published_anchor(api)
        fx.file_evaluation(
            api,
            son["id"],
            progeny_daughter_count=49,
            effective_at="2026-08-10T00:00:00Z",
            **SON_TRAITS,
        )

        blended = fx.file_evaluation(
            api,
            son["id"],
            progeny_daughter_count=50,
            effective_at="2026-08-15T00:00:00Z",
            **SON_TRAITS,
        )
        assert blended["evaluation_basis"] == "PROGENY_BLENDED"
        assert blended["parent_average_weight"] == pytest.approx(0.30, abs=0.001)
        assert blended["production_index"] == pytest.approx(52.90, abs=0.01)
        assert blended["health_index"] == pytest.approx(65.62, abs=0.01)
        assert blended["parent_average_index"] == pytest.approx(31.19, abs=0.01)
        assert blended["composite_index"] == pytest.approx(49.95, abs=0.01)

        rows, meta = validate_paginated(
            api.list_genomic_evaluations(fx.DIRECTOR, {"sire_id": son["id"]})
        )
        assert meta["total_count"] == 2
        assert all(row["status"] == "DRAFT" for row in rows)


class TestLn2LevelExactlyAtTheServiceDueThreshold:
    """25.0 percent is inclusive, and exactly 0 is a different posture again."""

    THIRTY_FOUR_DAYS = "2026-09-04T00:00:00Z"
    THIRTY_FIVE_DAYS = "2026-09-05T00:00:00Z"
    FORTY_SEVEN_DAYS = "2026-09-17T00:00:00Z"
    FORTY_EIGHT_DAYS = "2026-09-18T00:00:00Z"

    @staticmethod
    def _tank_filled_at_the_epoch(api):
        partner = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-DELTA"},
            tank_overrides={
                "serial": "TK-D",
                "capacity_straws": 500,
                "service_interval_days": 60,
                "initial_fill_pct": 95.0,
            },
        )
        tank = fx.read_tank(api, partner["tank"]["id"])
        assert tank["ln2_level_pct"] == pytest.approx(95.0, abs=0.05)
        assert tank["tank_status"] == "IN_SERVICE"
        assert tank["service_count"] == 0
        return partner

    def test_the_level_falling_to_exactly_twenty_five_is_service_due(self, api):
        """Otherwise, when `ln2_level_pct` is at or below 25.0 — the boundary is
        inclusive — or the logical clock has reached `next_service_due_at`, the
        tank is `SERVICE_DUE`.

        Design: Difficulty/boundary_precision_check/ln2_level_exactly_at_service_due_threshold
        """
        partner = self._tank_filled_at_the_epoch(api)
        tank_id = partner["tank"]["id"]

        fx.advance_clock(api, self.THIRTY_FOUR_DAYS)
        above = fx.read_tank(api, tank_id)
        assert above["ln2_level_pct"] == pytest.approx(27.0, abs=0.05)
        assert above["tank_status"] == "IN_SERVICE"

        sweep = fx.advance_clock(api, self.THIRTY_FIVE_DAYS)
        at_threshold = fx.read_tank(api, tank_id)
        assert at_threshold["ln2_level_pct"] == pytest.approx(25.0, abs=0.05)
        assert at_threshold["tank_status"] == "SERVICE_DUE"
        assert tank_id in sweep["service_due_tank_ids"]
        assert at_threshold["next_service_due_at"] == "2026-09-30T00:00:00.000Z"

    def test_the_level_reaching_exactly_zero_is_out_of_service_until_refilled(self, api):
        """When `ln2_level_pct` is exactly 0 the tank is `OUT_OF_SERVICE`.

        Design: Difficulty/boundary_precision_check/ln2_level_exactly_at_service_due_threshold
        """
        partner = self._tank_filled_at_the_epoch(api)
        tank_id = partner["tank"]["id"]

        fx.advance_clock(api, self.FORTY_SEVEN_DAYS)
        nearly_empty = fx.read_tank(api, tank_id)
        assert nearly_empty["ln2_level_pct"] == pytest.approx(1.0, abs=0.05)
        assert nearly_empty["tank_status"] == "SERVICE_DUE"

        sweep = fx.advance_clock(api, self.FORTY_EIGHT_DAYS)
        empty = fx.read_tank(api, tank_id)
        assert empty["ln2_level_pct"] == pytest.approx(0.0, abs=0.05)
        assert empty["tank_status"] == "OUT_OF_SERVICE"
        assert tank_id in sweep["out_of_service_tank_ids"]

        serviced = fx.service_tank(
            api, tank_id, fill_pct=95.0, headers=partner["distributor_headers"]
        )
        assert serviced["ln2_level_pct"] == pytest.approx(95.0, abs=0.05)
        assert serviced["tank_status"] == "IN_SERVICE"
        assert serviced["last_service_at"] == "2026-09-18T00:00:00.000Z"
        assert serviced["service_count"] == 1


class TestRebateTierAtExactlyFiveHundredThousandCents:
    """The tier is keyed on the subtotal, so the service fee can tip it over."""

    @staticmethod
    def _reconciled_transfer(api, doses):
        context = fx.received_consignment(
            api,
            facility_overrides={
                "code": "F-IA-08",
                "housing_capacity": 2,
                "bench_capacity": 1,
                "approved_export_countries": ["CA"],
            },
            registration_code="REG-B",
            straw_count=300,
            processing_cost_cents=375000,
            distributor_overrides={"name": "D-ECHO", "credit_limit_cents": 100000000},
            tank_overrides={
                "serial": "TK-E",
                "capacity_straws": 500,
                "service_interval_days": 60,
                "initial_fill_pct": 95.0,
            },
            doses=doses,
            unit_price_cents=4000,
        )
        lot = fx.read_lot(api, context["lot"]["id"])
        assert lot["unit_book_value_cents"] == 1250
        assert context["transfer"]["tank_service_count_at_dispatch"] == 0

        serviced = fx.service_tank(
            api,
            context["tank"]["id"],
            fill_pct=99.0,
            headers=context["distributor_headers"],
        )
        assert serviced["service_count"] == 1

        context["transfer"] = fx.report_usage(
            api,
            context["transfer"]["id"],
            context["distributor"]["id"],
            doses_used=doses,
            doses_returned=0,
        )
        return context

    def test_the_service_fee_carries_the_subtotal_onto_the_three_percent_tier(self, api):
        """Step three: the pre-rebate subtotal is `gross_cents` plus
        `service_fee_cents`. Step four: the volume rebate percentage is taken from
        the highest tier whose minimum subtotal is at or below that pre-rebate
        subtotal.

        Design: Difficulty/boundary_precision_check/rebate_tier_at_exact_five_hundred_thousand_cent_subtotal
        """
        context = self._reconciled_transfer(api, 122)
        transfer = context["transfer"]
        assert transfer["status"] == "RECONCILED"
        assert transfer["gross_cents"] == 488000
        assert transfer["service_fee_cents"] == 12000
        assert transfer["rebate_cents"] == 14640
        assert transfer["settlement_total_cents"] == 485360

        distributor = fx.read_distributor(api, context["distributor"]["id"])
        assert distributor["outstanding_balance_cents"] == 485360
        assert distributor["cumulative_doses_used"] == 122

    def test_one_dose_fewer_stays_below_the_boundary_and_earns_no_rebate(self, api):
        """Step five: `rebate_cents` is `gross_cents` multiplied by that
        percentage, rounded half up to whole cents — the rebate applies to the
        goods only and never to the service fee.

        Design: Difficulty/boundary_precision_check/rebate_tier_at_exact_five_hundred_thousand_cent_subtotal
        """
        context = self._reconciled_transfer(api, 121)
        transfer = context["transfer"]
        assert transfer["gross_cents"] == 484000
        assert transfer["service_fee_cents"] == 12000
        assert transfer["rebate_cents"] == 0
        assert transfer["settlement_total_cents"] == 496000

        distributor = fx.read_distributor(api, context["distributor"]["id"])
        assert distributor["outstanding_balance_cents"] == 496000


class TestInbreedingCeilingInclusiveAtSixPointTwoFivePercent:
    """A half-sib mating at exactly the ceiling is admissible; 6.24 empties the pool."""

    DAM_REF = "COW-9001"

    @classmethod
    def _half_sib_pedigree(cls, api):
        anchor = fx.register_sire(
            api,
            registration_code="REG-A",
            birth_date="2020-03-01",
            acquisition_cost_cents=0,
        )
        fx.published_proof(api, anchor["id"], **ANCHOR_PROOF)

        context = fx.released_lot(
            api,
            facility_overrides={
                "code": "F-IA-17",
                "housing_capacity": 2,
                "bench_capacity": 1,
                "approved_export_countries": ["CA"],
            },
            registration_code="REG-C",
            sire_overrides={"birth_date": "2023-05-01", "sire_id": anchor["id"]},
            product_line="CONVENTIONAL",
            straw_count=200,
            processing_cost_cents=250000,
        )
        son_proof = fx.published_proof(
            api,
            context["sire"]["id"],
            progeny_daughter_count=50,
            effective_at="2026-09-01T00:00:00Z",
            **SON_TRAITS,
        )
        assert son_proof["composite_index"] == pytest.approx(49.95, abs=0.01)

        context["anchor"] = anchor
        context["dam_sire"] = fx.register_sire(
            api,
            registration_code="REG-D",
            birth_date="2021-04-01",
            sire_id=anchor["id"],
            acquisition_cost_cents=0,
        )
        distributor = fx.register_distributor(api, name="D-FOX")
        context["distributor"] = distributor
        context["edge_herd"] = fx.register_customer_herd(
            api, distributor["id"], herd_name="H-EDGE", max_inbreeding_pct=6.25
        )
        context["tight_herd"] = fx.register_customer_herd(
            api, distributor["id"], herd_name="H-TIGHT", max_inbreeding_pct=6.24
        )
        return context

    def test_a_half_sib_mating_exactly_at_the_ceiling_is_recommended(self, api):
        """His inbreeding coefficient against the supplied `dam_sire_id` is at
        most the herd's `max_inbreeding_pct`, the boundary being inclusive.

        Design: Difficulty/boundary_precision_check/inbreeding_ceiling_inclusive_at_six_point_two_five_percent
        """
        context = self._half_sib_pedigree(api)

        recommendation = fx.request_recommendation(
            api,
            context["edge_herd"]["id"],
            dam_ref=self.DAM_REF,
            dam_sire_id=context["dam_sire"]["id"],
            requested_product_line="CONVENTIONAL",
            doses_requested=10,
        )
        assert recommendation["inbreeding_pct"] == pytest.approx(6.25, abs=0.01)
        assert recommendation["candidate_pool_size"] == 1
        assert recommendation["recommended_sire_id"] == context["sire"]["id"]
        assert recommendation["straw_lot_id"] == context["lot"]["id"]
        assert recommendation["status"] == "PROPOSED"
        assert recommendation["doses_committed"] == 0
        assert recommendation["expected_conception_rate"] == pytest.approx(
            expected_conception_rate("CONVENTIONAL", 49.95, 55.0, 6.25), abs=0.0001
        )
        assert recommendation["expected_conception_rate"] == pytest.approx(0.3113, abs=0.0001)

    def test_a_ceiling_one_hundredth_lower_empties_the_candidate_pool(self, api):
        """When that count is 0 — whether because of residency, collection status,
        a missing published proof, missing releasable stock of the requested line,
        the exclusion list, base-sire identity or an inbreeding figure above the
        herd's ceiling — the request is refused with `ERR_NO_ELIGIBLE_SIRE` and no
        recommendation row is created at all.

        Design: Difficulty/boundary_precision_check/inbreeding_ceiling_inclusive_at_six_point_two_five_percent
        """
        context = self._half_sib_pedigree(api)
        tight_herd = context["tight_herd"]

        validate_error(
            api.request_mating_recommendation(
                tight_herd["id"],
                factories.mating_recommendation_payload(
                    dam_ref=self.DAM_REF,
                    dam_sire_id=context["dam_sire"]["id"],
                    requested_product_line="CONVENTIONAL",
                    doses_requested=10,
                ),
                fx.ADVISOR,
            ),
            ApiErrorId.ERR_NO_ELIGIBLE_SIRE.value,
            422,
        )

        rows, meta = validate_paginated(
            api.list_mating_recommendations(
                fx.ADVISOR, {"customer_herd_id": tight_herd["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert rows == []
        assert fx.read_herd(api, tight_herd["id"])["recommendation_count"] == 0

        lot = fx.read_lot(api, context["lot"]["id"])
        assert lot["doses_available"] == 200
        assert lot["doses_reserved"] == 0
