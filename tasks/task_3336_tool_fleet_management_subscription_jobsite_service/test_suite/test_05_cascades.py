"""Transitive cascades: ticket close (depth-3) and theft approval (depth-2)."""
from test_helpers import (
    api_client, validate_success, setup_deployed_asset, setup_police_verified_claim,
    open_ticket, drive_ticket_to_in_shop, create_loaner, get_loaner, get_asset,
    get_jobsite, get_agreement, get_account, make_claims_adjuster_headers,
    TEST_USERS,
)

COORD = TEST_USERS["service_coordinator_headers"]
ADMIN = TEST_USERS["fleet_admin_headers"]


def _setup_dispatched_ticket():
    """Deployed LIGHT asset; AVAILABLE loaner of same model; ticket driven to
    LOANER_DISPATCHED then QUALITY_CHECK."""
    env = setup_deployed_asset(
        rate_card_overrides={
            "tool_category": "DRILL", "base_monthly_rate_cents": 5000,
            "tier2_threshold": 100, "tier2_monthly_rate_cents": 5000,
            "tier3_threshold": 200, "tier3_monthly_rate_cents": 5000,
            "min_monthly_fee_cents": 0,
        })
    loaner = create_loaner(env["tool_model"]["id"], serial_number="LN-K1")
    ticket = open_ticket(env["asset"]["id"], True, env["js"])
    drive_ticket_to_in_shop(ticket["id"])
    r = api_client.dispatch_loaner(ticket["id"], COORD)
    validate_success(r)
    r = api_client.complete_repair(ticket["id"], COORD)
    validate_success(r)
    env["loaner"] = loaner
    env["ticket"] = ticket
    return env


def test_ticket_close_two_hop_loaner_cascade(api):
    """PRD §3.6: "If a loaner was dispatched, the unit cascades through two hops
    within the same call — `DISPATCHED` to `RETURNED` and then immediately
    `RETURNED` to `AVAILABLE` — with `assigned_ticket_id` and the ticket's
    `loaner_unit_id` both cleared."

    Design: Difficulty/transitive_cascade/ticket_close_cascade_depth3
    """
    env = _setup_dispatched_ticket()
    r = api_client.close_ticket(env["ticket"]["id"], COORD)
    ticket = validate_success(r)
    assert ticket["status"] == "CLOSED"
    assert ticket["sla_breach_credit_cents"] == 0, "closed within the 3-day LIGHT SLA"
    assert ticket["loaner_unit_id"] is None
    loaner = get_loaner(env["loaner"]["id"])
    assert loaner["status"] == "AVAILABLE", "two-hop cascade completes in one call"
    assert loaner["assigned_ticket_id"] is None


def test_ticket_close_redeploys_asset_and_restores_jobsite_count(api):
    """PRD §3.6: "The repaired asset returns from `IN_REPAIR` to `DEPLOYED` at
    the jobsite recorded in its `current_jobsite_id`, and that jobsite's
    `deployed_asset_count` rises by 1."

    Design: Difficulty/transitive_cascade/ticket_close_cascade_depth3
    """
    env = _setup_dispatched_ticket()
    r = api_client.close_ticket(env["ticket"]["id"], COORD)
    validate_success(r)
    asset = get_asset(env["asset"]["id"])
    assert asset["status"] == "DEPLOYED"
    site = get_jobsite(env["jobsite"]["id"])
    assert site["deployed_asset_count"] == 1


def test_theft_approval_cascades_asset_lost_jobsite_count_and_balance(api):
    """PRD §3.7: "Approval also cascades to the asset, which moves from
    `DEPLOYED` to `LOST`: its jobsite's `deployed_asset_count` falls by 1 and
    its `current_jobsite_id` is cleared. The deductible is added to the
    account's `outstanding_balance_cents`."

    Design: Difficulty/transitive_cascade/theft_approval_cascade_depth2
    """
    env = setup_police_verified_claim(
        category="DRILL", weight_class="LIGHT", replacement_value_cents=100000,
        rate_card_overrides={
            "tool_category": "DRILL", "base_monthly_rate_cents": 5000,
            "tier2_threshold": 100, "tier2_monthly_rate_cents": 5000,
            "tier3_threshold": 200, "tier3_monthly_rate_cents": 5000,
            "min_monthly_fee_cents": 1000,
        },
        verifier="admin-x1", filed_at="2026-09-01T12:00:00Z")
    # activation on 2026-09-01: full month 5000 billed -> outstanding 5000
    r = api_client.decide_theft_claim(
        env["claim"]["id"], "APPROVE", make_claims_adjuster_headers("adj-x1"))
    claim = validate_success(r)
    assert claim["status"] == "APPROVED"
    # age 0 months -> 100% tier -> 100000; 10% = 10000 < 50000 floor
    assert claim["deductible_cents"] == 50000

    asset = get_asset(env["asset"]["id"])
    assert asset["status"] == "LOST", "link 1: asset moves to LOST"
    assert asset["current_jobsite_id"] is None
    site = get_jobsite(env["jobsite"]["id"])
    assert site["deployed_asset_count"] == 0, "link 2: caused by the LOST transition"
    agreement = get_agreement(env["agreement_id"])
    assert agreement["fleet_size_target"] == 0, "LOST leaves the billable set"
    account = get_account(env["account_id"])
    assert account["outstanding_balance_cents"] == 55000, (
        "5000 activation billing + 50000 deductible")


def test_theft_deny_leaves_asset_deployed_and_decrements_claim_count(api):
    """PRD §3.7: "A denial moves the claim to `DENIED`, leaves the asset
    `DEPLOYED`, and decrements the agreement's `theft_claim_count`."

    Design: Difficulty/transitive_cascade/theft_approval_cascade_depth2
    """
    env = setup_police_verified_claim(
        verifier="admin-x2", filed_at="2026-09-01T12:00:00Z")
    r = api_client.decide_theft_claim(
        env["claim"]["id"], "DENY", make_claims_adjuster_headers("adj-x2"))
    claim = validate_success(r)
    assert claim["status"] == "DENIED"
    asset = get_asset(env["asset"]["id"])
    assert asset["status"] == "DEPLOYED"
    agreement = get_agreement(env["agreement_id"])
    assert agreement["theft_claim_count"] == 0
