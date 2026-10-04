"""Depth-3 cascade from report acceptance: line -> accrual -> hold expiry."""
from test_helpers import (
    TEST_USERS, validate_success,
    set_clock, create_active_schedule, setup_active_dsp,
    create_report_with_lines, submit_report, get_line_accrual,
    hold_expiry_for_month, pad_report_for_match_floor,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]


def _setup_submitted_unmatchable_report():
    set_clock("2026-09-01T00:00:00Z")
    create_active_schedule()
    dsp, dsp_headers, ack = setup_active_dsp()
    report, lines = create_report_with_lines(dsp, dsp_headers, "2026-06", [
        {"track_title": "Petrel", "plays_count": 1000, "duration_seconds": 100,
         "isrc": "USAA19900003"},
    ])
    # Pad with a matched line so acceptance's circuit breaker passes with the
    # 131000-cent Petrel line unmatched (PRD §3.3: unmatched <= 60% of total).
    pad_report_for_match_floor(dsp, dsp_headers, report,
                               lines[0]["royalties_cents"])
    submit_report(dsp, dsp_headers, ack, report)
    return dsp, ack, report, lines[0]


def test_acceptance_cascades_line_to_unmatched_and_spawns_held_accrual(api):
    """PRD §3.5: "Every accrual is born from an unmatched line: when a line
    becomes `UNMATCHED`, the server creates a `RoyaltyAccrual` in `HELD` status
    whose `amount_cents` is an immutable snapshot of the line's
    `royalties_cents` at that moment, whose `usage_line_id` and
    `service_provider_id` record provenance, whose `reporting_month` is copied
    from the report for pool-window selection, and whose `hold_expires_at` marks
    the end of the claiming period — 36 months after the first day of the month
    following the report's reporting month."

    Design: Difficulty/transitive_cascade/acceptance_match_sweep_accrual_cascade
    """
    dsp, ack, report, line = _setup_submitted_unmatchable_report()
    accepted = validate_success(
        api_client.accept_usage_report(dsp["id"], report["id"], ack, ADMIN))
    assert accepted["status"] == "ACCEPTED"
    line_after = validate_success(api_client.get_usage_line(line["id"], ADMIN))
    assert line_after["status"] == "UNMATCHED", (
        f"the acceptance sweep moves the unmatchable line to UNMATCHED; "
        f"got {line_after['status']}")
    accrual = get_line_accrual(line["id"])
    assert accrual["status"] == "HELD"
    assert accrual["amount_cents"] == 131000, (
        f"accrual snapshots the line's royalties_cents; got {accrual['amount_cents']}")
    assert accrual["reporting_month"] == "2026-06"


def test_accrual_hold_expiry_derived_from_reporting_month(api):
    """PRD §3.5: "whose `hold_expires_at` marks the end of the claiming period —
    36 months after the first day of the month following the report's reporting
    month."

    Design: Difficulty/transitive_cascade/acceptance_match_sweep_accrual_cascade
    """
    from datetime import datetime, timezone
    dsp, ack, report, line = _setup_submitted_unmatchable_report()
    validate_success(api_client.accept_usage_report(dsp["id"], report["id"], ack, ADMIN))
    accrual = get_line_accrual(line["id"])
    # Compare as instants: PRD §3.5 pins the derived instant; the exact string
    # rendering follows the §2.4 three-fractional-digit timestamp convention.
    got = datetime.fromisoformat(
        accrual["hold_expires_at"].replace("Z", "+00:00"))
    want = datetime(2029, 7, 1, tzinfo=timezone.utc)
    assert got == want, (
        f"2026-06 + 1 month -> 2026-07-01, + 36 months -> 2029-07-01; "
        f"got {accrual['hold_expires_at']}")
    expected = datetime.fromisoformat(
        hold_expiry_for_month("2026-06").replace("Z", "+00:00"))
    assert got == expected
