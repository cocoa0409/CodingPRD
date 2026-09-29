"""The two paired approvals that must be split across two operators, and the
proof that splitting them locks no role out of its own surface."""

from test_helpers import (
    ApiErrorId,
    AwardStatus,
    CreditPolicy,
    GradeCode,
    GradeReplacementMode,
    GradeReplacementPolicy,
    IntakePosture,
    Modality,
    Pathway,
    PlacementStatus,
    PlanStatus,
    PriorOutcome,
    ProgressState,
    ProviderRoleType,
    ReferralStatus,
    ServiceCode,
    StudentStatus,
    SubjectArea,
    SupportSessionStatus,
    ALT_ED_TEACHER_HEADERS,
    DISTRICT_ADMIN_ALT_HEADERS,
    DISTRICT_ADMIN_HEADERS,
    REGISTRAR_ALT_HEADERS,
    REGISTRAR_HEADERS,
    assert_close,
    assert_seat_picture,
    assert_transcript_coding,
    factories as f,
    fixtures as fx,
    make_home_school_counselor_headers,
    make_placement_coordinator_headers,
    make_support_provider_staff_headers,
    validate_error,
    validate_success,
)

ALG1 = {
    "code": "ALG1",
    "title": "Algebra I",
    "subject_area": SubjectArea.MATH.value,
    "credit_value": 1.00,
    "modality": Modality.PACKET.value,
    "total_modules": 8,
    "required_seat_hours": 60.00,
    "pacing_days": 40,
    "proctoring_required": False,
    "ncaa_approved": False,
    "min_passing_percent": 60.00,
}

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

WIDE_CENTER = {
    "seat_capacity": 10,
    "certified_teacher_fte": 4.00,
    "support_staff_fte": 2.00,
    "max_students_per_teacher": 12,
}


def _submitted_by_the_first_registrar(api):
    """A finished competency enrollment whose submission was recorded against
    reg-01, so reg-01 is the comparand the award must differ from."""
    home_school = fx.open_home_school(api)
    center = fx.open_center(api, name="Cedar AEC", **WIDE_CENTER)
    course = fx.publish_course(api, **ALG1)
    student = fx.register_student(
        api,
        home_school["id"],
        state_student_id="S-5701",
        full_name="Uma Vitt",
        cohort_year=2027,
        grade_level=11,
    )
    plan = fx.open_active_plan(
        api,
        student["id"],
        required_credits_total=24.00,
        grade_replacement_policy=GradeReplacementPolicy.REPLACE_ON_RECOVERY.value,
    )
    referral = fx.screened_referral(
        api,
        student["id"],
        center["id"],
        home_school["id"],
        pathway=Pathway.CREDIT_DEFICIENCY.value,
        deficiency_credits=6.00,
        behavior_incident_count=1,
        days_disengaged=6,
    )
    fx.offer_seat(api, referral["id"], center["id"])
    placement = fx.accept_seat(
        api,
        referral["id"],
        home_school["id"],
        credit_policy=CreditPolicy.COMPETENCY.value,
        start_date="2026-08-01",
    )
    enrollment = fx.enroll_new_credit(api, placement["id"], course["id"])
    fx.report_progress(
        api,
        enrollment["id"],
        modules_passed_delta=8,
        seat_hours_delta=30.00,
        module_avg_percent=88.00,
    )
    submitted = fx.submit_work(api, enrollment["id"], 88.00, REGISTRAR_HEADERS)
    assert submitted["submitted_by_user_id"] == "reg-01"
    return {
        "student": student,
        "plan": plan,
        "enrollment": enrollment,
        "course": course,
    }


