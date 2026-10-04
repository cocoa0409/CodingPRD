"""Cyclic and forking state machines: estimates that come back, appointments that fork."""
from test_helpers import (
    TEST_USERS,
    dispatch_mobile_visit,
    get_order,
    get_success_data,
    set_clock,
    setup_triaged_mobile_appointment,
    walk_order_to_at_delivery_center,
)

ADMIN = TEST_USERS["platform_admin_headers"]
TECH = TEST_USERS["service_technician_headers"]


class TestDeliveryEstimateRestoreLoop:
    """PRD §3.4: a superseded estimate can be restored, and the accumulator unwinds."""

    def test_superseded_estimate_restores_to_firm(self, api):
        """PRD §3.4: "A superseded estimate may be restored as the live window,
        provided its `window_start` is still at or after the current clock instant"
        PRD §3.4: "Restoration moves the estimate to `FIRM`, supersedes every other
        `PROVISIONAL` or `FIRM` estimate on the order, and *decreases*
        `estimate_shift_days_cumulative` by the restored estimate's `shift_days`,
        undoing the accrual that its supersession had added."

        Design: Difficulty/non_linear_state_machine/delivery_estimate_cyclic_restore_loop
        """
        set_clock()
        ctx = walk_order_to_at_delivery_center()
        estimates = get_success_data(
            api.list_order_estimates(ctx["order"]["id"], ADMIN))
        first = [e for e in estimates if e["prior_estimate_id"] is None][0]

        # Supersede the live window with a deliberately fresh one.
        get_success_data(api.project_delivery_estimate(
            ctx["order"]["id"],
            {"basis_iso8601": "2026-09-21T00:00:00Z", "window_days": 7}, ADMIN))

        before = get_success_data(api.get_delivery_estimate(first["id"], ADMIN))
        assert before["estimate_state"] == "SUPERSEDED"

        restored = get_success_data(api.restore_delivery_estimate(first["id"], ADMIN))
        assert restored["estimate_state"] == "FIRM", (
            "restoration moves the estimate back out of SUPERSEDED into FIRM"
        )

    def test_unwinding_decreases_the_shift_accumulator(self, api):
        """PRD §3.4: "This asymmetry is deliberate: a transition *into*
        `SUPERSEDED` accrues the shift, and a restoration *out of* `SUPERSEDED`
        back to `FIRM` removes it."
        PRD §3.4: "Restoration moves the estimate to `FIRM`, supersedes every other
        `PROVISIONAL` or `FIRM` estimate on the order, and *decreases*
        `estimate_shift_days_cumulative` by the restored estimate's `shift_days`"

        Design: Difficulty/non_linear_state_machine/delivery_estimate_cyclic_restore_loop
        """
        set_clock()
        ctx = walk_order_to_at_delivery_center()
        estimates = get_success_data(
            api.list_order_estimates(ctx["order"]["id"], ADMIN))
        first = [e for e in estimates if e["prior_estimate_id"] is None][0]

        # Supersede the live window with a deliberately fresh one, a full day
        # past the prior window's start.
        get_success_data(api.project_delivery_estimate(
            ctx["order"]["id"],
            {"basis_iso8601": "2026-09-24T00:00:00Z", "window_days": 7}, ADMIN))
        order_before = get_order(ctx["order"]["id"])
        accrued = order_before["estimate_shift_days_cumulative"]

        get_success_data(api.restore_delivery_estimate(first["id"], ADMIN))
        order_after = get_order(ctx["order"]["id"])
        assert (order_after["estimate_shift_days_cumulative"]
                == order_before["estimate_shift_days_cumulative"]
                - first["shift_days"]), (
            "the restore removes exactly the shift the restored row carries"
        )
        # The restored original row's window was consumed by the booking, so its
        # own shift is 0 and there is nothing left for the restore to remove.
        assert first["shift_days"] == 0
        assert order_after["estimate_shift_days_cumulative"] == accrued


class TestServiceAppointmentForkJoin:
    """PRD §3.9: an appointment forks at TRIAGED and the two channels reconverge."""

    def test_critical_report_takes_the_center_branch(self, api):
        """PRD §3.9: "Scheduling into a center bay requires the appointment to be
        `TRIAGED` — otherwise `ERR_INVALID_STATE` (HTTP 409) — requires the
        referenced report's `triage_outcome` to be `CENTER_REQUIRED`"
        PRD §3.9: "the outcome is `CENTER_REQUIRED` when the severity is `HIGH` or
        `CRITICAL`, or when `is_driveable` is false, either condition alone being
        sufficient"
        PRD §3.9: "On success the appointment becomes `CENTER_SCHEDULED`"

        Design: Difficulty/non_linear_state_machine/mobile_visit_branching_fork_join_two_channels
        """
        set_clock()
        ctx = setup_triaged_mobile_appointment(
            fault_code="DRV-9001", severity="CRITICAL", is_driveable=False)
        appointment = ctx["appointment"]

        scheduled = get_success_data(api.schedule_service_center(
            appointment["id"],
            {"scheduled_start": "2026-09-25T14:00:00Z",
             "scheduled_end": "2026-09-25T16:00:00Z"},
            TECH))
        assert scheduled["status"] == "CENTER_SCHEDULED"
        assert ctx["report"]["triage_outcome"] == "CENTER_REQUIRED"

    def test_cancelling_the_mobile_branch_returns_the_appointment_to_triage(self, api):
        """PRD §3.9: "A `MOBILE_DISPATCHED` appointment whose visit is cancelled
        returns to `TRIAGED` so that the other channel can be chosen"
        PRD §3.10: "Cancellation is available while the visit is not already
        terminal — otherwise `ERR_ALREADY_TERMINAL` (HTTP 409) — and it returns the
        linked appointment to `TRIAGED` and clears the vehicle's hold to `NONE`."

        Design: Difficulty/non_linear_state_machine/mobile_visit_branching_fork_join_two_channels
        """
        set_clock()
        ctx = setup_triaged_mobile_appointment(
            fault_code="BMS-1103", severity="MEDIUM", is_driveable=True)
        appointment = ctx["appointment"]

        visit = dispatch_mobile_visit(appointment["id"], ctx["hub"]["id"],
                                      appointment["version"], labor_hours=1.5,
                                      parts_cost_cents=0, visit_miles=12)
        dispatched = get_success_data(
            api.get_service_appointment(appointment["id"], TECH))
        assert dispatched["status"] == "MOBILE_DISPATCHED"

        get_success_data(api.cancel_mobile_visit(visit["id"], TECH))
        returned = get_success_data(
            api.get_service_appointment(appointment["id"], TECH))
        assert returned["status"] == "TRIAGED", (
            "cancelling the mobile branch returns the appointment to the fork point"
        )
        vehicle = get_success_data(api.get_vehicle(ctx["vehicle"]["id"], TECH))
        assert vehicle["service_hold_state"] == "NONE"
