"""Derived-value arithmetic: the credit audit's ceilings and walk order, the
graded-outcome rollups, missed-class unit accounting and penalty points."""

import pytest

from test_helpers import factories, fixtures
from test_helpers.assertions import (
    assert_close,
    assert_missed_class_budget_conserved,
    assert_null,
    assert_risk,
    assert_status,
    assert_student_dimensions,
    assert_whole_number,
    created,
    ok,
)
from test_helpers.constants import (
    APPLICABILITY_CORE,
    APPLICABILITY_ELECTIVE,
    DEFAULT_MISSED_CLASS_UNITS_ALLOWANCE,
    ENROLLMENT_COMPLETED,
    EVENT_TYPE_REGULAR_SEASON,
    INCIDENT_ACTION_OPEN,
    INCIDENT_SUBSTANTIATED,
    MCR_DRAFT,
    RISK_TIER_1,
    RISK_TIER_3,
    SEVERITY_LEVEL_II,
    SUPPORT_MANDATED,
    SUPPORT_NORMAL,
    TUTOR_TRAINED,
)
from test_helpers.test_users import (
    ADVISOR,
    COMPLIANCE,
    INSTRUCTOR_ART_1,
    INSTRUCTOR_KINE_1,
    INSTRUCTOR_MUS_1,
    INSTRUCTOR_SOC_1,
    OPERATIONS,
    REGISTRAR,
)


def _kinesiology_world(api):
    """A declared student enrolled in a single 12.00-credit CORE course."""
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    term1 = fixtures.make_term(api, index=1)
    program = fixtures.make_program(
        api,
        code="DP43",
        name="Kinesiology",
        catalog_year=2026,
        total_required_credits=60.0,
    )
    course = fixtures.make_course(
        api,
        subject_code="KINE",
        course_number="200",
        title="Exercise Physiology",
        credit_hours=12.0,
        instructor_user_id=INSTRUCTOR_KINE_1,
    )
    fixtures.make_rule(
        api,
        program["id"],
        course["id"],
        effective_catalog_year=2026,
        applicability=APPLICABILITY_CORE,
    )
    student = fixtures.make_student(
        api,
        full_name="Sam Fortythree",
        sport_code="FB",
        entry_term_index=1,
        entry_catalog_year=2026,
    )
    fixtures.declare_major(api, student["id"], program["id"], term1["id"], ADVISOR)
    enrollment = fixtures.make_enrollment(
        api, student["id"], course["id"], term1["id"]
    )
    return {
        "term": term1,
        "program": program,
        "course": course,
        "student_id": student["id"],
        "enrollment_id": enrollment["id"],
    }


def test_grade_f_earns_no_credit_but_still_counts_as_attempted(api):
    """PRD 3.2: "the system writes `grade_points` from the fixed scale where `A`
    is 4.00, `B` is 3.00, `C` is 2.00, `D` is 1.00 and `F` is 0.00, sets
    `earned_credit_hours` to the enrollment's `credit_hours` when `grade_points`
    is greater than 0.00 and to 0 otherwise (an `F` is attempted but never
    earned), sets `is_full_time_countable`, and stamps `outcome_recorded_at`
    from the logical clock."

    PRD 3.3: "Enrollments in `ENROLLED`, `DROPPED`, `WITHDRAWN` or
    `INCOMPLETE`, and rows graded `F` with `grade_points` of 0.00, are excluded
    outright."

    PRD 3.2: "The comparison is inclusive, so a term with exactly 12 attempted
    credits against a minimum of 12 counts."

    Design: Corner/calculations/grade_f_excluded_from_earned_credits
    """
    world = _kinesiology_world(api)

    graded = ok(
        api.record_outcome(
            world["enrollment_id"], factories.record_grade("F"), REGISTRAR
        )
    )
    assert_status(graded, ENROLLMENT_COMPLETED)
    assert graded["grade"] == "F"
    assert_close(graded["grade_points"], 0.00)
    assert_close(graded["credit_hours"], 12.00)
    assert_close(graded["earned_credit_hours"], 0.00)
    assert_close(graded["degree_applicable_credits_counted"], 0.00)
    assert graded["is_full_time_countable"] is True
    assert graded["outcome_recorded_at"] is not None


