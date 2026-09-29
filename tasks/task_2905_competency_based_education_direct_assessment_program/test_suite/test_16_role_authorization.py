"""Role authorization and the ownership overlay: every declared holder of an
operation gets through it, nobody else does, and the three entity-backed roles
are confined to their own subject.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import BASE_CLOCK_UTC, PHANTOM_UUID, TEST_DEFAULTS
from test_helpers.factories import (
    create_aid_disbursement_payload,
    create_attempt_payload,
    create_integrity_case_payload,
    create_program_payload,
    create_sap_review_payload,
    create_transcript_record_payload,
    dimension_score,
    record_score_payload,
    submit_attempt_payload,
)
from test_helpers.test_users import (
    make_evaluator_headers,
    make_mentor_headers,
    make_student_headers,
)

NEXT_DAY_UTC = "2026-09-02T00:00:00.000Z"


def _seven_role_world():
    """A published program with an assessed competency IT-101 and an endorsable
    IT-102, one ACTIVE student on an ACTIVE term with an ACTIVE mentor pairing,
    one CERTIFIED reader, and the student's own attempt already submitted."""
    fx.set_clock(BASE_CLOCK_UTC)
    program = fx.create_program()
    assessed = fx.create_competency(program["id"], code="IT-101",
                                    title="Relational Data Modeling",
                                    unit_value=4, level="FOUNDATION")
    endorsable = fx.create_competency(program["id"], code="IT-102",
                                      title="Query Optimization",
                                      unit_value=4, level="CORE")
    mentor = fx.create_mentor(full_name="Mentor Meg", email="meg@example.edu")
    evaluator = fx.create_evaluator(full_name="Eve Reader",
                                    email="eve@example.edu",
                                    certification_level="SENIOR")
    program = fx.publish_program(program["id"])
    # Enrollment requires a published program, so the student is enrolled only
    # after publication: "The referenced program is published before a student may
    # enrol in it."
    student = fx.create_student(program["id"], full_name="Ada Learner",
                                email="ada@example.edu")
    blueprint = fx.create_blueprint(assessed, required_evaluator_count=1)
    student = fx.activate_student(student["id"])
    term = fx.activate_term(fx.create_term(student["id"])["id"])
    assignment = fx.assign_mentor(student, mentor["id"])
    attempt = fx.open_attempt(student["id"], assessed["id"])
    attempt = fx.submit_attempt(attempt["id"], student["id"],
                                artifact_hash="sha256:ada-1")
    # Opening and submitting the attempt both recompute the term's `attempts_used`
    # and increment the term's version, so the term is re-read here: the aid
    # scheduling below has to carry the term's *current* version.
    term = fx.refresh_term(term["id"])
    return {"program": program, "assessed": assessed, "endorsable": endorsable,
            "blueprint": blueprint, "student": student, "term": term,
            "mentor": mentor, "assignment": assignment,
            "evaluator": evaluator, "attempt": attempt}


def test_the_assessment_spine_admits_each_of_its_five_declared_holders():
    """The Registrar publishes the program and its rubric, the Student submits, the
    Evaluator opens the integrity case and later scores it, and the IntegrityOfficer
    investigates and dismisses it. Not one of those calls is refused.

    PRD: "If `X-User-Role` holds any other string, or holds a valid role that is not
    listed among the authorized roles for the endpoint being called, the request is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/every_role_can_run_its_own_exclusive_operations
    """
    ctx = _seven_role_world()
    assert ctx["program"]["status"] == "PUBLISHED"
    assert ctx["blueprint"]["status"] == "PUBLISHED"
    assert ctx["student"]["enrollment_status"] == "ACTIVE"
    assert ctx["term"]["status"] == "ACTIVE"
    assert ctx["assignment"]["status"] == "ACTIVE"
    assert ctx["attempt"]["status"] == "UNDER_REVIEW"

    opened = validate_success(
        api_client.create_integrity_case(
            create_integrity_case_payload(ctx["attempt"]["id"]),
            make_evaluator_headers(ctx["evaluator"]["id"]),
        ),
        201,
    )
    assert opened["opened_by_user_id"] == ctx["evaluator"]["id"]
    assert opened["status"] == "OPEN"

    assert fx.investigate_case(opened["id"], "officer-1")["status"] == \
        "UNDER_INVESTIGATION"
    resolved = fx.resolve_case(opened["id"], "DISMISSED", "NONE", "officer-2")
    # PRD: a DISMISSED outcome "sets `resolved_at_utc` to the logical clock and
    # `resolved_by_user_id` to the acting officer". The outcome itself is a payload
    # input the PRD never declares as a response-visible case attribute.
    assert resolved["resolved_by_user_id"] == "officer-2"
    A.assert_instant_equals(resolved["resolved_at_utc"], BASE_CLOCK_UTC,
                            "resolved_at_utc")
    assert fx.refresh_attempt(ctx["attempt"]["id"])["status"] == "UNDER_REVIEW"

    score = fx.record_score(ctx["attempt"]["id"], ctx["evaluator"]["id"],
                            [dimension_score("D1", 90)])
    A.assert_number_equals(score["weighted_score_pct"], 90.00,
                           "weighted_score_pct")
    assert fx.refresh_attempt(ctx["attempt"]["id"])["status"] == "SCORED_MASTERED"
    assert fx.refresh_term(ctx["term"]["id"])["credit_equivalency_earned"] == 1


