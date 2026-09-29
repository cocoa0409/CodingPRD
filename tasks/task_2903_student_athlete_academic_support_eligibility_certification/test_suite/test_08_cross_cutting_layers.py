"""Cross-cutting layers: optimistic concurrency, cumulative thresholds and the
term-close checkpoint.

Each test here drives one mechanism that reaches across several entities at
once: the `expected_student_athlete_version` gate of PRD 2.8, the tutor penalty
threshold of PRD 3.9 with its assignment cascade, and the academic-progress-rate
close that publishes `squad_apr` and freezes every write bound to the term.
"""

from test_helpers import created, error, ok, page
from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_errors import (
    ERR_APR_TERM_CLOSED,
    ERR_STALE_STUDENT_VERSION,
)
from test_helpers.assertions import (
    assert_apr_ledger_conserved,
    assert_benchmark,
    assert_close,
    assert_null,
    assert_status,
    assert_whole_number,
)
from test_helpers.constants import (
    APR_STATUS_CLOSED,
    ASSIGN_ACTIVE,
    ASSIGN_TERMINATED,
    BENCHMARK_PASS,
    CERT_CERTIFIED,
    CERT_DRAFT,
    CERT_TYPE_INITIAL,
    ENROLLMENT_ENROLLED,
    INCIDENT_ACTION_OPEN,
    REASON_TUTOR_SUSPENDED,
    SEVERITY_LEVEL_I,
    SEVERITY_LEVEL_II,
    SUPPORT_NORMAL,
    TUTOR_SUSPENDED,
    TUTOR_TRAINED,
)
from test_helpers.test_users import (
    CERT_OFFICER,
    COMPLIANCE,
    INSTRUCTOR_MATH_1,
    REGISTRAR,
    SPECIALIST,
)

CLOCK = "2026-09-01T00:00:00Z"


