"""Derived figures: the genetic index, lot valuation, LN2 decay, settlement and matings."""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_buckets,
    assert_instant_equals,
    assert_settlement,
    expected_composite_index,
    expected_conception_rate,
    expected_health_index,
    expected_ln2_level_pct,
    expected_market_unit_value_cents,
    expected_production_index,
    expected_settlement,
    expected_standard_unit_value_cents,
    expected_theoretical_doses,
    VET_ALT_USER_ID,
    factories,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

# The payload whose every constant is exercised at once: three production
# weights, three health terms, the reliability shrink and the genomic-only
# blend, with both pedigree parents absent.
SCORED_TRAITS = {
    "milk_kg": 1000,
    "fat_kg": 40,
    "protein_kg": 30,
    "somatic_cell_score": 2.95,
    "fertility_pct": 1.5,
    "longevity_months": 2.0,
    "reliability_pct": 80,
    "progeny_daughter_count": 0,
}

# Both sub-indices land exactly on a half-cent boundary.
HALF_CENT_TRAITS = {
    "milk_kg": 1000.5,
    "fat_kg": 100,
    "protein_kg": 0,
    "somatic_cell_score": 2.95,
    "fertility_pct": 3.0,
    "longevity_months": 1.34,
    "reliability_pct": 50,
    "progeny_daughter_count": 0,
}

# The trailing-zero case: every reported figure still carries two decimals.
TRAILING_ZERO_TRAITS = {
    "milk_kg": 1000,
    "fat_kg": 40,
    "protein_kg": 20,
    "somatic_cell_score": 2.90,
    "fertility_pct": 0,
    "longevity_months": 0,
    "reliability_pct": 50,
    "progeny_daughter_count": 0,
}


class TestSireIndexWeightedScoring:
    """One trait payload through all six pinned scoring steps."""

    def test_the_six_pinned_steps_produce_the_composite(self, api):
        """Sixth, the blend. `composite_index` is one minus
        `parent_average_weight`, multiplied by the quantity (0.60 multiplied by
        `production_index` plus 0.40 multiplied by `health_index`), plus
        `parent_average_weight` multiplied by `parent_average_index`, with the
        whole result rounded half up to two decimal places.

        Design: Corner/calculations/sire_index_weighted_scoring_computes_subindices_and_blend
        """
        bull = fx.register_sire(
            api,
            registration_code="REG-CALC1",
            breed="HOLSTEIN",
            birth_date="2022-01-10",
            acquisition_cost_cents=900000,
        )
        assert bull["version"] == 1
        assert bull["pedigree_depth"] == 0

        proof = fx.file_evaluation(
            api,
            bull["id"],
            effective_at="2026-07-01T00:00:00Z",
            **SCORED_TRAITS,
        )

        # production_raw = 0.02*1000 + 0.60*40 + 0.80*30 = 68.00, shrink 0.80
        assert proof["production_index"] == pytest.approx(54.40, abs=0.001)
        assert proof["production_index"] == pytest.approx(
            expected_production_index(1000, 40, 30, 80), abs=0.001
        )
        # health_raw = 8.0*(3.00-2.95)*100 + 6.0*1.5 + 1.5*2.0 = 52.00
        assert proof["health_index"] == pytest.approx(41.60, abs=0.001)
        assert proof["health_index"] == pytest.approx(
            expected_health_index(2.95, 1.5, 2.0, 80), abs=0.001
        )
        assert proof["evaluation_basis"] == "GENOMIC_ONLY"
        assert proof["parent_average_weight"] == pytest.approx(0.50, abs=0.001)
        # Both parents null: each contributes 0.00 over a divisor that stays 2.
        assert proof["parent_average_index"] == pytest.approx(0.00, abs=0.001)
        assert proof["composite_index"] == pytest.approx(24.64, abs=0.001)
        assert proof["composite_index"] == pytest.approx(
            expected_composite_index(54.40, 41.60, 0.00, 0.50), abs=0.001
        )

        assert proof["status"] == "DRAFT"
        assert proof["revaluation_delta_cents"] == 0
        assert proof["published_at"] is None
        assert proof["supersedes_evaluation_id"] is None

        # Filing increments the bull's own version but moves no published field.
        after = fx.read_sire(api, bull["id"])
        assert after["version"] == 2
        assert after["published_composite_index"] == pytest.approx(0.00, abs=0.001)
        assert after["published_evaluation_effective_at"] is None


class TestSireIndexRoundsSubIndicesBeforeBlending:
    """The rounding order is observable: 18.01, never 18.00."""

    def test_the_blend_reads_the_already_rounded_sub_indices(self, api):
        """Third, and this is the pinned rounding order, `production_index` is
        the production aggregate multiplied by the shrink factor rounded half up
        to two decimal places, and `health_index` is the health aggregate
        multiplied by the shrink factor rounded half up to two decimal places;
        the composite is later computed from these **already-rounded**
        sub-indices, never from the unrounded products.

        Design: Corner/calculations/sire_index_rounds_subindices_before_blending
        """
        bull = fx.register_sire(
            api,
            registration_code="REG-CALC2",
            breed="JERSEY",
            birth_date="2022-03-03",
            acquisition_cost_cents=500000,
        )

        proof = fx.file_evaluation(
            api,
            bull["id"],
            effective_at="2026-07-01T00:00:00Z",
            **HALF_CENT_TRAITS,
        )

        # 0.02*1000.5 + 0.60*100 + 0.80*0 = 80.01; 80.01 * 0.50 = 40.005 exactly.
        assert proof["production_index"] == pytest.approx(40.01, abs=0.001)
        # 8.0*(3.00-2.95)*100 + 6.0*3.0 + 1.5*1.34 = 60.01; halved = 30.005.
        assert proof["health_index"] == pytest.approx(30.01, abs=0.001)
        # 0.50 * (0.60*40.01 + 0.40*30.01) = 18.005 -> 18.01.  Blending the
        # unrounded 40.005 and 30.005 instead gives 18.0025 -> 18.00.
        assert proof["composite_index"] == pytest.approx(18.01, abs=0.001)
        assert proof["composite_index"] != pytest.approx(18.00, abs=0.001)
        assert proof["composite_index"] == pytest.approx(
            expected_composite_index(40.01, 30.01, 0.00, 0.50), abs=0.001
        )

    def test_a_trailing_zero_figure_is_still_carried_to_two_decimals(self, api):
        """Two-decimal, round-half-up precision governs `production_index`,
        `health_index`, `parent_average_index`, `composite_index`, the published
        index snapshots on a bull, and the inbreeding percentage.

        Design: Corner/calculations/sire_index_rounds_subindices_before_blending
        """
        bull = fx.register_sire(
            api,
            registration_code="REG-CALC2",
            breed="JERSEY",
            birth_date="2022-03-03",
            acquisition_cost_cents=500000,
        )

        proof = fx.file_evaluation(
            api,
            bull["id"],
            effective_at="2026-07-01T00:00:00Z",
            **TRAILING_ZERO_TRAITS,
        )

        # 0.02*1000 + 0.60*40 + 0.80*20 = 60.00, halved by the 0.50 shrink.
        assert proof["production_index"] == pytest.approx(30.00, abs=0.001)
        # 8.0*(3.00-2.90)*100 = 80.00 with both remaining terms at 0.
        assert proof["health_index"] == pytest.approx(40.00, abs=0.001)
        assert proof["composite_index"] == pytest.approx(17.00, abs=0.001)
        assert proof["composite_index"] == pytest.approx(
            expected_composite_index(30.00, 40.00, 0.00, 0.50), abs=0.001
        )


