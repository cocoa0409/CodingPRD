"""Difficulty-queue tests: non-linear state machines (enrollment and visit cycles)."""
import pytest

from test_helpers import (
    ApiErrorId,
    COORDINATOR,
    SPECIALIST,
    api_client,
    create_member_with_enrollment,
    create_scheduled_visit,
    get_measurement_for_member,
    get_success_data,
    setup_active_enrollment,
    setup_basic_reference,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/member_enrollment_outreach_declined_reengagement_cycle
# ---------------------------------------------------------------------------

def _setup_identified_enrollment():
    program, contract, pcp, _np = setup_basic_reference(with_clinician=False)
    member, enrollment = create_member_with_enrollment(program, contract, pcp)
    return member, enrollment


def test_outreach_self_loop_increments_attempts(api):
    """PRD section 3.3: "While in `OUTREACH`, the specialist records each subsequent contact by recording an attempt. This is a cyclic self-transition that leaves the enrollment in `OUTREACH` and increments `outreach_attempts` by 1."
    PRD section 3.3: "Both paths require `is_current` to be `true` — operating on a superseded enrollment is rejected with `ERR_ENROLLMENT_SUPERSEDED` — and both reset `outreach_attempts` to 1, initializing the counter on first outreach and resetting it on re-engagement."

    Design: Difficulty/non_linear_state_machine/member_enrollment_outreach_declined_reengagement_cycle
    """
    _member, enrollment = _setup_identified_enrollment()
    enr_id = enrollment["id"]

    first = validate_success(api.begin_outreach(enr_id, SPECIALIST))
    assert first["status"] == "OUTREACH"
    assert first["outreach_attempts"] == 1, (
        "begin-outreach initializes the counter to 1"
    )

    looped = validate_success(api.record_attempt(enr_id, SPECIALIST))
    assert looped["status"] == "OUTREACH"
    assert looped["outreach_attempts"] == 2, (
        "the OUTREACH self-loop increments the counter"
    )


def test_declined_reengagement_resets_attempts(api):
    """PRD section 3.3: "The same begin-outreach action is also the re-engagement path from `DECLINED` back to `OUTREACH`; the two paths are distinguished by their starting state, with a call against an `IDENTIFIED` enrollment carrying the precondition that the status really is `IDENTIFIED` (else `ERR_ENROLLMENT_NOT_IDENTIFIED`) and a call against a `DECLINED` enrollment requiring the status really be `DECLINED` (else `ERR_ENROLLMENT_NOT_DECLINED`)."
    PRD section 3.3: "Both paths require `is_current` to be `true` — operating on a superseded enrollment is rejected with `ERR_ENROLLMENT_SUPERSEDED` — and both reset `outreach_attempts` to 1, initializing the counter on first outreach and resetting it on re-engagement."

    Design: Difficulty/non_linear_state_machine/member_enrollment_outreach_declined_reengagement_cycle
    """
    _member, enrollment = _setup_identified_enrollment()
    enr_id = enrollment["id"]

    validate_success(api.begin_outreach(enr_id, SPECIALIST))
    validate_success(api.record_attempt(enr_id, SPECIALIST))
    declined = validate_success(api.record_decline(enr_id, SPECIALIST))
    assert declined["status"] == "DECLINED"

    reengaged = validate_success(api.begin_outreach(enr_id, SPECIALIST))
    assert reengaged["status"] == "OUTREACH"
    assert reengaged["outreach_attempts"] == 1, (
        "re-engagement resets the counter to 1, it does not increment"
    )


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/visit_cancelled_to_scheduled_reschedule_cycle
# ---------------------------------------------------------------------------

def _cancel_and_reschedule(visit, version, day):
    cancelled = validate_success(api_client.cancel_visit(
        visit["id"], {"cancellation_reason": "MEMBER_REQUEST"}, COORDINATOR
    ))
    rescheduled = validate_success(api_client.reschedule_visit(
        visit["id"],
        {
            "scheduled_start": f"{day}T09:00:00Z",
            "scheduled_end": f"{day}T10:00:00Z",
            "expected_visit_version": cancelled["version"],
        },
        COORDINATOR,
    ))
    return cancelled, rescheduled


def test_reschedule_cycle_increments_count_up_to_cap(api):
    """PRD section 3.5: "A successful reschedule increments `reschedule_count` by 1, updates `scheduled_start` and `scheduled_end` to the new window, re-increments the clinician's `active_daily_visit_count` by 1, decrements `visits_cancelled` by 1 with `composite_score` recomputed, and advances the visit's `version` by 1 — which is exactly the mechanism by which a concurrent writer's stale reschedule is caught."

    Design: Difficulty/non_linear_state_machine/visit_cancelled_to_scheduled_reschedule_cycle
    """
    ctx = setup_active_enrollment(clinician_overrides={"max_daily_visits": 10})
    visit = create_scheduled_visit(ctx["enrollment"]["id"])

    cancelled, rescheduled = _cancel_and_reschedule(visit, visit["version"], "2026-09-06")
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["reschedule_count"] == 0
    assert rescheduled["status"] == "SCHEDULED"
    assert rescheduled["reschedule_count"] == 1

    _c2, rescheduled2 = _cancel_and_reschedule(rescheduled, rescheduled["version"], "2026-09-08")
    assert rescheduled2["reschedule_count"] == 2


def test_third_reschedule_rejected_at_cap(api):
    """PRD section 3.5: "The reschedule requires the visit to be `CANCELLED` (else `ERR_VISIT_NOT_CANCELLED`), the visit's `reschedule_count` to be strictly less than the cap of 2 (else `ERR_MAX_RESCHEDULES_EXCEEDED`), the proposed window to clear the half-open overlap check against the clinician's other in-flight visits (else `ERR_VISIT_TIME_OVERLAP`), and the parent enrollment to be `ACTIVE` (else `ERR_ENROLLMENT_NOT_ACTIVE`)."

    Design: Difficulty/non_linear_state_machine/visit_cancelled_to_scheduled_reschedule_cycle
    """
    ctx = setup_active_enrollment(clinician_overrides={"max_daily_visits": 10})
    visit = create_scheduled_visit(ctx["enrollment"]["id"])

    _c1, r1 = _cancel_and_reschedule(visit, visit["version"], "2026-09-06")
    _c2, r2 = _cancel_and_reschedule(r1, r1["version"], "2026-09-08")
    c3 = validate_success(api_client.cancel_visit(
        r2["id"], {"cancellation_reason": "MEMBER_REQUEST"}, COORDINATOR
    ))
    resp = api_client.reschedule_visit(
        r2["id"],
        {
            "scheduled_start": "2026-09-10T09:00:00Z",
            "scheduled_end": "2026-09-10T10:00:00Z",
            "expected_visit_version": c3["version"],
        },
        COORDINATOR,
    )
    validate_error(resp, ApiErrorId.ERR_MAX_RESCHEDULES_EXCEEDED, expected_status=409)
    after = validate_success(api.get_visit(r2["id"], COORDINATOR))
    assert after["reschedule_count"] == 2, (
        "the rejected third reschedule must not advance the counter"
    )
    row = get_measurement_for_member(ctx["member"]["id"])
    assert row["visits_cancelled"] == 1, (
        "only the third, un-rescheduled cancel remains counted"
    )
