"""Role-based access control and authentication: exclusive operations, the
RefugeManager hierarchical override, ownership anchors (applicant_ref,
cooperator_ref, volunteer self-scope), and the auth-first validation order.
"""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated,
    create_unit, create_final_determination, create_approved_permit,
    create_volunteer, create_cleared_volunteer, create_program,
    create_assignment, setup_program_with_volunteers,
    setup_grazing_offering, setup_awarded_agreement,
    setup_determination_with_comment,
    create_management_unit_payload, create_bid_payload,
    create_assess_payload, create_adjudicate_payload,
    make_permit_applicant_headers, make_cooperator_headers,
    make_volunteer_headers,
)

RM = TEST_USERS["refuge_manager_headers"]
BIO = TEST_USERS["biologist_headers"]
PO = TEST_USERS["permit_officer_headers"]
VC = TEST_USERS["volunteer_coordinator_headers"]
LEO = TEST_USERS["law_enforcement_officer_headers"]


def test_permit_officer_cannot_create_unit_returns_403(api):
    """PRD §2.1: "`RefugeManager` is the refuge's senior authority: the
    manager alone creates management units, closes and selects grazing
    awards, posts refunds, completes cooperative agreements, and advances
    the logical clock, and additionally may perform any operation available
    to `Biologist`, `PermitOfficer`, `VolunteerCoordinator`,
    `LawEnforcementOfficer`, or `StateAgencyPartner` — a hierarchical
    override across all staff operations."
    PRD §2.1: "A caller whose role is not among an endpoint's authorized
    roles — or who violates an ownership anchor defined below — is rejected
    with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/permit_officer_cannot_create_unit_returns_403
    """
    resp = api_client.create_management_unit(
        create_management_unit_payload(
            name="Rogue Unit", habitat_type="WETLAND", acreage=10), PO)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_applicant_cannot_pay_for_other_applicant_returns_403(api):
    """PRD §2.1: "Every permit application records an `applicant_ref` that
    must equal the calling `PermitApplicant`'s `X-User-ID` at creation, and
    subsequent applicant-only actions on that application compare
    `X-User-ID` against the stored `applicant_ref`."

    Design: Corner/rbac/applicant_cannot_pay_for_other_applicant_returns_403
    """
    unit = create_unit()
    det = create_final_determination(use_type="RESEARCH")
    permit = create_approved_permit(unit["id"], det["id"], applicant_ref="app-1")
    resp = api_client.pay_permit(
        permit["id"], {"amount_cents": permit["assessed_fee_cents"]},
        make_permit_applicant_headers("app-2"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_biologist_cannot_adjudicate_comment_returns_403(api):
    """PRD §2.1: "`PermitOfficer` owns compatibility determinations, comment
    adjudication, and permit review, approval, and revocation."
    PRD §2.1: "A caller whose role is not among an endpoint's authorized
    roles — or who violates an ownership anchor defined below — is rejected
    with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/biologist_cannot_adjudicate_comment_returns_403
    """
    det, comment = setup_determination_with_comment(use_type="PHOTOGRAPHY")
    resp = api_client.adjudicate_comment(
        comment["id"], create_adjudicate_payload(disposition="NOTED"), BIO)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_refuge_manager_override_adjudicates_comment(api):
    """PRD §2.1: "and additionally may perform any operation available to
    `Biologist`, `PermitOfficer`, `VolunteerCoordinator`,
    `LawEnforcementOfficer`, or `StateAgencyPartner` — a hierarchical
    override across all staff operations."

    Design: Corner/rbac/refuge_manager_override_adjudicates_comment
    """
    det, comment = setup_determination_with_comment(use_type="PHOTOGRAPHY")
    adjudicated = validate_success(api_client.adjudicate_comment(
        comment["id"], create_adjudicate_payload(disposition="ACCEPTED"), RM))
    assert adjudicated["status"] == "ADJUDICATED"
    assert adjudicated["disposition"] == "ACCEPTED"


def test_volunteer_reads_own_assignments(api):
    """PRD §3.6: "Reads are staff affairs with one anchored exception: a
    caller in the `Volunteer` role may list and read only assignments under
    their own `volunteer_id`, and any attempt to frame the query on someone
    else's — or to read another volunteer's assignment by id — is rejected
    with `ERR_UNAUTHORIZED_ROLE`."

    Design: Corner/rbac/volunteer_reads_own_assignments
    """
    ctx = setup_program_with_volunteers(num_volunteers=1)
    volunteer = ctx["volunteers"][0]
    resp = api_client.list_assignments(
        make_volunteer_headers(volunteer["id"]),
        params={"volunteer_id": volunteer["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1 and len(data) == 1
    assert data[0]["volunteer_id"] == volunteer["id"]


def test_volunteer_reading_others_assignments_forbidden_returns_403(api):
    """PRD §3.6: "Reads are staff affairs with one anchored exception: a
    caller in the `Volunteer` role may list and read only assignments under
    their own `volunteer_id`, and any attempt to frame the query on someone
    else's — or to read another volunteer's assignment by id — is rejected
    with `ERR_UNAUTHORIZED_ROLE`."

    Design: Corner/rbac/volunteer_reading_others_assignments_forbidden_returns_403
    """
    unit = create_unit(name="Visitor Center Unit", habitat_type="MIXED",
                       acreage=500)
    v1 = create_volunteer(full_name="Vol One", email="v1@x.com")
    v2 = create_cleared_volunteer(full_name="Vol Two", email="v2@x.com")
    program = create_program(
        unit["id"], title="Owl Prowl", program_date="2026-12-01",
        min_volunteers=1, max_volunteers=3)
    create_assignment(program["id"], v2["id"])
    resp = api_client.list_assignments(
        make_volunteer_headers(v1["id"]), params={"volunteer_id": v2["id"]})
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_cooperator_cannot_bid_as_other_returns_403(api):
    """PRD §3.7: "A `Cooperator` submits a bid naming themselves through
    `cooperator_ref`, which must equal the caller's `X-User-ID`, quoting a
    `rate_cents_per_aum` — the price in cents per animal-unit-month, an
    integer greater than zero — and declaring a `stewardship_rating` from 1
    to 10, which the offering's floor will judge at selection."

    Design: Corner/rbac/cooperator_cannot_bid_as_other_returns_403
    """
    ctx = setup_grazing_offering()
    resp = api_client.create_bid(
        ctx["offering"]["id"],
        create_bid_payload(cooperator_ref="coop-victim",
                           rate_cents_per_aum=100, stewardship_rating=9),
        make_cooperator_headers("coop-attacker"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_leo_cannot_assess_agreement_returns_403(api):
    """PRD §2.1: "`Biologist` owns habitat treatments, facility closures, the
    grazing offering lifecycle, and period assessments on agreements."
    PRD §2.1: "A caller whose role is not among an endpoint's authorized
    roles — or who violates an ownership anchor defined below — is rejected
    with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/leo_cannot_assess_agreement_returns_403
    """
    ctx = setup_awarded_agreement()
    agreement = ctx["agreement"]
    resp = api_client.assess_agreement(
        agreement["id"],
        create_assess_payload(
            agreement["version"], period_key="2026-11", aum_used=1,
            rate_cents_per_aum=1000),
        LEO)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "A request whose `X-User-Role` header is missing, or whose
    value does not match one of the declared roles, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401); the same rejection applies when
    `X-User-ID` is absent for any role other than `Anonymous`, the one role
    that calls without an identity header."

    Design: Corner/validations/missing_auth_headers_returns_401
    """
    unit = create_unit()
    resp = api_client.get_management_unit(unit["id"], headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_missing_auth_precedes_not_found_returns_401(api):
    """PRD §2.6: "Every request passes through a single ordered validation
    cascade, and the first failing check determines the error returned; later
    checks are never consulted once an earlier one has fired."
    PRD §2.6: "1. **Authentication** — the role header is present and names a
    declared role, and the identity header is present for every role except
    `Anonymous` (`ERR_UNAUTHENTICATED`, 401)."

    Design: Corner/validations/missing_auth_precedes_not_found_returns_401
    """
    resp = api_client.get_permit(
        "00000000-0000-0000-0000-000000000000", headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