class TestMarketRevaluationAppliesMultiplierPurityAndFloor:
    """One publication values four lines of the same bull's stock."""

    STRONG_EFFECTIVE_AT = "2026-07-01T00:00:00Z"
    WEAK_EFFECTIVE_AT = "2026-07-15T00:00:00Z"

    @classmethod
    def _four_lots_and_two_drafts(cls, api):
        context = fx.accepted_ejaculate(
            api,
            facility_overrides={
                "code": "F-CALC-03",
                "housing_capacity": 2,
                "bench_capacity": 1,
            },
            registration_code="REG-CALC3",
        )
        assert context["ejaculate"]["total_doses_theoretical"] == 480
        ejaculate_id = context["ejaculate"]["id"]

        context["lots"] = {
            "CONVENTIONAL": fx.cut_lot(api, ejaculate_id, "CONVENTIONAL", 100, 250000),
            "SEXED_90": fx.cut_lot(
                api, ejaculate_id, "SEXED", 100, 250000, sexing_purity_pct=90.0
            ),
            "SEXED_72": fx.cut_lot(
                api, ejaculate_id, "SEXED", 100, 250000, sexing_purity_pct=72.0
            ),
            "EMBRYO": fx.cut_lot(api, ejaculate_id, "EMBRYO", 100, 250000),
        }
        for lot in context["lots"].values():
            assert lot["unit_book_value_cents"] == expected_standard_unit_value_cents(
                250000, 100
            )
            assert lot["unit_book_value_cents"] == 2500
            assert lot["valuation_basis"] == "STANDARD_COST"
            assert lot["pre_revaluation_unit_value_cents"] is None
            assert lot["distribution_status"] == "QUARANTINE"
        assert fx.plant_value(api) == 1000000

        sire_id = context["sire"]["id"]
        context["strong"] = fx.file_evaluation(
            api, sire_id, effective_at=cls.STRONG_EFFECTIVE_AT, **SCORED_TRAITS
        )
        context["weak"] = fx.file_evaluation(
            api, sire_id, effective_at=cls.WEAK_EFFECTIVE_AT, **TRAILING_ZERO_TRAITS
        )
        assert context["strong"]["composite_index"] == pytest.approx(24.64, abs=0.001)
        assert context["weak"]["composite_index"] == pytest.approx(17.00, abs=0.001)
        return context

    def test_the_line_multiplier_and_the_purity_ratio_are_both_applied(self, api):
        """Take 45 cents per index point, multiply by the bull's
        `published_composite_index` floored at 0 ... and multiply by the
        product-line multiplier: 1.00 for `CONVENTIONAL`, 1.85 for `SEXED` and
        3.40 for `EMBRYO`. For a `SEXED` lot only, multiply the running figure by
        the lot's `sexing_purity_pct` divided by the reference purity of 90.0.

        Design: Corner/calculations/market_revaluation_applies_product_multiplier_purity_and_floor
        """
        context = self._four_lots_and_two_drafts(api)

        published = fx.publish_evaluation(api, context["strong"]["id"])
        assert published["status"] == "PUBLISHED"
        sire = fx.read_sire(api, context["sire"]["id"])
        assert sire["published_composite_index"] == pytest.approx(24.64, abs=0.001)

        # 45 * 24.64 = 1108.80 before any line multiplier.
        expected = {
            "CONVENTIONAL": 1109,
            "SEXED_90": 2051,
            "SEXED_72": 1641,
            "EMBRYO": 3770,
        }
        for key, unit in expected.items():
            revalued = fx.read_lot(api, context["lots"][key]["id"])
            assert revalued["unit_book_value_cents"] == unit, key
            assert revalued["valuation_basis"] == "MARKET_REVALUED"
            assert revalued["pre_revaluation_unit_value_cents"] == 2500

        assert expected["CONVENTIONAL"] == expected_market_unit_value_cents(
            24.64, "CONVENTIONAL"
        )
        assert expected["SEXED_90"] == expected_market_unit_value_cents(24.64, "SEXED", 90.0)
        assert expected["SEXED_72"] == expected_market_unit_value_cents(24.64, "SEXED", 72.0)
        assert expected["EMBRYO"] == expected_market_unit_value_cents(24.64, "EMBRYO")

        # 857100 after hop 2 against 1000000 immediately before it.
        assert fx.plant_value(api) == 857100
        assert published["revaluation_delta_cents"] == -142900

    def test_a_weaker_proof_drives_the_conventional_line_onto_the_floor(self, api):
        """Round that result half up to whole cents, then take the larger of it
        and the market floor of 800 cents, and store the outcome as
        `unit_book_value_cents`.

        Design: Corner/calculations/market_revaluation_applies_product_multiplier_purity_and_floor
        """
        context = self._four_lots_and_two_drafts(api)

        published = fx.publish_evaluation(api, context["weak"]["id"])
        sire = fx.read_sire(api, context["sire"]["id"])
        assert sire["published_composite_index"] == pytest.approx(17.00, abs=0.001)

        # 45 * 17.00 = 765.00: the CONVENTIONAL figure is lifted to the floor,
        # while every multiplied line clears it on its own.
        expected = {
            "CONVENTIONAL": 800,
            "SEXED_90": 1415,
            "SEXED_72": 1132,
            "EMBRYO": 2601,
        }
        for key, unit in expected.items():
            revalued = fx.read_lot(api, context["lots"][key]["id"])
            assert revalued["unit_book_value_cents"] == unit, key
            assert revalued["valuation_basis"] == "MARKET_REVALUED"
            assert revalued["pre_revaluation_unit_value_cents"] == 2500

        assert expected["CONVENTIONAL"] == expected_market_unit_value_cents(
            17.00, "CONVENTIONAL"
        )
        assert expected["SEXED_90"] == expected_market_unit_value_cents(17.00, "SEXED", 90.0)
        assert expected["SEXED_72"] == expected_market_unit_value_cents(17.00, "SEXED", 72.0)
        assert expected["EMBRYO"] == expected_market_unit_value_cents(17.00, "EMBRYO")

        assert fx.plant_value(api) == 594800
        assert published["revaluation_delta_cents"] == -405200


