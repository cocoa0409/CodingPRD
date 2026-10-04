"""Queue B / entities: required fields, computed-field policy, enums, parents."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    NON_EXISTENT_UUID, make_applicant, make_reference_product, make_application,
    make_innovator_headers, make_applicant_headers, setup_approved,
)


def test_listed_patent_missing_expiry_date_returns_invalid_request():
    """PRD section 3.2: "Listing a `ListedPatent` requires the
    `patent_number`, a `patent_type` of `DRUG_SUBSTANCE`, `DRUG_PRODUCT`, or
    `METHOD_OF_USE`, and the `expiry_date` on which the patent lapses."
    PRD section 2.7 step 5: required-field absence is `ERR_INVALID_REQUEST`.

    Design: Corner/entities/listed_patent_missing_expiry_date_returns_invalid_request
    """
    rld = make_reference_product(brand_name="Reqpat",
                                 patent_owner_user_id="innovator-ops-52")
    resp = api_client.create_listed_patent(rld["id"], {
        "patent_number": "US1111111", "patent_type": "DRUG_SUBSTANCE"},
        make_innovator_headers("innovator-ops-52"))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert resp.status_code == 400, "omitted required expiry_date is a 400, not a 422"


def test_bioequivalence_study_is_adequate_input_ignored():
    """PRD section 2.7: "Unknown payload fields, and client-supplied system or
    computed fields such as `id`, `created_at`, `version`, `is_adequate`, or
    `status`, are ignored — never echoed and never rejected."

    Design: Corner/entities/bioequivalence_study_is_adequate_input_ignored
    """
    applicant = make_applicant(legal_name="Ignored Input Labs")
    rld = make_reference_product(brand_name="Ignorex")
    app = make_application(rld["id"], applicant["id"])
    resp = api_client.create_be_study(app["id"], {
        "study_type": "FASTING", "analyte": "ignorexol", "auc_ratio_pct": 100.0,
        "auc_ci_low_pct": 92.0, "auc_ci_high_pct": 108.0, "cmax_ratio_pct": 99.0,
        "cmax_ci_low_pct": 90.0, "cmax_ci_high_pct": 110.0,
        "is_adequate": False, "status": "DEFICIENT"},
        make_applicant_headers(applicant["id"]))
    study = validate_success(resp, 201)
    assert study["is_adequate"] is True and study["status"] == "ACCEPTED", (
        "the server computes adequacy from the bounds; client verdicts are ignored")


def test_supplement_change_type_invalid_enum_returns_invalid_request():
    """PRD section 3.9: "Each supplement declares a `change_type` —
    `MANUFACTURING_SITE`, `FORMULATION`, `LABELING`, `PACKAGING`, or
    `EDITORIAL`" — a closed enum; PRD section 2.7 step 5 rejects invalid enum
    members with `ERR_INVALID_REQUEST`.

    Design: Corner/entities/supplement_change_type_invalid_enum_returns_invalid_request
    """
    ctx = setup_approved()
    resp = api_client.create_supplement(ctx["app"]["id"], {
        "change_type": "CRYO_STORAGE", "pathway": "PRIOR_APPROVAL"},
        make_applicant_headers(ctx["applicant"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert resp.status_code == 400, "shape validation runs before any business rule"


def test_patent_certification_under_unknown_application_returns_not_found():
    """PRD section 2.8: "Existence of the parent container is always settled
    before any rule that depends on the child."

    Design: Corner/entities/patent_certification_under_unknown_application_returns_not_found
    """
    applicant = make_applicant(legal_name="Orphan Cert Co")
    rld = make_reference_product(brand_name="Orphanex")
    app = make_application(rld["id"], applicant["id"])
    resp = api_client.create_patent_certification(NON_EXISTENT_UUID, {
        "patent_id": NON_EXISTENT_UUID, "certification_type": "PARAGRAPH_III_DEFER",
        "expected_application_version": app["version"]},
        make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_FOUND)
    assert resp.status_code == 404, "unknown path id 404s before body validation"
