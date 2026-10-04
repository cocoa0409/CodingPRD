"""Temporal overlap rules: the refund window and pacing-hold exclusivity.

Both rules define a window during which some action is or is not permitted, but
they have different geometry — a half-open 24-hour window on the refund side and
zero-tolerance exclusivity per sponsored job per logical day on the hold side.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of,
    get_success_data, TEST_USERS, ApiErrorId,
    make_employer_headers, set_clock, create_employer, create_posting,
    create_active_campaign, create_sponsored_job, create_hold,
    get_campaign, record_click, refund_payload,
    assert_pacing_hold, assert_sponsor_event,
)

ADMIN = TEST_USERS["admin_headers"]
TRUST = TEST_USERS["trust_headers"]


# ─── Refund window on a sponsor event ─────────────────

def _refund_scenario():
    """ACTIVE CPC campaign with two billed clicks recorded at the start instant."""
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="WindowCo", domain="win.example")
    headers = make_employer_headers(employer["id"])
    posting = create_posting(employer, title="Window Engineer",
                             description_text="Refund window.")
    campaign = create_active_campaign(
        employer, name="WD", pricing_model="CPC",
        daily_budget_cents=300000, total_budget_cents=3000000)
    sponsored_job = create_sponsored_job(campaign, posting, employer,
                                         cpc_bid_cents=400)

    event1 = record_click(campaign, sponsored_job, employer, device_fingerprint="fp-wd-1")
    event2 = record_click(campaign, sponsored_job, employer, device_fingerprint="fp-wd-2")
    return employer, campaign, sponsored_job, event1, event2


def test_refund_allowed_at_the_twenty_four_hour_boundary(api):
    """PRD §3.8: "The second is the refund window: the event's `occurred_at` must
    be no more than 24 hours before the current logical clock, and an event whose
    `occurred_at` is more than 24 hours in the past fails with
    `ERR_REFUND_WINDOW_EXPIRED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/refund_window_tolerance_boundary_on_sponsor_event
    """
    employer, campaign, sponsored_job, event1, event2 = _refund_scenario()
    headers = make_employer_headers(employer["id"])

    get_success_data(api.set_current_utc({"current_utc": "2026-09-02T00:00:00Z"}, ADMIN))
    version = get_campaign(campaign["id"], employer)["version"]

    res = api.refund_event(event1["id"], refund_payload(version), TRUST)
    refunded = validate_success(res, 200)
    assert_sponsor_event(refunded)
    assert refunded["status"] == "REFUNDED"


def test_refund_rejected_just_past_the_window(api):
    """PRD §3.8: "an event whose `occurred_at` is more than 24 hours in the past
    fails with `ERR_REFUND_WINDOW_EXPIRED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/refund_window_tolerance_boundary_on_sponsor_event
    """
    employer, campaign, sponsored_job, event1, event2 = _refund_scenario()

    get_success_data(api.set_current_utc({"current_utc": "2026-09-02T00:00:00Z"}, ADMIN))
    version = get_campaign(campaign["id"], employer)["version"]
    validate_success(api.refund_event(event1["id"], refund_payload(version), TRUST), 200)

    get_success_data(api.set_current_utc({"current_utc": "2026-09-02T00:00:01Z"}, ADMIN))
    version2 = get_campaign(campaign["id"], employer)["version"]

    res = api.refund_event(event2["id"], refund_payload(version2), TRUST)
    assert res.status_code == 409
    validate_error_is_one_of(res, [
        ApiErrorId.ERR_REFUND_WINDOW_EXPIRED.value,
        ApiErrorId.ERR_EVENT_NOT_REFUNDABLE.value,
    ])


# ─── Pacing-hold exclusivity ──────────────────────────

def _hold_scenario():
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="HoldCo", domain="hold.example")
    headers = make_employer_headers(employer["id"])
    posting = create_posting(employer, title="Hold Engineer",
                             description_text="Hold exclusivity.")
    campaign = create_active_campaign(
        employer, name="HD", pricing_model="CPC",
        daily_budget_cents=100000, total_budget_cents=1000000)
    sponsored_job = create_sponsored_job(campaign, posting, employer)
    hold = create_hold(sponsored_job, employer, 400)
    return employer, campaign, sponsored_job, hold


def test_second_active_hold_on_same_job_is_rejected(api):
    """PRD §3.5: "First, a sponsored job may hold only one reservation per
    logical day: if the sponsored job already has an `ACTIVE` hold for the
    current logical day, the new request is rejected with
    `ERR_PACING_HOLD_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/pacing_hold_exclusivity_per_job_per_day
    """
    employer, campaign, sponsored_job, hold = _hold_scenario()
    headers = make_employer_headers(employer["id"])

    res = api.create_pacing_hold(sponsored_job["id"], {"amount_cents": 400}, headers)
    validate_error(res, ApiErrorId.ERR_PACING_HOLD_OVERLAP.value, expected_status=409)


def test_rejected_overlapping_hold_leaves_reservation_untouched(api):
    """PRD §3.5: "Creating a hold appends a `HOLD` entry to the campaign's ledger
    and raises the campaign's `held_cents` by the reserved amount" — a rejected
    hold reserves nothing.

    Design: Difficulty/resource_temporal_overlap/pacing_hold_exclusivity_per_job_per_day
    """
    employer, campaign, sponsored_job, hold = _hold_scenario()
    headers = make_employer_headers(employer["id"])

    res = api.create_pacing_hold(sponsored_job["id"], {"amount_cents": 400}, headers)
    assert res.status_code == 409

    live_hold = get_success_data(api_client.list_pacing_holds(
        sponsored_job["id"], headers))
    assert len(live_hold) == 1
    assert_pacing_hold(live_hold[0])
    assert live_hold[0]["status"] == "ACTIVE"
    assert get_campaign(campaign["id"], employer)["held_cents"] == 400