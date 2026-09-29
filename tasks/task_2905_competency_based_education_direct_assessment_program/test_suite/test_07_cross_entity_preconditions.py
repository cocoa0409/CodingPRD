"""One entity's write gated on another entity's state: the term's status gating an
attempt, and the student's progress axis gating the release of aid.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import BASE_CLOCK_UTC
from test_helpers.factories import create_attempt_payload, dimension_score
from test_helpers.test_users import make_student_headers


def test_an_attempt_is_refused_while_the_students_only_term_is_still_pending():
    """The attempt payload names nothing about the term, yet it is refused purely
    because the term the attempt would be booked against is not active yet.

    PRD: "The student holds a subscription term whose status is `ACTIVE` and whose
    half-open window from `term_start_utc` up to but excluding `term_end_utc`
    contains the logical clock, and that term is the one the operation is booked
    against — otherwise `ERR_TERM_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/attempt_creation_requires_active_term
    """
    ctx = fx.base_chain(with_blueprint=True, activate_the_term=False)
    assert ctx["term"]["status"] == "PENDING"

    response = api_client.create_attempt(
        create_attempt_payload(ctx["student"]["id"], ctx["competency"]["id"]),
        make_student_headers(ctx["student"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_TERM_NOT_ACTIVE.value, 409)

    A.assert_page(
        api_client.list_attempts(fx.REGISTRAR,
                                 params={"student_id": ctx["student"]["id"]}),
        0,
    )


def test_activating_that_other_row_makes_the_identical_attempt_payload_succeed():
    """Nothing about the attempt request changes — only the term's state — and the
    accepted attempt pins itself to that now-active term.

    PRD: "Its `term_id` is the student's `ACTIVE` subscription term whose half-open
    window contains the logical clock; when the student has no such term the request
    is refused with `ERR_TERM_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/attempt_creation_requires_active_term
    """
    ctx = fx.base_chain(with_blueprint=True, activate_the_term=False)
    payload = create_attempt_payload(ctx["student"]["id"], ctx["competency"]["id"])
    headers = make_student_headers(ctx["student"]["id"])
    validate_error(api_client.create_attempt(payload, headers),
                   ApiErrorId.ERR_TERM_NOT_ACTIVE.value, 409)

    activated = fx.activate_term(ctx["term"]["id"])
    assert activated["status"] == "ACTIVE"

    attempt = validate_success(api_client.create_attempt(payload, headers), 201)
    assert attempt["status"] == "DRAFT"
    assert attempt["attempt_number"] == 1
    assert attempt["term_id"] == ctx["term"]["id"]


def _student_on_probation_with_a_scheduled_award():
    """Two units of four expected, so the first checkpoint lands the student on
    PROBATION, with a scheduled award waiting on the active term."""
    fx.set_clock(BASE_CLOCK_UTC)
    program = fx.create_program(code="CBE-SAP", title="Applied Management",
                                sap_min_units_per_term=4, units_per_credit_hour=1.0,
                                aid_min_credit_equivalency=1)
    first = fx.create_competency(program["id"], code="SA-1",
                                 title="Operations Basics", unit_value=2,
                                 level="FOUNDATION")
    fx.create_blueprint(first, required_evaluator_count=1)
    second = fx.create_competency(program["id"], code="SA-2",
                                  title="Operations Practice", unit_value=2,
                                  level="CORE")
    fx.create_blueprint(second, required_evaluator_count=1)
    program = fx.publish_program(program["id"])
    student = fx.activate_student(fx.create_student(program["id"])["id"])
    term = fx.activate_term(fx.create_term(student["id"])["id"])
    evaluator = fx.create_evaluator()

    early = fx.open_attempt(student["id"], first["id"])
    fx.submit_attempt(early["id"], student["id"], artifact_hash="sha256:sa1-a")
    fx.record_score(early["id"], evaluator["id"], [dimension_score("D1", 95)])

    review = fx.create_sap_review(student["id"], term["id"])
    award = fx.schedule_aid(student["id"], fx.refresh_term(term["id"]))
    return {"program": program, "student": student, "term": term,
            "second": second, "evaluator": evaluator, "review": review,
            "award": award}


def test_releasing_aid_is_refused_while_the_students_progress_axis_says_probation():
    """The blocking state is not a lifecycle status but the progress axis, which
    only a checkpoint can move: at a 50.00 pace the release is refused.

    PRD: "The student's `sap_status` must be `GOOD_STANDING` or `WARNING`; a student
    on `PROBATION` or already `DISMISSED` is refused with `ERR_AID_SAP_INELIGIBLE`."

    Design: Difficulty/cross_entity_state_dependency/aid_disburse_requires_student_sap_state
    """
    ctx = _student_on_probation_with_a_scheduled_award()
    A.assert_number_equals(ctx["review"]["pace_pct"], 50.00, "pace_pct")
    assert ctx["review"]["pace_band"] == "PROB"
    assert ctx["review"]["new_sap_status"] == "PROBATION"
    assert ctx["award"]["status"] == "SCHEDULED"

    validate_error(api_client.disburse_aid(ctx["award"]["id"], fx.AID_OFFICER),
                   ApiErrorId.ERR_AID_SAP_INELIGIBLE.value, 422)

    award = fx.refresh_award(ctx["award"]["id"])
    assert award["status"] == "SCHEDULED"
    A.assert_cents(award["disbursed_amount_cents"], 0, "disbursed_amount_cents")


def test_one_good_checkpoint_restores_the_axis_and_the_same_release_succeeds():
    """Mastering the second competency lifts the pace to 100.00, one checkpoint
    returns the student straight to good standing, and the release then goes
    through, snapshotting the term's equivalency.

    PRD: "A successful release moves `status` to `DISBURSED`, sets
    `disbursed_amount_cents` to `scheduled_amount_cents`, drives
    `outstanding_amount_cents` to zero, sets `retained_amount_cents` to the full
    scheduled amount, clears `hold_reason` back to null, sets `disbursed_at_utc` to
    the logical clock, and captures `credit_equivalency_at_disbursement` as the
    term's `credit_equivalency_earned` at that exact moment."

    Design: Difficulty/cross_entity_state_dependency/aid_disburse_requires_student_sap_state
    """
    ctx = _student_on_probation_with_a_scheduled_award()

    later = fx.open_attempt(ctx["student"]["id"], ctx["second"]["id"])
    fx.submit_attempt(later["id"], ctx["student"]["id"], artifact_hash="sha256:sa2-a")
    fx.record_score(later["id"], ctx["evaluator"]["id"], [dimension_score("D1", 95)])

    recovery = fx.create_sap_review(ctx["student"]["id"], ctx["term"]["id"])
    A.assert_number_equals(recovery["pace_pct"], 100.00, "pace_pct")
    assert recovery["pace_band"] == "GOOD"
    assert recovery["previous_sap_status"] == "PROBATION"
    assert recovery["new_sap_status"] == "GOOD_STANDING"
    assert recovery["terms_counted"] == 1
    assert recovery["expected_units"] == 4

    term = fx.refresh_term(ctx["term"]["id"])
    assert term["credit_equivalency_earned"] == 4

    award = fx.disburse_aid(ctx["award"]["id"])
    assert award["status"] == "DISBURSED"
    assert award["credit_equivalency_at_disbursement"] == 4
    A.assert_cents(award["retained_amount_cents"], 200000, "retained_amount_cents")
    A.assert_cents(award["outstanding_amount_cents"], 0, "outstanding_amount_cents")
    A.assert_instant_equals(award["disbursed_at_utc"], BASE_CLOCK_UTC,
                            "disbursed_at_utc")
    A.assert_aid_ledger_identity(award)

    A.assert_cents(fx.refresh_student(ctx["student"]["id"])["aid_retained_total_cents"],
                   200000, "aid_retained_total_cents")
