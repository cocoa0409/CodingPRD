"""Derived figures pinned to the arithmetic the contract writes out.

Each family walks a computation to the exact place where a plausible shortcut -
rounding a sum, forgetting a floor, counting calendar months, comparing serial
suffixes numerically - would produce a different number.
"""

import pytest

from test_helpers import (
    approx2,
    approx4,
    assert_decimal_places,
    assert_hardness_band,
    assert_serial_number,
    assert_version_unchanged,
    compliance_engineer_headers,
    data_of,
    efficiency_test_payload,
    ERR_SUPPLIER_SCORE_BELOW_FLOOR,
    ERR_WARRANTY_COVERAGE_EXPIRED,
    make_full_plant,
    make_model,
    make_test_cell,
    plant_operator_headers,
    qualify_payload,
    quality_inspector_headers,
    recall_campaign_payload,
    scope_payload,
    supplier_payload,
    supplier_quality_headers,
    validate_error,
    validate_paginated,
    validate_success,
    warranty_analyst_headers,
    warranty_claim_payload,
    WINDOW_AUG04_06_10,
    WINDOW_AUG04_22_AUG05_02,
    fixtures as x,
)

#: The three August serials and the two September ones, in labelling order.
AUGUST_SERIALS = (
    "GX50-T-202608-00001",
    "GX50-T-202608-00002",
    "GX50-T-202608-00003",
)
SEPTEMBER_SERIALS = ("GX50-T-202609-00001", "GX50-T-202609-00002")


def _score(api, name, audit_score, defect_ppm, open_capa_count):
    """Register a supplier on three inputs and score it on the same three."""
    supplier = data_of(
        api.create_supplier(
            supplier_payload(
                name=name,
                audit_score=audit_score,
                defect_ppm=defect_ppm,
                open_capa_count=open_capa_count,
            ),
            supplier_quality_headers(),
        )
    )
    response = api.qualify_supplier(
        supplier["id"],
        qualify_payload(
            audit_score=audit_score,
            defect_ppm=defect_ppm,
            open_capa_count=open_capa_count,
        ),
        supplier_quality_headers(),
    )
    return supplier, response


class TestSupplierScoreBandBoundary:
    """Eighty-five point zero qualifies; one hundredth less does not."""

    def test_01_a_score_landing_exactly_on_the_floor_qualifies(self, api):
        """Ninety on audit, 1125 ppm and one open action come to exactly 85.00.

        PRD: "Band selection reads the **rounded** score, never the unrounded
        weighted sum. A score of at least 85.00 earns `QUALIFIED`; a score of at least
        70.00 but below 85.00 earns `CONDITIONAL`; anything below 70.00 is refused
        outright with `ERR_SUPPLIER_SCORE_BELOW_FLOOR`, and the same score-floor rule is
        declared on the requalification action as well as on scoring."

        Design: Corner/calculations/supplier_score_at_qualified_floor_and_one_cent_below
        """
        _supplier, response = _score(api, "Borderline Brass", 90, 1125, 1)

        scored = validate_success(response)

        assert scored["qualification_score"] == approx2(85.00)
        assert scored["qualification_status"] == "QUALIFIED"
        assert_decimal_places(scored["qualification_score"], 2)

    def test_02_one_more_defect_per_million_drops_the_supplier_a_band(self, api):
        """84.993 rounds to 84.99, which is a hundredth short of qualifying.

        PRD: "The three components are then combined with weights of 0.40 for the
        audit component, 0.35 for the parts-per-million component and 0.25 for the
        corrective-action component, and the weighted sum is rounded half up to two
        decimal places to become `qualification_score`."

        Design: Corner/calculations/supplier_score_at_qualified_floor_and_one_cent_below
        """
        _supplier, response = _score(api, "Borderline Bronze", 90, 1126, 1)

        scored = validate_success(response)

        assert scored["qualification_score"] == approx2(84.99)
        assert scored["qualification_status"] == "CONDITIONAL"
        assert_decimal_places(scored["qualification_score"], 2)
        assert scored["blocked_lot_count"] == 0


