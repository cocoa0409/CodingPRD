"""Depth tests for the compensating invariants.

Two instances: the technician revenue ledger conserved across completion and
cancellation, and booked hours conserved across dispatch and release.
"""
from test_helpers import TEST_USERS, api_client, fixtures as F, validate_success

DISPATCHER = TEST_USERS["dispatcher_headers"]
MANAGER = TEST_USERS["manager_headers"]


# =====================================================================
# ledger_cents_conserved_across_completion_and_cancellation
# =====================================================================
def test_cancelling_a_completed_appointment_restores_the_ledger_total(api):
    """PRD §3.10: "Where the guard passes, the cancellation sets the appointment's `status`
    to `CANCELLED` and appends a compensating `RevenueLedgerEntry`: its `entry_type` is
    `REVERSAL`, its `amount_cents` is the negated appointment `sold_price_cents`".
    PRD §3.10: "Its core identity is that after an accrual and its paired reversal, the
    technician's revenue ledger total equals its value immediately before the accrual was
    appended."

    Design: Difficulty/compensating_invariant/ledger_cents_conserved_across_completion_and_cancellation
    """
    branch, technician, task, appointment = F.setup_dispatched_appointment(
        code="HVAC-COIL", price_cents=60000, hours=1.0,
        window_start="2026-09-10T09:00:00Z", window_end="2026-09-10T11:00:00Z",
    )
    before = F.get_technician(technician["id"])
    assert before["technician_revenue_ledger_cents"] == 0

    completed = F.dispatch_two_calls(appointment["id"])
    accrued = F.get_technician(technician["id"])
    assert accrued["technician_revenue_ledger_cents"] == 60000, (
        f"the accrual adds the sold price, got {accrued['technician_revenue_ledger_cents']}"
    )

    # A manager, not the earning technician, voids the settled revenue.
    cancelled = validate_success(
        api_client.cancel_appointment(
            completed["id"], {"reason": "customer dispute"}, MANAGER
        )
    )
    assert cancelled["status"] == "CANCELLED"

    after = F.get_technician(technician["id"])
    assert after["technician_revenue_ledger_cents"] == 0, (
        "the reversal returns the ledger to its pre-completion value, "
        f"got {after['technician_revenue_ledger_cents']}"
    )


def test_the_ledger_holds_a_matched_accrual_and_reversal_pair(api):
    """PRD §3.10: "The `technician_revenue_ledger_total` calculation defines the total as
    the sum of the technician's entries with accruals positive and reversals negative."
    PRD §2.9: "A revenue ledger entry's `entry_type` is either `ACCRUAL` or `REVERSAL`."

    Design: Difficulty/compensating_invariant/ledger_cents_conserved_across_completion_and_cancellation
    """
    branch, technician, task, appointment = F.setup_dispatched_appointment(
        code="HVAC-COIL", price_cents=60000, hours=1.0,
        window_start="2026-09-10T09:00:00Z", window_end="2026-09-10T11:00:00Z",
    )
    completed = F.dispatch_two_calls(appointment["id"])
    validate_success(
        api_client.cancel_appointment(completed["id"], {"reason": "customer dispute"}, MANAGER)
    )

    technician_row = F.get_technician(technician["id"])
    assert technician_row["technician_revenue_ledger_cents"] == 0, (
        "an accrual of 60000 and its reversal of -60000 net to zero"
    )
    assert technician_row["revenue_window_cents"] == 0, (
        "the rolling window sums the same signed entries, so it nets to zero too"
    )


