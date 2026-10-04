"""Campaign budget cycling and posting state re-derivation.

The campaign machine is cyclic rather than a pipeline: it leaves ACTIVE for
PACING_HOLD and re-enters ACTIVE on a day rollover, and it reaches its terminal
COMPLETED state only when committed spend reaches the lifetime budget. The
posting machine is compound: its state is derived from the newest snapshot's
freshness, so a fresh re-ingestion revives an expired posting.
"""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data, TEST_USERS,
    make_employer_headers, set_clock, create_employer, create_posting,
    create_active_campaign, create_sponsored_job, get_campaign, get_posting,
    record_click, ingest_version,
    assert_campaign, assert_job_posting,
)

ADMIN = TEST_USERS["admin_headers"]


def setup_cycle_scenario(daily_budget_cents=6000, total_budget_cents=12000,
                         cpc_bid_cents=6000):
    """ACTIVE CPC campaign whose solo bid clears at its full bid amount."""
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="CycleCo", domain="cycle.example")
    campaign = create_active_campaign(
        employer, name="CY", pricing_model="CPC",
        daily_budget_cents=daily_budget_cents,
        total_budget_cents=total_budget_cents)
    posting = create_posting(employer, title="Cyclic Engineer",
                             location="Austin, TX",
                             description_text="Cycle the budget.")
    sponsored_job = create_sponsored_job(campaign, posting, employer,
                                         cpc_bid_cents=cpc_bid_cents,
                                         cpa_bid_cents=900)
    return employer, campaign, posting, sponsored_job


def test_campaign_cycles_through_pacing_hold_back_to_active(api):
    """PRD §3.2: "When `daily_spent_cents` reaches or exceeds `daily_budget_cents`,
    the campaign leaves `ACTIVE` for `PACING_HOLD`, and every `SponsoredJob` in
    that campaign that is currently `ELIGIBLE` moves to `BUDGET_HOLD`."
    PRD §3.2: "A day rollover resets the daily clock. The rollover fires whenever
    the logical clock crosses into a calendar date later than a campaign's
    recorded `day_open_date`, and it does three things for each affected
    campaign: `daily_spent_cents` is reset to 0, `day_open_date` is advanced to
    the new logical day, and any campaign sitting in `PACING_HOLD` returns to
    `ACTIVE` because it now has a fresh daily budget to spend."

    Design: Difficulty/non_linear_state_machine/campaign_budget_cycle_returns_to_active_and_completes
    """
    employer, campaign, posting, sponsored_job = setup_cycle_scenario()

    record_click(campaign, sponsored_job, employer, device_fingerprint="fp-cy-1")
    after_spend = get_campaign(campaign["id"], employer)
    assert after_spend["status"] == "PACING_HOLD"
    assert after_spend["daily_spent_cents"] == 6000
    assert after_spend["daily_spent_cents"] == after_spend["daily_budget_cents"]

    get_success_data(api.set_current_utc({"current_utc": "2026-09-02T00:00:00Z"}, ADMIN))
    after_rollover = get_campaign(campaign["id"], employer)
    assert after_rollover["status"] == "ACTIVE"
    assert after_rollover["daily_spent_cents"] == 0
    assert after_rollover["day_open_date"] == "2026-09-02T00:00:00Z"


def test_campaign_reaches_completed_once_lifetime_budget_is_committed(api):
    """PRD §3.2: "Lifetime exhaustion is a stronger and terminal condition: when
    a committed spend causes `spent_cents` to reach or exceed `total_budget_cents`,
    the campaign moves to `COMPLETED` in the very same request that reached the
    total, every `SponsoredJob` in the campaign moves to `PAUSED`, and every
    `ACTIVE` `PacingHold` in the campaign moves to `RELEASED`."

    Design: Difficulty/non_linear_state_machine/campaign_budget_cycle_returns_to_active_and_completes
    """
    employer, campaign, posting, sponsored_job = setup_cycle_scenario()

    # First day exhausts the daily budget and parks the campaign in PACING_HOLD.
    record_click(campaign, sponsored_job, employer, device_fingerprint="fp-cy-2a")
    get_success_data(api.set_current_utc({"current_utc": "2026-09-02T00:00:00Z"}, ADMIN))

    # A second cleared click on the fresh day takes lifetime spend to 12000.
    record_click(campaign, sponsored_job, employer, device_fingerprint="fp-cy-2b")
    final = get_campaign(campaign["id"], employer)

    assert final["status"] == "COMPLETED"
    assert final["spent_cents"] == 12000
    assert final["spent_cents"] >= final["total_budget_cents"]

    frozen_job = get_success_data(api_client.get_sponsored_job(
        sponsored_job["id"], make_employer_headers(employer["id"])))
    assert frozen_job["status"] == "PAUSED"


def test_expired_posting_revives_to_active_after_fresh_ingestion(api):
    """PRD §3.1: "Otherwise, if `current_freshness` is `EXPIRED` the posting's
    `state` is `EXPIRED`; if `current_freshness` is `STALE` the state is `STALE`;
    and if `current_freshness` is `FRESH` the state is `ACTIVE`."
    PRD §3.1: "a snapshot is `FRESH` while its age is less than 30 whole days,
    `STALE` once its age reaches 30 whole days and up to 59 whole days, and
    `EXPIRED` once its age is 60 whole days or more."

    Design: Difficulty/non_linear_state_machine/job_posting_state_reexpires_and_revives_via_supersession
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="ReviveCo", domain="revive.example",
                               ats_provider="WORKDAY")
    posting = create_posting(employer, title="Lifecycle Engineer",
                             location="Boise, ID",
                             description_text="Freshness matters.",
                             external_posting_id="REV-1")

    get_success_data(api.set_current_utc({"current_utc": "2026-11-05T00:00:00Z"}, ADMIN))
    decayed = get_posting(posting["id"])
    assert decayed["current_freshness"] == "EXPIRED"
    assert decayed["state"] == "EXPIRED"

    ingest_version(posting, employer, "REV-1",
                   title="Lifecycle Engineer",
                   description_text="Freshness matters again.")
    revived = get_posting(posting["id"])
    assert revived["current_freshness"] == "FRESH"
    assert revived["state"] == "ACTIVE"


def test_expiry_side_effect_pauses_sponsored_job_but_not_campaign(api):
    """PRD §3.1: "A posting that goes `STALE` → `EXPIRED`, or directly `ACTIVE`
    → `EXPIRED` when a single re-derivation skips the intermediate freshness, is
    terminal for distribution, and every `SponsoredJob` sponsoring that posting
    is moved to `PAUSED` in the same response."

    Design: Difficulty/non_linear_state_machine/job_posting_state_reexpires_and_revives_via_supersession
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="DecayCo", domain="decay.example")
    posting = create_posting(employer, title="Decay Engineer",
                             location="Boise, ID",
                             description_text="Decay.", external_posting_id="DEC-1")
    campaign = create_active_campaign(employer, name="DC")
    sponsored_job = create_sponsored_job(campaign, posting, employer)

    get_success_data(api.set_current_utc({"current_utc": "2026-11-05T00:00:00Z"}, ADMIN))

    expired = get_posting(posting["id"])
    assert expired["state"] == "EXPIRED"
    paused_job = get_success_data(api_client.get_sponsored_job(
        sponsored_job["id"], make_employer_headers(employer["id"])))
    assert paused_job["status"] == "PAUSED"

    live_campaign = get_campaign(campaign["id"], employer)
    assert live_campaign["status"] == "ACTIVE"