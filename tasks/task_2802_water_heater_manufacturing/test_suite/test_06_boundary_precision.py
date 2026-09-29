"""Inclusive thresholds walked one unit either side of the boundary.

The holiday ceiling decides a verdict field and the compliance margin decides a
terminal state; both are pinned at four decimal places, so a two-decimal
implementation cannot even express the distance being measured.
"""

import pytest

from test_helpers import (
    approx4,
    certification_payload,
    compliance_engineer_headers,
    data_of,
    efficiency_test_payload,
    ERR_INSUFFICIENT_TEST_SAMPLE,
    heat_pump_model_payload,
    holiday_inspection_payload,
    lot_inspections,
    make_fired_batch,
    make_lined_tank_lot,
    make_model,
    make_test_cell,
    plant_operator_headers,
    quality_inspector_headers,
    tank_lot_version,
    validate_error,
    validate_success,
    WINDOW_AUG02_06_10,
    WINDOW_AUG02_22_AUG03_02,
    WINDOW_AUG03_14_18,
    fixtures as x,
)


def _lined_lot_for_a_hundred_tank_sample(api):
    """A LINED lot large enough that a 100-tank sample is meaningful."""
    model_id = make_model(api)["id"]
    batch = make_fired_batch(api)
    return make_lined_tank_lot(api, model_id, batch.batch_id)


def _file_holiday_count(api, lot_id, holiday_count, **overrides):
    """File one holiday record over a 100-tank sample against the current version."""
    return data_of(
        api.create_lining_inspection(
            holiday_inspection_payload(
                lot_id,
                tank_lot_version(api, lot_id),
                sample_size=100,
                holiday_count=holiday_count,
                **overrides,
            ),
            quality_inspector_headers(),
        )
    )


class TestHolidayDensityCeiling:
    """The 0.50 discontinuity ceiling is inclusive."""

    def test_01_a_density_exactly_at_the_ceiling_passes(self, api):
        """Fifty holidays over a hundred tanks is 0.5000, which is not a failure.

        PRD: "For a `HOLIDAY` record the service then computes `holidays_per_tank`
        as the `holiday_count` divided by the `sample_size`, rounded half up to four
        decimal places, and sets `result` to `FAIL` when that density is **strictly
        greater** than 0.50 and to `PASS` otherwise — a density of exactly 0.5000
        passes."

        Design: Difficulty/boundary_precision_check/holiday_density_exactly_at_max_passes
        """
        lot_id = _lined_lot_for_a_hundred_tank_sample(api)

        record = _file_holiday_count(api, lot_id, 50)
        lot = validate_success(api.get_tank_lot(lot_id, quality_inspector_headers()))

        assert record["holidays_per_tank"] == approx4(0.5000)
        assert record["result"] == "PASS"
        assert lot["status"] == "LINED"

    def test_02_a_density_just_below_the_ceiling_passes(self, api):
        """Forty-nine holidays is 0.4900, one hundredth clear of the boundary.

        PRD: "For a `HOLIDAY` record the service then computes `holidays_per_tank`
        as the `holiday_count` divided by the `sample_size`, rounded half up to four
        decimal places, and sets `result` to `FAIL` when that density is **strictly
        greater** than 0.50 and to `PASS` otherwise — a density of exactly 0.5000
        passes."

        Design: Difficulty/boundary_precision_check/holiday_density_exactly_at_max_passes
        """
        lot_id = _lined_lot_for_a_hundred_tank_sample(api)

        record = _file_holiday_count(api, lot_id, 49)
        lot = validate_success(api.get_tank_lot(lot_id, quality_inspector_headers()))

        assert record["holidays_per_tank"] == approx4(0.4900)
        assert record["result"] == "PASS"
        assert lot["status"] == "LINED"

    def test_03_a_density_just_above_the_ceiling_fails_and_charges_its_scrap(self, api):
        """Fifty-one holidays is 0.5100 and condemns the five tanks it names.

        PRD: "When the computed `result` is `FAIL` the filing must additionally
        carry `scrap_quantity`, the number of tanks condemned by this inspection, which
        must be at least 1 and at most the lot's current `wip_quantity`; when the
        result is `PASS`, `scrap_quantity` must be omitted."

        Design: Difficulty/boundary_precision_check/holiday_density_exactly_at_max_passes
        """
        lot_id = _lined_lot_for_a_hundred_tank_sample(api)

        record = _file_holiday_count(api, lot_id, 51, scrap_quantity=5)
        lot = validate_success(api.get_tank_lot(lot_id, quality_inspector_headers()))

        assert record["holidays_per_tank"] == approx4(0.5100)
        assert record["result"] == "FAIL"
        assert lot["status"] == "LINING_REJECTED"
        assert lot["wip_quantity"] == 115
        assert lot["scrapped_quantity"] == 5
        assert lot["rework_count"] == 1

    def test_04_walking_the_boundary_leaves_only_the_last_record_current(self, api):
        """Three successive filings of one type keep only the newest as current.

        PRD: "Every accepted record stores the caller's `X-User-ID` as
        `inspector_user_id` and enters at `record_status` `CURRENT`; any earlier record
        of the **same** `inspection_type` on the same lot moves to `record_status`
        `SUPERSEDED`."

        Design: Difficulty/boundary_precision_check/holiday_density_exactly_at_max_passes
        """
        lot_id = _lined_lot_for_a_hundred_tank_sample(api)

        _file_holiday_count(api, lot_id, 49)
        _file_holiday_count(api, lot_id, 50)
        _file_holiday_count(api, lot_id, 51, scrap_quantity=5)

        rows = lot_inspections(api, lot_id)

        assert len(rows) == 3
        assert [row["record_status"] for row in rows] == [
            "SUPERSEDED",
            "SUPERSEDED",
            "CURRENT",
        ]
        assert [row["holiday_count"] for row in rows] == [49, 50, 51]


