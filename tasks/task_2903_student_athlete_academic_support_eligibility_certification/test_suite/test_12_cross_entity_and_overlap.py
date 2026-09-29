"""Cross-entity state gates and shared-resource temporal rules."""

from test_helpers import assert_close, created, error, ok, page
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_APR_TERM_CLOSED,
    ERR_EVENT_NOT_TRAVEL_APPROVED,
    ERR_INVALID_STATE_TRANSITION,
    ERR_STUDENT_SESSION_OVERLAP,
    ERR_TUTOR_BUFFER_VIOLATION,
)
from test_helpers.constants import (
    APPEAL_COMMITTEE_REVIEW,
    ELIGIBILITY_INELIGIBLE,
)
from test_helpers.test_users import (
    ADVISOR,
    COMMITTEE,
    INSTRUCTOR_SOC_1,
    OPERATIONS,
    REGISTRAR,
    SPECIALIST,
    tutor_headers,
)


def _scheduled_event_and_one_meeting(api):
    """An enrolled student and a still-SCHEDULED trip over one 50-minute class."""
    return fx.travel_world(
        api,
        meeting_days=[1, 3, 5],
        meeting_duration_minutes=50,
        departure_at="2026-09-14T08:00:00Z",
        return_at="2026-09-15T00:00:00Z",
        sport_code="WBB",
        approve=False,
    )


