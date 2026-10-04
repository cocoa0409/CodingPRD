"""Queue B — rbac: role and ownership denials, including both segregation-of-
duties pairs (program director vs psychomotor evaluator is covered by the
difficulty queue; here the hearing-officer split and the ownership gates).
"""
from test_helpers import (
    ApiErrorId,
    DEFAULT_RECERT_CLOCK,
    api_client,
    advance_clock,
    ce_entry_payload,
    create_candidate,
    create_completion_record_payload,
    create_education_program_payload,
    create_exam_application,
    create_level,
    create_program,
    create_recert_draft,
    decision_payload,
    get_success_data,
    make_candidate_headers,
    make_exam_proctor_headers,
    make_hearing_officer_headers,
    make_program_director_headers,
    make_state_official_headers,
    open_case,
    schedule_attempt_payload,
    setup_approved_application,
    setup_candidate_with_verified_completion,
    setup_certified_candidate,
    validate_error,
    walk_case_to_under_review,
)


def test_rbac_exam_decision_denied_to_candidate(api):
    """PRD §2.1: "Access to every operation is restricted by role, and a caller
    whose role is not on an endpoint's authorized list is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: the exam-application decision endpoint admits `RegistryAdmin` only.

    Candidates cannot decide their own exam applications.

    Design: Corner/rbac/rbac_exam_decision_denied_to_candidate
    """
    ctx = setup_candidate_with_verified_completion()
    application = create_exam_application(
        ctx["candidate"]["id"], ctx["level"]["id"], ctx["completion_record"]["id"],
    )
    resp = api_client.decide_exam_application(
        application["id"], decision_payload("APPROVED"),
        make_candidate_headers(ctx["candidate"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert get_success_data(
        api_client.get_exam_application(application["id"], make_candidate_headers(ctx["candidate"]["id"]))
    )["status"] == "SUBMITTED"


def test_rbac_completion_attest_denied_to_foreign_director(api):
    """PRD §2.1: "On program-scoped attestations the server compares it against
    the `director_user_id` recorded on the target education program: a
    completion attestation naming a program whose `director_user_id` differs
    from the caller's `X-User-ID` is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/rbac_completion_attest_denied_to_foreign_director
    """
    level = create_level()
    program = create_program(level["id"])  # directed by dir-1
    candidate = create_candidate()
    resp = api_client.create_program_completion_record(
        create_completion_record_payload(candidate["id"], program["id"]),
        make_program_director_headers("dir-2"),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_rbac_program_creation_denied_to_state_official(api):
    """PRD §2.1: "Access to every operation is restricted by role, and a caller
    whose role is not on an endpoint's authorized list is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: program registration admits `RegistryAdmin` only.

    Design: Corner/rbac/rbac_program_creation_denied_to_state_official
    """
    level = create_level()
    resp = api_client.create_education_program(
        create_education_program_payload(level["id"], director_user_id="dir-9"),
        make_state_official_headers("so-1"),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_rbac_scheduling_denied_to_proctor(api):
    """PRD §2.1: "Access to every operation is restricted by role, and a caller
    whose role is not on an endpoint's authorized list is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: attempt scheduling admits `Candidate` only; `ExamProctor` delivers
    responses.

    Design: Corner/rbac/rbac_scheduling_denied_to_proctor
    """
    ctx = setup_approved_application()
    resp = api_client.schedule_cognitive_exam_attempt(
        schedule_attempt_payload(ctx["att_id"]),
        make_exam_proctor_headers("proctor-1"),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_rbac_hearing_officer_segregation(api):
    """PRD §3.9: "A `HearingOfficer` then schedules the hearing — from
    `UNDER_REVIEW`, or from `REHEARING` on a remanded case — provided the
    officer's identity differs from the case opener's
    (`ERR_SEGREGATION_OF_DUTIES`)".
    PRD §2.1: "When `X-User-Role` is `HearingOfficer`, `X-User-ID` is likewise
    opaque, with one segregation constraint: it must differ from the
    `opened_by_user_id` of the disciplinary case being scheduled or decided."

    The same opaque operator id on both sides is rejected even across two
    different roles.

    Design: Corner/rbac/rbac_hearing_officer_segregation
    """
    candidate = create_candidate()
    case = open_case(
        candidate["id"], violation_type="EXAM_SECURITY",
        description="Suspected device in exam room", opener_user_id="shared-op",
    )
    walk_case_to_under_review(case["id"], candidate["id"])
    resp = api_client.schedule_case_hearing(
        case["id"], make_hearing_officer_headers("shared-op"),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


def test_rbac_ce_entry_denied_to_foreign_candidate(api):
    """PRD §2.1: "When `X-User-Role` is `Candidate`, `X-User-ID` is the `id` of
    the acting Candidate, minted at self-registration; ownership checks on any
    resource that references a Candidate compare the resource's candidate
    foreign key to `X-User-ID`."
    PRD §3.6: "Only the draft's owner may add entries".

    Candidate B cannot add entries to candidate A's draft.

    Design: Corner/rbac/rbac_ce_entry_denied_to_foreign_candidate
    """
    ctx = setup_certified_candidate()
    advance_clock(DEFAULT_RECERT_CLOCK)
    draft = create_recert_draft(ctx["candidate"]["id"], ctx["certification"]["id"])
    interloper = create_candidate()
    resp = api_client.add_ce_entry(
        draft["id"],
        ce_entry_payload("NATIONAL", 10, "IN_PERSON", "2027-10-01", "EvilCE"),
        make_candidate_headers(interloper["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
