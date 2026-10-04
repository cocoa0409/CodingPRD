"""Corner tests (errors + rbac): error envelope shape, role denial, segregation of
duties, and entity-backed ownership."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    get_success_data,
    make_researcher_headers,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_program_payload
from test_helpers.fixtures import (
    PLATFORM_ADMIN,
    PROGRAM_ADMIN,
    TRIAGER,
    approve_award,
    create_award,
    create_validated_report,
    get_award,
    register_researcher,
    setup_active_program,
    submit_report,
)


def test_error_envelope_shape_on_404(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this standard
    envelope format" with `response_type` "error", `data.error_id`, and
    `data.message`.
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    Design: Corner/errors/error_envelope_shape_on_404
    """
    resp = api.get_program(NON_EXISTENT_UUID, PLATFORM_ADMIN)
    assert resp.status_code == 404
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]
    assert body["meta"]["api_request_id"].startswith("req_")


def test_researcher_cannot_create_program_forbidden(api):
    """PRD §2.1: "Once authenticated, the role is checked against the endpoint's
    authorized role list; a role not listed for that endpoint yields
    `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "`Researcher` is a security researcher who submits reports, answers
    information requests, negotiates disclosure, and manages their own tax
    documents."

    Design: Corner/rbac/researcher_cannot_create_program_forbidden
    """
    researcher = register_researcher()
    resp = api.create_program(
        create_program_payload(), make_researcher_headers(researcher["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert resp.status_code == 403


def test_award_chain_segregation_of_duties(api):
    """PRD §3.9: "Approval and payment are segregated duties: a `ProgramAdmin`
    approves, a `PlatformAdmin` pays."
    PRD §2.1: "Once authenticated, the role is checked against the endpoint's
    authorized role list; a role not listed for that endpoint yields
    `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.9: "Awards are proposed by a `Triager` naming the `report_id`, an
    `award_type` of `BOUNTY`, `BONUS`, or `RETEST`, and — for `BONUS` only — an
    `amount_cents`."

    Design: Corner/rbac/award_chain_segregation_of_duties
    """
    program, asset = setup_active_program(criticality="MEDIUM")
    researcher = register_researcher()
    report = create_validated_report(
        program, asset, researcher, impact=5, exploitability=5, affected_scope=5)
    award = create_award(report["id"], "BOUNTY")
    # Triager proposed but cannot approve
    err1 = api.approve_award(award["id"], TRIAGER)
    validate_error(err1, ApiErrorId.ERR_FORBIDDEN)
    # ProgramAdmin approves legitimately
    approved = approve_award(award["id"])
    assert approved["status"] == "APPROVED"
    # ProgramAdmin cannot pay
    err2 = api.pay_award(award["id"], PROGRAM_ADMIN)
    validate_error(err2, ApiErrorId.ERR_FORBIDDEN)
    # PlatformAdmin cannot propose
    err3 = api.create_award(
        {"report_id": report["id"], "award_type": "BONUS", "amount_cents": 1000},
        PLATFORM_ADMIN)
    validate_error(err3, ApiErrorId.ERR_FORBIDDEN)
    assert get_award(award["id"])["status"] == "APPROVED"


def test_researcher_cannot_answer_other_researchers_needs_info(api):
    """PRD §2.1: "a researcher may only answer an information request on their
    own report, respond to their own invitations, submit tax documents for their
    own profile, request disclosure for their own reports, and creates reports
    with themselves as the submitter — any attempt to act on another researcher's
    resource is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.6: "Requesting more information moves `TRIAGED` to `NEEDS_INFO` and
    refreshes `triaged_at`; the ball is then in the researcher's court, and the
    owning researcher answers with an `info` payload that returns the report to
    `TRIAGED`, again refreshing `triaged_at`."

    Design: Corner/rbac/researcher_cannot_answer_other_researchers_needs_info
    """
    program, asset = setup_active_program(criticality="HIGH")
    researcher_a = register_researcher()
    researcher_b = register_researcher()
    report = submit_report(program, asset, researcher_a)
    get_success_data(api.triage_report(report["id"], {"action": "TRIAGE"}, TRIAGER))
    get_success_data(api.triage_report(report["id"], {"action": "REQUEST_INFO"}, TRIAGER))
    assert get_success_data(api.get_report(report["id"], TRIAGER))["status"] == "NEEDS_INFO"
    resp = api.provide_info(
        report["id"], {"info": "not my report"},
        make_researcher_headers(researcher_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_success_data(api.get_report(report["id"], TRIAGER))["status"] == "NEEDS_INFO"
