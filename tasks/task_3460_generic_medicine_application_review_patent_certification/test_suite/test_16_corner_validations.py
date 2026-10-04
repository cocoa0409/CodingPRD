"""Queue B / validations: BE gate, referential errors, uniqueness, ordering."""
from test_helpers import (
    api_client, validate_error, ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    make_applicant, make_reference_product, make_application, add_be_study,
    make_listed_patent, add_certification, get_application,
    make_protected_indication, make_applicant_headers,
)

REVIEWER = TEST_USERS["regulatory_reviewer_headers"]


def test_submit_without_accepted_be_returns_no_adequate_be_study():
    """PRD section 3.3: "the application must be a draft (`ERR_INVALID_STATE`);
    at least one study must stand `ACCEPTED` (`ERR_NO_ADEQUATE_BE_STUDY`)" —
    an application whose only study is DEFICIENT fails the filing gate.

    Design: Corner/validations/submit_without_accepted_be_returns_no_adequate_be_study
    """
    applicant = make_applicant(legal_name="No Be Co")
    rld = make_reference_product(brand_name="Nobex")
    app = make_application(rld["id"], applicant["id"])
    add_be_study(app["id"], applicant["id"], auc_ci_low_pct=78.0,
                 auc_ci_high_pct=124.0)

    resp = api_client.submit_application(app["id"], make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_ADEQUATE_BE_STUDY)
    assert resp.status_code == 422
    after = get_application(app["id"])
    assert after["status"] == "DRAFT"
    assert after["received_date"] is None and after["current_cycle_number"] == 0


def test_certification_for_patent_of_other_rld_returns_referential_error():
    """PRD section 3.3: "The patent must be one listed on the application's
    own reference product (`ERR_PATENT_NOT_LISTED_FOR_REFERENCE_PRODUCT`)".

    Design: Corner/validations/certification_for_patent_of_other_rld_returns_referential_error
    """
    applicant = make_applicant(legal_name="Cross Ref Co")
    owner = "innovator-ops-71"
    rld1 = make_reference_product(brand_name="CrossOne", patent_owner_user_id=owner)
    rld2 = make_reference_product(brand_name="CrossTwo", patent_owner_user_id=owner)
    pat2 = make_listed_patent(rld2, patent_number="US1313001",
                              patent_type="DRUG_PRODUCT", expiry_date="2029-12-31")
    app = make_application(rld1["id"], applicant["id"])
    version = get_application(app["id"])["version"]

    resp = api_client.create_patent_certification(app["id"], {
        "patent_id": pat2["id"], "certification_type": "PARAGRAPH_III_DEFER",
        "expected_application_version": version},
        make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_PATENT_NOT_LISTED_FOR_REFERENCE_PRODUCT)
    assert resp.status_code == 409, "both ids exist; the cross-product link still fails"


def test_duplicate_certification_for_same_patent_returns_conflict():
    """PRD section 3.3: "a second certification for the same
    application-and-patent pair is refused as `ERR_DUPLICATE_CERTIFICATION`."

    Design: Corner/validations/duplicate_certification_for_same_patent_returns_conflict
    """
    applicant = make_applicant(legal_name="Dup Cert Co")
    rld = make_reference_product(brand_name="Dupex",
                                 patent_owner_user_id="innovator-ops-72")
    patent = make_listed_patent(rld, patent_number="US1414001", expiry_date="2029-06-30")
    app = make_application(rld["id"], applicant["id"])
    add_certification(app["id"], applicant["id"], patent["id"], "PARAGRAPH_III_DEFER")
    fresh_version = get_application(app["id"])["version"]

    resp = api_client.create_patent_certification(app["id"], {
        "patent_id": patent["id"], "certification_type": "PARAGRAPH_IV_CHALLENGE",
        "expected_application_version": fresh_version},
        make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CERTIFICATION)
    assert resp.status_code == 409, (
        "the fresh version passes OCC; pair uniqueness fails later")


def test_unknown_path_id_returns_404_before_state_checks():
    """PRD section 2.8: "Existence of the parent container is always settled
    before any rule that depends on the child." PRD section 2.7 orders
    identifier resolution (step 4) before state preconditions (step 7).

    Design: Corner/validations/unknown_path_id_returns_404_before_state_checks
    """
    applicant = make_applicant(legal_name="Order Co")
    rld = make_reference_product(brand_name="Orderex")
    app = make_application(rld["id"], applicant["id"])
    api_client.withdraw_application(app["id"], make_applicant_headers(applicant["id"]))

    missing = api_client.approval_decision(
        NON_EXISTENT_UUID, {"decision": "APPROVE"}, REVIEWER)
    validate_error(missing, ApiErrorId.ERR_APPLICATION_NOT_FOUND)
    assert missing.status_code == 404

    withdrawn = api_client.approval_decision(app["id"], {"decision": "APPROVE"}, REVIEWER)
    validate_error(withdrawn, ApiErrorId.ERR_INVALID_STATE)
    assert withdrawn.status_code == 409


def test_carve_out_of_unprotected_indication_returns_error():
    """PRD section 3.3: "a carved code that names an indication under no
    active protection fails with `ERR_CARVE_OUT_OF_UNPROTECTED`" — checked at
    application creation (PRD section 2.7 step 14).

    Design: Corner/validations/carve_out_of_unprotected_indication_returns_error
    """
    applicant = make_applicant(legal_name="Carve Co")
    rld = make_reference_product(brand_name="Carvex",
                                 indication_codes=["IND-A", "IND-B"],
                                 patent_owner_user_id="innovator-ops-74")
    make_protected_indication(rld["id"], indication_code="IND-A",
                              effective_from="2026-01-01", protected_until="2028-01-01")
    resp = api_client.create_application({
        "reference_product_id": rld["id"], "applicant_id": applicant["id"],
        "review_priority": "STANDARD", "labeling_mode": "CARVE_OUT",
        "carved_indication_codes": ["IND-A", "IND-B"]},
        make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_CARVE_OUT_OF_UNPROTECTED)
    assert resp.status_code == 422, "IND-B has no ACTIVE protection, so over-carving fails"
