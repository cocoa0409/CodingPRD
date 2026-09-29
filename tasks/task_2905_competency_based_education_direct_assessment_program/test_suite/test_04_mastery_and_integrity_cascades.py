"""Transitive cascades: mastery driving a student all the way to graduation, and
an integrity substantiation running the same ledger backwards.
"""
from prd_bench_local_runner.testing import get_success_data

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.constants import BASE_CLOCK_UTC
from test_helpers.factories import create_integrity_case_payload, dimension_score
from test_helpers.test_users import make_evaluator_headers


def _one_competency_short_of_the_finish_line():
    """A certificate needing eight units, four of them already mastered, with an
    active mentor assignment and a second attempt waiting for its reader."""
    fx.set_clock(BASE_CLOCK_UTC)
    program = fx.create_program(code="CBE-CERT", title="Data Analytics Certificate",
                                required_unit_total=8, units_per_credit_hour=3.0)
    first = fx.create_competency(program["id"], code="FC-1",
                                 title="Descriptive Statistics", unit_value=4,
                                 level="FOUNDATION")
    fx.create_blueprint(first, required_evaluator_count=1)
    second = fx.create_competency(program["id"], code="FC-2",
                                  title="Inferential Statistics", unit_value=4,
                                  level="CORE")
    fx.create_blueprint(second, required_evaluator_count=1)
    program = fx.publish_program(program["id"])
    student = fx.activate_student(fx.create_student(program["id"])["id"])
    term = fx.activate_term(fx.create_term(student["id"])["id"])
    mentor = fx.create_mentor(full_name="Mentor Mira", email="mira@example.edu",
                              max_caseload=5, cadence_days=7)
    student = fx.refresh_student(student["id"])
    assignment = fx.assign_mentor(student, mentor["id"])
    evaluator = fx.create_evaluator()

    early = fx.open_attempt(student["id"], first["id"])
    fx.submit_attempt(early["id"], student["id"], artifact_hash="sha256:fc1-a")
    fx.record_score(early["id"], evaluator["id"], [dimension_score("D1", 90)])

    final = fx.open_attempt(student["id"], second["id"])
    fx.submit_attempt(final["id"], student["id"], artifact_hash="sha256:fc2-a")
    return {"program": program, "student": student, "term": term, "mentor": mentor,
            "assignment": assignment, "evaluator": evaluator, "attempt": final}


def test_the_second_mastery_lifts_the_unit_total_and_the_terms_equivalency():
    """Hop one masters the attempt and hop two fires only because that happened,
    raising the student's lifetime total and recomputing the owning term.

    PRD: "Hop two fires because the attempt entered that state: the student's
    `mastered_unit_total` increases by the mastered competency's `unit_value`,
    `mastered_competency_count` increases by one, `cumulative_credit_equivalency`
    is recomputed, the owning term's `units_mastered_in_term` and
    `credit_equivalency_earned` are recomputed, and every transcript record of
    that student in `DRAFT` or `ISSUED` is voided with `voided_reason`
    `UNIT_TOTAL_CHANGED` — a transcript is a snapshot and is invalidated rather
    than edited whenever the underlying total moves."

    Design: Difficulty/transitive_cascade/mastery_to_graduation_cascade
    """
    ctx = _one_competency_short_of_the_finish_line()

    score = fx.record_score(ctx["attempt"]["id"], ctx["evaluator"]["id"],
                            [dimension_score("D1", 90)])
    A.assert_number_equals(score["weighted_score_pct"], 90.00, "weighted_score_pct")

    attempt = fx.refresh_attempt(ctx["attempt"]["id"])
    assert attempt["status"] == "SCORED_MASTERED"
    A.assert_instant_equals(attempt["mastered_at_utc"], BASE_CLOCK_UTC,
                            "mastered_at_utc")

    student = fx.refresh_student(ctx["student"]["id"])
    assert student["mastered_unit_total"] == 8
    assert student["mastered_competency_count"] == 2
    A.assert_number_equals(student["cumulative_credit_equivalency"], 2.7,
                           "cumulative_credit_equivalency")

    term = fx.refresh_term(ctx["term"]["id"])
    assert term["units_mastered_in_term"] == 8
    assert term["credit_equivalency_earned"] == 2


def test_graduation_releases_the_mentor_and_closes_the_term_as_fully_earned():
    """Hop three graduates the student because the total reached the requirement,
    and hop four fires only because of that, ending the mentoring relationship and
    closing the commercial period — none of which the scoring request named.

    PRD: "Hop four fires because the student graduated: every mentor assignment of
    that student in `ACTIVE` is ended with `ended_at_utc` at the logical clock,
    each ending decrementing its mentor's `current_caseload` by one, and every
    subscription term of that student in `ACTIVE` is closed as `COMPLETED` with
    `closed_effective_utc` at the logical clock."

    Design: Difficulty/transitive_cascade/mastery_to_graduation_cascade
    """
    ctx = _one_competency_short_of_the_finish_line()

    fx.record_score(ctx["attempt"]["id"], ctx["evaluator"]["id"],
                    [dimension_score("D1", 90)])

    student = fx.refresh_student(ctx["student"]["id"])
    assert student["enrollment_status"] == "GRADUATED"
    A.assert_instant_equals(student["graduated_at_utc"], BASE_CLOCK_UTC,
                            "graduated_at_utc")

    assignment = fx.refresh_assignment(ctx["assignment"]["id"])
    assert assignment["status"] == "ENDED"
    A.assert_instant_equals(assignment["ended_at_utc"], BASE_CLOCK_UTC, "ended_at_utc")
    assert fx.refresh_mentor(ctx["mentor"]["id"])["current_caseload"] == 0

    term = fx.refresh_term(ctx["term"]["id"])
    assert term["status"] == "COMPLETED"
    A.assert_number_equals(term["earned_pct"], 1.0000, "earned_pct")
    A.assert_cents(term["institutional_refund_cents"], 0, "institutional_refund_cents")
    A.assert_instant_equals(term["closed_effective_utc"], BASE_CLOCK_UTC,
                            "closed_effective_utc")


