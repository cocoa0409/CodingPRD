"""Day rollover and immediate-consistency behaviour.

A rollover replenishes daily capacity without touching lifetime spend, and a
committed write is visible on the very next read with no lag.
"""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data, TEST_USERS,
    make_employer_headers, set_clock, create_employer, create_posting,
    create_active_campaign, create_sponsored_job, create_hold,
    get_campaign, record_click,
    assert_campaign, assert_ledger_net_equals_spent,
)

ADMIN = TEST_USERS["admin_headers"]


def test_day_rollover_resets_daily_spend_only(api):
    """PRD §3.2: "it does three things for each affected campaign:
    `daily_spent_cents` is reset to 0, `day_open_date` is advanced to the new
    logical day, and any campaign sitting in `PACING_HOLD` returns to `ACTIVE`
    because it now has a fresh daily budget to spend."

    Design: Corner/cross_cutting_complexity_layers/day_rollover_resets_daily_spend_without_touching_lifetime_spend
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Rollover Co", domain="roll.example")
    headers = make_employer_headers(employer["id"])
    posting = create_posting(employer, title="Rollover Engineer")
    campaign = create_active_campaign(employer, name="RO")
    sponsored_job = create_sponsored_job(campaign, posting, employer,
                                         cpc_bid_cents=500)

    record_click(campaign, sponsored_job, employer, device_fingerprint="fp-ro-1")
    before = get_campaign(campaign["id"], employer)
    assert before["spent_cents"] == 500

    get_success_data(api.set_current_utc({"current_utc": "2026-09-02T00:00:00Z"}, ADMIN))
    after = get_campaign(campaign["id"], employer)

    assert after["daily_spent_cents"] == 0
    assert after["day_open_date"] == "2026-09-02T00:00:00Z"
    assert after["spent_cents"] == 500


def test_campaign_spend_reconciles_with_the_ledger_after_a_commit(api):
    """PRD §2.5: "The first is lifetime committed spend: `spent_cents` equals the
    sum of the `amount_cents` over all of the campaign's entries whose
    `entry_type` is `COMMIT`, plus the sum over all entries whose `entry_type` is
    `REFUND`."

    Design: Corner/cross_cutting_complexity_layers/campaign_spent_reconciles_with_budget_ledger
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Recon Co", domain="recon.example")
    headers = make_employer_headers(employer["id"])
    posting = create_posting(employer, title="Recon Engineer")
    campaign = create_active_campaign(employer, name="RC")
    sponsored_job = create_sponsored_job(campaign, posting, employer,
                                         cpc_bid_cents=500)

    hold = create_hold(sponsored_job, employer, 200)
    record_click(campaign, sponsored_job, employer, device_fingerprint="fp-rc-1")

    live_campaign = get_campaign(campaign["id"], employer)
    assert_campaign(live_campaign)
    assert live_campaign["spent_cents"] == 500
    assert live_campaign["held_cents"] == 0

    ledger = get_success_data(api_client.list_campaign_budget_ledger(
        campaign["id"], headers))
    assert_ledger_net_equals_spent(ledger, live_campaign["spent_cents"])

    holds = get_success_data(api_client.list_pacing_holds(sponsored_job["id"], headers))
    assert holds[0]["status"] == "COMMITTED"


def test_committed_event_cost_is_visible_on_the_next_read(api):
    """PRD §3.5: "Committing spend has three further effects in the same
    response, all of them immediate. The campaign's `daily_spent_cents` rises by
    the cleared amount alongside `spent_cents`. The owning employer's
    `balance_cents` rises by the cleared amount, because the employer now owes
    that money."

    Design: Corner/consistency_model/immediate_consistency_event_cost_visible_on_next_read
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Immediate Co", domain="imm.example")
    posting = create_posting(employer, title="Immediate Engineer")
    campaign = create_active_campaign(employer, name="IM3")
    sponsored_job = create_sponsored_job(campaign, posting, employer,
                                         cpc_bid_cents=500)

    event = record_click(campaign, sponsored_job, employer, device_fingerprint="fp-im-1")
    assert event["cost_cents"] == 500

    live_campaign = get_campaign(campaign["id"], employer)
    assert live_campaign["spent_cents"] == 500
    assert live_campaign["daily_spent_cents"] == 500


def test_reaching_the_lifetime_total_completes_and_pauses(api):
    """PRD §3.2: "when a committed spend causes `spent_cents` to reach or exceed
    `total_budget_cents`, the campaign moves to `COMPLETED` in the very same
    request that reached the total, every `SponsoredJob` in the campaign moves to
    `PAUSED`, and every `ACTIVE` `PacingHold` in the campaign moves to
    `RELEASED`."

    Design: Corner/cross_cutting_complexity_layers/committed_spend_on_total_budget_pauses_sponsored_job
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Cascade Co", domain="casc.example")
    headers = make_employer_headers(employer["id"])
    posting = create_posting(employer, title="Cascade Engineer")
    campaign = create_active_campaign(employer, name="CA",
                                      total_budget_cents=1000)
    sponsored_job = create_sponsored_job(campaign, posting, employer,
                                         cpc_bid_cents=1000)

    event = record_click(campaign, sponsored_job, employer, device_fingerprint="fp-casc-1")
    assert event["cost_cents"] == 1000

    completed = get_campaign(campaign["id"], employer)
    assert completed["spent_cents"] == 1000
    assert completed["status"] == "COMPLETED"
    assert get_success_data(api_client.get_sponsored_job(
        sponsored_job["id"], headers))["status"] == "PAUSED"