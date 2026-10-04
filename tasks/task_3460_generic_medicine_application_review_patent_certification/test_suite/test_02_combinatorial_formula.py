"""Queue A: combinatorial_formula — multi-input formulas with pinned orders."""
from test_helpers import (
    api_client, validate_success, validate_paginated, TEST_USERS,
    make_applicant, make_reference_product, make_application,
    add_be_study, submit_application, set_clock, setup_submitted,
    make_listed_patent, add_certification, make_facility,
    schedule_and_pass_inspection, send_notice, get_application, list_cycles,
    add_amendment, make_applicant_headers,
)

REVIEWER = TEST_USERS["regulatory_reviewer_headers"]


def test_goal_date_priority_base_plus_stacked_major_extensions():
    """PRD section 3.5: "Its `goal_date` is derived by adding to `opened_date`
    a number of calendar months equal to the base plus three additional months
    for each major amendment applied to the cycle, clamped per the month
    convention and recomputed on every such amendment; there is no cap on
    extensions." PRIORITY base 8 opened 2026-09-01: goal 2027-05-01, then two
    MAJOR amendments stack to 2027-08-01 and 2027-11-01.

    Design: Difficulty/combinatorial_formula/goal_date_priority_base_plus_stacked_major_extensions
    """
    ctx = setup_submitted(priority="PRIORITY")
    app_id, ac_id = ctx["app"]["id"], ctx["applicant"]["id"]

    cycle = list_cycles(app_id)[0]
    assert cycle["cycle_number"] == 1 and cycle["status"] == "OPEN"
    assert cycle["base_review_months"] == 8, "PRIORITY snapshot is 8 months"
    assert cycle["major_amendment_extensions_count"] == 0
    assert cycle["goal_date"] == "2027-05-01", f"8mo from 2026-09-01: {cycle['goal_date']}"

    set_clock("2026-11-01T00:00:00Z")
    validate_success(api_client.issue_deficiency(
        cycle["id"], {"deficiency_summary": "BE statistical review comments"}, REVIEWER), 201)

    set_clock("2027-01-15T00:00:00Z")
    add_amendment(app_id, ac_id, classification="MAJOR", contains_new_be_data=True,
                  notes="new BE data")
    cycle = list_cycles(app_id)[0]
    assert cycle["status"] == "AMENDMENT_RECEIVED"
    assert cycle["major_amendment_extensions_count"] == 1
    assert cycle["goal_date"] == "2027-08-01", f"+3mo extension: {cycle['goal_date']}"

    set_clock("2027-02-01T00:00:00Z")
    add_amendment(app_id, ac_id, classification="MAJOR", contains_new_be_data=False,
                  notes="unsolicited major update")
    cycle = list_cycles(app_id)[0]
    assert cycle["major_amendment_extensions_count"] == 2
    assert cycle["goal_date"] == "2027-11-01", (
        f"second MAJOR stacks another 3 months: {cycle['goal_date']}")


def test_be_round_first_per_bound_vs_compare_raw():
    """PRD section 2.9: "Confidence-interval bounds on bioequivalence studies
    are compared only after each bound has been independently rounded to
    exactly two decimal places using round-half-up decimal arithmetic; the
    rounded values, not the raw submissions, decide adequacy." 125.004 rounds
    to 125.00 and passes the inclusive upper bound; 125.006 rounds to 125.01
    and fails.

    Design: Difficulty/combinatorial_formula/be_round_first_per_bound_vs_compare_raw
    """
    applicant = make_applicant(legal_name="Rounding Generics")
    rld = make_reference_product(brand_name="Roundex")
    app = make_application(rld["id"], applicant["id"])
    headers = make_applicant_headers(applicant["id"])
    base = {"study_type": "FASTING", "analyte": "roundexol", "auc_ratio_pct": 100.0,
            "auc_ci_low_pct": 82.0, "cmax_ratio_pct": 99.0,
            "cmax_ci_low_pct": 90.0, "cmax_ci_high_pct": 110.0}

    st_pass = validate_success(api_client.create_be_study(
        app["id"], {**base, "auc_ci_high_pct": 125.004}, headers), 201)
    assert st_pass["is_adequate"] is True and st_pass["status"] == "ACCEPTED", (
        "round_half_up(125.004, 2) == 125.00 meets the inclusive upper bound")

    st_fail = validate_success(api_client.create_be_study(
        app["id"], {**base, "auc_ci_high_pct": 125.006}, headers), 201)
    assert st_fail["is_adequate"] is False and st_fail["status"] == "DEFICIENT", (
        "round_half_up(125.006, 2) == 125.01 exceeds the inclusive upper bound")


