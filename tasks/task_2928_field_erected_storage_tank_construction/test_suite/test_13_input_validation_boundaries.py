"""Validation rules at their limits: grid shape, inclusive prep limits, permit
windows, the running volume ledger, a conditional voltage floor and the order in
which a body foreign key is resolved.

Each case shows the rule refusing one request and accepting the neighbouring one,
so the boundary itself is what is pinned.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_HOLIDAY_TEST_VOLTAGE_LOW,
    ERR_INSUFFICIENT_SURVEY_POINTS,
    ERR_PERMITTED_VOLUME_EXCEEDED,
    ERR_WATER_PERMIT_EXPIRED,
    ERR_WELDER_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_instant,
    assert_list_total,
    assert_money,
    assert_object_envelope,
    assert_source_ledger,
    assert_tank_state,
)
from test_helpers.constants import (
    CLOCK_BASE,
    COATING_ACCEPTED,
    COATING_DFT_RECORDED,
    COATING_PREP_ACCEPTED,
    COURSE_FITTED,
    DFT_NOT_EVALUATED,
    DFT_PASS,
    GHOST_UUID,
    PHASE_DESIGN_REGISTERED,
    PKG_PLANNED,
    PREP_SSPC_SP6,
    SCOPE_EXTERNAL_COATING,
    SCOPE_INTERNAL_LINING,
    SEAM_FIT_READY,
    WELDER_QUALIFIED,
    WITHDRAWAL_RESERVED,
)
from test_helpers.factories import (
    holiday_test_payload,
    point_readings,
    settlement_survey_payload,
    weld_log_payload,
    withdrawal_payload,
)
from test_helpers.test_users import CC1, ES1, QC1, welder_headers


class TestSurveyGridValidation:
    def test_a_reading_grid_that_does_not_match_the_package_is_refused(self, api):
        """Seven readings and a duplicated index are both grid failures, not shape ones.

        PRD: "The array must contain exactly as many entries as the package's
        `monitoring_point_count`, with `point_index` values running from 1 to that
        count and each value appearing exactly once; anything else is rejected with
        `ERR_INSUFFICIENT_SURVEY_POINTS`."

        Design: Corner/validations/survey_point_grid_mismatch_is_rejected
        """
        ctx = X.tank_with_package(api, clock=CLOCK_BASE)

        validate_error(
            api.create_settlement_survey(
                settlement_survey_payload(ctx.package_id, [100.0] * 7, 0.0), CC1
            ),
            ERR_INSUFFICIENT_SURVEY_POINTS,
            409,
        )

        duplicated = point_readings([100.0] * 8)
        duplicated[7]["point_index"] = 1
        validate_error(
            api.create_settlement_survey(
                settlement_survey_payload(ctx.package_id, point_readings=duplicated), CC1
            ),
            ERR_INSUFFICIENT_SURVEY_POINTS,
            409,
        )

        assert_list_total(
            api.list_settlement_surveys(CC1, {"foundation_package_id": ctx.package_id}), 0
        )
        package = X.read_foundation_package(api, ctx.package_id)
        assert package["status"] == PKG_PLANNED
        assert package["baseline_survey_id"] is None


class TestCoatingPreparationLimits:
    def test_preparation_exactly_on_both_limits_is_accepted(self, api):
        """Equal cleanliness and a spread of exactly five degrees both pass.

        PRD: "The achieved grade must be at least as clean as the specified grade,
        equality being acceptable; a shortfall is rejected with
        `ERR_SURFACE_PREP_DEFICIENT`."

        PRD: "The spread must be at least 5.0 degrees Fahrenheit, exactly 5.0 being
        acceptable, and a tighter spread risks condensation and is rejected with
        `ERR_DEW_POINT_SPREAD_INSUFFICIENT`."

        Design: Corner/validations/surface_prep_at_the_exact_limits_is_accepted
        """
        X.set_clock(api, CLOCK_BASE)
        tank = X.create_tank(api)
        application = X.create_coating(
            api,
            tank["id"],
            scope=SCOPE_EXTERNAL_COATING,
            specified_prep_standard=PREP_SSPC_SP6,
            specified_min_dft_mils=8.0,
        )

        prepared = X.surface_prep(
            api,
            application["id"],
            achieved_prep_standard=PREP_SSPC_SP6,
            profile_mils=2.5,
            dew_point_spread_f=5.0,
        )

        assert prepared["status"] == COATING_PREP_ACCEPTED
        assert prepared["achieved_prep_standard"] == PREP_SSPC_SP6
        assert prepared["profile_mils"] == 2.5
        assert prepared["dew_point_spread_f"] == 5.0
        assert prepared["dft_verdict"] == DFT_NOT_EVALUATED
        assert prepared["rework_cycle_count"] == 0

    def test_the_voltage_floor_binds_an_internal_lining_and_not_an_external_coat(self, api):
        """Identical readings and one voltage, two different answers.

        PRD: "When the `scope` is `INTERNAL_LINING`, `test_voltage_v` must be at
        least 67.5 multiplied by `specified_min_dft_mils`, exactly at that floor
        being acceptable; below it the test is not probative and is rejected with
        `ERR_HOLIDAY_TEST_VOLTAGE_LOW`."

        PRD: "An `EXTERNAL_COATING` scope has no voltage floor whatsoever."

        Design: Corner/validations/holiday_voltage_floor_applies_only_to_internal_linings
        """
        X.set_clock(api, CLOCK_BASE)
        tank = X.create_tank(api)
        internal = X.create_coating(api, tank["id"], scope=SCOPE_INTERNAL_LINING)
        external = X.create_coating(api, tank["id"], scope=SCOPE_EXTERNAL_COATING)
        for application_id in (internal["id"], external["id"]):
            X.surface_prep(api, application_id)
            recorded = X.dft_readings(api, application_id, [[10.0, 11.0, 12.0]])
            assert recorded["status"] == COATING_DFT_RECORDED
            assert recorded["dft_verdict"] == DFT_PASS
            assert recorded["computed_spot_average_min_mils"] == 11.00
            assert recorded["computed_spot_average_max_mils"] == 11.00
            assert recorded["computed_overall_average_mils"] == 11.00
            assert recorded["computed_min_gauge_reading_mils"] == 10.00

        validate_error(
            api.holiday_test(internal["id"], holiday_test_payload(0, 600.0), QC1),
            ERR_HOLIDAY_TEST_VOLTAGE_LOW,
            409,
        )
        internal_after = X.read_coating(api, internal["id"])
        assert internal_after["status"] == COATING_DFT_RECORDED
        assert internal_after["holidays_found"] is None

        external_after = X.holiday_test(api, external["id"], 0, 600.0)
        assert external_after["status"] == COATING_ACCEPTED
        assert external_after["holidays_found"] == 0
        assert external_after["holiday_test_voltage_v"] == 600.0

        assert_tank_state(X.read_tank(api, tank["id"]), phase=PHASE_DESIGN_REGISTERED)


class TestWaterPermitAndVolumeLedger:
    def test_a_window_running_past_the_permit_is_refused_at_the_second(self, api):
        """One window ends four hours late and is refused; the next ends exactly on time.

        PRD: "The end must be strictly after the start (`ERR_INVALID_WINDOW`), and
        the source's `permit_expiry_utc` must be at or after `window_end_utc`, since
        a withdrawal may not run past the permit (`ERR_WATER_PERMIT_EXPIRED`)."

        Design: Corner/validations/withdrawal_window_outliving_the_permit_is_rejected
        """
        X.set_clock(api, CLOCK_BASE)
        tank = X.create_tank(api)
        source = X.create_water_source(
            api, source_name="Municipal Hydrant 12", permit_expiry_utc="2026-09-01T00:00:00Z"
        )
        plan = X.create_plan(api, tank["id"], source["id"], fill_volume_gal=200000.0)
        version = X.source_version(api, source["id"])

        validate_error(
            api.create_water_withdrawal(
                withdrawal_payload(
                    plan["id"], source["id"], "2026-08-31T20:00:00Z", "2026-09-01T04:00:00Z",
                    100.0, 100000.0, version,
                ),
                ES1,
            ),
            ERR_WATER_PERMIT_EXPIRED,
            409,
        )
        untouched = X.read_water_source(api, source["id"])
        assert untouched["version"] == version
        assert_source_ledger(untouched, 0.00, 0.00, 2000000.00)

        accepted = assert_object_envelope(
            api.create_water_withdrawal(
                withdrawal_payload(
                    plan["id"], source["id"], "2026-08-31T20:00:00Z", "2026-09-01T00:00:00Z",
                    100.0, 100000.0, version,
                ),
                ES1,
            ),
            201,
        )
        assert accepted["status"] == WITHDRAWAL_RESERVED
        assert_source_ledger(
            X.read_water_source(api, source["id"]), 100000.00, 0.00, 1900000.00
        )

    def test_individually_small_reservations_still_exhaust_the_permit(self, api):
        """The rule reads the running ledger, and the exact remainder is acceptable.

        PRD: "Separately, the requested `reserved_volume_gal` may not exceed the
        source's current `available_volume_gal`; exactly equal is accepted, and
        oversubscribing the permit is rejected with
        `ERR_PERMITTED_VOLUME_EXCEEDED`."

        Design: Corner/validations/individually_valid_reservations_collectively_exceed_the_permit
        """
        X.set_clock(api, CLOCK_BASE)
        tank = X.create_tank(api)
        source = X.create_water_source(api)
        plan = X.create_plan(api, tank["id"], source["id"], fill_volume_gal=2000000.0)

        first = X.reserve_withdrawal(
            api, plan["id"], source["id"],
            "2026-08-11T00:00:00Z", "2026-08-11T20:00:00Z", 400.0, 1200000.0,
        )
        assert first["status"] == WITHDRAWAL_RESERVED
        assert_source_ledger(
            X.read_water_source(api, source["id"]), 1200000.00, 0.00, 800000.00
        )
        version = X.source_version(api, source["id"])

        validate_error(
            api.create_water_withdrawal(
                withdrawal_payload(
                    plan["id"], source["id"], "2026-08-12T00:00:00Z", "2026-08-12T20:00:00Z",
                    400.0, 1200000.0, version,
                ),
                ES1,
            ),
            ERR_PERMITTED_VOLUME_EXCEEDED,
            409,
        )
        held = X.read_water_source(api, source["id"])
        assert held["version"] == version
        assert_money(held["available_volume_gal"], 800000.00, "available volume")

        exact = assert_object_envelope(
            api.create_water_withdrawal(
                withdrawal_payload(
                    plan["id"], source["id"], "2026-08-12T00:00:00Z", "2026-08-12T20:00:00Z",
                    400.0, 800000.0, version,
                ),
                ES1,
            ),
            201,
        )
        assert exact["status"] == WITHDRAWAL_RESERVED
        assert_source_ledger(
            X.read_water_source(api, source["id"]), 2000000.00, 0.00, 0.00
        )
        assert_list_total(
            api.list_water_withdrawals(ES1, {"water_source_id": source["id"]}), 2
        )


class TestForeignKeyResolutionOrder:
    def test_an_unresolvable_welder_id_answers_before_any_qualification_check(self, api):
        """The acting identity matches the body, so only the missing row can answer.

        PRD: "Sixth comes resolution of foreign keys supplied in the body, in the
        order the endpoint declares its inputs, using the same mapping."

        PRD: "Then come the safety checks, in this order: welder qualification
        currency (`ERR_WELDER_NOT_QUALIFIED`), then qualified thickness range
        (`ERR_THICKNESS_OUT_OF_QUALIFIED_RANGE`), then achieved surface preparation
        grade (`ERR_SURFACE_PREP_DEFICIENT`), then dew-point spread
        (`ERR_DEW_POINT_SPREAD_INSUFFICIENT`), then holiday-test voltage
        (`ERR_HOLIDAY_TEST_VOLTAGE_LOW`), then the dry-film verdict gate on
        acceptance (`ERR_DFT_NOT_PASSED`), then segregation of duties
        (`ERR_SEGREGATION_OF_DUTIES`)."

        Design: Corner/validations/weld_log_resolves_the_welder_fk_before_judging_qualification
        """
        ctx = X.erecting_tank(api, clock=CLOCK_BASE)
        welder = X.create_welder(api)
        seam = X.create_seam(api, ctx.course_id, "V1", 1)

        validate_error(
            api.weld_log(
                seam["id"], weld_log_payload(GHOST_UUID), welder_headers(GHOST_UUID)
            ),
            ERR_WELDER_NOT_FOUND,
            404,
        )

        after = X.read_seam(api, seam["id"])
        assert after["status"] == SEAM_FIT_READY
        assert after["welder_id"] is None
        assert after["welded_at_utc"] is None

        welder_after = X.read_welder(api, welder["id"])
        assert welder_after["qualification_status"] == WELDER_QUALIFIED
        # PRD: "On creation the welder's `qualification_status` is `QUALIFIED`,
        # `last_weld_date_utc` is set to `qualification_date_utc`" — the refused
        # weld log must not have moved that base date forward.
        assert_instant(
            welder_after["last_weld_date_utc"],
            welder["qualification_date_utc"],
            "last_weld_date_utc",
        )
        assert X.read_course(api, ctx.course_id)["status"] == COURSE_FITTED
