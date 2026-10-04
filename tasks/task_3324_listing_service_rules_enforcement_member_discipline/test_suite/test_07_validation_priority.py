"""Validation priority pairs: segregation beats temporal; OCC before business
checks; source-state legality before the policy/compensation gate; existence
before the member disciplinary gate."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
    create_association, create_member, create_office, create_listing,
    create_dues_period, bill_dues_period, set_clock,
    activate_policy_revision, activate_listing, change_status,
    get_member_invoice, pay_invoice,
    make_member_headers, make_grievance_headers, TEST_USERS, api_client,
)

STAFF = TEST_USERS["staff_headers"]


def test_screening_overdue_loses_to_screener_conflict(api):
    """PRD §2.7: "(7) the member disciplinary and segregation-of-duties gate — `ERR_MEMBER_SUSPENDED`, `ERR_SCREENING_CONFLICT`, `ERR_APPEAL_CONFLICT`, `ERR_PANEL_SOLE_ACTOR`; (8) the policy and compensation gate — `ERR_COMP_DISPLAY_PROHIBITED`, `ERR_RULESET_MISMATCH`, `ERR_LISTING_FLAGGED`; (9) time-window rules — `ERR_HEARING_WINDOW_CLOSED`, `ERR_SCREENING_OVERDUE`, `ERR_APPEAL_WINDOW_CLOSED`, `ERR_CURE_WINDOW_CLOSED`, `ERR_ARBITRATION_WINDOW_CLOSED`, `ERR_CONSOLIDATION_NOT_DUE`".
    PRD §2.7: "When a request violates more than one rule, the rejection is determined by a fixed priority order, evaluated from first to last".
    PRD §3.6: "the screener must be neither the complainant nor the respondent, else `ERR_SCREENING_CONFLICT`; and the screening must conclude no later than `grievance_review_due_at`, else `ERR_SCREENING_OVERDUE`."

    Design: Difficulty/priority_pair_validation_conflict/screening_overdue_loses_to_screener_conflict
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="PV1")
    mc = create_member(assoc["id"], member_nr="MC", full_name="Complainant")
    mr = create_member(assoc["id"], member_nr="MR", full_name="Respondent")
    set_clock("2026-09-10T00:00:00Z")
    case = get_success_data(api.create_ethics_case(
        assoc["id"], {"respondent_member_id": mr["id"], "article_code": "A16"},
        make_member_headers(mc["id"])))
    assert case["status"] == "GRIEVANCE_SCREENING"
    # Past the 45-day grievance deadline (due 2026-10-25).
    set_clock("2026-10-26T00:00:00Z")
    resp = api.screen_ethics_case(
        assoc["id"], case["id"], "FORWARDED", make_grievance_headers(mc["id"]))
    validate_error(resp, ApiErrorId.ERR_SCREENING_CONFLICT)
    case_now = get_success_data(api.get_ethics_case(assoc["id"], case["id"], STAFF))
    assert case_now["status"] == "GRIEVANCE_SCREENING"