class TestTheAwardPairIsSplitAcrossTwoRegistrars:
    """reg-01 submitted, so reg-01 may not award; reg-02 may."""

    def test_the_submitting_registrar_cannot_award_its_own_submission(self, api):
        """The award is refused with ERR_SEGREGATION_OF_DUTIES at 403 and the plan's
        version token is not spent.

        PRD: "The `X-User-ID` recorded as `submitted_by_user_id` when an enrollment
        was submitted for award may not be the `X-User-ID` that awards credit for
        it, nor the one that denies the award."

        Design: Corner/rbac/award_credit_by_submitting_user_rejected
        """
        world = _submitted_by_the_first_registrar(api)
        before = fx.plan_version(api, world["plan"]["id"])

        response = api.award_credit(
            world["enrollment"]["id"],
            f.award_credit_payload(before),
            REGISTRAR_HEADERS,
        )
        validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)

        enrollment = fx.read_enrollment(api, world["enrollment"]["id"])
        assert enrollment["progress_state"] == ProgressState.SUBMITTED_FOR_AWARD.value
        assert enrollment["awarded_credits"] is None
        assert fx.plan_version(api, world["plan"]["id"]) == before

    def test_the_second_registrar_posts_the_identical_award(self, api):
        """reg-02 posts the full competency credit, the transcript row carries its
        own coding, and the ledger moves in one step.

        PRD: "That row carries the `course_enrollment_id` it was awarded for, the
        `student_id` denormalized from the enrollment's placement so the transcript
        can be queried by student, the `prior_course_record_id` it replaces or
        averages against when there is one, the computed `credits_awarded`, an
        `award_basis` copied verbatim from the placement's `credit_policy`, and a
        `posted_on` stamp holding the logical clock date at posting."

        Design: Corner/rbac/award_credit_by_submitting_user_rejected
        """
        world = _submitted_by_the_first_registrar(api)
        before = fx.plan_version(api, world["plan"]["id"])
        api.award_credit(
            world["enrollment"]["id"],
            f.award_credit_payload(before),
            REGISTRAR_HEADERS,
        )

        award = validate_success(
            api.award_credit(
                world["enrollment"]["id"],
                f.award_credit_payload(before),
                REGISTRAR_ALT_HEADERS,
            ),
            201,
        )
        assert award["course_enrollment_id"] == world["enrollment"]["id"]
        assert award["student_id"] == world["student"]["id"]
        assert award["prior_course_record_id"] is None
        assert_close(award["credits_awarded"], 1.00, "credits awarded")
        assert award["award_basis"] == CreditPolicy.COMPETENCY.value
        assert award["posted_on"] == "2026-08-01"
        assert award["status"] == AwardStatus.POSTED.value
        assert award["grade_replacement_mode"] == GradeReplacementMode.NONE.value
        assert_transcript_coding(award, "ALG1", "PK", GradeCode.B.value)
        assert award["ncaa_acceptable"] is False

        student = fx.read_student(api, world["student"]["id"])
        assert_close(student["credits_earned_total"], 1.00, "credits earned total")
        assert_close(student["alt_ed_credits"], 1.00, "alt ed credits")
        assert_close(student["ncaa_acceptable_credits"], 0.00, "ncaa credits")
        assert_close(student["gpa"], 3.00, "gpa")

        assert (
            fx.read_enrollment(api, world["enrollment"]["id"])["progress_state"]
            == ProgressState.AWARDED.value
        )
        assert fx.plan_version(api, world["plan"]["id"]) == before + 1