class TestPlantValuationSourceSet:
    """The aggregate runs over QUARANTINE and RELEASED lots and nothing else."""

    @staticmethod
    def _three_lots_of_one_ejaculate(api):
        context = fx.accepted_ejaculate(
            api,
            facility_overrides={
                "code": "F-CALC-04",
                "housing_capacity": 2,
                "bench_capacity": 1,
            },
            registration_code="REG-CALC4",
        )
        assert context["ejaculate"]["total_doses_theoretical"] == 480
        ejaculate_id = context["ejaculate"]["id"]

        context["l1"] = fx.cut_lot(api, ejaculate_id, "CONVENTIONAL", 100, 250000)
        context["l2"] = fx.cut_lot(api, ejaculate_id, "CONVENTIONAL", 200, 250000)
        context["l3"] = fx.cut_lot(api, ejaculate_id, "CONVENTIONAL", 100, 100000)
        assert context["l1"]["unit_book_value_cents"] == 2500
        assert context["l2"]["unit_book_value_cents"] == 1250
        assert context["l3"]["unit_book_value_cents"] == 1000

        context["l2"] = fx.release_lot(api, context["l2"]["id"])
        assert context["l2"]["distribution_status"] == "RELEASED"
        return context

    def test_a_condemned_lot_keeps_its_unit_value_and_leaves_the_source_set(self, api):
        """Doses in `doses_used` or `doses_destroyed` are consumed and contribute
        nothing, and lots in `REJECTED` or `DEPLETED` are excluded from the source
        set altogether even though their stored unit value survives.

        Design: Corner/calculations/plant_valuation_source_set_excludes_rejected_lots
        """
        context = self._three_lots_of_one_ejaculate(api)

        opening = fx.read_valuation(api)
        assert opening["plant_inventory_value_cents"] == 600000
        assert opening["quarantine_value_cents"] == 350000
        assert opening["released_value_cents"] == 250000
        assert opening["lot_count"] == 3

        condemned = fx.reject_lot(api, context["l3"]["id"])
        assert condemned["distribution_status"] == "REJECTED"
        assert condemned["straw_count"] == 100
        assert_buckets(condemned, 0, 0, 0, 0, 100)
        assert condemned["unit_book_value_cents"] == 1000

        after = fx.read_valuation(api)
        assert after["plant_inventory_value_cents"] == 500000
        assert after["quarantine_value_cents"] == 250000
        assert after["released_value_cents"] == 250000
        assert after["lot_count"] == 2

        # The split is by status, not by age.
        fx.release_lot(api, context["l1"]["id"])
        shifted = fx.read_valuation(api)
        assert shifted["plant_inventory_value_cents"] == 500000
        assert shifted["quarantine_value_cents"] == 0
        assert shifted["released_value_cents"] == 500000
        assert shifted["lot_count"] == 2

        rows, meta = validate_paginated(
            api.list_straw_lots(fx.DIRECTOR, {"ejaculate_id": context["ejaculate"]["id"]})
        )
        assert meta["total_count"] == 3
        assert len(rows) == 3

    def test_a_depleted_lot_drops_out_once_every_dose_is_consumed(self, api):
        """A depleted lot leaves the plant inventory aggregate, and its `version`
        increments by 1 with `updated_at` refreshed.

        Design: Corner/calculations/plant_valuation_source_set_excludes_rejected_lots
        """
        context = self._three_lots_of_one_ejaculate(api)
        fx.reject_lot(api, context["l3"]["id"])
        fx.release_lot(api, context["l1"]["id"])
        assert fx.plant_value(api) == 500000

        partner = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-CALC4", "credit_limit_cents": 100000000},
            tank_overrides={"serial": "TK-CALC4", "capacity_straws": 500},
        )
        walked = fx.received_consignment(
            api,
            {**context, **partner, "lot": context["l2"]},
            doses=200,
            unit_price_cents=4000,
        )
        assert fx.plant_value(api) == 500000

        reconciled = fx.report_usage(
            api,
            walked["transfer"]["id"],
            partner["distributor"]["id"],
            doses_used=200,
            doses_returned=0,
        )
        assert reconciled["status"] == "RECONCILED"

        emptied = fx.read_lot(api, context["l2"]["id"])
        assert emptied["distribution_status"] == "DEPLETED"
        assert_buckets(emptied, 0, 0, 0, 200, 0)
        assert emptied["unit_book_value_cents"] == 1250

        closing = fx.read_valuation(api)
        assert closing["plant_inventory_value_cents"] == 250000
        assert closing["quarantine_value_cents"] == 0
        assert closing["released_value_cents"] == 250000
        assert closing["lot_count"] == 1


class TestTankLn2DecayFloorsPartialDays:
    """The boil-off is a whole-day step curve that restarts at every service."""

    HALF_DAY_PAST_DUE = "2026-08-11T12:00:00Z"
    THREE_DAYS_ON = "2026-08-14T12:00:00Z"
    LONG_AFTER = "2026-09-25T12:00:00Z"

    @staticmethod
    def _tank_on_a_ten_day_interval(api):
        partner = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-LN2", "credit_limit_cents": 5000000},
            tank_overrides={
                "serial": "TK-LN2",
                "capacity_straws": 500,
                "service_interval_days": 10,
                "initial_fill_pct": 95.0,
            },
        )
        tank = partner["tank"]
        assert tank["ln2_level_pct"] == pytest.approx(95.0, abs=0.05)
        assert tank["last_service_fill_pct"] == pytest.approx(95.0, abs=0.05)
        assert_instant_equals(tank["last_service_at"], "2026-08-01T00:00:00.000Z")
        assert_instant_equals(tank["next_service_due_at"], "2026-08-11T00:00:00.000Z")
        assert tank["service_count"] == 0
        assert tank["tank_status"] == "IN_SERVICE"
        return partner

    def test_the_extra_twelve_hours_decay_nothing_while_the_calendar_arm_fires(self, api):
        """Count `elapsed_days` as the logical clock minus `last_service_at`,
        divided by 86400 seconds and floored to whole days — partial days never
        count.

        Design: Corner/calculations/tank_ln2_decay_floors_partial_days_and_restarts_on_service
        """
        partner = self._tank_on_a_ten_day_interval(api)
        tank_id = partner["tank"]["id"]

        sweep = fx.advance_clock(api, self.HALF_DAY_PAST_DUE)
        tank = fx.read_tank(api, tank_id)

        # floor(10.5) = 10 whole days at 2.0 points each.
        assert tank["ln2_level_pct"] == pytest.approx(75.0, abs=0.05)
        assert tank["ln2_level_pct"] == pytest.approx(
            expected_ln2_level_pct(95.0, 10), abs=0.05
        )
        # The calendar arm alone decides the posture: 75.0 is far above 25.0.
        assert tank["tank_status"] == "SERVICE_DUE"
        assert tank_id in sweep["service_due_tank_ids"]
        assert tank["service_count"] == 0

    def test_the_curve_restarts_at_the_service_and_floors_at_zero(self, api):
        """A service sets `last_service_at` to the logical clock and
        `last_service_fill_pct` to the supplied `fill_pct`, restarting the decay
        curve from that origin.

        Design: Corner/calculations/tank_ln2_decay_floors_partial_days_and_restarts_on_service
        """
        partner = self._tank_on_a_ten_day_interval(api)
        tank_id = partner["tank"]["id"]
        fx.advance_clock(api, self.HALF_DAY_PAST_DUE)
        assert fx.read_tank(api, tank_id)["ln2_level_pct"] == pytest.approx(75.0, abs=0.05)

        serviced = fx.service_tank(
            api, tank_id, fill_pct=80.0, headers=partner["distributor_headers"]
        )
        assert serviced["ln2_level_pct"] == pytest.approx(80.0, abs=0.05)
        assert serviced["last_service_fill_pct"] == pytest.approx(80.0, abs=0.05)
        assert serviced["service_count"] == 1
        assert serviced["tank_status"] == "IN_SERVICE"
        assert_instant_equals(serviced["last_service_at"], "2026-08-11T12:00:00.000Z")
        assert_instant_equals(serviced["next_service_due_at"], "2026-08-21T12:00:00.000Z")

        fx.advance_clock(api, self.THREE_DAYS_ON)
        restarted = fx.read_tank(api, tank_id)
        # 80.0 - 2.0*3 from the new origin, not 95.0 - 2.0*13 from the old one.
        assert restarted["ln2_level_pct"] == pytest.approx(74.0, abs=0.05)
        assert restarted["ln2_level_pct"] == pytest.approx(
            expected_ln2_level_pct(80.0, 3), abs=0.05
        )
        assert restarted["tank_status"] == "IN_SERVICE"

        sweep = fx.advance_clock(api, self.LONG_AFTER)
        emptied = fx.read_tank(api, tank_id)
        # 45 whole days would take the raw figure to -10.0; the floor holds it at 0.
        assert emptied["ln2_level_pct"] == pytest.approx(0.0, abs=0.05)
        assert emptied["ln2_level_pct"] == pytest.approx(
            expected_ln2_level_pct(80.0, 45), abs=0.05
        )
        assert emptied["tank_status"] == "OUT_OF_SERVICE"
        assert tank_id in sweep["out_of_service_tank_ids"]