def _substantiable_case_over_mastered_work():
    """Four mastered units carrying an issued transcript and a scheduled award,
    with a duplicate-artifact case already under investigation."""
    ctx = fx.scored_attempt(
        score=92,
        program_overrides={"units_per_credit_hour": 3.0,
                           "aid_min_credit_equivalency": 1},
    )
    ctx["record"] = fx.issue_transcript(
        fx.create_transcript(ctx["student"]["id"], purpose="TRANSFER")["id"]
    )
    ctx["term"] = fx.refresh_term(ctx["term"]["id"])
    assert ctx["term"]["credit_equivalency_earned"] == 1
    ctx["award"] = fx.schedule_aid(ctx["student"]["id"], ctx["term"])

    case = get_success_data(
        api_client.create_integrity_case(
            create_integrity_case_payload(
                ctx["attempt"]["id"], signal_type="DUPLICATE_ARTIFACT",
                severity="HIGH",
                note="Artifact hash seen on an external repository",
            ),
            make_evaluator_headers(ctx["evaluator"]["id"]),
        )
    )
    ctx["case"] = fx.investigate_case(case["id"], officer_user_id="io-1")
    return ctx


def test_voiding_a_mastered_attempt_unwinds_the_units_and_voids_the_transcript():
    """Substantiation with an attempt void takes the units straight back out and
    invalidates the transcript rather than editing it, leaving no residue.

    PRD: "Hop three fires **only because hop two removed the attempt's
    contribution**, and only when the voided attempt was in `SCORED_MASTERED`: the
    student's `mastered_unit_total` decreases by the competency's `unit_value`,
    `mastered_competency_count` decreases by one, `cumulative_credit_equivalency`
    is recomputed, the owning term's `units_mastered_in_term` and
    `credit_equivalency_earned` are recomputed, every transcript record of that
    student in `DRAFT` or `ISSUED` is voided with `voided_reason`
    `UNIT_TOTAL_CHANGED`, and the reliability figures of every affected evaluator
    are recomputed because the voided pair has left their denominators."

    Design: Difficulty/transitive_cascade/integrity_void_cascade
    """
    ctx = _substantiable_case_over_mastered_work()

    resolved = fx.resolve_case(ctx["case"]["id"], "SUBSTANTIATED",
                               sanction="ATTEMPT_VOID", resolver_user_id="io-1")
    assert resolved["status"] == "SUBSTANTIATED"
    assert resolved["sanction"] == "ATTEMPT_VOID"

    attempt = fx.refresh_attempt(ctx["attempt"]["id"])
    assert attempt["status"] == "VOIDED"
    assert attempt["integrity_hold"] is False

    score = fx.refresh_score(ctx["score"]["id"])
    assert score["status"] == "VOIDED"
    assert score["voided_reason"] == "ATTEMPT_VOIDED"

    student = fx.refresh_student(ctx["student"]["id"])
    assert student["integrity_strike_count"] == 1
    assert student["mastered_unit_total"] == 0
    assert student["mastered_competency_count"] == 0
    A.assert_number_equals(student["cumulative_credit_equivalency"], 0.0,
                           "cumulative_credit_equivalency")

    record = fx.refresh_transcript(ctx["record"]["id"])
    assert record["status"] == "VOIDED"
    assert record["voided_reason"] == "UNIT_TOTAL_CHANGED"


def test_the_collapsed_equivalency_holds_the_scheduled_award_for_shortfall():
    """The last hop fires only because the term's equivalency fell under the
    program floor, and it holds the award without touching enrollment — this is
    only the first strike.

    PRD: "Hop four fires **only because hop three changed the term's
    equivalency**: when the term's recomputed `credit_equivalency_earned` has
    fallen below the program's `aid_min_credit_equivalency`, every disbursement on
    that term with `status` `SCHEDULED` moves to `HELD` with `hold_reason`
    `CREDIT_EQUIVALENCY_SHORTFALL`, and every disbursement already `DISBURSED` has
    `aid_review_required` set to true — money that has already left cannot be
    un-sent, so it is flagged for a human instead."

    Design: Difficulty/transitive_cascade/integrity_void_cascade
    """
    ctx = _substantiable_case_over_mastered_work()

    fx.resolve_case(ctx["case"]["id"], "SUBSTANTIATED", sanction="ATTEMPT_VOID",
                    resolver_user_id="io-1")

    term = fx.refresh_term(ctx["term"]["id"])
    assert term["units_mastered_in_term"] == 0
    assert term["credit_equivalency_earned"] == 0

    award = fx.refresh_award(ctx["award"]["id"])
    assert award["status"] == "HELD"
    assert award["hold_reason"] == "CREDIT_EQUIVALENCY_SHORTFALL"
    A.assert_cents(award["outstanding_amount_cents"], 200000,
                   "outstanding_amount_cents")
    A.assert_aid_ledger_identity(award)

    assert fx.refresh_student(ctx["student"]["id"])["enrollment_status"] == "ACTIVE"
