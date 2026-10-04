"""Cross-entity state dependency: report submission gated on the DSP posture."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, ApiErrorId,
    set_clock, create_active_schedule, setup_active_dsp,
    create_report_with_lines, submit_report,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]


def _setup_suspended_dsp_with_draft_report():
    """DSP with one SUBMITTED report (2026-07, making it suspendable) and one
    DRAFT report (2026-08, with one line); DSP then SUSPENDED."""
    set_clock("2026-09-10T00:00:00Z")
    create_active_schedule()
    dsp, dsp_headers, ack = setup_active_dsp()
    r1, _ = create_report_with_lines(dsp, dsp_headers, "2026-07", [
        {"track_title": "Sora", "plays_count": 10, "duration_seconds": 100,
         "isrc": "USAA19900041"},
    ])
    submit_report(dsp, dsp_headers, ack, r1)
    r2, _ = create_report_with_lines(dsp, dsp_headers, "2026-08", [
        {"track_title": "Ruff", "plays_count": 10, "duration_seconds": 100,
         "isrc": "USAA19900042"},
    ])
    validate_success(api_client.suspend_service_provider(dsp["id"], ADMIN))
    return dsp, dsp_headers, ack, r2


def test_submit_under_suspended_dsp_rejected(api):
    """PRD §3.1: "A `SUSPENDED` provider cannot file or submit new usage
    reports — the attempt is rejected with `ERR_DSP_NOT_ACTIVE` — until an
    administrator reinstates it, which returns `participation_status` to
    `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/report_submit_requires_dsp_active
    """
    dsp, dsp_headers, ack, r2 = _setup_suspended_dsp_with_draft_report()
    validate_error(
        api_client.submit_usage_report(dsp["id"], r2["id"], ack, dsp_headers),
        ApiErrorId.ERR_DSP_NOT_ACTIVE)


def test_failed_submit_leaves_report_and_dsp_unchanged(api):
    """PRD §3.1: "A `SUSPENDED` provider cannot file or submit new usage
    reports — the attempt is rejected with `ERR_DSP_NOT_ACTIVE` — until an
    administrator reinstates it, which returns `participation_status` to
    `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/report_submit_requires_dsp_active
    """
    dsp, dsp_headers, ack, r2 = _setup_suspended_dsp_with_draft_report()
    validate_error(
        api_client.submit_usage_report(dsp["id"], r2["id"], ack, dsp_headers),
        ApiErrorId.ERR_DSP_NOT_ACTIVE)
    report_after = validate_success(
        api_client.get_usage_report(dsp["id"], r2["id"], ADMIN))
    assert report_after["status"] == "DRAFT", (
        f"the failed submit leaves the report DRAFT; got {report_after['status']}")
    dsp_after = validate_success(api_client.get_service_provider(dsp["id"], ADMIN))
    assert dsp_after["participation_status"] == "SUSPENDED"
