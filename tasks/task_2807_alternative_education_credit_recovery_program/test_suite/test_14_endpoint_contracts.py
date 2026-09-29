"""Four endpoint contracts read literally: the partial staffing revision, the
delivery action, the recovery cross-reference and the projection exposed on a
plain enrollment read."""

from test_helpers import (
    CreditPolicy,
    EnrollmentType,
    IntakePosture,
    IntegrityState,
    PacingFlag,
    Pathway,
    PlanPosture,
    PriorOutcome,
    ProgressState,
    ProviderRoleType,
    ReplacementStatus,
    ServiceCode,
    SubjectArea,
    SupportSessionStatus,
    DISTRICT_ADMIN_HEADERS,
    REGISTRAR_HEADERS,
    assert_close,
    assert_seat_picture,
    assert_version_advanced,
    factories as f,
    fixtures as fx,
    make_support_provider_staff_headers,
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
    "proctoring_required": False,
    "ncaa_approved": False,
    "min_passing_percent": 60.00,
}

WIDE_CENTER = {
    "name": "Cedar AEC",
    "seat_capacity": 20,
    "certified_teacher_fte": 4.00,
    "support_staff_fte": 2.00,
    "max_students_per_teacher": 12,
}


class TestTheStaffingRevisionTouchesOnlyTheKeysItIsSent:
    """Each of the three staffing inputs is independently optional."""

    def test_revising_both_fte_figures_leaves_the_load_cap_alone(self, api):
        """Certified FTE 6.00 and support FTE 3.00 land while
        max_students_per_teacher stays 12, lifting staffing headroom to 72.

        PRD: "A `DistrictAdmin` may revise any of `certified_teacher_fte`,
        `support_staff_fte` and `max_students_per_teacher` — each independently
        optional in the revision, so a caller may send one, two or all three — under
        the stale-version guard of §2.6."

        Design: Corner/endpoints/staffing_patch_updates_only_supplied_fields
        """
        center = fx.open_center(api, **WIDE_CENTER)
        assert center["staffing_headroom"] == 48

        revised = validate_success(
            api.revise_staffing(
                center["id"],
                {
                    "certified_teacher_fte": 6.00,
                    "support_staff_fte": 3.00,
                    "expected_center_version": center["version"],
                },
                DISTRICT_ADMIN_HEADERS,
            )
        )
        assert_close(revised["certified_teacher_fte"], 6.00, "certified teacher fte")
        assert_close(revised["support_staff_fte"], 3.00, "support staff fte")
        assert revised["max_students_per_teacher"] == 12
        assert revised["staffing_headroom"] == 72
        assert_close(revised["student_teacher_ratio"], 0.00, "student teacher ratio")
        assert_version_advanced(center, revised)
        assert revised["restricted_seat_margin"] == 2
        assert_seat_picture(revised, 0, 0, 20, IntakePosture.OPEN.value)

    def test_revising_the_load_cap_alone_leaves_both_fte_figures_alone(self, api):
        """A body carrying only max_students_per_teacher moves headroom to 24 and
        holds the certified and support FTE at their opening values.

        PRD: "`staffing_headroom` is the certified teacher FTE multiplied by the
        contractual students-per-teacher cap, rounded down to a whole number, minus
        the active student count."

        Design: Corner/endpoints/staffing_patch_updates_only_supplied_fields
        """
        center = fx.open_center(api, **WIDE_CENTER)

        revised = validate_success(
            api.revise_staffing(
                center["id"],
                {
                    "max_students_per_teacher": 6,
                    "expected_center_version": center["version"],
                },
                DISTRICT_ADMIN_HEADERS,
            )
        )
        assert revised["max_students_per_teacher"] == 6
        assert_close(revised["certified_teacher_fte"], 4.00, "certified teacher fte")
        assert_close(revised["support_staff_fte"], 2.00, "support staff fte")
        assert revised["staffing_headroom"] == 24
        assert revised["intake_posture"] == IntakePosture.OPEN.value
        assert_version_advanced(center, revised)


class TestCompletingASupportSessionIsTheOnlyRecordOfDelivery:
    """The completion action stores the delivered minutes and raises the
    placement's completed-session count."""

    def test_delivery_moves_the_session_and_counts_on_the_placement(self, api):
        """The session reads COMPLETED with 55 minutes and its note, the placement
        counts one completed session, and readiness still reads 0.0000 because the
        base score never reaches a bonus tier.

        PRD: "Completion increases the delivering provider's
        `completed_session_count` by 1, increases the receiving placement's
        `support_sessions_completed` by 1 — that figure being the count of the
        placement's support sessions in `COMPLETED` status — and, through that
        count, can raise the placement's `engagement_bonus` and therefore its
        `readiness_score`, as §3.9 details."

        Design: Corner/endpoints/complete_support_session_action_records_delivery
        """
        world = fx.place_student(
            api,
            credit_policy=CreditPolicy.SEAT_TIME.value,
            student_overrides={"grade_level": 11, "cohort_year": 2027},
            referral_overrides={
                "pathway": Pathway.RE_ENGAGEMENT.value,
                "deficiency_credits": 2.00,
                "behavior_incident_count": 0,
                "days_disengaged": 45,
            },
        )
        provider = fx.assign_provider(
            api,
            world["center"]["id"],
            role_type=ProviderRoleType.COUNSELOR.value,
            full_name="Ana Prieto",
            max_concurrent_students=2,
        )
        session = fx.schedule_support_session(
            api,
            provider["id"],
            world["placement"]["id"],
            world["center"]["id"],
            start_at="2026-08-04T13:00:00.000Z",
            end_at="2026-08-04T14:00:00.000Z",
            service_code=ServiceCode.RE_ENGAGEMENT_CHECKIN.value,
        )
        assert session["status"] == SupportSessionStatus.SCHEDULED.value
        assert fx.read_placement(api, world["placement"]["id"])[
            "support_sessions_completed"
        ] == 0

        completed = validate_success(
            api.complete_support_session(
                session["id"],
                f.complete_support_session_payload(
                    55, completion_note="re-engagement check-in delivered"
                ),
                make_support_provider_staff_headers(provider["id"]),
            )
        )
        assert completed["status"] == SupportSessionStatus.COMPLETED.value
        assert completed["minutes_delivered"] == 55
        assert completed["completion_note"] == "re-engagement check-in delivered"

        placement = fx.read_placement(api, world["placement"]["id"])
        assert placement["support_sessions_completed"] == 1
        assert placement["attendance_rate"] is None
        assert_close(placement["readiness_base_score"], 0.0000, "readiness base score")
        assert_close(placement["engagement_bonus"], 0.0000, "engagement bonus")
        assert_close(placement["readiness_score"], 0.0000, "readiness score")
        assert fx.read_provider(api, provider["id"])["completed_session_count"] == 1


