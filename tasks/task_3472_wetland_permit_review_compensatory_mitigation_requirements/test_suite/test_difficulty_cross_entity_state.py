"""Difficulty queue — cross-entity state dependencies (PRD §3.3, §3.4).

Application submission is gated on the referenced determination's state and
determination value; plan creation is gated on the alternatives analysis
being ACCEPTED.
"""
from test_helpers import (
    AaVerdict,
    ApiErrorId,
    ApplicationStatus,
    assert_credit_requirement,
    create_aa,
    create_application,
    create_applicant,
    create_jd,
    create_mitigation_plan_payload,
    create_plan,
    create_site,
    issue_jd,
    make_applicant_headers,
    review_aa,
    setup_application_in_alternatives_review,
    validate_error,
    validate_success,
)


def test_submit_requires_jurisdictional_jd(api, reviewer_headers):
    """PRD §3.3: "The referenced determination must be `ISSUED` (else
    `ERR_JD_INVALID_STATE` at the state tier), must be unexpired — the
    current clock no later than its `expiration_date`, with expiry exactly at
    the clock still acceptable, else `ERR_JD_EXPIRED` (HTTP 409) — and must
    carry a `JURISDICTIONAL` determination, else `ERR_JD_NOT_JURISDICTIONAL`
    (HTTP 422); a `NON_JURISDICTIONAL` site needs no permit at all."

    An ISSUED but NON_JURISDICTIONAL determination and a never-issued DRAFT
    determination produce the two distinct errors, and both applications
    remain in DRAFT.

    Design: Difficulty/cross_entity_state_dependency/submit_requires_jurisdictional_jd
    """
    applicant = create_applicant()
    site = create_site(applicant, resource_types_present=["FORESTED_WETLAND"])
    jd_nj = create_jd(
        site, determination="NON_JURISDICTIONAL",
        rationale="Isolated wetland, no interstate commerce nexus",
    )
    jd_nj = issue_jd(jd_nj)
    jd_draft = create_jd(site, rationale="Second delineation under review")

    headers = make_applicant_headers(applicant["id"])
    app1 = create_application(site, jd_nj, applicant)
    resp = api.submit_application(app1["id"], headers)
    validate_error(resp, ApiErrorId.ERR_JD_NOT_JURISDICTIONAL)

    app2 = create_application(site, jd_draft, applicant)
    resp = api.submit_application(app2["id"], headers)
    validate_error(resp, ApiErrorId.ERR_JD_INVALID_STATE)

    app1_after = validate_success(api.get_application(app1["id"], reviewer_headers))
    app2_after = validate_success(api.get_application(app2["id"], reviewer_headers))
    assert app1_after["status"] == ApplicationStatus.DRAFT.value
    assert app2_after["status"] == ApplicationStatus.DRAFT.value


def test_plan_creation_requires_accepted_alternatives(api):
    """PRD §3.4: "The sequencing principle binds two later steps: creating a
    mitigation plan for an `INDIVIDUAL` or `ATF_INDIVIDUAL` application
    requires the analysis to already be `ACCEPTED`, and publishing the public
    notice requires the same — both fail with `ERR_AA_NOT_ACCEPTED` (HTTP
    422) otherwise."

    While the analysis is merely SUBMITTED, plan creation is rejected; the
    moment the ACCEPT verdict lands, the identical plan creation succeeds
    with the provisional requirement {FORESTED_WETLAND: 6.00}.

    Design: Difficulty/cross_entity_state_dependency/plan_creation_requires_accepted_alternatives
    """
    ctx = setup_application_in_alternatives_review()
    app, applicant = ctx["app"], ctx["applicant"]
    aa = create_aa(app, applicant)  # SUBMITTED, not yet reviewed

    headers = make_applicant_headers(applicant["id"])
    resp = api.create_mitigation_plan(
        create_mitigation_plan_payload(app["id"]), headers
    )
    validate_error(resp, ApiErrorId.ERR_AA_NOT_ACCEPTED)

    review_aa(aa, AaVerdict.ACCEPT.value)
    plan = create_plan(app, applicant)
    assert plan["status"] == "DRAFT"
    assert_credit_requirement(plan, {"FORESTED_WETLAND": 6.00})
