"""Endpoint behaviour: catalogue round trips, conditional actions, computed reads.

Every test builds its own world through public endpoints because the harness
restarts the server, and therefore empties the database, before each test.
"""

from test_helpers import (
    assert_benchmark,
    assert_close,
    assert_instant_equals,
    assert_null,
    assert_page_meta,
    assert_risk,
    assert_status,
    assert_student_dimensions,
    assert_version_advanced,
    assert_version_is,
    created,
    error,
    ids_of,
    ok,
    page,
)
from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_errors import ERR_APR_TERM_NOT_ENDED
from test_helpers.constants import (
    APR_STATUS_OPEN,
    ASSIGN_PROPOSED,
    AUDIT_AT_ENTRY,
    BENCHMARK_PASS,
    ELIGIBILITY_NOT_CERTIFIED,
    ENROLLMENT_COMPLETED,
    RISK_TERM_SNAPSHOT,
    RISK_TIER_1,
    SUPPORT_NORMAL,
)
from test_helpers.test_users import (
    ADVISOR,
    CERT_OFFICER,
    COMPLIANCE,
    INSTRUCTOR_MATH_1,
    INSTRUCTOR_SOC_1,
    REGISTRAR,
    SPECIALIST,
)


def test_course_with_full_meeting_pattern_reads_back_and_lists_once(api):
    """PRD 3.1: "A course is registered with a `subject_code` prefix such as
    `KINE`, a `course_number` such as `190` — the pair is unique across all
    courses — a `title`, `credit_hours` of record greater than 0 and at most 12,
    and an `instructor_user_id`, which is the opaque operator identifier of the
    instructor of record rather than a foreign key to any stored row."
    PRD 3.1: "`meeting_days` holds ISO weekday numbers, where 1 is Monday
    through 7 is Sunday, and defaults to an empty list, meaning the course never
    meets and can never generate a missed meeting"
    PRD 2.4: "`version`, an integer that begins at 1 when the row is created and
    increases by exactly 1 on every mutation of that row"

    Design: Corner/endpoints/course_create_read_and_list_round_trip
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")

    course_row = created(
        api.create_course(
            f.course(
                subject_code="SOCI",
                course_number="150",
                title="Introduction to Sociology",
                credit_hours=3.0,
                instructor_user_id=INSTRUCTOR_SOC_1,
                is_remedial=False,
                meeting_days=[1, 3, 5],
                meeting_start_minute_utc=600,
                meeting_duration_minutes=50,
            ),
            REGISTRAR,
        )
    )

    read = ok(api.get_course(course_row["id"], REGISTRAR))
    assert read["id"] == course_row["id"]
    assert_version_is(read, 1)
    assert read["subject_code"] == "SOCI"
    assert read["course_number"] == "150"
    assert_close(read["credit_hours"], 3.00)
    assert read["instructor_user_id"] == INSTRUCTOR_SOC_1
    assert read["meeting_days"] == [1, 3, 5]
    assert read["meeting_start_minute_utc"] == 600
    assert read["meeting_duration_minutes"] == 50
    assert read["is_remedial"] is False

    rows, meta = page(api.list_courses(REGISTRAR, {"subject_code": "SOCI"}))
    assert_page_meta(meta, limit=10, offset=0, total_count=1, has_more=False)
    assert ids_of(rows) == [course_row["id"]]


def test_apr_close_one_day_before_term_end_is_refused(api):
    """PRD 2.7: "`ERR_APR_TERM_NOT_ENDED` (409) when a term close is requested
    while the logical clock is still before the term's `end_date`."
    PRD 3.1: "A newly registered term is `OPEN`, with `apr_points_possible` and
    `apr_points_earned` both 0 and `squad_apr` null."

    Design: Corner/endpoints/apr_close_before_term_end_returns_409
    """
    fixtures.set_clock(api, "2026-12-17T00:00:00Z", COMPLIANCE)
    term = fixtures.make_term(api, index=1)
    assert_instant_equals(term["end_date"], "2026-12-18T00:00:00Z")

    error(api.apr_close(term["id"], COMPLIANCE), ERR_APR_TERM_NOT_ENDED, 409)

    after = ok(api.get_term(term["id"], COMPLIANCE))
    assert_status(after, APR_STATUS_OPEN, field="apr_status")
    assert after["apr_points_possible"] == 0
    assert after["apr_points_earned"] == 0
    assert_null(after, "squad_apr")
    assert_version_is(after, 1)


def test_major_declaration_after_clock_move_stamps_the_declaration_term(api):
    """PRD 2.4: "An administrative test-driving capability sets the clock to a
    supplied `current_utc` instant; it modifies no entity and re-runs no
    calculation, and it is available to every role."
    PRD 3.2: "A registrar or an academic advisor records it by supplying the
    `declared_program_id` being declared and the `term_id` of the term in which
    the declaration is filed; the system writes `major_declared_term_index` from
    that term's ordinal."
    PRD 3.2: "A successful declaration re-runs the credit audit, transfer-credit
    acceptance, the progress-benchmark evaluation, the risk score and the
    study-hall requirement, and advances the student's `version`."

    Design: Corner/endpoints/major_declaration_records_term_from_logical_clock
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    term = fixtures.make_term(api, index=1)
    program = fixtures.make_program(api, code="DP55", name="Sociology")
    student = fixtures.make_student(
        api, full_name="Sam Fiftyfive", sport_code="SOC", entry_term_index=1
    )

    moved = ok(api.set_clock("2026-10-05T12:00:00Z", REGISTRAR))
    assert_instant_equals(moved["current_utc"], "2026-10-05T12:00:00Z")

    declared = ok(
        api.declare_major(
            student["id"], f.major_declaration(program["id"], term["id"]), ADVISOR
        )
    )
    assert declared["declared_program_id"] == program["id"]
    assert declared["major_declared_term_index"] == 1
    assert_close(declared["degree_applicable_credits"], 0.00)
    assert_close(declared["progress_pct"], 0.0000, 0.0001)
    assert_student_dimensions(declared, eligibility_state=ELIGIBILITY_NOT_CERTIFIED)