def test_the_aid_mentoring_and_platform_frontiers_admit_their_own_holders_too():
    """The FinancialAidOfficer schedules an award, the FacultyMentor endorses a
    second competency for their own mentee, and the PlatformAdmin moves the
    reader's standing — three operations no other role may call, each accepted
    from its single declared holder.

    PRD: "Standing can be set to `CERTIFIED`, `PROVISIONAL` or `SUSPENDED` by a
    platform administrator; attempting to change the standing of an evaluator who
    is already `SUSPENDED` is refused with `ERR_EVALUATOR_SUSPENDED`, since
    suspension is terminal."

    Design: Corner/rbac/every_role_can_run_its_own_exclusive_operations
    """
    ctx = _seven_role_world()

    award = fx.schedule_aid(ctx["student"]["id"], ctx["term"])
    assert award["status"] == "SCHEDULED"
    A.assert_cents(award["outstanding_amount_cents"],
                   TEST_DEFAULTS["AID_SCHEDULED_CENTS"],
                   "outstanding_amount_cents")

    endorsed = fx.record_endorsement(ctx["assignment"]["id"], ctx["mentor"]["id"],
                                     ctx["endorsable"]["id"])
    assert endorsed["status"] == "ACTIVE"
    assert endorsed["endorsement_count"] == 1
    assert endorsed["endorsed_competency_ids"] == [ctx["endorsable"]["id"]]

    demoted = fx.set_evaluator_status(ctx["evaluator"]["id"], "PROVISIONAL")
    assert demoted["status"] == "PROVISIONAL"
    A.assert_common_fields(demoted, expected_version=2)


def _a_draft_program_beside_a_certified_reader():
    """A PlatformAdmin-registered program still in DRAFT, one competency, one
    CERTIFIED reader and one mentor — the identities the cross-role probes below
    act under."""
    fx.set_clock(BASE_CLOCK_UTC)
    program = validate_success(
        api_client.create_program(create_program_payload(), fx.ADMIN), 201
    )
    assert program["status"] == "DRAFT"
    competency = fx.create_competency(program["id"], code="IT-101",
                                      title="Relational Data Modeling",
                                      unit_value=4, level="FOUNDATION")
    evaluator = fx.create_evaluator(full_name="Eve Reader",
                                    email="eve@example.edu",
                                    certification_level="SENIOR")
    mentor = fx.create_mentor(full_name="Mentor Meg", email="meg@example.edu")
    # Adding the competency mutated the program ("Creation also increments the
    # owning program's `competency_count` and its `version`"), so the probes below
    # must measure "nothing moved" against the refreshed draft, not the create
    # response.
    return {"program": fx.refresh_program(program["id"]),
            "competency": competency,
            "evaluator": evaluator, "mentor": mentor}


def _six_cross_role_probes(ctx):
    """The six calls each of which a role holds no grant for. The aid and
    progress-checkpoint bodies deliberately name the competency's id where a
    student and a term id belong."""
    wrong_id = ctx["competency"]["id"]
    return [
        api_client.publish_program(ctx["program"]["id"], fx.ADMIN),
        api_client.set_evaluator_status(ctx["evaluator"]["id"],
                                        {"status": "PROVISIONAL"}, fx.REGISTRAR),
        api_client.create_aid_disbursement(
            create_aid_disbursement_payload(wrong_id, wrong_id, 1),
            make_evaluator_headers(ctx["evaluator"]["id"]),
        ),
        api_client.activate_student(wrong_id, fx.AID_OFFICER),
        api_client.create_sap_review(create_sap_review_payload(wrong_id, wrong_id),
                                     make_mentor_headers(ctx["mentor"]["id"])),
        api_client.suspend_student(wrong_id, make_student_headers(PHANTOM_UUID),
                                   {"reason": "self-service suspension"}),
    ]