class TestSupplierScoreFloorAndComponentClamps:
    """Below seventy nothing is written, and no component may go negative."""

    def test_03_a_score_below_the_conditional_floor_is_refused_outright(self, api):
        """Neither a weak supplier nor a well-audited one with catastrophic ppm passes.

        PRD: "The parts-per-million component is 100 reduced by the `defect_ppm`
        divided by 50, with the result floored at 0 so a catastrophically bad supplier
        contributes zero rather than a negative amount."

        Design: Corner/calculations/supplier_score_below_conditional_floor_is_rejected_with_clamped_components
        """
        weak, weak_response = _score(api, "Weak Works", 60, 4000, 3)
        clamped, clamped_response = _score(api, "Clamp Castings", 100, 10000, 0)

        validate_error(
            weak_response, ERR_SUPPLIER_SCORE_BELOW_FLOOR, expected_status=422
        )
        validate_error(
            clamped_response, ERR_SUPPLIER_SCORE_BELOW_FLOOR, expected_status=422
        )
        for supplier in (weak, clamped):
            after = validate_success(
                api.get_supplier(supplier["id"], supplier_quality_headers())
            )
            assert after["qualification_status"] == "PENDING"
            assert after["qualification_score"] is None
            assert after["qualified_until"] is None

    def test_04_the_refused_calls_wrote_nothing_and_the_capa_floor_is_observable(
        self, api
    ):
        """Ten open actions contribute zero rather than minus twenty-five.

        PRD: "The corrective-action component is 100 reduced by 12.5 for each open
        corrective action, again floored at 0 — which means eight or more open actions
        contribute nothing."

        Design: Corner/calculations/supplier_score_below_conditional_floor_is_rejected_with_clamped_components
        """
        weak, _weak_response = _score(api, "Weak Works", 60, 4000, 3)
        _floored, floored_response = _score(api, "Capa Mountain", 100, 0, 10)

        after = validate_success(
            api.get_supplier(weak["id"], supplier_quality_headers())
        )
        assert_version_unchanged(weak, after)
        scored = validate_success(floored_response)
        assert scored["qualification_score"] == approx2(75.00)
        assert scored["qualification_status"] == "CONDITIONAL"


def _a_gas_unit_shipped_on_the_fifth_of_august(api):
    """One GX50-T unit in the field, shipped at 2026-08-05T06:00:00Z."""
    plant = make_full_plant(api)
    unit_id = x.ship_unit(api, plant, hardness_gpg=12.0)
    return plant, unit_id


def _claim_at(api, unit_id, clock):
    """Move the clock, then open a tank-leak claim that freezes its service months."""
    x.set_clock(api, clock)
    return data_of(
        api.create_warranty_claim(
            warranty_claim_payload(unit_id, reported_water_hardness_gpg=14.0),
            warranty_analyst_headers(),
        )
    )


