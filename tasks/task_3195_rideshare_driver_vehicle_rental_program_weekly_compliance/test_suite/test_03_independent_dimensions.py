"""Lifecycles that do not read as a single linear path: the independent payment
dimension that rides on the same week row, and the service event whose completion
branch depends on where the driver's cover came from.
"""
from test_helpers import (
    FLEET,
    SUPPORT,
    api_client,
    get_maintenance_event,
    get_success_data,
    get_vehicle,
    get_week,
    setup_agreement_with_due_week,
    setup_loaner_scenario,
    tender_week,
)
from test_helpers import lapse_grace, set_clock


def test_payment_dimension_walks_independently_of_the_week_dimension(api):
    """PRD §3.6: "When amount_cents is positive and strictly less than the
    outstanding amount owed, payment_status becomes PARTIAL, amount_due_cents is
    reduced by the tendered amount - the remainder is still genuinely owed - and
    coverage_cents is recomputed so the ledger still reconciles against the
    reduced balance."
    PRD §3.6: "When the channel reports payment_outcome as FAILED against a week
    whose payment_status is UNPAID or PARTIAL, payment_status becomes FAILED."

    Design: Difficulty/non_linear_state_machine/rental_week_payment_dimension_cycles_independently
    """
    ctx = setup_agreement_with_due_week(unlimited=True)
    week_id = ctx.week["id"]

    assert get_week(week_id)["payment_status"] == "UNPAID"

    partial = tender_week(week_id, 20_000)
    assert partial["payment_status"] == "PARTIAL"
    assert partial["week_status"] == "DUE", "the week dimension has not moved"
    assert partial["amount_due_cents"] == 18_435, (
        "the remainder of the tendered amount is still genuinely owed"
    )

    failed = tender_week(week_id, 18_435, outcome="FAILED")
    assert failed["payment_status"] == "FAILED"
    assert failed["week_status"] == "DUE", (
        "the week dimension is untouched by the payment dimension"
    )


def test_failed_week_recovers_by_retry_and_settles(api):
    """PRD §3.6: "Recovery from that state is a distinct operation: a SupportAgent
    or PlatformAdmin retries collection on the week, supplying a fresh amount and
    outcome. A retry against a FAILED week whose tender is again insufficient
    returns the week to UNPAID and records the new attempt; a retry whose tender
    covers the outstanding amount takes the week to SETTLED directly."
    PRD §3.6: "When enough has been tendered to cover the outstanding amount,
    payment_status becomes SETTLED and, if week_status was still DUE, GRACE or
    DELINQUENT, it also becomes PAID."

    Design: Difficulty/non_linear_state_machine/rental_week_payment_dimension_cycles_independently
    """
    ctx = setup_agreement_with_due_week(unlimited=True)
    week_id = ctx.week["id"]

    partial = tender_week(week_id, 20_000)
    assert partial["amount_due_cents"] == 18_435

    failed = tender_week(week_id, 18_435, outcome="FAILED")
    assert failed["payment_status"] == "FAILED"

    unsettled = get_success_data(api_client.retry_payment(
        week_id, {"amount_cents": 9_000, "payment_outcome": "SUCCEEDED"}, SUPPORT
    ))
    assert unsettled["payment_status"] == "UNPAID", (
        "an insufficient retry returns the week to UNPAID"
    )
    assert unsettled["week_status"] == "DUE"

    failed_again = tender_week(week_id, 9_000, outcome="FAILED")
    assert failed_again["payment_status"] == "FAILED", (
        "a week may fail, retry, fail again and retry again"
    )

    settled = get_success_data(api_client.retry_payment(
        week_id, {"amount_cents": 18_435, "payment_outcome": "SUCCEEDED"}, SUPPORT
    ))
    assert settled["payment_status"] == "SETTLED"
    assert settled["week_status"] == "PAID"


def test_week_status_is_untouched_by_the_payment_dimension_while_delinquent(api):
    """PRD §3.6: "This is a deliberately cyclic edge - a week may fail, retry,
    fail again, and retry again - and the week's status is untouched by the
    payment dimension throughout."
    PRD §3.4: "These two dimensions evolve independently on the very same row,
    and conflating them is a mistake the contract explicitly forbids: a period
    can be GRACE in status while UNPAID in payment, or DELINQUENT in status while
    FAILED in payment, and the transitions of one dimension never imply the
    transitions of the other."

    Design: Difficulty/non_linear_state_machine/rental_week_payment_dimension_cycles_independently
    """
    ctx = setup_agreement_with_due_week(unlimited=True)
    week_id = ctx.week["id"]

    set_clock("2026-09-11T00:00:00Z")
    delinquent = lapse_grace(week_id)
    assert delinquent["week_status"] == "DELINQUENT"
    assert delinquent["payment_status"] == "FAILED", (
        "declaring the week delinquent forces the payment dimension to FAILED"
    )

    revived = get_success_data(api_client.retry_payment(
        week_id, {"amount_cents": 1_000, "payment_outcome": "SUCCEEDED"}, SUPPORT
    ))
    assert revived["payment_status"] == "UNPAID"
    assert revived["week_status"] == "DELINQUENT", (
        "the payment dimension moved but the week dimension did not"
    )


