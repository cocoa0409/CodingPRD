"""Corner/calculations: month-boundary sweep billing; SLA breach credit."""
from test_helpers import (
    api_client, validate_success, setup_agreement_with_assets,
    setup_deployed_asset, open_ticket, drive_ticket_to_quality_check,
    get_agreement, get_account, get_asset, set_clock, TEST_USERS,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
COORD = TEST_USERS["service_coordinator_headers"]

SIX_UNIT_DRILL_CARD = {
    "tool_category": "DRILL", "base_monthly_rate_cents": 10000,
    "tier2_threshold": 5, "tier2_monthly_rate_cents": 9000,
    "tier3_threshold": 10, "tier3_monthly_rate_cents": 8000,
    "min_monthly_fee_cents": 25000,
}

HEAVY_BREAKER_CARD = {
    "tool_category": "BREAKER", "base_monthly_rate_cents": 20000,
    "tier2_threshold": 100, "tier2_monthly_rate_cents": 20000,
    "tier3_threshold": 200, "tier3_monthly_rate_cents": 20000,
    "min_monthly_fee_cents": 0,
}


def test_month_boundary_sweep_bills_full_month(api):
    """PRD §3.3: "The sweep variant uses a proration factor of exactly 1 — the
    full month is billed — and additionally resets every asset's
    `utilization_minutes_current_month` to 0."

    Design: Corner/calculations/month_boundary_sweep_bills_full_month_and_resets_utilization
    """
    set_clock("2026-09-16T00:00:00Z")
    env = setup_agreement_with_assets(
        n_assets=6, rate_card_overrides=SIX_UNIT_DRILL_CARD,
        start_date="2026-09-16T00:00:00Z")
    # activation billed 29000 prorated
    set_clock("2026-10-01T00:00:00Z")
    agreement = get_agreement(env["agreement_id"])
    assert agreement["billed_this_month_cents"] == 58000, (
        "full October: 4*10000 + 2*9000, no proration on the sweep")
    account = get_account(env["account_id"])
    assert account["outstanding_balance_cents"] == 87000, (
        "29000 September prorated + 58000 October")


def test_month_boundary_sweep_resets_utilization(api):
    """PRD §2.5: "when the clock crosses into a new calendar month, full monthly
    billing runs for every agreement in `ACTIVE`, and every asset's
    `utilization_minutes_current_month` resets to 0."

    Design: Corner/calculations/month_boundary_sweep_bills_full_month_and_resets_utilization
    """
    set_clock("2026-09-16T00:00:00Z")
    env = setup_deployed_asset(
        clock=None, rate_card_overrides=SIX_UNIT_DRILL_CARD,
        start_date="2026-09-16T00:00:00Z", n_assets=6)
    r = api_client.record_usage_event(
        env["asset"]["id"],
        {"started_at": "2026-09-16T08:00:00Z", "ended_at": "2026-09-16T16:00:00Z"},
        env["js"])
    validate_success(r, expected_status=201)
    assert get_asset(env["asset"]["id"])["utilization_minutes_current_month"] == 480
    set_clock("2026-10-01T00:00:00Z")
    assert get_asset(env["asset"]["id"])["utilization_minutes_current_month"] == 0


def test_sla_breach_credit_ceil_and_cap(api):
    """PRD §3.6: "the credit is the breach days multiplied by the daily credit —
    2500 cents per day for `LIGHT`, 9000 cents per day for `HEAVY` — capped at
    50000 cents, with the ceiling applied last (round-up to whole days first,
    then multiply, then cap)."
    PRD §3.6: "any positive credit reduces the account's
    `outstanding_balance_cents`, floored at 0."

    Design: Corner/calculations/sla_breach_credit_ceil_and_cap
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_deployed_asset(
        clock=None, category="BREAKER", weight_class="HEAVY",
        replacement_value_cents=300000, rate_card_overrides=HEAVY_BREAKER_CARD)
    ticket = open_ticket(env["asset"]["id"], False, env["js"])
    # promised_return_by = opened 9/1 00:00 + 5d = 2026-09-06T00:00:00Z
    drive_ticket_to_quality_check(ticket["id"])
    set_clock("2026-09-07T06:00:00Z")  # 30h past the promise
    r = api_client.close_ticket(ticket["id"], COORD)
    closed = validate_success(r)
    # ceil(30/24) = 2 breach days * 9000 HEAVY = 18000, under the 50000 cap
    assert closed["sla_breach_credit_cents"] == 18000
    account = get_account(env["account_id"])
    assert account["outstanding_balance_cents"] == 2000, (
        "20000 activation billing - 18000 credit")


def test_within_sla_close_grants_no_credit(api):
    """PRD §3.6: "a breach exists only when the ticket closed strictly after
    the promised instant"

    Design: Corner/calculations/sla_breach_credit_ceil_and_cap
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_deployed_asset(clock=None)
    ticket = open_ticket(env["asset"]["id"], False, env["js"])
    drive_ticket_to_quality_check(ticket["id"])
    r = api_client.close_ticket(ticket["id"], COORD)
    closed = validate_success(r)
    assert closed["sla_breach_credit_cents"] == 0, "same-day close is within SLA"
    assert closed["closed_at"] is not None