class TestStrawLotCuttingStopsAtTheDoseCap:
    """The ceiling is a running sum over the ejaculate's lots, inclusive."""

    @staticmethod
    def _four_hundred_straws_already_cut(api):
        context = fx.accepted_ejaculate(
            api,
            facility_overrides={
                "code": "F-CALC-06",
                "housing_capacity": 2,
                "bench_capacity": 1,
            },
            registration_code="REG-CALC6",
        )
        ejaculate = context["ejaculate"]
        assert ejaculate["total_doses_theoretical"] == 480
        assert ejaculate["total_doses_theoretical"] == expected_theoretical_doses(6.0, 1200)
        context["first"] = fx.cut_lot(
            api, ejaculate["id"], "CONVENTIONAL", 400, 400000
        )
        return context

    def test_one_straw_over_is_refused_and_exactly_at_the_cap_succeeds(self, api):
        """The dose ceiling is aggregate, not per-lot: the sum of `straw_count`
        across every lot already cut from this ejaculate, including the row being
        created, must not exceed the ejaculate's `total_doses_theoretical`, or the
        request is refused with `ERR_DOSE_CAP_EXCEEDED`.

        Design: Corner/calculations/straw_lot_cutting_stops_at_the_theoretical_dose_cap
        """
        context = self._four_hundred_straws_already_cut(api)
        ejaculate_id = context["ejaculate"]["id"]

        validate_error(
            api.cut_straw_lot(
                ejaculate_id,
                factories.straw_lot_payload("CONVENTIONAL", 81, 81000),
                fx.TECH,
            ),
            ApiErrorId.ERR_DOSE_CAP_EXCEEDED.value,
            422,
        )
        rows, meta = validate_paginated(
            api.list_straw_lots(fx.TECH, {"ejaculate_id": ejaculate_id})
        )
        assert meta["total_count"] == 1

        at_the_cap = validate_success(
            api.cut_straw_lot(
                ejaculate_id,
                factories.straw_lot_payload("CONVENTIONAL", 80, 81000),
                fx.TECH,
            ),
            201,
        )
        assert at_the_cap["straw_count"] == 80
        assert at_the_cap["unit_book_value_cents"] == 1013
        assert at_the_cap["unit_book_value_cents"] == expected_standard_unit_value_cents(
            81000, 80
        )

        rows, meta = validate_paginated(
            api.list_straw_lots(fx.TECH, {"ejaculate_id": ejaculate_id})
        )
        assert meta["total_count"] == 2
        assert sum(row["straw_count"] for row in rows) == 480

    def test_condemning_a_lot_gives_back_no_headroom(self, api):
        """Condemning a lot ... moves the whole shelf ledger in one step:
        `doses_destroyed` increases by the current `doses_available` and
        `doses_available` is then set to 0, leaving `straw_count` untouched as the
        conserved total.

        Design: Corner/calculations/straw_lot_cutting_stops_at_the_theoretical_dose_cap
        """
        context = self._four_hundred_straws_already_cut(api)
        ejaculate_id = context["ejaculate"]["id"]
        filler = fx.cut_lot(api, ejaculate_id, "CONVENTIONAL", 80, 81000)

        validate_error(
            api.cut_straw_lot(
                ejaculate_id,
                factories.straw_lot_payload("CONVENTIONAL", 1, 1000),
                fx.TECH,
            ),
            ApiErrorId.ERR_DOSE_CAP_EXCEEDED.value,
            422,
        )

        condemned = fx.reject_lot(api, filler["id"])
        assert condemned["distribution_status"] == "REJECTED"
        assert condemned["straw_count"] == 80
        assert_buckets(condemned, 0, 0, 0, 0, 80)

        validate_error(
            api.cut_straw_lot(
                ejaculate_id,
                factories.straw_lot_payload("CONVENTIONAL", 1, 1000),
                fx.TECH,
            ),
            ApiErrorId.ERR_DOSE_CAP_EXCEEDED.value,
            422,
        )

        rows, meta = validate_paginated(
            api.list_straw_lots(fx.TECH, {"ejaculate_id": ejaculate_id})
        )
        assert meta["total_count"] == 2
        assert sum(row["straw_count"] for row in rows) == 480


class TestSettlementBillsOnlyPostDispatchServices:
    """The service fee reads the counter delta since dispatch, not the lifetime count."""

    FIRST_TOP_UP_CLOCK = "2026-09-11T08:00:00Z"
    SECOND_TOP_UP_CLOCK = "2026-09-12T08:00:00Z"

    @classmethod
    def _reconciled_after_two_post_dispatch_services(cls, api, doses):
        context = fx.released_lot(
            api,
            facility_overrides={
                "code": "F-CALC-07",
                "housing_capacity": 2,
                "bench_capacity": 1,
            },
            registration_code="REG-CALC7",
            straw_count=200,
            processing_cost_cents=250000,
        )
        assert context["lot"]["unit_book_value_cents"] == 1250
        context.update(
            fx.distributor_with_tank(
                api,
                distributor_overrides={
                    "name": "D-STL",
                    "credit_limit_cents": 100000000,
                },
                tank_overrides={
                    "serial": "TK-STL",
                    "capacity_straws": 500,
                    "initial_fill_pct": 95.0,
                },
            )
        )
        tank_id = context["tank"]["id"]
        distributor_id = context["distributor"]["id"]
        headers = context["distributor_headers"]

        # One top-up before dispatch, which this consignment must never pay for.
        before_dispatch = fx.service_tank(api, tank_id, fill_pct=98.0, headers=headers)
        assert before_dispatch["service_count"] == 1

        transfer = fx.request_consignment(
            api, context["lot"]["id"], distributor_id, tank_id, doses, 4000
        )
        fx.approve_transfer(api, transfer["id"])
        dispatched = fx.dispatch_transfer(api, transfer["id"])
        assert dispatched["tank_service_count_at_dispatch"] == 1

        # Two top-ups afterwards, each on its own day so the fill genuinely
        # exceeds the decayed level it replaces.
        fx.advance_clock(api, cls.FIRST_TOP_UP_CLOCK)
        assert fx.read_tank(api, tank_id)["ln2_level_pct"] == pytest.approx(96.0, abs=0.05)
        assert fx.service_tank(api, tank_id, 97.0, headers)["service_count"] == 2
        fx.advance_clock(api, cls.SECOND_TOP_UP_CLOCK)
        assert fx.read_tank(api, tank_id)["ln2_level_pct"] == pytest.approx(95.0, abs=0.05)
        third = fx.service_tank(api, tank_id, 96.0, headers)
        assert third["service_count"] == 3
        assert third["tank_status"] == "IN_SERVICE"

        fx.receive_transfer(api, transfer["id"], distributor_id)
        context["transfer"] = fx.report_usage(
            api, transfer["id"], distributor_id, doses_used=doses, doses_returned=0
        )
        return context

    def test_only_the_two_services_after_dispatch_reach_the_invoice(self, api):
        """Step two: `service_fee_cents` is 120 dollars, that is 12000 cents, for
        each liquid-nitrogen service performed on the destination tank since
        dispatch, computed as the tank's current `service_count` minus the
        transfer's `tank_service_count_at_dispatch`; services performed before
        dispatch are not billed to this consignment.

        Design: Corner/calculations/settlement_bills_only_ln2_services_performed_after_dispatch
        """
        context = self._reconciled_after_two_post_dispatch_services(api, 100)
        transfer = context["transfer"]

        assert transfer["status"] == "RECONCILED"
        assert transfer["gross_cents"] == 400000
        # 12000 * (3 - 1), never 12000 * 3.
        assert transfer["service_fee_cents"] == 24000
        assert transfer["rebate_cents"] == 0
        assert transfer["settlement_total_cents"] == 424000
        assert_settlement(transfer, expected_settlement(100, 4000, 2))

        partner = fx.read_distributor(api, context["distributor"]["id"])
        assert partner["outstanding_balance_cents"] == 424000
        assert partner["cumulative_doses_used"] == 100
        assert partner["consignment_value_cents"] == 0

    def test_the_fee_carries_the_tier_but_never_earns_the_rebate(self, api):
        """Step five: `rebate_cents` is `gross_cents` multiplied by that
        percentage, rounded half up to whole cents — the rebate applies to the
        goods only and never to the service fee.

        Design: Corner/calculations/settlement_bills_only_ln2_services_performed_after_dispatch
        """
        context = self._reconciled_after_two_post_dispatch_services(api, 125)
        transfer = context["transfer"]

        assert transfer["gross_cents"] == 500000
        assert transfer["service_fee_cents"] == 24000
        # The 524000 subtotal buys the 3 percent tier, but the fee is not discounted.
        assert transfer["rebate_cents"] == 15000
        assert transfer["settlement_total_cents"] == 509000
        assert_settlement(transfer, expected_settlement(125, 4000, 2))

        partner = fx.read_distributor(api, context["distributor"]["id"])
        assert partner["outstanding_balance_cents"] == 509000
        assert partner["cumulative_doses_used"] == 125


