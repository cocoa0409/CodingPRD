"""Queue A: priority_pair_validation_conflict — first-failure-wins ordering."""
from test_helpers import (
    api_client, validate_error, TEST_USERS, ApiErrorId,
    make_applicant, make_reference_product, make_application, add_be_study,
    make_facility, schedule_inspection, record_outcome, submit_application,
    make_protected_indication, make_applicant_headers,
)

REVIEWER = TEST_USERS["regulatory_reviewer_headers"]


def test_submit_state_error_beats_nce_temporal_error():
    """PRD section 2.7: "When more than one rule could reject the same
    request, the server evaluates its checks in a fixed order and reports the
    first failure encountered" — state preconditions (step 7,
    `ERR_INVALID_STATE`) precede the NCE bar (step 11,
    `ERR_NCE_SUBMISSION_BARRED`). A submit on a WITHDRAWN application inside
    the NCE bar window returns the state error only.

    Design: Difficulty/priority_pair_validation_conflict/submit_state_error_beats_nce_temporal_error
    """
    applicant = make_applicant(legal_name="Conflict Generics")
    rld = make_reference_product(brand_name="Newentitex",
                                 rld_approval_date="2025-06-15",
                                 is_new_chemical_entity=True,
                                 indication_codes=["IND-HTN"],
                                 patent_owner_user_id="innovator-ops-10")
    app = make_application(rld["id"], applicant["id"])
    headers = make_applicant_headers(applicant["id"])
    api_client.withdraw_application(app["id"], headers)

    resp = api_client.submit_application(app["id"], headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409, (
        f"state failure must surface, not the NCE bar: {resp.status_code}")
    assert resp.json()["data"]["error_id"] != "ERR_NCE_SUBMISSION_BARRED", (
        "2026-09-01 < rld_approval_date + 48 months also fails, but loses")


def test_approval_facility_safety_beats_carveout_constraint():
    """PRD section 2.7: "Ninth, facility clearance at the approval decision
    (`ERR_FACILITY_CLEARANCE_FAILED`)." precedes "Fourteenth, carve-out
    completeness in both directions, checked at application creation, at
    filing, and at the approval decision (`ERR_LABEL_CARVE_OUT_INCOMPLETE`,
    `ERR_CARVE_OUT_OF_UNPROTECTED`)." With a FAILED latest inspection AND a
    drifted protection registry, the facility error wins.

    Design: Difficulty/priority_pair_validation_conflict/approval_facility_safety_beats_carveout_constraint
    """
    applicant = make_applicant(legal_name="Drift Generics")
    rld = make_reference_product(brand_name="Driftex", indication_codes=["IND-A", "IND-B"],
                                 patent_owner_user_id="innovator-ops-11")
    app = make_application(rld["id"], applicant["id"])
    add_be_study(app["id"], applicant["id"])
    facility = make_facility(applicant["id"])
    inspection = schedule_inspection(facility["id"], app["id"])
    submit_application(app["id"], applicant["id"])

    # Registry drift after filing: IND-A becomes actively protected.
    make_protected_indication(rld["id"], indication_code="IND-A",
                              effective_from="2026-01-01", protected_until="2028-01-01")
    record_outcome(inspection["id"], "FAILED")

    resp = api_client.approval_decision(app["id"], {"decision": "APPROVE"}, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_FACILITY_CLEARANCE_FAILED)
    assert resp.status_code == 422
    assert resp.json()["data"]["error_id"] != "ERR_LABEL_CARVE_OUT_INCOMPLETE", (
        "business_safety (step 9) beats business_constraint (step 14)")