def test_grade_f_rollup_lands_on_the_tier_3_boundary(api):
    """PRD 3.2: "over the student's enrollments that are `COMPLETED`, carry
    `credit_source` of `RESIDENT` and hold a grade among `A`, `B`, `C`, `D` and
    `F`, take the sum of each row's `grade_points` multiplied by its attempted
    `credit_hours`, divide by the sum of those same attempted credit hours, and
    round half up to two decimal places."

    PRD 3.6: "The grade component takes the shortfall of the variant-selected
    average below a risk floor of 2.30 grade points, treating any surplus as a
    shortfall of 0.00; that shortfall is divided by 2.30 and multiplied by
    100.00, capped at 100.00 — so an average of 2.30 or better scores 0.00 and
    an average of 0.00 scores the full 100.00."

    PRD 3.6: "Each lower bound is inclusive and each upper bound is exclusive,
    so a score of exactly 40.00 is `TIER_3` and never `TIER_2`."

    PRD 3.6: "First, the base weekly hours come from the tier: no hours at all
    for `TIER_1`, 4.0 for `TIER_2`, 8.0 for `TIER_3` and 12.0 for `TIER_4`."

    Design: Corner/calculations/grade_f_excluded_from_earned_credits
    """
    world = _kinesiology_world(api)

    fixtures.record_grade(api, world["enrollment_id"], "F")

    student = fixtures.read_student(api, world["student_id"])
    assert_close(student["cumulative_gpa"], 0.00)
    assert student["completed_full_time_terms"] == 1
    assert_close(student["degree_applicable_credits"], 0.00)
    assert student["progress_pct"] == pytest.approx(0.0000, abs=1e-4)
    assert_risk(student, 40.00, RISK_TIER_3)
    assert_close(student["required_study_hall_hours"], 8.0)
    assert_student_dimensions(student, support_status=SUPPORT_MANDATED)


def _two_elective_world(api):
    """Two 8.00-credit ELECTIVE courses against a 12.00 elective ceiling."""
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    term1 = fixtures.make_term(api, index=1)
    program = fixtures.make_program(
        api,
        code="DP41",
        name="Liberal Studies",
        catalog_year=2026,
        total_required_credits=60.0,
        max_elective_credits_countable=12.0,
    )
    art = fixtures.make_course(
        api,
        subject_code="ART",
        course_number="100",
        title="Drawing I",
        credit_hours=8.0,
        instructor_user_id=INSTRUCTOR_ART_1,
    )
    music = fixtures.make_course(
        api,
        subject_code="MUS",
        course_number="200",
        title="Music Theory",
        credit_hours=8.0,
        instructor_user_id=INSTRUCTOR_MUS_1,
    )
    for course in (art, music):
        rule = fixtures.make_rule(
            api,
            program["id"],
            course["id"],
            effective_catalog_year=2026,
            applicability=APPLICABILITY_ELECTIVE,
        )
        assert_null(rule, "max_countable_credits")
    student = fixtures.make_student(
        api,
        full_name="Sam Fortyone",
        sport_code="TRACK",
        entry_term_index=1,
        entry_catalog_year=2026,
    )
    fixtures.declare_major(api, student["id"], program["id"], term1["id"], ADVISOR)
    art_enrollment = fixtures.make_enrollment(
        api, student["id"], art["id"], term1["id"]
    )
    music_enrollment = fixtures.make_enrollment(
        api, student["id"], music["id"], term1["id"]
    )
    fixtures.record_grade(api, art_enrollment["id"], "B")
    return {
        "program": program,
        "student_id": student["id"],
        "art_enrollment_id": art_enrollment["id"],
        "music_enrollment_id": music_enrollment["id"],
    }


def test_elective_crossing_row_contributes_only_the_program_headroom(api):
    """PRD 3.3: "Walk the rows classified `ELECTIVE` in the order term ordinal
    ascending, then course `subject_code` ascending, then `course_number`
    ascending, then enrollment `created_at` ascending, adding each countable
    figure while the running elective total stays at or below the program's
    `max_elective_credits_countable`. The row that would carry the running total
    past the ceiling contributes only the headroom that remains, and every later
    elective row contributes zero."

    PRD 3.3: "Every enrollment records what it contributed the last time the
    audit ran for its student, in `degree_applicable_credits_counted`."

    Design: Corner/calculations/elective_credit_program_cap_applied_in_declared_order
    """
    world = _two_elective_world(api)
    assert_close(world["program"]["max_elective_credits_countable"], 12.00)

    graded = ok(
        api.record_outcome(
            world["music_enrollment_id"], factories.record_grade("B"), REGISTRAR
        )
    )
    assert_status(graded, ENROLLMENT_COMPLETED)
    assert_close(graded["grade_points"], 3.00)
    assert_close(graded["earned_credit_hours"], 8.00)
    assert_close(graded["degree_applicable_credits_counted"], 4.00)

    art_row = ok(api.get_enrollment(world["art_enrollment_id"], REGISTRAR))
    assert_close(art_row["earned_credit_hours"], 8.00)
    assert_close(art_row["degree_applicable_credits_counted"], 8.00)