def test_missed_class_request_is_refused_while_the_event_is_scheduled(api):
    """PRD 3.8: "Approving travel takes the event `SCHEDULED →
    TRAVEL_APPROVED` and requires the event's term to still be open; only from
    `TRAVEL_APPROVED` may missed-class requests be filed."

    Design: Difficulty/cross_entity_state_dependency/missed_class_request_requires_travel_approved_event
    """
    ctx = _scheduled_event_and_one_meeting(api)
    assert ctx.event["status"] == "SCHEDULED"

    error(
        api.create_missed_class_request(
            f.missed_class_request(ctx.event_id, ctx.enrollment_id), ADVISOR
        ),
        ERR_EVENT_NOT_TRAVEL_APPROVED,
    )

    student = fx.read_student(api, ctx.student_id)
    assert_close(student["missed_class_units_charged"], 0.00)
    rows, meta = page(
        api.list_missed_class_requests(
            ADVISOR, {"enrollment_id": ctx.enrollment_id}
        )
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_the_same_request_is_accepted_once_travel_is_approved(api):
    """PRD 3.8: "Third, each counted occurrence yields its own unit figure:
    take the length in whole minutes of the intersection between the meeting
    interval and the travel window, divide by 60 minutes — one missed-class unit
    is one hour of overlap — and round half up to two decimal places."

    Design: Difficulty/cross_entity_state_dependency/missed_class_request_requires_travel_approved_event
    """
    ctx = _scheduled_event_and_one_meeting(api)
    error(
        api.create_missed_class_request(
            f.missed_class_request(ctx.event_id, ctx.enrollment_id), ADVISOR
        ),
        ERR_EVENT_NOT_TRAVEL_APPROVED,
    )

    approved = fx.event_action(api, ctx.event_id, "APPROVE_TRAVEL")
    request = created(
        api.create_missed_class_request(
            f.missed_class_request(ctx.event_id, ctx.enrollment_id), ADVISOR
        )
    )

    assert approved["status"] == "TRAVEL_APPROVED"
    assert request["status"] == "DRAFT"
    assert request["missed_meeting_count"] == 1
    # 50 minutes of overlap is 50 / 60 = 0.8333 -> 0.83 units.
    assert_close(request["missed_units_gross"], 0.83)
    assert_close(request["missed_units"], 0.83)
    student = fx.read_student(api, ctx.student_id)
    assert_close(student["missed_class_units_charged"], 0.83)
    assert_close(student["missed_class_units_remaining"], 8.17)
    event = ok(api.get_event(ctx.event_id, OPERATIONS))
    assert_close(event["charged_units_total"], 0.83)


def _appeal_in_review_under_a_closed_term(api):
    """A live appeal whose term two hops away has been APR-closed."""
    ctx = fx.enrolled_student(
        api,
        term_count=1,
        clock="2026-09-01T00:00:00Z",
        credit_hours=12.0,
        declare_major_in_term=1,
        min_progress_gpa=2.0,
        student_overrides={"full_name": "Sam Sixteen", "sport_code": "TRACK"},
    )
    fx.record_grade(api, ctx.enrollment_id, "D")
    certification = fx.make_denied_certification(api, ctx.student_id, ctx.term_id)
    appeal = fx.make_appeal_in_review(
        api, certification["id"], requested_credit_relief=6.0
    )
    ctx.certification_id = certification["id"]
    ctx.appeal_id = appeal["id"]
    ctx.closed_term = fx.close_term(api, ctx.term_id, "2026-12-18T00:00:00Z")
    return ctx


def test_appeal_denial_is_refused_once_the_term_is_apr_closed(api):
    """PRD 3.9: "From that instant every certification and appeal bound to the
    term is frozen and every later write against it is refused with
    `ERR_APR_TERM_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/appeal_decision_blocked_when_term_apr_closed
    """
    ctx = _appeal_in_review_under_a_closed_term(api)
    assert ctx.closed_term["apr_status"] == "CLOSED"

    response = api.appeal_status(ctx.appeal_id, f.action("DENY"), COMMITTEE)

    body = error(response, ERR_APR_TERM_CLOSED)
    # COMMITTEE_REVIEW is a declared from-state for DENY, so the transition
    # itself is legal and only the frozen term stands in the way.
    assert body["error_id"] != ERR_INVALID_STATE_TRANSITION


def test_the_frozen_term_leaves_appeal_and_certification_untouched(api):
    """PRD 2.9: "The moment the term closes, every one of those writes is
    refused with `ERR_APR_TERM_CLOSED`, and the certifications and appeals bound
    to that term are frozen with their snapshot fields exactly as the close left
    them."

    Design: Difficulty/cross_entity_state_dependency/appeal_decision_blocked_when_term_apr_closed
    """
    ctx = _appeal_in_review_under_a_closed_term(api)

    error(
        api.appeal_status(ctx.appeal_id, f.action("DENY"), COMMITTEE),
        ERR_APR_TERM_CLOSED,
    )

    appeal = ok(api.get_appeal(ctx.appeal_id, COMMITTEE))
    assert appeal["status"] == APPEAL_COMMITTEE_REVIEW
    assert appeal["round_number"] == 1
    assert appeal["decided_by_user_id"] is None
    assert appeal["decided_at"] is None
    certification = fx.read_certification(api, ctx.certification_id)
    assert certification["status"] == "DENIED"
    assert_close(certification["credit_relief_applied"], 0.00)
    student = fx.read_student(api, ctx.student_id)
    assert student["eligibility_state"] == ELIGIBILITY_INELIGIBLE
    term = ok(api.get_term(ctx.term_id, REGISTRAR))
    assert term["apr_status"] == "CLOSED"
    assert term["apr_points_possible"] == 2
    assert term["apr_points_earned"] == 1
    assert term["squad_apr"] == 500


def _student_with_a_two_hour_study_hall(api):
    """One STUDY_HALL session from 14:00 to 16:00 on 2026-09-14."""
    fx.set_clock(api, "2026-09-14T00:00:00Z")
    term = fx.make_term(api, index=1, catalog_year=2026)
    student = fx.make_student(
        api, full_name="Sam Seventeen", sport_code="BASE", entry_term_index=1,
        entry_catalog_year=2026,
    )
    first = fx.make_session(
        api, student["id"], "2026-09-14T14:00:00Z", "2026-09-14T16:00:00Z"
    )
    return fx.Ctx(
        term_id=term["id"], student_id=student["id"], first_session=first,
        first_session_id=first["id"],
    )


def test_session_starting_exactly_when_another_ends_is_accepted(api):
    """PRD 3.7: "No two sessions of the same student may overlap: the windows
    are half-open, so a session beginning exactly when another ends is accepted
    while a single minute of true overlap is rejected with
    `ERR_STUDENT_SESSION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/student_session_half_open_adjacency_allowed_overlap_rejected
    """
    world = _student_with_a_two_hour_study_hall(api)

    adjacent = created(
        api.create_session(
            f.session(
                world.student_id,
                "2026-09-14T16:00:00Z",
                "2026-09-14T17:00:00Z",
            ),
            SPECIALIST,
        )
    )

    assert_close(adjacent["hours_credited"], 1.00)
    assert adjacent["term_index_of_record"] == 1
    assert_close(world.first_session["hours_credited"], 2.00)
    # SupportSession is the one entity that carries no optimistic-lock column.
    assert "version" not in adjacent


def test_one_minute_of_true_session_overlap_is_rejected(api):
    """PRD 3.7: "On logging, `hours_credited` is the length of the interval in
    minutes divided by 60, rounded half up to two decimal places, and
    `term_index_of_record` is the ordinal of the unique term whose `[start_date,
    end_date)` window contains `start_at`; a session whose start falls in no term
    at all is rejected."

    Design: Difficulty/resource_temporal_overlap/student_session_half_open_adjacency_allowed_overlap_rejected
    """
    world = _student_with_a_two_hour_study_hall(api)
    fx.make_session(
        api, world.student_id, "2026-09-14T16:00:00Z", "2026-09-14T17:00:00Z"
    )

    response = api.create_session(
        f.session(
            world.student_id, "2026-09-14T16:59:00Z", "2026-09-14T18:00:00Z"
        ),
        SPECIALIST,
    )

    error(response, ERR_STUDENT_SESSION_OVERLAP)
    rows, meta = page(
        api.list_sessions(SPECIALIST, {"student_athlete_id": world.student_id})
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2


def _one_tutor_two_students_one_logged_session(api):
    """A tutor holding two ACTIVE assignments, with a 14:00-15:00 session logged."""
    fx.set_clock(api, "2026-09-14T00:00:00Z")
    term = fx.make_term(api, index=1, catalog_year=2026)
    course = fx.make_course(
        api, subject_code="SOCI", course_number="150",
        title="Introduction to Sociology", credit_hours=3.0,
        instructor_user_id=INSTRUCTOR_SOC_1,
    )
    first_student = fx.make_student(
        api, full_name="Sam Eighteen A", sport_code="SOC", entry_term_index=1,
        entry_catalog_year=2026,
    )
    second_student = fx.make_student(
        api, full_name="Sam Eighteen B", sport_code="SOC", entry_term_index=1,
        entry_catalog_year=2026,
    )
    first_enrollment = fx.make_enrollment(
        api, first_student["id"], course["id"], term["id"]
    )
    second_enrollment = fx.make_enrollment(
        api, second_student["id"], course["id"], term["id"]
    )
    tutor = fx.make_trained_tutor(
        api, term["id"], ["SOCI"], full_name="Tomas Buffer",
        max_weekly_hours=20.0,
    )
    first_assignment = fx.make_active_assignment(
        api, tutor["id"], first_enrollment["id"], 2.0
    )
    second_assignment = fx.make_active_assignment(
        api, tutor["id"], second_enrollment["id"], 2.0
    )
    ctx = fx.Ctx(
        term_id=term["id"],
        tutor_id=tutor["id"],
        first_student_id=first_student["id"],
        second_student_id=second_student["id"],
        first_assignment_id=first_assignment["id"],
        second_assignment_id=second_assignment["id"],
    )
    ctx.tutor_headers = tutor_headers(tutor["id"])
    created(
        api.create_session(
            f.tutor_session(
                ctx.first_student_id,
                ctx.first_assignment_id,
                "2026-09-14T14:00:00Z",
                "2026-09-14T15:00:00Z",
            ),
            ctx.tutor_headers,
        )
    )
    return ctx


def test_exactly_twenty_minutes_of_clear_tutor_time_is_accepted(api):
    """PRD 3.7: "Two sessions whose assignments belong to the same tutor must be
    separated by at least 20 minutes of clear time between the earlier session's
    `end_at` and the later session's `start_at`; a gap of exactly 20 minutes is
    accepted and a gap of 10 minutes is rejected with
    `ERR_TUTOR_BUFFER_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/tutor_twenty_minute_buffer_rejects_ten_minute_gap
    """
    ctx = _one_tutor_two_students_one_logged_session(api)

    second = created(
        api.create_session(
            f.tutor_session(
                ctx.second_student_id,
                ctx.second_assignment_id,
                "2026-09-14T15:20:00Z",
                "2026-09-14T16:20:00Z",
            ),
            ctx.tutor_headers,
        )
    )

    assert_close(second["hours_credited"], 1.00)
    assert second["term_index_of_record"] == 1
    assert second["logged_by_user_id"] == ctx.tutor_id


def test_ten_minute_tutor_gap_is_rejected_without_touching_either_assignment(api):
    """PRD 3.7: "When the session names an assignment, that assignment's
    `logged_hours` increases by `hours_credited`; `logged_hours` is the running
    sum of credited hours across the assignment's sessions, held at two decimal
    places."

    Design: Difficulty/resource_temporal_overlap/tutor_twenty_minute_buffer_rejects_ten_minute_gap
    """
    ctx = _one_tutor_two_students_one_logged_session(api)
    created(
        api.create_session(
            f.tutor_session(
                ctx.second_student_id,
                ctx.second_assignment_id,
                "2026-09-14T15:20:00Z",
                "2026-09-14T16:20:00Z",
            ),
            ctx.tutor_headers,
        )
    )

    response = api.create_session(
        f.tutor_session(
            ctx.first_student_id,
            ctx.first_assignment_id,
            "2026-09-14T16:30:00Z",
            "2026-09-14T17:00:00Z",
        ),
        ctx.tutor_headers,
    )

    body = error(response, ERR_TUTOR_BUFFER_VIOLATION)
    # The first student's own calendar holds [14:00, 15:00) only, so nothing of
    # hers overlaps [16:30, 17:00) - the clash is purely the shared tutor's.
    assert body["error_id"] != ERR_STUDENT_SESSION_OVERLAP
    first = ok(api.get_assignment(ctx.first_assignment_id, SPECIALIST))
    second = ok(api.get_assignment(ctx.second_assignment_id, SPECIALIST))
    assert_close(first["logged_hours"], 1.00)
    assert_close(second["logged_hours"], 1.00)
    tutor = fx.read_tutor(api, ctx.tutor_id)
    assert_close(tutor["assigned_weekly_hours"], 4.00)
    assert tutor["status"] == "TRAINED"