def test_no_role_may_step_onto_another_roles_exclusive_operation():
    """Publication is the Registrar's alone and certification the PlatformAdmin's
    alone, and the aid, progress and enrollment frontiers are impassable in both
    directions: all six crossings are refused with the same role error at 403.

    PRD: "`X-User-Role` names one of the seven declared roles and that role is
    authorized for the target endpoint — otherwise `ERR_FORBIDDEN_ROLE`. Applies to
    every endpoint."

    Design: Corner/rbac/no_role_can_run_another_roles_exclusive_operation
    """
    ctx = _a_draft_program_beside_a_certified_reader()

    for response in _six_cross_role_probes(ctx):
        validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_the_role_refusal_lands_before_the_nonsense_in_the_body_is_ever_read():
    """The refused calls carry a competency id where a student and a term id belong,
    yet none of them reports a missing student or term, and nothing they touched
    moved: the program is still a draft at exactly the version the map build left
    it on, and the reader is still certified at version 1.

    PRD: "If `X-User-Role` holds any other string, or holds a valid role that is not
    listed among the authorized roles for the endpoint being called, the request is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/no_role_can_run_another_roles_exclusive_operation
    """
    ctx = _a_draft_program_beside_a_certified_reader()

    seen = [validate_error(r, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)["error_id"]
            for r in _six_cross_role_probes(ctx)]
    assert seen == ["ERR_FORBIDDEN_ROLE"] * 6

    program = fx.refresh_program(ctx["program"]["id"])
    assert program["status"] == "DRAFT"
    A.assert_common_fields(program, expected_version=ctx["program"]["version"])

    evaluator = fx.refresh_evaluator(ctx["evaluator"]["id"])
    assert evaluator["status"] == "CERTIFIED"
    A.assert_common_fields(evaluator, expected_version=1)

    A.assert_page(api_client.list_aid_disbursements(fx.AID_OFFICER), 0)
    A.assert_page(api_client.list_sap_reviews(fx.REGISTRAR), 0)


def _two_candidates_two_mentors_and_one_submitted_attempt():
    """Ada and Ben are both ACTIVE on the same published program; Ada alone holds a
    term, a pairing with mentor Alpha and an attempt under review. Mentor Beta holds
    no pairing at all."""
    fx.set_clock(BASE_CLOCK_UTC)
    program = fx.create_program()
    competency = fx.create_competency(program["id"], code="IT-101",
                                      title="Relational Data Modeling",
                                      unit_value=4, level="FOUNDATION")
    program = fx.publish_program(program["id"])
    fx.create_blueprint(competency, required_evaluator_count=1)
    ada = fx.activate_student(
        fx.create_student(program["id"], full_name="Ada Learner",
                          email="ada@example.edu")["id"]
    )
    ben = fx.activate_student(
        fx.create_student(program["id"], full_name="Ben Learner",
                          email="ben@example.edu")["id"]
    )
    alpha = fx.create_mentor(full_name="Mentor Alpha", email="alpha@example.edu")
    beta = fx.create_mentor(full_name="Mentor Beta", email="beta@example.edu")
    assignment = fx.assign_mentor(ada, alpha["id"])
    term = fx.activate_term(fx.create_term(ada["id"])["id"])
    evaluator = fx.create_evaluator(full_name="Eve Reader",
                                    email="eve@example.edu",
                                    certification_level="SENIOR")
    attempt = fx.open_attempt(ada["id"], competency["id"])
    attempt = fx.submit_attempt(attempt["id"], ada["id"],
                                artifact_hash="sha256:aaa",
                                client_fingerprint="fp-ada-1")
    assert attempt["status"] == "UNDER_REVIEW"
    return {"program": program, "competency": competency, "ada": ada, "ben": ben,
            "alpha": alpha, "beta": beta, "assignment": assignment, "term": term,
            "evaluator": evaluator, "attempt": attempt}


def test_one_candidate_cannot_read_or_write_another_candidates_record():
    """Ben's role is on every one of these five endpoints, and every one of them is
    still refused, because the subject of each resource is Ada and not him.

    PRD: "When the role is permitted to call the endpoint but the acting principal
    does not own the resource in question, the rejection is `ERR_NOT_RESOURCE_OWNER`
    (HTTP 403)."

    Design: Corner/rbac/entity_backed_roles_cannot_reach_across_to_another_subject
    """
    ctx = _two_candidates_two_mentors_and_one_submitted_attempt()
    intruder = make_student_headers(ctx["ben"]["id"])

    probes = [
        api_client.get_student(ctx["ada"]["id"], intruder),
        api_client.get_progress_summary(ctx["ada"]["id"], intruder),
        api_client.get_attempt(ctx["attempt"]["id"], intruder),
        api_client.create_attempt(
            create_attempt_payload(ctx["ada"]["id"], ctx["competency"]["id"]),
            intruder,
        ),
        api_client.submit_attempt(
            ctx["attempt"]["id"],
            submit_attempt_payload(artifact_hash="sha256:bbb",
                                   client_fingerprint="fp-ben-1"),
            intruder,
        ),
    ]
    for response in probes:
        validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)