def test_capped_elective_total_drives_the_progress_proportion(api):
    """PRD 3.3: "`degree_applicable_credits` is the core total plus the capped
    elective total plus the capped remedial total plus the transfer total,
    rounded half up to two decimal places."

    PRD 3.4: "`progress_pct` is `degree_applicable_credits` divided by the
    program's `total_required_credits`, rounded half up to four decimal places."

    PRD 3.6: "`risk_score` is then the grade component weighted at 0.40, plus
    the progress component at 0.25, plus the travel component at 0.20, plus the
    incident component at 0.15 — the four weights sum to 1.00 — with the
    weighted sum rounded half up to two decimal places once at the end."

    Design: Corner/calculations/elective_credit_program_cap_applied_in_declared_order
    """
    world = _two_elective_world(api)

    fixtures.record_grade(api, world["music_enrollment_id"], "B")

    student = fixtures.read_student(api, world["student_id"])
    assert_close(student["degree_applicable_credits"], 12.00)
    assert student["progress_pct"] == pytest.approx(0.2000, abs=1e-4)
    assert_close(student["cumulative_gpa"], 3.00)
    assert student["completed_full_time_terms"] == 1
    assert_risk(student, 0.00, RISK_TIER_1)
    assert_close(student["required_study_hall_hours"], 0.0)
    assert_student_dimensions(student, support_status=SUPPORT_NORMAL)


def _monday_wednesday_friday_travel_world(api):
    """A Mon/Wed/Fri 10:00-10:50 UTC course and an approved trip that returns
    exactly when the Wednesday meeting begins."""
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    term1 = fixtures.make_term(api, index=1)
    course = fixtures.make_course(
        api,
        subject_code="SOCI",
        course_number="150",
        title="Introduction to Sociology",
        credit_hours=3.0,
        instructor_user_id=INSTRUCTOR_SOC_1,
        meeting_days=[1, 3, 5],
        meeting_start_minute_utc=600,
        meeting_duration_minutes=50,
    )
    student = fixtures.make_student(
        api,
        full_name="Sam Fortyfour",
        sport_code="WBB",
        entry_term_index=1,
        entry_catalog_year=2026,
    )
    enrollment = fixtures.make_enrollment(
        api, student["id"], course["id"], term1["id"]
    )
    event = fixtures.make_approved_event(
        api,
        term1["id"],
        departure_at="2026-09-14T08:00:00Z",
        return_at="2026-09-16T10:00:00Z",
        sport_code="WBB",
        event_type=EVENT_TYPE_REGULAR_SEASON,
    )
    return {
        "student_id": student["id"],
        "enrollment_id": enrollment["id"],
        "event": event,
    }


def test_meeting_starting_exactly_at_return_at_is_not_counted(api):
    """PRD 3.8: "An occurrence counts as missed when its meeting interval
    overlaps the travel window by a strictly positive duration; because both
    windows are half-open, a meeting that begins exactly at `return_at` does not
    count, and neither does one that ends exactly at `departure_at`."

    PRD 3.8: "Third, each counted occurrence yields its own unit figure: take
    the length in whole minutes of the intersection between the meeting interval
    and the travel window, divide by 60 minutes — one missed-class unit is one
    hour of overlap — and round half up to two decimal places."

    PRD 3.8: "Fifth, `missed_units` is `missed_units_gross` multiplied by the
    event's `missed_class_unit_multiplier`, rounded half up to two decimal
    places, and that is the amount charged."

    PRD 3.8: "The request is created in `DRAFT` with `dispute_count` of 0 and
    with `instructor_user_id`, `notified_at`, `acknowledgement_deadline_at` and
    `instructor_response_note` all null."

    Design: Corner/calculations/meeting_starting_exactly_at_return_at_not_counted
    """
    world = _monday_wednesday_friday_travel_world(api)
    assert_close(world["event"]["missed_class_unit_multiplier"], 1.0)

    request = created(
        api.create_missed_class_request(
            factories.missed_class_request(
                world["event"]["id"], world["enrollment_id"]
            ),
            ADVISOR,
        )
    )
    assert_status(request, MCR_DRAFT)
    assert request["missed_meeting_count"] == 1
    assert_close(request["missed_units_gross"], 0.83)
    assert_close(request["missed_units"], 0.83)
    assert request["dispute_count"] == 0
    assert_null(
        request,
        "instructor_user_id",
        "notified_at",
        "acknowledgement_deadline_at",
        "instructor_response_note",
    )


