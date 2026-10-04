"""Transitive cascades from a single transition.

Committing the total budget completes a campaign, which pauses its sponsored
jobs, which releases their active pacing holds. Suspending an employer cascades
through its postings and campaigns to the same sponsored jobs and holds.
"""
import pytest

from test_helpers import (
    api_client, get_success_data, TEST_USERS,
    make_employer_headers, set_clock, create_employer, create_posting,
    create_active_campaign, create_sponsored_job, create_hold,
    get_campaign,
)

ADMIN = TEST_USERS["admin_headers"]
TRUST = TEST_USERS["trust_headers"]


def _live_hold(sponsored_job_id, employer):
    return get_success_data(api_client.list_pacing_holds(
        sponsored_job_id, make_employer_headers(employer["id"])))[0]


def test_total_budget_commit_cascades_to_jobs_and_holds(api):
    """PRD §3.5: "the campaign is re-tested against its lifetime total: if
    `spent_cents` has now reached or exceeded `total_budget_cents`, the campaign
    is moved to `COMPLETED` in this same request, every sponsored job in it is
    moved to `PAUSED`, and every `ACTIVE` hold in it is moved to `RELEASED`."

    Design: Difficulty/transitive_cascade/spend_commit_cascade_reaches_sponsored_job_and_pacing_holds
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="ChainCo", domain="chain.example")
    headers = make_employer_headers(employer["id"])
    campaign = create_active_campaign(
        employer, name="CH", pricing_model="CPC",
        daily_budget_cents=20000, total_budget_cents=1000)
    posting1 = create_posting(employer, title="Chain Engineer",
                              description_text="Chain one.")
    posting2 = create_posting(employer, title="Chain Engineer II",
                              description_text="Chain two.")
    sj1 = create_sponsored_job(campaign, posting1, employer, cpc_bid_cents=1000)
    sj2 = create_sponsored_job(campaign, posting2, employer, cpc_bid_cents=1000)

    hold1 = create_hold(sj1, employer, 1000)
    hold2 = create_hold(sj2, employer, 900)

    live_campaign = get_campaign(campaign["id"], employer)
    event = get_success_data(api.record_event({
        "campaign_id": campaign["id"],
        "sponsored_job_id": sj1["id"],
        "event_type": "CLICK",
        "device_fingerprint": "fp-ch-1",
        "ip_hash": "ip-ch-1",
        "expected_campaign_version": live_campaign["version"],
    }, ADMIN))

    # Runner-up rank 1000, capped at the bidder's own 1000-cent bid.
    assert event["cost_cents"] == 1000

    # Link 1: the campaign completes in the same request.
    completed = get_campaign(campaign["id"], employer)
    assert completed["status"] == "COMPLETED"

    # Link 2: every sponsored job in the campaign is paused.
    assert get_success_data(api_client.get_sponsored_job(sj1["id"], headers))["status"] == "PAUSED"
    assert get_success_data(api_client.get_sponsored_job(sj2["id"], headers))["status"] == "PAUSED"

    # Link 3: the reservation on the serving job was already consumed by the
    # commit split of PRD 3.5 before the completion cascade ran, so only the
    # reservation on the non-serving job is moved to RELEASED. Either way no
    # reservation is left stranded: the campaign's reserved budget is zero.
    assert _live_hold(sj1["id"], employer)["status"] == "COMMITTED"
    assert _live_hold(sj2["id"], employer)["status"] == "RELEASED"
    assert completed["held_cents"] == 0


def test_employer_suspension_cascades_through_postings_campaigns_and_holds(api):
    """PRD §3.1: "In the same response, every `JobPosting` belonging to that
    employer moves to `SUSPENDED`, every `Campaign` belonging to that employer
    moves to `PAUSED`, every `SponsoredJob` inside those campaigns moves to
    `PAUSED`, and every `PacingHold` that was `ACTIVE` on any of those sponsored
    jobs moves to `RELEASED`, returning its reserved budget."

    Design: Difficulty/transitive_cascade/employer_suspension_cascade_reaches_postings_campaigns_and_holds
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="SuspendCo", domain="susp.example")
    headers = make_employer_headers(employer["id"])
    posting = create_posting(employer, title="Suspension Engineer",
                             location="Reno, NV",
                             description_text="Suspension target.")
    campaign = create_active_campaign(employer, name="SU", pricing_model="CPC")
    sponsored_job = create_sponsored_job(campaign, posting, employer)
    hold = create_hold(sponsored_job, employer, 600)

    suspended = get_success_data(api.suspend_employer(
        employer["id"], {"reason": "Misleading posting: pay-to-start fee"}, TRUST))

    # Link 1: the employer itself.
    assert suspended["status"] == "SUSPENDED"
    assert suspended["billing_status"] == "FROZEN"

    # Link 2: postings and campaign.
    assert get_success_data(api_client.get_job_posting(posting["id"], ADMIN))["state"] == "SUSPENDED"
    live_campaign = get_campaign(campaign["id"], employer)
    assert live_campaign["status"] == "PAUSED"

    # Link 3 and 4: the sponsored job and its released reservation.
    assert get_success_data(api_client.get_sponsored_job(
        sponsored_job["id"], headers))["status"] == "PAUSED"
    assert _live_hold(sponsored_job["id"], employer)["status"] == "RELEASED"
    assert live_campaign["held_cents"] == 0


