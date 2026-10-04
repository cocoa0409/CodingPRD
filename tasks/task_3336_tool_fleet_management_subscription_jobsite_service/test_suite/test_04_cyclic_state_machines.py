"""Cyclic state machines: repair-ticket reopen loop; account suspend/reinstate."""
from test_helpers import (
    api_client, validate_success, validate_error, setup_deployed_asset,
    setup_agreement_with_assets, open_ticket, drive_ticket_to_closed,
    get_agreement, set_clock, TEST_USERS,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
COORD = TEST_USERS["service_coordinator_headers"]

SIX_UNIT_DRILL_CARD = {
    "tool_category": "DRILL", "base_monthly_rate_cents": 10000,
    "tier2_threshold": 5, "tier2_monthly_rate_cents": 9000,
    "tier3_threshold": 10, "tier3_monthly_rate_cents": 8000,
    "min_monthly_fee_cents": 25000,
}


def _setup_ticket():
    env = setup_deployed_asset(
        rate_card_overrides={
            "tool_category": "DRILL", "base_monthly_rate_cents": 5000,
            "tier2_threshold": 100, "tier2_monthly_rate_cents": 5000,
            "tier3_threshold": 200, "tier3_monthly_rate_cents": 5000,
            "min_monthly_fee_cents": 0,
        })
    ticket = open_ticket(env["asset"]["id"], False, env["js"])
    env["ticket"] = ticket
    return env


def test_ticket_reopen_cycle_reopens_and_reenters_pipeline(api):
    """PRD §3.6: "Reopening moves the ticket to `REOPENED`, moves the asset from
    `DEPLOYED` back to `IN_REPAIR` with its jobsite's `deployed_asset_count`
    falling by 1, and raises `reopen_count` by 1; the previously granted
    `sla_breach_credit_cents` is left untouched."
    PRD §3.6: "When the reopened unit is received again, the `REOPENED` leg into
    `IN_SHOP` recomputes `promised_return_by` from that receive timestamp,
    opening a fresh SLA window."

    Design: Difficulty/non_linear_state_machine/repair_ticket_reopen_cycle
    """
    env = _setup_ticket()
    closed = drive_ticket_to_closed(env["ticket"]["id"])
    assert closed["status"] == "CLOSED"
    assert closed["sla_breach_credit_cents"] == 0, "closed within the 3-day LIGHT SLA"

    r = api_client.reopen_ticket(env["ticket"]["id"], env["js"])
    reopened = validate_success(r)
    assert reopened["status"] == "REOPENED"
    assert reopened["reopen_count"] == 1
    assert reopened["sla_breach_credit_cents"] == 0, "credit immutable across reopen"

    r = api_client.receive_ticket(env["ticket"]["id"], COORD)
    in_shop = validate_success(r)
    assert in_shop["status"] == "IN_SHOP", "cycle re-enters the pipeline"


def test_ticket_reopen_second_cycle_count_two(api):
    """PRD §3.6: "the ticket's `reopen_count` must still be below the hard cap
    of 2 (a ticket already reopened twice rejects with
    `ERR_CAPACITY_EXCEEDED`)."

    Design: Difficulty/non_linear_state_machine/repair_ticket_reopen_cycle
    """
    env = _setup_ticket()
    drive_ticket_to_closed(env["ticket"]["id"])
    r = api_client.reopen_ticket(env["ticket"]["id"], env["js"])
    validate_success(r)
    drive_ticket_to_closed(env["ticket"]["id"])  # REOPENED -> ... -> CLOSED
    r = api_client.reopen_ticket(env["ticket"]["id"], env["js"])
    second = validate_success(r)
    assert second["status"] == "REOPENED"
    assert second["reopen_count"] == 2


def test_account_suspend_reinstate_cycle_with_cascade(api):
    """PRD §3.1: "Suspension cascades: every agreement of the account that is
    `ACTIVE` moves to `SUSPENDED`, and each cascaded agreement's `version`
    increments by 1."
    PRD §3.1: "a `FleetAdmin` may reinstate a `SUSPENDED` account only once
    `outstanding_balance_cents` is at most `credit_limit_cents` (again
    `ERR_CREDIT_LIMIT_EXCEEDED` otherwise), and reinstatement cascades every
    `SUSPENDED` agreement of the account back to `ACTIVE`, incrementing each
    such agreement's `version` by 1."

    Design: Difficulty/non_linear_state_machine/account_suspend_reinstate_cycle
    """
    set_clock("2026-09-16T00:00:00Z")
    env = setup_agreement_with_assets(
        n_assets=6, credit_limit_cents=25000, rate_card_overrides=SIX_UNIT_DRILL_CARD,
        start_date="2026-09-16T00:00:00Z")
    # activation bill: floor(58000 * 15/30) = 29000 > 25000
    r = api_client.suspend_account(env["account_id"], ADMIN)
    account = validate_success(r)
    assert account["status"] == "SUSPENDED"
    agreement = get_agreement(env["agreement_id"])
    assert agreement["status"] == "SUSPENDED", "cascade flips the agreement"
    assert agreement["version"] == env["agreement_version"] + 1

    r = api_client.record_payment(env["account_id"], 4000, env["cm"])
    account = validate_success(r)
    assert account["outstanding_balance_cents"] == 25000, (
        "29000 - 4000; boundary: balance == limit allows reinstate")

    r = api_client.reinstate_account(env["account_id"], ADMIN)
    account = validate_success(r)
    assert account["status"] == "ACTIVE"
    agreement = get_agreement(env["agreement_id"])
    assert agreement["status"] == "ACTIVE", "reverse cascade closes the cycle"


def test_suspend_requires_balance_over_limit(api):
    """PRD §3.1: "A `FleetAdmin` may suspend an account only while its
    `outstanding_balance_cents` exceeds its `credit_limit_cents`; the attempt
    is otherwise rejected with `ERR_CREDIT_LIMIT_EXCEEDED`."

    Design: Difficulty/non_linear_state_machine/account_suspend_reinstate_cycle
    """
    set_clock("2026-09-16T00:00:00Z")
    env = setup_agreement_with_assets(
        n_assets=6, credit_limit_cents=25000, rate_card_overrides=SIX_UNIT_DRILL_CARD,
        start_date="2026-09-16T00:00:00Z")
    # pay down to exactly the limit first; suspend must then be rejected
    r = api_client.record_payment(env["account_id"], 4000, env["cm"])
    validate_success(r)
    r = api_client.suspend_account(env["account_id"], ADMIN)
    err = validate_error(r, "ERR_CREDIT_LIMIT_EXCEEDED")
    assert err["error_id"] == "ERR_CREDIT_LIMIT_EXCEEDED"
