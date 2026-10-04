"""Queue A: compensating_invariant — conserved counts across action pairs."""
from test_helpers import (
    api_client, validate_success, TEST_USERS,
    setup_approved, setup_submitted, get_application, list_cycles,
    add_amendment, make_applicant_headers,
)

REVIEWER = TEST_USERS["regulatory_reviewer_headers"]


def test_supplement_submit_withdraw_conserves_open_count():
    """PRD section 3.9: "The parent's `open_supplement_count` — its running
    tally of supplements standing `SUBMITTED` — rises by one for the three
    reviewable pathways" and "Decisions and withdrawals each decrement the
    parent's `open_supplement_count` by one." Create followed by withdraw
    conserves the count bit-identically.

    Design: Difficulty/compensating_invariant/supplement_submit_withdraw_conserves_open_count
    """
    ctx = setup_approved()
    app_id, ac_id = ctx["app"]["id"], ctx["applicant"]["id"]
    assert get_application(app_id)["open_supplement_count"] == 0

    supp = validate_success(api_client.create_supplement(app_id, {
        "change_type": "MANUFACTURING_SITE", "pathway": "PRIOR_APPROVAL",
        "description": "add second site"}, make_applicant_headers(ac_id)), 201)
    assert get_application(app_id)["open_supplement_count"] == 1

    validate_success(api_client.withdraw_supplement(
        supp["id"], make_applicant_headers(ac_id)), 200)
    assert get_application(app_id)["open_supplement_count"] == 0, (
        "the forward action and its compensation conserve the SUBMITTED count")
    rows = validate_success(api_client.list_supplements(app_id, REVIEWER), 200)
    assert rows[0]["review_status"] == "WITHDRAWN"


def test_deficiency_issue_and_response_conserve_open_deficiency_count():
    """PRD section 3.5: "The parent's `open_deficiency_count` rises by one."
    and "whereupon `deficiency_response_received_date` is stamped, the cycle
    moves to `AMENDMENT_RECEIVED`, and the open-deficiency count falls by
    one." A MINOR response perturbs no timeline constant.

    Design: Difficulty/compensating_invariant/deficiency_issue_and_response_conserve_open_deficiency_count
    """
    ctx = setup_submitted()
    app_id, ac_id = ctx["app"]["id"], ctx["applicant"]["id"]
    cycle = list_cycles(app_id)[0]
    assert cycle["goal_date"] == "2027-07-01", "STANDARD base 10 from 2026-09-01"
    assert get_application(app_id)["open_deficiency_count"] == 0

    validate_success(api_client.issue_deficiency(
        cycle["id"], {"deficiency_summary": "labeling format comments"}, REVIEWER), 201)
    assert get_application(app_id)["open_deficiency_count"] == 1

    add_amendment(app_id, ac_id, classification="MINOR",
                  notes="response to labeling comments")
    assert get_application(app_id)["open_deficiency_count"] == 0, (
        "count(CRL_ISSUED cycles) is conserved across the issue/respond pair")
    cycle = list_cycles(app_id)[0]
    assert cycle["status"] == "AMENDMENT_RECEIVED"
    assert cycle["deficiency_response_received_date"] == "2026-09-01"
    assert cycle["goal_date"] == "2027-07-01", "a MINOR amendment moves no date"
