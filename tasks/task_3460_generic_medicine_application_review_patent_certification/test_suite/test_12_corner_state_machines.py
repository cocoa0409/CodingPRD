"""Queue B / state_machines: initial states, happy path, invalid + terminal."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_applicant, make_reference_product, make_application, add_be_study,
    submit_application, get_application, list_awards,
    make_listed_patent, make_applicant_headers,
)

REVIEWER = TEST_USERS["regulatory_reviewer_headers"]


def test_listed_patent_created_with_past_expiry_starts_expired():
    """PRD section 3.2: "A patent stands `LISTED` while the logical clock has
    not moved beyond its `expiry_date` and becomes `EXPIRED` once it has —
    including at registration, where a patent listed with an already-past
    `expiry_date` starts directly in `EXPIRED`."

    Design: Corner/state_machines/listed_patent_created_with_past_expiry_starts_expired
    """
    rld = make_reference_product(brand_name="Oldpat", rld_approval_date="2001-01-01",
                                 patent_owner_user_id="innovator-ops-57")
    patent = make_listed_patent(rld, patent_number="US5555555",
                                patent_type="DRUG_PRODUCT", expiry_date="2020-06-01")
    assert patent["status"] == "EXPIRED", (
        "the expiry evaluation runs at creation against the fixed clock")


def test_submit_happy_path_sets_received_date_and_opens_cycle_one():
    """PRD section 3.3: "A successful filing stamps `received_date` with the
    current logical date, sets `current_cycle_number` to 1, and opens the
    first `ReviewCycle` in `OPEN` status" and "If the application carries at
    least one paragraph-IV certification and no `ExclusivityAward` yet exists
    for the reference product, the system creates one in `ELIGIBLE` status" —
    a P4-free filing creates none.

    Design: Corner/state_machines/submit_happy_path_sets_received_date_and_opens_cycle_one
    """
    applicant = make_applicant(legal_name="Happy Path Pharma")
    rld = make_reference_product(brand_name="Happyex")
    app = make_application(rld["id"], applicant["id"])
    add_be_study(app["id"], applicant["id"])
    submitted = validate_success(api_client.submit_application(
        app["id"], make_applicant_headers(applicant["id"])), 200)
    assert submitted["status"] == "RECEIVED"
    assert submitted["received_date"] == "2026-09-01"
    assert submitted["current_cycle_number"] == 1
    assert list_awards(application_id=app["id"]) == [], (
        "no paragraph-IV certification means no exclusivity award")


def test_approval_decision_on_draft_application_returns_invalid_state():
    """PRD section 2.7 step 7: "the state-machine preconditions of the target
    transition — filing only from a draft, a decision only on a filed
    application, an outcome only on a scheduled inspection, and so on
    (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/approval_decision_on_draft_application_returns_invalid_state
    """
    applicant = make_applicant(legal_name="Draft Decision Co")
    rld = make_reference_product(brand_name="Draftex")
    app = make_application(rld["id"], applicant["id"])

    resp = api_client.approval_decision(app["id"], {"decision": "APPROVE"}, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409

    after = get_application(app["id"])
    assert after["status"] == "DRAFT"
    assert after["approval_date"] is None and after["tentative_approval_date"] is None


def test_withdrawn_application_terminal_lockdown_rejects_all_actions():
    """PRD section 2.7: "Seventh, the state-machine preconditions of the
    target transition — filing only from a draft, a decision only on a filed
    application, an outcome only on a scheduled inspection, and so on
    (`ERR_INVALID_STATE`)." PRD section 3.8: "The sponsor may withdraw the
    application — moving it to `WITHDRAWN` — from `DRAFT` (a clean exit with
    no cascade), from `RECEIVED` (the open cycle closes with `closed_reason`
    `SUPERSEDED`, and an `ELIGIBLE` or `AWARDED` award is forfeited as
    `APPLICATION_WITHDRAWN`), from `TENTATIVE_APPROVAL` (the cycle already
    stands closed from the tentative approval; the same forfeiture fires), or
    from `APPROVED` (an `AWARDED` or `ACTIVE` award is forfeited on the same
    reason)." WITHDRAWN is terminal: submit, amend, and approval-decision all
    fail and the record is untouched.

    Design: Corner/state_machines/withdrawn_application_terminal_lockdown_rejects_all_actions
    """
    applicant = make_applicant(legal_name="Terminal Co")
    rld = make_reference_product(brand_name="Terminex")
    app = make_application(rld["id"], applicant["id"])
    headers = make_applicant_headers(applicant["id"])
    withdrawn = validate_success(api_client.withdraw_application(app["id"], headers), 200)
    assert withdrawn["status"] == "WITHDRAWN"
    v_wd = get_application(app["id"])["version"]

    r1 = api_client.submit_application(app["id"], headers)
    validate_error(r1, ApiErrorId.ERR_INVALID_STATE)
    r2 = api_client.create_amendment(app["id"], {
        "classification": "MINOR", "contains_new_be_data": False,
        "expected_application_version": v_wd}, headers)
    validate_error(r2, ApiErrorId.ERR_INVALID_STATE)
    r3 = api_client.approval_decision(app["id"], {"decision": "APPROVE"}, REVIEWER)
    validate_error(r3, ApiErrorId.ERR_INVALID_STATE)
    for r in (r1, r2, r3):
        assert r.status_code == 409

    after = get_application(app["id"])
    assert after["status"] == "WITHDRAWN" and after["version"] == v_wd