def _ready_for_re_entry(api):
    """A grade-12 placement whose readiness reads 0.7800: attendance exactly
    0.9000, one un-rated enrollment and one delivered support session."""
    home_school = fx.open_home_school(api)
    center = fx.open_center(api, name="Cedar AEC", **WIDE_CENTER)
    provider = fx.assign_provider(
        api,
        center["id"],
        role_type=ProviderRoleType.COUNSELOR.value,
        full_name="Ana Prieto",
        max_concurrent_students=2,
    )
    course = fx.publish_course(api, **ART1)
    student = fx.register_student(
        api,
        home_school["id"],
        state_student_id="S-5801",
        full_name="Vera Wold",
        cohort_year=2026,
        grade_level=12,
    )
    fx.open_active_plan(
        api,
        student["id"],
        required_credits_total=0.25,
        grade_replacement_policy=GradeReplacementPolicy.REPLACE_ON_RECOVERY.value,
    )
    fx.post_prior_record(
        api,
        student["id"],
        course["id"],
        original_percent=91.00,
        credits_attempted=0.25,
        outcome=PriorOutcome.PASSED.value,
    )
    referral = fx.screened_referral(
        api,
        student["id"],
        center["id"],
        home_school["id"],
        pathway=Pathway.RE_ENGAGEMENT.value,
        deficiency_credits=2.00,
        behavior_incident_count=0,
        days_disengaged=45,
    )
    fx.offer_seat(api, referral["id"], center["id"])
    placement = fx.accept_seat(
        api,
        referral["id"],
        home_school["id"],
        credit_policy=CreditPolicy.SEAT_TIME.value,
        start_date="2026-08-01",
    )
    fx.enroll_new_credit(api, placement["id"], course["id"])
    fx.log_attendance(api, placement["id"], 27, 30)
    session = fx.schedule_support_session(
        api,
        provider["id"],
        placement["id"],
        center["id"],
        start_at="2026-08-04T13:00:00.000Z",
        end_at="2026-08-04T14:00:00.000Z",
        service_code=ServiceCode.RE_ENGAGEMENT_CHECKIN.value,
    )
    fx.complete_support_session(api, session["id"], provider["id"], 50)
    return {"center": center, "student": student, "placement": placement}


class TestTheReEntryPairIsSplitAcrossTwoAdministrators:
    """The administrator who asked for the return may not grant it."""

    def test_the_requesting_administrator_cannot_approve_its_own_request(self, api):
        """admin-01 requests at readiness 0.7800 and is refused at approval with
        ERR_SEGREGATION_OF_DUTIES, leaving the placement pending.

        PRD: "Approval is subject to segregation of duties: the acting `X-User-ID`
        must differ from the recorded `re_entry_requested_by_user_id`, or the
        approval is refused with `ERR_SEGREGATION_OF_DUTIES` — the administrator who
        asked for the return may not be the one who grants it."

        Design: Corner/rbac/approve_re_entry_by_requesting_user_rejected
        """
        world = _ready_for_re_entry(api)
        placement = fx.read_placement(api, world["placement"]["id"])
        assert_close(placement["attendance_component"], 0.9000, "attendance component")
        assert_close(placement["pacing_component"], 1.0000, "pacing component")
        assert_close(placement["credit_component"], 0.0000, "credit component")
        assert_close(placement["readiness_base_score"], 0.7500, "readiness base score")
        assert_close(placement["engagement_bonus"], 0.0300, "engagement bonus")
        assert_close(placement["readiness_score"], 0.7800, "readiness score")

        pending = validate_success(
            api.request_re_entry(
                world["placement"]["id"],
                f.request_re_entry_payload(target_re_entry_date="2026-09-01"),
                DISTRICT_ADMIN_HEADERS,
            )
        )
        assert pending["status"] == PlacementStatus.RE_ENTRY_PENDING.value
        assert pending["re_entry_requested_by_user_id"] == "admin-01"

        response = api.approve_re_entry(
            world["placement"]["id"],
            f.approve_re_entry_payload(actual_re_entry_date="2026-09-01"),
            DISTRICT_ADMIN_HEADERS,
        )
        validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)

        held = fx.read_placement(api, world["placement"]["id"])
        assert held["status"] == PlacementStatus.RE_ENTRY_PENDING.value
        assert held["actual_re_entry_date"] is None

    def test_the_second_administrator_approves_and_releases_the_seat(self, api):
        """admin-02 moves the placement to RE_ENTERED, returns the student and hands
        the seat back to the centre.

        PRD: "Approval sets the student's `status` to `RE_ENTERED` and releases the
        seat: the center's `active_student_count` falls by one, `seats_committed`
        falls by one, `seats_available` rises by one, `student_teacher_ratio`,
        `staffing_headroom` and `intake_posture` are all re-derived, and — because
        releasing a committed seat can lift the posture into `OPEN` — a waitlisted
        referral may be promoted in the same request per §2.7."

        Design: Corner/rbac/approve_re_entry_by_requesting_user_rejected
        """
        world = _ready_for_re_entry(api)
        validate_success(
            api.request_re_entry(
                world["placement"]["id"],
                f.request_re_entry_payload(target_re_entry_date="2026-09-01"),
                DISTRICT_ADMIN_HEADERS,
            )
        )
        api.approve_re_entry(
            world["placement"]["id"],
            f.approve_re_entry_payload(actual_re_entry_date="2026-09-01"),
            DISTRICT_ADMIN_HEADERS,
        )

        approved = validate_success(
            api.approve_re_entry(
                world["placement"]["id"],
                f.approve_re_entry_payload(actual_re_entry_date="2026-09-01"),
                DISTRICT_ADMIN_ALT_HEADERS,
            )
        )
        assert approved["status"] == PlacementStatus.RE_ENTERED.value
        assert approved["actual_re_entry_date"] == "2026-09-01"

        assert (
            fx.read_student(api, world["student"]["id"])["status"]
            == StudentStatus.RE_ENTERED.value
        )
        center = fx.read_center(api, world["center"]["id"])
        assert_seat_picture(center, 0, 0, 10, IntakePosture.OPEN.value)
        assert_close(center["student_teacher_ratio"], 0.00, "student teacher ratio")
        assert center["staffing_headroom"] == 48


