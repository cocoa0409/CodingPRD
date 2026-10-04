"""Queue A: boundary_precision_check — X-1 / X / X+1 on pinned thresholds."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId,
    make_applicant, make_reference_product, make_application,
    make_applicant_headers, set_clock, setup_submitted,  # noqa: F401
    make_listed_patent, add_certification, add_be_study,
)
from test_helpers import TEST_USERS  # noqa: F401


def test_be_ci_upper_bound_inclusive_boundary():
    """PRD section 2.9: "The two regulatory bounds themselves are expressed to
    two decimals — 80.00 and 125.00 — and comparisons against them are
    inclusive." A study whose rounded bounds sit exactly on 80.00 and 125.00
    is ACCEPTED; an upper bound of 125.01 is DEFICIENT.

    Design: Difficulty/boundary_precision_check/be_ci_upper_bound_inclusive_boundary
    """
    applicant = make_applicant(legal_name="Boundary Bio")
    rld = make_reference_product(brand_name="Boundex")
    app = make_application(rld["id"], applicant["id"])
    headers = make_applicant_headers(applicant["id"])
    base = {"analyte": "boundexol", "cmax_ratio_pct": 99.0,
            "cmax_ci_low_pct": 90.0, "cmax_ci_high_pct": 110.0}

    edge_ok = validate_success(api_client.create_be_study(app["id"], {
        **base, "study_type": "FASTING", "auc_ratio_pct": 100.0,
        "auc_ci_low_pct": 80.0, "auc_ci_high_pct": 125.0}, headers), 201)
    assert edge_ok["status"] == "ACCEPTED", "both bounds exactly on the limits pass"

    edge_fail = validate_success(api_client.create_be_study(app["id"], {
        **base, "study_type": "FED", "auc_ratio_pct": 100.5,
        "auc_ci_low_pct": 82.0, "auc_ci_high_pct": 125.01}, headers), 201)
    assert edge_fail["status"] == "DEFICIENT", (
        "125.01 exceeds 125.00 by one hundredth of a percent")


def test_nce_p4_bar_exact_four_year_date():
    """PRD section 3.3: "The boundaries are inclusive — a filing made exactly
    on the 48-month date with a paragraph-IV certification succeeds, while one
    day earlier is barred." For an NCE product approved 2022-12-10, submit on
    2026-12-09 is ERR_NCE_SUBMISSION_BARRED; on 2026-12-10 it is RECEIVED.

    Design: Difficulty/boundary_precision_check/nce_p4_bar_exact_four_year_date
    """
    applicant = make_applicant(legal_name="Dateline Generics")
    rld = make_reference_product(brand_name="Ncebrand", strength="120 mg",
                                 dosage_form="INJECTION",
                                 rld_approval_date="2022-12-10",
                                 is_new_chemical_entity=True,
                                 indication_codes=["IND-ONC"],
                                 patent_owner_user_id="innovator-ops-13")
    patent = make_listed_patent(rld, patent_number="US9500006", expiry_date="2030-01-01")
    app = make_application(rld["id"], applicant["id"])
    add_be_study(app["id"], applicant["id"], analyte="ncebrandle")
    add_certification(app["id"], applicant["id"], patent["id"],
                      "PARAGRAPH_IV_CHALLENGE")
    headers = make_applicant_headers(applicant["id"])

    set_clock("2026-12-09T00:00:00Z")
    resp = api_client.submit_application(app["id"], headers)
    validate_error(resp, ApiErrorId.ERR_NCE_SUBMISSION_BARRED)
    assert resp.status_code == 422, "one day before the 48-month mark is barred"

    set_clock("2026-12-10T00:00:00Z")
    submitted = validate_success(api_client.submit_application(app["id"], headers), 200)
    assert submitted["status"] == "RECEIVED"
    assert submitted["received_date"] == "2026-12-10", (
        "the 48-month date itself is inclusive with a P4 certification present")
