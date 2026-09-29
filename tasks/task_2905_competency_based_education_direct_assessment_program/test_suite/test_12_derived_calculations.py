"""Derived figures with one arithmetic answer: the cadence decay curve, the
progress-pace denominator, the critical-ratio constant, the two credit-hour
roundings, the mentor selector and the transcript translation.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import BASE_CLOCK_UTC
from test_helpers.factories import (
    create_attempt_payload,
    create_transcript_record_payload,
    dimension_score,
    rubric_dimension,
)
from test_helpers.test_users import make_mentor_headers, make_student_headers

OVERDUE_CLOCK_UTC = "2026-09-20T00:00:00.000Z"
FIRST_DUE_UTC = "2026-09-08T00:00:00.000Z"
RESET_DUE_UTC = "2026-09-27T00:00:00.000Z"
SECOND_MASTERY_UTC = "2026-09-02T00:00:00.000Z"
THIRD_MASTERY_UTC = "2026-09-03T00:00:00.000Z"
SECOND_TERM_START_UTC = "2026-12-01T00:00:00.000Z"
SECOND_TERM_END_UTC = "2027-03-01T00:00:00.000Z"
THIRD_TERM_START_UTC = "2027-03-01T00:00:00.000Z"
THIRD_TERM_END_UTC = "2027-06-01T00:00:00.000Z"

CRITICAL_PAIR_RUBRIC = [
    rubric_dimension("D1", 0.5000, 100, True),
    rubric_dimension("D2", 0.5000, 100, False),
]


def _assignment_twelve_days_overdue():
    """A weekly assignment made on 2026-09-01 with no contact ever recorded,
    observed nineteen days later so the due instant is twelve days behind."""
    ctx = fx.base_chain(with_blueprint=True)
    ctx["mentor"] = fx.create_mentor(max_caseload=5, cadence_days=7)
    ctx["assignment"] = fx.assign_mentor(fx.refresh_student(ctx["student"]["id"]),
                                        ctx["mentor"]["id"])
    assert ctx["assignment"]["cadence_days"] == 7
    A.assert_instant_equals(ctx["assignment"]["next_contact_due_utc"], FIRST_DUE_UTC,
                            "next_contact_due_utc")
    fx.set_clock(OVERDUE_CLOCK_UTC)
    return ctx


def test_the_overdue_day_count_is_the_whole_days_past_the_due_instant():
    """The anchor stays the assignment instant because no contact was ever made, so
    from 2026-09-20 the due instant of 2026-09-08 is twelve whole days behind. The
    same pair of clock-derived figures is echoed by the progress summary.

    PRD: "Its `overdue_days` is 0 while compliant, and otherwise the whole number of
    days by which the clock has passed the due instant, obtained by dividing the
    elapsed seconds by 86,400 and discarding the remainder."

    Design: Corner/calculations/cadence_overdue_days_computed_and_gates_attempts
    """
    ctx = _assignment_twelve_days_overdue()

    read = fx.refresh_assignment(ctx["assignment"]["id"])
    assert read["last_contact_utc"] is None
    A.assert_instant_equals(read["next_contact_due_utc"], FIRST_DUE_UTC,
                            "next_contact_due_utc")
    assert read["cadence_status"] == "OVERDUE"
    assert read["overdue_days"] == 12

    summary = fx.progress_summary(ctx["student"]["id"])
    A.assert_progress_summary_shape(summary)
    assert summary["cadence_status"] == "OVERDUE"
    assert summary["overdue_days"] == 12


def test_the_same_overdue_figure_gates_a_new_attempt():
    """Twelve overdue days has reached the program's gate of seven, so the read and
    the gate are visibly one computation: no attempt may be opened and no row is
    created.

    PRD: "When a student's active assignment has an `overdue_days` that has reached
    the program's `cadence_gate_overdue_days`, no new attempt may be opened, and the
    request is refused with `ERR_MENTOR_CADENCE_OVERDUE`."

    Design: Corner/calculations/cadence_overdue_days_computed_and_gates_attempts
    """
    ctx = _assignment_twelve_days_overdue()

    response = api_client.create_attempt(
        create_attempt_payload(ctx["student"]["id"], ctx["competency"]["id"]),
        make_student_headers(ctx["student"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_MENTOR_CADENCE_OVERDUE.value, 422)

    A.assert_page(
        api_client.list_attempts(fx.REGISTRAR,
                                 params={"student_id": ctx["student"]["id"]}),
        0,
    )


def test_a_contact_restarts_the_cadence_curve_from_the_contact_instant():
    """The reset anchors on the contact rather than on the missed due date: seven
    days after 2026-09-20 is 2026-09-27, not seven days after the 2026-09-08 the
    assignment had already sailed past.

    PRD: "An assignment's `next_contact_due_utc` is its `last_contact_utc` advanced
    by `cadence_days` days when a contact has been recorded, and its
    `assigned_at_utc` advanced by `cadence_days` days when none has."

    Design: Corner/calculations/contact_resets_the_cadence_curve
    """
    ctx = _assignment_twelve_days_overdue()
    before = fx.refresh_assignment(ctx["assignment"]["id"])
    assert before["cadence_status"] == "OVERDUE"
    assert before["overdue_days"] == 12
    assert before["contact_count"] == 0

    after = validate_success(
        api_client.record_contact(
            ctx["assignment"]["id"],
            make_mentor_headers(ctx["mentor"]["id"]),
            {"note": "Weekly progress call"},
        ),
        200,
    )
    A.assert_instant_equals(after["last_contact_utc"], OVERDUE_CLOCK_UTC,
                            "last_contact_utc")
    A.assert_instant_equals(after["next_contact_due_utc"], RESET_DUE_UTC,
                            "next_contact_due_utc")


def test_the_contact_self_transition_clears_the_whole_overdue_picture():
    """Recording the contact is a self-transition: the pairing stays active while the
    compliance state, the overdue count and the contact tally all move in one step.

    PRD: "On success `last_contact_utc` becomes the logical clock, `contact_count`
    increases by 1, `next_contact_due_utc` is recomputed from the new anchor,
    `cadence_status` returns to `COMPLIANT`, `overdue_days` returns to 0, and the
    assignment's `version` increments."

    Design: Corner/calculations/contact_resets_the_cadence_curve
    """
    ctx = _assignment_twelve_days_overdue()

    after = fx.record_contact(ctx["assignment"]["id"], ctx["mentor"]["id"],
                             note="Weekly progress call")
    A.assert_mentor_assignment(after)
    assert after["status"] == "ACTIVE"
    assert after["cadence_status"] == "COMPLIANT"
    assert after["overdue_days"] == 0
    assert after["contact_count"] == 1
    assert after["version"] > ctx["assignment"]["version"]


def test_the_progress_pace_denominator_ignores_the_pending_and_cancelled_terms():
    """Three terms exist but only the one that actually started counts, so the bar is
    twelve units rather than thirty-six and twelve mastered units read as exactly on
    pace instead of far behind.

    PRD: "First, `terms_counted` is the number of the student's subscription terms
    whose `status` is `ACTIVE`, `COMPLETED` or `LAPSED` and whose `term_start_utc` is
    at or before the reviewed term's `term_start_utc`."

    Design: Corner/calculations/sap_denominator_counts_only_started_terms
    """
    ctx = fx.scored_attempt(
        score=100,
        competency_overrides={"unit_value": 12, "level": "CORE"},
    )
    assert ctx["student"]["mastered_unit_total"] == 12

    fx.create_term(ctx["student"]["id"], term_start_utc=SECOND_TERM_START_UTC,
                  term_end_utc=SECOND_TERM_END_UTC)
    third = fx.create_term(ctx["student"]["id"], term_start_utc=THIRD_TERM_START_UTC,
                          term_end_utc=THIRD_TERM_END_UTC)
    assert fx.close_term(third["id"], "CANCELLED", BASE_CLOCK_UTC)["status"] == "CANCELLED"

    review = validate_success(
        api_client.create_sap_review(
            {"student_id": ctx["student"]["id"], "term_id": ctx["term"]["id"]},
            fx.REGISTRAR,
        ),
        201,
    )
    A.assert_sap_review(review)
    assert review["terms_counted"] == 1
    assert review["expected_units"] == 12
    A.assert_number_equals(review["pace_pct"], 100.00, "pace_pct")
    assert review["pace_band"] == "GOOD"
    assert review["previous_sap_status"] == "GOOD_STANDING"
    assert review["new_sap_status"] == "GOOD_STANDING"


def test_the_critical_ratio_constant_and_not_the_total_decides_the_outcome():
    """A critical dimension at 0.85 of its ceiling falls short of the program's
    raised floor of 0.90, so the flag fires even though the weighted total of 92.50
    clears the 80.00 bar and the attempt lands short of mastery with a cool-off.

    PRD: "It is true when at least one dimension marked `critical` has a ratio
    strictly below the program's `critical_dimension_min_ratio`."

    Design: Corner/calculations/critical_dimension_ratio_constant_is_applied
    """
    ctx = fx.attempt_under_review(
        program_overrides={"critical_dimension_min_ratio": 0.90,
                           "mastery_threshold_pct": 80.00},
        blueprint_dimensions=CRITICAL_PAIR_RUBRIC,
        blueprint_overrides={"passing_rule": "WEIGHTED_PLUS_ALL_CRITICAL",
                             "required_evaluator_count": 1},
        submit_overrides={"artifact_hash": "sha256:crit1",
                          "client_fingerprint": "fp-crit-1"},
    )
    A.assert_number_equals(ctx["program"]["critical_dimension_min_ratio"], 0.90,
                           "critical_dimension_min_ratio")

    score = fx.record_score(
        ctx["attempt"]["id"], ctx["evaluator"]["id"],
        [dimension_score("D1", 85), dimension_score("D2", 100)],
    )
    A.assert_number_equals(score["weighted_score_pct"], 92.50, "weighted_score_pct")
    assert score["critical_fail"] is True

    attempt = fx.refresh_attempt(ctx["attempt"]["id"])
    assert attempt["status"] == "SCORED_NOT_MASTERED"
    A.assert_number_equals(attempt["final_score_pct"], 92.50, "final_score_pct")
    assert attempt["critical_fail"] is True
    A.assert_instant_equals(attempt["cooloff_until_utc"],
                            "2026-09-03T00:00:00.000Z", "cooloff_until_utc")
    assert attempt["mastered_at_utc"] is None
    assert fx.refresh_student(ctx["student"]["id"])["mastered_unit_total"] == 0


def test_five_units_over_three_reads_as_one_point_seven_cumulatively_and_one_for_aid():
    """The same five units are divided by the same ratio twice under two different
    rules: the cumulative transcript figure rounds half up to 1.7 while the term's
    aid figure takes the floor at 1, and the summary publishes the 0.7 gap between
    them as a first-class number.

    PRD: "It divides the student's lifetime `mastered_unit_total` by
    `units_per_credit_hour` and rounds half up to one decimal place, evaluated
    cumulatively over the student's entire record rather than per term."

    Design: Corner/calculations/credit_equivalency_rounds_to_one_decimal
    """
    ctx = fx.scored_attempt(
        score=100,
        competency_overrides={"unit_value": 5, "level": "CORE"},
    )
    A.assert_number_equals(ctx["program"]["units_per_credit_hour"], 3.0,
                           "units_per_credit_hour")

    term = fx.refresh_term(ctx["term"]["id"])
    assert term["units_mastered_in_term"] == 5
    assert term["credit_equivalency_earned"] == 1

    summary = fx.progress_summary(ctx["student"]["id"])
    assert summary["mastered_unit_total"] == 5
    A.assert_number_equals(summary["cumulative_credit_equivalency"], 1.7,
                           "cumulative_credit_equivalency")
    A.assert_number_equals(summary["aid_credit_equivalency_sum"], 1,
                           "aid_credit_equivalency_sum")
    A.assert_number_equals(summary["credit_equivalency_variance"], 0.7,
                           "credit_equivalency_variance")
    A.assert_credit_equivalency_variance(summary)


def _idle_mentor_beside_a_loaded_one():
    """Mentor Alpha created first and already carrying Ben, Mentor Beta created
    second and idle, with Ada waiting for the selector to choose."""
    ctx = fx.base_chain(create_the_term=False)
    ben = fx.create_student(ctx["program"]["id"], full_name="Ben Learner",
                           email="ben@example.edu")
    ben = fx.activate_student(ben["id"])
    ctx["alpha"] = fx.create_mentor(full_name="Mentor Alpha",
                                   email="alpha@example.edu",
                                   max_caseload=5, cadence_days=7)
    ctx["beta"] = fx.create_mentor(full_name="Mentor Beta",
                                  email="beta@example.edu",
                                  max_caseload=5, cadence_days=14)
    fx.assign_mentor(ben, ctx["alpha"]["id"])
    assert fx.refresh_mentor(ctx["alpha"]["id"])["current_caseload"] == 1
    assert fx.refresh_mentor(ctx["beta"]["id"])["current_caseload"] == 0

    ctx["chosen"] = validate_success(
        api_client.create_mentor_assignment(
            {"student_id": ctx["student"]["id"],
             "expected_student_version": fx.refresh_student(
                 ctx["student"]["id"])["version"]},
            fx.REGISTRAR,
        ),
        201,
    )
    return ctx


def test_the_selector_reads_the_live_caseload_and_picks_the_idle_mentor():
    """With the mentor unnamed the ranking runs on the caseloads as they stand, so
    the idle mentor wins over the one already carrying a mentee even though that one
    was registered first, and both caseloads settle at one.

    PRD: "The eligible pool is then ranked by four criteria applied in order until
    one mentor remains: ascending `current_caseload`, so the least-loaded mentor
    wins; then descending `max_caseload`, preferring the mentor with the most
    headroom; then ascending `cadence_days`, preferring the most attentive contact
    rhythm; and finally ascending `created_at` as the deterministic last tie-break."

    Design: Corner/calculations/auto_selection_propagates_to_the_least_loaded_mentor
    """
    ctx = _idle_mentor_beside_a_loaded_one()

    A.assert_mentor_assignment(ctx["chosen"])
    assert ctx["chosen"]["selection_mode"] == "AUTO_SELECTED"
    assert ctx["chosen"]["mentor_id"] == ctx["beta"]["id"]
    assert fx.refresh_mentor(ctx["alpha"]["id"])["current_caseload"] == 1
    assert fx.refresh_mentor(ctx["beta"]["id"])["current_caseload"] == 1


def test_the_auto_selected_pairing_inherits_the_chosen_mentors_own_rhythm():
    """No cadence was supplied, so the pairing takes the fortnightly rhythm of the
    mentor the selector landed on rather than the weekly rhythm of the one it passed
    over.

    PRD: "The created assignment stores its own `cadence_days`: the value supplied in
    the request when one was supplied, and otherwise the `cadence_days` of the mentor
    who was chosen."

    Design: Corner/calculations/auto_selection_propagates_to_the_least_loaded_mentor
    """
    chosen = _idle_mentor_beside_a_loaded_one()["chosen"]

    assert chosen["cadence_days"] == 14
    A.assert_instant_equals(chosen["next_contact_due_utc"],
                            "2026-09-15T00:00:00.000Z", "next_contact_due_utc")
    assert chosen["cadence_status"] == "COMPLIANT"
    assert chosen["overdue_days"] == 0


def _mastered_out_of_creation_order():
    """Two four-unit competencies: the one attempted first is mastered second, so the
    creation order and the mastery order disagree."""
    fx.set_clock(BASE_CLOCK_UTC)
    program = fx.create_program()
    first = fx.create_competency(program["id"], code="IT-101",
                                title="Relational Data Modeling",
                                unit_value=4, level="FOUNDATION")
    second = fx.create_competency(program["id"], code="IT-102",
                                 title="Query Optimisation",
                                 unit_value=4, level="FOUNDATION")
    fx.create_blueprint(first)
    fx.create_blueprint(second)
    program = fx.publish_program(program["id"])
    student = fx.activate_student(fx.create_student(program["id"])["id"])
    term = fx.activate_term(fx.create_term(student["id"])["id"])
    evaluator = fx.create_evaluator()

    early = fx.open_attempt(student["id"], first["id"])
    fx.submit_attempt(early["id"], student["id"], artifact_hash="sha256:chronA",
                     client_fingerprint="fp-chron-a")

    fx.set_clock(SECOND_MASTERY_UTC)
    late = fx.open_attempt(student["id"], second["id"])
    fx.submit_attempt(late["id"], student["id"], artifact_hash="sha256:chronB",
                     client_fingerprint="fp-chron-b")
    fx.record_score(late["id"], evaluator["id"], [dimension_score("D1", 100)])

    fx.set_clock(THIRD_MASTERY_UTC)
    fx.record_score(early["id"], evaluator["id"], [dimension_score("D1", 100)])

    return {"program": program, "student": student, "term": term,
            "early": early, "late": late}


def test_the_transcript_lists_lines_by_mastery_instant_not_by_creation_instant():
    """Ordering by creation would invert the record: the competency attempted first
    was mastered a day later, so it belongs on the second line.

    PRD: "Lines are ordered by `mastered_at_utc` ascending with the mastering
    attempt's `created_at` ascending as tie-break — ordered by **mastery** instant,
    not by creation instant, so a competency the student attempted first but mastered
    later appears later on the transcript."

    Design: Corner/calculations/transcript_lines_ordered_by_mastery_not_creation
    """
    ctx = _mastered_out_of_creation_order()

    record = validate_success(
        api_client.create_transcript_record(
            create_transcript_record_payload(ctx["student"]["id"], purpose="TRANSFER"),
            fx.REGISTRAR,
        ),
        201,
    )
    A.assert_transcript_record(record)
    assert record["status"] == "DRAFT"
    assert record["competency_line_count"] == 2

    codes = [line["competency_code"] for line in record["lines"]]
    assert codes == ["IT-102", "IT-101"], f"lines out of mastery order: {codes}"
    A.assert_instant_equals(record["lines"][0]["mastered_at_utc"],
                            SECOND_MASTERY_UTC, "lines[0].mastered_at_utc")
    A.assert_instant_equals(record["lines"][1]["mastered_at_utc"],
                            THIRD_MASTERY_UTC, "lines[1].mastered_at_utc")


def test_the_two_rounding_rules_disagree_by_a_published_residual():
    """Each four-unit line rounds to 1.33 for a line sum of 2.66, while the headline
    figure divides the eight summed units once and rounds to 2.7 — and the four
    hundredths of a credit hour between them is published rather than hidden.

    PRD: "The gap between the two approaches is not swept under the rug but published
    as `rounding_residual_credit_hours`, which is `line_credit_hour_sum` minus
    `translated_credit_hours`, rounded half up to two decimals — the artifact the
    receiving institution must reconcile, stated explicitly rather than left for them
    to discover."

    Design: Corner/calculations/transcript_lines_ordered_by_mastery_not_creation
    """
    ctx = _mastered_out_of_creation_order()

    record = fx.create_transcript(ctx["student"]["id"], purpose="TRANSFER")
    assert record["total_mastered_units"] == 8
    for index, line in enumerate(record["lines"]):
        A.assert_number_equals(line["line_credit_hours"], 1.33,
                               f"lines[{index}].line_credit_hours")
    A.assert_number_equals(record["line_credit_hour_sum"], 2.66,
                           "line_credit_hour_sum")
    A.assert_number_equals(record["translated_credit_hours"], 2.7,
                           "translated_credit_hours")
    A.assert_number_equals(record["rounding_residual_credit_hours"], -0.04,
                           "rounding_residual_credit_hours")


def test_a_zero_hour_cooloff_publishes_an_already_elapsed_window():
    """With the policy set to no hours at all the failed attempt still publishes the
    window, and it lands on its own scoring instant — a boundary that the clock has
    already reached.

    PRD: "The logical clock must be at or after that instant; the boundary is
    inclusive, so the attempt becomes available at exactly the cool-off instant
    rather than a moment later."

    Design: Corner/calculations/failed_attempt_reshapes_the_next_attempt_ladder
    """
    ctx = fx.scored_attempt(
        score=40,
        program_overrides={"code": "CBE-LADDER", "title": "Ladder Program",
                           "attempt_cooloff_hours": 0},
        submit_overrides={"artifact_hash": "sha256:lad1",
                          "client_fingerprint": "fp-lad-1"},
    )
    assert ctx["program"]["attempt_cooloff_hours"] == 0
    assert ctx["program"]["attempts_before_endorsement"] == 3

    attempt = ctx["attempt"]
    assert attempt["attempt_number"] == 1
    assert attempt["status"] == "SCORED_NOT_MASTERED"
    A.assert_instant_equals(attempt["scored_at_utc"], BASE_CLOCK_UTC, "scored_at_utc")
    A.assert_instant_equals(attempt["cooloff_until_utc"], BASE_CLOCK_UTC,
                            "cooloff_until_utc")


def test_the_retry_is_admitted_at_the_same_instant_and_numbered_second():
    """The ladder is re-evaluated against the history that exists: one failure is
    still below the endorsement threshold and the cool-off has already elapsed, so the
    retry is created as the second attempt with no endorsement consumed.

    PRD: "The attempt's `attempt_number` is the one-based ordinal of this attempt
    among the student's non-voided attempts on the same competency, ordered by
    creation instant."

    Design: Corner/calculations/failed_attempt_reshapes_the_next_attempt_ladder
    """
    ctx = fx.scored_attempt(
        score=40,
        program_overrides={"code": "CBE-LADDER", "title": "Ladder Program",
                           "attempt_cooloff_hours": 0},
        submit_overrides={"artifact_hash": "sha256:lad1",
                          "client_fingerprint": "fp-lad-1"},
    )

    retry = validate_success(
        api_client.create_attempt(
            create_attempt_payload(ctx["student"]["id"], ctx["competency"]["id"]),
            make_student_headers(ctx["student"]["id"]),
        ),
        201,
    )
    assert retry["attempt_number"] == 2
    assert retry["status"] == "DRAFT"
    assert retry["cooloff_until_utc"] is None
    assert retry["endorsement_consumed"] is False
