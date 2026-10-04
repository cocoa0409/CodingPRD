"""Dual-variant calculation behaviour.

The pacing calculation projects forward from a time target while the realized
calculation measures delivered spend against an even schedule, and the employer
quality signal produces two different scores for the same pair of applications
depending on whether the unanswered one has been closed. These tests pin the
divergence between each pair of variants.
"""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data, TEST_USERS,
    make_employer_headers, make_seeker_headers,
    set_clock, create_employer, create_seeker, create_posting,
    create_active_campaign, create_sponsored_job, get_campaign,
    get_sponsored_job, get_employer, start_application, record_click,
    create_completed_application, create_answered_application,
    assert_pacing_multiplier, assert_sponsored_job, assert_employer,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── Pacing multiplier: scheduled vs realized ─────────

def _pacing_scenario(daily_budget_cents=100000, total_budget_cents=1000000,
                     cpc_bid_cents=200):
    """ACTIVE CPC campaign with one sponsored job and no spend yet."""
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="PaceCo", domain="pace.example",
                               ats_provider="GREENHOUSE")
    campaign = create_active_campaign(
        employer, name="Always-On Engineering", pricing_model="CPC",
        daily_budget_cents=daily_budget_cents,
        total_budget_cents=total_budget_cents)
    posting = create_posting(employer, title="Staff Site Reliability Engineer",
                             location="Austin, TX",
                             description_text="Own reliability for the job marketplace.")
    sponsored_job = create_sponsored_job(campaign, posting, employer,
                                         cpc_bid_cents=cpc_bid_cents,
                                         cpa_bid_cents=900)
    return employer, campaign, posting, sponsored_job


def test_scheduled_and_realized_pacing_multipliers_diverge(api):
    """PRD §3.2: "The two multipliers move in opposite directions for the same
    data, and this is intentional rather than a defect: a campaign that is behind
    pace gets a scheduled multiplier above 1.0 to push it forward and a realized
    multiplier below 1.0 because it has in fact delivered less than its
    even-schedule share."
    PRD §3.2: "the elapsed fraction is treated as the target fraction of the
    day's budget that ought to have been spent by now, and the actual fraction is
    computed as `daily_spent_cents` divided by `daily_budget_cents`."

    Design: Difficulty/dual_variant_calc/pacing_multiplier_scheduled_vs_realized_diverge_for_fresh_campaign
    """
    employer, campaign, posting, sponsored_job = _pacing_scenario(cpc_bid_cents=50000)

    # A single billed click at the day's start commits half the daily budget
    # (the solo bidder clears at its own bid).
    recorded = record_click(campaign, sponsored_job, employer,
                            device_fingerprint="fp-pace-1")
    assert recorded["cost_cents"] == 50000

    get_success_data(api.set_current_utc({"current_utc": "2026-09-01T18:00:00Z"},
                                         ADMIN))

    sponsored_job = get_sponsored_job(sponsored_job["id"], employer)
    assert_pacing_multiplier(sponsored_job["scheduled_pacing_multiplier"])
    assert_pacing_multiplier(sponsored_job["realized_pacing_multiplier"])

    # Three quarters of the day has elapsed with half the budget committed, so
    # the campaign is behind pace: the scheduled multiplier is 1.0 + (0.75 -
    # 0.5) = 1.25, while the realized multiplier is the delivered fraction of
    # the even schedule, 50000 / 75000, which sits below 1.0.
    assert sponsored_job["scheduled_pacing_multiplier"] == pytest.approx(1.25, abs=1e-9)
    assert sponsored_job["realized_pacing_multiplier"] == pytest.approx(0.667, abs=1e-3)
    assert sponsored_job["scheduled_pacing_multiplier"] > sponsored_job["realized_pacing_multiplier"]

    live_campaign = get_campaign(campaign["id"], employer)
    assert live_campaign["daily_spent_cents"] == 50000
    assert live_campaign["daily_budget_cents"] == 100000


