"""Role authorisation: the exclusive-write denial matrix and the duties pairs.

The role model is disjoint on writes and universal on reads, so the same six
operators that share every read see a hard refusal on one another's write
surface. Three pairs of steps go one step further and demand two different
human operators rather than two different roles.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import fixtures as X
from test_helpers.api_errors import ERR_FORBIDDEN_ROLE, ERR_SEGREGATION_OF_DUTIES
from test_helpers.assertions import (
    assert_instant,
    assert_list_total,
    assert_object_envelope,
)
from test_helpers.constants import (
    APP_INSTALLED,
    APP_NOZZLE,
    CLOCK_BASE,
    DECISION_ACCEPT,
    GHOST_UUID,
    NDE_REPORTED_ACCEPT,
    NDE_SCHEDULED,
    PACKAGE_ACCEPTED,
    PACKAGE_SUBMITTED,
    PASS_DECISION,
    PHASE_COATED,
    PHASE_COMMISSIONED,
    PHASE_HYDROTEST_PASSED,
    PLAN_FILL_HOLD,
    PLAN_PASSED,
    POSTURE_OPEN,
    REQUIRED_DOCUMENT_TYPES,
    REVIEW_ACCEPT,
    SEAM_EXAM_SCHEDULED,
    SEAM_RT_ACCEPTED,
    WELDER_QUALIFIED,
)
from test_helpers.factories import (
    allocation_payload,
    foundation_package_payload,
    holiday_test_payload,
    nde_report_payload,
    nde_result_payload,
    nde_void_payload,
    plan_completion_payload,
    review_payload,
    settlement_survey_payload,
    submission_payload,
    tank_payload,
    weld_log_payload,
    welder_payload,
)
from test_helpers.test_users import (
    AI1,
    AI1_ID,
    AI2,
    AI3,
    AI3_ID,
    AI_AS_PE1,
    CC1,
    ES1,
    PE1,
    PE1_ID,
    QC1,
    QC1_ID,
    QC_AS_AI1,
    welder_headers,
)


class TestExclusiveWriteDenialMatrix:
    def test_twelve_exclusive_writes_are_all_refused_before_any_id_is_resolved(self, api):
        """One wrong-role caller per exclusive slice, every path id deliberately unresolvable.

        PRD: "If `X-User-Role` holds a string that is not one of those six spellings, or holds a
        valid role that is not authorised for the endpoint being called, the request is
        rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        PRD: "Authentication and authorisation come first, in three steps: header presence
        (`ERR_UNAUTHENTICATED`), then role validity and endpoint authorisation
        (`ERR_FORBIDDEN_ROLE`), then — on a weld log only — the welder-identity match
        (`ERR_WELDER_IDENTITY_MISMATCH`). Fourth comes resolution of path identifiers,
        left to right, using the mapping in §2.4."

        PRD: "Only the Welder role may call this, and the acting X-User-ID must equal the
        welder_id in the body."

        Design: Corner/rbac/exclusive_operations_are_rejected_for_every_other_role
        """
        start, end = X.rt_window("2026-08-11", 0)

        refusals = [
            # ProjectEngineer's registry writes, attempted by the civil contractor.
            ("tank registration", lambda: api.create_tank(tank_payload(), CC1)),
            # CivilContractor's foundation writes, attempted by the engineer.
            (
                "foundation package",
                lambda: api.create_foundation_package(
                    foundation_package_payload(GHOST_UUID), PE1
                ),
            ),
            # CivilContractor's survey writes, attempted by the inspector.
            (
                "settlement survey",
                lambda: api.create_settlement_survey(
                    settlement_survey_payload(GHOST_UUID, [100.0]), QC1
                ),
            ),
            # ErectionSuperintendent's erection writes, attempted by a welder.
            ("course fit-up", lambda: api.fitup(GHOST_UUID, welder_headers("w-1"))),
            # The Welder's own weld log, attempted by the superintendent.
            (
                "weld log",
                lambda: api.weld_log(GHOST_UUID, weld_log_payload(GHOST_UUID), ES1),
            ),
            # QcInspector's examination writes, attempted by the inspector of record.
            (
                "examination scheduling",
                lambda: api.create_nde_report(
                    nde_report_payload(GHOST_UUID, start, end), AI1
                ),
            ),
            # AuthorizedInspector's void, attempted by the QC inspector.
            (
                "report void",
                lambda: api.nde_void(
                    GHOST_UUID, nde_void_payload(void_reason="wrong film"), QC1
                ),
            ),
            # AuthorizedInspector's welder qualification, attempted by the engineer.
            ("welder qualification", lambda: api.create_welder(welder_payload(), PE1)),
            # ErectionSuperintendent's plate allocation, attempted by the engineer.
            (
                "plate allocation",
                lambda: api.plate_lot_allocation(
                    GHOST_UUID, allocation_payload(GHOST_UUID, 8000.0), PE1
                ),
            ),
            # AuthorizedInspector's hydrotest sign-off, attempted by the superintendent.
            (
                "hydrotest completion",
                lambda: api.plan_completion(
                    GHOST_UUID, plan_completion_payload(PASS_DECISION), ES1
                ),
            ),
            # QcInspector's coating quality step, attempted by the engineer.
            (
                "holiday test",
                lambda: api.holiday_test(GHOST_UUID, holiday_test_payload(0, 675.0), PE1),
            ),
            # AuthorizedInspector's package review, attempted by the engineer.
            (
                "package review",
                lambda: api.package_review(GHOST_UUID, review_payload(REVIEW_ACCEPT), PE1),
            ),
        ]

        for label, call in refusals:
            response = call()
            assert response.status_code == 403, f"{label} should be a role refusal"
            validate_error(response, ERR_FORBIDDEN_ROLE, 403)

        assert_list_total(api.list_tanks(PE1), 0)
        assert_list_total(api.list_welders(AI1), 0)


class TestSharedReadsAndTheLogicalClock:
    def test_all_six_roles_read_the_same_row_and_may_move_the_clock(self, api):
        """The peer-role complement: no projection differs and the clock is everyone's.

        PRD: "Every read endpoint in the system is available to all six roles, and so is the
        logical-clock capability described in §2.4; all other writes are restricted as
        listed in §4."

        PRD: "Sets the server's logical clock, which every deadline, expiry, continuity window
        and hold-period rule reads. Before any call to this endpoint the logical clock
        reads exactly 2026-08-01T00:00:00Z - the mandatory startup default - and never
        falls back to real wall-clock time. Returns the new current_utc."

        PRD: "`version` is an integer that starts at 1 when the resource is created and
        increases by exactly 1 on every mutation of that resource; `updated_at` is
        refreshed on the same mutation."

        Design: Corner/rbac/shared_operations_work_for_all_six_roles
        """
        tank = X.create_tank(api)
        welder = X.create_welder(api)
        assert welder["qualification_status"] == WELDER_QUALIFIED

        readers = [
            ("ProjectEngineer", PE1),
            ("CivilContractor", CC1),
            ("ErectionSuperintendent", ES1),
            ("Welder", welder_headers(welder["id"])),
            ("QcInspector", QC1),
            ("AuthorizedInspector", AI1),
        ]

        projection = None
        progress = None
        for role, headers in readers:
            row = assert_object_envelope(api.get_tank(tank["id"], headers), 200)
            summary = assert_object_envelope(api.get_tank_summary(tank["id"], headers), 200)
            if projection is None:
                projection, progress = row, summary
            else:
                assert row == projection, f"{role} sees a different tank projection"
                assert summary == progress, f"{role} sees a different progress read"

        assert projection["id"] == tank["id"]
        assert projection["tank_tag"] == "TK-101"
        assert projection["version"] == 1
        assert progress["tank_id"] == tank["id"]

        welders_clock = assert_object_envelope(
            api.set_clock(CLOCK_BASE, welder_headers(welder["id"])), 200
        )
        assert_instant(welders_clock["current_utc"], CLOCK_BASE, "clock set by the welder")

        contractors_clock = assert_object_envelope(
            api.set_clock("2026-08-11T00:00:00Z", CC1), 200
        )
        assert_instant(
            contractors_clock["current_utc"],
            "2026-08-11T00:00:00Z",
            "clock set by the civil contractor",
        )

        after = X.read_tank(api, tank["id"], ES1)
        assert after["version"] == 1
        assert after == projection


class TestExaminationResultDuties:
    def test_the_qualifying_inspector_may_not_judge_that_welders_radiograph(self, api):
        """Right role, wrong human: the refusal turns on stored user ids, not on roles.

        PRD: "First, the `QcInspector` who reports an examination result must not be the
        operator recorded in the seam welder's `qualified_by_user_id` — that is, the
        inspector who witnessed and recorded that welder's qualification may not then
        judge that welder's radiographs."

        PRD: "In all three cases the comparison is between the acting `X-User-ID` and the stored
        value, and a collision is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        PRD: "The report must be `SCHEDULED` (`ERR_NDE_STATE_INVALID`), and the acting operator
        must not be the one recorded in `qualified_by_user_id` for the seam's welder
        (`ERR_SEGREGATION_OF_DUTIES`). On either decision, `reported_by_user_id` is
        stamped with the acting `X-User-ID` and `reported_at_utc` from the logical clock."

        PRD: "An acceptance moves the report `SCHEDULED → REPORTED_ACCEPT` and the seam
        `EXAM_SCHEDULED → RT_ACCEPTED`."

        PRD: "Registers a welder whose performance qualification has just been witnessed. The
        welder is created QUALIFIED and the acting inspector is recorded as the qualifier."

        Design: Corner/rbac/nde_result_reporter_must_not_be_the_qualifying_inspector
        """
        ctx = X.welded_course(api, seam_labels=("V1",))
        assert ctx.welder["qualified_by_user_id"] == AI1_ID

        start, end = X.rt_window("2026-08-11", 0)
        report = X.schedule_nde(api, ctx.seam_id, start, end)
        assert report["status"] == NDE_SCHEDULED
        assert X.read_seam(api, ctx.seam_id)["status"] == SEAM_EXAM_SCHEDULED

        validate_error(
            api.nde_result(
                report["id"], nde_result_payload(DECISION_ACCEPT, 0, 4), QC_AS_AI1
            ),
            ERR_SEGREGATION_OF_DUTIES,
            403,
        )

        refused = X.read_nde_report(api, report["id"])
        assert refused["status"] == NDE_SCHEDULED
        assert refused["reported_by_user_id"] is None
        assert refused["reported_at_utc"] is None
        assert X.read_seam(api, ctx.seam_id)["status"] == SEAM_EXAM_SCHEDULED

        accepted = assert_object_envelope(
            api.nde_result(report["id"], nde_result_payload(DECISION_ACCEPT, 0, 4), QC1), 200
        )
        assert accepted["status"] == NDE_REPORTED_ACCEPT
        assert accepted["reported_by_user_id"] == QC1_ID
        assert_instant(accepted["reported_at_utc"], CLOCK_BASE, "result stamp")

        seam = X.read_seam(api, ctx.seam_id)
        assert seam["status"] == SEAM_RT_ACCEPTED
        # The bead was logged under the welder's own id, which plays no part in the
        # comparison: only the qualifying inspector recorded on that welder does.
        assert seam["welder_id"] == ctx.welder_id
        assert accepted["reported_by_user_id"] != seam["welder_id"]
        assert ctx.welder_id != AI1_ID


class TestHydrotestAndPackageDuties:
    def test_the_approver_cannot_sign_the_test_off_and_the_submitter_cannot_review_it(self, api):
        """Two counterpart pairs at the far end of the pipeline, both 403 and both total.

        PRD: "Second, the `AuthorizedInspector` who records a hydrostatic test completion
        decision must not be the operator recorded in the plan's `approved_by_user_id`."

        PRD: "Third, the `AuthorizedInspector` who reviews a commissioning package must not be
        the operator recorded in the package's `submitted_by_user_id`."

        PRD: "The plan must be `FILL_HOLD` (`ERR_PLAN_STATE_INVALID`) and the acting operator
        must not be the plan's `approved_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`)."

        PRD: "The package must be `SUBMITTED` (`ERR_PACKAGE_STATE_INVALID`) and the acting
        `X-User-ID` must differ from `submitted_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`)."

        PRD: "On `ACCEPT` the package moves `SUBMITTED → ACCEPTED`, which is terminal,
        `reviewed_by_user_id` records the acting operator, `accepted_at_utc` is stamped
        from the logical clock, the in-service schedule below is computed, and the tank
        advances `COATED → COMMISSIONED` — the terminal construction phase — with its
        `version` incremented by 1."

        PRD: "`bottom_remaining_life_years` is the tank's `bottom_thickness_in` less its
        `bottom_minimum_thickness_in`, divided by its `assumed_corrosion_rate_ipy`,
        rounded half up to 2 decimal places. `internal_inspection_interval_years` is the
        smaller of 20 and the floor of half that remaining life, taken as a whole number
        of years — the floor is applied after the two-decimal rounding, and the 20-year
        ceiling caps even a very thick bottom. `external_inspection_interval_years` is 5
        when the tank has a coating application with `scope` `EXTERNAL_COATING` whose
        `status` is `ACCEPTED`, and 2 otherwise; an internal lining, however well it
        passed, earns nothing here. `next_internal_due_utc` is `accepted_at_utc` advanced
        by `internal_inspection_interval_years` whole years and `next_external_due_utc` is
        `accepted_at_utc` advanced by `external_inspection_interval_years` whole years,
        calendar arithmetic landing on the same month and day-of-month."

        Design: Corner/rbac/hydrotest_and_package_counterparts_must_not_be_the_same_user
        """
        ctx = X.plan_at_fill_hold(api)
        assert ctx.plan["status"] == PLAN_FILL_HOLD
        assert ctx.plan["approved_by_user_id"] == PE1_ID
        assert ctx.plan["fill_percent_current"] == pytest.approx(100.0)

        nozzle = X.create_appurtenance(api, ctx.tank_id, ctx.course_id)
        assert nozzle["appurtenance_type"] == APP_NOZZLE
        assert X.install_appurtenance(api, nozzle["id"])["status"] == APP_INSTALLED

        X.set_clock(api, "2026-08-11T00:00:00Z")

        # Pair two: the approver pe-1, carrying the AuthorizedInspector role, is barred
        # from recording the result of the very plan they approved.
        validate_error(
            api.plan_completion(
                ctx.plan_id, plan_completion_payload(PASS_DECISION), AI_AS_PE1
            ),
            ERR_SEGREGATION_OF_DUTIES,
            403,
        )
        held = X.read_plan(api, ctx.plan_id)
        assert held["status"] == PLAN_FILL_HOLD
        assert held["completed_at_utc"] is None
        assert held["approved_by_user_id"] == PE1_ID

        passed = assert_object_envelope(
            api.plan_completion(
                ctx.plan_id, plan_completion_payload(PASS_DECISION, remarks="no leaks"), AI2
            ),
            200,
        )
        assert passed["status"] == PLAN_PASSED
        assert passed["fill_percent_current"] == pytest.approx(100.0)
        assert_instant(passed["completed_at_utc"], "2026-08-11T00:00:00Z", "completion stamp")
        assert X.read_tank(api, ctx.tank_id)["construction_phase"] == PHASE_HYDROTEST_PASSED

        # The coating chain opens the package gates.
        application = X.create_coating(api, ctx.tank_id)
        X.accept_coating(api, application["id"])
        coated = X.read_tank(api, ctx.tank_id)
        assert coated["construction_phase"] == PHASE_COATED
        assert coated["quality_posture"] == POSTURE_OPEN

        X.package_with_documents(api, ctx)
        assert ctx.commissioning["document_count"] == 4
        assert ctx.commissioning["submitted_document_types"] == REQUIRED_DOCUMENT_TYPES
        assert ctx.commissioning["missing_document_types"] == []

        submitted = assert_object_envelope(
            api.package_submission(ctx.commissioning_id, submission_payload(), PE1), 200
        )
        assert submitted["status"] == PACKAGE_SUBMITTED
        assert submitted["submitted_by_user_id"] == PE1_ID
        assert submitted["missing_document_types"] == []

        # Pair three: the same operator may not review what they submitted.
        validate_error(
            api.package_review(
                ctx.commissioning_id, review_payload(REVIEW_ACCEPT), AI_AS_PE1
            ),
            ERR_SEGREGATION_OF_DUTIES,
            403,
        )
        untouched = X.read_commissioning_package(api, ctx.commissioning_id)
        assert untouched["status"] == PACKAGE_SUBMITTED
        assert untouched["reviewed_by_user_id"] is None
        assert untouched["accepted_at_utc"] is None
        assert untouched["deficiency_count"] == 0
        assert X.read_tank(api, ctx.tank_id)["construction_phase"] == PHASE_COATED

        reviewed = assert_object_envelope(
            api.package_review(ctx.commissioning_id, review_payload(REVIEW_ACCEPT), AI3), 200
        )
        assert reviewed["status"] == PACKAGE_ACCEPTED
        assert reviewed["reviewed_by_user_id"] == AI3_ID
        assert reviewed["deficiency_count"] == 0
        assert_instant(reviewed["accepted_at_utc"], "2026-08-11T00:00:00Z", "acceptance stamp")

        assert reviewed["bottom_remaining_life_years"] == pytest.approx(15.00)
        assert reviewed["internal_inspection_interval_years"] == 7
        assert reviewed["external_inspection_interval_years"] == 2
        assert_instant(
            reviewed["next_internal_due_utc"], "2033-08-11T00:00:00Z", "next internal due"
        )
        assert_instant(
            reviewed["next_external_due_utc"], "2028-08-11T00:00:00Z", "next external due"
        )

        assert X.read_tank(api, ctx.tank_id)["construction_phase"] == PHASE_COMMISSIONED
