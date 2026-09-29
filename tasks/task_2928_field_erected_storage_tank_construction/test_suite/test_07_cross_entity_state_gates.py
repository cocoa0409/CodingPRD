"""Writes gated on the state of an entity the request merely references.

The gated row is legal throughout each case; what refuses the write is a welder's
qualification, a host course's derived status, or a tank's posture dimension.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_HOST_COURSE_NOT_ACCEPTED,
    ERR_TANK_POSTURE_RESTRICTED,
    ERR_WELDER_NOT_QUALIFIED,
)
from test_helpers.assertions import assert_angle, assert_instant, assert_settlement, assert_tank_state
from test_helpers.constants import (
    ACTION_REVOKE,
    APPROVE,
    APP_DESIGNED,
    APP_INSTALLED,
    APP_NOZZLE,
    COURSE_FITTED,
    COURSE_RT_ACCEPTED,
    COURSE_WELDED,
    DECISION_ACCEPT,
    DISPOSAL_DISCHARGE_TO_POTW,
    NC_CLOSED_BY_SUPERSEDING_SURVEY,
    NC_OPEN,
    PHASE_ERECTION_IN_PROGRESS,
    PHASE_SHELL_COMPLETE,
    PLAN_APPROVED,
    PLAN_DRAFT,
    POSTURE_OPEN,
    POSTURE_RESTRICTED,
    SEAM_FIT_READY,
    SEAM_RT_ACCEPTED,
    SEAM_WELDED,
    SOURCE_MUNICIPAL,
    SURVEY_ROLE_MONITORING,
    VERDICT_OUT_OF_TOLERANCE,
    VERDICT_WITHIN_TOLERANCE,
    WELDER_REVOKED,
)
from test_helpers.test_users import ES1, PE1, PE1_ID, welder_headers


class TestWeldLogGateReadsWelderQualification:
    def _seam_with_one_revoked_and_one_current_welder(self, api):
        ctx = X.erecting_tank(api)
        ctx.revoked = X.create_welder(api, welder_stamp="W-07")
        ctx.current = X.create_welder(api, welder_stamp="W-08", full_name="T. Nakamura")
        ctx.seam = X.create_seam(api, ctx.course_id, "V1", 1)
        ctx.revoked = X.welder_action(
            api, ctx.revoked["id"], ACTION_REVOKE, remarks="failed bend test re-audit"
        )
        return ctx

    def test_the_gate_reads_the_referenced_welder_not_the_seam(self, api):
        """The seam is a legal FIT_READY, yet the weld log is refused.

        PRD: "The welder's `qualification_status`, re-evaluated against the logical
        clock as described above, must be `QUALIFIED`; a `LAPSED` or `REVOKED`
        welder may not weld and the attempt is rejected with
        `ERR_WELDER_NOT_QUALIFIED`."

        Design: Difficulty/cross_entity_state_dependency/weld_log_gate_reads_welder_qualification_status
        """
        ctx = self._seam_with_one_revoked_and_one_current_welder(api)
        assert ctx.revoked["qualification_status"] == WELDER_REVOKED

        validate_error(
            api.weld_log(
                ctx.seam["id"],
                {"welder_id": ctx.revoked["id"], "filler_lot": "E7018-A"},
                welder_headers(ctx.revoked["id"]),
            ),
            ERR_WELDER_NOT_QUALIFIED,
        )

        seam = X.read_seam(api, ctx.seam["id"])
        assert seam["status"] == SEAM_FIT_READY
        assert seam["welder_id"] is None
        assert seam["welded_at_utc"] is None
        assert X.read_course(api, ctx.course_id)["status"] == COURSE_FITTED
        assert X.read_tank(api, ctx.tank_id)["construction_phase"] == PHASE_ERECTION_IN_PROGRESS

    def test_the_same_request_shape_succeeds_under_a_qualified_welder(self, api):
        """Only the referenced welder row differs, and the write goes through.

        PRD: "On success the seam moves to `WELDED` — either `FIT_READY → WELDED`
        for a first weld or `REPAIR_IN_PROGRESS → WELDED` for a re-weld after
        excavation, in which case `repair_cycle_count` is incremented by 1."

        Design: Difficulty/cross_entity_state_dependency/weld_log_gate_reads_welder_qualification_status
        """
        ctx = self._seam_with_one_revoked_and_one_current_welder(api)
        api.weld_log(
            ctx.seam["id"],
            {"welder_id": ctx.revoked["id"], "filler_lot": "E7018-A"},
            welder_headers(ctx.revoked["id"]),
        )

        welded = X.weld(api, ctx.seam["id"], ctx.current["id"], filler_lot="E7018-A")

        assert welded["status"] == SEAM_WELDED
        assert welded["welder_id"] == ctx.current["id"]
        assert_instant(welded["welded_at_utc"], "2026-08-10T00:00:00Z", "welded_at_utc")
        assert X.read_course(api, ctx.course_id)["status"] == COURSE_WELDED

    def test_the_production_weld_refreshes_only_the_welder_who_welded(self, api):
        """The revoked welder's record is untouched by either call.

        PRD: "Every production weld resets the decay curve — the welder stays
        `QUALIFIED`, `last_weld_date_utc` is moved forward to the instant of that
        weld, and `continuity_expires_at_utc` is recomputed as the new base date
        plus `continuity_limit_days`."

        Design: Difficulty/cross_entity_state_dependency/weld_log_gate_reads_welder_qualification_status
        """
        ctx = self._seam_with_one_revoked_and_one_current_welder(api)
        api.weld_log(
            ctx.seam["id"],
            {"welder_id": ctx.revoked["id"], "filler_lot": "E7018-A"},
            welder_headers(ctx.revoked["id"]),
        )
        X.weld(api, ctx.seam["id"], ctx.current["id"], filler_lot="E7018-A")

        current = X.read_welder(api, ctx.current["id"])
        assert_instant(current["last_weld_date_utc"], "2026-08-10T00:00:00Z", "last weld date")
        assert_instant(
            current["continuity_expires_at_utc"], "2027-02-06T00:00:00Z", "refreshed expiry"
        )

        revoked = X.read_welder(api, ctx.revoked["id"])
        assert revoked["qualification_status"] == WELDER_REVOKED
        assert_instant(revoked["last_weld_date_utc"], "2026-06-01T00:00:00Z", "last weld date")


class TestAppurtenanceGateReadsHostCourseStatus:
    def _designed_nozzle_on_a_welded_course(self, api):
        ctx = X.welded_course(api, seam_labels=("V1",))
        start, end = X.rt_window("2026-08-11", 0)
        ctx.report = X.schedule_nde(api, ctx.seam_id, start, end)
        ctx.report_id = ctx.report["id"]
        ctx.nozzle = X.create_appurtenance(
            api, ctx.tank_id, ctx.course_id, nominal_size_in=6.0, azimuth_deg=0.0
        )
        return ctx

    def test_installation_is_refused_while_the_host_course_is_only_welded(self, api):
        """The nozzle row is a perfectly legal DESIGNED; the course is not RT_ACCEPTED.

        PRD: "The appurtenance must be `DESIGNED`, or the request is rejected with
        `ERR_APPURTENANCE_STATE_INVALID`; the tank must not be `FROZEN`; and the
        host shell course must already be `RT_ACCEPTED`, since nobody cuts a hole
        in plate whose seams have not yet been radiographically accepted — a
        course in any other state is rejected with `ERR_HOST_COURSE_NOT_ACCEPTED`."

        Design: Difficulty/cross_entity_state_dependency/appurtenance_installation_gate_reads_host_course_status
        """
        ctx = self._designed_nozzle_on_a_welded_course(api)
        assert ctx.nozzle["status"] == APP_DESIGNED
        assert ctx.nozzle["appurtenance_type"] == APP_NOZZLE
        assert_angle(ctx.nozzle["required_clearance_deg"], 9.0, "required clearance")
        assert X.read_course(api, ctx.course_id)["status"] == COURSE_WELDED

        validate_error(
            api.appurtenance_installation(ctx.nozzle["id"], {}, ES1),
            ERR_HOST_COURSE_NOT_ACCEPTED,
        )

        nozzle = X.read_appurtenance(api, ctx.nozzle["id"])
        assert nozzle["status"] == APP_DESIGNED
        assert nozzle["installed_at_utc"] is None

    def test_accepting_the_examination_opens_the_gate_for_the_same_request(self, api):
        """The seam acceptance bubbles the course, and the identical install now lands.

        PRD: "The course is `RT_ACCEPTED` when it has at least one seam and every one
        of its seams is `RT_ACCEPTED`."

        Design: Difficulty/cross_entity_state_dependency/appurtenance_installation_gate_reads_host_course_status
        """
        ctx = self._designed_nozzle_on_a_welded_course(api)
        api.appurtenance_installation(ctx.nozzle["id"], {}, ES1)

        X.report_nde(api, ctx.report_id, DECISION_ACCEPT, 0, 4)
        assert X.read_seam(api, ctx.seam_id)["status"] == SEAM_RT_ACCEPTED
        assert X.read_course(api, ctx.course_id)["status"] == COURSE_RT_ACCEPTED

        installed = X.install_appurtenance(
            api, ctx.nozzle["id"], installed_at_utc="2026-08-16T09:00:00Z"
        )
        assert installed["status"] == APP_INSTALLED
        assert_instant(installed["installed_at_utc"], "2026-08-16T09:00:00Z", "installed_at_utc")

    def test_the_gate_never_moves_the_tank_phase(self, api):
        """Neither the refusal nor the later installation is a phase event.

        PRD: "Installation is recorded by the `ErectionSuperintendent`, optionally
        supplying `installed_at_utc`; when omitted, the installation instant is
        taken from the logical clock."

        Design: Difficulty/cross_entity_state_dependency/appurtenance_installation_gate_reads_host_course_status
        """
        ctx = self._designed_nozzle_on_a_welded_course(api)
        assert X.read_tank(api, ctx.tank_id)["construction_phase"] == PHASE_ERECTION_IN_PROGRESS

        api.appurtenance_installation(ctx.nozzle["id"], {}, ES1)
        assert X.read_tank(api, ctx.tank_id)["construction_phase"] == PHASE_ERECTION_IN_PROGRESS

        X.report_nde(api, ctx.report_id, DECISION_ACCEPT, 0, 4)
        X.install_appurtenance(api, ctx.nozzle["id"], installed_at_utc="2026-08-16T09:00:00Z")
        assert X.read_tank(api, ctx.tank_id)["construction_phase"] == PHASE_ERECTION_IN_PROGRESS


class TestHydrotestApprovalGateReadsTankPosture:
    def _draft_plan_under_a_restricted_tank(self, api):
        ctx = X.shell_complete_tank(api)
        ctx.source = X.create_water_source(
            api, source_name="Municipal Hydrant 12", source_type=SOURCE_MUNICIPAL
        )
        ctx.source_id = ctx.source["id"]
        ctx.plan = X.create_plan(
            api,
            ctx.tank_id,
            ctx.source_id,
            fill_volume_gal=400000.0,
            hold_hours=24,
            disposal_method=DISPOSAL_DISCHARGE_TO_POTW,
        )
        ctx.plan_id = ctx.plan["id"]
        ctx.bad_survey = X.create_survey(api, ctx.package_id, X.DISHED_POINT1, 25.0)
        return ctx

    def test_a_settlement_nonconformance_restricts_the_tank_without_moving_the_phase(self, api):
        """The out-of-tolerance round bites the posture dimension only.

        PRD: "An `OUT_OF_TOLERANCE` monitoring survey instead moves to `OPEN`, which
        raises the tank's `open_nonconformance_count` and triggers the posture
        recomputation and the suspension cascade of §2.8 — suspending the tank's
        live hydrostatic test plan and releasing its water reservations."

        Design: Difficulty/cross_entity_state_dependency/hydrotest_approval_gate_reads_tank_quality_posture
        """
        ctx = self._draft_plan_under_a_restricted_tank(api)

        assert ctx.bad_survey["survey_role"] == SURVEY_ROLE_MONITORING
        assert_settlement(ctx.bad_survey["uniform_settlement_in"], 0.750, "uniform settlement")
        assert_settlement(ctx.bad_survey["max_out_of_plane_in"], 3.750, "max out of plane")
        assert_settlement(
            ctx.bad_survey["max_adjacent_differential_in"], 6.000, "max adjacent differential"
        )
        assert ctx.bad_survey["verdict"] == VERDICT_OUT_OF_TOLERANCE
        assert ctx.bad_survey["nonconformance_state"] == NC_OPEN

        assert_tank_state(
            X.read_tank(api, ctx.tank_id),
            phase=PHASE_SHELL_COMPLETE,
            posture=POSTURE_RESTRICTED,
            nonconformance_count=1,
        )

    def test_approval_is_refused_on_posture_not_on_plan_state(self, api):
        """The plan is a legal DRAFT, so the refusal names the posture rule.

        PRD: "Those four require `quality_posture` to be exactly `OPEN`; `RESTRICTED`
        is sufficient for ordinary erection work but not for these, and an attempt
        made while the posture is `RESTRICTED` is rejected with
        `ERR_TANK_POSTURE_RESTRICTED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/hydrotest_approval_gate_reads_tank_quality_posture
        """
        ctx = self._draft_plan_under_a_restricted_tank(api)
        assert ctx.plan["status"] == PLAN_DRAFT

        validate_error(
            api.plan_approval(ctx.plan_id, {"decision": APPROVE}, PE1),
            ERR_TANK_POSTURE_RESTRICTED,
        )

        plan = X.read_plan(api, ctx.plan_id)
        assert plan["status"] == PLAN_DRAFT
        assert plan["approved_by_user_id"] is None
        assert plan["state_before_suspension"] is None
        assert X.read_tank(api, ctx.tank_id)["active_hydrotest_plan_id"] is None

    def test_a_superseding_survey_reopens_the_gate_for_the_identical_approval(self, api):
        """Closing the nonconformance returns the posture to OPEN and the same call lands.

        PRD: "That nonconformance closes when a later survey on the same foundation
        package comes back `WITHIN_TOLERANCE` at a `fill_percent` greater than or
        equal to the open survey's own `fill_percent`: the earlier survey moves
        `OPEN → CLOSED_BY_SUPERSEDING_SURVEY`, its `superseded_by_survey_id` is
        pointed at the new survey, the tank's count is decremented, and a return
        to `OPEN` posture restores every suspended plan to its
        `state_before_suspension`."

        Design: Difficulty/cross_entity_state_dependency/hydrotest_approval_gate_reads_tank_quality_posture
        """
        ctx = self._draft_plan_under_a_restricted_tank(api)
        api.plan_approval(ctx.plan_id, {"decision": APPROVE}, PE1)

        good = X.create_survey(api, ctx.package_id, X.SETTLED_2IN, 25.0)
        assert good["verdict"] == VERDICT_WITHIN_TOLERANCE

        closed = X.read_survey(api, ctx.bad_survey["id"])
        assert closed["nonconformance_state"] == NC_CLOSED_BY_SUPERSEDING_SURVEY
        assert closed["superseded_by_survey_id"] == good["id"]
        assert_tank_state(
            X.read_tank(api, ctx.tank_id),
            phase=PHASE_SHELL_COMPLETE,
            posture=POSTURE_OPEN,
            nonconformance_count=0,
        )

        plan = X.approve_plan(api, ctx.plan_id)
        assert plan["status"] == PLAN_APPROVED
        assert plan["approved_by_user_id"] == PE1_ID
        assert plan["state_before_suspension"] is None
        assert X.read_tank(api, ctx.tank_id)["active_hydrotest_plan_id"] == ctx.plan_id
