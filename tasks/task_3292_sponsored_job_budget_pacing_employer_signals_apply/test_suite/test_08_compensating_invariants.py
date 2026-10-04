"""Compensating invariants across paired operations.

Two conserved quantities are checked: campaign committed spend, which a refund
must return to its exact prior value, and the employer's outstanding receivable,
which account discipline must not write off.
"""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data, TEST_USERS,
    make_employer_headers, set_clock, create_employer, create_posting,
    create_active_campaign, create_sponsored_job, create_hold,
    get_campaign, get_employer, record_click, refund_payload,
    assert_campaign, assert_employer, assert_ledger_net_equals_spent,
)

ADMIN = TEST_USERS["admin_headers"]
TRUST = TEST_USERS["trust_headers"]


def test_committed_spend_returns_to_prior_value_after_refund(api):
    """PRD §2.5: "Because refund entries are negative, a refund reduces committed
    spend by exactly the refunded amount".
    PRD §3.8: "It appends a `REFUND` ledger entry whose `amount_cents` is
    negative, so the campaign's `spent_cents` falls by the refunded amount
    through the invariant of §2.5."

    Design: Difficulty/compensating_invariant/campaign_spend_conserved_across_click_and_refund
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="ConserveCo", domain="cons.example")
    headers = make_employer_headers(employer["id"])
    posting = create_posting(employer, title="Conserve Engineer",
                             description_text="Conserve spend.")
    campaign = create_active_campaign(
        employer, name="CS", pricing_model="CPC",
        daily_budget_cents=100000, total_budget_cents=1000000)
    sponsored_job = create_sponsored_job(campaign, posting, employer,
                                         cpc_bid_cents=500)

    event = record_click(campaign, sponsored_job, employer, device_fingerprint="fp-cs-1")
    assert event["cost_cents"] == 500
    after_click = get_campaign(campaign["id"], employer)
    assert after_click["spent_cents"] == 500

    validate_success(api.refund_event(
        event["id"], refund_payload(after_click["version"]), TRUST), 200)

    after_refund = get_campaign(campaign["id"], employer)
    assert_campaign(after_refund)
    assert after_refund["spent_cents"] == 0
    assert after_refund["daily_spent_cents"] == 0


def test_receivable_unchanged_by_refund_and_ledger_nets_to_zero(api):
    """PRD §2.5: "The employer's own outstanding obligation is a separate
    quantity: `Employer.balance_cents` rises by the cleared cost of every billed
    sponsored event and falls by the cleared cost of every granted refund".
    PRD §2.5: "The first is lifetime committed spend: `spent_cents` equals the
    sum of the `amount_cents` over all of the campaign's entries whose
    `entry_type` is `COMMIT`, plus the sum over all entries whose `entry_type` is
    `REFUND`."

    Design: Difficulty/compensating_invariant/campaign_spend_conserved_across_click_and_refund
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="ConserveCo2", domain="cons2.example")
    headers = make_employer_headers(employer["id"])
    posting = create_posting(employer, title="Conserve Engineer II",
                             description_text="Conserve spend two.")
    campaign = create_active_campaign(
        employer, name="CS2", pricing_model="CPC",
        daily_budget_cents=100000, total_budget_cents=1000000)
    sponsored_job = create_sponsored_job(campaign, posting, employer,
                                         cpc_bid_cents=500)

    event = record_click(campaign, sponsored_job, employer, device_fingerprint="fp-cs-2")
    after_click = get_campaign(campaign["id"], employer)
    assert get_employer(employer["id"])["balance_cents"] == 500

    validate_success(api.refund_event(
        event["id"], refund_payload(after_click["version"]), TRUST), 200)

    employer_after = get_employer(employer["id"])
    assert_employer(employer_after)
    assert employer_after["balance_cents"] == 0

    ledger = get_success_data(api_client.list_campaign_budget_ledger(
        campaign["id"], headers))
    assert_ledger_net_equals_spent(ledger, 0)


def test_receivable_survives_suspension_and_reinstatement(api):
    """PRD §3.8: "the balance is a receivable rather than a spending limit: the
    campaign's daily and total budgets are what bound spend, and the billing
    posture governs whether the account is permitted to transact at all."

    Design: Difficulty/compensating_invariant/employer_receivable_conserved_across_suspend_and_reinstate
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="RecvCo", domain="recv.example")
    headers = make_employer_headers(employer["id"])
    posting = create_posting(employer, title="Receivable Engineer",
                             description_text="Conserve receivable.")
    campaign = create_active_campaign(
        employer, name="RC", pricing_model="CPC",
        daily_budget_cents=100000, total_budget_cents=1000000)
    sponsored_job = create_sponsored_job(campaign, posting, employer,
                                         cpc_bid_cents=500)

    record_click(campaign, sponsored_job, employer, device_fingerprint="fp-rc-1")
    before = get_employer(employer["id"])
    assert before["balance_cents"] == 500

    suspended = get_success_data(api.suspend_employer(
        employer["id"], {"reason": "Account under review"}, TRUST))
    assert suspended["billing_status"] == "FROZEN"
    assert get_campaign(campaign["id"], employer)["status"] == "PAUSED"

    reinstated = get_success_data(api.reinstate_employer(employer["id"], TRUST))
    assert reinstated["billing_status"] == "CURRENT"
    assert reinstated["balance_cents"] == 500


def test_billed_event_costs_still_total_the_receivable_after_reinstatement(api):
    """PRD §2.5: "`Employer.balance_cents` rises by the cleared cost of every
    billed sponsored event and falls by the cleared cost of every granted refund,
    and is settled separately by invoice."
    PRD §3.1: "on success the employer's `status` returns to `ACTIVE` and
    `billing_status` to `CURRENT`."

    Design: Difficulty/compensating_invariant/employer_receivable_conserved_across_suspend_and_reinstate
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="RecvCo2", domain="recv2.example")
    headers = make_employer_headers(employer["id"])
    posting = create_posting(employer, title="Receivable Engineer II",
                             description_text="Conserve receivable two.")
    campaign = create_active_campaign(
        employer, name="RC2", pricing_model="CPC",
        daily_budget_cents=100000, total_budget_cents=1000000)
    sponsored_job = create_sponsored_job(campaign, posting, employer,
                                         cpc_bid_cents=500)

    # Two billed clicks give a 1000-cent receivable.
    record_click(campaign, sponsored_job, employer, device_fingerprint="fp-rc-2a")
    record_click(campaign, sponsored_job, employer, device_fingerprint="fp-rc-2b")

    events = validate_success(api_client.list_campaign_events(
        campaign["id"], headers, params={"status": "BILLED"}), 200)
    billed_total = sum(e["cost_cents"] for e in events)
    assert billed_total == 1000
    assert get_employer(employer["id"])["balance_cents"] == billed_total

    get_success_data(api.suspend_employer(
        employer["id"], {"reason": "Account under review"}, TRUST))
    after_reinstate = get_success_data(api.reinstate_employer(employer["id"], TRUST))

    assert after_reinstate["balance_cents"] == billed_total