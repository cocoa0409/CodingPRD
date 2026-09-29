"""Requests that break two rules at once, where only one error may surface.

Each case pins a specific adjacent pair of the fixed rejection order: a state gate
against a safety check, a temporal check against a fiscal one, and a referential
check against a constraint.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_HOST_COURSE_NOT_ACCEPTED,
    ERR_SEAM_NOT_WELDABLE,
    ERR_WITHDRAWAL_CAPACITY_CONFLICT,
)
from test_helpers.assertions import assert_angle, assert_source_ledger
from test_helpers.constants import (
    ACTION_REVOKE,
    APP_DESIGNED,
    APP_INSTALLED,
    APP_NOZZLE,
    COURSE_WELDED,
    DISPOSAL_DISCHARGE_TO_POTW,
    SEAM_WELDED,
    SOURCE_MUNICIPAL,
    WELDER_REVOKED,
)
from test_helpers.test_users import ES1, welder_headers


class TestSeamStateOutranksWelderQualification:
    def _welded_seam_and_revoked_welder(self, api):
        ctx = X.welded_course(api)
        ctx.welder = X.welder_action(api, ctx.welder_id, ACTION_REVOKE, remarks="failed retest")
        return ctx

    def test_the_safety_rule_is_genuinely_violated_as_well(self, api):
        """The welder really has lost their qualification before the second attempt.

        PRD: "`REVOKE` is available from either `QUALIFIED` or `LAPSED` and
        drives the welder to the terminal `REVOKED` status with `revoked_at_utc`
        stamped from the logical clock; seams the welder has already completed keep
        their status, because revocation is not retroactive."

        Design: Difficulty/priority_pair_validation_conflict/seam_state_outranks_welder_qualification_safety
        """
        ctx = self._welded_seam_and_revoked_welder(api)

        assert ctx.welder["qualification_status"] == WELDER_REVOKED
        assert X.read_seam(api, ctx.seam_id)["status"] == SEAM_WELDED

    def test_the_state_gate_reports_before_the_qualification_safety_check(self, api):
        """A weld log on an already welded seam names the state error, not the safety one.

        PRD: "Then come the safety checks, in this order: welder qualification
        currency (`ERR_WELDER_NOT_QUALIFIED`)"

        Design: Difficulty/priority_pair_validation_conflict/seam_state_outranks_welder_qualification_safety
        """
        ctx = self._welded_seam_and_revoked_welder(api)

        validate_error(
            api.weld_log(
                ctx.seam_id,
                {"welder_id": ctx.welder_id, "filler_lot": "E7018-Z"},
                welder_headers(ctx.welder_id),
            ),
            ERR_SEAM_NOT_WELDABLE,
        )

    def test_the_refused_weld_log_leaves_the_seam_exactly_as_it_was(self, api):
        """No field of the seam moves on a rejected request.

        PRD: "`welder_id` and `filler_lot` are recorded (both overwritten on each
        repair re-weld)"

        Design: Difficulty/priority_pair_validation_conflict/seam_state_outranks_welder_qualification_safety
        """
        ctx = self._welded_seam_and_revoked_welder(api)
        before = X.read_seam(api, ctx.seam_id)

        api.weld_log(
            ctx.seam_id,
            {"welder_id": ctx.welder_id, "filler_lot": "E7018-Z"},
            welder_headers(ctx.welder_id),
        )

        after = X.read_seam(api, ctx.seam_id)
        assert after["status"] == SEAM_WELDED
        assert after["welder_id"] == before["welder_id"]
        assert after["filler_lot"] == before["filler_lot"]
        assert after["version"] == before["version"]


class TestWithdrawalRateOutranksPermitVolume:
    def _source_with_one_large_reservation(self, api):
        X.set_clock(api, "2026-08-10T00:00:00Z")
        tank = X.create_tank(api)
        source = X.create_water_source(
            api, source_name="Municipal Tap", source_type=SOURCE_MUNICIPAL,
            permitted_volume_gal=500000.0, max_concurrent_rate_gpm=900.0,
        )
        plan = X.create_plan(api, tank["id"], source["id"], fill_volume_gal=500000.0,
                             disposal_method=DISPOSAL_DISCHARGE_TO_POTW)
        X.reserve_withdrawal(
            api, plan["id"], source["id"], "2026-08-11T00:00:00Z", "2026-08-11T12:00:00Z",
            600.0, 400000.0,
        )
        return source["id"], plan["id"]

    def test_the_temporal_capacity_check_reports_before_the_fiscal_one(self, api):
        """An overlapping window that also overdraws the permit names the rate conflict.

        PRD: "The temporal checks follow: window ordering (`ERR_INVALID_WINDOW`),
        radiographic window exclusivity (`ERR_EXAM_WINDOW_CONFLICT`), water permit
        currency (`ERR_WATER_PERMIT_EXPIRED`), hold-period elapse
        (`ERR_HOLD_PERIOD_NOT_ELAPSED`), and concurrent withdrawal rate capacity
        (`ERR_WITHDRAWAL_CAPACITY_CONFLICT`). The fiscal checks follow those:
        permitted volume not oversubscribed (`ERR_PERMITTED_VOLUME_EXCEEDED`)"

        Design: Difficulty/priority_pair_validation_conflict/withdrawal_rate_temporal_outranks_permit_volume_fiscal
        """
        source_id, plan_id = self._source_with_one_large_reservation(api)

        validate_error(
            api.create_water_withdrawal(
                {
                    "hydrotest_plan_id": plan_id,
                    "water_source_id": source_id,
                    "window_start_utc": "2026-08-11T06:00:00Z",
                    "window_end_utc": "2026-08-11T18:00:00Z",
                    "rate_gpm": 400.0,
                    "reserved_volume_gal": 200000.0,
                    "expected_water_source_version": X.source_version(api, source_id),
                },
                ES1,
            ),
            ERR_WITHDRAWAL_CAPACITY_CONFLICT,
        )

    def test_the_fiscal_rule_is_genuinely_violated_and_the_ledger_never_moves(self, api):
        """Only 100,000 gallons remain, so the request really does overdraw the permit.

        PRD: "A new source starts with `reserved_volume_gal` and
        `consumed_volume_gal` at 0.0 and `available_volume_gal` equal to
        `permitted_volume_gal`."

        Design: Difficulty/priority_pair_validation_conflict/withdrawal_rate_temporal_outranks_permit_volume_fiscal
        """
        source_id, plan_id = self._source_with_one_large_reservation(api)
        before = X.read_water_source(api, source_id)

        api.create_water_withdrawal(
            {
                "hydrotest_plan_id": plan_id,
                "water_source_id": source_id,
                "window_start_utc": "2026-08-11T06:00:00Z",
                "window_end_utc": "2026-08-11T18:00:00Z",
                "rate_gpm": 400.0,
                "reserved_volume_gal": 200000.0,
                "expected_water_source_version": before["version"],
            },
            ES1,
        )

        after = X.read_water_source(api, source_id)
        assert_source_ledger(after, reserved=400000.00, consumed=0.00, available=100000.00)
        assert after["version"] == before["version"]

    def test_the_refused_reservation_creates_no_withdrawal_row(self, api):
        """The plan is still holding exactly one window.

        PRD: "exactly at the ceiling the reservation is accepted, and above it the
        request is rejected with `ERR_WITHDRAWAL_CAPACITY_CONFLICT`."

        Design: Difficulty/priority_pair_validation_conflict/withdrawal_rate_temporal_outranks_permit_volume_fiscal
        """
        source_id, plan_id = self._source_with_one_large_reservation(api)

        api.create_water_withdrawal(
            {
                "hydrotest_plan_id": plan_id,
                "water_source_id": source_id,
                "window_start_utc": "2026-08-11T06:00:00Z",
                "window_end_utc": "2026-08-11T18:00:00Z",
                "rate_gpm": 400.0,
                "reserved_volume_gal": 200000.0,
                "expected_water_source_version": X.source_version(api, source_id),
            },
            ES1,
        )

        rows, _ = X.list_rows(
            api, api.list_water_withdrawals(ES1, {"hydrotest_plan_id": plan_id})
        )
        assert len(rows) == 1


class TestHostCourseReferentialOutranksClearance:
    def _clashing_nozzle_on_a_downgraded_course(self, api):
        """Two 6-inch nozzles 5 degrees apart, with the host course knocked back."""
        ctx = X.rt_accepted_course(api)
        ctx.installed = X.create_appurtenance(
            api, ctx.tank_id, ctx.course_id, appurtenance_type=APP_NOZZLE,
            nominal_size_in=6.0, elevation_ft=4.0, azimuth_deg=0.0,
        )
        ctx.installed = X.install_appurtenance(api, ctx.installed["id"])
        ctx.designed = X.create_appurtenance(
            api, ctx.tank_id, ctx.course_id, appurtenance_type=APP_NOZZLE,
            nominal_size_in=6.0, elevation_ft=4.0, azimuth_deg=5.0,
        )
        start, end = X.rt_window("2026-08-13", 0)
        X.schedule_nde(api, ctx.seam_id, start, end, coverage_pct=20.0,
                       technician_stamp="RT-4")
        return ctx

    def test_both_the_clearance_envelope_and_the_host_course_gate_are_violated(self, api):
        """A 9.0-degree envelope against a 5.0-degree separation, on a WELDED course.

        PRD: "For a `NOZZLE` or a `MANWAY` it is the greater of 8.0 degrees and
        `nominal_size_in` multiplied by 1.5, so small nozzles all sit at the
        8.0-degree floor while a size above 5.333… inches begins to drive the
        requirement upward."

        Design: Difficulty/priority_pair_validation_conflict/host_course_referential_outranks_clearance_constraint
        """
        ctx = self._clashing_nozzle_on_a_downgraded_course(api)

        assert_angle(ctx.installed["required_clearance_deg"], 9.0, "installed nozzle")
        assert ctx.installed["status"] == APP_INSTALLED
        assert_angle(ctx.designed["required_clearance_deg"], 9.0, "designed nozzle")
        assert X.read_course(api, ctx.course_id)["status"] == COURSE_WELDED

    def test_the_referential_gate_reports_before_the_clearance_constraint(self, api):
        """The host-course precondition is checked before any clash arithmetic.

        PRD: "Next come the referential checks: same-tank agreement between every
        entity referenced in one request (`ERR_CROSS_TANK_REFERENCE`), then the
        accepted-foundation precondition for fit-up and weld logging
        (`ERR_FOUNDATION_NOT_ACCEPTED`), then the host-course acceptance
        precondition for appurtenance installation
        (`ERR_HOST_COURSE_NOT_ACCEPTED`)"

        Design: Difficulty/priority_pair_validation_conflict/host_course_referential_outranks_clearance_constraint
        """
        ctx = self._clashing_nozzle_on_a_downgraded_course(api)

        validate_error(
            api.appurtenance_installation(ctx.designed["id"], {}, ES1),
            ERR_HOST_COURSE_NOT_ACCEPTED,
        )

    def test_the_refused_installation_leaves_the_appurtenance_designed(self, api):
        """No instant is stamped on a rejected installation.

        PRD: "A new appurtenance opens at `status` `DESIGNED` with
        `installed_at_utc` null."

        Design: Difficulty/priority_pair_validation_conflict/host_course_referential_outranks_clearance_constraint
        """
        ctx = self._clashing_nozzle_on_a_downgraded_course(api)

        api.appurtenance_installation(ctx.designed["id"], {}, ES1)

        row = X.read_appurtenance(api, ctx.designed["id"])
        assert row["status"] == APP_DESIGNED
        assert row["installed_at_utc"] is None
