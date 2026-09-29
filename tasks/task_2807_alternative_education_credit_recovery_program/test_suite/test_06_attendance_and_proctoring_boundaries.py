"""Two inclusive boundaries: the attendance rate that sits exactly on 0.9000,
and the completed-proctored-exam count sitting exactly on zero."""

from test_helpers import (
    ApiErrorId,
    CreditPolicy,
    PacingFlag,
    PlacementStatus,
    PlanPosture,
    ProctorSessionStatus,
    ProgressState,
    assert_close,
    fixtures as fx,
    make_placement_coordinator_headers,
    validate_error,
    validate_success,
)

BIO1 = {
    "code": "BIO1",
    "title": "Biology I",
    "subject_area": "SCIENCE",
    "credit_value": 1.00,
    "total_modules": 10,
    "required_seat_hours": 60.00,
    "pacing_days": 40,
    "proctored_exam_weight": 0.40,
    "ncaa_approved": True,
    "min_passing_percent": 60.00,
}


class TestAttendanceRateSitsInclusivelyOnNinetyPercent:
    """44 of 50 days refuses the re-entry request; 45 of 50 admits it."""

    def test_forty_four_of_fifty_days_refuses_the_request_on_attendance_alone(
        self, api
    ):
        """The rate reads 0.8800 with readiness already past its own threshold, so
        the 409 names ERR_ATTENDANCE_BELOW_MINIMUM and nothing else.

        PRD: "Re-entry requires an `attendance_rate` of at least 0.9000; an
        attendance rate that is null because no enrolled days have been logged
        fails this check."

        Design: Difficulty/boundary_precision_check/attendance_rate_exactly_ninety_allows_re_entry
        """
        world = fx.re_entry_ready_world(api, days_present=44, days_enrolled=50)
        coordinator = make_placement_coordinator_headers(world["center"]["id"])

        placement = fx.read_placement(api, world["placement"]["id"])
        assert_close(placement["attendance_rate"], 0.8800, "attendance rate")
        assert_close(placement["readiness_base_score"], 0.7400, "readiness base score")
        assert_close(placement["engagement_bonus"], 0.0300, "engagement bonus")
        assert_close(placement["readiness_score"], 0.7700, "readiness score")
        assert placement["re_entry_eligible"] is False

        response = api.request_re_entry(
            world["placement"]["id"],
            {"target_re_entry_date": "2026-08-24"},
            coordinator,
        )
        body = validate_error(
            response, ApiErrorId.ATTENDANCE_BELOW_MINIMUM.value, 409
        )
        assert body["error_id"] != ApiErrorId.READINESS_BELOW_THRESHOLD.value

    def test_one_more_present_day_lands_exactly_on_the_threshold_and_admits_it(
        self, api
    ):
        """One extra present day makes the rate exactly 0.9000, lifts readiness to
        0.7800 and the same request now moves the placement to RE_ENTRY_PENDING.

        PRD: "On success the placement records `target_re_entry_date` and
        captures the acting `X-User-ID` into `re_entry_requested_by_user_id`, and
        its `version` increments by 1."

        Design: Difficulty/boundary_precision_check/attendance_rate_exactly_ninety_allows_re_entry
        """
        world = fx.re_entry_ready_world(api, days_present=44, days_enrolled=50)
        center_id = world["center"]["id"]
        coordinator = make_placement_coordinator_headers(center_id)
        api.request_re_entry(
            world["placement"]["id"],
            {"target_re_entry_date": "2026-08-24"},
            coordinator,
        )

        bumped = fx.log_attendance(api, world["placement"]["id"], 1, 0)
        assert bumped["days_present"] == 45
        assert bumped["days_enrolled"] == 50
        assert_close(bumped["attendance_rate"], 0.9000, "attendance rate")
        assert_close(bumped["readiness_base_score"], 0.7500, "readiness base score")
        assert_close(bumped["engagement_bonus"], 0.0300, "engagement bonus")
        assert_close(bumped["readiness_score"], 0.7800, "readiness score")
        assert bumped["re_entry_eligible"] is True

        pending = validate_success(
            api.request_re_entry(
                world["placement"]["id"],
                {"target_re_entry_date": "2026-08-24"},
                coordinator,
            )
        )
        assert pending["status"] == PlacementStatus.RE_ENTRY_PENDING.value
        assert pending["target_re_entry_date"] == "2026-08-24"
        assert pending["re_entry_requested_by_user_id"] == center_id

    def test_the_pacing_component_is_the_capped_one_not_the_raw_pace_index(self, api):
        """The enrollment's pace index reads 4.000 ON_PACE, yet readiness only
        ever credits the capped 1.0000, and the plan gate never fires.

        PRD: "Otherwise each rated enrollment contributes its `pace_index` held
        at a maximum of 1.0000, and an enrollment whose `pace_index` is still
        null because no instructional day has elapsed contributes a full 1.0000
        rather than zero — a brand-new enrollment is given the benefit of the
        doubt."

        Design: Difficulty/boundary_precision_check/attendance_rate_exactly_ninety_allows_re_entry
        """
        world = fx.re_entry_ready_world(api, days_present=44, days_enrolled=50)

        enrollment = fx.read_enrollment(api, world["enrollment"]["id"])
        assert_close(enrollment["pace_index"], 4.000, "pace index")
        assert enrollment["pacing_flag"] == PacingFlag.ON_PACE.value

        placement = fx.read_placement(api, world["placement"]["id"])
        assert_close(placement["pacing_component"], 1.0000, "pacing component")
        assert_close(placement["credit_component"], 0.0000, "credit component")

        plan = fx.read_plan(api, world["plan"]["id"])
        assert_close(plan["expected_credits_by_grade"], 1.00, "expected credits")
        assert_close(plan["credits_earned"], 1.00, "plan credits earned")
        assert plan["posture"] == PlanPosture.ON_TRACK.value


