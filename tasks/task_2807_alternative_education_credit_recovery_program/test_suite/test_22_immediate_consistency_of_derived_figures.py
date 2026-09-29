"""Immediate consistency read literally: the derived figures a write changes are
already correct in that write's own response body, and the following read adds
nothing to them."""

from test_helpers import (
    ALT_ED_TEACHER_HEADERS,
    CreditPolicy,
    DISTRICT_ADMIN_HEADERS,
    IntakePosture,
    Modality,
    Pathway,
    ProviderRoleType,
    ServiceCode,
    SubjectArea,
    assert_close,
    assert_readiness_figures,
    assert_seat_picture,
    factories as f,
    fixtures as fx,
    validate_success,
)

ART1 = {
    "code": "ART1",
    "title": "Studio Art",
    "subject_area": SubjectArea.ELECTIVE.value,
    "credit_value": 0.25,
    "modality": Modality.PACKET.value,
    "total_modules": 1,
    "required_seat_hours": 15.00,
    "pacing_days": 30,
    "proctoring_required": False,
    "ncaa_approved": False,
    "min_passing_percent": 60.00,
}

RE_ENGAGEMENT_CASE = {
    "pathway": Pathway.RE_ENGAGEMENT.value,
    "deficiency_credits": 2.00,
    "behavior_incident_count": 0,
    "days_disengaged": 45,
}