class TestInbreedingCollapsesRepeatPaths:
    """A diamond ancestor counts once, at its shortest distance."""

    DAM_REF = "COW-4471"

    @staticmethod
    def _diamond_pedigree(api):
        context = fx.released_lot(
            api,
            facility_overrides={
                "code": "F-CALC-08",
                "housing_capacity": 2,
                "bench_capacity": 1,
            },
            registration_code="REG-IBC",
            straw_count=100,
            processing_cost_cents=125000,
        )
        proof = fx.published_proof(
            api,
            context["sire"]["id"],
            effective_at="2026-09-01T00:00:00Z",
            **SCORED_TRAITS,
        )
        assert proof["composite_index"] == pytest.approx(24.64, abs=0.001)

        context["g"] = fx.register_sire(
            api,
            registration_code="REG-G",
            birth_date="2012-01-01",
            acquisition_cost_cents=0,
        )
        for code, birth_date in (
            ("REG-A", "2016-01-01"),
            ("REG-B", "2016-06-01"),
            ("REG-D", "2017-01-01"),
        ):
            context[code] = fx.register_sire(
                api,
                registration_code=code,
                birth_date=birth_date,
                sire_id=context["g"]["id"],
                acquisition_cost_cents=0,
            )
            assert context[code]["pedigree_depth"] == 1

        amended = validate_success(
            api.amend_sire_pedigree(
                context["sire"]["id"],
                factories.pedigree_payload(
                    sire_id=context["REG-A"]["id"], dam_sire_id=context["REG-B"]["id"]
                ),
                fx.DIRECTOR,
            ),
            200,
        )
        # 1 plus the largest pedigree_depth among the non-null parents.
        assert amended["pedigree_depth"] == 2

        distributor = fx.register_distributor(
            api, name="D-IBC", credit_limit_cents=5000000
        )
        context["distributor"] = distributor
        context["herd"] = fx.register_customer_herd(
            api,
            distributor["id"],
            herd_name="Willow Creek",
            max_inbreeding_pct=10.0,
        )
        return context

    def test_the_shared_ancestor_is_counted_once_at_its_shortest_distance(self, api):
        """Where several paths reach the same ancestor, that shortest distance is
        the one that counts, which is what makes the sum order-independent.

        Design: Corner/calculations/inbreeding_collapses_repeat_paths_and_truncates_at_depth_three
        """
        context = self._diamond_pedigree(api)

        recommendation = fx.request_recommendation(
            api,
            context["herd"]["id"],
            dam_ref=self.DAM_REF,
            dam_sire_id=context["REG-D"]["id"],
            requested_product_line="CONVENTIONAL",
            doses_requested=1,
        )

        # REG-G alone is shared: candidate distance 2, maternal 1 + 1 = 2, so
        # 0.5^(2+2+1) = 0.03125.  Counting him once per path would give 6.25.
        assert recommendation["inbreeding_pct"] == pytest.approx(3.13, abs=0.001)
        assert recommendation["recommended_sire_id"] == context["sire"]["id"]
        assert recommendation["straw_lot_id"] == context["lot"]["id"]
        assert recommendation["candidate_pool_size"] == 1
        assert recommendation["status"] == "PROPOSED"
        assert recommendation["doses_committed"] == 0
        assert recommendation["expected_conception_rate"] == pytest.approx(
            expected_conception_rate("CONVENTIONAL", 24.64, 55.0, 3.13), abs=0.0001
        )

        without_maternal_side = fx.request_recommendation(
            api,
            context["herd"]["id"],
            dam_ref="COW-4472",
            requested_product_line="CONVENTIONAL",
            doses_requested=1,
        )
        assert without_maternal_side["inbreeding_pct"] == pytest.approx(0.00, abs=0.001)
        assert without_maternal_side["dam_sire_id"] is None

    def test_an_ancestor_four_edges_out_drops_silently_from_the_sum(self, api):
        """Otherwise the server walks the pedigree upward from the candidate bull,
        following both the `sire_id` and `dam_sire_id` edges, at most 3 edges deep.

        Design: Corner/calculations/inbreeding_collapses_repeat_paths_and_truncates_at_depth_three
        """
        context = self._diamond_pedigree(api)
        herd_id = context["herd"]["id"]
        dam_sire_id = context["REG-D"]["id"]

        great = fx.register_sire(
            api,
            registration_code="REG-GG",
            birth_date="2008-01-01",
            acquisition_cost_cents=0,
        )
        validate_success(
            api.amend_sire_pedigree(
                context["g"]["id"],
                factories.pedigree_payload(sire_id=great["id"]),
                fx.DIRECTOR,
            ),
            200,
        )

        # REG-GG sits 3 edges from the candidate and 2 from the dam's sire:
        # 0.5^(3+3+1) = 0.0078125 on top of REG-G's 0.03125.
        deeper = fx.request_recommendation(
            api,
            herd_id,
            dam_ref="COW-4473",
            dam_sire_id=dam_sire_id,
            requested_product_line="CONVENTIONAL",
            doses_requested=1,
        )
        assert deeper["inbreeding_pct"] == pytest.approx(3.91, abs=0.001)

        beyond = fx.register_sire(
            api,
            registration_code="REG-GGG",
            birth_date="2004-01-01",
            acquisition_cost_cents=0,
        )
        validate_success(
            api.amend_sire_pedigree(
                great["id"],
                factories.pedigree_payload(sire_id=beyond["id"]),
                fx.DIRECTOR,
            ),
            200,
        )

        # REG-GGG is 4 edges from the candidate, so he never enters the sum even
        # though he is only 3 from the dam's sire.
        truncated = fx.request_recommendation(
            api,
            herd_id,
            dam_ref="COW-4474",
            dam_sire_id=dam_sire_id,
            requested_product_line="CONVENTIONAL",
            doses_requested=1,
        )
        assert truncated["inbreeding_pct"] == pytest.approx(3.91, abs=0.001)