def test_single_missed_meeting_posts_its_charge_to_both_ledgers(api):
    """PRD 3.8: "The charge posts immediately: the student's
    `missed_class_units_charged` increases by `missed_units`,
    `missed_class_units_remaining` becomes the `missed_class_units_allowance`
    minus the new charged total, and the event's `charged_units_total` increases
    by `missed_units`."

    PRD 3.2: "Also optionally, `missed_class_units_allowance` sets the season
    budget of missed-class units the student may be charged; it may not be
    negative and defaults to 9.0 units."

    Design: Corner/calculations/meeting_starting_exactly_at_return_at_not_counted
    """
    world = _monday_wednesday_friday_travel_world(api)

    fixtures.make_request(api, world["event"]["id"], world["enrollment_id"])

    student = fixtures.read_student(api, world["student_id"])
    assert_close(
        student["missed_class_units_allowance"], DEFAULT_MISSED_CLASS_UNITS_ALLOWANCE
    )
    assert_close(student["missed_class_units_charged"], 0.83)
    assert_close(student["missed_class_units_remaining"], 8.17)
    assert_missed_class_budget_conserved(student)

    event = ok(api.get_event(world["event"]["id"], OPERATIONS))
    assert_close(event["charged_units_total"], 0.83)


def test_incident_severity_points_applied_without_decay(api):
    """PRD 3.9: "Substantiating it moves the incident `UNDER_INVESTIGATION →
    SUBSTANTIATED` and requires a `severity` of `LEVEL_I`, `LEVEL_II` or
    `LEVEL_III`, which converts directly into points: one point for `LEVEL_I`,
    two for `LEVEL_II`, three for `LEVEL_III`, written to
    `penalty_points_assessed`."

    PRD 3.9: "The assessed points are added to the student's
    `substantiated_penalty_points`, and where the incident names a tutor, the
    same points are added to that tutor's `penalty_points`. If the tutor's
    `penalty_points` has thereby reached three, the tutor moves `TRAINED →
    SUSPENDED` or `EXPIRED → SUSPENDED`"

    PRD 3.7: "the system writes `training_completed_term_index` from that term's
    ordinal and `training_valid_through_term_index` as that ordinal plus the
    three-term validity span minus one — that is, the ordinal plus two, so
    training completed in term 5 remains valid through terms 5, 6 and 7."

    PRD 2.5: "Point counters — `apr_points_possible`, `apr_points_earned`,
    `apr_points_forfeited`, `penalty_points`, `penalty_points_assessed` and
    `substantiated_penalty_points` — hold whole numbers; no fractional penalty
    is ever stored."

    Design: Corner/calculations/incident_severity_points_applied_without_decay
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z", headers=COMPLIANCE)
    term1 = fixtures.make_term(api, index=1)
    student = fixtures.make_student(
        api,
        full_name="Sam Fortyfive",
        sport_code="MBB",
        entry_term_index=1,
        entry_catalog_year=2026,
    )
    tutor = fixtures.make_trained_tutor(
        api, term1["id"], subject_codes=["MATH"], full_name="Tomas Twopoints"
    )
    incident = fixtures.make_incident(
        api,
        student["id"],
        incident_type="EXCESSIVE_TUTOR_HOURS",
        narrative="Tutor logged hours beyond the weekly cap for this student.",
        tutor_id=tutor["id"],
    )
    fixtures.incident_action(api, incident["id"], INCIDENT_ACTION_OPEN, COMPLIANCE)

    substantiated = ok(
        api.incident_status(
            incident["id"], factories.substantiate(SEVERITY_LEVEL_II), COMPLIANCE
        )
    )
    assert_status(substantiated, INCIDENT_SUBSTANTIATED)
    assert substantiated["severity"] == SEVERITY_LEVEL_II
    assert_whole_number(substantiated["penalty_points_assessed"])
    assert_close(substantiated["penalty_points_assessed"], 2)

    after_tutor = fixtures.read_tutor(api, tutor["id"])
    assert_whole_number(after_tutor["penalty_points"])
    assert_close(after_tutor["penalty_points"], 2)
    assert_status(after_tutor, TUTOR_TRAINED)
    assert after_tutor["training_completed_term_index"] == 1
    assert after_tutor["training_valid_through_term_index"] == 3

    after_student = fixtures.read_student(api, student["id"])
    assert_whole_number(after_student["substantiated_penalty_points"])
    assert_close(after_student["substantiated_penalty_points"], 2)