class TestWarrantyPayoutLineRounding:
    """Each allowance is rounded before the three are added, never after."""

    def test_05_a_fully_covered_tank_leak_pays_the_three_allowances_whole(self, api):
        """Seventy-two service months is the last month of full tank coverage.

        PRD: "The part allowance is a fixed catalogue figure keyed on the failure
        mode: 41,500 cents for both `TANK_LEAK` and `ANODE_DEPLETION`, 4,200 cents for
        `THERMOSTAT`, 8,200 cents for `GAS_VALVE`, 52,000 cents for `COMPRESSOR`, and 0
        for `OTHER`."

        Design: Corner/calculations/warranty_payout_rounds_each_line_before_summing
        """
        _plant, unit_id = _a_gas_unit_shipped_on_the_fifth_of_august(api)

        claim = _claim_at(api, unit_id, "2032-07-04T06:00:00Z")
        validated = validate_success(
            api.validate_claim(claim["id"], warranty_analyst_headers())
        )

        assert validated["months_in_service_at_report"] == 72
        assert validated["coverage_pct"] == approx2(1.00)
        assert validated["approved_payout_cents"] == 57350
        assert validated["status"] == "VALIDATED"

    def test_06_at_the_half_share_two_lines_round_half_up_before_summing(self, api):
        """6,262.5 and 1,662.5 both round up, so the total is 28,676 and not 28,675.

        PRD: "At the half share of 0.50 the labour line of 12,525 cents halves to
        6,262.5 cents and rounds half up to 6,263, and the freight line of 3,325 cents
        halves to 1,662.5 and rounds half up to 1,663 — the two places where the half-up
        direction is directly observable."

        Design: Corner/calculations/warranty_payout_rounds_each_line_before_summing
        """
        _plant, unit_id = _a_gas_unit_shipped_on_the_fifth_of_august(api)

        claim = _claim_at(api, unit_id, "2032-08-03T06:00:00Z")
        validated = validate_success(
            api.validate_claim(claim["id"], warranty_analyst_headers())
        )

        assert validated["months_in_service_at_report"] == 73
        assert validated["coverage_pct"] == approx2(0.50)
        assert validated["approved_payout_cents"] == 28676
        assert validated["status"] == "VALIDATED"

    def test_07_beyond_ninety_six_months_the_claim_can_never_be_validated(self, api):
        """Zero coverage is a refusal, and the earlier claim's frozen months stand.

        PRD: "Whenever the resolved coverage is 0.00 the validation is refused with
        `ERR_WARRANTY_COVERAGE_EXPIRED` and the claim stays `OPEN`; note that a claim can
        therefore be denied for being out of warranty, but it can never be *validated* at
        zero coverage."

        Design: Corner/calculations/warranty_payout_rounds_each_line_before_summing
        """
        _plant, unit_id = _a_gas_unit_shipped_on_the_fifth_of_august(api)

        early_claim = _claim_at(api, unit_id, "2032-07-04T06:00:00Z")
        data_of(api.validate_claim(early_claim["id"], warranty_analyst_headers()))
        late_claim = _claim_at(api, unit_id, "2034-07-24T06:00:00Z")

        response = api.validate_claim(late_claim["id"], warranty_analyst_headers())

        validate_error(response, ERR_WARRANTY_COVERAGE_EXPIRED, expected_status=422)
        still_open = validate_success(
            api.get_warranty_claim(late_claim["id"], warranty_analyst_headers())
        )
        assert still_open["status"] == "OPEN"
        assert still_open["coverage_pct"] is None
        assert still_open["approved_payout_cents"] is None
        assert still_open["months_in_service_at_report"] == 97
        frozen = validate_success(
            api.get_warranty_claim(early_claim["id"], warranty_analyst_headers())
        )
        unit = validate_success(api.get_heater_unit(unit_id, warranty_analyst_headers()))
        assert frozen["months_in_service_at_report"] == 72
        assert unit["months_in_service"] == 97


class TestMonthsInServiceFloorsOnThirtyDayUnits:
    """Service age advances in 30-day units, truncated downward."""

    def test_08_the_thirtieth_day_is_the_first_service_month(self, api):
        """Twenty-nine days and twenty-three fifty-nine is still month zero.

        PRD: "From shipment onward a unit read reports `months_in_service`,
        recomputed on every read as the whole number of 30-day months that have elapsed
        between `shipped_at` and the current logical clock, truncated downward and never
        rounded up; it stays null while `shipped_at` is null."

        Design: Corner/calculations/months_in_service_floors_on_thirty_day_units
        """
        _plant, unit_id = _a_gas_unit_shipped_on_the_fifth_of_august(api)

        at_shipment = validate_success(
            api.get_heater_unit(unit_id, warranty_analyst_headers())
        )
        x.set_clock(api, "2026-09-04T05:59:00Z")
        one_minute_short = validate_success(
            api.get_heater_unit(unit_id, warranty_analyst_headers())
        )
        x.set_clock(api, "2026-09-04T06:00:00Z")
        exactly_thirty_days = validate_success(
            api.get_heater_unit(unit_id, warranty_analyst_headers())
        )

        assert at_shipment["months_in_service"] == 0
        assert at_shipment["shipped_at"].startswith("2026-08-05T06:00:00")
        assert one_minute_short["months_in_service"] == 0
        assert exactly_thirty_days["months_in_service"] == 1

    def test_09_a_unit_that_never_shipped_reports_no_service_age_at_all(self, api):
        """The figure stays null rather than falling back to zero.

        PRD: "This figure is derived from the logical clock alone and never from the
        host wall clock."

        Design: Corner/calculations/months_in_service_floors_on_thirty_day_units
        """
        plant, _shipped_id = _a_gas_unit_shipped_on_the_fifth_of_august(api)

        staged_id = x.stage_unit(api, plant)
        x.set_clock(api, "2026-09-04T06:00:00Z")
        staged = validate_success(
            api.get_heater_unit(staged_id, warranty_analyst_headers())
        )

        assert staged["build_status"] == "COMPONENTS_STAGED"
        assert staged["shipped_at"] is None
        assert staged["months_in_service"] is None