def _placement_with_one_fresh_enrollment_and_one_service(api):
    """A grade-12 placement holding one enrollment created today, so its pace is
    not yet rated, and one delivered support session."""
    home_school = fx.open_home_school(api)
    center = fx.open_center(api, name="Cedar AEC")
    provider = fx.assign_provider(
        api,
        center["id"],
        role_type=ProviderRoleType.COUNSELOR.value,
        full_name="Ida Jung",
        max_concurrent_students=2,
    )
    course = fx.publish_course(api, **ART1)
    student = fx.register_student(
        api,
        home_school["id"],
        state_student_id="S-6701",
        full_name="Jonas Kerr",
        grade_level=12,
        cohort_year=2026,
    )
    referral = fx.screened_referral(
        api, student["id"], center["id"], home_school["id"], **RE_ENGAGEMENT_CASE
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
    session = fx.schedule_support_session(
        api,
        provider["id"],
        placement["id"],
        center["id"],
        start_at="2026-08-04T13:00:00.000Z",
        end_at="2026-08-04T14:00:00.000Z",
        service_code=ServiceCode.RE_ENGAGEMENT_CHECKIN.value,
    )
    fx.complete_support_session(api, session["id"], provider["id"], minutes_delivered=50)
    return {
        "center": center,
        "provider": provider,
        "student": student,
        "placement": placement,
        "enrollment": enrollment,
    }


def _post_attendance(api, placement_id, days_present, days_enrolled):
    return validate_success(
        api.log_attendance(
            placement_id,
            f.attendance_payload(days_present, days_enrolled),
            ALT_ED_TEACHER_HEADERS,
        )
    )


class TestTheAttendanceWriteAlreadyCarriesTheNewReadinessFigures:
    """Twenty-seven days of thirty are posted once, and the response is already
    the whole readiness picture."""

    def test_the_posting_response_reports_every_recomputed_readiness_field(self, api):
        """The write's own body carries attendance_rate 0.9000, the three components
        0.9000, 1.0000 and 0.0000, a base of 0.7500, a bonus of 0.0300 and a readiness
        score of 0.7800.

        PRD: "A successful attendance posting re-derives `attendance_rate`,
        `attendance_component`, `readiness_base_score`, `engagement_bonus`,
        `readiness_score` and `re_entry_eligible`."

        Design: Corner/consistency model/attendance_response_carries_recomputed_readiness_immediately
        """
        world = _placement_with_one_fresh_enrollment_and_one_service(api)
        posted = _post_attendance(api, world["placement"]["id"], 27, 30)

        assert posted["days_present"] == 27
        assert posted["days_enrolled"] == 30
        assert_close(posted["attendance_rate"], 0.9000, "attendance rate")
        assert_close(posted["attendance_component"], 0.9000, "attendance component")
        assert_close(posted["pacing_component"], 1.0000, "pacing component")
        assert_close(posted["credit_component"], 0.0000, "credit component")
        assert_readiness_figures(posted, base_score=0.7500, bonus=0.0300, score=0.7800)
        assert posted["support_sessions_completed"] == 1

    def test_the_immediately_following_read_adds_nothing(self, api):
        """A GET taken straight after the write returns the identical nine derived
        values, so no field lags behind the posting.

        PRD: "Second, every derived figure in this system is recomputed from current
        persisted state on every read rather than cached, so a seat count, a readiness
        score, a GPA or a cohort flag can never be observed stale."

        Design: Corner/consistency model/attendance_response_carries_recomputed_readiness_immediately
        """
        world = _placement_with_one_fresh_enrollment_and_one_service(api)
        posted = _post_attendance(api, world["placement"]["id"], 27, 30)
        read = fx.read_placement(api, world["placement"]["id"])

        for field in (
            "days_present",
            "days_enrolled",
            "attendance_rate",
            "attendance_component",
            "pacing_component",
            "credit_component",
            "readiness_base_score",
            "engagement_bonus",
            "readiness_score",
        ):
            assert read[field] == posted[field], f"{field} disagrees after the write"

    def test_a_second_posting_moves_the_figures_again_in_its_own_body(self, api):
        """Ten absent days drop the rate to 0.6750 and the base to 0.6375, which falls
        out of the bonus tier, so the score is the bare base.

        PRD: "The tier is selected on the **rounded base score**, in fixed order: when
        the base is at least 0.8000 and `support_sessions_completed` is at least 2, the
        bonus is 0.0500; otherwise, when the base is at least 0.6500 and
        `support_sessions_completed` is at least 1, the bonus is 0.0300; otherwise the
        bonus is 0.0000."

        Design: Corner/consistency model/attendance_response_carries_recomputed_readiness_immediately
        """
        world = _placement_with_one_fresh_enrollment_and_one_service(api)
        _post_attendance(api, world["placement"]["id"], 27, 30)
        second = _post_attendance(api, world["placement"]["id"], 0, 10)

        assert second["days_present"] == 27
        assert second["days_enrolled"] == 40
        assert_close(second["attendance_rate"], 0.6750, "attendance rate")
        assert_close(second["attendance_component"], 0.6750, "attendance component")
        assert_readiness_figures(second, base_score=0.6375, bonus=0.0000, score=0.6375)
        assert second["re_entry_eligible"] is False


def _center_carrying_one_active_placement(api):
    """A 10-seat centre at 4.00 certified FTE with exactly one student on the
    roster, so the headroom is 47 and the posture is OPEN."""
    home_school = fx.open_home_school(api)
    center = fx.open_center(api, name="Cedar AEC")
    student = fx.register_student(
        api,
        home_school["id"],
        state_student_id="S-6801",
        full_name="Kira Lund",
        grade_level=11,
        cohort_year=2027,
    )
    referral = fx.screened_referral(
        api,
        student["id"],
        center["id"],
        home_school["id"],
        deficiency_credits=6.00,
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
    return {"center": center, "student": student, "placement": placement}


def _cut_the_teaching_staff(api, center_id, expected_center_version):
    return api.revise_staffing(
        center_id,
        f.staffing_payload(expected_center_version, certified_teacher_fte=0.20),
        DISTRICT_ADMIN_HEADERS,
    )


class TestTheStaffingPatchShowsThePostureFlipInItsOwnResponse:
    """Cutting the certified FTE to 0.20 drops the headroom from 47 to exactly 1,
    and the PATCH body says so without waiting for a read."""

    def test_the_patch_body_already_reports_the_restricted_posture(self, api):
        """The pre-edit read is OPEN at headroom 47 and ratio 0.25, and the PATCH
        response itself reports headroom 1, ratio 5.00 and RESTRICTED with the same
        nine seats free.

        PRD: "A revision that is accepted re-derives `student_teacher_ratio`,
        `staffing_headroom` and `intake_posture`, and — because raising the certified
        FTE can lift a center out of `FROZEN` or `RESTRICTED` — may trigger the single
        waitlist promotion described in §2.7."

        Design: Corner/consistency model/staffing_patch_response_shows_the_posture_flip_in_its_own_body
        """
        world = _center_carrying_one_active_placement(api)
        before = fx.read_center(api, world["center"]["id"])
        assert_close(before["certified_teacher_fte"], 4.00, "certified teacher fte")
        assert before["staffing_headroom"] == 47
        assert_close(before["student_teacher_ratio"], 0.25, "student teacher ratio")
        assert_seat_picture(before, 1, 0, 9, IntakePosture.OPEN.value)

        revised = validate_success(
            _cut_the_teaching_staff(api, world["center"]["id"], before["version"])
        )
        assert_close(revised["certified_teacher_fte"], 0.20, "certified teacher fte")
        assert revised["staffing_headroom"] == 1
        assert_close(revised["student_teacher_ratio"], 5.00, "student teacher ratio")
        assert_seat_picture(revised, 1, 0, 9, IntakePosture.RESTRICTED.value)

    def test_the_following_read_never_disagrees_with_the_write(self, api):
        """The cut is accepted because the new headroom is 1 rather than below zero,
        and the following GET returns the same figures one version later.

        PRD: "A revision that would leave `staffing_headroom` below zero when measured
        against the center's existing `ACTIVE` and `RE_ENTRY_PENDING` placements is
        refused outright with `ERR_STAFFING_RATIO_EXCEEDED`; the district will not let
        a paper edit create a ratio violation for students already sitting in the
        building."

        Design: Corner/consistency model/staffing_patch_response_shows_the_posture_flip_in_its_own_body
        """
        world = _center_carrying_one_active_placement(api)
        before_version = fx.center_version(api, world["center"]["id"])
        revised = validate_success(
            _cut_the_teaching_staff(api, world["center"]["id"], before_version)
        )

        read = fx.read_center(api, world["center"]["id"])
        for field in (
            "certified_teacher_fte",
            "staffing_headroom",
            "student_teacher_ratio",
            "seats_available",
            "seats_committed",
            "active_student_count",
            "intake_posture",
        ):
            assert read[field] == revised[field], f"{field} disagrees after the write"
        assert read["version"] == before_version + 1