def _booked_but_unscored_world(api):
    """A proctored ONLINE enrollment with one still-SCHEDULED exam session."""
    world = fx.proctored_world(
        api,
        credit_policy=CreditPolicy.COMPETENCY.value,
        course_overrides=dict(BIO1),
        plan_overrides={"required_credits_total": 24.00},
        referral_overrides={
            "deficiency_credits": 6.00,
            "behavior_incident_count": 1,
            "days_disengaged": 6,
        },
    )
    fx.report_progress(
        api,
        world["enrollment"]["id"],
        modules_passed_delta=9,
        seat_hours_delta=40.00,
        module_avg_percent=84.00,
    )
    world["session"] = fx.book_proctor_session(
        api,
        world["enrollment"]["id"],
        world["station"]["id"],
        world["center"]["id"],
        scheduled_start="2026-08-05T09:00:00.000Z",
        scheduled_end="2026-08-05T10:00:00.000Z",
    )
    return world


class TestZeroCompletedProctoredExamsBlocksSubmission:
    """A booked-but-unscored exam is still zero completed exams."""

    def test_a_scheduled_session_does_not_count_as_a_completed_exam(self, api):
        """Submission is refused with ERR_PROCTORED_EXAM_MISSING and the
        enrollment keeps its IN_PROGRESS state with no submitter recorded.

        PRD: "a course whose `proctoring_required` is true cannot be submitted
        for award while the enrollment has zero `COMPLETED` proctored exam
        sessions (`ERR_PROCTORED_EXAM_MISSING`)"

        Design: Difficulty/boundary_precision_check/submit_for_award_with_zero_completed_proctor_sessions
        """
        world = _booked_but_unscored_world(api)

        before = fx.read_enrollment(api, world["enrollment"]["id"])
        assert before["proctored_exam_percent"] is None
        assert_close(before["mastery_pct"], 84.00, "mastery before any exam score")

        response = api.submit_for_award(
            world["enrollment"]["id"],
            {"final_percent": 84.00},
            fx.ALT_ED_TEACHER_HEADERS,
        )
        validate_error(response, ApiErrorId.PROCTORED_EXAM_MISSING.value, 409)

        held = fx.read_enrollment(api, world["enrollment"]["id"])
        assert held["progress_state"] == ProgressState.IN_PROGRESS.value
        assert held["submitted_by_user_id"] is None

    def test_completing_the_exam_blends_mastery_away_from_the_module_average(
        self, api
    ):
        """A score of 78.00 against a module average of 84.00 at weight 0.40 makes
        mastery 81.60, and the competency projection stays at the full credit.

        PRD: "Completion makes this session's score visible to the enrollment as
        `proctored_exam_percent` — defined as the `score_percent` of the latest
        `COMPLETED` session for that enrollment when ordered by `created_at`
        ascending, so the most recently created completed session wins, and null
        while no session for the enrollment has completed — and therefore
        re-derives the enrollment's `mastery_pct` and `projected_credits`."

        Design: Difficulty/boundary_precision_check/submit_for_award_with_zero_completed_proctor_sessions
        """
        world = _booked_but_unscored_world(api)

        completed = fx.complete_proctor_session(
            api,
            world["session"]["id"],
            world["center"]["id"],
            78.00,
            integrity_incident=False,
        )
        assert completed["status"] == ProctorSessionStatus.COMPLETED.value
        assert_close(completed["score_percent"], 78.00, "exam score")
        assert completed["integrity_incident"] is False

        enrollment = fx.read_enrollment(api, world["enrollment"]["id"])
        assert_close(enrollment["proctored_exam_percent"], 78.00, "exam percent")
        assert_close(enrollment["mastery_pct"], 81.60, "blended mastery")
        assert_close(enrollment["projected_credits"], 1.00, "projected credits")

    def test_the_scored_exam_unblocks_submission_and_still_holds_the_station(
        self, api
    ):
        """The same submission now succeeds, and the station keeps counting the
        session it has already run.

        PRD: "On success the system records `final_percent` and captures the
        acting `X-User-ID` into `submitted_by_user_id`, which is the comparand the
        segregation-of-duties rule of §2.9 will use at award time, and increments
        the enrollment's `version` by 1."

        Design: Difficulty/boundary_precision_check/submit_for_award_with_zero_completed_proctor_sessions
        """
        world = _booked_but_unscored_world(api)
        fx.complete_proctor_session(
            api,
            world["session"]["id"],
            world["center"]["id"],
            78.00,
            integrity_incident=False,
        )

        submitted = validate_success(
            api.submit_for_award(
                world["enrollment"]["id"],
                {"final_percent": 84.00},
                fx.ALT_ED_TEACHER_HEADERS,
            )
        )
        assert submitted["progress_state"] == ProgressState.SUBMITTED_FOR_AWARD.value
        assert_close(submitted["final_percent"], 84.00, "final percent")
        assert submitted["submitted_by_user_id"] == "teach-01"

        station = fx.read_station(api, world["station"]["id"])
        assert station["scheduled_session_count"] == 1
