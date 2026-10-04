"""Breadth tests for the state machines: illegal transitions, dispatch side
effects, dispatch preconditions and the visit terminal-state behaviour.
"""
from prd_bench_local_runner.testing import validate_error, validate_error_is_one_of, validate_success

from test_helpers import TEST_USERS, api_client, fixtures as F

DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_cancelling_an_in_service_appointment_is_refused(api):
    """PRD §3.7: "The first call against a `DISPATCHED` appointment moves only the capacity
    dimension: the appointment's `dispatch_status` becomes `IN_SERVICE`".
    PRD §3.10: "Any attempt to cancel from a state the machine does not declare is refused
    with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/cancel_completed_appointment_from_priced_state
    """
    branch, technician, task, appointment = F.setup_dispatched_appointment(
        code="HVAC-COIL", price_cents=60000, hours=1.0,
        window_start="2026-09-10T09:00:00Z", window_end="2026-09-10T11:00:00Z",
    )
    F.complete_first_call(appointment["id"])

    in_service = F.get_appointment(appointment["id"])
    assert in_service["dispatch_status"] == "IN_SERVICE"
    assert in_service["status"] == "DISPATCHED"

    response = api_client.cancel_appointment(
        appointment["id"], {"reason": "no longer needed"}, DISPATCHER
    )
    validate_error_is_one_of(response, ["ERR_INVALID_STATE", "ERR_SEGREGATION_OF_DUTIES"])

    refreshed = F.get_appointment(appointment["id"])
    assert refreshed["status"] == "DISPATCHED"
    assert refreshed["dispatch_status"] == "IN_SERVICE"


def test_dispatch_publishes_technician_pricing_and_quote_together(api):
    """PRD §3.5: "The appointment's `technician_id` becomes the selected technician's id,
    its `status` becomes `DISPATCHED` and its `dispatch_status` becomes `DISPATCHED`."
    PRD §3.5: "The discount rate is normally zero".
    PRD §3.5: "`authorization_required` is set true exactly when the committed quote exceeds
    one and twenty hundredths of the appointment's `labor_base_cents`".

    Design: Corner/state_machines/dispatch_side_effect_publishes_the_auto_quote
    """
    branch, technician, task, appointment = F.setup_dispatched_appointment(
        code="HVAC-COMP", price_cents=300000, hours=3.0
    )

    assert appointment["status"] == "DISPATCHED"
    assert appointment["dispatch_status"] == "DISPATCHED"
    assert appointment["pricing_status"] == "AUTO_QUOTED"
    assert appointment["technician_id"] == technician["id"]
    assert appointment["quoted_price_cents"] == 300000, (
        f"no membership discount applies here, got {appointment['quoted_price_cents']}"
    )
    assert appointment["authorization_required"] is False
    assert appointment["estimated_hours"] == 3.0
    assert F.get_technician(technician["id"])["dispatched_hours"] == 3.0
    assert F.get_branch(branch["id"])["capacity_consumed_hours"] == 3.0


def test_dispatching_a_line_free_appointment_is_refused(api):
    """PRD §3.5: "it must carry at least one line; an appointment with no lines has
    `estimated_hours` of 0 and is not dispatchable, and the attempt is refused with
    `ERR_NO_APPOINTMENT_LINES` (HTTP 409)."

    Design: Corner/state_machines/dispatch_refused_for_zero_line_appointment
    """
    branch, technician, task, appointment, line = F.setup_branch_appointment_and_task(with_line=False)

    response = api_client.dispatch_order({"appointment_id": appointment["id"]}, DISPATCHER)
    validate_error(response, "ERR_NO_APPOINTMENT_LINES")

    refreshed = F.get_appointment(appointment["id"])
    assert refreshed["estimated_hours"] == 0
    assert refreshed["dispatch_status"] == "UNASSIGNED"
    assert F.get_technician(technician["id"])["dispatched_hours"] == 0


def test_rescheduling_an_already_completed_visit_is_refused(api):
    """PRD §3.9: "the visit must be in a state from which the transition is declared."
    PRD §3.9: "A `Dispatcher` reschedules a visit by supplying a new `scheduled_date`".

    Design: Corner/state_machines/membership_visit_reached_terminal_state
    """
    branch, technician, plan, agreement, visit, appointment, task = (
        F.setup_member_visit_appointment(code="HVAC-TUNE", price_cents=5000, hours=1.0)
    )
    F.dispatch_two_calls(appointment["id"])

    completed = [v for v in F.list_visits(agreement["id"]) if v["id"] == visit["id"]][0]
    assert completed["status"] == "COMPLETED"
    assert completed["completed_appointment_id"] == appointment["id"]

    response = api_client.reschedule_visit(
        visit["id"], {"scheduled_date": "2026-10-05T00:00:00Z"}, DISPATCHER
    )
    validate_error(response, "ERR_INVALID_STATE")

    still = [v for v in F.list_visits(agreement["id"]) if v["id"] == visit["id"]][0]
    assert still["status"] == "COMPLETED"
    assert still["completed_appointment_id"] == appointment["id"]
    assert F.get_agreement(agreement["id"])["visits_fulfilled_count"] == 1