class TestMatingSelectorRanksByIndexThenCreatedAt:
    """Two equally strong bulls are separated by age, and the lot by stock."""

    @staticmethod
    def _two_bulls_of_equal_merit(api):
        facility = fx.register_facility(
            api, code="F-SEL", housing_capacity=2, bench_capacity=2
        )
        registered = []
        for code in ("REG-SEL1", "REG-SEL2"):
            sire = fx.register_sire(api, registration_code=code, birth_date="2021-04-01")
            fx.contract_sire(api, sire["id"])
            fx.house_sire(api, sire["id"], facility["id"], 30)
            fx.grant_base_health_currency(api, sire["id"], facility["id"])
            registered.append(sire)

        fx.advance_clock(api, fx.CLOCK_ISOLATION_SERVED)
        bookings = []
        for sire in registered:
            validate_success(
                api.clear_sire_for_collection(
                    sire["id"], factories.clearance_payload(), fx.VET
                ),
                200,
            )
            bookings.append(
                fx.book_collection(api, sire["id"], facility["id"])
            )

        fx.advance_clock(api, fx.CLOCK_AT_COLLECTION)
        lots = []
        for sire, booking in zip(registered, bookings):
            fx.complete_collection(api, booking["id"], facility["id"])
            ejaculate = fx.evaluate_qc(
                api, fx.discover_ejaculate(api, booking["id"])["id"]
            )
            straw_counts = (150, 100) if sire["registration_code"] == "REG-SEL1" else (200,)
            for straw_count in straw_counts:
                cut = fx.cut_lot(
                    api,
                    ejaculate["id"],
                    "CONVENTIONAL",
                    straw_count,
                    250000,
                )
                lots.append(fx.release_lot(api, cut["id"]))

        for sire in registered:
            proof = fx.published_proof(api, sire["id"], **SCORED_TRAITS)
            assert proof["composite_index"] == pytest.approx(24.64, abs=0.001)
            assert fx.read_sire(api, sire["id"])[
                "published_composite_index"
            ] == pytest.approx(24.64, abs=0.001)

        distributor = fx.register_distributor(
            api, name="D-SEL", credit_limit_cents=5000000
        )
        herd = fx.register_customer_herd(
            api, distributor["id"], herd_name="Elm Ridge", max_inbreeding_pct=5.0
        )
        return {
            "facility": facility,
            "first_sire": registered[0],
            "second_sire": registered[1],
            "big_lot": lots[0],
            "small_lot": lots[1],
            "rival_lot": lots[2],
            "herd": herd,
        }

    def test_the_older_bull_wins_the_tie_and_his_fullest_lot_is_chosen(self, api):
        """Ranking is by highest `published_composite_index` first. Ties are broken
        by lower `inbreeding_pct` first, and a remaining tie by earlier `created_at`
        on the bull. A bull's `id` is never a decision input. ... Within that bull's
        eligible lots the server then picks the one with the most stock — highest
        `doses_available` first — breaking a tie on the earlier `created_at` of the
        lot.

        Design: Corner/calculations/mating_selector_ranks_by_index_then_breaks_ties_on_created_at
        """
        context = self._two_bulls_of_equal_merit(api)
        assert context["big_lot"]["doses_available"] == 150
        assert context["small_lot"]["doses_available"] == 100
        assert context["rival_lot"]["doses_available"] == 200

        recommendation = fx.request_recommendation(
            api,
            context["herd"]["id"],
            dam_ref="COW-1200",
            requested_product_line="CONVENTIONAL",
            doses_requested=10,
        )

        # Both bulls clear residency, collection status, proof and stock.
        assert recommendation["candidate_pool_size"] == 2
        # The composite indices tie at 24.64 and both coefficients are 0.00, so
        # the earlier created_at decides — never the larger stock of the rival.
        assert recommendation["recommended_sire_id"] == context["first_sire"]["id"]
        assert recommendation["straw_lot_id"] == context["big_lot"]["id"]
        assert recommendation["inbreeding_pct"] == pytest.approx(0.00, abs=0.001)
        assert recommendation["status"] == "PROPOSED"
        assert recommendation["doses_committed"] == 0
        assert recommendation["decided_at"] is None
        assert recommendation["expected_conception_rate"] == pytest.approx(
            expected_conception_rate("CONVENTIONAL", 24.64, 55.0, 0.00), abs=0.0001
        )
        assert fx.read_lot(api, context["big_lot"]["id"])["doses_available"] == 150

    def test_exclusion_and_stock_both_shrink_the_pool_before_ranking(self, api):
        """... an optional `excluded_sire_ids` array of bulls the customer refuses,
        which defaults to empty and is removed from the pool before ranking. ...
        and there exists at least one straw lot of his whose `distribution_status`
        is `RELEASED`, whose `product_line` equals the `requested_product_line`, and
        whose `doses_available` is at least `doses_requested`.

        Design: Corner/calculations/mating_selector_ranks_by_index_then_breaks_ties_on_created_at
        """
        context = self._two_bulls_of_equal_merit(api)
        herd_id = context["herd"]["id"]
        first_id = context["first_sire"]["id"]
        second_id = context["second_sire"]["id"]

        excluded = fx.request_recommendation(
            api,
            herd_id,
            dam_ref="COW-1201",
            requested_product_line="CONVENTIONAL",
            doses_requested=10,
            excluded_sire_ids=[first_id],
        )
        assert excluded["recommended_sire_id"] == second_id
        assert excluded["straw_lot_id"] == context["rival_lot"]["id"]
        assert excluded["candidate_pool_size"] == 1

        # Stock is part of eligibility, not a post-filter: no lot of the older
        # bull holds 160 available doses, so he never enters the pool at all.
        starved = fx.request_recommendation(
            api,
            herd_id,
            dam_ref="COW-1202",
            requested_product_line="CONVENTIONAL",
            doses_requested=160,
        )
        assert starved["recommended_sire_id"] == second_id
        assert starved["candidate_pool_size"] == 1