class TestWaterHardnessBandEdges:
    """Every band boundary belongs to the band below it."""

    @pytest.mark.parametrize(
        "hardness,band",
        [
            (3.49, "SOFT"),
            (3.5, "MODERATE"),
            (7.0, "MODERATE"),
            (10.5, "HARD"),
            (10.51, "VERY_HARD"),
        ],
    )
    def test_10_each_boundary_grain_falls_in_the_declared_band(self, api, hardness, band):
        """3.5 and 7.0 are MODERATE, 10.5 is HARD, and 10.51 tips over.

        PRD: "Water chemistry is banded with boundaries that must be read exactly as
        written. A hardness below 3.5 grains per gallon is `SOFT`; from 3.5 up to and
        including 7.0 is `MODERATE`; above 7.0 up to and including 10.5 is `HARD`; above
        10.5 is `VERY_HARD`."

        Design: Corner/calculations/water_hardness_band_boundaries_are_inclusive_upward
        """
        plant = make_full_plant(api)

        unit_id = x.ship_unit(api, plant, hardness_gpg=hardness)
        unit = validate_success(api.get_heater_unit(unit_id, plant_operator_headers()))

        assert_hardness_band(unit, band)
        assert unit["install_water_hardness_gpg"] == approx2(hardness)

    def test_11_five_units_across_the_bands_each_keep_the_hardness_posted(self, api):
        """The multiplier travels with the band, and the reading is stored verbatim.

        PRD: "The band is stored as `water_hardness_band` and its exposure multiplier
        as `hardness_factor`: 0.80 for `SOFT`, 1.00 for `MODERATE`, 1.35 for `HARD` and
        1.80 for `VERY_HARD`."

        Design: Corner/calculations/water_hardness_band_boundaries_are_inclusive_upward
        """
        plant = make_full_plant(api)

        expected = [
            (3.49, "SOFT", 0.80),
            (3.5, "MODERATE", 1.00),
            (7.0, "MODERATE", 1.00),
            (10.5, "HARD", 1.35),
            (10.51, "VERY_HARD", 1.80),
        ]
        for hardness, band, factor in expected:
            unit = validate_success(
                api.get_heater_unit(
                    x.ship_unit(api, plant, hardness_gpg=hardness),
                    plant_operator_headers(),
                )
            )
            assert unit["build_status"] == "SHIPPED"
            assert unit["install_water_hardness_gpg"] == approx2(hardness)
            assert unit["water_hardness_band"] == band
            assert unit["hardness_factor"] == approx2(factor)


def _three_assembled_units_awaiting_their_labels(api):
    """Three interchangeable units, created in a known order and all ASSEMBLED."""
    plant = make_full_plant(api)
    first = x.assemble_unit(api, plant)
    second = x.assemble_unit(api, plant)
    third = x.assemble_unit(api, plant)
    return plant, first, second, third


