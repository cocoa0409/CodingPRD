"""The DRAFT -> SUBMITTED -> REJECTED -> DRAFT cycle of usage reports."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, ApiErrorId,
    set_clock, create_active_schedule, setup_active_dsp,
    create_report_with_lines, submit_report,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]


def _setup_report_after_one_cycle():
    """Report for 2026-08 (one 13100-cent line) already cycled once:
    SUBMITTED -> REJECTED -> DRAFT."""
    set_clock("2026-09-10T00:00:00Z")
    create_active_schedule()
    dsp, dsp_headers, ack = setup_active_dsp()
    report, _lines = create_report_with_lines(dsp, dsp_headers, "2026-08", [
        {"track_title": "Wigeon", "plays_count": 100, "duration_seconds": 100,
         "isrc": "USAA19900009"},
    ])
    submit_report(dsp, dsp_headers, ack, report)
    validate_success(api_client.reject_usage_report(dsp["id"], report["id"], ADMIN))
    validate_success(api_client.reopen_usage_report(dsp["id"], report["id"], dsp_headers))
    return dsp, dsp_headers, ack, report


def test_report_cycles_back_to_submitted_with_lines_retained(api):
    """PRD §3.3: "Rejection, by contrast, simply moves a `SUBMITTED` report to
    `REJECTED`; the provider may then reopen it, returning it to `DRAFT`, and
    the cycle of draft, submission, rejection, and reopening may repeat without
    bound."

    Design: Difficulty/non_linear_state_machine/usage_report_reject_reopen_cycle
    """
    dsp, dsp_headers, ack, report = _setup_report_after_one_cycle()
    resubmitted = validate_success(
        api_client.submit_usage_report(dsp["id"], report["id"], ack, dsp_headers))
    assert resubmitted["status"] == "SUBMITTED", (
        f"second submit after reopen must reach SUBMITTED; got {resubmitted['status']}")
    assert resubmitted["total_usage_cents"] == 13100, (
        f"the line set is retained across the loop; got {resubmitted['total_usage_cents']}")


def test_reject_from_draft_is_invalid_state(api):
    """PRD §3.3: "Rejection, by contrast, simply moves a `SUBMITTED` report to
    `REJECTED`; the provider may then reopen it, returning it to `DRAFT`, and
    the cycle of draft, submission, rejection, and reopening may repeat without
    bound."

    Design: Difficulty/non_linear_state_machine/usage_report_reject_reopen_cycle
    """
    dsp, _dsp_headers, _ack, report = _setup_report_after_one_cycle()
    # The report is back in DRAFT after the first cycle; reject requires SUBMITTED.
    validate_error(
        api_client.reject_usage_report(dsp["id"], report["id"], ADMIN),
        ApiErrorId.ERR_INVALID_STATE)