def _heat_pump_with_three_scheduled_uef_tests(api):
    """HP65-B on a 12-hour-cooldown cell, three windows spaced to respect it.

    At a two-unit sample the model's floor works out to exactly 2.8800, so the
    three readings below straddle it in the fourth decimal place.
    """
    model_id = make_model(api, heat_pump_model_payload())["id"]
    cell_id = make_test_cell(api)["id"]
    test_ids = []
    for window in (WINDOW_AUG02_06_10, WINDOW_AUG02_22_AUG03_02, WINDOW_AUG03_14_18):
        test_ids.append(
            data_of(
                api.create_efficiency_test(
                    efficiency_test_payload(
                        model_id, cell_id, window=window, sample_size=2
                    ),
                    compliance_engineer_headers(),
                )
            )["id"]
        )
    x.set_clock(api, "2026-08-05T06:00:00Z")
    return model_id, test_ids


class TestUefMarginZeroBoundary:
    """A signed margin of exactly 0.0000 is a pass, not a failure."""

    @pytest.mark.parametrize(
        "slot,measured,expected_margin,expected_status",
        [
            (0, 2.8799, -0.0001, "FAILED"),
            (1, 2.88, 0.0000, "PASSED"),
            (2, 2.8801, 0.0001, "PASSED"),
        ],
    )
    def test_05_the_terminal_state_turns_on_the_sign_of_a_four_decimal_margin(
        self, api, slot, measured, expected_margin, expected_status
    ):
        """One ten-thousandth either side of the floor decides PASSED or FAILED.

        PRD: "In all three cases `margin` is then the `measured_value` less the
        `effective_minimum`, rounded half up to four decimal places, and the outcome
        branches on its sign: a `margin` of 0 or more moves the test `SCHEDULED →
        PASSED`, while a negative `margin` moves it `SCHEDULED → FAILED`."

        Design: Difficulty/boundary_precision_check/uef_margin_exactly_zero_passes
        """
        _model_id, test_ids = _heat_pump_with_three_scheduled_uef_tests(api)

        recorded = validate_success(
            api.record_test_result(
                test_ids[slot],
                {"measured_value": measured},
                quality_inspector_headers(),
            )
        )

        assert recorded["effective_minimum"] == approx4(2.8800)
        assert recorded["margin"] == approx4(expected_margin)
        assert recorded["status"] == expected_status

    def test_06_a_zero_margin_passes_where_a_strict_comparison_would_fail_it(self, api):
        """The middle reading is the row a `margin > 0` pass condition gets wrong.

        PRD: "A margin of exactly 0.0000 passes."

        Design: Difficulty/boundary_precision_check/uef_margin_exactly_zero_passes
        """
        model_id, test_ids = _heat_pump_with_three_scheduled_uef_tests(api)

        for test_id, measured in zip(test_ids, (2.8799, 2.88, 2.8801)):
            data_of(
                api.record_test_result(
                    test_id, {"measured_value": measured}, quality_inspector_headers()
                )
            )

        exactly_at_the_floor = validate_success(
            api.get_efficiency_test(test_ids[1], compliance_engineer_headers())
        )
        model = validate_success(
            api.get_product_model(model_id, compliance_engineer_headers())
        )

        assert exactly_at_the_floor["margin"] == approx4(0.0000)
        assert exactly_at_the_floor["status"] == "PASSED"
        assert model["certification_status"] == "TEST_PENDING"

    def test_07_two_passing_uef_tests_are_still_short_of_the_submission_threshold(
        self, api
    ):
        """Only the two non-negative margins passed, so the programme is incomplete.

        PRD: "It requires the model to hold at least 3 `PASSED` `UEF` tests, at least
        one `PASSED` `FIRST_HOUR_RATING` test and at least one `PASSED` `RECOVERY` test;
        a model short on any of the three is refused with `ERR_INSUFFICIENT_TEST_SAMPLE`,
        and on a resubmission all three counts are re-evaluated afresh against the
        model's current passed tests rather than reusing the earlier figures."

        Design: Difficulty/boundary_precision_check/uef_margin_exactly_zero_passes
        """
        model_id, test_ids = _heat_pump_with_three_scheduled_uef_tests(api)

        for test_id, measured in zip(test_ids, (2.8799, 2.88, 2.8801)):
            data_of(
                api.record_test_result(
                    test_id, {"measured_value": measured}, quality_inspector_headers()
                )
            )
        cert = data_of(
            api.create_certification(
                certification_payload(model_id, x.model_version(api, model_id)),
                compliance_engineer_headers(),
            )
        )

        response = api.submit_certification(cert["id"], compliance_engineer_headers())

        validate_error(response, ERR_INSUFFICIENT_TEST_SAMPLE, expected_status=409)
