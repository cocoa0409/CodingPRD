"""Writes that succeed or fail purely because of a derived field on a third
entity the request never names."""

from test_helpers import (
    ApiErrorId,
    CreditPolicy,
    EnrollmentType,
    GradeCode,
    GradeReplacementPolicy,
    IntakePosture,
    IntegrityState,
    PacingFlag,
    Pathway,
    PlacementStatus,
    PlanPosture,
    PriorOutcome,
    ProgressState,
    ProviderRoleType,
    ServiceCode,
    SubjectArea,
    ALT_ED_TEACHER_HEADERS,
    DISTRICT_ADMIN_HEADERS,
    assert_close,
    fixtures as fx,
    make_placement_coordinator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ALG1 = {
    "code": "ALG1",
    "title": "Algebra I",
    "subject_area": SubjectArea.MATH.value,
    "credit_value": 1.00,
    "total_modules": 8,
    "required_seat_hours": 60.00,
    "pacing_days": 40,
    "min_passing_percent": 60.00,
}


def _one_teacher_center_world(api):
    """A centre whose single 1.00-FTE teacher is fully committed by one student,
    so staffing drives the posture to FROZEN while nine seats stand empty."""
    home_school = fx.open_home_school(api)
    center = fx.open_center(
        api,
        name="Birch AEC",
        seat_capacity=10,
        certified_teacher_fte=1.00,
        support_staff_fte=1.00,
        max_students_per_teacher=1,
    )
    course = fx.publish_course(api, **ALG1)
    student = fx.register_student(
        api, home_school["id"], grade_level=10, cohort_year=2028
    )
    referral = fx.screened_referral(
        api,
        student["id"],
        center["id"],
        home_school["id"],
        pathway=Pathway.BEHAVIOR.value,
        deficiency_credits=0.00,
        behavior_incident_count=3,
        days_disengaged=0,
    )
    fx.offer_seat(api, referral["id"], center["id"])
    placement = fx.accept_seat(
        api,
        referral["id"],
        home_school["id"],
        credit_policy=CreditPolicy.SEAT_TIME.value,
    )
    return {
        "home_school": home_school,
        "center": center,
        "course": course,
        "student": student,
        "placement": placement,
    }


def _enrollment_body(placement_id, course_id, version):
    return {
        "placement_id": placement_id,
        "course_id": course_id,
        "enrollment_type": EnrollmentType.NEW_CREDIT.value,
        "expected_placement_version": version,
    }


class TestEnrollmentCreateReadsTheCentersStaffingPosture:
    """The enrollment is legal or illegal because of the centre, not the payload."""

    def test_the_frozen_posture_comes_from_staffing_while_seats_stand_empty(self, api):
        """Nine seats are free, yet headroom of 0 freezes intake and the create is
        refused with ERR_INTAKE_FROZEN without consuming the version token.

        PRD: "A center whose `intake_posture` is `FROZEN` accepts no new offer and
        no new enrollment (`ERR_INTAKE_FROZEN`)"

        Design: Difficulty/cross_entity_state_dependency/enrollment_create_blocked_by_frozen_center_posture
        """
        world = _one_teacher_center_world(api)
        center = fx.read_center(api, world["center"]["id"])
        assert center["active_student_count"] == 1
        assert center["staffing_headroom"] == 0
        assert center["seats_available"] == 9
        assert center["intake_posture"] == IntakePosture.FROZEN.value

        placement_version = fx.placement_version(api, world["placement"]["id"])
        response = api.create_course_enrollment(
            _enrollment_body(
                world["placement"]["id"], world["course"]["id"], placement_version
            ),
            ALT_ED_TEACHER_HEADERS,
        )
        validate_error(response, ApiErrorId.INTAKE_FROZEN.value, 409)
        assert fx.placement_version(api, world["placement"]["id"]) == placement_version

        rows, _meta = validate_paginated(
            api.list_course_enrollments(
                ALT_ED_TEACHER_HEADERS, {"placement_id": world["placement"]["id"]}
            )
        )
        assert rows == []

    def test_raising_the_teacher_fte_alone_reopens_the_identical_payload(self, api):
        """Only the centre's staffing changes, and the same enrollment body then
        creates a fresh IN_PROGRESS enrollment.

        PRD: "A `RESTRICTED` center still accepts new course enrollments for
        students already placed there, but it accepts a new seat offer only for a
        referral whose `pathway` is `BEHAVIOR` or whose `priority_score` is at
        least 0.5000; an offer that meets neither condition is refused with
        `ERR_INTAKE_RESTRICTED`."

        Design: Difficulty/cross_entity_state_dependency/enrollment_create_blocked_by_frozen_center_posture
        """
        world = _one_teacher_center_world(api)
        placement_version = fx.placement_version(api, world["placement"]["id"])
        api.create_course_enrollment(
            _enrollment_body(
                world["placement"]["id"], world["course"]["id"], placement_version
            ),
            ALT_ED_TEACHER_HEADERS,
        )

        restaffed = validate_success(
            api.revise_staffing(
                world["center"]["id"],
                {
                    "certified_teacher_fte": 2.00,
                    "expected_center_version": fx.center_version(
                        api, world["center"]["id"]
                    ),
                },
                DISTRICT_ADMIN_HEADERS,
            )
        )
        assert_close(restaffed["certified_teacher_fte"], 2.00, "teacher fte")
        assert restaffed["staffing_headroom"] == 1
        assert_close(restaffed["student_teacher_ratio"], 0.50, "student teacher ratio")
        assert restaffed["intake_posture"] == IntakePosture.RESTRICTED.value

        enrollment = validate_success(
            api.create_course_enrollment(
                _enrollment_body(
                    world["placement"]["id"], world["course"]["id"], placement_version
                ),
                ALT_ED_TEACHER_HEADERS,
            ),
            201,
        )
        assert enrollment["progress_state"] == ProgressState.IN_PROGRESS.value
        assert enrollment["integrity_state"] == IntegrityState.CLEAR.value
        assert enrollment["enrolled_on"] == "2026-08-01"
        assert enrollment["pacing_flag"] == PacingFlag.NOT_YET_RATED.value

    def test_only_the_successful_create_advances_the_placement_version(self, api):
        """Across a refusal and a success the placement's version moves by exactly
        one.

        PRD: "`expected_placement_version` accompanies the request under the
        stale-version guard of §2.6, and a successful create increments the
        placement's `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/enrollment_create_blocked_by_frozen_center_posture
        """
        world = _one_teacher_center_world(api)
        before = fx.placement_version(api, world["placement"]["id"])

        api.create_course_enrollment(
            _enrollment_body(world["placement"]["id"], world["course"]["id"], before),
            ALT_ED_TEACHER_HEADERS,
        )
        api.revise_staffing(
            world["center"]["id"],
            {
                "certified_teacher_fte": 2.00,
                "expected_center_version": fx.center_version(api, world["center"]["id"]),
            },
            DISTRICT_ADMIN_HEADERS,
        )
        validate_success(
            api.create_course_enrollment(
                _enrollment_body(
                    world["placement"]["id"], world["course"]["id"], before
                ),
                ALT_ED_TEACHER_HEADERS,
            ),
            201,
        )

        assert fx.placement_version(api, world["placement"]["id"]) == before + 1


ENG1 = {
    "code": "ENG1",
    "title": "English I",
    "subject_area": SubjectArea.ELA.value,
    "credit_value": 2.00,
    "total_modules": 8,
    "required_seat_hours": 60.00,
    "pacing_days": 40,
    "min_passing_percent": 60.00,
}


def _off_track_plan_world(api):
    """A placement whose own re-entry gates are both satisfied, sitting under a
    graduation plan with no credits at all."""
    home_school = fx.open_home_school(api)
    center = fx.open_center(api)
    course = fx.publish_course(api, **ALG1)
    other_course = fx.publish_course(api, **ENG1)
    student = fx.register_student(
        api, home_school["id"], grade_level=9, cohort_year=2029
    )
    plan = fx.open_active_plan(
        api,
        student["id"],
        required_credits_total=8.00,
        grade_replacement_policy=GradeReplacementPolicy.AVERAGE_ON_RECOVERY.value,
    )
    referral = fx.screened_referral(
        api,
        student["id"],
        center["id"],
        home_school["id"],
        deficiency_credits=4.00,
        behavior_incident_count=1,
        days_disengaged=6,
    )
    fx.offer_seat(api, referral["id"], center["id"])
    placement = fx.accept_seat(
        api,
        referral["id"],
        home_school["id"],
        credit_policy=CreditPolicy.SEAT_TIME.value,
        start_date="2026-08-01",
    )
    enrollment = fx.enroll_new_credit(api, placement["id"], course["id"])
    fx.report_progress(
        api,
        enrollment["id"],
        modules_passed_delta=8,
        seat_hours_delta=45.00,
        module_avg_percent=86.00,
    )
    provider = fx.assign_provider(
        api,
        center["id"],
        role_type=ProviderRoleType.SOCIAL_WORKER.value,
        max_concurrent_students=2,
    )
    session = fx.schedule_support_session(
        api,
        provider["id"],
        placement["id"],
        center["id"],
        start_at="2026-08-05T15:00:00.000Z",
        end_at="2026-08-05T16:00:00.000Z",
        service_code=ServiceCode.SOCIAL_WORK.value,
    )
    fx.complete_support_session(api, session["id"], provider["id"])
    validate_success(api.advance_clock_to("2026-08-11T00:00:00Z", DISTRICT_ADMIN_HEADERS))
    placement = fx.log_attendance(api, placement["id"], 45, 50)
    return {
        "home_school": home_school,
        "center": center,
        "course": course,
        "other_course": other_course,
        "student": student,
        "plan": plan,
        "placement": placement,
        "coordinator": make_placement_coordinator_headers(center["id"]),
    }


class TestReEntryRequestReadsTheGraduationPlansPosture:
    """The placement's own gates pass; the plan on another entity blocks it."""

    def test_the_off_track_plan_blocks_a_placement_that_meets_its_own_gates(self, api):
        """Attendance 0.9000 and readiness 0.7800 both clear, yet the request is
        refused with ERR_PLAN_POSTURE_BLOCKS_RE_ENTRY.

        PRD: "Re-entry to the home school requires the student's graduation plan
        `posture` to be `ON_TRACK` or `AT_RISK`; an `OFF_TRACK` plan blocks the
        request."

        Design: Difficulty/cross_entity_state_dependency/re_entry_request_blocked_by_off_track_plan
        """
        world = _off_track_plan_world(api)
        placement = fx.read_placement(api, world["placement"]["id"])
        assert_close(placement["attendance_rate"], 0.9000, "attendance rate")
        assert_close(placement["readiness_score"], 0.7800, "readiness score")
        assert placement["re_entry_eligible"] is False

        plan = fx.read_plan(api, world["plan"]["id"])
        assert_close(plan["expected_credits_by_grade"], 2.00, "expected credits")
        assert_close(plan["credits_earned"], 0.00, "plan credits earned")
        assert_close(plan["credits_remaining"], 8.00, "plan credits remaining")
        assert plan["posture"] == PlanPosture.OFF_TRACK.value

        response = api.request_re_entry(
            world["placement"]["id"],
            {"target_re_entry_date": "2026-08-24"},
            world["coordinator"],
        )
        body = validate_error(
            response, ApiErrorId.PLAN_POSTURE_BLOCKS_RE_ENTRY.value, 409
        )
        assert body["error_id"] != ApiErrorId.ATTENDANCE_BELOW_MINIMUM.value
        assert body["error_id"] != ApiErrorId.READINESS_BELOW_THRESHOLD.value

        still_active = fx.read_placement(api, world["placement"]["id"])
        assert still_active["status"] == PlacementStatus.ACTIVE.value
        assert still_active["re_entry_requested_by_user_id"] is None

    def test_an_unrelated_historical_row_lifts_the_plan_to_at_risk(self, api):
        """Posting 1.75 credits of history clears the 1.60 AT_RISK threshold
        without reaching the 1.90 ON_TRACK threshold, and the placement's own
        figures do not move.

        PRD: "Otherwise, if the earned credits are at least eighty percent of
        that same expectation, again rounded to 2 decimal places before comparing,
        the posture is `AT_RISK`."

        Design: Difficulty/cross_entity_state_dependency/re_entry_request_blocked_by_off_track_plan
        """
        world = _off_track_plan_world(api)
        api.request_re_entry(
            world["placement"]["id"],
            {"target_re_entry_date": "2026-08-24"},
            world["coordinator"],
        )

        record = fx.post_prior_record(
            api,
            world["student"]["id"],
            world["other_course"]["id"],
            original_percent=78.00,
            credits_attempted=1.75,
            outcome=PriorOutcome.PASSED.value,
        )
        assert record["original_grade_code"] == GradeCode.C.value

        student = fx.read_student(api, world["student"]["id"])
        assert_close(student["credits_earned_total"], 1.75, "credits earned total")

        plan = fx.read_plan(api, world["plan"]["id"])
        assert_close(plan["credits_earned"], 1.75, "plan credits earned")
        assert_close(plan["credits_remaining"], 6.25, "plan credits remaining")
        assert plan["posture"] == PlanPosture.AT_RISK.value

        placement = fx.read_placement(api, world["placement"]["id"])
        assert_close(placement["attendance_rate"], 0.9000, "attendance rate")
        assert_close(placement["readiness_score"], 0.7800, "readiness score")
        assert placement["re_entry_eligible"] is True

    def test_the_identical_request_then_succeeds_and_the_seat_is_still_held(self, api):
        """The re-entry request now moves the placement to RE_ENTRY_PENDING while
        the centre keeps counting the student.

        PRD: "The seat is **not** released at this point: a placement in
        `RE_ENTRY_PENDING` still counts inside the center's
        `active_student_count`, so nothing about the center's capacity picture
        changes yet."

        Design: Difficulty/cross_entity_state_dependency/re_entry_request_blocked_by_off_track_plan
        """
        world = _off_track_plan_world(api)
        fx.post_prior_record(
            api,
            world["student"]["id"],
            world["other_course"]["id"],
            original_percent=78.00,
            credits_attempted=1.75,
            outcome=PriorOutcome.PASSED.value,
        )

        pending = validate_success(
            api.request_re_entry(
                world["placement"]["id"],
                {"target_re_entry_date": "2026-08-24"},
                world["coordinator"],
            )
        )
        assert pending["status"] == PlacementStatus.RE_ENTRY_PENDING.value
        assert pending["target_re_entry_date"] == "2026-08-24"

        center = fx.read_center(api, world["center"]["id"])
        assert center["active_student_count"] == 1
        assert center["intake_posture"] == IntakePosture.OPEN.value