class TestCertificateExpiryIntersection:
    """The document lapses with the first of the windows it rests on."""

    LATER_BVD_SAMPLE_DATE = "2026-08-05"
    LATER_BVD_VALID_UNTIL = "2027-02-21T00:00:00.000Z"
    EARLIER_BVD_VALID_UNTIL = "2027-01-28T00:00:00.000Z"
    ISSUE_CLOCK = "2026-09-10T08:00:00.000Z"

    @classmethod
    def _released_lot_of_a_well_tested_bull(cls, api, *, with_later_bvd=True):
        context = fx.eligible_sire(
            api,
            facility_overrides={
                "code": "F-EXP",
                "housing_capacity": 2,
                "bench_capacity": 1,
                "approved_export_countries": ["CA", "MX"],
            },
            registration_code="REG-EXP",
            per_type_validity_days={"BVD": 180, "TRICHOMONIASIS": 120},
        )
        sire_id = context["sire"]["id"]
        facility_id = context["facility"]["id"]
        assert_instant_equals(
            context["health_tests"]["IBR"]["valid_until"], fx.BASE_VALID_UNTIL
        )
        assert_instant_equals(
            context["health_tests"]["BVD"]["valid_until"], cls.EARLIER_BVD_VALID_UNTIL
        )

        if with_later_bvd:
            # Only orderable now: a sample_date ahead of the clock is refused.
            later = fx.negative_test(
                api,
                sire_id,
                facility_id,
                "BVD",
                sample_date=cls.LATER_BVD_SAMPLE_DATE,
                validity_days=200,
            )
            assert_instant_equals(later["valid_until"], cls.LATER_BVD_VALID_UNTIL)
            context["later_bvd"] = later

        context = fx.accepted_ejaculate(api, fx.collected_ejaculate(api, context))
        context = fx.released_lot(
            api,
            fx.quarantine_lot(
                api, context, straw_count=200, processing_cost_cents=250000
            ),
        )
        assert context["sire"]["isolation_days_applied"] == 30
        return context

    @staticmethod
    def _submitted_for(api, context, *, country_code, max_test_age_days):
        requirement = fx.register_country_requirement(
            api,
            country_code=country_code,
            required_test_types=["IBR", "BVD"],
            max_test_age_days=max_test_age_days,
            min_isolation_days=21,
            sexed_semen_allowed=False,
            embryo_allowed=False,
        )
        certificate = fx.submitted_certificate(
            api, context["sire"]["id"], context["lot"]["id"], requirement["id"]
        )
        assert certificate["status"] == "SUBMITTED"
        assert certificate["submission_round"] == 1
        assert certificate["destination_country_code"] == country_code
        assert certificate["expires_at"] is None
        return requirement, certificate

    def test_the_later_row_is_chosen_per_type_and_the_earliest_window_wins(self, api):
        """... and sets `expires_at` to the **earliest** `valid_until` among the
        chosen satisfying tests — the certificate's validity window is the
        intersection of the individual test windows, so it lapses with the first of
        them. ... Where a type has more than one satisfying row, the server picks
        the one with the latest `valid_until`, breaking a tie on the earliest
        `created_at`, so that the outcome is deterministic.

        Design: Corner/calculations/certificate_expiry_is_the_intersection_of_satisfying_test_windows
        """
        context = self._released_lot_of_a_well_tested_bull(api)
        _requirement, certificate = self._submitted_for(
            api, context, country_code="CA", max_test_age_days=45
        )

        issued = fx.issue_certificate(api, certificate["id"])

        assert issued["status"] == "ISSUED"
        assert issued["issued_by_user_id"] == VET_ALT_USER_ID
        assert_instant_equals(issued["issued_at"], self.ISSUE_CLOCK)
        # BVD keeps its later window, and that date is earlier than IBR's.
        assert_instant_equals(issued["expires_at"], self.LATER_BVD_VALID_UNTIL)
        assert issued["rejection_reason"] is None
        assert issued["revocation_reason"] is None
        # The IBR window is the latest date on file and never sets expires_at,
        # and the two base types outside the destination's list are irrelevant
        # even though TRICHOMONIASIS lapses long before either BVD row.
        assert_instant_equals(
            context["health_tests"]["TRICHOMONIASIS"]["valid_until"],
            "2026-11-29T00:00:00.000Z",
        )

    def test_without_the_second_assay_the_window_closes_a_month_earlier(self, api):
        """... for every `test_type` in the destination's `required_test_types`,
        there must exist a `HealthTest` for the certificate's `sire_id` of that type
        whose `result` is `NEGATIVE`, whose `valid_until` is strictly later than the
        logical clock ...

        Design: Corner/calculations/certificate_expiry_is_the_intersection_of_satisfying_test_windows
        """
        context = self._released_lot_of_a_well_tested_bull(api, with_later_bvd=False)
        _requirement, certificate = self._submitted_for(
            api, context, country_code="CA", max_test_age_days=45
        )

        issued = fx.issue_certificate(api, certificate["id"])

        assert issued["status"] == "ISSUED"
        assert_instant_equals(issued["expires_at"], self.EARLIER_BVD_VALID_UNTIL)

    def test_a_ten_day_age_window_leaves_every_bvd_row_too_old(self, api):
        """... and whose age — the logical clock minus its `sample_date` — is no
        greater than the destination's `max_test_age_days` multiplied by 86400
        seconds. If any required type has no such row, issuance fails with
        `ERR_COUNTRY_TEST_MISSING`.

        Design: Corner/calculations/certificate_expiry_is_the_intersection_of_satisfying_test_windows
        """
        context = self._released_lot_of_a_well_tested_bull(api)
        _requirement, certificate = self._submitted_for(
            api, context, country_code="MX", max_test_age_days=10
        )

        validate_error(
            api.issue_export_certificate(
                certificate["id"], factories.certificate_issue_payload(), fx.VET_ALT
            ),
            ApiErrorId.ERR_COUNTRY_TEST_MISSING.value,
            422,
        )

        untouched = fx.read_certificate(api, certificate["id"])
        assert untouched["status"] == "SUBMITTED"
        assert untouched["issued_by_user_id"] is None
        assert untouched["issued_at"] is None
        assert untouched["expires_at"] is None


class TestDistributorExposureBuckets:
    """Carried value and outstanding balance read disjoint status sets."""

    @staticmethod
    def _received_hundred_dose_consignment(api):
        context = fx.received_consignment(
            api,
            facility_overrides={
                "code": "F-CALC-11",
                "housing_capacity": 2,
                "bench_capacity": 1,
            },
            registration_code="REG-EXPO",
            straw_count=200,
            processing_cost_cents=250000,
            distributor_overrides={"name": "D-EXPO", "credit_limit_cents": 365000},
            tank_overrides={"serial": "TK-EXPO", "capacity_straws": 500},
            doses=100,
            unit_price_cents=4000,
        )
        assert context["lot"]["unit_book_value_cents"] == 1250
        assert context["transfer"]["status"] == "RECEIVED"
        assert context["transfer"]["doses_on_hand"] == 100
        assert context["transfer"]["carried_value_cents"] == 125000

        opening = fx.read_distributor(api, context["distributor"]["id"])
        assert opening["consignment_value_cents"] == 125000
        assert opening["outstanding_balance_cents"] == 0
        assert opening["cumulative_doses_used"] == 0
        return context

    def test_reconciliation_moves_the_contribution_between_the_two_aggregates(self, api):
        """`consignment_value_cents` is the sum, over the partner's consignments
        whose `status` is `RECEIVED`, of each transfer's `doses_on_hand` multiplied
        by its lot's `unit_book_value_cents`. `outstanding_balance_cents` is the sum
        of `settlement_total_cents` over the partner's consignments whose `status` is
        `RECONCILED`, and `cumulative_doses_used` is the sum of `doses_used` over
        those same reconciled rows.

        Design: Corner/calculations/distributor_exposure_counts_only_received_and_reconciled_transfers
        """
        context = self._received_hundred_dose_consignment(api)
        distributor_id = context["distributor"]["id"]

        reconciled = fx.report_usage(
            api,
            context["transfer"]["id"],
            distributor_id,
            doses_used=60,
            doses_returned=40,
        )

        assert reconciled["status"] == "RECONCILED"
        assert reconciled["doses_on_hand"] == 0
        assert reconciled["carried_value_cents"] == 0
        assert reconciled["gross_cents"] == 240000
        assert reconciled["service_fee_cents"] == 0
        assert reconciled["rebate_cents"] == 0
        assert reconciled["settlement_total_cents"] == 240000
        assert_settlement(reconciled, expected_settlement(60, 4000, 0))

        # The contribution moved buckets instead of being counted twice.
        partner = fx.read_distributor(api, distributor_id)
        assert partner["consignment_value_cents"] == 0
        assert partner["outstanding_balance_cents"] == 240000
        assert partner["cumulative_doses_used"] == 60

        lot = fx.read_lot(api, context["lot"]["id"])
        assert_buckets(lot, 140, 0, 0, 60, 0)
        assert lot["straw_count"] == 200
        assert lot["distribution_status"] == "RELEASED"

    def test_pending_rows_are_invisible_and_the_gate_admits_the_exact_limit(self, api):
        """Consignments in `REQUESTED`, `APPROVED`, `IN_TRANSIT`, `REJECTED` or
        `RETURNED` contribute nothing to any of the three. ... The comparison is
        inclusive, so a projection landing exactly on the limit is approved, and a
        projection above it is refused with `ERR_CREDIT_LIMIT_EXCEEDED`.

        Design: Corner/calculations/distributor_exposure_counts_only_received_and_reconciled_transfers
        """
        context = self._received_hundred_dose_consignment(api)
        lot_id = context["lot"]["id"]
        distributor_id = context["distributor"]["id"]
        tank_id = context["tank"]["id"]
        fx.report_usage(
            api, context["transfer"]["id"], distributor_id, doses_used=60, doses_returned=40
        )

        # 240000 already outstanding, so 101 doses project 366250 - one dose too many.
        too_much = fx.request_consignment(
            api, lot_id, distributor_id, tank_id, 101, 4000
        )
        assert fx.read_distributor(api, distributor_id)["consignment_value_cents"] == 0
        validate_error(
            api.approve_consignment_transfer(
                too_much["id"], factories.transfer_approve_payload(), fx.DIRECTOR
            ),
            ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value,
            422,
        )
        assert fx.read_transfer(api, too_much["id"])["status"] == "REQUESTED"
        assert_buckets(fx.read_lot(api, lot_id), 140, 0, 0, 60, 0)

        exact = fx.request_consignment(api, lot_id, distributor_id, tank_id, 100, 4000)
        assert fx.read_distributor(api, distributor_id)["consignment_value_cents"] == 0

        # 240000 + 100 * 1250 lands exactly on credit_limit_cents.
        approved = fx.approve_transfer(api, exact["id"])
        assert approved["status"] == "APPROVED"
        assert approved["carried_value_cents"] == 0
        assert fx.read_distributor(api, distributor_id)["consignment_value_cents"] == 0

        fx.dispatch_transfer(api, exact["id"])
        assert fx.read_transfer(api, exact["id"])["status"] == "IN_TRANSIT"
        assert fx.read_distributor(api, distributor_id)["consignment_value_cents"] == 0

        fx.receive_transfer(api, exact["id"], distributor_id)
        settled = fx.read_distributor(api, distributor_id)
        assert settled["consignment_value_cents"] == 125000
        assert settled["outstanding_balance_cents"] == 240000


