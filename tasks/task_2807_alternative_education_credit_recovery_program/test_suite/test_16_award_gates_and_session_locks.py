"""The two policy-specific award refusals, and the way both session families
lock after their single forward transition."""

from test_helpers import (
    ApiErrorId,
    CreditPolicy,
    Modality,
    ProctorSessionStatus,
    ProgressState,
    ProviderRoleType,
    ServiceCode,
    SubjectArea,
    SupportSessionStatus,
    assert_close,
    factories as f,
    fixtures as fx,
    make_placement_coordinator_headers,
    make_support_provider_staff_headers,
    validate_error,
    validate_paginated,
    validate_success,
    REGISTRAR_HEADERS,
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

ENG1 = dict(ALG1, code="ENG1", title="English I", subject_area=SubjectArea.ELA.value)

BIO1 = {
    "code": "BIO1",
    "title": "Biology I",
    "subject_area": SubjectArea.SCIENCE.value,
    "credit_value": 1.00,
    "modality": Modality.ONLINE.value,
    "total_modules": 8,
    "required_seat_hours": 60.00,
    "pacing_days": 40,
    "proctoring_required": True,
    "proctored_exam_weight": 0.40,
    "ncaa_approved": True,
    "min_passing_percent": 60.00,
}

DEFICIENT = {
    "deficiency_credits": 6.00,
    "behavior_incident_count": 1,
    "days_disengaged": 6,
}


def _both_policies_submitted(api):
    """One student holding two placements: a COMPETENCY one whose ALG1 work sits
    at mastery 65.00, and a SEAT_TIME one whose ENG1 work has 5.00 of 60.00
    hours banked. Both are submitted for award."""
    home_school = fx.open_home_school(api)
    center = fx.open_center(api, name="Cedar AEC")
    competency_course = fx.publish_course(api, **ALG1)
    seat_time_course = fx.publish_course(api, **ENG1)
    student = fx.register_student(
        api, home_school["id"], state_student_id="S-5001", grade_level=11, cohort_year=2027
    )
    plan = fx.open_active_plan(api, student["id"], required_credits_total=24.00)

    first_referral = fx.screened_referral(
        api, student["id"], center["id"], home_school["id"], **DEFICIENT
    )
    fx.offer_seat(api, first_referral["id"], center["id"])
    competency_placement = fx.accept_seat(
        api,
        first_referral["id"],
        home_school["id"],
        credit_policy=CreditPolicy.COMPETENCY.value,
        start_date="2026-08-01",
    )
    competency_enrollment = fx.enroll_new_credit(
        api, competency_placement["id"], competency_course["id"]
    )
    fx.report_progress(
        api,
        competency_enrollment["id"],
        modules_passed_delta=5,
        seat_hours_delta=40.00,
        module_avg_percent=65.00,
    )
    fx.submit_work(api, competency_enrollment["id"], 62.00)

    second_referral = fx.screened_referral(
        api,
        student["id"],
        center["id"],
        home_school["id"],
        prior_referral_id=first_referral["id"],
        **DEFICIENT,
    )
    fx.offer_seat(api, second_referral["id"], center["id"])
    seat_time_placement = fx.accept_seat(
        api,
        second_referral["id"],
        home_school["id"],
        credit_policy=CreditPolicy.SEAT_TIME.value,
        start_date="2026-08-02",
    )
    seat_time_enrollment = fx.enroll_new_credit(
        api, seat_time_placement["id"], seat_time_course["id"]
    )
    fx.report_progress(
        api,
        seat_time_enrollment["id"],
        modules_passed_delta=8,
        seat_hours_delta=5.00,
        module_avg_percent=90.00,
    )
    fx.submit_work(api, seat_time_enrollment["id"], 90.00)

    return {
        "student": student,
        "plan": plan,
        "competency_enrollment": competency_enrollment,
        "seat_time_enrollment": seat_time_enrollment,
    }


class TestEachCreditPolicyOwnsItsOwnAwardRefusal:
    """The mastery gate fires only under COMPETENCY and the seat-hour gate only
    under SEAT_TIME."""

    def test_mastery_sixty_five_is_refused_although_the_final_percent_passed(self, api):
        """The COMPETENCY award returns ERR_MASTERY_NOT_MET because mastery 65.00 sits
        below the partial band, even though final_percent 62.00 cleared the course's
        60.00 minimum.

        PRD: "and when `mastery_pct` is below 70.00 the award computes to 0.00 and is
        refused with `ERR_MASTERY_NOT_MET`."

        Design: Corner/errors/award_credit_mastery_and_seat_time_gates_rejected
        """
        world = _both_policies_submitted(api)
        enrollment = fx.read_enrollment(api, world["competency_enrollment"]["id"])
        assert_close(enrollment["mastery_pct"], 65.00, "mastery percent")
        assert_close(enrollment["final_percent"], 62.00, "final percent")
        assert_close(enrollment["projected_credits"], 0.00, "projected credits")

        response = api.award_credit(
            world["competency_enrollment"]["id"],
            f.award_credit_payload(fx.plan_version(api, world["plan"]["id"])),
            REGISTRAR_HEADERS,
        )
        body = validate_error(response, ApiErrorId.MASTERY_NOT_MET.value, 409)
        assert body["error_id"] != ApiErrorId.SEAT_TIME_INSUFFICIENT.value
        assert body["error_id"] != ApiErrorId.FINAL_PERCENT_BELOW_PASSING.value

    def test_five_of_sixty_hours_is_refused_although_mastery_was_ninety(self, api):
        """The SEAT_TIME award returns ERR_SEAT_TIME_INSUFFICIENT because 0.0833 of
        the required hours floors to no credit, and the variant never reads the 90.00
        mastery.

        PRD: "Mastery is ignored entirely in this variant — a student with the hours
        banks the credit, and a student whose seat-hour computation floors all the way
        to 0.00 is refused with `ERR_SEAT_TIME_INSUFFICIENT`."

        Design: Corner/errors/award_credit_mastery_and_seat_time_gates_rejected
        """
        world = _both_policies_submitted(api)
        enrollment = fx.read_enrollment(api, world["seat_time_enrollment"]["id"])
        assert_close(enrollment["seat_hours_logged"], 5.00, "seat hours logged")
        assert_close(enrollment["mastery_pct"], 90.00, "mastery percent")
        assert_close(enrollment["projected_credits"], 0.00, "projected credits")

        response = api.award_credit(
            world["seat_time_enrollment"]["id"],
            f.award_credit_payload(fx.plan_version(api, world["plan"]["id"])),
            REGISTRAR_HEADERS,
        )
        body = validate_error(response, ApiErrorId.SEAT_TIME_INSUFFICIENT.value, 409)
        assert body["error_id"] != ApiErrorId.MASTERY_NOT_MET.value

    def test_neither_refusal_posts_a_row_or_spends_the_plan_version(self, api):
        """Both enrollments stay SUBMITTED_FOR_AWARD, the student has no transcript
        row, and the plan's version is exactly the one both attempts supplied.

        PRD: "The supplied `expected_graduation_plan_version` must match the
        student's plan `version` per §2.6."

        Design: Corner/errors/award_credit_mastery_and_seat_time_gates_rejected
        """
        world = _both_policies_submitted(api)
        plan_version = fx.plan_version(api, world["plan"]["id"])

        for enrollment_id in (
            world["competency_enrollment"]["id"],
            world["seat_time_enrollment"]["id"],
        ):
            api.award_credit(
                enrollment_id,
                f.award_credit_payload(plan_version),
                REGISTRAR_HEADERS,
            )
            assert (
                fx.read_enrollment(api, enrollment_id)["progress_state"]
                == ProgressState.SUBMITTED_FOR_AWARD.value
            )

        awards, _meta = validate_paginated(
            api.list_credit_awards(
                REGISTRAR_HEADERS, {"student_id": world["student"]["id"]}
            )
        )
        assert awards == []

        plan = fx.read_plan(api, world["plan"]["id"])
        assert_close(plan["credits_earned"], 0.00, "plan credits earned")
        assert plan["version"] == plan_version


def _completed_exam_world(api):
    """Two centres: A holds the station, the placement and provider A; B holds
    provider B. The placement's BIO1 exam has already been completed at 80.00."""
    home_school = fx.open_home_school(api)
    center_a = fx.open_center(api, name="Cedar AEC")
    center_b = fx.open_center(api, name="Birch AEC")
    station = fx.register_station(api, center_a["id"], label="RM-1")
    provider_a = fx.assign_provider(
        api,
        center_a["id"],
        role_type=ProviderRoleType.COUNSELOR.value,
        full_name="Ana Prieto",
        max_concurrent_students=2,
    )
    provider_b = fx.assign_provider(
        api,
        center_b["id"],
        role_type=ProviderRoleType.COUNSELOR.value,
        full_name="Bo Riis",
        max_concurrent_students=2,
    )
    course = fx.publish_course(api, **BIO1)
    student = fx.register_student(
        api, home_school["id"], state_student_id="S-5101", grade_level=11, cohort_year=2027
    )
    referral = fx.screened_referral(
        api, student["id"], center_a["id"], home_school["id"], **DEFICIENT
    )
    fx.offer_seat(api, referral["id"], center_a["id"])
    placement = fx.accept_seat(
        api,
        referral["id"],
        home_school["id"],
        credit_policy=CreditPolicy.COMPETENCY.value,
        start_date="2026-08-01",
    )
    enrollment = fx.enroll_new_credit(api, placement["id"], course["id"])
    session = fx.book_proctor_session(
        api,
        enrollment["id"],
        station["id"],
        center_a["id"],
        scheduled_start="2026-08-05T09:00:00.000Z",
        scheduled_end="2026-08-05T10:00:00.000Z",
    )
    fx.complete_proctor_session(
        api, session["id"], center_a["id"], 80.00, integrity_incident=False
    )
    return {
        "center_a": center_a,
        "center_b": center_b,
        "provider_a": provider_a,
        "provider_b": provider_b,
        "placement": placement,
        "enrollment": enrollment,
        "session": session,
        "coordinator": make_placement_coordinator_headers(center_a["id"]),
    }


def _support_body(world, provider_id):
    return f.support_session_payload(
        provider_id,
        world["placement"]["id"],
        start_at="2026-08-06T13:00:00.000Z",
        end_at="2026-08-06T14:00:00.000Z",
        service_code=ServiceCode.ACADEMIC_COUNSELING.value,
    )


class TestAProctorSessionLocksOnceItHasEnded:
    """COMPLETED is terminal, so the no-show branch is no longer reachable."""

    def test_a_completed_session_refuses_the_no_show_branch(self, api):
        """The no-show returns ERR_SESSION_STATE_INVALID and the session keeps its
        completed result with no note written.

        PRD: "A session ends one of two ways, and only from `SCHEDULED` — attempting
        either move on a session that has already ended is refused with
        `ERR_SESSION_STATE_INVALID`."

        Design: Corner/errors/session_lifecycle_and_provider_center_errors_rejected
        """
        world = _completed_exam_world(api)

        response = api.no_show_proctor_session(
            world["session"]["id"],
            f.no_show_payload(no_show_note="student did not appear"),
            world["coordinator"],
        )
        validate_error(response, ApiErrorId.SESSION_STATE_INVALID.value, 409)

        session = validate_success(
            api.get_proctor_session(world["session"]["id"], world["coordinator"])
        )
        assert session["status"] == ProctorSessionStatus.COMPLETED.value
        assert_close(session["score_percent"], 80.00, "exam score")
        assert session["no_show_note"] is None
        assert fx.read_station(api, world["session"]["proctor_station_id"])[
            "scheduled_session_count"
        ] == 1


class TestASupportSessionIsRefusedOnItsProvidersCenterFirst:
    """The centre check answers before any interval arithmetic, and the same
    interval succeeds with the local provider."""

    def test_a_provider_from_another_center_cannot_serve_this_placement(self, api):
        """Provider B's booking returns ERR_PROVIDER_CENTER_MISMATCH and the identical
        interval is then accepted for provider A.

        PRD: "A provider whose `center_id` differs from the center of the session's
        placement is refused with `ERR_PROVIDER_CENTER_MISMATCH`."

        Design: Corner/errors/session_lifecycle_and_provider_center_errors_rejected
        """
        world = _completed_exam_world(api)

        refused = api.create_support_session(
            _support_body(world, world["provider_b"]["id"]), world["coordinator"]
        )
        body = validate_error(refused, ApiErrorId.PROVIDER_CENTER_MISMATCH.value, 409)
        assert body["error_id"] != ApiErrorId.INVALID_INTERVAL.value
        assert body["error_id"] != ApiErrorId.PROVIDER_CAPACITY_EXCEEDED.value

        accepted = validate_success(
            api.create_support_session(
                _support_body(world, world["provider_a"]["id"]), world["coordinator"]
            ),
            201,
        )
        assert accepted["status"] == SupportSessionStatus.SCHEDULED.value
        assert accepted["support_provider_id"] == world["provider_a"]["id"]
        assert fx.read_provider(api, world["provider_b"]["id"])[
            "completed_session_count"
        ] == 0

    def test_a_delivered_support_session_refuses_a_second_completion(self, api):
        """The first completion records 45 minutes, the second returns
        ERR_SUPPORT_SESSION_STATE_INVALID, and the delivered minutes stay 45.

        PRD: "Completing a session that is not `SCHEDULED` is refused with
        `ERR_SUPPORT_SESSION_STATE_INVALID`."

        Design: Corner/errors/session_lifecycle_and_provider_center_errors_rejected
        """
        world = _completed_exam_world(api)
        session = validate_success(
            api.create_support_session(
                _support_body(world, world["provider_a"]["id"]), world["coordinator"]
            ),
            201,
        )
        provider_headers = make_support_provider_staff_headers(
            world["provider_a"]["id"]
        )

        completed = validate_success(
            api.complete_support_session(
                session["id"],
                f.complete_support_session_payload(45),
                provider_headers,
            )
        )
        assert completed["status"] == SupportSessionStatus.COMPLETED.value
        assert completed["minutes_delivered"] == 45

        response = api.complete_support_session(
            session["id"], f.complete_support_session_payload(30), provider_headers
        )
        validate_error(response, ApiErrorId.SUPPORT_SESSION_STATE_INVALID.value, 409)

        held = validate_success(
            api.get_support_session(session["id"], world["coordinator"])
        )
        assert held["minutes_delivered"] == 45
        assert fx.read_placement(api, world["placement"]["id"])[
            "support_sessions_completed"
        ] == 1