def test_zero_downtime_service_completes_straight_from_reported(api):
    """PRD §3.7: "When the expected downtime is 0 hours, the event can be
    completed directly from REPORTED without ever entering IN_PROGRESS, because
    there is no window to cover. Completion in this path requires the downtime to
    be exactly 0, moves event_status to COMPLETED, records
    maintenance_allowance_applied_miles as 0, returns vehicle_status from
    MAINTENANCE to ASSIGNED, and recomputes the damage apportionment into
    damage_charge_cents on the agreement's open week. No loaner is ever issued on
    this path."

    Design: Difficulty/non_linear_state_machine/maintenance_completion_branches_on_loaner_presence
    """
    ctx = setup_loaner_scenario(downtime_hours=0, event_type="SCHEDULED_SERVICE")

    assert ctx.event["event_status"] == "REPORTED"
    assert get_vehicle(ctx.vehicle["id"])["vehicle_status"] == "MAINTENANCE"

    completed = get_success_data(api_client.complete_maintenance_event(
        ctx.event["id"], FLEET
    ))
    assert completed["event_status"] == "COMPLETED"
    assert completed["maintenance_allowance_applied_miles"] == 0
    assert completed["loaner_vehicle_id"] is None, "no loaner is issued on this path"

    vehicle = get_vehicle(ctx.vehicle["id"])
    assert vehicle["vehicle_status"] == "ASSIGNED"
    assert vehicle["assigned_driver_id"] == ctx.driver["id"]


def test_short_work_completes_from_in_progress_with_the_downtime_protected(api):
    """PRD §3.7: "When the expected downtime is greater than 0 but no greater than
    24 hours, completion is taken from IN_PROGRESS. event_status reaches
    COMPLETED, vehicle_status returns from MAINTENANCE to ASSIGNED,
    earnings_interruption_hours is recorded as the full downtime_hours, and
    maintenance_allowance_applied_miles is the smaller of downtime_hours and the
    agreement's maintenance_allowance_miles."

    Design: Difficulty/non_linear_state_machine/maintenance_completion_branches_on_loaner_presence
    """
    ctx = setup_loaner_scenario(downtime_hours=12, event_type="SCHEDULED_SERVICE")

    started = get_success_data(api_client.start_maintenance_event(ctx.event["id"], FLEET))
    assert started["event_status"] == "IN_PROGRESS"

    completed = get_success_data(api_client.complete_maintenance_event(
        ctx.event["id"], FLEET
    ))
    assert completed["event_status"] == "COMPLETED"
    assert completed["earnings_interruption_hours"] == 12, (
        "the driver did not actually lose working time, so the full downtime is protected"
    )
    assert completed["maintenance_allowance_applied_miles"] == 12, (
        "the smaller of the 12-hour downtime and the 200-mile allowance"
    )
    assert get_vehicle(ctx.vehicle["id"])["vehicle_status"] == "ASSIGNED"


def test_loaner_backed_completion_records_no_earnings_interruption(api):
    """PRD §3.7: "Completing a loaner-backed event is the compensating half. It
    requires event_status to be LOANER_ISSUED with loaner_vehicle_id set, and on
    success event_status reaches COMPLETED, the loaner's vehicle_status is
    released back to AVAILABLE with its assigned_driver_id cleared, the original
    unit's vehicle_status returns from MAINTENANCE to ASSIGNED with
    assigned_driver_id restamped from the agreement's driver_id,
    earnings_interruption_hours is recorded as 0."

    Design: Difficulty/non_linear_state_machine/maintenance_completion_branches_on_loaner_presence
    """
    ctx = setup_loaner_scenario(downtime_hours=30, event_type="UNSCHEDULED_REPAIR")

    api_client.start_maintenance_event(ctx.event["id"], FLEET)
    issued = get_success_data(api_client.issue_loaner(ctx.event["id"], FLEET))
    assert issued["event_status"] == "LOANER_ISSUED"
    assert issued["loaner_vehicle_id"] == ctx.spare["id"]

    completed = get_success_data(api_client.complete_maintenance_event(
        ctx.event["id"], FLEET
    ))
    assert completed["event_status"] == "COMPLETED"
    assert completed["earnings_interruption_hours"] == 0, (
        "the driver has been covered and so loses nothing"
    )

    original = get_vehicle(ctx.vehicle["id"])
    assert original["vehicle_status"] == "ASSIGNED"
    assert original["assigned_driver_id"] == ctx.driver["id"]

    spare = get_vehicle(ctx.spare["id"])
    assert spare["vehicle_status"] == "AVAILABLE"
    assert spare["assigned_driver_id"] is None


def test_loaner_allowance_divides_the_downtime_by_eight(api):
    """PRD §3.7: "maintenance_allowance_applied_miles is the smaller of
    downtime_hours divided by 8 rounded half up to a whole number of hours, and
    the agreement's maintenance_allowance_miles. That divisor reflects the fact
    that a loaner already absorbed the driver's working hours, so only the unit's
    own wear is charged against the allowance."

    Design: Difficulty/non_linear_state_machine/maintenance_completion_branches_on_loaner_presence
    """
    ctx = setup_loaner_scenario(downtime_hours=30, event_type="UNSCHEDULED_REPAIR")
    api_client.start_maintenance_event(ctx.event["id"], FLEET)
    api_client.issue_loaner(ctx.event["id"], FLEET)
    completed = get_success_data(api_client.complete_maintenance_event(
        ctx.event["id"], FLEET
    ))

    assert completed["maintenance_allowance_applied_miles"] == 4, (
        "30 hours divided by 8 rounds half up to 4, which is below the 200-mile allowance"
    )
    assert get_maintenance_event(ctx.event["id"])["earnings_interruption_hours"] == 0