class TestSerialSequenceFollowsLabelOrder:
    """The sequence counts serialised siblings, not rows or identifiers."""

    def test_12_the_unit_labelled_first_takes_the_first_serial(self, api):
        """Created last, labelled first, and therefore numbered 00001.

        PRD: "The third is a sequence number, left-padded with zeros to a width of
        five digits, whose value is one more than the count of units that share this
        unit's `product_model_id` **and** its `production_period` **and** already hold a
        non-null `serial_number`."

        Design: Corner/calculations/serial_sequence_follows_label_call_order_not_creation_order
        """
        _plant, first, second, third = _three_assembled_units_awaiting_their_labels(api)

        labelled_third = validate_success(api.label_unit(third, plant_operator_headers()))
        labelled_first = validate_success(api.label_unit(first, plant_operator_headers()))
        labelled_second = validate_success(
            api.label_unit(second, plant_operator_headers())
        )

        assert labelled_third["serial_number"] == AUGUST_SERIALS[0]
        assert labelled_first["serial_number"] == AUGUST_SERIALS[1]
        assert labelled_second["serial_number"] == AUGUST_SERIALS[2]

    def test_13_every_serial_is_prefix_period_and_a_five_digit_sequence(self, api):
        """The cohort key loses its hyphen and the counter is zero-padded.

        PRD: "The second is the unit's `production_period` with its hyphen removed,
        so a cohort key of `2026-08` contributes `202608`."

        Design: Corner/calculations/serial_sequence_follows_label_call_order_not_creation_order
        """
        plant, first, second, third = _three_assembled_units_awaiting_their_labels(api)

        for sequence, unit_id in enumerate((third, first, second), start=1):
            labelled = validate_success(api.label_unit(unit_id, plant_operator_headers()))
            assert_serial_number(labelled, "GX50-T", "2026-08", sequence)
            assert labelled["label_status"] == "APPLIED"
            assert labelled["build_status"] == "LABELED"
        model = validate_success(
            api.get_product_model(plant.model_id, compliance_engineer_headers())
        )
        assert model["label_serial_prefix"] == "GX50-T"


def _two_production_months_of_labelled_units(api):
    """Three August units and two September units of the same model.

    The September lot is opened after the clock moves on, so its cohort key differs
    and its sequence counter restarts at one.
    """
    plant = make_full_plant(api)
    august = [x.label_unit(api, plant) for _ in range(3)]
    x.set_clock(api, "2026-09-10T06:00:00Z")
    september_lot = x.make_released_tank_lot(
        api, plant.model_id, plant.batch_id, lot_code="TL-002", planned_quantity=40
    )
    plant.tank_lot_id = september_lot
    september = [x.label_unit(api, plant) for _ in range(2)]
    return plant, august, september


class TestRecallScopeComparesWholeSerialStrings:
    """The range is ASCII string arithmetic over the whole serial, not its tail."""

    def test_14_a_range_spanning_two_cohorts_counts_three_of_five_units(self, api):
        """The second August unit through the first September unit is three units.

        PRD: "The affected population is then the set of units belonging to
        `scope_product_model_id` that hold a non-null `serial_number` lying within the
        inclusive range under plain ASCII string comparison — not numeric comparison of the
        trailing sequence — and whose `build_status` is `LABELED`, `SHIPPED` or `HELD`."

        Design: Corner/calculations/recall_scope_range_compares_full_serial_strings
        """
        plant, august, september = _two_production_months_of_labelled_units(api)

        campaign = data_of(
            api.create_recall_campaign(
                recall_campaign_payload(plant.model_id), warranty_analyst_headers()
            )
        )
        scoped = validate_success(
            api.scope_campaign(
                campaign["id"],
                scope_payload(AUGUST_SERIALS[1], SEPTEMBER_SERIALS[0]),
                warranty_analyst_headers(),
            )
        )

        assert len(august) == 3 and len(september) == 2
        assert scoped["status"] == "SCOPED"
        assert scoped["affected_unit_count"] == 3
        assert scoped["serial_range_start"] == AUGUST_SERIALS[1]
        assert scoped["serial_range_end"] == SEPTEMBER_SERIALS[0]
        assert scoped["per_unit_remedy_cost_cents"] == 20700
        assert scoped["estimated_remedy_cost_cents"] == 62100

    def test_15_the_sequence_restarts_in_the_new_cohort_and_the_last_unit_is_outside(
        self, api
    ):
        """September numbering begins at 00001 again, and 00002 is above the range end.

        PRD: "Units can be listed filtered by `tank_lot_id`, `product_model_id`,
        `gas_control_lot_id`, `safety_valve_lot_id`, `build_status`, `production_period` or
        `serial_number`."

        Design: Corner/calculations/recall_scope_range_compares_full_serial_strings
        """
        _plant, _august, september = _two_production_months_of_labelled_units(api)

        rows, meta = validate_paginated(
            api.list_heater_units(
                warranty_analyst_headers(),
                {"serial_number": SEPTEMBER_SERIALS[0], "limit": 10, "offset": 0},
            )
        )
        excluded = validate_success(
            api.get_heater_unit(september[1], warranty_analyst_headers())
        )

        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [september[0]]
        assert rows[0]["production_period"] == "2026-09"
        assert excluded["serial_number"] == SEPTEMBER_SERIALS[1]


