"""Depth tests for boundary precision.

Instance: the branch-capacity boundary at booking.
"""
from prd_bench_local_runner.testing import validate_success

from test_helpers import TEST_USERS, api_client, fixtures as F

DISPATCHER = TEST_USERS["dispatcher_headers"]


def _branch_with_capacity_budget():
    """A branch declaring 8.0 hours, two technicians and one 4.0-hour task.

    The first 4.0-hour job is dispatched (which takes its technician off the candidate
    pool), and a second 4.0-hour job is booked but left undispatched. The branch rollup
    therefore sits exactly on its declared capacity.
    """
    branch = F.create_branch(daily_dispatch_capacity_hours=8)
    holder = F.hire_technician(branch["id"], name="Dana", daily_capacity_hours=8)
    F.hire_technician(branch["id"], name="Eli", postal_code="78702", daily_capacity_hours=8)
    F.create_task(code="HVAC-COIL", estimated_hours=4.0, flat_rate_cents=15000)

    dispatched = F.book_appointment(
        branch["id"],
        window_start_utc="2026-09-11T09:00:00Z",
        window_end_utc="2026-09-11T11:00:00Z",
    )
    F.add_line(dispatched["id"], code="HVAC-COIL", status="SOLD")
    dispatched = F.dispatch(dispatched["id"])

    queued = F.book_appointment(
        branch["id"],
        window_start_utc="2026-09-12T09:00:00Z",
        window_end_utc="2026-09-12T11:00:00Z",
    )
    F.add_line(queued["id"], code="HVAC-COIL")
    return branch, holder, dispatched, queued


def test_a_branch_sitting_exactly_on_its_capacity_still_accepts_a_booking(api):
    """PRD §2.6: "`Branch.capacity_consumed_hours` is the sum of the `estimated_hours` of
    that branch's appointments whose `status` is `SCHEDULED` or `DISPATCHED`."
    PRD §2.6: "The identity that must hold is this: committing hours adds to the rollups and
    releasing them returns the rollups to precisely their pre-commitment value."

    A dispatched 4.0-hour job plus a booked 4.0-hour job bring the rollup to exactly the
    declared 8.0, and a further booking is still admitted.

    Design: Difficulty/boundary_precision_check/branch_capacity_exact_threshold_at_booking
    """
    branch, holder, dispatched, queued = _branch_with_capacity_budget()

    at_capacity = F.get_branch(branch["id"])
    assert at_capacity["capacity_consumed_hours"] == 8.0, (
        "a dispatched 4.0-hour job and a booked 4.0-hour job consume 8.0 hours, "
        f"got {at_capacity['capacity_consumed_hours']}"
    )
    assert F.get_technician(holder["id"])["dispatched_hours"] == 4.0

    third = F.book_appointment(
        branch["id"],
        window_start_utc="2026-09-13T09:00:00Z",
        window_end_utc="2026-09-13T11:00:00Z",
    )
    assert third["status"] == "SCHEDULED", (
        "the (capacity == consumed) case is admitted rather than refused"
    )
    assert F.get_branch(branch["id"])["capacity_consumed_hours"] == 8.0, (
        "a booking carrying no line contributes 0 hours, so the rollup is unchanged"
    )


def test_cancelling_a_dispatched_job_comes_off_the_capacity_rollup(api):
    """PRD §3.10: "The technician's `status` returns to `AVAILABLE` and their
    `dispatched_hours` falls by the appointment's `estimated_hours`; the branch's
    `capacity_consumed_hours` falls by the same amount."
    PRD §3.3: "appointments that are `COMPLETED` or `CANCELLED` no longer occupy the
    branch's calendar, so a slot they vacated is free again."

    Design: Difficulty/boundary_precision_check/branch_capacity_exact_threshold_at_booking
    """
    branch, holder, dispatched, queued = _branch_with_capacity_budget()

    cancelled = validate_success(
        api_client.cancel_appointment(
            dispatched["id"], {"reason": "no longer needed"}, DISPATCHER
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["technician_id"] is None

    remaining = F.get_branch(branch["id"])
    assert remaining["capacity_consumed_hours"] == 4.0, (
        "the cancelled job's hours come off the rollup, leaving the queued job's 4.0, "
        f"got {remaining['capacity_consumed_hours']}"
    )

    released = F.get_technician(holder["id"])
    assert released["dispatched_hours"] == 0, (
        f"the released technician carries no dispatched hours, got {released['dispatched_hours']}"
    )