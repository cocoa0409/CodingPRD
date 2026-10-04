"""Auction clearing and the budget-commit split.

The clearing price fuses the runner-up's pacing-adjusted bid with the winner's
own quality tilt, and the cleared charge is then allocated across the campaign's
outstanding reservations oldest-first with any remainder committed directly.
"""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data, TEST_USERS,
    make_employer_headers, make_seeker_headers,
    set_clock, create_employer, create_seeker, create_posting,
    create_active_campaign, create_sponsored_job, create_campaign,
    get_campaign, get_sponsored_job, get_employer, create_hold,
    setup_competing_employers, setup_campaign_with_two_sponsored_jobs,
    record_click, create_closed_unanswered_application,
    assert_campaign, assert_sponsored_job, assert_pacing_hold,
    assert_budget_ledger_entry,
)

ADMIN = TEST_USERS["admin_headers"]


def test_clearing_price_applies_runner_up_quality_tilt(api):
    """PRD §3.4: "The ranking score of the candidate immediately behind the
    bidder is taken, divided by the bidding job's employer's `quality_score`, and
    multiplied by 100 — which effectively recovers the runner-up's
    pacing-adjusted bid as the floor the winner must beat, stripped of the
    winner's own quality tilt. One cent is then added to that floor, and the
    result is rounded up to the next whole cent."

    Design: Difficulty/combinatorial_formula/auction_clearing_price_gsp_with_quality_tilt_mode_a
    """
    world = setup_competing_employers(quality_b_middle=True, bid_a=300, bid_b=300)

    # Employer B's quality is the middle tier: 5000 bps of a four-application
    # disposition history (two answered of four dispositioned).
    quality_b = get_employer(world["employer_b"]["id"])["quality_score"]
    assert quality_b == 70

    campaign_a = get_campaign(world["campaign_a"]["id"], world["employer_a"])
    event = get_success_data(api.record_event({
        "campaign_id": world["campaign_a"]["id"],
        "sponsored_job_id": world["sponsored_job_a"]["id"],
        "event_type": "CLICK",
        "device_fingerprint": "fp-auction-1",
        "ip_hash": "ip-auction-1",
        "expected_campaign_version": campaign_a["version"],
    }, ADMIN))

    # Runner-up rank is 300 * 70/100 = 210; plus one cent is 211, below the bid.
    assert event["cost_cents"] == 211
    assert event["status"] == "BILLED"
    assert event["billable"] is True


def test_clearing_price_never_exceeds_bidder_bid(api):
    """PRD §3.4: "Finally the rounded amount is bounded below by one cent and
    above by the bidder's own relevant bid amount, so the clearing price is never
    below one cent and never above the bidder's bid."

    Design: Difficulty/combinatorial_formula/auction_clearing_price_gsp_with_quality_tilt_mode_a
    """
    world = setup_competing_employers(bid_a=100, bid_b=300)

    campaign_a = get_campaign(world["campaign_a"]["id"], world["employer_a"])
    event = get_success_data(api.record_event({
        "campaign_id": world["campaign_a"]["id"],
        "sponsored_job_id": world["sponsored_job_a"]["id"],
        "event_type": "CLICK",
        "device_fingerprint": "fp-auction-2",
        "ip_hash": "ip-auction-2",
        "expected_campaign_version": campaign_a["version"],
    }, ADMIN))

    assert event["cost_cents"] >= 1
    assert event["cost_cents"] <= 100


def test_commit_split_fills_holds_oldest_first_then_commits_remainder(api):
    """PRD §3.5: "One `COMMIT` entry is appended for each hold that was fully or
    partially consumed, and if the remaining accumulator is still greater than
    zero after every active hold has been exhausted — including the case where
    the campaign had no active holds at all — a final `COMMIT` entry is appended
    for that remainder, representing unreserved budget spent directly."

    Design: Difficulty/combinatorial_formula/budget_commit_split_waterfall_rounding_order_mode_b
    """
    world = setup_campaign_with_two_sponsored_jobs(
        daily_budget_cents=300000, total_budget_cents=3000000,
        bid1=500, bid2=400, hold1=200, hold2=200)
    employer, headers = world["employer"], world["employer_headers"]
    campaign = world["campaign"]
    sj1 = world["sponsored_jobs"][0]

    event = record_click(campaign, sj1, employer, device_fingerprint="fp-wf-1")

    # Second price: runner-up rank 400, winner quality 100 -> 400 + 1.
    assert event["cost_cents"] == 401
    assert event["status"] == "BILLED"

    for hold in world["holds"]:
        live_hold = get_success_data(api_client.list_pacing_holds(
            hold["sponsored_job_id"], headers))
        assert live_hold[0]["status"] == "COMMITTED"

    live_campaign = get_campaign(campaign["id"], employer)
    assert_campaign(live_campaign)
    assert live_campaign["spent_cents"] == 401
    assert live_campaign["held_cents"] == 0


def test_commit_split_ledger_rows_match_the_waterfall(api):
    """PRD §3.5: "The cleared cost is placed in a remaining-amount accumulator
    that starts at the full cleared amount. The campaign's `PacingHold` records
    whose `status` is `ACTIVE` are then consumed in ascending `created_at` order
    — oldest reservation first, with the record `id` never used as a tie-break —
    and for each hold a take amount is computed as the smaller of that hold's
    `amount_cents` and the remaining accumulator."

    Design: Difficulty/combinatorial_formula/budget_commit_split_waterfall_rounding_order_mode_b
    """
    world = setup_campaign_with_two_sponsored_jobs(
        daily_budget_cents=300000, total_budget_cents=3000000,
        bid1=500, bid2=400, hold1=200, hold2=200)
    employer, headers = world["employer"], world["employer_headers"]
    campaign = world["campaign"]
    sj1 = world["sponsored_jobs"][0]

    record_click(campaign, sj1, employer, device_fingerprint="fp-wf-2")

    ledger = get_success_data(api_client.list_campaign_budget_ledger(
        campaign["id"], headers, params={"entry_type": "COMMIT"}))
    for entry in ledger:
        assert_budget_ledger_entry(entry)

    amounts = [entry["amount_cents"] for entry in ledger]
    assert amounts == [200, 200, 1]
    # The third entry is the direct remainder beyond the reserved holds.
    assert sum(amounts) == 401