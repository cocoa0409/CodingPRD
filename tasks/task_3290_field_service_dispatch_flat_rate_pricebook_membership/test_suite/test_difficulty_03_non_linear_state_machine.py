"""Depth tests for the non-linear state machines.

Two instances: the Appointment's three parallel dimensions, and the
MembershipVisit / MembershipAgreement cycle around a missed visit.
"""
from test_helpers import (
    TEST_USERS,
    api_client,
    fixtures as F,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import completion_payload, decide_payload, override_request_payload

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
MANAGER = TEST_USERS["manager_headers"]


# =====================================================================
# appointment_three_parallel_dimensions
# =====================================================================
def _dispatched_appointment_with_rejected_override(requested=340000):
    branch, technician, task, appointment = F.setup_dispatched_appointment(
        code="HVAC-COMP", price_cents=300000, hours=3.0
    )
    tech_headers = F.make_technician_headers(appointment["technician_id"])
    request = validate_success(
        api_client.file_override_request(
            appointment["id"], override_request_payload(requested), tech_headers
        ),
        expected_status=201,
    )
    current = F.get_appointment(appointment["id"])
    response = api_client.decide_override(
        request["id"], decide_payload("REJECT", current["version"]), MANAGER
    )
    rejected = validate_success(response)
    return branch, technician, task, appointment, rejected, tech_headers


def test_rejected_quote_leaves_lifecycle_and_capacity_dimensions_untouched(api):
    """PRD §2.9: "An appointment carries three parallel dimensions."
    PRD §3.6: "On rejection the consequence falls on the technician, not the price. The
    request's `status` becomes `REJECTED` ... the appointment's `pricing_status` becomes
    `QUOTE_REJECTED`".

    Design: Difficulty/non_linear_state_machine/appointment_three_parallel_dimensions
    """
    branch, technician, task, appointment, rejected, tech_headers = (
        _dispatched_appointment_with_rejected_override()
    )

    refreshed = F.get_appointment(appointment["id"])
    assert refreshed["pricing_status"] == "QUOTE_REJECTED", (
        f"a rejected decision moves only the pricing dimension, got {refreshed['pricing_status']}"
    )
    assert refreshed["status"] == "DISPATCHED", (
        f"the job never moved, got status {refreshed['status']}"
    )
    assert refreshed["dispatch_status"] == "DISPATCHED", (
        f"the capacity dimension never moved, got {refreshed['dispatch_status']}"
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["decided_by_user_id"] == TEST_USERS["manager_headers"]["X-User-ID"]


def test_rejected_quote_can_be_refiled_while_the_job_stays_dispatched(api):
    """PRD §3.6: "a request may be filed when the appointment is `QUOTE_REJECTED`, moving
    it back to `OVERRIDE_PENDING`: a refused quote is not a dead end and may be
    re-submitted."

    Design: Difficulty/non_linear_state_machine/appointment_three_parallel_dimensions
    """
    branch, technician, task, appointment, rejected, tech_headers = (
        _dispatched_appointment_with_rejected_override()
    )

    refiled = validate_success(
        api_client.file_override_request(
            appointment["id"], override_request_payload(342500), tech_headers
        ),
        expected_status=201,
    )
    assert refiled["status"] == "PENDING"

    refreshed = F.get_appointment(appointment["id"])
    assert refreshed["pricing_status"] == "OVERRIDE_PENDING", (
        f"re-filing must loop the pricing dimension back, got {refreshed['pricing_status']}"
    )
    assert refreshed["status"] == "DISPATCHED"
    assert refreshed["dispatch_status"] == "DISPATCHED"


# =====================================================================
# membership_visit_cyclic_missed_loop
# =====================================================================
def _activated_agreement_with_one_visit():
    branch, plan, agreement, visits = F.setup_membership(
        visit_dates=["2026-10-01T00:00:00Z"]
    )
    return branch, plan, agreement, visits[0]


def test_missed_visit_reschedule_reopens_it_and_clears_the_overdue_parent(api):
    """PRD §3.9: "When the reschedule succeeds the visit's `status` returns to `SCHEDULED`
    and its `scheduled_date` is replaced, and the parent agreement returns to `ACTIVE`
    when it was `OVERDUE` and no other visit on it remains `MISSED`."

    Design: Difficulty/non_linear_state_machine/membership_visit_cyclic_missed_loop
    """
    branch, plan, agreement, visit = _activated_agreement_with_one_visit()

    api_client.set_clock({"to_iso8601": "2026-11-15T00:00:00Z"}, ADMIN)
    missed = F.list_visits(agreement["id"])[0]
    assert missed["status"] == "MISSED", "advancing the clock past the visit date marks it MISSED"
    assert F.get_agreement(agreement["id"])["status"] == "OVERDUE"

    response = api_client.reschedule_visit(
        visit["id"], {"scheduled_date": "2026-12-01T00:00:00Z"}, DISPATCHER
    )
    reopened = validate_success(response)
    assert reopened["status"] == "SCHEDULED", f"got {reopened['status']}"
    assert reopened["scheduled_date"].startswith("2026-12-01")
    assert F.get_agreement(agreement["id"])["status"] == "ACTIVE", (
        "a single successful reschedule clears the OVERDUE state"
    )


def test_the_missed_loop_is_reachable_a_second_time(api):
    """PRD §2.4: "The server starts with its logical clock fixed at `2026-09-01T00:00:00Z`".
    PRD §3.9: "Every `MembershipVisit` whose `scheduled_date` is strictly earlier than the
    new reading and whose `status` is `SCHEDULED` transitions to `MISSED`."

    Design: Difficulty/non_linear_state_machine/membership_visit_cyclic_missed_loop
    """
    branch, plan, agreement, visit = _activated_agreement_with_one_visit()

    api_client.set_clock({"to_iso8601": "2026-11-15T00:00:00Z"}, ADMIN)
    api_client.reschedule_visit(visit["id"], {"scheduled_date": "2026-12-01T00:00:00Z"}, DISPATCHER)

    api_client.set_clock({"to_iso8601": "2027-01-15T00:00:00Z"}, ADMIN)
    again = F.list_visits(agreement["id"])[0]
    assert again["status"] == "MISSED", (
        f"the same visit must be missable again after reopening, got {again['status']}"
    )
    assert F.get_agreement(agreement["id"])["status"] == "OVERDUE", (
        "the parent must return to OVERDUE on the second lap"
    )