def test_proposed_assignment_is_reachable_from_both_filters_and_holds_no_hours(api):
    """PRD 3.7: "It is created `PROPOSED` with `suspension_count` of 0,
    `logged_hours` of 0 and a null `terminated_reason`, and it reserves no
    capacity at all until it is activated."
    PRD 2.10: "For every tutor, `assigned_weekly_hours` equals the sum of
    `weekly_hours` over that tutor's assignments whose status is `ACTIVE` — no
    more and no less — after every assignment transition, every cascade and every
    tutor status change."

    Design: Corner/endpoints/tutor_assignment_links_tutor_and_enrollment
    """
    ctx = fixtures.enrolled_student(
        api,
        term_count=1,
        clock="2026-09-01T00:00:00Z",
        subject_code="MATH",
        credit_hours=3.0,
        course_overrides={
            "course_number": "101",
            "title": "College Algebra",
            "instructor_user_id": INSTRUCTOR_MATH_1,
        },
    )
    tutor = fixtures.make_trained_tutor(
        api, ctx.term_id, subject_codes=["MATH"], full_name="Tina Linkage"
    )

    assignment = created(
        api.create_assignment(
            f.assignment(tutor["id"], ctx.enrollment_id, 2.0), SPECIALIST
        )
    )
    assert_status(assignment, ASSIGN_PROPOSED)
    assert assignment["suspension_count"] == 0
    assert_close(assignment["logged_hours"], 0.00)
    assert_null(assignment, "terminated_reason")

    by_tutor, tutor_meta = page(
        api.list_assignments(SPECIALIST, {"tutor_id": tutor["id"]})
    )
    assert tutor_meta["total_count"] == 1
    assert by_tutor[0]["enrollment_id"] == ctx.enrollment_id

    by_enrollment, enrollment_meta = page(
        api.list_assignments(SPECIALIST, {"enrollment_id": ctx.enrollment_id})
    )
    assert enrollment_meta["total_count"] == 1
    assert by_enrollment[0]["tutor_id"] == tutor["id"]

    assert_close(fixtures.read_tutor(api, tutor["id"])["assigned_weekly_hours"], 0.00)


