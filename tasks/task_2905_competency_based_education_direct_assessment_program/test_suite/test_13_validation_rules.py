"""Cross-entity and aggregate validation rules: the prerequisite chain, the
one-score-per-reader rule, evaluator standing, the caseload cap, the endorsement
gate, and the precedence of the role check over body foreign keys.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import BASE_CLOCK_UTC
from test_helpers.factories import (
    create_aid_disbursement_payload,
    create_attempt_payload,
    create_mentor_assignment_payload,
    dimension_score,
    record_score_payload,
)
from test_helpers.test_users import make_evaluator_headers, make_student_headers

BOGUS_STUDENT_ID = "00000000-0000-4000-8000-000000000001"
BOGUS_TERM_ID = "00000000-0000-4000-8000-000000000002"


def _two_competency_ladder():
    """A published program whose IT-201 declares IT-101 as its prerequisite, both
    carrying a one-reader rubric, with an active student who has mastered nothing."""
    fx.set_clock(BASE_CLOCK_UTC)
    program = fx.create_program()
    foundation = fx.create_competency(program["id"], code="IT-101",
                                      title="Relational Data Modeling",
                                      unit_value=4, level="FOUNDATION")
    fx.create_blueprint(foundation, required_evaluator_count=1)
    dependent = fx.create_competency(program["id"], code="IT-201",
                                     title="Query Optimization",
                                     unit_value=4, level="CORE")
    fx.create_blueprint(dependent, required_evaluator_count=1)
    program = fx.publish_program(program["id"])
    dependent = fx.set_prerequisite(dependent["id"], foundation["id"])
    student = fx.activate_student(fx.create_student(program["id"])["id"])
    term = fx.activate_term(fx.create_term(student["id"])["id"])
    return {"program": program, "foundation": foundation, "dependent": dependent,
            "student": student, "term": term, "evaluator": fx.create_evaluator()}


def test_a_single_unmastered_ancestor_refuses_the_dependent_attempt():
    """IT-201 is itself perfectly attemptable, yet the chain is walked and the
    unmastered IT-101 refuses the request, leaving no attempt row behind.

    PRD: "The second rung enforces the map: every competency in the target's
    prerequisite chain, walked transitively all the way to its root, must already be
    mastered by this student, and a single unmastered ancestor anywhere in the chain
    refuses the attempt with `ERR_PREREQUISITE_NOT_MASTERED`."

    Design: Corner/validations/unmastered_prerequisite_blocks_the_attempt
    """
    ctx = _two_competency_ladder()
    assert ctx["dependent"]["prerequisite_competency_id"] == ctx["foundation"]["id"]
    assert fx.refresh_student(ctx["student"]["id"])["mastered_competency_count"] == 0

    response = api_client.create_attempt(
        create_attempt_payload(ctx["student"]["id"], ctx["dependent"]["id"]),
        make_student_headers(ctx["student"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_PREREQUISITE_NOT_MASTERED.value, 422)

    A.assert_page(
        api_client.list_attempts(fx.REGISTRAR,
                                 params={"student_id": ctx["student"]["id"]}),
        0,
    )


def test_mastering_the_ancestor_admits_the_dependent_attempt():
    """The identical request that was refused a moment ago is accepted once IT-101
    is mastered, and the dependent competency's own ordinal starts at one.

    PRD: "Every competency in the target competency's transitive prerequisite chain
    is already mastered by this student — otherwise `ERR_PREREQUISITE_NOT_MASTERED`.
    Applies to attempt creation."

    Design: Corner/validations/mastered_prerequisite_admits_the_attempt
    """
    ctx = _two_competency_ladder()

    first = fx.open_attempt(ctx["student"]["id"], ctx["foundation"]["id"])
    fx.submit_attempt(first["id"], ctx["student"]["id"],
                      artifact_hash="sha256:pre1", client_fingerprint="fp-pre-1")
    fx.record_score(first["id"], ctx["evaluator"]["id"],
                    [dimension_score("D1", 100)])
    assert fx.refresh_attempt(first["id"])["status"] == "SCORED_MASTERED"

    response = api_client.create_attempt(
        create_attempt_payload(ctx["student"]["id"], ctx["dependent"]["id"]),
        make_student_headers(ctx["student"]["id"]),
    )
    attempt = validate_success(response, 201)
    assert attempt["status"] == "DRAFT"
    assert attempt["attempt_number"] == 1
    assert attempt["competency_id"] == ctx["dependent"]["id"]


def test_the_first_reader_leaves_the_two_reader_attempt_provisional():
    """The control for the duplicate rule: reader one takes ordinal one and the
    attempt stays open on a provisional figure while the second slot is unfilled.

    PRD: "The attempt stays in `UNDER_REVIEW`, `final_score_pct` is written as
    reader one's figure, `is_provisional_score` is set to true, and
    `scores_received_count` becomes 1 — but no mastery outcome is recorded, no units
    are awarded, and no cascade fires."

    Design: Corner/validations/same_evaluator_cannot_score_an_attempt_twice
    """
    ctx = fx.two_reader_scenario()

    score = fx.record_score(ctx["attempt"]["id"], ctx["evaluator_one"]["id"],
                            [dimension_score("D1", 90)])
    assert score["reader_ordinal"] == 1

    attempt = fx.refresh_attempt(ctx["attempt"]["id"])
    assert attempt["status"] == "UNDER_REVIEW"
    assert attempt["scores_received_count"] == 1
    assert attempt["is_provisional_score"] is True
    A.assert_number_equals(attempt["final_score_pct"], 90.00, "final_score_pct")


def test_the_same_reader_cannot_fill_the_second_slot_as_well():
    """Reader one returning for the open second slot is refused, and the attempt is
    left with exactly the one score it already had.

    PRD: "The same evaluator may not score the same attempt twice, and the attempt
    may not collect more reader scores than the bound blueprint requires, on pain of
    `ERR_DUPLICATE_EVALUATOR_SCORE`."

    Design: Corner/validations/same_evaluator_cannot_score_an_attempt_twice
    """
    ctx = fx.two_reader_scenario()
    fx.record_score(ctx["attempt"]["id"], ctx["evaluator_one"]["id"],
                    [dimension_score("D1", 90)])

    response = api_client.record_score(
        ctx["attempt"]["id"],
        record_score_payload(ctx["evaluator_one"]["id"],
                             [dimension_score("D1", 90)]),
        make_evaluator_headers(ctx["evaluator_one"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_EVALUATOR_SCORE.value, 409)

    attempt = fx.refresh_attempt(ctx["attempt"]["id"])
    assert attempt["status"] == "UNDER_REVIEW"
    assert attempt["scores_received_count"] == 1
    assert attempt["is_provisional_score"] is True
    A.assert_number_equals(attempt["final_score_pct"], 90.00, "final_score_pct")
    A.assert_page(
        api_client.list_evaluator_scores(
            fx.REGISTRAR, params={"attempt_id": ctx["attempt"]["id"]}),
        1,
    )


def test_the_role_refusal_arrives_before_the_body_foreign_keys_are_resolved():
    """A candidate calling the aid desk with two invented foreign keys is told about
    the role, not about the missing rows, and no award is created for anyone.

    PRD: "The rejection a caller sees is always the violation with the lowest
    precedence number in the ordering below, and evaluation stops there."

    Design: Corner/validations/role_check_outranks_body_fk_existence
    """
    ctx = fx.base_chain(activate_the_term=False)
    assert ctx["term"]["version"] == 1

    response = api_client.create_aid_disbursement(
        create_aid_disbursement_payload(BOGUS_STUDENT_ID, BOGUS_TERM_ID,
                                        ctx["term"]["version"],
                                        scheduled_amount_cents=200000),
        make_student_headers(BOGUS_STUDENT_ID),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    A.assert_page(api_client.list_aid_disbursements(fx.AID_OFFICER), 0)


def _one_suspended_and_one_certified_reader():
    """An impeccable attempt under review, with reader one suspended by the platform
    administrator and reader two left certified."""
    ctx = fx.attempt_under_review(
        evaluator_overrides={"full_name": "Reader One", "email": "r1@example.edu"},
        submit_overrides={"artifact_hash": "sha256:susp1",
                          "client_fingerprint": "fp-susp-1"},
    )
    ctx["clean_reader"] = fx.create_evaluator(
        full_name="Reader Two", email="r2@example.edu",
        certification_level="SENIOR",
    )
    ctx["suspended_reader"] = fx.set_evaluator_status(ctx["evaluator"]["id"],
                                                      "SUSPENDED")
    return ctx


def test_a_suspended_reader_may_not_score_an_otherwise_perfect_attempt():
    """Nothing about the attempt has changed; validity hinges entirely on the other
    entity's standing, so the score is refused and no score row appears.

    PRD: "The reader's standing permits scoring, and the adjudication slot
    additionally requires a certified reader; a provisionally certified or suspended
    reader may not adjudicate — otherwise `ERR_EVALUATOR_NOT_CERTIFIED`. Applies to
    rubric scoring."

    Design: Corner/validations/suspended_evaluator_cannot_score
    """
    ctx = _one_suspended_and_one_certified_reader()
    assert ctx["suspended_reader"]["status"] == "SUSPENDED"

    response = api_client.record_score(
        ctx["attempt"]["id"],
        record_score_payload(ctx["suspended_reader"]["id"],
                             [dimension_score("D1", 95)]),
        make_evaluator_headers(ctx["suspended_reader"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_EVALUATOR_NOT_CERTIFIED.value, 422)

    attempt = fx.refresh_attempt(ctx["attempt"]["id"])
    assert attempt["status"] == "UNDER_REVIEW"
    assert attempt["scores_received_count"] == 0


def test_the_still_certified_reader_resolves_the_very_same_attempt():
    """The rule tracks the evaluator's own status rather than anything about the
    attempt: a certified reader takes the first ordinal and resolves it outright.

    PRD: "When the blueprint requires one reader, the sole score resolves the attempt
    immediately under `SINGLE_READER_FINAL`: `final_score_pct` is that reader's
    `weighted_score_pct` and `is_provisional_score` is false."

    Design: Corner/validations/suspended_evaluator_cannot_score
    """
    ctx = _one_suspended_and_one_certified_reader()

    score = fx.record_score(ctx["attempt"]["id"], ctx["clean_reader"]["id"],
                            [dimension_score("D1", 95)])
    A.assert_number_equals(score["weighted_score_pct"], 95.00, "weighted_score_pct")
    assert score["reader_ordinal"] == 1

    attempt = fx.refresh_attempt(ctx["attempt"]["id"])
    assert attempt["status"] == "SCORED_MASTERED"
    assert attempt["scores_received_count"] == 1
    assert attempt["is_provisional_score"] is False


def _mentor_with_a_single_slot_already_taken():
    """One active mentor whose cap is a single mentee, already paired with Ada,
    beside an equally eligible Ben who has no mentor at all."""
    fx.set_clock(BASE_CLOCK_UTC)
    program = fx.create_program()
    fx.create_competency(program["id"])
    program = fx.publish_program(program["id"])
    ada = fx.activate_student(fx.create_student(program["id"])["id"])
    ben = fx.activate_student(
        fx.create_student(program["id"], full_name="Ben Learner",
                          email="ben@example.edu")["id"]
    )
    mentor = fx.create_mentor(full_name="Mentor Solo", email="solo@example.edu",
                              max_caseload=1, cadence_days=7)
    assignment = fx.assign_mentor(ada, mentor["id"])
    return {"program": program, "ada": ada, "ben": ben,
            "mentor": fx.refresh_mentor(mentor["id"]), "assignment": assignment}


def test_the_second_individually_legal_pairing_breaches_the_collective_cap():
    """Ben's request is faultless in isolation; only the mentor's aggregate load
    refuses it, and the load is left exactly where it was.

    PRD: "When `mentor_id` is supplied the pairing is explicit and the resulting
    record has `selection_mode` `EXPLICIT`; the named mentor must be `ACTIVE` and must
    have a `current_caseload` strictly below their `max_caseload`, or the request is
    refused with `ERR_MENTOR_CASELOAD_FULL`."

    Design: Corner/validations/caseload_cap_is_an_aggregate_limit
    """
    ctx = _mentor_with_a_single_slot_already_taken()
    assert ctx["mentor"]["max_caseload"] == 1
    assert ctx["mentor"]["current_caseload"] == 1

    response = api_client.create_mentor_assignment(
        create_mentor_assignment_payload(ctx["ben"]["id"], ctx["ben"]["version"],
                                         mentor_id=ctx["mentor"]["id"]),
        fx.REGISTRAR,
    )
    validate_error(response, ApiErrorId.ERR_MENTOR_CASELOAD_FULL.value, 409)

    assert fx.refresh_mentor(ctx["mentor"]["id"])["current_caseload"] == 1


def test_the_refused_pairing_leaves_no_partially_created_assignment():
    """The refusal is total: Ben holds no assignment row at all, and Ada's remains
    the mentor's only active pairing.

    PRD: "An explicitly named mentor has spare caseload and is available — otherwise
    `ERR_MENTOR_CASELOAD_FULL`. Applies to mentor-assignment creation, and only when
    `mentor_id` is supplied."

    Design: Corner/validations/caseload_cap_is_an_aggregate_limit
    """
    ctx = _mentor_with_a_single_slot_already_taken()

    response = api_client.create_mentor_assignment(
        create_mentor_assignment_payload(ctx["ben"]["id"], ctx["ben"]["version"],
                                         mentor_id=ctx["mentor"]["id"]),
        fx.REGISTRAR,
    )
    validate_error(response, ApiErrorId.ERR_MENTOR_CASELOAD_FULL.value, 409)

    A.assert_page(
        api_client.list_mentor_assignments(fx.REGISTRAR,
                                           params={"student_id": ctx["ben"]["id"]}),
        0,
    )
    ada_rows = api_client.list_mentor_assignments(
        fx.REGISTRAR, params={"student_id": ctx["ada"]["id"], "status": "ACTIVE"})
    A.assert_page(ada_rows, 1)


def _one_failure_under_a_one_failure_threshold():
    """A program configured to demand faculty sign-off after a single failure, with
    the cool-off set to zero hours so it can never mask the endorsement gate, and one
    attempt already scored 40."""
    ctx = fx.assessment_ready(
        program_overrides={"code": "CBE-ENDORSE", "title": "Endorsement Program",
                           "attempts_before_endorsement": 1,
                           "attempt_cooloff_hours": 0},
        open_the_attempt=False,
    )
    ctx["mentor"] = fx.create_mentor(full_name="Mentor Meg", email="meg@example.edu",
                                     max_caseload=5, cadence_days=7)
    ctx["assignment"] = fx.assign_mentor(ctx["student"], ctx["mentor"]["id"])
    ctx["student"] = fx.refresh_student(ctx["student"]["id"])

    first = fx.open_attempt(ctx["student"]["id"], ctx["competency"]["id"])
    fx.submit_attempt(first["id"], ctx["student"]["id"],
                      artifact_hash="sha256:end1", client_fingerprint="fp-end-1")
    fx.record_score(first["id"], ctx["evaluator"]["id"], [dimension_score("D1", 40)])
    ctx["first_attempt"] = fx.refresh_attempt(first["id"])
    return ctx


def test_the_configured_failure_count_and_not_the_default_arms_the_gate():
    """This program asks for sign-off after one failure rather than three, so the
    very first retry is refused even though the cool-off has already elapsed.

    PRD: "The service counts the student's non-voided attempts on this competency
    whose status is `SCORED_NOT_MASTERED`; when that count has reached the program's
    `attempts_before_endorsement`, an unconsumed mentor endorsement for this
    student-and-competency pair is required, and without one the attempt is refused
    with `ERR_MENTOR_ENDORSEMENT_REQUIRED`."

    Design: Corner/validations/endorsement_rule_applies_only_past_the_configured_failure_count
    """
    ctx = _one_failure_under_a_one_failure_threshold()
    assert ctx["program"]["attempts_before_endorsement"] == 1
    assert ctx["first_attempt"]["status"] == "SCORED_NOT_MASTERED"
    A.assert_instant_equals(ctx["first_attempt"]["cooloff_until_utc"],
                            BASE_CLOCK_UTC, "cooloff_until_utc")
    assert ctx["assignment"]["endorsed_competency_ids"] == []

    response = api_client.create_attempt(
        create_attempt_payload(ctx["student"]["id"], ctx["competency"]["id"]),
        make_student_headers(ctx["student"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_MENTOR_ENDORSEMENT_REQUIRED.value, 422)

    A.assert_page(
        api_client.list_attempts(fx.REGISTRAR,
                                 params={"student_id": ctx["student"]["id"]}),
        1,
    )


def test_the_endorsement_admits_the_retry_and_is_consumed_by_it():
    """The identical request succeeds once the mentor signs off, and the sign-off is
    spent by the attempt it unlocked rather than left standing.

    PRD: "Creating the attempt consumes exactly one endorsement — it is removed from
    the assignment's `endorsed_competency_ids` and the attempt records
    `endorsement_consumed` as true — so the gate re-arms for the attempt after that."

    Design: Corner/validations/endorsement_rule_applies_only_past_the_configured_failure_count
    """
    ctx = _one_failure_under_a_one_failure_threshold()

    endorsed = fx.record_endorsement(ctx["assignment"]["id"], ctx["mentor"]["id"],
                                     ctx["competency"]["id"])
    assert endorsed["endorsement_count"] == 1
    assert endorsed["endorsed_competency_ids"] == [ctx["competency"]["id"]]

    response = api_client.create_attempt(
        create_attempt_payload(ctx["student"]["id"], ctx["competency"]["id"]),
        make_student_headers(ctx["student"]["id"]),
    )
    retry = validate_success(response, 201)
    assert retry["status"] == "DRAFT"
    assert retry["attempt_number"] == 2
    assert retry["endorsement_consumed"] is True

    assignment = fx.refresh_assignment(ctx["assignment"]["id"])
    assert assignment["endorsed_competency_ids"] == []
    assert assignment["endorsement_count"] == 1