def test_exclusivity_window_anchor_evaluation_order():
    """PRD section 3.8: "The block on siblings persists while the award stands
    `ACTIVE` and the current logical date is earlier than `exclusivity_end_date`;
    when the clock reaches that date the block lifts at the date itself, the
    award settles to `EXPIRED`, siblings recompute `exclusivity_blocked` false,
    and their tentative approvals re-evaluate." First filer A approves
    2026-12-01 and markets 2026-12-10 (end date 2027-06-08); sibling B is
    TENTATIVE_APPROVAL on 2027-06-07 and auto-approves on 2027-06-08.

    Design: Difficulty/combinatorial_formula/exclusivity_window_anchor_evaluation_order
    """
    ac_a = make_applicant(legal_name="First Filer Pharma")
    ac_b = make_applicant(legal_name="Second Filer Pharma")
    rld = make_reference_product(brand_name="Exclusex", rld_approval_date="2015-04-01",
                                 patent_owner_user_id="innovator-ops-4")
    patent = make_listed_patent(rld, patent_number="US9100002",
                                patent_type="DRUG_PRODUCT", expiry_date="2030-01-01")

    def build_and_submit(applicant, analyte):
        app = make_application(rld["id"], applicant["id"])
        add_be_study(app["id"], applicant["id"], analyte=analyte)
        cert = add_certification(app["id"], applicant["id"], patent["id"])
        facility = make_facility(applicant["id"])
        schedule_and_pass_inspection(facility["id"], app["id"])
        return submit_application(app["id"], applicant["id"]), cert

    app_a, cert_a = build_and_submit(ac_a, "exclusexol")
    set_clock("2026-09-02T00:00:00Z")
    app_b, cert_b = build_and_submit(ac_b, "exclusexol")
    set_clock("2026-09-05T00:00:00Z")
    send_notice(cert_a["id"], ac_a["id"])
    set_clock("2026-09-06T00:00:00Z")
    send_notice(cert_b["id"], ac_b["id"])
    set_clock("2026-10-22T00:00:00Z")
    set_clock("2026-12-01T00:00:00Z")
    decided_a = validate_success(api_client.approval_decision(
        app_a["id"], {"decision": "APPROVE"}, REVIEWER), 200)
    assert decided_a["status"] == "APPROVED" and decided_a["approval_date"] == "2026-12-01"

    set_clock("2026-12-10T00:00:00Z")
    award = validate_success(api_client.record_first_marketing(
        app_a["id"], make_applicant_headers(ac_a["id"])), 200)
    assert award["status"] == "ACTIVE"
    assert award["marketing_deadline"] == "2027-02-14", "approval + 75 days"
    assert award["first_marketing_date"] == "2026-12-10"
    assert award["exclusivity_end_date"] == "2027-06-08", "marketing + 180 days"

    set_clock("2027-06-07T00:00:00Z")
    decided_b = validate_success(api_client.approval_decision(
        app_b["id"], {"decision": "APPROVE"}, REVIEWER), 200)
    assert decided_b["status"] == "TENTATIVE_APPROVAL", (
        "2027-06-07 < exclusivity_end_date 2027-06-08, so B is still blocked")

    set_clock("2027-06-08T00:00:00Z")
    app_b_after = get_application(app_b["id"])
    assert app_b_after["status"] == "APPROVED"
    assert app_b_after["approval_date"] == "2027-06-08", (
        "block lifts AT the end date; B auto-approves on re-evaluation")
    rows, _meta = validate_paginated(api_client.list_exclusivity_awards(
        REVIEWER, params={"reference_product_id": rld["id"]}))
    assert len(rows) == 1 and rows[0]["status"] == "EXPIRED"