class TestConceptionRateClampedToFloor:
    """The clamp bites on the whole product, not on any single factor."""

    FIRST_WINDOW_START = "2026-09-01T08:00:00Z"
    FIRST_WINDOW_END = "2026-09-01T10:00:00Z"
    SECOND_WINDOW_START = "2026-09-03T10:00:00Z"
    SECOND_WINDOW_END = "2026-09-03T12:00:00Z"

    @classmethod
    def _two_lots_of_differing_post_thaw_vigour(cls, api):
        context = fx.eligible_sire(
            api,
            facility_overrides={
                "code": "F-CALC-12",
                "housing_capacity": 2,
                "bench_capacity": 1,
            },
            registration_code="REG-CR",
        )
        sire_id = context["sire"]["id"]
        facility_id = context["facility"]["id"]

        # Exactly 48 hours of rest between the two windows.
        weak_booking = fx.book_collection(
            api, sire_id, facility_id, cls.FIRST_WINDOW_START, cls.FIRST_WINDOW_END
        )
        strong_booking = fx.book_collection(
            api, sire_id, facility_id, cls.SECOND_WINDOW_START, cls.SECOND_WINDOW_END
        )

        lots = {}
        for booking, clock, post_thaw, product_line in (
            (weak_booking, cls.FIRST_WINDOW_START, 40.0, "EMBRYO"),
            (strong_booking, cls.SECOND_WINDOW_START, 60.0, "CONVENTIONAL"),
        ):
            fx.advance_clock(api, clock)
            fx.complete_collection(api, booking["id"], facility_id)
            ejaculate = fx.evaluate_qc(
                api,
                fx.discover_ejaculate(api, booking["id"])["id"],
                "ACCEPTED",
                post_thaw,
            )
            assert ejaculate["post_thaw_motility_pct"] == pytest.approx(post_thaw, abs=0.01)
            cut = fx.cut_lot(api, ejaculate["id"], product_line, 100, 125000)
            lots[product_line] = fx.release_lot(api, cut["id"])

        proof = fx.published_proof(api, sire_id, **SCORED_TRAITS)
        assert proof["composite_index"] == pytest.approx(24.64, abs=0.001)

        distributor = fx.register_distributor(
            api, name="D-CR", credit_limit_cents=5000000
        )
        herd = fx.register_customer_herd(
            api,
            distributor["id"],
            herd_name="Cedar Hollow",
            target_product_line="EMBRYO",
            max_inbreeding_pct=6.25,
        )
        return {"sire": context["sire"], "lots": lots, "herd": herd}

    def test_a_sub_floor_product_is_reported_as_the_floor_at_four_digits(self, api):
        """Clamp the product to a floor of 0.2000 and a ceiling of 0.7500, and only
        then round half up to four decimal places, storing the result as
        `expected_conception_rate`, a fraction between 0 and 1 rather than a
        percentage.

        Design: Corner/calculations/conception_rate_clamped_to_the_floor_after_multiplication
        """
        context = self._two_lots_of_differing_post_thaw_vigour(api)

        recommendation = fx.request_recommendation(
            api,
            context["herd"]["id"],
            dam_ref="COW-88",
            requested_product_line="EMBRYO",
            doses_requested=1,
        )

        assert recommendation["recommended_sire_id"] == context["sire"]["id"]
        assert recommendation["straw_lot_id"] == context["lots"]["EMBRYO"]["id"]
        assert recommendation["inbreeding_pct"] == pytest.approx(0.00, abs=0.001)
        # 0.42 * 1.009856 * 0.40 = 0.169655808, which is below the floor: 0.1697
        # would mean the clamp was skipped.
        assert recommendation["expected_conception_rate"] == pytest.approx(
            0.2000, abs=0.00001
        )
        assert recommendation["expected_conception_rate"] == pytest.approx(
            expected_conception_rate("EMBRYO", 24.64, 40.0, 0.00), abs=0.00001
        )

    def test_a_mid_range_product_rounds_normally_from_the_post_thaw_figure(self, api):
        """Multiply by the selected lot's parent ejaculate's `post_thaw_motility_pct`
        divided by 100 — the post-thaw figure recorded at quality evaluation, not the
        fresh `motility_pct` taken at collection.

        Design: Corner/calculations/conception_rate_clamped_to_the_floor_after_multiplication
        """
        context = self._two_lots_of_differing_post_thaw_vigour(api)

        recommendation = fx.request_recommendation(
            api,
            context["herd"]["id"],
            dam_ref="COW-89",
            requested_product_line="CONVENTIONAL",
            doses_requested=1,
        )

        assert recommendation["straw_lot_id"] == context["lots"]["CONVENTIONAL"]["id"]
        # 0.60 * 1.009856 * 0.60 = 0.36354816, rounded to four places, and the
        # 68.0 fresh motility recorded at collection plays no part.
        assert recommendation["expected_conception_rate"] == pytest.approx(
            0.3635, abs=0.00001
        )
        assert recommendation["expected_conception_rate"] == pytest.approx(
            expected_conception_rate("CONVENTIONAL", 24.64, 60.0, 0.00), abs=0.00001
        )
