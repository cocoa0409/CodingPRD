"""Queue A: dual_variant_calc — pinned variants of dual-reading calculations."""
from test_helpers import (
    api_client, validate_success, make_applicant_headers,
    make_applicant, make_reference_product, make_application, add_be_study,
    submit_application, set_clock, setup_submitted, send_notice, get_application,
    assert_be_study,
)
from test_helpers import TEST_USERS

REVIEWER = TEST_USERS["regulatory_reviewer_headers"]


def test_be_per_study_verdict_not_pooled_average():
    """PRD section 3.3: "Each study is judged on its own numbers; bounds are
    never averaged or pooled across studies." Study A (rounded AUC lower bound
    79.00) fails on its own while study B (80.20) passes, so the application is
    submittable on the strength of the single ACCEPTED study — a pooled average
    of 79.60 would have failed both.

    Design: Difficulty/dual_variant_calc/be_per_study_vs_pooled_average_verdict
    """
    applicant = make_applicant(legal_name="Teva-like Generics LLC")
    rld = make_reference_product(brand_name="Brandex", rld_approval_date="2020-01-15",
                                 indication_codes=["IND-HTN"])
    app = make_application(rld["id"], applicant["id"])
    headers = make_applicant_headers(applicant["id"])

    resp_a = api_client.create_be_study(app["id"], {
        "study_type": "FASTING", "analyte": "brandexol", "auc_ratio_pct": 101.0,
        "auc_ci_low_pct": 79.0, "auc_ci_high_pct": 124.9, "cmax_ratio_pct": 99.0,
        "cmax_ci_low_pct": 81.0, "cmax_ci_high_pct": 124.0}, headers)
    study_a = validate_success(resp_a, 201)
    assert_be_study(study_a)
    assert study_a["is_adequate"] is False and study_a["status"] == "DEFICIENT", (
        f"study A must fail alone on rounded lower bound 79.00: {study_a}")

    resp_b = api_client.create_be_study(app["id"], {
        "study_type": "FED", "analyte": "brandexol", "auc_ratio_pct": 100.0,
        "auc_ci_low_pct": 80.2, "auc_ci_high_pct": 124.9, "cmax_ratio_pct": 99.5,
        "cmax_ci_low_pct": 85.0, "cmax_ci_high_pct": 120.0}, headers)
    study_b = validate_success(resp_b, 201)
    assert study_b["is_adequate"] is True and study_b["status"] == "ACCEPTED", (
        f"study B must pass alone: {study_b}")

    submitted = validate_success(api_client.submit_application(app["id"], headers), 200)
    assert submitted["status"] == "RECEIVED", (
        "one ACCEPTED study suffices; pooled averaging would have barred submit")


def test_approval_posture_open_suit_window_does_not_block():
    """PRD section 3.4: "Should the logical clock pass the suit deadline with no
    suit recorded, the notice settles into `NO_SUIT_FILED` and no stay ever
    attaches — under the system's pinned optimistic posture, an open suit window
    contributes nothing to any block." With the notice sent and the 45-day
    window still open, APPROVE yields full APPROVED, not TENTATIVE_APPROVAL.

    Design: Difficulty/dual_variant_calc/approval_posture_optimistic_vs_conservative_window
    """
    ctx = setup_submitted(with_facility=True, patent_expiry="2030-06-30",
                          cert_type="PARAGRAPH_IV_CHALLENGE",
                          rld_overrides={"brand_name": "Patentex",
                                         "patent_owner_user_id": "innovator-ops-9"})
    app_id = ctx["app"]["id"]
    ac_id = ctx["applicant"]["id"]

    set_clock("2026-09-10T00:00:00Z")
    notice = send_notice(ctx["cert"]["id"], ac_id)
    assert notice["is_timely"] is True, "notice on day 9 is timely"
    assert notice["suit_deadline"] == "2026-10-25", (
        f"suit_deadline must be notice_date + 45 days, got {notice['suit_deadline']}")
    assert notice["status"] == "NOTICE_SENT"

    set_clock("2026-09-15T00:00:00Z")
    decided = validate_success(
        api_client.approval_decision(app_id, {"decision": "APPROVE"}, REVIEWER), 200)
    assert decided["status"] == "APPROVED", (
        f"open suit window must not block approval, got {decided['status']}")
    assert decided["approval_date"] == "2026-09-15"
    assert get_application(app_id)["patent_blocked_until"] is None
