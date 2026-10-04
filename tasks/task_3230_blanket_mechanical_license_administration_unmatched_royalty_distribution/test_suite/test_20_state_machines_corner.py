"""Queue B (corner) — usage-report state machine and cascades."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, ApiErrorId,
    set_clock, create_active_schedule, setup_active_dsp,
    create_report_with_lines, submit_report,
    create_member, create_work, create_share,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]


def _setup_active_dsp_with_report(month="2026-08", lines=None):
    set_clock("2026-09-10T00:00:00Z")
    create_active_schedule()
    dsp, dsp_headers, ack = setup_active_dsp()
    report, created = create_report_with_lines(
        dsp, dsp_headers, month, lines or [])
    return dsp, dsp_headers, ack, report, created


def test_accept_draft_report_returns_invalid_state(api):
    """PRD §3.3: "The report must be `SUBMITTED` (`ERR_INVALID_STATE`); the
    payload's `accepted_rate_schedule_version` must still equal the provider's
    current value (`ERR_STALE_RATE_SCHEDULE`); and no other report of the same
    provider with an earlier `reporting_month` may still be `SUBMITTED` —
    acceptance is strictly in chronological order, and an out-of-order attempt
    is rejected with `ERR_OUT_OF_ORDER_ACCEPTANCE` (HTTP 409)."

    Design: Corner/state_machines/accept_rejected_report_returns_invalid_state
    """
    dsp, _h, ack, report, _l = _setup_active_dsp_with_report()
    validate_error(
        api_client.accept_usage_report(dsp["id"], report["id"], ack, ADMIN),
        ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api_client.get_usage_report(dsp["id"], report["id"], ADMIN))
    assert after["status"] == "DRAFT"


def test_submit_empty_report_returns_empty_report(api):
    """PRD §3.3: "Submission — performed by the provider's own user — requires
    the report to be `DRAFT` (`ERR_INVALID_STATE` otherwise), the owning
    provider to be `ACTIVE`, at least one line on the report
    (`ERR_EMPTY_REPORT`, HTTP 422), the reporting month fully elapsed, and the
    payload's `accepted_rate_schedule_version` equal to the provider's current
    value (`ERR_STALE_RATE_SCHEDULE`)."

    Design: Corner/state_machines/submit_empty_report_returns_empty_report
    """
    dsp, dsp_headers, ack, report, _l = _setup_active_dsp_with_report()
    validate_error(
        api_client.submit_usage_report(dsp["id"], report["id"], ack, dsp_headers),
        ApiErrorId.ERR_EMPTY_REPORT)


def test_submit_current_month_returns_future_period(api):
    """PRD §2.5: "A reporting month is **fully elapsed** only when the end of
    that month is strictly before the current logical time; a report for the
    month containing the current instant is premature and is rejected with
    `ERR_FUTURE_PERIOD` (HTTP 422) both at creation and at submission."

    Design: Corner/state_machines/submit_future_period_returns_future_period
    """
    # Create the report while its month is fully elapsed (creation-time check
    # passes), then move the logical clock back into the report's month so the
    # submission-time check fires.
    dsp, dsp_headers, ack, report, _l = _setup_active_dsp_with_report(
        month="2026-08",
        lines=[{"track_title": "Sora", "plays_count": 10,
                "duration_seconds": 100, "isrc": "USAA19900051"}],
    )
    set_clock("2026-08-15T00:00:00Z")
    validate_error(
        api_client.submit_usage_report(dsp["id"], report["id"], ack, dsp_headers),
        ApiErrorId.ERR_FUTURE_PERIOD)


def test_double_submit_returns_invalid_state(api):
    """PRD §3.3: "Submission — performed by the provider's own user — requires
    the report to be `DRAFT` (`ERR_INVALID_STATE` otherwise), the owning
    provider to be `ACTIVE`, at least one line on the report
    (`ERR_EMPTY_REPORT`, HTTP 422), the reporting month fully elapsed, and the
    payload's `accepted_rate_schedule_version` equal to the provider's current
    value (`ERR_STALE_RATE_SCHEDULE`)."

    Design: Corner/state_machines/double_submit_returns_invalid_state_idempotency
    """
    dsp, dsp_headers, ack, report, _l = _setup_active_dsp_with_report(
        lines=[{"track_title": "Sora", "plays_count": 10,
                "duration_seconds": 100, "isrc": "USAA19900051"}],
    )
    submit_report(dsp, dsp_headers, ack, report)
    validate_error(
        api_client.submit_usage_report(dsp["id"], report["id"], ack, dsp_headers),
        ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api_client.get_usage_report(dsp["id"], report["id"], ADMIN))
    assert after["total_usage_cents"] == 1310, (
        f"no double recompute side effect; got {after['total_usage_cents']}")


def test_work_withdraw_cascades_shares(api):
    """PRD §3.2: "Withdrawal cascades: every share of the work in `ACTIVE` or
    `DISPUTED` status moves to `WITHDRAWN`, and every `OPEN` dispute on the
    work is force-closed as `ESCALATED` with `resolution_note` set to
    `WORK_WITHDRAWN`."
    PRD §3.2: "When a work is withdrawn, `withdrawn_at` is stamped; until then
    it is null."

    Design: Corner/state_machines/work_withdraw_cascades_shares
    """
    set_clock("2026-09-01T00:00:00Z")
    m_a = create_member(legal_name="Alder Publishing", ipi_number="00000000101")
    m_b = create_member(legal_name="Birch Songs", ipi_number="00000000202")
    work = create_work(title="Kestrel")
    s1 = create_share(work["id"], m_a["id"], share_percent=60)
    s2 = create_share(work["id"], m_b["id"], share_percent=40)
    withdrawn = validate_success(api_client.withdraw_work(work["id"], ADMIN))
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn.get("withdrawn_at"), "withdrawn_at must be stamped"
    for sid in (s1["id"], s2["id"]):
        share = validate_success(api_client.get_share(work["id"], sid, ADMIN))
        assert share["status"] == "WITHDRAWN", (
            f"share {sid} must cascade to WITHDRAWN; got {share['status']}")
    assert withdrawn["total_share_percent"] == 0


def test_rate_schedule_activation_bubbles_to_dsps(api):
    """PRD §3.1: "Activation supersedes: the previously `ACTIVE` schedule moves
    to `SUPERSEDED`, at most one schedule is ever `ACTIVE`, and every provider
    in `ACTIVE` or `SUSPENDED` status has its `accepted_rate_schedule_version`
    bumped to the newly activated schedule's `version`."

    Design: Corner/state_machines/rate_schedule_activation_bubbles_to_dsps
    """
    from test_helpers import create_schedule_pending, activate_dsp, create_dsp
    set_clock("2026-09-01T00:00:00Z")
    rs1 = create_schedule_pending(
        under=120, over=240,
        effective_from="2026-01-01T00:00:00Z", effective_to="2026-06-01T00:00:00Z")
    rs2 = create_schedule_pending(
        effective_from="2026-06-01T00:00:00Z")
    validate_success(api_client.activate_rate_schedule(rs1["id"], ADMIN))
    dsp, _h, _ack = activate_dsp(create_dsp())
    validate_success(api_client.activate_rate_schedule(rs2["id"], ADMIN))
    rs1_after = validate_success(api_client.get_rate_schedule(rs1["id"], ADMIN))
    rs2_after = validate_success(api_client.get_rate_schedule(rs2["id"], ADMIN))
    assert rs1_after["status"] == "SUPERSEDED"
    assert rs2_after["status"] == "ACTIVE"
    dsp_after = validate_success(api_client.get_service_provider(dsp["id"], ADMIN))
    assert dsp_after["accepted_rate_schedule_version"] == rs2_after["version"]


def test_terminated_dsp_rejects_reinstate(api):
    """PRD §3.1: "Termination, reachable from either `ACTIVE` or `SUSPENDED`,
    is guarded on two fronts: the provider must have no report in `SUBMITTED`
    or `UNDER_AUDIT` (`ERR_DSP_HAS_OPEN_REPORTS` when one exists) and no audit
    engagement in `OPEN` or `FINDINGS_ISSUED` (`ERR_AUDIT_IN_PROGRESS` when one
    exists). Termination does not disturb the historical record: every accrual
    the provider funded that is still `HELD` remains `HELD`, and its pool
    eligibility is unchanged."

    Design: Corner/state_machines/terminal_state_lockdown_terminated_dsp
    """
    from test_helpers import create_dsp, activate_dsp
    dsp, _h, _ack = activate_dsp(create_dsp())
    validate_success(api_client.terminate_service_provider(dsp["id"], ADMIN))
    validate_error(api_client.reinstate_service_provider(dsp["id"], ADMIN),
                   ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api_client.get_service_provider(dsp["id"], ADMIN))
    assert after["participation_status"] == "TERMINATED"
