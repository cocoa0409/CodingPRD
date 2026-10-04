"""Schedule-window pricing variants for usage lines (dual-variant calculation)."""
from test_helpers import (
    TEST_USERS, make_dsp_headers, validate_success,
    set_clock, create_schedule_pending, activate_dsp, create_dsp,
    create_report_with_lines,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]


def _setup_two_schedules_and_dsp():
    """OLD (120/240) over [2026-01-01, 2026-07-01) superseded by NEW (131/252)
    over [2026-07-01, null); DSP activated under OLD then re-bumped by NEW."""
    set_clock("2026-09-10T00:00:00Z")
    rs_old = create_schedule_pending(
        under=120, over=240,
        effective_from="2026-01-01T00:00:00Z", effective_to="2026-07-01T00:00:00Z")
    rs_new = create_schedule_pending(
        under=131, over=252, effective_from="2026-07-01T00:00:00Z")
    api_client.activate_rate_schedule(rs_old["id"], ADMIN)
    dsp = create_dsp()
    dsp, dsp_headers, _ack = activate_dsp(dsp)
    api_client.activate_rate_schedule(rs_new["id"], ADMIN)
    dsp = validate_success(api_client.get_service_provider(dsp["id"], ADMIN))
    return dsp, dsp_headers, dsp["accepted_rate_schedule_version"]


def test_superseded_window_prices_at_its_own_schedule(api):
    """PRD §3.3: "the schedule whose half-open effectiveness window contains the
    first day of the report's reporting month is selected — the schedule ACTIVE
    at acceptance is authoritative, but a SUPERSEDED schedule still prices its
    own window, so a back-dated report prices under the schedule that governed
    its month."

    Design: Difficulty/dual_variant_calc/usage_line_royalty_schedule_window_variants
    """
    dsp, dsp_headers, _ack = _setup_two_schedules_and_dsp()
    report, _ = create_report_with_lines(dsp, dsp_headers, "2026-06", [])
    line = validate_success(api_client.create_usage_line(
        dsp["id"], report["id"],
        {"isrc": "USAA19900001", "track_title": "Kestrel",
         "plays_count": 1000, "duration_seconds": 200},
        dsp_headers), expected_status=201)
    assert line["royalties_cents"] == 120000, (
        f"2026-06 falls in the SUPERSEDED 120-cent window; expected 120000, "
        f"got {line['royalties_cents']}")


def test_active_window_prices_at_current_schedule(api):
    """PRD §3.3: "the schedule whose half-open effectiveness window contains the
    first day of the report's reporting month is selected — the schedule ACTIVE
    at acceptance is authoritative, but a SUPERSEDED schedule still prices its
    own window, so a back-dated report prices under the schedule that governed
    its month."

    Design: Difficulty/dual_variant_calc/usage_line_royalty_schedule_window_variants
    """
    dsp, dsp_headers, _ack = _setup_two_schedules_and_dsp()
    report, _ = create_report_with_lines(dsp, dsp_headers, "2026-08", [])
    line = validate_success(api_client.create_usage_line(
        dsp["id"], report["id"],
        {"isrc": "USAA19900001", "track_title": "Kestrel",
         "plays_count": 1000, "duration_seconds": 200},
        dsp_headers), expected_status=201)
    assert line["royalties_cents"] == 131000, (
        f"2026-08 falls in the ACTIVE 131-cent window; expected 131000, "
        f"got {line['royalties_cents']}")