def test_a_mentor_cannot_log_a_contact_against_another_mentors_pairing():
    """Mentor Beta is a FacultyMentor, and the contacts endpoint is a FacultyMentor
    endpoint, but the pairing belongs to Alpha — so the cadence clock never resets.

    PRD: "When `X-User-Role` is `FacultyMentor`, `X-User-ID` is the `id` of the
    acting `Mentor` row; a faculty mentor may only act on a mentor-assignment record
    whose `mentor_id` equals `X-User-ID`."

    Design: Corner/rbac/entity_backed_roles_cannot_reach_across_to_another_subject
    """
    ctx = _two_candidates_two_mentors_and_one_submitted_attempt()

    response = api_client.record_contact(ctx["assignment"]["id"],
                                         make_mentor_headers(ctx["beta"]["id"]),
                                         {"note": "not my mentee"})
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    assignment = fx.refresh_assignment(ctx["assignment"]["id"])
    assert assignment["contact_count"] == 0
    assert assignment["last_contact_utc"] is None
    assert assignment["status"] == "ACTIVE"


def test_a_reader_cannot_file_a_score_under_another_readers_identity():
    """The score body names the certified reader Eve while the acting identity is
    somebody else entirely; the mismatch is caught before the duplicate-score and
    certification rules are ever consulted.

    PRD: "When `X-User-Role` is `Evaluator`, `X-User-ID` is the `id` of the acting
    `Evaluator` row; an evaluator may only submit a rubric score whose
    `evaluator_id` equals `X-User-ID`."

    Design: Corner/rbac/entity_backed_roles_cannot_reach_across_to_another_subject
    """
    ctx = _two_candidates_two_mentors_and_one_submitted_attempt()

    response = api_client.record_score(
        ctx["attempt"]["id"],
        record_score_payload(ctx["evaluator"]["id"], [dimension_score("D1", 90)]),
        make_evaluator_headers(ctx["beta"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    attempt = fx.refresh_attempt(ctx["attempt"]["id"])
    assert attempt["status"] == "UNDER_REVIEW"
    assert attempt["scores_received_count"] == 0
    A.assert_page(
        api_client.list_evaluator_scores(fx.REGISTRAR,
                                         params={"attempt_id": ctx["attempt"]["id"]}),
        0,
    )


def test_the_rightful_owners_still_reach_their_own_rows_after_the_intrusions():
    """The refusals are surgical rather than defensive: Ada reads her own record and
    her own attempt exactly as before, no attempt was created for Ben, and Alpha's
    pairing still shows no contact.

    PRD: "Resource ownership for the three entity-backed roles, as described in §2.1
    — otherwise `ERR_NOT_RESOURCE_OWNER`. Applies to the nine operations enumerated
    in §2.1."

    Design: Corner/rbac/entity_backed_roles_cannot_reach_across_to_another_subject
    """
    ctx = _two_candidates_two_mentors_and_one_submitted_attempt()
    intruder = make_student_headers(ctx["ben"]["id"])
    validate_error(
        api_client.create_attempt(
            create_attempt_payload(ctx["ada"]["id"], ctx["competency"]["id"]),
            intruder,
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403,
    )
    validate_error(
        api_client.record_contact(ctx["assignment"]["id"],
                                  make_mentor_headers(ctx["beta"]["id"]),
                                  {"note": "not my mentee"}),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403,
    )

    owner = make_student_headers(ctx["ada"]["id"])
    own_student = validate_success(api_client.get_student(ctx["ada"]["id"], owner))
    assert own_student["enrollment_status"] == "ACTIVE"
    A.assert_common_fields(own_student, expected_version=3)

    own_attempt = validate_success(
        api_client.get_attempt(ctx["attempt"]["id"], owner)
    )
    assert own_attempt["status"] == "UNDER_REVIEW"
    assert own_attempt["scores_received_count"] == 0

    A.assert_page(
        api_client.list_attempts(fx.REGISTRAR,
                                 params={"student_id": ctx["ben"]["id"]}),
        0,
    )
    assert fx.refresh_assignment(ctx["assignment"]["id"])["contact_count"] == 0


def _an_active_pairing_and_its_mentee():
    """One ACTIVE student on a published program with an ACTIVE pairing to mentor
    Meg, and no contact recorded yet."""
    fx.set_clock(BASE_CLOCK_UTC)
    program = fx.create_program()
    fx.create_competency(program["id"], code="IT-101",
                         title="Relational Data Modeling",
                         unit_value=4, level="FOUNDATION")
    program = fx.publish_program(program["id"])
    student = fx.activate_student(
        fx.create_student(program["id"], full_name="Ada Learner",
                          email="ada@example.edu")["id"]
    )
    mentor = fx.create_mentor(full_name="Mentor Meg", email="meg@example.edu")
    assignment = fx.assign_mentor(student, mentor["id"])
    assert assignment["contact_count"] == 0
    return {"program": program, "student": student, "mentor": mentor,
            "assignment": assignment}


def test_a_progress_contact_is_accepted_from_the_registrar_and_from_the_mentor():
    """Both declared holders drive the same self-transition with identical
    semantics, and the ownership overlay binds only the mentor: the Registrar's call
    carries no matching `X-User-ID` at all and still lands.

    PRD: "Three preconditions apply: the assignment must be `ACTIVE`, or the request
    is refused with `ERR_ASSIGNMENT_NOT_ACTIVE`; when the caller acts as
    `FacultyMentor` their `X-User-ID` must equal the assignment's `mentor_id`; and
    the mentee's `enrollment_status` must be either `ACTIVE` or `SUSPENDED`, because
    mentoring a suspended student is precisely how a suspension gets resolved."

    Design: Corner/rbac/shared_operations_work_for_every_declared_holder
    """
    ctx = _an_active_pairing_and_its_mentee()

    by_registrar = validate_success(
        api_client.record_contact(ctx["assignment"]["id"], fx.REGISTRAR,
                                  {"note": "registrar-recorded check-in"})
    )
    assert by_registrar["contact_count"] == 1
    A.assert_instant_equals(by_registrar["last_contact_utc"], BASE_CLOCK_UTC,
                            "last_contact_utc")

    by_mentor = fx.record_contact(ctx["assignment"]["id"], ctx["mentor"]["id"],
                                  note="mentor-recorded check-in")
    assert by_mentor["contact_count"] == 2
    assert by_mentor["cadence_status"] == "COMPLIANT"
    assert by_mentor["status"] == "ACTIVE"


def test_a_transcript_drafted_by_the_student_supersedes_the_registrars_draft():
    """The shared build endpoint yields the same shape from either holder — and the
    second draft is not a duplicate but a replacement, voiding the first as
    superseded.

    PRD: "The record is created in `DRAFT`, and creating it voids any earlier draft
    record for the same student with `voided_reason` `SUPERSEDED`."

    Design: Corner/rbac/shared_operations_work_for_every_declared_holder
    """
    ctx = _an_active_pairing_and_its_mentee()

    first = validate_success(
        api_client.create_transcript_record(
            create_transcript_record_payload(ctx["student"]["id"], "INTERNAL"),
            fx.REGISTRAR,
        ),
        201,
    )
    assert first["status"] == "DRAFT"
    assert first["competency_line_count"] == 0

    second = validate_success(
        api_client.create_transcript_record(
            create_transcript_record_payload(ctx["student"]["id"], "STUDENT_COPY"),
            make_student_headers(ctx["student"]["id"]),
        ),
        201,
    )
    assert second["status"] == "DRAFT"
    assert second["purpose"] == "STUDENT_COPY"
    assert set(second.keys()) == set(first.keys())

    superseded = fx.refresh_transcript(first["id"])
    assert superseded["status"] == "VOIDED"
    assert superseded["voided_reason"] == "SUPERSEDED"


def test_the_logical_clock_moves_for_a_holder_other_than_the_platform_admin():
    """The clock endpoint declares four holders, so a financial-aid officer's write
    is as good as a platform administrator's.

    PRD: "| POST | `/_clock/set_current_utc` | Set the logical clock that every rule
    in this specification reads as the current instant. Moving the clock backwards is
    permitted. | PlatformAdmin, Registrar, IntegrityOfficer, FinancialAidOfficer |"

    Design: Corner/rbac/shared_operations_work_for_every_declared_holder
    """
    fx.set_clock(BASE_CLOCK_UTC)

    moved = validate_success(api_client.set_clock(NEXT_DAY_UTC, fx.AID_OFFICER))
    A.assert_instant_equals(moved["current_utc"], NEXT_DAY_UTC, "current_utc")
    A.assert_instant_equals(fx.read_clock()["current_utc"], NEXT_DAY_UTC,
                            "current_utc")