def test_screening_overdue_rejected_when_no_conflict(api):
    """PRD §3.6: "the screening must conclude no later than
    `grievance_review_due_at`, else `ERR_SCREENING_OVERDUE`."
    PRD §3.6: "Filing stamps `filed_at`, computes `grievance_review_due_at` as
    exactly 45 days after filing, and immediately opens screening".

    Design: Difficulty/priority_pair_validation_conflict/screening_overdue_loses_to_screener_conflict
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="PV1B")
    mc = create_member(assoc["id"], member_nr="MC", full_name="Complainant")
    mr = create_member(assoc["id"], member_nr="MR", full_name="Respondent")
    mg = create_member(assoc["id"], member_nr="MG", full_name="Grievance")
    set_clock("2026-09-10T00:00:00Z")
    case = get_success_data(api.create_ethics_case(
        assoc["id"], {"respondent_member_id": mr["id"], "article_code": "A16"},
        make_member_headers(mc["id"])))
    set_clock("2026-10-26T00:00:00Z")
    resp = api.screen_ethics_case(
        assoc["id"], case["id"], "FORWARDED", make_grievance_headers(mg["id"]))
    validate_error(resp, ApiErrorId.ERR_SCREENING_OVERDUE)


def test_stale_version_loses_to_not_found_but_beats_comp_prohibition(api):
    """PRD §2.7: "(5) optimistic concurrency — `ERR_STALE_VERSION` on the two guarded endpoints; (6) source-state legality — `ERR_INVALID_STATE`; (7) the member disciplinary and segregation-of-duties gate — `ERR_MEMBER_SUSPENDED`, `ERR_SCREENING_CONFLICT`, `ERR_APPEAL_CONFLICT`, `ERR_PANEL_SOLE_ACTOR`; (8) the policy and compensation gate — `ERR_COMP_DISPLAY_PROHIBITED`, `ERR_RULESET_MISMATCH`, `ERR_LISTING_FLAGGED`".
    PRD §2.7: "When a request violates more than one rule, the rejection is determined by a fixed priority order, evaluated from first to last".
    PRD §3.3: "if the request to activate carries a listing whose `offer_comp_cents` is greater than zero while the governing revision's `comp_display_mode` is `COMP_DISPLAY_OFF`, activation is rejected outright with `ERR_COMP_DISPLAY_PROHIBITED` — this is a validation, not a clamp".

    Design: Difficulty/priority_pair_validation_conflict/stale_version_loses_to_not_found_but_beats_comp_prohibition
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="PV2")
    broker = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    office = create_office(assoc["id"], broker["id"], office_code="O1")
    r1 = activate_policy_revision(
        assoc["id"], assoc["version"], revision_code="R1",
        effective_at="2026-09-01T00:00:00Z", activate_now="2026-09-02T00:00:00Z")
    listing3 = create_listing(assoc["id"], office["id"], broker["id"],
                              mls_number="MLS-P2A", offer_comp_cents=500000)
    listing2 = create_listing(assoc["id"], office["id"], broker["id"],
                              mls_number="MLS-P2B")
    activate_listing(assoc["id"], office["id"], listing2)
    change_status(assoc["id"], office["id"], listing2, "PENDING",
                  "2026-09-02T00:00:00Z")
    change_status(assoc["id"], office["id"], listing2, "SOLD",
                  "2026-09-02T01:00:00Z")
    # Second revision (COMP_DISPLAY_OFF) advances the association version.
    assoc_now = get_success_data(api.get_association(assoc["id"], STAFF))
    r2 = activate_policy_revision(
        assoc["id"], assoc_now["version"], revision_code="R2",
        effective_at="2026-09-05T00:00:00Z", comp_display_mode="COMP_DISPLAY_OFF",
        activate_now="2026-09-05T00:00:00Z")
    # (i) stale expected version on revision create -> ERR_STALE_VERSION.
    resp = api.create_policy_revision(
        assoc["id"],
        {"revision_code": "R3", "effective_at": "2026-09-20T00:00:00Z",
         "comp_display_mode": "COMP_DISPLAY_ON",
         "expected_association_version": assoc_now["version"] - 1},
        STAFF)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    # (ii) activation with offer_comp > 0 under COMP_DISPLAY_OFF -> prohibited.
    resp = api.activate_listing(
        assoc["id"], office["id"], listing3["id"], make_member_headers(broker["id"]))
    validate_error(resp, ApiErrorId.ERR_COMP_DISPLAY_PROHIBITED)
    # (iii) SOLD listing: source-state legality beats the policy gate.
    resp = api.change_listing_status(
        assoc["id"], office["id"], listing2["id"],
        {"to_status": "WITHDRAWN", "business_effective_at": "2026-09-05T00:00:00Z"},
        make_member_headers(broker["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_stale_version_beats_invalid_state_on_dues_bill(api):
    """PRD §2.7: "(5) optimistic concurrency — `ERR_STALE_VERSION` on the two guarded endpoints; (6) source-state legality — `ERR_INVALID_STATE`".
    PRD §2.7: "When a request violates more than one rule, the rejection is determined by a fixed priority order, evaluated from first to last".
    PRD §2.6: "Billing a dues period requires `expected_dues_period_version` matching the period's current `version`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412); billing mints one invoice per `ACTIVE` member and a stale view risks double-billing after a corrective period edit."

    Design: Difficulty/priority_pair_validation_conflict/stale_version_loses_to_not_found_but_beats_comp_prohibition
    """
    assoc = create_association(association_code="PV2B")
    period = create_dues_period(assoc["id"], year=2026,
                                period_start_date="2026-09-01T00:00:00Z",
                                due_date="2026-09-30T00:00:00Z",
                                grace_end_date="2026-10-10T00:00:00Z",
                                amount_cents=100000)
    bill_dues_period(assoc["id"], period)
    # Second bill with the pre-bill version: stale (5) beats state (6).
    resp = api.bill_dues_period(assoc["id"], period["id"], period["version"], STAFF)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