def test_eligibility_summary_projects_the_audit_with_default_variants(api):
    """PRD 3.6: "That summary capability recomputes the credit audit, the
    benchmark evaluation, the risk score and the study-hall requirement,
    optionally taking `audit_variant` to choose the catalog year and
    `risk_variant` to choose the grade basis"
    PRD 3.3: "when `audit_variant` is omitted the variant is `CATALOG_AT_ENTRY`
    when the student's `major_declared_term_index` is null or is at most
    `entry_term_index`, and `CATALOG_AT_CERTIFICATION` when the major was
    declared later than entry"
    PRD 3.6: "`TERM_SNAPSHOT` applies when `risk_variant` is omitted and the
    student's `completed_full_time_terms` is below two"
    PRD 3.4: "for a student with fewer than two such terms
    `required_progress_pct` is 0.0000 — the first two full-time terms are a grace
    period during which no credit progress is demanded"

    Design: Corner/endpoints/eligibility_summary_computed_read_matches_audit
    """
    ctx = fixtures.enrolled_student(
        api,
        term_count=1,
        clock="2026-09-01T00:00:00Z",
        credit_hours=12.0,
        declare_major_in_term=1,
    )
    fixtures.record_grade(api, ctx.enrollment_id, "B")

    response = api.eligibility_summary(ctx.student_id, CERT_OFFICER)
    assert response.json()["response_type"] == "object"
    summary = ok(response)

    assert summary["student_athlete_id"] == ctx.student_id
    assert summary["audit_variant"] == AUDIT_AT_ENTRY
    assert summary["risk_variant"] == RISK_TERM_SNAPSHOT
    assert_close(summary["degree_applicable_credits"], 12.00)
    assert_close(summary["progress_pct"], 0.2000, 0.0001)
    assert_close(summary["required_progress_pct"], 0.0000, 0.0001)
    assert_benchmark(summary, BENCHMARK_PASS, [])
    assert_close(summary["cumulative_gpa"], 3.00)
    assert summary["completed_full_time_terms"] == 1
    assert_close(summary["transfer_credits_accepted"], 0.00)
    assert_risk(summary, 0.00, RISK_TIER_1)
    assert_close(summary["required_study_hall_hours"], 0.0)
    assert_close(summary["missed_class_units_charged"], 0.00)
    assert_close(summary["missed_class_units_remaining"], 9.00)
    assert summary["apr_points_possible"] == 0
    assert summary["apr_points_earned"] == 0
    assert summary["apr_points_forfeited"] == 0


def test_recorded_grade_settles_every_aggregate_within_the_same_request(api):
    """PRD 2.11: "First, they are **immediate and in-request**: there is no
    deferred queue, and a response reflects the fully settled state of every
    entity the request touched."
    PRD 3.2: "the system writes `grade_points` from the fixed scale where `A` is
    4.00, `B` is 3.00, `C` is 2.00, `D` is 1.00 and `F` is 0.00, sets
    `earned_credit_hours` to the enrollment's `credit_hours` when `grade_points`
    is greater than 0.00 and to 0 otherwise (an `F` is attempted but never
    earned), sets `is_full_time_countable`, and stamps `outcome_recorded_at` from
    the logical clock."

    Design: Corner/consistency model/enrollment_outcome_reflects_recomputed_fields_without_any_delay
    """
    ctx = fixtures.enrolled_student(
        api,
        term_count=1,
        clock="2026-09-01T00:00:00Z",
        credit_hours=12.0,
        declare_major_in_term=1,
    )
    before = fixtures.read_student(api, ctx.student_id)

    graded = ok(api.record_outcome(ctx.enrollment_id, f.record_grade("B"), REGISTRAR))
    assert_status(graded, ENROLLMENT_COMPLETED)
    assert graded["grade"] == "B"
    assert_close(graded["grade_points"], 3.00)
    assert_close(graded["earned_credit_hours"], 12.00)
    assert_close(graded["degree_applicable_credits_counted"], 12.00)
    assert graded["is_full_time_countable"] is True
    assert_instant_equals(graded["outcome_recorded_at"], "2026-09-01T00:00:00Z")

    after = fixtures.read_student(api, ctx.student_id)
    assert_close(after["cumulative_gpa"], 3.00)
    assert after["completed_full_time_terms"] == 1
    assert_close(after["degree_applicable_credits"], 12.00)
    assert_close(after["progress_pct"], 0.2000, 0.0001)
    assert_version_advanced(before, after)
    assert_risk(after, 0.00, RISK_TIER_1)
    assert_close(after["required_study_hall_hours"], 0.0)
    assert_student_dimensions(after, support_status=SUPPORT_NORMAL)

    summary = ok(api.eligibility_summary(ctx.student_id, ADVISOR))
    assert_close(summary["progress_pct"], 0.2000, 0.0001)
    assert_close(summary["required_progress_pct"], 0.0000, 0.0001)
    assert_benchmark(summary, BENCHMARK_PASS, [])
