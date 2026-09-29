"""Validation-ladder precedence pairs and exact-boundary probes."""

from test_helpers import assert_close, created, error, ok, page
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_EVENT_NOT_TRAVEL_APPROVED,
    ERR_MISSED_CLASS_ALLOWANCE_EXCEEDED,
    ERR_TUTOR_NOT_TRAINED,
    ERR_TUTOR_SUBJECT_MISMATCH,
)
from test_helpers.constants import (
    AUDIT_AT_ENTRY,
    BENCHMARK_PASS,
    CERT_TYPE_CONTINUING,
)
from test_helpers.test_users import (
    ADVISOR,
    CERT_OFFICER,
    OPERATIONS,
    SPECIALIST,
)


def _exhausted_budget_and_a_scheduled_event(api):
    """A student with no allowance left and a second event still SCHEDULED."""
    ctx = fx.travel_world(
        api,
        meeting_days=[1, 3, 5],
        meeting_duration_minutes=180,
        departure_at="2026-09-14T08:00:00Z",
        return_at="2026-09-19T00:00:00Z",
        sport_code="WBB",
    )
    ctx.first_request = fx.make_request(api, ctx.event_id, ctx.enrollment_id)
    # A Monday-only trip worth 3.00 units, but the event is never approved.
    ctx.scheduled_event = fx.make_event(
        api, ctx.term_id, "2026-10-05T08:00:00Z", "2026-10-06T00:00:00Z",
        sport_code="WBB",
    )
    ctx.scheduled_event_id = ctx.scheduled_event["id"]
    return ctx


def test_event_state_error_outranks_the_allowance_error(api):
    """PRD 2.7: "`ERR_EVENT_NOT_TRAVEL_APPROVED` (409) when a new missed-class
    request names a competition event that is not travel-approved; because this
    band outranks every business rule below it, a request that targets a merely
    scheduled event *and* would exceed the student's missed-class allowance
    reports the event error, not the allowance error."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_missed_class_request_create
    """
    ctx = _exhausted_budget_and_a_scheduled_event(api)
    student = fx.read_student(api, ctx.student_id)
    assert_close(student["missed_class_units_remaining"], 0.00)

    response = api.create_missed_class_request(
        f.missed_class_request(ctx.scheduled_event_id, ctx.enrollment_id),
        ADVISOR,
    )

    body = error(response, ERR_EVENT_NOT_TRAVEL_APPROVED)
    assert body["error_id"] != ERR_MISSED_CLASS_ALLOWANCE_EXCEEDED


def test_rejected_request_against_a_scheduled_event_writes_nothing(api):
    """PRD 2.7: "Requests are validated in strictly ascending priority bands.
    The **first** violated rule decides the response, and no later rule is
    evaluated — so when a single request breaks several rules at once, the
    reported error is always the one from the lowest-numbered band."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_missed_class_request_create
    """
    ctx = _exhausted_budget_and_a_scheduled_event(api)

    error(
        api.create_missed_class_request(
            f.missed_class_request(ctx.scheduled_event_id, ctx.enrollment_id),
            ADVISOR,
        ),
        ERR_EVENT_NOT_TRAVEL_APPROVED,
    )

    assert_close(ctx.first_request["missed_units"], 9.00)
    student = fx.read_student(api, ctx.student_id)
    assert_close(student["missed_class_units_charged"], 9.00)
    event = ok(api.get_event(ctx.scheduled_event_id, OPERATIONS))
    assert event["status"] == "SCHEDULED"
    assert_close(event["charged_units_total"], 0.00)
    rows, meta = page(
        api.list_missed_class_requests(
            ADVISOR, {"competition_event_id": ctx.scheduled_event_id}
        )
    )
    assert meta["total_count"] == 0
    assert rows == []


def _untrained_tutor_with_wrong_subject(api):
    """An UNTRAINED tutor cleared for MATH facing a SOCI enrollment."""
    ctx = fx.enrolled_student(
        api,
        term_count=1,
        clock="2026-09-01T00:00:00Z",
        subject_code="SOCI",
        credit_hours=3.0,
        student_overrides={"full_name": "Sam Twelve"},
    )
    tutor = fx.make_tutor(
        api, full_name="Tess Tutor", subject_codes=["MATH"]
    )
    ctx.tutor = tutor
    ctx.tutor_id = tutor["id"]
    return ctx


