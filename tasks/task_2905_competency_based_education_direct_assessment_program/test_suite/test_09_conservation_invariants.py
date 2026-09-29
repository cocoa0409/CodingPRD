"""Conserved quantities across a compensating action: competency units on an
integrity void, and integer aid cents across the whole award ledger.
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.constants import BASE_CLOCK_UTC
from test_helpers.factories import (
    create_integrity_case_payload,
    dimension_score,
    rubric_dimension,
)
from test_helpers.test_users import make_evaluator_headers

CLOSE_CLOCK_UTC = "2026-10-01T00:00:00.000Z"
SINGLE_DIMENSION = [rubric_dimension("D1", 1.0000, 100, False)]


def _ten_units_over_two_competencies_with_a_case_on_the_smaller():
    """Four units and six units both mastered at 95.00, with an integrity case
    already under investigation against the four-unit attempt."""
    fx.set_clock(BASE_CLOCK_UTC)
    program = fx.create_program(units_per_credit_hour=3.0,
                               aid_min_credit_equivalency=1)
    small = fx.create_competency(program["id"], code="IT-101",
                                 title="Relational Data Modeling",
                                 unit_value=4, level="FOUNDATION")
    fx.create_blueprint(small, dimensions=SINGLE_DIMENSION,
                        required_evaluator_count=1)
    large = fx.create_competency(program["id"], code="IT-102",
                                 title="Systems Analysis",
                                 unit_value=6, level="CORE")
    fx.create_blueprint(large, dimensions=SINGLE_DIMENSION,
                        required_evaluator_count=1)
    program = fx.publish_program(program["id"])
    student = fx.activate_student(fx.create_student(program["id"])["id"])
    term = fx.activate_term(fx.create_term(student["id"])["id"])
    evaluator = fx.create_evaluator(full_name="Reader One", email="r1@example.edu")

    small_attempt = fx.open_attempt(student["id"], small["id"])
    fx.submit_attempt(small_attempt["id"], student["id"],
                      artifact_hash="sha256:it101-a")
    fx.record_score(small_attempt["id"], evaluator["id"],
                    [dimension_score("D1", 95)])
    large_attempt = fx.open_attempt(student["id"], large["id"])
    fx.submit_attempt(large_attempt["id"], student["id"],
                      artifact_hash="sha256:it102-a")
    fx.record_score(large_attempt["id"], evaluator["id"],
                    [dimension_score("D1", 95)])

    case = get_success_data(api_client.create_integrity_case(
        create_integrity_case_payload(
            small_attempt["id"], signal_type="SHARED_DEVICE", severity="MEDIUM",
            note="Same device fingerprint reported by proctoring analytics",
        ),
        make_evaluator_headers(evaluator["id"]),
    ))
    case = fx.investigate_case(case["id"], officer_user_id="io-1")
    return {"program": program, "student": student, "term": term, "small": small,
            "large": large, "small_attempt": small_attempt,
            "large_attempt": large_attempt, "case": case}


def test_the_unit_ledger_agrees_with_itself_across_student_term_and_attempts():
    """Before any compensation, ten units are reported identically by the student
    roll-up, by the owning term and by the two mastered attempts, and the published
    reconciliation gap is the 0.3 the two rounding rules genuinely disagree by.

    PRD: "A student's `mastered_unit_total` always equals a full recomputation of the
    sum of `unit_value` over the competencies for which the student currently holds a
    non-provisional mastered attempt, and `mastered_competency_count` always equals
    the count of distinct competencies contributing to that sum."

    Design: Difficulty/compensating_invariant/unit_conservation_on_integrity_void
    """
    ctx = _ten_units_over_two_competencies_with_a_case_on_the_smaller()

    summary = fx.progress_summary(ctx["student"]["id"])
    A.assert_progress_summary_shape(summary)
    assert summary["mastered_unit_total"] == 10
    assert summary["mastered_competency_count"] == 2
    A.assert_number_equals(summary["cumulative_credit_equivalency"], 3.3,
                           "cumulative_credit_equivalency")
    assert summary["aid_credit_equivalency_sum"] == 3
    A.assert_number_equals(summary["credit_equivalency_variance"], 0.3,
                           "credit_equivalency_variance")
    A.assert_credit_equivalency_variance(summary)

    term = fx.refresh_term(ctx["term"]["id"])
    assert term["units_mastered_in_term"] == 10
    assert term["credit_equivalency_earned"] == 3
    assert term["units_mastered_in_term"] == summary["mastered_unit_total"]


def test_voiding_the_four_unit_attempt_leaves_no_residue_anywhere_in_the_ledger():
    """The void is the compensating action for the mastery award, so every figure
    derived from the unit total steps back exactly: 10 units become 6, two mastered
    competencies become one, the cumulative figure is recomputed downwards to 2.0 and
    the term's whole-credit figure to 2, closing the variance to 0.0.

    PRD: "No residue may remain in the student's total, in the owning term's
    `units_mastered_in_term` or `credit_equivalency_earned`, or in any transcript
    record — a transcript is voided outright rather than edited."

    Design: Difficulty/compensating_invariant/unit_conservation_on_integrity_void
    """
    ctx = _ten_units_over_two_competencies_with_a_case_on_the_smaller()

    resolved = fx.resolve_case(ctx["case"]["id"], "SUBSTANTIATED",
                               sanction="ATTEMPT_VOID", resolver_user_id="io-1")
    assert resolved["status"] == "SUBSTANTIATED"

    assert fx.refresh_attempt(ctx["small_attempt"]["id"])["status"] == "VOIDED"
    assert fx.refresh_attempt(ctx["large_attempt"]["id"])["status"] == "SCORED_MASTERED"

    summary = fx.progress_summary(ctx["student"]["id"])
    assert summary["mastered_unit_total"] == 6
    assert summary["mastered_competency_count"] == 1
    A.assert_number_equals(summary["cumulative_credit_equivalency"], 2.0,
                           "cumulative_credit_equivalency")
    assert summary["aid_credit_equivalency_sum"] == 2
    A.assert_number_equals(summary["credit_equivalency_variance"], 0.0,
                           "credit_equivalency_variance")

    term = fx.refresh_term(ctx["term"]["id"])
    assert term["units_mastered_in_term"] == 6
    assert term["credit_equivalency_earned"] == 2
    assert term["units_mastered_in_term"] == summary["mastered_unit_total"]

    student = fx.refresh_student(ctx["student"]["id"])
    assert student["mastered_unit_total"] == 6
    assert student["mastered_competency_count"] == 1


def _one_award_through_schedule_and_release():
    """A 200000-cent award on a term that already carries one whole credit hour,
    scheduled and then released."""
    ctx = fx.scored_attempt(
        score=95,
        program_overrides={"units_per_credit_hour": 3.0,
                           "aid_min_credit_equivalency": 1},
    )
    assert fx.refresh_term(ctx["term"]["id"])["credit_equivalency_earned"] == 1
    ctx["scheduled"] = validate_success(
        api_client.create_aid_disbursement(
            {"student_id": ctx["student"]["id"], "term_id": ctx["term"]["id"],
             "scheduled_amount_cents": 200000,
             "expected_term_version": fx.refresh_term(ctx["term"]["id"])["version"]},
            fx.AID_OFFICER,
        ),
        201,
    )
    return ctx


def test_the_cents_identity_holds_at_both_the_scheduled_and_the_released_state():
    """One award, two states, one identity: 200000 sits wholly in the outstanding
    bucket while scheduled and moves wholly into the retained bucket on release, with
    nothing created and nothing lost in between.

    PRD: "In `SCHEDULED` and `HELD`, `outstanding_amount_cents` equals
    `scheduled_amount_cents` and the retained, returned and cancelled buckets are all
    zero. In `DISBURSED`, outstanding is zero, retained equals the scheduled amount,
    and returned and cancelled are zero."

    Design: Difficulty/compensating_invariant/aid_cents_conservation_on_return
    """
    ctx = _one_award_through_schedule_and_release()

    scheduled = ctx["scheduled"]
    A.assert_aid_disbursement(scheduled)
    assert scheduled["status"] == "SCHEDULED"
    A.assert_cents(scheduled["outstanding_amount_cents"], 200000, "outstanding")
    A.assert_cents(scheduled["retained_amount_cents"], 0, "retained")
    A.assert_cents(scheduled["returned_amount_cents"], 0, "returned")
    A.assert_cents(scheduled["cancelled_amount_cents"], 0, "cancelled")
    A.assert_aid_ledger_identity(scheduled)

    released = fx.disburse_aid(scheduled["id"])
    assert released["status"] == "DISBURSED"
    A.assert_cents(released["outstanding_amount_cents"], 0, "outstanding")
    A.assert_cents(released["retained_amount_cents"], 200000, "retained")
    A.assert_cents(released["returned_amount_cents"], 0, "returned")
    A.assert_cents(released["cancelled_amount_cents"], 0, "cancelled")
    A.assert_aid_ledger_identity(released)


def test_the_compensating_return_balances_and_the_students_liability_stays_outside_it():
    """The return moves 82874 cents out of the retained bucket and nowhere else, so
    the identity still totals the original 200000. The student's own 51186-cent
    liability is reported alongside and is deliberately not one of the four buckets.

    PRD: "The student's own share is reported as a liability but is not part of the
    institution's ledger — the school returns its share, and the student owes theirs."

    Design: Difficulty/compensating_invariant/aid_cents_conservation_on_return
    """
    ctx = _one_award_through_schedule_and_release()
    award = fx.disburse_aid(ctx["scheduled"]["id"])

    fx.set_clock(CLOSE_CLOCK_UTC)
    assert fx.close_term(ctx["term"]["id"], "LAPSED", CLOSE_CLOCK_UTC)["status"] == "LAPSED"

    returned = fx.return_aid(award["id"])
    assert returned["status"] == "RETURNED"
    A.assert_cents(returned["outstanding_amount_cents"], 0, "outstanding")
    A.assert_cents(returned["retained_amount_cents"], 117126, "retained")
    A.assert_cents(returned["returned_amount_cents"], 82874, "returned")
    A.assert_cents(returned["cancelled_amount_cents"], 0, "cancelled")
    A.assert_cents(returned["student_return_share_cents"], 51186, "student share")
    A.assert_aid_ledger_identity(returned)
    assert (
        returned["outstanding_amount_cents"] + returned["retained_amount_cents"]
        + returned["returned_amount_cents"] + returned["cancelled_amount_cents"]
        == 200000
    ), "the four buckets must still total the scheduled amount"

    summary = fx.progress_summary(ctx["student"]["id"])
    A.assert_cents(summary["aid_scheduled_total_cents"], 200000, "aid_scheduled_total")
    A.assert_cents(summary["aid_retained_total_cents"], 117126, "aid_retained_total")
    A.assert_cents(summary["aid_returned_total_cents"], 82874, "aid_returned_total")
