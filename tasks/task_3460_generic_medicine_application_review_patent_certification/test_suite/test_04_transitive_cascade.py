"""Queue A: transitive_cascade — depth-3 clock-driven chains."""
from test_helpers import (
    api_client, validate_success, validate_paginated, TEST_USERS,
    set_clock, get_application, list_cycles, list_awards,
    setup_tentative_p3, setup_submitted,
)

REVIEWER = TEST_USERS["regulatory_reviewer_headers"]


def test_patent_expiry_cascade_auto_approves_tentative():
    """PRD section 3.2: "Expiry is consequential: every paragraph-III deferral
    on that patent stops contributing to each referencing application's
    `patent_blocked_until`, any litigation block decided in the patent's favor
    lifts with it, and each tentatively approved application referencing the
    patent is re-evaluated and auto-approves if no block remains."

    Design: Difficulty/transitive_cascade/patent_expiry_cascade_auto_approves_tentative
    """
    ctx = setup_tentative_p3(patent_expiry="2027-02-01")
    app_id, rld_id = ctx["app"]["id"], ctx["rld"]["id"]
    assert ctx["app"]["status"] == "TENTATIVE_APPROVAL"
    assert ctx["app"]["patent_blocked_until"] == "2027-02-01", (
        "P3 deferral blocks until the patent's expiry date")

    set_clock("2027-02-02T00:00:00Z")
    patents, _meta = validate_paginated(api_client.list_listed_patents(rld_id, REVIEWER))
    assert patents[0]["status"] == "EXPIRED", "hop 1: clock passed expiry_date"

    app = get_application(app_id)
    assert app["patent_blocked_until"] is None, (
        "hop 2: the expired patent's deferral no longer contributes")
    assert app["status"] == "APPROVED" and app["approval_date"] == "2027-02-02", (
        "hop 3: automatic re-evaluation approved without any reviewer action")


def test_deficiency_lapse_cascade_forfeits_exclusivity():
    """PRD section 3.5: "Should the logical clock pass the response due date
    with `deficiency_response_received_date` still unset, the cycle lapses: it
    moves to `LAPSED` with `closed_reason` `LAPSED`, the parent application
    collapses to `LAPSED` as well, and an `ELIGIBLE` exclusivity award held by
    that application is forfeited with reason `APPLICATION_LAPSED`, with the
    sibling unblocking and re-evaluation of §3.8."

    Design: Difficulty/transitive_cascade/deficiency_lapse_cascade_forfeits_exclusivity
    """
    ctx = setup_submitted(patent_expiry="2030-01-01",
                          cert_type="PARAGRAPH_IV_CHALLENGE",
                          rld_overrides={"brand_name": "Lapsex",
                                         "patent_owner_user_id": "innovator-ops-8"})
    app_id = ctx["app"]["id"]
    cycle_id = list_cycles(app_id)[0]["id"]
    awards = list_awards(application_id=app_id)
    assert len(awards) == 1 and awards[0]["status"] == "ELIGIBLE"
    award_id = awards[0]["id"]

    set_clock("2026-11-01T00:00:00Z")
    issued = validate_success(api_client.issue_deficiency(
        cycle_id, {"deficiency_summary": "CMC information request"}, REVIEWER), 201)
    assert issued["deficiency_response_due_date"] == "2027-11-01", (
        "issued 2026-11-01 + 12 calendar months")

    set_clock("2027-11-02T00:00:00Z")
    assert list_cycles(app_id)[0]["status"] == "LAPSED", "hop 1: cycle lapses"
    assert get_application(app_id)["status"] == "LAPSED", "hop 2: application lapses"
    award = validate_success(api_client.get_exclusivity_award(award_id, REVIEWER), 200)
    assert award["status"] == "FORFEITED"
    assert award["forfeiture_reason"] == "APPLICATION_LAPSED", (
        "hop 3: lapse at 2027-11-02 precedes the 30-month TA-failure clock "
        "(2029-03-01), so the lapse is the forfeiting event")
