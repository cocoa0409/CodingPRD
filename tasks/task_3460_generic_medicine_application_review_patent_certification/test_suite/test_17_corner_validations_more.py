"""Queue B / validations: waiver gate, NCE window, P4-notice precondition."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    set_clock, make_applicant, make_reference_product, make_application,
    add_be_study, make_facility, schedule_inspection, record_outcome,
    submit_application, get_application, setup_submitted,
    make_applicant_headers,
)

REVIEWER = TEST_USERS["regulatory_reviewer_headers"]
INSPECTOR = TEST_USERS["facility_inspector_headers"]


def test_foreign_facility_waiver_rejected():
    """PRD section 3.6: "`WAIVED` is reserved for a domestic facility — its
    `is_foreign` must be false — that has another inspection recorded
    `PASSED` with an `outcome_date` within the 24 calendar months preceding
    the waiver; a waiver for a foreign site, or one without that prior pass,
    fails with `ERR_FOREIGN_FACILITY_WAIVER`."

    Design: Corner/validations/foreign_facility_waiver_rejected
    """
    applicant = make_applicant(legal_name="Foreign Fill Co", headquarters_country="IN")
    rld = make_reference_product(brand_name="Forex")
    app = make_application(rld["id"], applicant["id"])
    facility = make_facility(applicant["id"], facility_name="Goa Plant",
                             fei_number="FEI-IN-1", country_code="IN")
    assert facility["is_foreign"] is True, "is_foreign derives from country_code != US"
    insp = schedule_inspection(facility["id"], app["id"],
                               scheduled_start_date="2026-09-10",
                               scheduled_end_date="2026-09-12")

    resp = api_client.record_inspection_outcome(insp["id"], {"outcome": "WAIVED"}, INSPECTOR)
    validate_error(resp, ApiErrorId.ERR_FOREIGN_FACILITY_WAIVER)
    assert resp.status_code == 422
    stayed = validate_success(api_client.get_inspection(insp["id"], REVIEWER), 200)
    assert stayed["status"] == "SCHEDULED"


def test_nce_full_bar_five_year_window_without_p4():
    """PRD section 3.3: "beginning exactly on that 48-month date and running
    until the date 60 calendar months after `rld_approval_date`, filing is
    permitted only when the application carries at least one
    `PARAGRAPH_IV_CHALLENGE` certification; on or after the 60-month date,
    filing is unrestricted."

    Design: Corner/validations/nce_full_bar_five_year_window_without_p4
    """
    applicant = make_applicant(legal_name="Full Bar Co")
    rld = make_reference_product(brand_name="Fullbarx", rld_approval_date="2022-12-10",
                                 is_new_chemical_entity=True,
                                 indication_codes=["IND-ONC"],
                                 patent_owner_user_id="innovator-ops-76")
    app = make_application(rld["id"], applicant["id"])
    add_be_study(app["id"], applicant["id"], analyte="fullbarxol")
    headers = make_applicant_headers(applicant["id"])

    set_clock("2027-06-01T00:00:00Z")
    resp = api_client.submit_application(app["id"], headers)
    validate_error(resp, ApiErrorId.ERR_NCE_SUBMISSION_BARRED)
    assert resp.status_code == 422, "inside the [48, 60) month window without a P4"

    set_clock("2027-12-10T00:00:00Z")
    submitted = validate_success(api_client.submit_application(app["id"], headers), 200)
    assert submitted["status"] == "RECEIVED", "the bar lifts entirely at month 60"


def test_domestic_waiver_with_recent_prior_pass_succeeds_and_clears():
    """PRD section 3.6: "`WAIVED` is reserved for a domestic facility — its
    `is_foreign` must be false — that has another inspection recorded
    `PASSED` with an `outcome_date` within the 24 calendar months preceding
    the waiver" and "Clearance demands that every facility's latest outcome
    be `PASSED` or `WAIVED`".

    Design: Corner/validations/domestic_waiver_with_recent_prior_pass_succeeds_and_clears
    """
    applicant = make_applicant(legal_name="Waiver Co")
    rld = make_reference_product(brand_name="Waivex")
    app = make_application(rld["id"], applicant["id"])
    add_be_study(app["id"], applicant["id"])
    facility = make_facility(applicant["id"], facility_name="WV Plant")
    insp1 = schedule_inspection(facility["id"], app["id"],
                                scheduled_start_date="2026-09-05",
                                scheduled_end_date="2026-09-07")
    record_outcome(insp1["id"], "PASSED")
    submit_application(app["id"], applicant["id"])

    set_clock("2027-06-01T00:00:00Z")
    insp2 = schedule_inspection(facility["id"], app["id"],
                                scheduled_start_date="2027-06-10",
                                scheduled_end_date="2027-06-12")
    waived = record_outcome(insp2["id"], "WAIVED")
    assert waived["status"] == "WAIVED", (
        "a PASSED outcome 9 months earlier satisfies the 24-month rule")

    decided = validate_success(api_client.approval_decision(
        app["id"], {"decision": "APPROVE"}, REVIEWER), 200)
    assert decided["status"] == "APPROVED", "latest outcome WAIVED clears a domestic site"


def test_approval_with_unnoticed_p4_certification_returns_notice_required():
    """PRD section 3.7: the scientific gates demand "every paragraph-IV
    certification still standing `CERTIFIED` carrying its notice
    (`ERR_P4_NOTICE_REQUIRED`)".

    Design: Corner/validations/approval_with_unnoticed_p4_certification_returns_notice_required
    """
    ctx = setup_submitted(with_facility=True, patent_expiry="2030-01-01",
                          cert_type="PARAGRAPH_IV_CHALLENGE")
    app_id = ctx["app"]["id"]

    resp = api_client.approval_decision(app_id, {"decision": "APPROVE"}, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_P4_NOTICE_REQUIRED)
    assert resp.status_code == 422
    after = get_application(app_id)
    assert after["status"] == "RECEIVED"
    assert after["approval_date"] is None and after["tentative_approval_date"] is None