def _chain_prerequisites(api):
    """Everything a DistrictAdmin and a Registrar must open before the chain can
    start: a school, a centre, a behaviour specialist, a course and a student."""
    home_school = fx.open_home_school(api)
    center = fx.open_center(api, name="Cedar AEC", **WIDE_CENTER)
    provider = fx.assign_provider(
        api,
        center["id"],
        role_type=ProviderRoleType.BEHAVIOR_SPECIALIST.value,
        full_name="Cleo Duarte",
        max_concurrent_students=2,
    )
    course = fx.publish_course(api, **ALG1)
    student = fx.register_student(
        api,
        home_school["id"],
        state_student_id="S-5901",
        full_name="Wes Yaman",
        cohort_year=2027,
        grade_level=11,
    )
    return {
        "home_school": home_school,
        "center": center,
        "provider": provider,
        "course": course,
        "student": student,
        "counselor": make_home_school_counselor_headers(home_school["id"]),
        "coordinator": make_placement_coordinator_headers(center["id"]),
    }


BEHAVIOR_REFERRAL = {
    "pathway": Pathway.BEHAVIOR.value,
    "deficiency_credits": 3.00,
    "behavior_incident_count": 4,
    "days_disengaged": 15,
}


class TestEveryRoleStillOwnsItsOwnExclusiveMove:
    """One referral-to-service chain, each hop performed by its own role."""

    def test_the_intake_chain_runs_registrar_counselor_coordinator_counselor(
        self, api
    ):
        """The plan, the referral, the screening, the offer and the acceptance each
        succeed for the one role the endpoint lists.

        PRD: "A `HomeSchoolCounselor` whose `X-User-ID` equals the referred
        student's `home_school_id` moves the referral from `PLACEMENT_OFFERED` to
        `ACCEPTED`, a terminal status, supplying the two inputs that define the
        placement: `credit_policy`, which is either `SEAT_TIME` or `COMPETENCY` and
        is fixed here for the whole placement, and `start_date`, the first day of
        attendance at the center as an ISO date."

        Design: Corner/rbac/each_role_performs_its_own_exclusive_operation
        """
        world = _chain_prerequisites(api)

        plan = validate_success(
            api.create_graduation_plan(
                f.graduation_plan_payload(
                    world["student"]["id"], required_credits_total=24.00
                ),
                REGISTRAR_HEADERS,
            ),
            201,
        )
        assert plan["status"] == PlanStatus.DRAFT.value

        referral = validate_success(
            api.create_referral(
                f.referral_payload(
                    world["student"]["id"], world["center"]["id"], **BEHAVIOR_REFERRAL
                ),
                world["counselor"],
            ),
            201,
        )
        assert referral["status"] == ReferralStatus.SUBMITTED.value
        assert_close(referral["priority_score"], 0.6550, "priority score")

        screened = validate_success(
            api.screen_referral(
                referral["id"],
                f.screen_payload(screening_note="intake reviewed"),
                world["coordinator"],
            )
        )
        assert screened["status"] == ReferralStatus.SCREENING.value
        assert screened["screening_note"] == "intake reviewed"

        offered = validate_success(
            api.offer_referral(
                referral["id"],
                f.offer_payload(fx.center_version(api, world["center"]["id"])),
                world["coordinator"],
            )
        )
        assert offered["status"] == ReferralStatus.PLACEMENT_OFFERED.value

        placement = validate_success(
            api.accept_offer(
                referral["id"],
                f.accept_offer_payload(
                    credit_policy=CreditPolicy.SEAT_TIME.value,
                    start_date="2026-08-01",
                ),
                world["counselor"],
            ),
            201,
        )
        assert placement["status"] == PlacementStatus.ACTIVE.value
        assert placement["credit_policy"] == CreditPolicy.SEAT_TIME.value

    def test_the_service_chain_runs_teacher_coordinator_then_provider(self, api):
        """The teacher opens the coursework, the coordinator books the service and
        only the provider records its delivery.

        PRD: "Delivery is recorded by the provider itself and nobody else: the
        acting `X-User-ID` must equal the session's `support_provider_id`, and
        completion moves `status` from `SCHEDULED` to `COMPLETED`, which is
        terminal."

        Design: Corner/rbac/each_role_performs_its_own_exclusive_operation
        """
        world = _chain_prerequisites(api)
        referral = fx.screened_referral(
            api,
            world["student"]["id"],
            world["center"]["id"],
            world["home_school"]["id"],
            **BEHAVIOR_REFERRAL,
        )
        fx.offer_seat(api, referral["id"], world["center"]["id"])
        placement = fx.accept_seat(
            api,
            referral["id"],
            world["home_school"]["id"],
            credit_policy=CreditPolicy.SEAT_TIME.value,
            start_date="2026-08-01",
        )

        enrollment = validate_success(
            api.create_course_enrollment(
                f.new_credit_enrollment_payload(
                    placement["id"],
                    world["course"]["id"],
                    fx.placement_version(api, placement["id"]),
                ),
                ALT_ED_TEACHER_HEADERS,
            ),
            201,
        )
        assert enrollment["progress_state"] == ProgressState.IN_PROGRESS.value

        session = validate_success(
            api.create_support_session(
                f.support_session_payload(
                    world["provider"]["id"],
                    placement["id"],
                    start_at="2026-08-04T13:00:00.000Z",
                    end_at="2026-08-04T14:00:00.000Z",
                    service_code=ServiceCode.BEHAVIOR_COACHING.value,
                ),
                world["coordinator"],
            ),
            201,
        )
        assert session["status"] == SupportSessionStatus.SCHEDULED.value

        completed = validate_success(
            api.complete_support_session(
                session["id"],
                f.complete_support_session_payload(60),
                make_support_provider_staff_headers(world["provider"]["id"]),
            )
        )
        assert completed["status"] == SupportSessionStatus.COMPLETED.value
        assert completed["minutes_delivered"] == 60

        assert fx.read_placement(api, placement["id"])["support_sessions_completed"] == 1
        assert fx.read_provider(api, world["provider"]["id"])[
            "completed_session_count"
        ] == 1
