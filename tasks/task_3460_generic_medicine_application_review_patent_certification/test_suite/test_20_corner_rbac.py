"""Queue B / rbac: ownership pinning, role lists, missing context headers."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_applicant, make_reference_product, make_application, add_be_study,
    submit_application, make_applicant_headers, make_innovator_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
REVIEWER = TEST_USERS["regulatory_reviewer_headers"]


def test_applicant_cannot_amend_other_applicants_application():
    """PRD section 2.1: "ownership checks on any resource that references an
    applicant company compare the resource's `applicant_id` field to
    `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`
    (HTTP 403)" — PRD section 2.7 evaluates ownership (step 3) before the OCC
    token (step 6).

    Design: Corner/rbac/applicant_cannot_amend_other_applicants_application
    """
    ac_a = make_applicant(legal_name="Owner A", contact_email="a@oa.example")
    ac_b = make_applicant(legal_name="Owner B", contact_email="b@ob.example")
    rld = make_reference_product(brand_name="Ownex", rld_approval_date="2000-01-01")
    app = make_application(rld["id"], ac_a["id"])
    add_be_study(app["id"], ac_a["id"])
    submit_application(app["id"], ac_a["id"])
    seen_by_b = validate_success(api_client.get_application(
        app["id"], make_applicant_headers(ac_b["id"])), 200)

    resp = api_client.create_amendment(app["id"], {
        "classification": "MINOR", "contains_new_be_data": False,
        "expected_application_version": seen_by_b["version"]},
        make_applicant_headers(ac_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    assert resp.status_code == 403, (
        "a legally observed version does not substitute for ownership")


def test_innovator_can_list_patent_only_for_owned_product():
    """PRD section 2.1: "the server records it as `patent_owner_user_id` on
    each `ReferenceProduct` and compares it against that field when the
    sponsor lists patents or reports an infringement suit, again rejecting
    mismatches with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/innovator_can_list_patent_only_for_owned_product
    """
    rld = make_reference_product(brand_name="Guarded", rld_approval_date="2000-01-01",
                                 patent_owner_user_id="innovator-ops-1")
    payload = {"patent_number": "US1717001", "patent_type": "DRUG_SUBSTANCE",
               "expiry_date": "2030-01-01"}

    denied = api_client.create_listed_patent(
        rld["id"], payload, make_innovator_headers("innovator-ops-999"))
    validate_error(denied, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    assert denied.status_code == 403

    allowed = api_client.create_listed_patent(
        rld["id"], payload, make_innovator_headers("innovator-ops-1"))
    patent = validate_success(allowed, 201)
    assert patent["status"] == "LISTED", (
        "ownership is pinned to the stored field, not the role alone")


def test_reviewer_cannot_register_reference_product():
    """PRD section 2.1: "Every endpoint declares the roles permitted to invoke
    it; a call from any other role is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)." PRD section 4 lists only
    ProgramAdmin for POST /reference-products.

    Design: Corner/rbac/reviewer_cannot_register_reference_product
    """
    resp = api_client.create_reference_product({
        "brand_name": "ReviewerBrand", "active_ingredient": "revol",
        "strength": "53 mg", "dosage_form": "TABLET",
        "rld_approval_date": "2000-01-01", "is_new_chemical_entity": False,
        "indication_codes": ["IND-A"], "patent_owner_user_id": "innovator-ops-1"},
        REVIEWER)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    assert resp.status_code == 403


def test_missing_auth_header_returns_400():
    """PRD section 2.1: "A request missing either header, or carrying a role
    value outside this list, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/rbac/missing_auth_header_returns_400
    """
    resp = api_client.list_applications(headers=None)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    assert resp.status_code == 400, (
        "no X-User-ID / X-User-Role headers are sent, so step 1 fires first")
