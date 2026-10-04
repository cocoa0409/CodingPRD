"""Queue B / state_machines: side effects, window close, terminal creation."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    set_clock, setup_submitted, setup_approved, send_notice, list_awards,
    get_application, make_applicant_headers,
)

REVIEWER = TEST_USERS["regulatory_reviewer_headers"]


def test_certification_amend_forfeits_eligible_award():
    """PRD section 3.4: "The amendment is one-way to paragraph III: the
    certification moves to `AMENDED_TO_P3`, is treated thereafter as
    `PARAGRAPH_III_DEFER` (deferring to the patent's expiry), stamps
    `amended_date`, recomputes the application's `patent_blocked_until`,
    forfeits an `ELIGIBLE` or `AWARDED` exclusivity award with reason
    `CERTIFICATION_AMENDED` (with the sibling unblocking and re-evaluation of
    §3.8), and advances the application's `version` by one."

    Design: Corner/state_machines/certification_amend_forfeits_eligible_award
    """
    ctx = setup_submitted(patent_expiry="2031-01-01",
                          cert_type="PARAGRAPH_IV_CHALLENGE")
    app_id, ac_id = ctx["app"]["id"], ctx["applicant"]["id"]
    awards = list_awards(application_id=app_id)
    assert len(awards) == 1 and awards[0]["status"] == "ELIGIBLE"

    amended = validate_success(api_client.amend_certification(
        ctx["cert"]["id"], make_applicant_headers(ac_id)), 200)
    assert amended["status"] == "AMENDED_TO_P3"
    assert amended["amended_date"] == "2026-09-01"

    award = validate_success(api_client.get_exclusivity_award(awards[0]["id"], REVIEWER), 200)
    assert award["status"] == "FORFEITED"
    assert award["forfeiture_reason"] == "CERTIFICATION_AMENDED"
    all_awards = list_awards(reference_product_id=ctx["rld"]["id"])
    assert len(all_awards) == 1, "no successor award is created for the product"


def test_notice_window_close_without_suit_transitions_no_suit_filed():
    """PRD section 3.4: "Should the logical clock pass the suit deadline with
    no suit recorded, the notice settles into `NO_SUIT_FILED` and no stay ever
    attaches — under the system's pinned optimistic posture, an open suit
    window contributes nothing to any block."

    Design: Corner/state_machines/notice_window_close_without_suit_transitions_no_suit_filed
    """
    ctx = setup_submitted(patent_expiry="2030-06-30",
                          cert_type="PARAGRAPH_IV_CHALLENGE")
    set_clock("2026-09-05T00:00:00Z")
    notice = send_notice(ctx["cert"]["id"], ctx["applicant"]["id"])
    assert notice["suit_deadline"] == "2026-10-20", "notice 2026-09-05 + 45 days"

    set_clock("2026-10-21T00:00:00Z")
    notices = validate_success(api_client.list_notices(ctx["cert"]["id"], REVIEWER), 200)
    assert notices[0]["status"] == "NO_SUIT_FILED"
    assert notices[0]["stay_until"] is None, "no stay ever attaches to a closed window"


def test_annual_report_supplement_is_logged_and_not_reviewable():
    """PRD section 3.9: "except annual reports, which are born `LOGGED`,
    terminal and never reviewable" and "an `ANNUAL_REPORT` supplement arrives
    `LOGGED` and `EFFECTIVE`, likewise effective on its submission date"; a
    later decision attempt is refused — "an annual report is never decidable
    at all (`ERR_SUPPLEMENT_NOT_REVIEWABLE`)."

    Design: Corner/state_machines/annual_report_supplement_is_logged_and_not_reviewable
    """
    ctx = setup_approved()
    app_id, ac_id = ctx["app"]["id"], ctx["applicant"]["id"]
    supp = validate_success(api_client.create_supplement(app_id, {
        "change_type": "EDITORIAL", "pathway": "ANNUAL_REPORT",
        "description": "typo fix in label"}, make_applicant_headers(ac_id)), 201)
    assert supp["review_status"] == "LOGGED"
    assert supp["effectivity"] == "EFFECTIVE"
    assert supp["effective_date"] == "2026-09-01"

    resp = api_client.supplement_review_decision(supp["id"], {"decision": "APPROVE"}, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_SUPPLEMENT_NOT_REVIEWABLE)
    assert resp.status_code == 409
    assert get_application(app_id)["open_supplement_count"] == 0, (
        "LOGGED is terminal at creation, so the tally never moved")
