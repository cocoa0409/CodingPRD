"""Boundary precision on the five-minute duration threshold (300s inclusive)."""
from test_helpers import (
    TEST_USERS, validate_success,
    set_clock, create_active_schedule, setup_active_dsp,
    create_report_with_lines,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]


def _setup_draft_report():
    set_clock("2026-09-10T00:00:00Z")
    create_active_schedule()
    dsp, dsp_headers, ack = setup_active_dsp()
    report, _ = create_report_with_lines(dsp, dsp_headers, "2026-08", [])
    return dsp, dsp_headers, report


def test_exactly_five_minutes_prices_at_short_rate(api):
    """PRD §2.6: "The five-minute boundary is exact: a duration of exactly 300
    seconds prices at the short rate, while 301 seconds prices at the long-form
    rule."
    PRD §3.3: "When `duration_seconds` is at most 300, the unit price is that
    schedule's `rate_cents_under_5min`."

    Design: Difficulty/boundary_precision_check/long_track_five_minute_boundary
    """
    dsp, dsp_headers, report = _setup_draft_report()
    line = validate_success(api_client.create_usage_line(
        dsp["id"], report["id"],
        {"isrc": "USAA19900021", "track_title": "Sora",
         "plays_count": 10, "duration_seconds": 300},
        dsp_headers), expected_status=201)
    assert line["royalties_cents"] == 1310, (
        f"300s is still the flat tier (10 * 131); got {line['royalties_cents']}")


def test_three_hundred_one_seconds_prices_long_form(api):
    """PRD §2.6: "The five-minute boundary is exact: a duration of exactly 300
    seconds prices at the short rate, while 301 seconds prices at the long-form
    rule."
    PRD §3.3: "When the duration exceeds 300 seconds, the unit price is the
    greater of the short rate and the per-minute rate multiplied by the duration
    in minutes rounded up to the next whole minute."

    Design: Difficulty/boundary_precision_check/long_track_five_minute_boundary
    """
    dsp, dsp_headers, report = _setup_draft_report()
    line = validate_success(api_client.create_usage_line(
        dsp["id"], report["id"],
        {"isrc": "USAA19900022", "track_title": "Ruff",
         "plays_count": 10, "duration_seconds": 301},
        dsp_headers), expected_status=201)
    assert line["royalties_cents"] == 15120, (
        f"301s -> ceil 6 minutes; 10 * max(131, 252*6) == 15120; "
        f"got {line['royalties_cents']}")
