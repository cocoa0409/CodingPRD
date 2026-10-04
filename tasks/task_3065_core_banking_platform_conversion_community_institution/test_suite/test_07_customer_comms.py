"""Customer communication waves: scheduling, send windows, and resend backoff."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_mock_conversion_project,
    create_comm, schedule_comm, set_clock,
)

CO = TEST_USERS["co_headers"]


class TestCommWaveAndBackoff:
    def test_wave_schedule_then_backoff_on_resend(self, api):
        """PRD §3.10: "The send window is derived deterministically from the
        project's creation clock time: `send_after` is the project creation
        time plus (wave − 1) whole days, and `send_before` is exactly three
        days after `send_after` — the window closes three days after it opens."
        PRD §3.10: "Resending a failed comm (`FAILED → SENT`) increments
        `resend_count` and applies wave backoff: the new `scheduled_send_date`
        is `send_after` shifted later by `resend_count` whole days, computed
        with the count after its increment."

        Design: Difficulty/dual_variant_calc/comm_wave_schedule_vs_comm_backoff_variants
        """
        ctx = setup_mock_conversion_project(
            account_overrides={"legacy_account_number": "L-2001",
                               "opening_principal_cents": 500000}
        )
        pid = ctx["project"]["id"]
        acct_id = ctx["account"]["id"]
        comm = create_comm(pid, acct_id, comm_type="ACCOUNT_NUMBER_CHANGE", wave=2)
        assert comm["send_after"] == "2026-09-02T00:00:00.000Z"
        scheduled = schedule_comm(comm["id"], pid)
        assert scheduled["scheduled_send_date"] == "2026-09-02T00:00:00.000Z"
        set_clock("2026-09-02T00:00:00Z")
        get_success_data(api.send_comm(comm["id"], CO))
        get_success_data(api.fail_comm(comm["id"], CO))
        resent = get_success_data(api.resend_comm(comm["id"], CO))
        assert resent["status"] == "SENT"
        assert resent["resend_count"] == 1
        assert resent["scheduled_send_date"] == "2026-09-03T00:00:00.000Z"

    def test_schedule_copies_send_after_and_resend_shifts_it(self, api):
        """PRD §3.10: "A new comm begins in `DRAFT` status with
        `scheduled_send_date` initialized to `send_after` and `resend_count`
        zero."
        PRD §3.10: "Backoff only ever pushes a comm later, never earlier than
        `send_after`, and it may legitimately push `scheduled_send_date` beyond
        `send_before` — the resent comm remains bound by `send_before` on its
        next send attempt, so a sufficiently backed-off comm can become
        unsendable."

        Design: Difficulty/dual_variant_calc/comm_wave_schedule_vs_comm_backoff_variants
        """
        ctx = setup_mock_conversion_project()
        pid = ctx["project"]["id"]
        acct_id = ctx["account"]["id"]
        comm = create_comm(pid, acct_id, wave=1)
        assert comm["status"] == "DRAFT"
        assert comm["resend_count"] == 0
        assert comm["scheduled_send_date"] == comm["send_after"]
        schedule_comm(comm["id"], pid)
        set_clock("2026-09-01T00:00:00Z")
        get_success_data(api.send_comm(comm["id"], CO))
        get_success_data(api.fail_comm(comm["id"], CO))
        first = get_success_data(api.resend_comm(comm["id"], CO))
        get_success_data(api.fail_comm(comm["id"], CO))
        second = get_success_data(api.resend_comm(comm["id"], CO))
        assert first["resend_count"] == 1
        assert second["resend_count"] == 2
        assert second["scheduled_send_date"] > first["scheduled_send_date"]


class TestCommSendWindow:
    def test_send_outside_window_rejected_both_sides(self, api):
        """PRD §3.10: "Sending (`SCHEDULED → SENT`) requires the clock to be at
        or after `scheduled_send_date` and at or before `send_before`; a comm
        whose window has expired cannot be sent and the attempt is rejected
        with `ERR_OUTSIDE_WINDOW`."

        Design: Corner/endpoints/comm_send_before_scheduled_date_and_after_send_before
        """
        ctx = setup_mock_conversion_project(
            account_overrides={"legacy_account_number": "L-1",
                               "opening_principal_cents": 1000}
        )
        pid = ctx["project"]["id"]
        acct_id = ctx["account"]["id"]
        comm = create_comm(pid, acct_id, wave=1)
        schedule_comm(comm["id"], pid)
        set_clock("2026-08-31T23:00:00Z")
        resp_early = api.send_comm(comm["id"], CO)
        validate_error(resp_early, ApiErrorId.ERR_OUTSIDE_WINDOW)
        set_clock("2026-09-04T00:00:01Z")
        resp_late = api.send_comm(comm["id"], CO)
        validate_error(resp_late, ApiErrorId.ERR_OUTSIDE_WINDOW)
        set_clock("2026-09-02T12:00:00Z")
        sent = get_success_data(api.send_comm(comm["id"], CO))
        assert sent["status"] == "SENT"