class TestTheRecoveryEnrollmentCarriesItsBackingTranscriptRow:
    """The citation is stored, listable and replaces nothing on its own."""

    def test_the_created_enrollment_is_reachable_through_the_prior_record_filter(
        self, api
    ):
        """The enrollment records prior_course_record_id, the filtered listing returns
        exactly that row, and the cited record stays NOT_REPLACED.

        PRD: "A cited record whose `student_id` is not the placement's student, or
        whose `course_id` is not the course being enrolled, is refused with
        `ERR_PRIOR_RECORD_MISMATCH`."

        Design: Corner/endpoints/credit_recovery_enrollment_links_failed_prior_record
        """
        world = fx.place_student(
            api,
            credit_policy=CreditPolicy.SEAT_TIME.value,
            student_overrides={"grade_level": 11, "cohort_year": 2027},
            referral_overrides={
                "deficiency_credits": 6.00,
                "behavior_incident_count": 1,
                "days_disengaged": 6,
            },
        )
        course = fx.publish_course(api, **ALG1)
        record = fx.post_prior_record(
            api,
            world["student"]["id"],
            course["id"],
            original_percent=42.00,
            credits_attempted=1.00,
            outcome=PriorOutcome.FAILED.value,
        )
        before_version = fx.placement_version(api, world["placement"]["id"])

        enrollment = fx.enroll_recovery(
            api, world["placement"]["id"], course["id"], record["id"], before_version
        )
        assert enrollment["enrollment_type"] == EnrollmentType.CREDIT_RECOVERY.value
        assert enrollment["prior_course_record_id"] == record["id"]
        assert enrollment["progress_state"] == ProgressState.IN_PROGRESS.value
        assert enrollment["integrity_state"] == IntegrityState.CLEAR.value

        rows, meta = validate_paginated(
            api.list_course_enrollments(
                REGISTRAR_HEADERS, {"prior_course_record_id": record["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [enrollment["id"]]

        assert (
            fx.read_prior_record(api, record["id"])["replacement_status"]
            == ReplacementStatus.NOT_REPLACED.value
        )
        assert fx.placement_version(api, world["placement"]["id"]) == before_version + 1


class TestAnEnrollmentReadAlreadyPublishesTheAwardArithmetic:
    """Nothing has been submitted, yet the seat-time projection is visible."""

    def test_forty_five_of_sixty_hours_projects_three_quarters_of_a_credit(self, api):
        """The enrollment reports projected_credits 0.75 with a null mastery and an
        unrated pace, and the plan mirrors the projection as work in progress.

        PRD: "The same computation, run against whatever progress data exists at the
        moment, is what an enrollment continuously exposes as `projected_credits` —
        what the award *would* post right now."

        Design: Corner/endpoints/enrollment_read_exposes_projected_seat_time_credits
        """
        world = fx.new_credit_world(
            api,
            credit_policy=CreditPolicy.SEAT_TIME.value,
            course_overrides=dict(ALG1),
            plan_overrides={"required_credits_total": 24.00},
            student_overrides={"grade_level": 11, "cohort_year": 2027},
            referral_overrides={
                "deficiency_credits": 6.00,
                "behavior_incident_count": 1,
                "days_disengaged": 6,
            },
        )
        fx.report_progress(api, world["enrollment"]["id"], seat_hours_delta=45.00)

        enrollment = validate_success(
            api.get_course_enrollment(world["enrollment"]["id"], REGISTRAR_HEADERS)
        )
        assert_close(enrollment["seat_hours_logged"], 45.00, "seat hours logged")
        assert enrollment["modules_passed"] == 0
        assert_close(enrollment["projected_credits"], 0.75, "projected credits")
        assert enrollment["mastery_pct"] is None
        assert enrollment["pace_index"] is None
        assert enrollment["pacing_flag"] == PacingFlag.NOT_YET_RATED.value

        plan = validate_success(
            api.get_graduation_plan(world["plan"]["id"], REGISTRAR_HEADERS)
        )
        assert_close(plan["credits_in_progress"], 0.75, "plan credits in progress")
        assert_close(plan["credits_earned"], 0.00, "plan credits earned")
        assert_close(plan["credits_remaining"], 24.00, "plan credits remaining")
        assert_close(plan["expected_credits_by_grade"], 18.00, "expected credits")
        assert plan["posture"] == PlanPosture.OFF_TRACK.value
