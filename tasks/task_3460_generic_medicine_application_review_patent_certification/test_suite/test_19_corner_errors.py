"""Queue B / errors: every entity-specific 404 in the catalogue is reachable."""
from test_helpers import (
    api_client, validate_error, ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    make_applicant, make_reference_product, make_application,
    make_applicant_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
REVIEWER = TEST_USERS["regulatory_reviewer_headers"]


def test_unknown_ids_return_entity_specific_404s():
    """PRD section 2.7: "Fourth, identifiers must resolve: path identifiers
    are validated left to right, then body-referenced identifiers
    (`reference_product_id`, `patent_id`, `facility_id`, `application_id`) in
    the endpoint's input declaration order, each unresolvable identifier
    producing its own 404 — `ERR_APPLICANT_NOT_FOUND`,
    `ERR_REFERENCE_PRODUCT_NOT_FOUND`, `ERR_LISTED_PATENT_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`,
    `ERR_NOTICE_NOT_FOUND`, `ERR_REVIEW_CYCLE_NOT_FOUND`,
    `ERR_FACILITY_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`,
    `ERR_SUPPLEMENT_NOT_FOUND`, or `ERR_EXCLUSIVITY_AWARD_NOT_FOUND`."

    Design: Corner/errors/unknown_ids_return_entity_specific_404s
    """
    ac = make_applicant(legal_name="Sweep Co")
    rld = make_reference_product(brand_name="Sweepex", rld_approval_date="2001-01-01")
    app = make_application(rld["id"], ac["id"])
    headers = make_applicant_headers(ac["id"])
    MISSING = NON_EXISTENT_UUID

    checks = [
        (api_client.get_applicant_company(MISSING, ADMIN),
         ApiErrorId.ERR_APPLICANT_NOT_FOUND),
        (api_client.get_reference_product(MISSING, ADMIN),
         ApiErrorId.ERR_REFERENCE_PRODUCT_NOT_FOUND),
        (api_client.create_patent_certification(app["id"], {
            "patent_id": MISSING, "certification_type": "PARAGRAPH_III_DEFER",
            "expected_application_version": app["version"]}, headers),
         ApiErrorId.ERR_LISTED_PATENT_NOT_FOUND),
        (api_client.get_patent_certification(MISSING, ADMIN),
         ApiErrorId.ERR_CERTIFICATION_NOT_FOUND),
        (api_client.create_litigation_event(MISSING, {
            "event_type": "COURT_DECIDED", "event_date": "2026-09-01",
            "outcome": "PATENT_VALID"}, ADMIN),
         ApiErrorId.ERR_NOTICE_NOT_FOUND),
        (api_client.issue_deficiency(MISSING, {}, REVIEWER),
         ApiErrorId.ERR_REVIEW_CYCLE_NOT_FOUND),
        (api_client.create_inspection({
            "facility_id": MISSING, "application_id": app["id"],
            "scheduled_start_date": "2026-09-10",
            "scheduled_end_date": "2026-09-12"}, REVIEWER),
         ApiErrorId.ERR_FACILITY_NOT_FOUND),
        (api_client.get_inspection(MISSING, ADMIN),
         ApiErrorId.ERR_INSPECTION_NOT_FOUND),
        (api_client.supplement_review_decision(MISSING, {"decision": "APPROVE"}, REVIEWER),
         ApiErrorId.ERR_SUPPLEMENT_NOT_FOUND),
        (api_client.get_exclusivity_award(MISSING, ADMIN),
         ApiErrorId.ERR_EXCLUSIVITY_AWARD_NOT_FOUND),
    ]
    for resp, error_id in checks:
        validate_error(resp, error_id)
        assert resp.status_code == 404, (
            f"{error_id.value} must carry HTTP 404, got {resp.status_code}")
