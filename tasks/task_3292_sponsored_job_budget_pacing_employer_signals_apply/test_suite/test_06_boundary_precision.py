"""Boundary precision on the freshness and pacing thresholds.

Posting freshness flips on inclusive day boundaries, and the pacing warm-up
band flips on an inclusive elapsed-fraction boundary, so both are probed just
below and exactly at the stated cut-off.
"""
import pytest

from test_helpers import (
    api_client, get_success_data, TEST_USERS,
    make_employer_headers, set_clock, create_employer, create_posting,
    create_active_campaign, create_sponsored_job, get_posting, get_sponsored_job,
    assert_job_posting, assert_pacing_multiplier,
    STALE_AFTER_DAYS, EXPIRED_AFTER_DAYS, WARMUP_FRACTION,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── Posting freshness: 30- and 60-day boundaries ─────

def _aged_posting():
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="BoundaryCo", domain="bnd.example",
                               ats_provider="WORKDAY")
    posting = create_posting(employer, title="Boundary Engineer",
                             location="Boise, ID",
                             description_text="Boundary posting.",
                             external_posting_id="BND-1")
    return employer, posting


def test_freshness_stays_fresh_below_thirty_days(api):
    """PRD §3.1: "a snapshot is `FRESH` while its age is less than 30 whole days,
    `STALE` once its age reaches 30 whole days and up to 59 whole days, and
    `EXPIRED` once its age is 60 whole days or more."

    Design: Difficulty/boundary_precision_check/posting_freshness_day_boundaries_at_30_and_60
    """
    employer, posting = _aged_posting()

    get_success_data(api.set_current_utc({"current_utc": "2026-09-30T00:00:00Z"}, ADMIN))
    at_29 = get_posting(posting["id"])
    assert at_29["current_freshness"] == "FRESH"
    assert at_29["state"] == "ACTIVE"


def test_freshness_flips_to_stale_at_exactly_thirty_days(api):
    """PRD §3.1: "Age is measured by subtracting `ingested_at` from the current
    logical instant, dividing by 86,400 seconds and truncating the fractional
    part, so exactly 30 days and 30 days and 12 hours both compute to an age of
    30 days."

    Design: Difficulty/boundary_precision_check/posting_freshness_day_boundaries_at_30_and_60
    """
    employer, posting = _aged_posting()

    get_success_data(api.set_current_utc({"current_utc": "2026-10-01T00:00:00Z"}, ADMIN))
    at_30 = get_posting(posting["id"])
    assert at_30["current_freshness"] == "STALE"
    assert at_30["state"] == "STALE"


def test_freshness_flips_to_expired_at_exactly_sixty_days(api):
    """PRD §3.1: "EXPIRED once its age is 60 whole days or more" — the boundary
    is inclusive, so a posting aged exactly 60 days is expired.

    Design: Difficulty/boundary_precision_check/posting_freshness_day_boundaries_at_30_and_60
    """
    employer, posting = _aged_posting()

    get_success_data(api.set_current_utc({"current_utc": "2026-10-31T00:00:00Z"}, ADMIN))
    at_60 = get_posting(posting["id"])
    assert at_60["current_freshness"] == "EXPIRED"
    assert at_60["state"] == "EXPIRED"


# ─── Pacing warm-up: 0.05 elapsed-fraction boundary ───

def _warmup_scenario():
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="WarpCo", domain="warp.example")
    posting = create_posting(employer, title="Warmup Engineer",
                             description_text="Warm up the pacer.")
    campaign = create_active_campaign(
        employer, name="WP", pricing_model="CPC",
        daily_budget_cents=100000, total_budget_cents=1000000)
    sponsored_job = create_sponsored_job(campaign, posting, employer,
                                         cpc_bid_cents=200)
    return employer, campaign, sponsored_job


def test_pacing_multiplier_pinned_during_warmup_window(api):
    """PRD §3.2: "If that elapsed fraction is less than 0.05 — the first 72
    minutes of the logical day, which is 5 percent of 86,400 seconds — the
    multiplier is exactly 1.0 and no further arithmetic is done, because the
    system will not front-load spend during the warm-up window."

    Design: Difficulty/boundary_precision_check/pacing_warmup_fraction_boundary_at_five_percent
    """
    employer, campaign, sponsored_job = _warmup_scenario()

    get_success_data(api.set_current_utc({"current_utc": "2026-09-01T01:11:54Z"}, ADMIN))
    live_job = get_sponsored_job(sponsored_job["id"], employer)

    # 4314 of 86400 seconds elapsed — strictly inside the warm-up band.
    assert (4314 / 86400) < WARMUP_FRACTION
    assert live_job["scheduled_pacing_multiplier"] == pytest.approx(1.0, abs=1e-9)
    assert_pacing_multiplier(live_job["scheduled_pacing_multiplier"])


def test_pacing_multiplier_advances_at_exactly_five_percent(api):
    """PRD §3.2: "Otherwise the elapsed fraction is treated as the target
    fraction of the day's budget that ought to have been spent by now, and the
    actual fraction is computed as `daily_spent_cents` divided by
    `daily_budget_cents`."
    PRD §3.2: "If the actual fraction is at or below the target fraction the
    campaign is behind pace, and the raw multiplier is 1.0 plus the difference
    between the target and the actual".

    Design: Difficulty/boundary_precision_check/pacing_warmup_fraction_boundary_at_five_percent
    """
    employer, campaign, sponsored_job = _warmup_scenario()

    get_success_data(api.set_current_utc({"current_utc": "2026-09-01T01:12:00Z"}, ADMIN))
    live_job = get_sponsored_job(sponsored_job["id"], employer)

    # Exactly 4320 of 86400 seconds elapsed: the warm-up rule no longer applies,
    # nothing has been spent, so the campaign is behind by the whole target.
    assert (4320 / 86400) == pytest.approx(WARMUP_FRACTION, abs=1e-12)
    assert live_job["scheduled_pacing_multiplier"] == pytest.approx(1.05, abs=1e-9)