def test_untrained_tutor_error_outranks_the_subject_mismatch(api):
    """PRD 2.7: "`ERR_TUTOR_NOT_TRAINED` (422) when an assignment is created
    for, or activated or reinstated on, an untrained tutor — reported even when
    every referential and capacity condition holds."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_tutor_assignment_create
    """
    ctx = _untrained_tutor_with_wrong_subject(api)
    assert ctx.tutor["status"] == "UNTRAINED"
    assert ctx.tutor["subject_codes"] == ["MATH"]

    response = api.create_assignment(
        f.assignment(ctx.tutor_id, ctx.enrollment_id, 2.0), SPECIALIST
    )

    body = error(response, ERR_TUTOR_NOT_TRAINED)
    assert body["error_id"] != ERR_TUTOR_SUBJECT_MISMATCH


def test_subject_mismatch_is_never_reached_for_an_untrained_tutor(api):
    """PRD 2.7: "`ERR_TUTOR_SUBJECT_MISMATCH` (422) on assignment creation —
    deliberately ordered *after* the training checks, so an untrained tutor who
    also lacks the subject clearance reports the training error."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_tutor_assignment_create
    """
    ctx = _untrained_tutor_with_wrong_subject(api)

    error(
        api.create_assignment(
            f.assignment(ctx.tutor_id, ctx.enrollment_id, 2.0), SPECIALIST
        ),
        ERR_TUTOR_NOT_TRAINED,
    )

    tutor = fx.read_tutor(api, ctx.tutor_id)
    assert tutor["status"] == "UNTRAINED"
    assert_close(tutor["assigned_weekly_hours"], 0.00)
    rows, meta = page(
        api.list_assignments(SPECIALIST, {"tutor_id": ctx.tutor_id})
    )
    assert meta["total_count"] == 0
    assert rows == []


def _student_exactly_at_the_progress_benchmark(api):
    """Two completed full-time terms and exactly 20% of the degree earned.

    KINE-101 is CORE and carries 12.00 of the program's 60.00 required credits,
    so `progress_pct` is 0.2000; HIST-210 is `NOT_APPLICABLE` and adds nothing
    but grade points.  The certification is filed against the third term, so
    both completed full-time terms sit strictly below its ordinal and
    `required_progress_pct` is 0.10 * 2 = 0.2000 as well.
    """
    ctx = fx.enrolled_student(
        api,
        term_count=3,
        clock="2026-09-01T00:00:00Z",
        credit_hours=12.0,
        declare_major_in_term=1,
        total_required_credits=60.0,
        student_overrides={"full_name": "Sam Thirteen", "sport_code": "TRACK"},
    )
    fx.record_grade(api, ctx.enrollment_id, "B")
    fx.set_clock(api, "2027-02-01T00:00:00Z")
    fx.add_graded_course(
        api,
        ctx,
        ctx.terms[1],
        grade="C",
        credit_hours=12.0,
        subject_code="HIST",
        applicability="NOT_APPLICABLE",
    )
    ctx.certification_term_id = ctx.terms[2]["id"]
    return ctx


def test_progress_exactly_at_the_benchmark_is_a_pass(api):
    """PRD 3.3: "The progress test passes when `progress_pct` is at least
    `required_progress_pct`; the comparison is inclusive, so a `progress_pct`
    exactly equal to `required_progress_pct` is a pass."

    Design: Difficulty/boundary_precision_check/ptd_progress_exactly_at_benchmark_passes
    """
    ctx = _student_exactly_at_the_progress_benchmark(api)

    certification = created(
        api.create_certification(
            f.certification(
                ctx.student_id,
                ctx.certification_term_id,
                fx.student_version(api, ctx.student_id),
                certification_type=CERT_TYPE_CONTINUING,
            ),
            CERT_OFFICER,
        )
    )

    assert certification["status"] == "DRAFT"
    assert_close(certification["progress_pct"], 0.2000, tolerance=0.00005)
    assert_close(
        certification["required_progress_pct"], 0.2000, tolerance=0.00005
    )
    assert certification["benchmark_result"] == BENCHMARK_PASS
    assert certification["failure_reasons"] == []