def test_scheduled_pacing_multiplier_stays_in_warmup_band(api):
    """PRD §3.2: "If that elapsed fraction is less than 0.05 — the first 72
    minutes of the logical day, which is 5 percent of 86,400 seconds — the
    multiplier is exactly 1.0 and no further arithmetic is done, because the
    system will not front-load spend during the warm-up window."

    Design: Difficulty/dual_variant_calc/pacing_multiplier_scheduled_vs_realized_diverge_for_fresh_campaign
    """
    employer, campaign, posting, sponsored_job = _pacing_scenario()

    get_success_data(api.set_current_utc({"current_utc": "2026-09-01T01:00:00Z"},
                                         ADMIN))
    sponsored_job = get_sponsored_job(sponsored_job["id"], employer)

    # One hour into the day is still inside the warm-up window, so the
    # scheduled multiplier is pinned at 1.0 no matter how much has been spent.
    assert sponsored_job["scheduled_pacing_multiplier"] == pytest.approx(1.0, abs=1e-9)
    assert_sponsored_job(sponsored_job)


# ─── Employer quality signal: same history, two scores ───

def test_quality_score_drops_thirty_points_when_unanswered_application_closes(api):
    """PRD §3.7: "The employer `quality_score` exists to make follow-through a
    first-class ranking input, and the `employer_quality_signal` that produces it
    recomputes every time an application of that employer receives a responding
    disposition or is closed without one."
    PRD §3.7: "First, an employer whose history is entirely non-responding
    dispositions scores exactly its tier with a delta of zero, so an employer
    with three responses out of four but no hires scores less than an employer
    with the same three-of-four response history and one hire."

    Design: Difficulty/dual_variant_calc/quality_signal_dual_variant_same_history_two_scores
    """
    employer = create_employer(legal_name="SignalCo", domain="signal.example",
                               ats_provider="LEVER")
    seeker = create_seeker(full_name="Quinn A")
    posting = create_posting(employer, title="Data Platform Engineer",
                             location="Austin, TX",
                             description_text="Build the jobs data platform.")
    employer_headers = make_employer_headers(employer["id"])

    answered = create_answered_application(posting, seeker, employer, disposition="REVIEWED")
    unanswered = create_completed_application(posting, seeker, employer)

    before = get_employer(employer["id"])
    assert before["quality_score"] == 100
    assert before["response_rate_bps"] == 10000

    # Closing without a response makes the unanswered application count as a
    # non-response, halving the response rate.
    get_success_data(api.close_application(unanswered["id"], employer_headers))

    after = get_employer(employer["id"])
    assert_employer(after)
    assert after["response_rate_bps"] == 5000
    assert after["quality_score"] == 70
    assert before["quality_score"] - after["quality_score"] == 30


def test_response_rate_is_the_responding_share_of_dispositioned_applications(api):
    """PRD §3.7: "The responding subset of that population is the applications
    whose `disposition` is `REVIEWED`, `INTERVIEW`, `REJECTED` or `HIRED`. The
    employer's `response_rate_bps` is then the number of responding applications
    multiplied by 10,000, divided by the number of dispositioned applications,
    with the fractional part truncated toward zero to a whole number of basis
    points".

    Design: Difficulty/dual_variant_calc/quality_signal_dual_variant_same_history_two_scores
    """
    employer = create_employer(legal_name="SignalCo2", domain="signal2.example")
    seeker = create_seeker(full_name="Riley B")
    posting = create_posting(employer, title="Data Platform Engineer II",
                             description_text="Build the jobs data platform too.")

    create_answered_application(posting, seeker, employer, disposition="REVIEWED")
    unanswered = create_completed_application(posting, seeker, employer)

    # While the second application is still open it is not yet dispositioned,
    # so the rate covers the answered one alone.
    open_state = get_employer(employer["id"])
    assert open_state["response_rate_bps"] == 10000

    get_success_data(api.close_application(
        unanswered["id"], make_employer_headers(employer["id"])))

    # The closed, unanswered application joins the dispositioned population.
    closed_state = get_employer(employer["id"])
    assert closed_state["response_rate_bps"] == 5000
    assert closed_state["response_rate_bps"] == open_state["response_rate_bps"] // 2