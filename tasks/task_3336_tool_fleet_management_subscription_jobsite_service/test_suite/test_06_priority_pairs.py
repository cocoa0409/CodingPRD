"""Validation priority: state beats fiscal; temporal beats constraint."""
from test_helpers import (
    api_client, validate_success, validate_error, create_account,
    create_consumable_product, setup_deployed_asset, open_ticket,
    drive_ticket_to_closed, set_clock,
    make_contractor_manager_headers, TEST_USERS,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
COORD = TEST_USERS["service_coordinator_headers"]


def _submit_order(acct, cm, product_id, qty=1):
    r = api_client.create_consumable_order(
        acct, [{"product_id": product_id, "quantity_units": qty}], cm)
    order = validate_success(r, expected_status=201)
    r = api_client.submit_consumable_order(acct, order["id"], cm)
    return validate_success(r)


def test_order_decide_on_rejected_reports_invalid_state_not_fiscal(api):
    """PRD §2.8: "then state-machine legality (`ERR_INVALID_STATE`) ... then the
    application-approval gate (`ERR_APPLICATION_APPROVAL_REQUIRED`), then credit
    checks (`ERR_CREDIT_LIMIT_EXCEEDED`), and finally uniqueness
    (`ERR_DUPLICATE`). A request failing an earlier check never reports a later
    one."

    Design: Difficulty/priority_pair_validation_conflict/order_decide_state_beats_fiscal
    """
    account = create_account(credit_limit_cents=100000)
    acct = account["id"]
    cm = make_contractor_manager_headers(acct)
    product = create_consumable_product(
        sku="P-P1", name="Nails", unit_price_cents=90000, pack_size=1,
        requires_application_approval=False)
    o1 = _submit_order(acct, cm, product["id"])
    r = api_client.decide_consumable_order(acct, o1["id"], "APPROVE", ADMIN)
    validate_success(r)
    # outstanding now 90000; a second 90000 approval would breach the limit
    o2 = _submit_order(acct, cm, product["id"])
    r = api_client.decide_consumable_order(acct, o2["id"], "REJECT", ADMIN)
    validate_success(r)
    # re-deciding a REJECTED order: state precondition fires first
    r = api_client.decide_consumable_order(acct, o2["id"], "APPROVE", ADMIN)
    validate_error(r, "ERR_INVALID_STATE")


def test_order_decide_on_fulfilled_reports_invalid_state(api):
    """PRD §2.8: "then state-machine legality (`ERR_INVALID_STATE`) ... then
    credit checks (`ERR_CREDIT_LIMIT_EXCEEDED`) ... A request failing an earlier
    check never reports a later one."

    Design: Difficulty/priority_pair_validation_conflict/order_decide_state_beats_fiscal
    """
    account = create_account(credit_limit_cents=100000)
    acct = account["id"]
    cm = make_contractor_manager_headers(acct)
    product = create_consumable_product(
        sku="P-P1B", name="Nails B", unit_price_cents=90000, pack_size=1,
        requires_application_approval=False)
    o1 = _submit_order(acct, cm, product["id"])
    r = api_client.decide_consumable_order(acct, o1["id"], "APPROVE", ADMIN)
    validate_success(r)  # outstanding 90000
    r = api_client.fulfill_consumable_order(acct, o1["id"], ADMIN)
    validate_success(r)
    # deciding a FULFILLED order would also breach credit; state fires first
    r = api_client.decide_consumable_order(acct, o1["id"], "APPROVE", ADMIN)
    validate_error(r, "ERR_INVALID_STATE")


def test_reopen_past_window_reports_temporal_not_cap(api):
    """PRD §2.8: "then time windows (`ERR_WINDOW_EXPIRED`), then structural and
    capacity constraints (`ERR_CAPACITY_EXCEEDED`, `ERR_WINDOW_OVERLAP`,
    `ERR_LOANER_POOL_EMPTY`, `ERR_AGREEMENT_HAS_OPEN_CLAIMS`,
    `ERR_RETURN_INCOMPLETE`) ... A request failing an earlier check never
    reports a later one."

    Design: Difficulty/priority_pair_validation_conflict/reopen_temporal_beats_constraint
    """
    env = setup_deployed_asset(
        rate_card_overrides={
            "tool_category": "DRILL", "base_monthly_rate_cents": 5000,
            "tier2_threshold": 100, "tier2_monthly_rate_cents": 5000,
            "tier3_threshold": 200, "tier3_monthly_rate_cents": 5000,
            "min_monthly_fee_cents": 0,
        })
    ticket = open_ticket(env["asset"]["id"], False, env["js"])
    # close, reopen, close, reopen -> reopen_count == 2 (cap reached)
    drive_ticket_to_closed(ticket["id"])
    r = api_client.reopen_ticket(ticket["id"], env["js"])
    validate_success(r)
    drive_ticket_to_closed(ticket["id"])
    r = api_client.reopen_ticket(ticket["id"], env["js"])
    reopened = validate_success(r)
    assert reopened["reopen_count"] == 2, "cap reached before the trigger"
    drive_ticket_to_closed(ticket["id"])
    # advance clock 15 days past the close (close happened at 2026-09-01)
    set_clock("2026-09-16T00:00:00Z")
    r = api_client.reopen_ticket(ticket["id"], env["js"])
    validate_error(r, "ERR_WINDOW_EXPIRED")


def test_reopen_within_window_reports_cap(api):
    """PRD §3.6: "the ticket's `reopen_count` must still be below the hard cap
    of 2 (a ticket already reopened twice rejects with
    `ERR_CAPACITY_EXCEEDED`)."

    Design: Difficulty/priority_pair_validation_conflict/reopen_temporal_beats_constraint
    """
    env = setup_deployed_asset(
        rate_card_overrides={
            "tool_category": "DRILL", "base_monthly_rate_cents": 5000,
            "tier2_threshold": 100, "tier2_monthly_rate_cents": 5000,
            "tier3_threshold": 200, "tier3_monthly_rate_cents": 5000,
            "min_monthly_fee_cents": 0,
        })
    ticket = open_ticket(env["asset"]["id"], False, env["js"])
    drive_ticket_to_closed(ticket["id"])
    validate_success(api_client.reopen_ticket(ticket["id"], env["js"]))
    drive_ticket_to_closed(ticket["id"])
    r = api_client.reopen_ticket(ticket["id"], env["js"])
    reopened = validate_success(r)
    assert reopened["reopen_count"] == 2
    drive_ticket_to_closed(ticket["id"])
    # same day, well within 14 days -> only the cap can fire
    r = api_client.reopen_ticket(ticket["id"], env["js"])
    validate_error(r, "ERR_CAPACITY_EXCEEDED")