def test_suspension_pauses_every_sponsored_job_not_only_eligible_ones(api):
    """PRD §3.1: "Note that the sponsored jobs are paused directly by the
    suspension rather than by their campaign's pause, because the suspension
    cascade reaches them in a single hop from the employer; the campaign pause
    would have paused only the sponsored jobs that were `ELIGIBLE`, whereas the
    suspension pauses all of them."

    Design: Difficulty/transitive_cascade/employer_suspension_cascade_reaches_postings_campaigns_and_holds
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="SuspendAllCo", domain="suspall.example")
    headers = make_employer_headers(employer["id"])
    posting = create_posting(employer, title="Suspension Engineer II",
                             location="Reno, NV",
                             description_text="Suspension target two.")
    campaign = create_active_campaign(employer, name="SU2")
    sponsored_job = create_sponsored_job(campaign, posting, employer)

    # Pause the campaign first so its sponsored job is already PAUSED; the
    # suspension cascade still has to reach it.
    api.pause_campaign(campaign["id"], headers)
    api.resume_campaign(campaign["id"], headers)
    assert get_success_data(api_client.get_sponsored_job(
        sponsored_job["id"], headers))["status"] == "ELIGIBLE"

    get_success_data(api.suspend_employer(
        employer["id"], {"reason": "Misleading posting: wire transfer"}, TRUST))

    assert get_success_data(api_client.get_sponsored_job(
        sponsored_job["id"], headers))["status"] == "PAUSED"
    assert get_campaign(campaign["id"], employer)["status"] == "PAUSED"


def test_completed_campaign_pauses_every_sponsored_job_in_it(api):
    """PRD §3.5: "if `spent_cents` has now reached or exceeded
    `total_budget_cents`, the campaign is moved to `COMPLETED` in this same
    request, every sponsored job in it is moved to `PAUSED`".

    Design: Difficulty/transitive_cascade/spend_commit_cascade_reaches_sponsored_job_and_pacing_holds
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="ChainCo2", domain="chain2.example")
    headers = make_employer_headers(employer["id"])
    campaign = create_active_campaign(
        employer, name="CH2", pricing_model="CPC",
        daily_budget_cents=20000, total_budget_cents=1000)
    posting1 = create_posting(employer, title="Chain Engineer",
                              description_text="Chain one again.")
    posting2 = create_posting(employer, title="Chain Engineer II",
                              description_text="Chain two again.")
    sj1 = create_sponsored_job(campaign, posting1, employer, cpc_bid_cents=1000)
    sj2 = create_sponsored_job(campaign, posting2, employer, cpc_bid_cents=1000)

    live_campaign = get_campaign(campaign["id"], employer)
    api.record_event({
        "campaign_id": campaign["id"],
        "sponsored_job_id": sj1["id"],
        "event_type": "CLICK",
        "device_fingerprint": "fp-ch-2",
        "ip_hash": "ip-ch-2",
        "expected_campaign_version": live_campaign["version"],
    }, ADMIN)

    assert get_campaign(campaign["id"], employer)["status"] == "COMPLETED"
    # Both sponsored jobs fall, not just the one that served the click.
    assert get_success_data(api_client.get_sponsored_job(sj1["id"], headers))["status"] == "PAUSED"
    assert get_success_data(api_client.get_sponsored_job(sj2["id"], headers))["status"] == "PAUSED"