def test_certification_create_refuses_a_stale_student_version_then_accepts_the_fresh_one(
    api,
):
    """PRD 2.8: "If that value does not equal the student's current `version`,
    the create is rejected with `ERR_STALE_STUDENT_VERSION` and HTTP 412, and
    nothing is written. This is a stale-version comparison and nothing else: it
    does not depend on how closely two requests fall together in time, only on
    whether the student row has advanced since the client read it."

    Design: Corner/cross-cutting complexity layers/certification_create_with_stale_student_version_returns_412
    """
    fixtures.set_clock(api, CLOCK)
    term = fixtures.make_term(api, index=1)
    course = fixtures.make_course(
        api,
        subject_code="MATH",
        course_number="101",
        title="College Algebra",
        credit_hours=3.0,
        instructor_user_id=INSTRUCTOR_MATH_1,
    )
    student = fixtures.make_student(
        api, full_name="Sam Seventythree", sport_code="MBB"
    )

    stale_version = fixtures.student_version(api, student["id"])
    enrollment = fixtures.make_enrollment(
        api, student["id"], course["id"], term["id"]
    )
    # Recording the grade recomputes the student's aggregates, which advances
    # the row the client is holding a picture of.
    fixtures.record_grade(api, enrollment["id"], "B")

    stale_payload = f.certification(
        student["id"], term["id"], stale_version, CERT_TYPE_INITIAL
    )
    error(
        api.create_certification(stale_payload, CERT_OFFICER),
        ERR_STALE_STUDENT_VERSION,
        412,
    )

    fresh_version = fixtures.student_version(api, student["id"])
    assert fresh_version == stale_version + 1

    draft = created(
        api.create_certification(
            f.certification(
                student["id"], term["id"], fresh_version, CERT_TYPE_INITIAL
            ),
            CERT_OFFICER,
        )
    )
    assert_status(draft, CERT_DRAFT)
    assert draft["student_athlete_id"] == student["id"]
    # The null-program path compares cumulative_gpa 3.00 against the
    # provisional floor of 1.80.
    assert_benchmark(draft, BENCHMARK_PASS)
    assert_close(draft["progress_pct"], 0.0000)
    assert_close(draft["required_progress_pct"], 0.0000)

    # Nothing was written by the refused attempt.
    rows, meta = page(
        api.list_certifications(CERT_OFFICER, {"student_athlete_id": student["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == draft["id"]


def test_tutor_holds_at_two_penalty_points_and_suspends_with_cascade_at_three(api):
    """PRD 3.9: "Substantiating it moves the incident `UNDER_INVESTIGATION →
    SUBSTANTIATED` and requires a `severity` of `LEVEL_I`, `LEVEL_II` or
    `LEVEL_III`, which converts directly into points: one point for `LEVEL_I`,
    two for `LEVEL_II`, three for `LEVEL_III`, written to
    `penalty_points_assessed`."

    PRD 3.9: "The suspension threshold reads that decayed figure: at three or
    more points a `TRAINED` or `EXPIRED` tutor is suspended, while at exactly
    two points the tutor keeps its current status."

    PRD 3.9: "Where the tutor did become suspended, each of that tutor's
    assignments in `PROPOSED` or `ACTIVE` moves to `TERMINATED` with
    `terminated_reason` of `TUTOR_SUSPENDED` in `created_at` ascending order,
    and the tutor's `assigned_weekly_hours` drops by each formerly active
    assignment's `weekly_hours`."

    Design: Corner/cross-cutting complexity layers/tutor_stays_trained_at_two_penalty_points_and_suspends_at_three
    """
    fixtures.set_clock(api, CLOCK)
    term = fixtures.make_term(api, index=1)
    course = fixtures.make_course(
        api,
        subject_code="MATH",
        course_number="101",
        title="College Algebra",
        credit_hours=3.0,
        instructor_user_id=INSTRUCTOR_MATH_1,
    )
    student = fixtures.make_student(
        api, full_name="Sam Seventyfive", sport_code="MBB"
    )
    enrollment = fixtures.make_enrollment(
        api, student["id"], course["id"], term["id"]
    )
    tutor = fixtures.make_trained_tutor(
        api, term["id"], subject_codes=["MATH"], full_name="Tina Seventyfive"
    )
    assignment = fixtures.make_active_assignment(
        api, tutor["id"], enrollment["id"], 2.0
    )

    first = fixtures.make_incident(
        api,
        student["id"],
        tutor_id=tutor["id"],
        incident_type="EXCESSIVE_TUTOR_HOURS",
        narrative="The tutor logged more hours than the assignment allows.",
    )
    second = fixtures.make_incident(
        api,
        student["id"],
        tutor_id=tutor["id"],
        incident_type="IMPERMISSIBLE_WORK_COMPLETION",
        narrative="The tutor drafted part of an assignment for the student.",
    )
    fixtures.incident_action(api, first["id"], INCIDENT_ACTION_OPEN)
    fixtures.incident_action(api, second["id"], INCIDENT_ACTION_OPEN)

    # LEVEL_II leaves the tutor exactly one point below the threshold.
    substantiated = ok(
        api.incident_status(
            first["id"], f.substantiate(SEVERITY_LEVEL_II), COMPLIANCE
        )
    )
    assert substantiated["penalty_points_assessed"] == 2
    assert_whole_number(substantiated["penalty_points_assessed"])

    held = fixtures.read_tutor(api, tutor["id"])
    assert held["penalty_points"] == 2
    assert_status(held, TUTOR_TRAINED)
    assert_close(held["assigned_weekly_hours"], 2.00)
    assert_status(
        ok(api.get_assignment(assignment["id"], SPECIALIST)), ASSIGN_ACTIVE
    )

    # One further LEVEL_I point reaches three and suspends the tutor.
    ok(api.incident_status(second["id"], f.substantiate(SEVERITY_LEVEL_I), COMPLIANCE))

    suspended = fixtures.read_tutor(api, tutor["id"])
    assert suspended["penalty_points"] == 3
    assert_status(suspended, TUTOR_SUSPENDED)
    assert_close(suspended["assigned_weekly_hours"], 0.00)

    terminated = ok(api.get_assignment(assignment["id"], SPECIALIST))
    assert_status(terminated, ASSIGN_TERMINATED)
    assert terminated["terminated_reason"] == REASON_TUTOR_SUSPENDED

    # Points are added to the student's history as well, and never rolled back.
    assert_close(
        fixtures.read_student(api, student["id"])["substantiated_penalty_points"], 3.00
    )


def _apr_close_world(api):
    """A single certified cohort student in the one and only reporting term.

    The student declares a program, completes a 12.00-credit CORE course graded
    ``B`` and holds a second, still ``ENROLLED`` course; an ``INITIAL``
    certification is requested, submitted and certified, and the clock is then
    moved past the term's ``end_date`` so the close is admissible.
    """
    ctx = fixtures.enrolled_student(
        api,
        term_count=1,
        clock=CLOCK,
        subject_code="KINE",
        credit_hours=12.0,
        declare_major_in_term=1,
        student_overrides={"full_name": "Sam Seventysix", "sport_code": "WBB"},
    )
    fixtures.record_grade(api, ctx.enrollment_id, "B")

    second_course = fixtures.make_course(
        api,
        subject_code="MATH",
        course_number="101",
        title="College Algebra",
        credit_hours=3.0,
        instructor_user_id=INSTRUCTOR_MATH_1,
    )
    ctx.open_enrollment = fixtures.make_enrollment(
        api, ctx.student_id, second_course["id"], ctx.term_id
    )
    ctx.certification = fixtures.make_certified_certification(
        api, ctx.student_id, ctx.term_id
    )
    assert_status(ctx.certification, CERT_CERTIFIED)
    fixtures.set_clock(api, "2026-12-19T00:00:00Z")
    return ctx


def test_apr_close_awards_both_points_and_publishes_squad_apr(api):
    """PRD 3.9: "Each cohort student contributes exactly 2 possible points, one
    for eligibility and one for retention. The eligibility point is earned when
    the student holds a certification for this term whose status is `CERTIFIED`
    or `RESTORED`, and is forfeited otherwise."

    PRD 3.9: "Where no next term row exists at all, the retention point is
    awarded by default."

    PRD 3.9: "The term's own `apr_points_possible` and `apr_points_earned` are
    the cohort sums, and `squad_apr` is the term's earned points divided by its
    possible points, multiplied by 1000 and rounded half up to a whole number;
    where the term's `apr_points_possible` is 0, `squad_apr` is null rather
    than 0."

    Design: Corner/cross-cutting complexity layers/apr_close_checkpoint_publishes_squad_apr_and_freezes_the_term
    """
    ctx = _apr_close_world(api)

    closed = ok(api.apr_close(ctx.term_id, COMPLIANCE))
    assert_status(closed, APR_STATUS_CLOSED, "apr_status")
    assert closed["apr_points_possible"] == 2
    assert_close(closed["apr_points_earned"], 2.0)
    assert closed["squad_apr"] == 1000
    assert_whole_number(closed["squad_apr"])

    student = fixtures.read_student(api, ctx.student_id)
    assert student["apr_points_possible"] == 2
    assert_close(student["apr_points_earned"], 2.0)
    assert_close(student["apr_points_forfeited"], 0.00)
    assert_apr_ledger_conserved(student)
    # Two earned points forfeit nothing, so the support dimension stays put.
    assert student["support_status"] == SUPPORT_NORMAL

    assert_status(
        fixtures.read_certification(api, ctx.certification["id"]), CERT_CERTIFIED
    )


def test_apr_close_freezes_the_term_against_further_enrollment_outcomes(api):
    """PRD 3.2: "All four actions are refused with `ERR_APR_TERM_CLOSED` once
    the enrollment's term has closed, and all four are refused with
    `ERR_INVALID_STATE_TRANSITION` from `COMPLETED`, `DROPPED` or `WITHDRAWN`,
    which are terminal."

    Design: Corner/cross-cutting complexity layers/apr_close_checkpoint_publishes_squad_apr_and_freezes_the_term
    """
    ctx = _apr_close_world(api)
    ok(api.apr_close(ctx.term_id, COMPLIANCE))

    error(
        api.record_outcome(
            ctx.open_enrollment["id"], f.record_grade("C"), REGISTRAR
        ),
        ERR_APR_TERM_CLOSED,
        409,
    )

    unchanged = ok(api.get_enrollment(ctx.open_enrollment["id"], REGISTRAR))
    assert_status(unchanged, ENROLLMENT_ENROLLED)
    assert_null(unchanged, "grade")
