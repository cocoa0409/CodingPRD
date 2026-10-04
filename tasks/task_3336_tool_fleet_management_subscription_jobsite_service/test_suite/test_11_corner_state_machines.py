"""Corner/state_machines: invalid transitions, loaner pool, expiry sweep."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    setup_deployed_asset, setup_police_verified_claim, open_ticket,
    drive_ticket_to_in_shop, create_loaner, get_loaner, get_agreement,
    create_account, create_jobsite, set_clock, make_contractor_manager_headers,
    make_claims_adjuster_headers, make_field_engineer_headers, TEST_USERS,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
COORD = TEST_USERS["service_coordinator_headers"]


def test_terminal_theft_claim_rejects_decide_returns_invalid_state(api):
    """PRD §3.7: "The adjuster submits a `decision` of `APPROVE` or `DENY`."
    PRD §2.8: "then state-machine legality (`ERR_INVALID_STATE`)"
    PRD §5: "ERR_INVALID_STATE | 409"

    Design: Corner/state_machines/terminal_theft_claim_rejects_decide_returns_invalid_state
    """
    env = setup_police_verified_claim(
        verifier="admin-sm1", filed_at="2026-09-01T06:00:00Z")
    r = api_client.decide_theft_claim(
        env["claim"]["id"], "APPROVE", make_claims_adjuster_headers("adj-sm1"))
    validate_success(r)
    r = api_client.decide_theft_claim(
        env["claim"]["id"], "DENY", make_claims_adjuster_headers("adj-sm2"))
    validate_error(r, "ERR_INVALID_STATE")


def test_close_from_opened_returns_invalid_state(api):
    """PRD §3.6: "Closing the ticket (from `QUALITY_CHECK` to `CLOSED`) is the
    settlement point of the repair pipeline"

    Design: Corner/state_machines/close_from_opened_returns_invalid_state
    """
    env = setup_deployed_asset()
    ticket = open_ticket(env["asset"]["id"], False, env["js"])
    assert ticket["status"] == "OPENED"
    r = api_client.close_ticket(ticket["id"], COORD)
    validate_error(r, "ERR_INVALID_STATE")


def test_loaner_dispatch_empty_pool_rejected(api):
    """PRD §3.6: "An empty eligible pool is rejected with
    `ERR_LOANER_POOL_EMPTY` (HTTP 409) and the ticket remains `IN_SHOP`."

    Design: Corner/state_machines/loaner_dispatch_empty_pool_rejected
    """
    env = setup_deployed_asset()
    ticket = open_ticket(env["asset"]["id"], True, env["js"])
    drive_ticket_to_in_shop(ticket["id"])
    r = api_client.dispatch_loaner(ticket["id"], COORD)
    validate_error(r, "ERR_LOANER_POOL_EMPTY")
    from test_helpers import get_ticket
    assert get_ticket(ticket["id"])["status"] == "IN_SHOP"


def test_loaner_selector_picks_oldest_available(api):
    """PRD §3.6: "eligible units are those in `AVAILABLE` whose `tool_model_id`
    equals the model of the asset under repair, ranked oldest first by
    `created_at` (creation timestamps are unique per row, so no further
    tie-break applies)."

    Design: Corner/state_machines/loaner_selector_picks_oldest_available
    """
    env = setup_deployed_asset()
    l_old = create_loaner(env["tool_model"]["id"], serial_number="LN-OLD")
    l_new = create_loaner(env["tool_model"]["id"], serial_number="LN-NEW")
    ticket = open_ticket(env["asset"]["id"], True, env["js"])
    drive_ticket_to_in_shop(ticket["id"])
    r = api_client.dispatch_loaner(ticket["id"], COORD)
    dispatched = validate_success(r)
    assert dispatched["status"] == "LOANER_DISPATCHED"
    assert dispatched["loaner_unit_id"] == l_old["id"], "oldest created_at wins"
    assert get_loaner(l_new["id"])["status"] == "AVAILABLE"


def test_theft_claim_auto_expires_on_clock_sweep(api):
    """PRD §3.7: "A claim that is still `REPORTED` when the logical clock passes
    the 48-hour mark is swept to `EXPIRED`, the asset remains `DEPLOYED`, and
    the agreement's `theft_claim_count` is decremented."

    Design: Corner/state_machines/theft_claim_auto_expires_on_clock_sweep
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_deployed_asset()
    from test_helpers import report_claim, get_asset
    claim = report_claim(env["asset"]["id"], env["js"])
    assert claim["status"] == "REPORTED"
    assert get_agreement(env["agreement_id"])["theft_claim_count"] == 1
    set_clock("2026-09-04T00:00:01Z")  # past reported_at + 48h
    data, _meta = validate_paginated(
        api_client.list_theft_claims_for_asset(env["asset"]["id"], ADMIN))
    assert data[0]["status"] == "EXPIRED"
    assert get_asset(env["asset"]["id"])["status"] == "DEPLOYED"
    assert get_agreement(env["agreement_id"])["theft_claim_count"] == 0


def test_review_on_rejected_support_case_returns_invalid_state(api):
    """PRD §3.8: "A `FieldEngineer` reviews the case with a `decision`:
    approval moves it to `DOCUMENTED` and requires a stamped
    `documentation_url` (absent, the approval fails with `ERR_VALIDATION`),
    recording the reviewing engineer's `X-User-ID` in
    `approved_by_engineer_id` alongside the documentation link; rejection moves
    it to `REJECTED`."

    Design: Corner/state_machines/review_on_rejected_support_case_returns_invalid_state
    """
    account = create_account()
    acct = account["id"]
    cm = make_contractor_manager_headers(acct)
    site = create_jobsite(acct, capacity_assets=5, cm=cm)
    r = api_client.create_support_case(
        acct, {"kind": "FIRESTOP", "jobsite_id": site["id"],
               "scheduled_for": "2026-09-20T10:00:00Z"}, cm)
    case = validate_success(r, expected_status=201)
    eng = make_field_engineer_headers("eng-sm6")
    r = api_client.review_support_case(acct, case["id"], {"decision": "REJECT"}, eng)
    validate_success(r)
    r = api_client.review_support_case(
        acct, case["id"],
        {"decision": "APPROVE", "documentation_url": "https://docs.example/x.pdf"},
        eng)
    validate_error(r, "ERR_INVALID_STATE")


def test_approve_without_documentation_returns_validation(api):
    """PRD §3.8: "approval moves it to `DOCUMENTED` and requires a stamped
    `documentation_url` (absent, the approval fails with `ERR_VALIDATION`)"

    Design: Corner/state_machines/approve_without_documentation_returns_validation
    """
    account = create_account()
    acct = account["id"]
    cm = make_contractor_manager_headers(acct)
    site = create_jobsite(acct, capacity_assets=5, cm=cm)
    r = api_client.create_support_case(
        acct, {"kind": "ANCHOR_DESIGN", "jobsite_id": site["id"],
               "scheduled_for": "2026-09-20T10:00:00Z"}, cm)
    case = validate_success(r, expected_status=201)
    eng = make_field_engineer_headers("eng-sm7")
    r = api_client.review_support_case(acct, case["id"], {"decision": "APPROVE"}, eng)
    validate_error(r, "ERR_VALIDATION")