def test_certification_snapshot_freezes_the_boundary_inputs(api):
    """PRD 3.3: "and from the second completed full-time term onward
    `required_progress_pct` is ten percent of the degree per completed full-time
    term, expressed as 0.10 multiplied by that count, never exceeding 1.0000,
    and rounded half up to four decimal places."

    Design: Difficulty/boundary_precision_check/ptd_progress_exactly_at_benchmark_passes
    """
    ctx = _student_exactly_at_the_progress_benchmark(api)

    certification = created(
        api.create_certification(
            f.certification(
                ctx.student_id,
                ctx.certification_term_id,
                fx.student_version(api, ctx.student_id),
                certification_type=CERT_TYPE_CONTINUING,
            ),
            CERT_OFFICER,
        )
    )

    assert certification["audit_variant"] == AUDIT_AT_ENTRY
    # HIST-210 is NOT_APPLICABLE, so only the 12.00 CORE credits count.
    assert_close(certification["degree_applicable_credits_counted"], 12.00)
    assert certification["completed_full_time_terms_counted"] == 2
    assert_close(certification["gpa_at_certification"], 2.50)
    student = fx.read_student(api, ctx.student_id)
    assert_close(student["progress_pct"], 0.2000, tolerance=0.00005)


def _reporting_term_with_only_a_dropped_enrollment(api):
    """A reporting term whose single student dropped its only enrollment."""
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    term = fx.make_term(api, index=1, catalog_year=2026, is_apr_reporting_term=True)
    course = fx.make_course(
        api, subject_code="SOCI", course_number="150",
        title="Introduction to Sociology", credit_hours=12.0,
    )
    student = fx.make_student(
        api, full_name="Sam Fourteen", sport_code="BASE", entry_term_index=1,
        entry_catalog_year=2026,
    )
    enrollment = fx.make_enrollment(
        api, student["id"], course["id"], term["id"]
    )
    fx.record_outcome(api, enrollment["id"], "DROP")
    return fx.Ctx(
        term_id=term["id"], student_id=student["id"],
        enrollment_id=enrollment["id"],
    )


def test_apr_close_with_an_empty_cohort_publishes_a_null_squad_apr(api):
    """PRD 3.9: "The term's own `apr_points_possible` and `apr_points_earned`
    are the cohort sums, and `squad_apr` is the term's earned points divided by
    its possible points, multiplied by 1000 and rounded half up to a whole
    number; where the term's `apr_points_possible` is 0, `squad_apr` is null
    rather than 0."

    Design: Difficulty/boundary_precision_check/apr_close_with_zero_eligible_students_yields_null_squad_apr
    """
    world = _reporting_term_with_only_a_dropped_enrollment(api)

    closed = fx.close_term(api, world.term_id, "2026-12-18T00:00:00Z")

    assert closed["apr_status"] == "CLOSED"
    assert closed["apr_points_possible"] == 0
    assert closed["apr_points_earned"] == 0
    assert closed["squad_apr"] is None


def test_dropped_only_student_is_absent_from_the_apr_cohort(api):
    """PRD 3.9: "A student with no enrollment in the term, or whose only
    enrollments in it were dropped or withdrawn, is excluded from both the
    numerator and the denominator — not counted as a forfeit, simply absent."

    Design: Difficulty/boundary_precision_check/apr_close_with_zero_eligible_students_yields_null_squad_apr
    """
    world = _reporting_term_with_only_a_dropped_enrollment(api)

    fx.close_term(api, world.term_id, "2026-12-18T00:00:00Z")

    student = fx.read_student(api, world.student_id)
    assert student["apr_points_possible"] == 0
    assert student["apr_points_earned"] == 0
    assert student["apr_points_forfeited"] == 0