def _a_first_hour_and_a_recovery_run_on_one_model(api):
    """One model with a single-unit FHR run and a single-unit recovery run booked."""
    model_id = make_model(api)["id"]
    cell_id = make_test_cell(api)["id"]
    first_hour = data_of(
        api.create_efficiency_test(
            efficiency_test_payload(
                model_id,
                cell_id,
                window=WINDOW_AUG04_06_10,
                test_type="FIRST_HOUR_RATING",
                sample_size=1,
            ),
            compliance_engineer_headers(),
        )
    )
    recovery = data_of(
        api.create_efficiency_test(
            efficiency_test_payload(
                model_id,
                cell_id,
                window=WINDOW_AUG04_22_AUG05_02,
                test_type="RECOVERY",
                sample_size=1,
            ),
            compliance_engineer_headers(),
        )
    )
    x.set_clock(api, "2026-08-05T06:00:00Z")
    return model_id, first_hour["id"], recovery["id"]


class TestFlatRatingFloors:
    """Two run types whose floor is a constant, immune to model attributes."""

    def test_16_the_flat_floors_are_thirty_gallons_and_ten_gallons_an_hour(self, api):
        """Exactly thirty passes at zero margin; 9.9 fails by a tenth.

        PRD: "For a `FIRST_HOUR_RATING` or `RECOVERY` run the floor is a flat constant
        and neither the model's `fuel_type` nor its `nominal_capacity_gallons` is consulted:
        `effective_minimum` is 30.0 gallons for a first-hour-rating run and 10.0 gallons per
        hour for a recovery run."

        Design: Corner/calculations/rating_floor_check_ignores_fuel_and_capacity
        """
        _model_id, first_hour_id, recovery_id = _a_first_hour_and_a_recovery_run_on_one_model(api)

        first_hour = validate_success(
            api.record_test_result(
                first_hour_id, {"measured_value": 30.0}, quality_inspector_headers()
            )
        )
        recovery = validate_success(
            api.record_test_result(
                recovery_id, {"measured_value": 9.9}, quality_inspector_headers()
            )
        )

        assert first_hour["effective_minimum"] == approx4(30.0000)
        assert first_hour["margin"] == approx4(0.0000)
        assert first_hour["status"] == "PASSED"
        assert recovery["effective_minimum"] == approx4(10.0000)
        assert recovery["margin"] == approx4(-0.1000)
        assert recovery["status"] == "FAILED"

    def test_17_neither_the_sample_derate_nor_the_insulation_credit_shifts_them(
        self, api
    ):
        """A single-unit sample on an R-20 model leaves both constants untouched.

        PRD: "Third**, a sample derate is added, keyed on the `sample_size` clamped at
        3 — a single-unit sample adds 0.02, a two-unit sample adds 0.01, and a sample of
        three or more units adds nothing at all."

        Design: Corner/calculations/rating_floor_check_ignores_fuel_and_capacity
        """
        model_id, first_hour_id, recovery_id = _a_first_hour_and_a_recovery_run_on_one_model(api)

        first_hour = validate_success(
            api.record_test_result(
                first_hour_id, {"measured_value": 30.0}, quality_inspector_headers()
            )
        )
        recovery = validate_success(
            api.record_test_result(
                recovery_id, {"measured_value": 9.9}, quality_inspector_headers()
            )
        )
        model = validate_success(
            api.get_product_model(model_id, compliance_engineer_headers())
        )

        assert first_hour["sample_size"] == 1
        assert first_hour["effective_minimum"] == approx4(30.0000)
        assert recovery["effective_minimum"] == approx4(10.0000)
        assert model["fhr_rated"] is None
        assert model["recovery_rate_rated"] is None
        assert model["certification_status"] == "TEST_PENDING"