# =====================================================================
# booked_hours_conserved_across_dispatch_and_release
# =====================================================================
def test_booked_hours_return_to_their_pre_dispatch_value_after_cancellation(api):
    """PRD §2.6: "after a dispatch and its paired completion or cancellation the branch's
    consumed hours and the technician's dispatched hours equal what they were immediately
    before the dispatch."
    PRD §3.10: "The technician's `status` returns to `AVAILABLE` and their
    `dispatched_hours` falls by the appointment's `estimated_hours`; the branch's
    `capacity_consumed_hours` falls by the same amount."

    Design: Difficulty/compensating_invariant/booked_hours_conserved_across_dispatch_and_release
    """
    branch = F.create_branch(daily_dispatch_capacity_hours=8)
    technician = F.hire_technician(
        branch["id"], daily_capacity_hours=8,
        shift_segments=[{"start_utc": "2026-09-01T00:00:00Z", "end_utc": "2026-09-30T18:00:00Z"}],
    )
    F.create_task(code="HVAC-COIL", estimated_hours=4.0, flat_rate_cents=60000)

    first = F.book_appointment(
        branch["id"],
        window_start_utc="2026-09-11T09:00:00Z",
        window_end_utc="2026-09-11T11:00:00Z",
    )
    F.add_line(first["id"], code="HVAC-COIL", status="SOLD")
    F.dispatch(first["id"])

    second = F.book_appointment(
        branch["id"],
        window_start_utc="2026-09-12T09:00:00Z",
        window_end_utc="2026-09-12T11:00:00Z",
    )
    F.add_line(second["id"], code="HVAC-COIL", status="SOLD")

    mid = F.get_technician(technician["id"])
    assert mid["dispatched_hours"] == 4.0, f"got {mid['dispatched_hours']}"
    assert F.get_branch(branch["id"])["capacity_consumed_hours"] == 8.0

    F.dispatch(second["id"])
    paired = F.get_technician(technician["id"])
    assert paired["dispatched_hours"] == 8.0, f"got {paired['dispatched_hours']}"
    assert F.get_branch(branch["id"])["capacity_consumed_hours"] == 8.0

    cancelled = validate_success(
        api_client.cancel_appointment(
            second["id"], {"reason": "no longer needed"}, DISPATCHER
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["technician_id"] is None, (
        "a cancelled dispatched appointment releases its technician"
    )

    released = F.get_technician(technician["id"])
    assert released["dispatched_hours"] == 4.0, (
        f"the paired cancellation returns the hours to 4.0, got {released['dispatched_hours']}"
    )
    assert F.get_branch(branch["id"])["capacity_consumed_hours"] == 4.0, (
        "the branch rollup returns to its pre-dispatch value too"
    )


def test_scheduled_hours_track_booked_but_undispatched_appointments(api):
    """PRD §2.6: "`Technician.scheduled_hours` is the sum of `estimated_hours` over that
    technician's appointments whose `status` is `SCHEDULED`, and
    `Technician.dispatched_hours` is the sum of `estimated_hours` over that technician's
    appointments whose `dispatch_status` is `DISPATCHED`."
    PRD §2.6: "an appointment that is dispatched inflates `dispatched_hours` while an
    appointment merely booked inflates `scheduled_hours`".

    Design: Difficulty/compensating_invariant/booked_hours_conserved_across_dispatch_and_release
    """
    branch = F.create_branch(daily_dispatch_capacity_hours=8)
    technician = F.hire_technician(branch["id"], daily_capacity_hours=8)
    F.create_task(code="HVAC-COIL", estimated_hours=4.0, flat_rate_cents=60000)

    first = F.book_appointment(
        branch["id"],
        window_start_utc="2026-09-11T09:00:00Z",
        window_end_utc="2026-09-11T11:00:00Z",
    )
    F.add_line(first["id"], code="HVAC-COIL")
    F.dispatch(first["id"])

    # A second 4.0-hour appointment is booked but left undispatched: it carries two lines
    # so its hour commitment is real, and it inflates the branch rollup rather than the
    # technician's dispatched hours.
    second = F.book_appointment(
        branch["id"],
        window_start_utc="2026-09-12T09:00:00Z",
        window_end_utc="2026-09-12T11:00:00Z",
    )
    F.add_line(second["id"], code="HVAC-COIL")

    technician_row = F.get_technician(technician["id"])
    assert technician_row["dispatched_hours"] == 4.0, (
        f"only the dispatched job counts here, got {technician_row['dispatched_hours']}"
    )
    assert F.get_branch(branch["id"])["capacity_consumed_hours"] == 8.0, (
        "the branch rollup counts both the dispatched and the merely-booked appointment, "
        f"got {F.get_branch(branch['id'])['capacity_consumed_hours']}"
    )