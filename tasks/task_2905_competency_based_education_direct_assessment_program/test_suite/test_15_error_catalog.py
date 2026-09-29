"""Error-family sweeps: the fourteen distinct 404s, the authentication and role
guards, the four-way state guards on students, attempts, integrity cases,
transcripts and aid, the graph guards, the rubric guard, the two capacity codes,
and the terminal evaluator standing.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import BASE_CLOCK_UTC, PHANTOM_UUID
from test_helpers.factories import (
    create_blueprint_payload,
    create_mentor_assignment_payload,
    create_program_payload,
    create_subscription_term_payload,
    dimension_score,
    rubric_dimension,
    submit_attempt_payload,
)
from test_helpers.test_users import (
    NO_HEADERS,
    blank_identity_headers,
    make_integrity_officer_headers,
    make_student_headers,
)


def test_every_path_prefix_answers_with_its_own_distinct_not_found_code():
    """The same well-formed but unknown uuid is asked of all fourteen collections, and
    each answers with the 404 belonging to the entity that segment addresses.

    PRD: "Path identifiers are resolved left to right, and each unresolved identifier
    yields the 404 error belonging to the entity that segment addresses:
    `ERR_PROGRAM_NOT_FOUND`, `ERR_COMPETENCY_NOT_FOUND`, `ERR_BLUEPRINT_NOT_FOUND`,
    `ERR_STUDENT_NOT_FOUND`, `ERR_TERM_NOT_FOUND`, `ERR_MENTOR_NOT_FOUND`,
    `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_EVALUATOR_NOT_FOUND`, `ERR_ATTEMPT_NOT_FOUND`,
    `ERR_SCORE_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_SAP_REVIEW_NOT_FOUND`,
    `ERR_DISBURSEMENT_NOT_FOUND`, and `ERR_TRANSCRIPT_NOT_FOUND`."

    Design: Corner/errors/every_entity_id_has_its_own_not_found_error
    """
    fx.set_clock(BASE_CLOCK_UTC)
    reads = [
        (api_client.get_program, ApiErrorId.ERR_PROGRAM_NOT_FOUND),
        (api_client.get_competency, ApiErrorId.ERR_COMPETENCY_NOT_FOUND),
        (api_client.get_blueprint, ApiErrorId.ERR_BLUEPRINT_NOT_FOUND),
        (api_client.get_student, ApiErrorId.ERR_STUDENT_NOT_FOUND),
        (api_client.get_subscription_term, ApiErrorId.ERR_TERM_NOT_FOUND),
        (api_client.get_mentor, ApiErrorId.ERR_MENTOR_NOT_FOUND),
        (api_client.get_mentor_assignment, ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND),
        (api_client.get_evaluator, ApiErrorId.ERR_EVALUATOR_NOT_FOUND),
        (api_client.get_attempt, ApiErrorId.ERR_ATTEMPT_NOT_FOUND),
        (api_client.get_evaluator_score, ApiErrorId.ERR_SCORE_NOT_FOUND),
        (api_client.get_integrity_case, ApiErrorId.ERR_CASE_NOT_FOUND),
        (api_client.get_sap_review, ApiErrorId.ERR_SAP_REVIEW_NOT_FOUND),
        (api_client.get_aid_disbursement, ApiErrorId.ERR_DISBURSEMENT_NOT_FOUND),
        (api_client.get_transcript_record, ApiErrorId.ERR_TRANSCRIPT_NOT_FOUND),
    ]
    seen = []
    for read, expected in reads:
        error = validate_error(read(PHANTOM_UUID, fx.REGISTRAR), expected.value, 404)
        seen.append(error["error_id"])

    assert len(set(seen)) == 14, "the fourteen 404 codes must be pairwise distinct"


def test_absent_and_blank_identity_are_both_unauthenticated():
    """A missing header and a present-but-blank header are the same thing, and the
    refusal arrives before the path id is ever resolved.

    PRD: "Both authentication headers are present and non-empty, treating a blank or
    whitespace-only value as absent — otherwise `ERR_UNAUTHENTICATED`. Applies to every
    endpoint."

    Design: Corner/errors/blank_identity_headers_are_unauthenticated_before_role_check
    """
    fx.set_clock(BASE_CLOCK_UTC)
    program = fx.create_program()

    validate_error(api_client.get_program(program["id"], NO_HEADERS),
                   ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    validate_error(api_client.get_program(program["id"], blank_identity_headers()),
                   ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    validate_error(api_client.get_program(PHANTOM_UUID, blank_identity_headers()),
                   ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    assert fx.refresh_program(program["id"])["status"] == "DRAFT"


def test_a_complete_but_unpermitted_role_is_forbidden_rather_than_unauthenticated():
    """Identity is impeccable here; only the role is wrong, so the refusal moves from
    401 to 403 and still leaves the program untouched.

    PRD: "`X-User-Role` names one of the seven declared roles and that role is
    authorized for the target endpoint — otherwise `ERR_FORBIDDEN_ROLE`. Applies to
    every endpoint."

    Design: Corner/errors/blank_identity_headers_are_unauthenticated_before_role_check
    """
    fx.set_clock(BASE_CLOCK_UTC)
    program = fx.create_program()

    response = api_client.publish_program(program["id"],
                                          make_student_headers("student-9"))
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    unchanged = fx.refresh_program(program["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["published_at_utc"] is None
    assert unchanged["version"] == 1


def _three_students_on_three_enrollment_states():
    """Ada active, Bob withdrawn and Cid still an applicant, all in one published
    program."""
    fx.set_clock(BASE_CLOCK_UTC)
    program = fx.create_program()
    fx.create_competency(program["id"])
    program = fx.publish_program(program["id"])
    active = fx.activate_student(fx.create_student(program["id"])["id"])
    bob = fx.activate_student(
        fx.create_student(program["id"], full_name="Bob Leaver",
                          email="bob@example.edu")["id"])
    withdrawn = fx.withdraw_student(bob["id"], BASE_CLOCK_UTC)
    applicant = fx.create_student(program["id"], full_name="Cid Applicant",
                                 email="cid@example.edu")
    return {"program": program, "active": active, "withdrawn": withdrawn,
            "applicant": applicant}


def test_three_wrong_state_moves_on_the_enrollment_axis_report_three_codes():
    """Re-activating, reinstating and suspending each fail for a different reason, and
    the codes are not collapsed into one generic conflict.

    PRD: "Activation needs an applicant student, or else `ERR_STUDENT_NOT_APPLICANT`.
    Reinstatement needs a suspended student, or else `ERR_STUDENT_NOT_SUSPENDED`.
    Withdrawal and suspension need a student who has not reached a terminal enrollment
    state, or else `ERR_STUDENT_ALREADY_CLOSED`."

    Design: Corner/errors/student_lifecycle_guards_return_four_distinct_state_errors
    """
    ctx = _three_students_on_three_enrollment_states()
    assert ctx["withdrawn"]["enrollment_status"] == "WITHDRAWN"

    validate_error(
        api_client.activate_student(ctx["active"]["id"], fx.REGISTRAR),
        ApiErrorId.ERR_STUDENT_NOT_APPLICANT.value, 409)
    validate_error(
        api_client.reinstate_student(ctx["active"]["id"], fx.REGISTRAR),
        ApiErrorId.ERR_STUDENT_NOT_SUSPENDED.value, 409)
    validate_error(
        api_client.suspend_student(ctx["withdrawn"]["id"], fx.REGISTRAR,
                                   {"reason": "integrity"}),
        ApiErrorId.ERR_STUDENT_ALREADY_CLOSED.value, 409)

    still_active = fx.refresh_student(ctx["active"]["id"])
    assert still_active["enrollment_status"] == "ACTIVE"
    assert still_active["version"] == ctx["active"]["version"]


def test_opening_a_term_for_an_applicant_reports_the_fourth_code():
    """The same axis refuses a different operation with a different code, and no term
    row is left behind.

    PRD: "The subject student's `enrollment_status` is `ACTIVE` — otherwise
    `ERR_STUDENT_NOT_ACTIVE`. Applies to five operations: opening a subscription term,
    creating a mentor assignment, opening an assessment attempt, scheduling an aid
    disbursement, and releasing an aid disbursement."

    Design: Corner/errors/student_lifecycle_guards_return_four_distinct_state_errors
    """
    ctx = _three_students_on_three_enrollment_states()
    assert ctx["applicant"]["enrollment_status"] == "APPLICANT"

    response = api_client.create_subscription_term(
        create_subscription_term_payload(ctx["applicant"]["id"]), fx.REGISTRAR)
    validate_error(response, ApiErrorId.ERR_STUDENT_NOT_ACTIVE.value, 409)

    A.assert_page(
        api_client.list_subscription_terms(
            fx.REGISTRAR, params={"student_id": ctx["applicant"]["id"]}),
        0,
    )


def test_the_three_attempt_write_guards_are_multiplexed_by_operation():
    """A single draft attempt refuses three different writes with three different
    codes, chosen by the operation rather than by the status alone.

    PRD: "The assessment attempt occupies the status its operation requires: draft to
    submit, or else `ERR_ATTEMPT_NOT_DRAFT`; under review or in adjudication to accept a
    rubric score, and under review or in adjudication to accept a revision request, or
    else `ERR_ATTEMPT_NOT_UNDER_REVIEW`; revision-requested to reopen, or else
    `ERR_ATTEMPT_NOT_IN_REVISION`."

    Design: Corner/errors/attempt_write_guards_return_four_distinct_state_errors
    """
    ctx = fx.assessment_ready()
    assert ctx["attempt"]["status"] == "DRAFT"

    validate_error(
        api_client.request_revision(ctx["attempt"]["id"],
                                   {"reason": "Artifact missing a section"},
                                   fx.REGISTRAR),
        ApiErrorId.ERR_ATTEMPT_NOT_UNDER_REVIEW.value, 409)
    validate_error(
        api_client.reopen_attempt(ctx["attempt"]["id"], fx.REGISTRAR),
        ApiErrorId.ERR_ATTEMPT_NOT_IN_REVISION.value, 409)

    submitted = fx.submit_attempt(ctx["attempt"]["id"], ctx["student"]["id"])
    assert submitted["status"] == "UNDER_REVIEW"

    validate_error(
        api_client.submit_attempt(ctx["attempt"]["id"], submit_attempt_payload(),
                                  make_student_headers(ctx["student"]["id"])),
        ApiErrorId.ERR_ATTEMPT_NOT_DRAFT.value, 409)


def test_the_voided_state_overrides_whichever_write_guard_would_have_answered():
    """Once the sanction has voided the attempt, the resubmission no longer reports a
    status mismatch but the terminal void itself.

    PRD: "Any write against an attempt already in the terminal voided state is refused
    with `ERR_ATTEMPT_VOIDED`."

    Design: Corner/errors/attempt_write_guards_return_four_distinct_state_errors
    """
    ctx = fx.held_attempt_scenario()
    fx.investigate_case(ctx["case"]["id"])
    fx.resolve_case(ctx["case"]["id"], "SUBSTANTIATED", sanction="ATTEMPT_VOID")

    voided = fx.refresh_attempt(ctx["attempt"]["id"])
    assert voided["status"] == "VOIDED"

    validate_error(
        api_client.submit_attempt(ctx["attempt"]["id"], submit_attempt_payload(),
                                  make_student_headers(ctx["student"]["id"])),
        ApiErrorId.ERR_ATTEMPT_VOIDED.value, 409)


def test_resolving_a_case_that_was_never_investigated_is_refused():
    """The ladder may not be short-circuited, and while the case sits open the hold has
    teeth against any new attempt for that student.

    PRD: "Resolution acts only on a case in `UNDER_INVESTIGATION` — resolving a case
    still sitting in `OPEN` is refused with `ERR_CASE_NOT_UNDER_INVESTIGATION` and
    resolving an already-terminal case with `ERR_CASE_ALREADY_RESOLVED`."

    Design: Corner/errors/integrity_case_guards_separate_open_from_resolved
    """
    ctx = fx.held_attempt_scenario(opener_user_id="officer-open")
    assert ctx["case"]["status"] == "OPEN"
    assert ctx["case"]["opened_by_user_id"] == "officer-open"

    validate_error(
        api_client.resolve_case(ctx["case"]["id"],
                                {"outcome": "DISMISSED", "sanction": "NONE"},
                                fx.INTEGRITY_OFFICER),
        ApiErrorId.ERR_CASE_NOT_UNDER_INVESTIGATION.value, 409)

    validate_error(
        api_client.create_attempt(
            {"student_id": ctx["student"]["id"],
             "competency_id": ctx["competency"]["id"]},
            make_student_headers(ctx["student"]["id"])),
        ApiErrorId.ERR_INTEGRITY_HOLD_ACTIVE.value, 409)


def test_the_officer_who_opened_the_case_may_not_also_resolve_it():
    """Segregation of duties is a 422 about the actor, not a 403 about the role: the
    same officer holds the right role and still cannot adjudicate their own accusation.

    PRD: "Segregation of duties is enforced here as strictly as it is at scoring time:
    the identity of the resolving officer must differ from the case's
    `opened_by_user_id`, or the request is refused with `ERR_CASE_RESOLVER_IS_OPENER`."

    Design: Corner/errors/integrity_case_guards_separate_open_from_resolved
    """
    ctx = fx.held_attempt_scenario(opener_user_id="officer-open")
    investigated = fx.investigate_case(ctx["case"]["id"], "officer-open")
    assert investigated["status"] == "UNDER_INVESTIGATION"

    # The resolving identity must be the case's own `opened_by_user_id` for the
    # segregation-of-duties refusal to be the rule under test.
    response = api_client.resolve_case(
        ctx["case"]["id"], {"outcome": "DISMISSED", "sanction": "NONE"},
        make_integrity_officer_headers("officer-open"))
    validate_error(response, ApiErrorId.ERR_CASE_RESOLVER_IS_OPENER.value, 422)

    assert fx.refresh_case(ctx["case"]["id"])["status"] == "UNDER_INVESTIGATION"


def test_a_resolved_case_refuses_both_the_investigate_and_the_resolve_step():
    """Dismissal is terminal, so a late sanction attempt cannot reach back and void the
    attempt the case had held.

    PRD: "The integrity case occupies the status its operation requires: open to begin
    investigating, or else `ERR_CASE_ALREADY_RESOLVED`; under investigation to resolve,
    where a still-open case yields `ERR_CASE_NOT_UNDER_INVESTIGATION` and an
    already-resolved case yields `ERR_CASE_ALREADY_RESOLVED`."

    Design: Corner/errors/integrity_case_guards_separate_open_from_resolved
    """
    ctx = fx.held_attempt_scenario(opener_user_id="officer-open")
    fx.investigate_case(ctx["case"]["id"], "officer-open")
    resolved = fx.resolve_case(ctx["case"]["id"], "DISMISSED",
                               resolver_user_id="officer-other")
    assert resolved["status"] == "DISMISSED"
    assert resolved["resolved_by_user_id"] == "officer-other"

    validate_error(
        api_client.investigate_case(ctx["case"]["id"], fx.INTEGRITY_OFFICER),
        ApiErrorId.ERR_CASE_ALREADY_RESOLVED.value, 409)
    validate_error(
        api_client.resolve_case(ctx["case"]["id"],
                                {"outcome": "SUBSTANTIATED",
                                 "sanction": "ATTEMPT_VOID"},
                                fx.INTEGRITY_OFFICER),
        ApiErrorId.ERR_CASE_ALREADY_RESOLVED.value, 409)

    attempt = fx.refresh_attempt(ctx["attempt"]["id"])
    assert attempt["status"] == "UNDER_REVIEW"
    assert attempt["integrity_hold"] is False


def test_the_transcript_cannot_be_issued_while_any_integrity_matter_is_open():
    """The open case sits on an attempt rather than on the record, and it still blocks
    issuance until it is dismissed — after which the very same call succeeds.

    PRD: "No integrity case for the subject student is open or under investigation,
    because a transcript may not be issued while an integrity matter is unresolved —
    otherwise `ERR_TRANSCRIPT_INTEGRITY_PENDING`. Applies to transcript issuance."

    Design: Corner/errors/transcript_issue_guards_cover_pending_integrity_and_reissue
    """
    ctx = fx.held_attempt_scenario(opener_user_id="officer-open")
    record = fx.create_transcript(ctx["student"]["id"])
    assert record["status"] == "DRAFT"
    assert record["competency_line_count"] == 0

    validate_error(
        api_client.issue_transcript_record(record["id"], fx.REGISTRAR),
        ApiErrorId.ERR_TRANSCRIPT_INTEGRITY_PENDING.value, 422)

    fx.investigate_case(ctx["case"]["id"], "officer-open")
    fx.resolve_case(ctx["case"]["id"], "DISMISSED", resolver_user_id="officer-other")

    issued = validate_success(
        api_client.issue_transcript_record(record["id"], fx.REGISTRAR))
    assert issued["status"] == "ISSUED"
    A.assert_instant_equals(issued["issued_at_utc"], BASE_CLOCK_UTC, "issued_at_utc")
    assert issued["version"] == 2


def test_reissuing_an_already_issued_record_reports_a_different_code():
    """The reissue refusal is a 409 about the record's own status, distinct from the 422
    the integrity matter produced.

    PRD: "The transcript record is still a draft; an already-issued record yields
    `ERR_TRANSCRIPT_ALREADY_ISSUED`. Applies to transcript issuance."

    Design: Corner/errors/transcript_issue_guards_cover_pending_integrity_and_reissue
    """
    ctx = fx.base_chain()
    record = fx.issue_transcript(fx.create_transcript(ctx["student"]["id"])["id"])
    assert record["status"] == "ISSUED"
    assert record["version"] == 2

    validate_error(
        api_client.issue_transcript_record(record["id"], fx.REGISTRAR),
        ApiErrorId.ERR_TRANSCRIPT_ALREADY_ISSUED.value, 409)

    final = fx.refresh_transcript(record["id"])
    assert final["status"] == "ISSUED"
    assert final["version"] == 2


def test_aid_cannot_be_released_on_a_term_that_earned_no_whole_credit_hour():
    """Every other precondition is satisfied — active student, active term, good
    standing — and the release still fails on the credit-hour floor alone.

    PRD: "The term's `credit_equivalency_earned` is at least the program's
    `aid_min_credit_equivalency` — otherwise `ERR_AID_CREDIT_EQUIVALENCY_SHORTFALL`.
    Applies to aid release."

    Design: Corner/errors/aid_shortfall_and_cancelled_award_guards
    """
    ctx = fx.scheduled_aid_scenario()
    assert ctx["program"]["aid_min_credit_equivalency"] == 1
    assert ctx["student"]["enrollment_status"] == "ACTIVE"
    assert ctx["student"]["sap_status"] == "GOOD_STANDING"
    assert ctx["term"]["status"] == "ACTIVE"
    assert ctx["term"]["credit_equivalency_earned"] == 0

    response = api_client.disburse_aid(ctx["award"]["id"], fx.AID_OFFICER)
    validate_error(response,
                   ApiErrorId.ERR_AID_CREDIT_EQUIVALENCY_SHORTFALL.value, 422)

    assert fx.refresh_award(ctx["award"]["id"])["status"] == "SCHEDULED"


def test_a_cancelled_award_refuses_both_release_and_a_second_cancellation():
    """Cancellation is terminal for the award, and the same two calls that were live a
    moment ago now report the status code instead.

    PRD: "Releasing an award that is already disbursed yields
    `ERR_AID_ALREADY_DISBURSED`; releasing or cancelling one that is returned or
    cancelled yields `ERR_DISBURSEMENT_NOT_SCHEDULED`; returning one that is not
    disbursed yields `ERR_AID_NOT_DISBURSED`."

    Design: Corner/errors/aid_shortfall_and_cancelled_award_guards
    """
    ctx = fx.scheduled_aid_scenario()
    cancelled = fx.cancel_aid(ctx["award"]["id"])
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancelled_amount_cents"] == 200000
    assert cancelled["outstanding_amount_cents"] == 0

    validate_error(api_client.disburse_aid(ctx["award"]["id"], fx.AID_OFFICER),
                   ApiErrorId.ERR_DISBURSEMENT_NOT_SCHEDULED.value, 409)
    validate_error(api_client.cancel_aid(ctx["award"]["id"], fx.AID_OFFICER),
                   ApiErrorId.ERR_DISBURSEMENT_NOT_SCHEDULED.value, 409)

    student = fx.refresh_student(ctx["student"]["id"])
    assert student["aid_scheduled_total_cents"] == 200000
    assert student["aid_retained_total_cents"] == 0


def test_the_mastered_competency_refuses_a_further_attempt():
    """One mastery closes the competency: the units land, the term earns its whole
    credit hour, and the rung-one guard turns the retry away.

    PRD: "The student has not already mastered this competency — otherwise
    `ERR_COMPETENCY_ALREADY_MASTERED`. Applies to attempt creation."

    Design: Corner/errors/mastery_then_duplicate_operations_are_refused
    """
    ctx = fx.scored_attempt(score=90)
    assert ctx["attempt"]["status"] == "SCORED_MASTERED"
    A.assert_number_equals(ctx["attempt"]["final_score_pct"], 90.00,
                           "final_score_pct")
    assert ctx["student"]["mastered_unit_total"] == 4
    A.assert_number_equals(ctx["student"]["cumulative_credit_equivalency"], 1.3,
                           "cumulative_credit_equivalency")
    assert ctx["term"]["credit_equivalency_earned"] == 1

    response = api_client.create_attempt(
        {"student_id": ctx["student"]["id"],
         "competency_id": ctx["competency"]["id"]},
        make_student_headers(ctx["student"]["id"]))
    validate_error(response, ApiErrorId.ERR_COMPETENCY_ALREADY_MASTERED.value, 409)


def test_the_released_award_refuses_a_second_release_and_keeps_its_ledger():
    """That same mastery clears the credit-hour floor exactly, so the release succeeds
    once and only once.

    PRD: "The award must be `SCHEDULED` or `HELD`; an award already released is refused
    with `ERR_AID_ALREADY_DISBURSED`, and one that is `RETURNED` or `CANCELLED` with
    `ERR_DISBURSEMENT_NOT_SCHEDULED`."

    Design: Corner/errors/mastery_then_duplicate_operations_are_refused
    """
    ctx = fx.mastery_then_aid_scenario(score=90)
    assert ctx["term"]["credit_equivalency_earned"] == 1

    released = fx.disburse_aid(ctx["award"]["id"])
    assert released["status"] == "DISBURSED"
    assert released["disbursed_amount_cents"] == 200000
    assert released["outstanding_amount_cents"] == 0
    assert released["retained_amount_cents"] == 200000

    validate_error(api_client.disburse_aid(ctx["award"]["id"], fx.AID_OFFICER),
                   ApiErrorId.ERR_AID_ALREADY_DISBURSED.value, 409)

    after = fx.refresh_award(ctx["award"]["id"])
    assert after["outstanding_amount_cents"] == 0
    assert after["retained_amount_cents"] == 200000
    A.assert_aid_ledger_identity(after)


def _two_published_maps_in_two_programs():
    """IT-101 and IT-201 in one published program, EE-101 in another, none linked."""
    fx.set_clock(BASE_CLOCK_UTC)
    first = fx.create_program()
    foundation = fx.create_competency(first["id"], code="IT-101",
                                      title="Relational Data Modeling",
                                      unit_value=4, level="FOUNDATION")
    dependent = fx.create_competency(first["id"], code="IT-201",
                                     title="Query Optimization",
                                     unit_value=4, level="CORE")
    first = fx.publish_program(first["id"])
    second = fx.create_program(code="CBE-BSEE", title="BS Electrical Engineering")
    foreign = fx.create_competency(second["id"], code="EE-101",
                                   title="Circuit Analysis",
                                   unit_value=4, level="FOUNDATION")
    second = fx.publish_program(second["id"])
    return {"foundation": foundation, "dependent": dependent, "foreign": foreign}


def test_a_prerequisite_from_another_program_is_a_mismatch_not_a_cycle():
    """The graph is program-local, and the locality check runs before any cycle
    reasoning happens.

    PRD: "A prerequisite must belong to the same program as the competency depending on
    it, or the request is refused with `ERR_PREREQUISITE_PROGRAM_MISMATCH`."

    Design: Corner/errors/prerequisite_edge_rejects_cross_program_and_cycle
    """
    ctx = _two_published_maps_in_two_programs()

    response = api_client.set_competency_prerequisite(
        ctx["dependent"]["id"],
        {"prerequisite_competency_id": ctx["foreign"]["id"]},
        fx.REGISTRAR,
    )
    validate_error(response, ApiErrorId.ERR_PREREQUISITE_PROGRAM_MISMATCH.value, 422)

    unchanged = fx.refresh_competency(ctx["dependent"]["id"])
    assert unchanged["prerequisite_competency_id"] is None
    assert unchanged["version"] == 1


def test_both_the_self_edge_and_the_two_hop_loop_are_cycles():
    """The degenerate self-edge and the longer loop that only becomes reachable after a
    legal edge exists are both refused with the same code.

    PRD: "And the new edge must not close a cycle — neither the degenerate case of a
    competency naming itself, nor a longer loop reachable by walking the chain
    transitively — or the request is refused with `ERR_PREREQUISITE_CYCLE`."

    Design: Corner/errors/prerequisite_edge_rejects_cross_program_and_cycle
    """
    ctx = _two_published_maps_in_two_programs()

    validate_error(
        api_client.set_competency_prerequisite(
            ctx["foundation"]["id"],
            {"prerequisite_competency_id": ctx["foundation"]["id"]}, fx.REGISTRAR),
        ApiErrorId.ERR_PREREQUISITE_CYCLE.value, 422)

    linked = fx.set_prerequisite(ctx["dependent"]["id"], ctx["foundation"]["id"])
    assert linked["prerequisite_competency_id"] == ctx["foundation"]["id"]
    assert linked["prerequisite_depth"] == 1

    validate_error(
        api_client.set_competency_prerequisite(
            ctx["foundation"]["id"],
            {"prerequisite_competency_id": ctx["dependent"]["id"]}, fx.REGISTRAR),
        ApiErrorId.ERR_PREREQUISITE_CYCLE.value, 422)

    root = fx.refresh_competency(ctx["foundation"]["id"])
    assert root["prerequisite_competency_id"] is None
    assert root["prerequisite_depth"] == 0
    assert root["version"] == 1


MALFORMED_RUBRICS = [
    [rubric_dimension("D1", 0.5000, 100), rubric_dimension("D2", 0.4000, 100)],
    [rubric_dimension("D1", 1.0000, 100), rubric_dimension("D2", 0.0000, 100)],
    [rubric_dimension("D1", 1.0000, 0)],
    [rubric_dimension("D1", 0.5000, 100),
     rubric_dimension("D1", 0.5000, 100, True)],
]

WELL_FORMED_RUBRIC = [
    rubric_dimension("D1", 0.6000, 100),
    rubric_dimension("D2", 0.4000, 50, True),
]


def _competency_awaiting_its_first_rubric():
    fx.set_clock(BASE_CLOCK_UTC)
    program = fx.create_program()
    competency = fx.create_competency(program["id"])
    fx.publish_program(program["id"])
    assert competency["effective_blueprint_id"] is None
    return competency


def _reject_every_malformed_rubric(competency):
    for dimensions in MALFORMED_RUBRICS:
        response = api_client.create_blueprint(
            create_blueprint_payload(competency["id"], competency["version"],
                                     dimensions=dimensions),
            fx.REGISTRAR,
        )
        validate_error(response, ApiErrorId.ERR_RUBRIC_WEIGHTS_INVALID.value, 422)


def test_one_code_covers_every_malformed_weight_set():
    """A short sum, a zero weight, a non-positive ceiling and a duplicate code are four
    different defects reported under one code, and none of them touches the competency.

    PRD: "The blueprint's rubric dimension weights sum to exactly one, every weight is
    greater than zero, every `max_score` is a positive integer, dimension codes are
    unique, and at least one dimension exists — otherwise `ERR_RUBRIC_WEIGHTS_INVALID`.
    Applies to blueprint publication."

    Design: Corner/errors/blueprint_rejects_every_malformed_weight_set
    """
    competency = _competency_awaiting_its_first_rubric()
    _reject_every_malformed_rubric(competency)

    untouched = fx.refresh_competency(competency["id"])
    assert untouched["version"] == 1
    assert untouched["effective_blueprint_id"] is None
    A.assert_page(
        api_client.list_blueprints(fx.REGISTRAR,
                                  params={"competency_id": competency["id"]}),
        0,
    )


def test_the_rejections_leave_the_first_ordinal_free_for_a_valid_rubric():
    """Because no row was ever written, the first rubric that does satisfy the rule
    still binds as the competency's first blueprint.

    PRD: "It also carries a human-readable `version_label` of the form `BP-` followed by
    a number, where the number is the one-based ordinal of this blueprint among the
    blueprints of the same competency when they are ordered by `effective_from_utc`
    ascending with `created_at` ascending as the tie-break."

    Design: Corner/errors/blueprint_rejects_every_malformed_weight_set
    """
    competency = _competency_awaiting_its_first_rubric()
    _reject_every_malformed_rubric(competency)

    response = api_client.create_blueprint(
        create_blueprint_payload(competency["id"], competency["version"],
                                 dimensions=WELL_FORMED_RUBRIC),
        fx.REGISTRAR,
    )
    blueprint = validate_success(response, 201)
    assert blueprint["version_label"] == "BP-1"
    assert blueprint["dimension_count"] == 2
    assert blueprint["status"] == "PUBLISHED"

    A.assert_page(
        api_client.list_blueprints(fx.REGISTRAR,
                                  params={"competency_id": competency["id"]}),
        1,
    )


def _one_full_mentor_beside_one_on_leave():
    """Alpha at her ceiling of one with Ada already assigned, Beta idle but ON_LEAVE, and
    Ben waiting for a coach."""
    fx.set_clock(BASE_CLOCK_UTC)
    program = fx.create_program()
    fx.create_competency(program["id"])
    program = fx.publish_program(program["id"])
    ada = fx.activate_student(fx.create_student(program["id"])["id"])
    ben = fx.activate_student(
        fx.create_student(program["id"], full_name="Ben Learner",
                          email="ben@example.edu")["id"])
    alpha = fx.create_mentor(full_name="Mentor Alpha", email="alpha@example.edu",
                             max_caseload=1, cadence_days=14)
    beta = fx.create_mentor(full_name="Mentor Beta", email="beta@example.edu",
                            max_caseload=1, cadence_days=14)
    fx.set_mentor_status(beta["id"], "ON_LEAVE")
    fx.assign_mentor(ada, alpha["id"])
    return {"ada": ada, "ben": ben, "alpha": fx.refresh_mentor(alpha["id"]),
            "beta": fx.refresh_mentor(beta["id"])}


def test_naming_a_full_mentor_and_naming_an_unavailable_one_report_the_same_code():
    """The explicit path reports a conflict against the specific mentor named, whether
    the obstacle is the ceiling or the availability.

    PRD: "An explicitly named mentor has spare caseload and is available — otherwise
    `ERR_MENTOR_CASELOAD_FULL`. Applies to mentor-assignment creation, and only when
    `mentor_id` is supplied."

    Design: Corner/errors/caseload_exhaustion_splits_named_from_automatic_selection
    """
    ctx = _one_full_mentor_beside_one_on_leave()
    assert ctx["alpha"]["current_caseload"] == 1
    assert ctx["beta"]["status"] == "ON_LEAVE"
    assert ctx["beta"]["current_caseload"] == 0

    validate_error(
        api_client.create_mentor_assignment(
            create_mentor_assignment_payload(ctx["ben"]["id"], ctx["ben"]["version"],
                                             mentor_id=ctx["alpha"]["id"]),
            fx.REGISTRAR),
        ApiErrorId.ERR_MENTOR_CASELOAD_FULL.value, 409)
    validate_error(
        api_client.create_mentor_assignment(
            create_mentor_assignment_payload(ctx["ben"]["id"], ctx["ben"]["version"],
                                             mentor_id=ctx["beta"]["id"]),
            fx.REGISTRAR),
        ApiErrorId.ERR_MENTOR_CASELOAD_FULL.value, 409)


def test_letting_the_selector_run_dry_reports_the_other_code():
    """The identical shortage reached through automatic selection is an unprocessable
    request rather than a conflict, and no assignment appears.

    PRD: "When `mentor_id` is omitted, automatic selection finds at least one eligible
    mentor — otherwise `ERR_NO_ELIGIBLE_MENTOR`. Applies to mentor-assignment creation,
    and only when `mentor_id` is omitted."

    Design: Corner/errors/caseload_exhaustion_splits_named_from_automatic_selection
    """
    ctx = _one_full_mentor_beside_one_on_leave()

    response = api_client.create_mentor_assignment(
        create_mentor_assignment_payload(ctx["ben"]["id"], ctx["ben"]["version"]),
        fx.REGISTRAR)
    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_MENTOR.value, 422)

    A.assert_page(
        api_client.list_mentor_assignments(fx.REGISTRAR,
                                          params={"student_id": ctx["ben"]["id"]}),
        0,
    )


def test_the_pool_refills_the_instant_the_idle_mentor_comes_back():
    """Eligibility is recomputed at the moment of the request, so the same automatic
    call succeeds once Beta is available again.

    PRD: "Automatic selection begins by filtering to the mentors who are eligible, which
    requires both that `status` is `ACTIVE` and that `current_caseload` is strictly less
    than `max_caseload` — a mentor exactly at their ceiling is not eligible."

    Design: Corner/errors/caseload_exhaustion_splits_named_from_automatic_selection
    """
    ctx = _one_full_mentor_beside_one_on_leave()
    revived = fx.set_mentor_status(ctx["beta"]["id"], "ACTIVE")
    assert revived["status"] == "ACTIVE"

    response = api_client.create_mentor_assignment(
        create_mentor_assignment_payload(ctx["ben"]["id"], ctx["ben"]["version"]),
        fx.REGISTRAR)
    assignment = validate_success(response, 201)
    assert assignment["mentor_id"] == ctx["beta"]["id"]
    assert assignment["status"] == "ACTIVE"
    assert assignment["selection_mode"] == "AUTO_SELECTED"
    assert assignment["cadence_days"] == 14

    assert fx.refresh_mentor(ctx["beta"]["id"])["current_caseload"] == 1


def test_a_suspended_evaluator_has_no_administrative_route_back():
    """The endpoint that produced the suspension refuses to undo it towards either
    remaining standing, and the row stays on the version the suspension wrote.

    PRD: "Changing an evaluator's standing may not move a suspended evaluator, or else
    `ERR_EVALUATOR_SUSPENDED`."

    Design: Corner/errors/a_suspended_evaluator_cannot_be_revived
    """
    fx.set_clock(BASE_CLOCK_UTC)
    evaluator = fx.create_evaluator(full_name="Eve Reader", email="eve@example.edu",
                                    certification_level="SENIOR")
    assert evaluator["status"] == "CERTIFIED"
    assert evaluator["version"] == 1

    suspended = fx.set_evaluator_status(evaluator["id"], "SUSPENDED")
    assert suspended["status"] == "SUSPENDED"
    assert suspended["version"] == 2

    for target in ("CERTIFIED", "PROVISIONAL"):
        validate_error(
            api_client.set_evaluator_status(evaluator["id"], {"status": target},
                                           fx.ADMIN),
            ApiErrorId.ERR_EVALUATOR_SUSPENDED.value, 409)

    final = fx.refresh_evaluator(evaluator["id"])
    assert final["status"] == "SUSPENDED"
    assert final["version"] == 2
