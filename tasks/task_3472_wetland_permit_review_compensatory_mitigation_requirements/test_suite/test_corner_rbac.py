"""Corner queue — role gates and segregation of duties (PRD §2.1, §2.9).

Exclusive-operation denials for mismatched roles, and the two
segregation-of-duties gates on recorded operator identifiers.
"""
from test_helpers import (
    ApiErrorId,
    create_agency_comment_payload,
    create_applicant,
    create_applicant_payload,
    create_enforcement_case_payload,
    make_district_engineer_headers,
    render_decision_payload,
    render_decision,
    setup_application_decision_pending,
    setup_application_public_notice_open,
    setup_applicant_and_site,
    setup_case_opened,
    confirm_case,
    setup_secured_bank_credits_plan,
    setup_site_with_issued_jd,
    create_application,
    submit_and_screen_begin,
    validate_error,
)


def test_corner_reviewer_cannot_render_decision(api, reviewer_2_headers):
    """PRD §2.1: "If the role is valid but does not appear in the endpoint's
    authorized role list, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."
    PRD §4: POST /wetland-permits/applications/{id}/render-decision is
    authorized for DistrictEngineer only.

    The Reviewer role is rejected even at a decision-shaped moment; the
    caller (rev-2) is not the screener, isolating the role check from the
    segregation-of-duties gate.

    Design: Corner/rbac/corner_reviewer_cannot_render_decision
    """
    applicant, site, jd = setup_site_with_issued_jd()
    app = create_application(site, jd, applicant)
    app = submit_and_screen_begin(app, applicant)

    resp = api.render_decision(
        app["id"], render_decision_payload("ISSUE"), reviewer_2_headers
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_corner_engineer_cannot_file_comment(api, district_engineer_headers):
    """PRD §2.1: "If the role is valid but does not appear in the endpoint's
    authorized role list, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."
    PRD §4: POST /wetland-permits/agency-comments is authorized for
    AgencyReviewer only.

    Design: Corner/rbac/corner_engineer_cannot_file_comment
    """
    ctx = setup_application_public_notice_open()
    resp = api.create_agency_comment(
        create_agency_comment_payload(
            ctx["app"]["id"], agency="EPA", comment_type="ADVISORY",
            comment_text="Out of lane",
        ),
        district_engineer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_corner_officer_exclusive_case_ops(api, reviewer_headers):
    """PRD §2.1: "If the role is valid but does not appear in the endpoint's
    authorized role list, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."
    PRD §4: POST /wetland-permits/enforcement-cases is authorized for
    EnforcementOfficer only.

    Design: Corner/rbac/corner_officer_exclusive_case_ops
    """
    applicant, site = setup_applicant_and_site()
    resp = api.create_enforcement_case(
        create_enforcement_case_payload(site["id"], applicant["id"]),
        reviewer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_corner_admin_exclusive_provisioning(api, reviewer_headers):
    """PRD §2.1: "If the role is valid but does not appear in the endpoint's
    authorized role list, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."
    PRD §4: POST /wetland-permits/applicants is authorized for SystemAdmin
    only.

    Design: Corner/rbac/corner_admin_exclusive_provisioning
    """
    resp = api.create_applicant(
        create_applicant_payload(legal_name="Rogue Registrant"),
        reviewer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_corner_case_opener_cannot_confirm(api, officer_opener_headers):
    """PRD §3.9: "Confirmation is a second officer's act: confirming the
    violation is rejected with `ERR_SEGREGATION_OF_DUTIES` when the caller's
    `X-User-ID` equals the case's `opened_by_officer_id`."
    PRD §2.9: "Confirming a violation is rejected with the same error when
    the caller's `X-User-ID` equals the case's recorded
    `opened_by_officer_id` — the officer who opens a case may never be the
    one who confirms it."

    The opener (eo-1) is rejected; a second officer confirms.

    Design: Corner/rbac/corner_case_opener_cannot_confirm
    """
    _, _, case = setup_case_opened(1.0)
    assert case["opened_by_officer_id"] == "eo-1"

    resp = api.confirm_violation(case["id"], officer_opener_headers)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    case = confirm_case(case)
    assert case["case_status"] == "VIOLATION_CONFIRMED"


def test_corner_screener_cannot_issue(api, decision_engineer_headers):
    """PRD §2.9: "Rendering a permit decision is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) when the caller's `X-User-ID`
    equals the application's recorded `screening_reviewer_id`."

    With every other issuance gate satisfied (FAVORABLE public interest
    outcome, plan CREDITS_SECURED), the screening reviewer's own id still
    cannot render the decision; a fresh district engineer can.

    Design: Corner/rbac/corner_screener_cannot_issue
    """
    ctx = setup_application_decision_pending()
    ctx = setup_secured_bank_credits_plan(ctx)
    app = ctx["app"]
    assert app["pir_outcome"] == "FAVORABLE"
    assert ctx["plan"]["status"] == "CREDITS_SECURED"

    resp = api.render_decision(
        app["id"],
        render_decision_payload("ISSUE"),
        make_district_engineer_headers(app["screening_reviewer_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    app = render_decision(app, "ISSUE")
    assert app["status"] == "ISSUED", "an uninvolved district engineer decides"
