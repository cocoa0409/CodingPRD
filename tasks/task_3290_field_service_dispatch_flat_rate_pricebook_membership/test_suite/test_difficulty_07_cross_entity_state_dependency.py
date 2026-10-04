"""Depth tests for cross-entity state dependencies.

Two instances: the coaching review that cannot close before its attributed job
completes, and the agreement-status guard on visit scheduling.
"""
from prd_bench_local_runner.testing import validate_error, validate_error_is_one_of

from test_helpers import (
    TEST_USERS,
    api_client,
    fixtures as F,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
MANAGER = TEST_USERS["manager_headers"]
CS = TEST_USERS["customer_service_headers"]



def _call_with_dispatched_job():
    """A recorded call whose attributed appointment is dispatched but not completed."""
    branch = F.create_branch()
    technician = F.hire_technician(
        branch["id"],
        daily_capacity_hours=40,
        shift_segments=[{"start_utc": "2026-09-01T00:00:00Z", "end_utc": "2026-09-20T00:00:00Z"}],
    )
    campaign = F.create_campaign(spend_cents=50000)
    F.create_task(
        code="HVAC-COIL", category="HVAC", required_skill_code="HVAC",
        estimated_hours=1.0, flat_rate_cents=60000,
    )
    call = F.create_call_record(campaign["id"])
    appointment = F.book_appointment(
        branch["id"],
        campaign_id=campaign["id"],
        call_record_id=call["id"],
    )
    F.add_line(appointment["id"], code="HVAC-COIL")
    appointment = F.dispatch(appointment["id"])
    api_client.assign_coaching(
        call["id"], {"decision": "ASSIGN_COACHING"}, MANAGER
    )
    return branch, technician, campaign, call, appointment


# =====================================================================
# call_review_requires_completed_appointment
# =====================================================================
def test_closing_a_call_review_before_the_job_completes_is_refused(api):
    """PRD §3.13: "A call with no attributed appointment, or whose attributed appointment
    is not yet complete, cannot be closed: the attempt is refused with
    `ERR_CALL_NOT_REVIEWABLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/call_review_requires_completed_appointment
    """
    branch, technician, campaign, call, appointment = _call_with_dispatched_job()

    assigned = validate_success(
        api_client.list_campaign_calls(campaign["id"], MANAGER)
    )
    if isinstance(assigned, dict) and "items" in assigned:
        assigned = assigned["items"]
    assert [c["coaching_status"] for c in assigned] == ["COACHING_ASSIGNED"]

    response = api_client.assign_coaching(
        call["id"], {"decision": "COMPLETE_REVIEW"}, MANAGER
    )
    validate_error(response, "ERR_CALL_NOT_REVIEWABLE")


def test_closing_the_review_succeeds_once_the_attributed_job_is_complete(api):
    """PRD §3.13: "A manager closes the review by supplying a decision that completes the
    review, and the call must have an `attributed_appointment_id` whose appointment's
    `status` is `COMPLETED`."
    PRD §3.13: "Two paths lead to `REVIEWED`: a call already at `COACHING_ASSIGNED` may be
    closed, and a call that never needed coaching may be closed directly from
    `UNREVIEWED`."

    Design: Difficulty/cross_entity_state_dependency/call_review_requires_completed_appointment
    """
    branch, technician, campaign, call, appointment = _call_with_dispatched_job()

    completed = F.dispatch_two_calls(appointment["id"])
    assert completed["status"] == "COMPLETED"

    response = api_client.assign_coaching(
        call["id"], {"decision": "COMPLETE_REVIEW"}, MANAGER
    )
    closed = validate_success(response)
    assert closed["coaching_status"] == "REVIEWED", (
        f"the guard is on the appointment pair, got {closed['coaching_status']}"
    )


# =====================================================================
# agreement_activation_gates_visit_scheduling
# =====================================================================
def _plan_and_agreement(activate=True):
    branch = F.create_branch()
    plan = F.create_plan()
    agreement = F.sell_agreement(branch["id"], plan["id"])
    if activate:
        F.record_payment(agreement["id"], 30000)
    return branch, plan, agreement


def test_scheduling_a_visit_on_a_cancelled_agreement_is_refused(api):
    """PRD §3.8: "The parent agreement may be `PENDING_PAYMENT`, `ACTIVE` or `OVERDUE`
    when a visit is scheduled."
    PRD §3.9: "In every case the agreement's `status` becomes `CANCELLED`".

    Design: Difficulty/cross_entity_state_dependency/agreement_activation_gates_visit_scheduling
    """
    branch, plan, agreement = _plan_and_agreement()
    F.schedule_visit(agreement["id"], 1, "2026-10-01T00:00:00Z")

    cancelled = validate_success(
        api_client.cancel_membership(
            agreement["id"], {"reason": "homeowner moved"}, MANAGER
        )
    )
    assert cancelled["status"] == "CANCELLED"

    response = api_client.schedule_visit(
        agreement["id"], {"sequence_number": 2, "scheduled_date": "2026-11-01T00:00:00Z"}, DISPATCHER
    )
    validate_error_is_one_of(response, ["ERR_AGREEMENT_NOT_ACTIVE", "ERR_INVALID_STATE"])

    visits = F.list_visits(agreement["id"])
    assert len(visits) == 1, "no second visit may be created on a cancelled agreement"


def test_a_pending_payment_agreement_still_accepts_a_scheduled_visit(api):
    """PRD §3.8: "The parent agreement may be `PENDING_PAYMENT`, `ACTIVE` or `OVERDUE`
    when a visit is scheduled."
    PRD §3.9: "the `membership_count_active` of every affected branch is recomputed."

    Design: Difficulty/cross_entity_state_dependency/agreement_activation_gates_visit_scheduling
    """
    branch, plan, agreement = _plan_and_agreement(activate=False)
    assert F.get_agreement(agreement["id"])["status"] == "PENDING_PAYMENT"

    response = api_client.schedule_visit(
        agreement["id"], {"sequence_number": 2, "scheduled_date": "2026-11-01T00:00:00Z"}, DISPATCHER
    )
    visit = validate_success(response, expected_status=201)
    assert visit["status"] == "SCHEDULED"
    assert visit["sequence_number"] == 2

    assert F.get_branch(branch["id"])["membership_count_active"] == 0, (
        "a PENDING_PAYMENT agreement is not an active member"
    )