"""Difficulty-queue tests: cross-entity state dependencies and compensating invariants."""
import pytest

from test_helpers import (
    ApiErrorId,
    COORDINATOR,
    SPECIALIST,
    activate_care_team_for,
    api_client,
    create_member_with_enrollment,
    create_scheduled_visit,
    drive_enrollment_to_consented,
    get_measurement_for_member,
    get_success_data,
    setup_active_enrollment,
    setup_basic_reference,
    create_clinician,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/enrollment_activate_gated_by_care_team_active
# ---------------------------------------------------------------------------

def _setup_consented_with_draft_care_team():
    program, contract, pcp, np = setup_basic_reference()
    member, enrollment = create_member_with_enrollment(program, contract, pcp)
    drive_enrollment_to_consented(enrollment["id"])
    # Assign the primary NP but do NOT activate the care team.
    get_success_data(api_client.update_care_team(
        enrollment["id"], {"primary_np_id": np["id"]}, COORDINATOR
    ))
    return program, member, enrollment, np


def test_enrollment_activate_blocked_while_care_team_draft(api):
    """PRD section 3.5: "Activation requires the enrollment to be in `CONSENTED` (else `ERR_ENROLLMENT_NOT_CONSENTED`) and the associated care team to be `ACTIVE` (else `ERR_CARE_TEAM_NOT_ACTIVE`)."

    Design: Difficulty/cross_entity_state_dependency/enrollment_activate_gated_by_care_team_active
    """
    _program, _member, enrollment, _np = _setup_consented_with_draft_care_team()
    resp = api.activate_enrollment(enrollment["id"], SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_CARE_TEAM_NOT_ACTIVE, expected_status=409)
    after = get_success_data(api.get_enrollment(enrollment["id"], SPECIALIST))
    assert after["status"] == "CONSENTED", (
        "the failed activation must leave the enrollment CONSENTED"
    )


def test_enrollment_activate_succeeds_after_care_team_activated(api):
    """PRD section 3.4: "Activating the care team requires the team to be in `DRAFT` (else `ERR_CARE_TEAM_NOT_DRAFT`) and requires `primary_np_id` to be populated, to reference an `ACTIVE` clinician, and to reference a clinician whose `discipline` is `NP` — failure of any of these is reported as `ERR_PRIMARY_NP_INVALID`. On success the team moves to `ACTIVE`. Only then can the parent enrollment be activated (see §3.5)."
    PRD section 3.5: "On success the enrollment moves to `ACTIVE`, becoming eligible for visit scheduling and urgent-response episodes."

    Design: Difficulty/cross_entity_state_dependency/enrollment_activate_gated_by_care_team_active
    """
    _program, _member, enrollment, np = _setup_consented_with_draft_care_team()
    activate_care_team_for(enrollment["id"], np["id"])
    activated = validate_success(api.activate_enrollment(enrollment["id"], SPECIALIST))
    assert activated["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/visit_creation_gated_by_enrollment_active_and_care_team_active
# ---------------------------------------------------------------------------

def test_visit_creation_blocked_while_care_team_suspended(api):
    """PRD section 3.4: "While a team is `SUSPENDED`, any new visit creation against the parent enrollment is rejected with `ERR_CARE_TEAM_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/visit_creation_gated_by_enrollment_active_and_care_team_active
    """
    ctx = setup_active_enrollment()
    get_success_data(api_client.suspend_care_team(ctx["enrollment"]["id"], COORDINATOR))
    resp = api.create_visit(
        {
            "enrollment_id": ctx["enrollment"]["id"],
            "visit_type": "ROUTINE_FOLLOWUP",
            "scheduled_start": "2026-09-02T09:00:00Z",
            "scheduled_end": "2026-09-02T10:00:00Z",
        },
        COORDINATOR,
    )
    validate_error(resp, ApiErrorId.ERR_CARE_TEAM_NOT_ACTIVE, expected_status=409)


def test_visit_creation_allowed_again_after_reinstate(api):
    """PRD section 3.4: "The coordinator may reinstate a `SUSPENDED` team back to `ACTIVE` — calling reinstate from any other status yields `ERR_CARE_TEAM_NOT_SUSPENDED`."
    PRD section 3.5: "On success the new visit lands in `SCHEDULED`, the assigned clinician's `active_daily_visit_count` increments by 1, and the visit's `member_id` is denormalized from the enrollment for direct lookup."

    Design: Difficulty/cross_entity_state_dependency/visit_creation_gated_by_enrollment_active_and_care_team_active
    """
    ctx = setup_active_enrollment()
    get_success_data(api_client.suspend_care_team(ctx["enrollment"]["id"], COORDINATOR))
    get_success_data(api_client.reinstate_care_team(ctx["enrollment"]["id"], COORDINATOR))
    visit = validate_success(api.create_visit(
        {
            "enrollment_id": ctx["enrollment"]["id"],
            "visit_type": "ROUTINE_FOLLOWUP",
            "scheduled_start": "2026-09-02T09:00:00Z",
            "scheduled_end": "2026-09-02T10:00:00Z",
        },
        COORDINATOR,
    ), expected_status=201)
    assert visit["status"] == "SCHEDULED"
    assert visit["member_id"] == ctx["member"]["id"]


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/visit_cancel_then_reschedule_conserves_active_daily_visit_count
# ---------------------------------------------------------------------------

def _setup_single_scheduled_visit():
    ctx = setup_active_enrollment(clinician_overrides={"max_daily_visits": 10})
    visit = create_scheduled_visit(ctx["enrollment"]["id"])
    return ctx, visit


def test_cancel_decrements_then_reschedule_restores_count(api):
    """PRD section 3.5: "Cancellation moves the visit to `CANCELLED`, decrements the assigned clinician's `active_daily_visit_count` by 1, and increments `visits_cancelled` on the period's `PerformanceMeasurement` row (with `composite_score` recomputed)."
    PRD section 3.5: "A successful reschedule increments `reschedule_count` by 1, updates `scheduled_start` and `scheduled_end` to the new window, re-increments the clinician's `active_daily_visit_count` by 1, decrements `visits_cancelled` by 1 with `composite_score` recomputed, and advances the visit's `version` by 1 — which is exactly the mechanism by which a concurrent writer's stale reschedule is caught."

    Design: Difficulty/compensating_invariant/visit_cancel_then_reschedule_conserves_active_daily_visit_count
    """
    ctx, visit = _setup_single_scheduled_visit()
    np_id = ctx["np"]["id"]
    assert get_success_data(api.get_clinician(np_id, COORDINATOR))["active_daily_visit_count"] == 1

    cancelled = validate_success(api.cancel_visit(
        visit["id"], {"cancellation_reason": "MEMBER_REQUEST"}, COORDINATOR
    ))
    assert get_success_data(api.get_clinician(np_id, COORDINATOR))["active_daily_visit_count"] == 0

    validate_success(api.reschedule_visit(
        visit["id"],
        {
            "scheduled_start": "2026-09-03T09:00:00Z",
            "scheduled_end": "2026-09-03T10:00:00Z",
            "expected_visit_version": cancelled["version"],
        },
        COORDINATOR,
    ))
    assert get_success_data(api.get_clinician(np_id, COORDINATOR))["active_daily_visit_count"] == 1


def test_cancel_reschedule_cycle_conserves_count_no_drift(api):
    """PRD section 3.5: "A successful reschedule increments `reschedule_count` by 1, updates `scheduled_start` and `scheduled_end` to the new window, re-increments the clinician's `active_daily_visit_count` by 1, decrements `visits_cancelled` by 1 with `composite_score` recomputed, and advances the visit's `version` by 1 — which is exactly the mechanism by which a concurrent writer's stale reschedule is caught."

    Design: Difficulty/compensating_invariant/visit_cancel_then_reschedule_conserves_active_daily_visit_count
    """
    ctx, visit = _setup_single_scheduled_visit()
    np_id = ctx["np"]["id"]
    pre = get_success_data(api.get_clinician(np_id, COORDINATOR))["active_daily_visit_count"]
    cancelled = validate_success(api.cancel_visit(
        visit["id"], {"cancellation_reason": "MEMBER_REQUEST"}, COORDINATOR
    ))
    validate_success(api.reschedule_visit(
        visit["id"],
        {
            "scheduled_start": "2026-09-03T09:00:00Z",
            "scheduled_end": "2026-09-03T10:00:00Z",
            "expected_visit_version": cancelled["version"],
        },
        COORDINATOR,
    ))
    post = get_success_data(api.get_clinician(np_id, COORDINATOR))["active_daily_visit_count"]
    assert post == pre, f"cancel+reschedule must conserve the count: {pre} -> {post}"


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/performance_measurement_visit_counters_conserve_under_cancel_reschedule_cycle
# ---------------------------------------------------------------------------

def test_cancel_increments_then_reschedule_decrements_visits_cancelled(api):
    """PRD section 3.5: "Cancellation moves the visit to `CANCELLED`, decrements the assigned clinician's `active_daily_visit_count` by 1, and increments `visits_cancelled` on the period's `PerformanceMeasurement` row (with `composite_score` recomputed)."
    PRD section 3.5: "A successful reschedule increments `reschedule_count` by 1, updates `scheduled_start` and `scheduled_end` to the new window, re-increments the clinician's `active_daily_visit_count` by 1, decrements `visits_cancelled` by 1 with `composite_score` recomputed, and advances the visit's `version` by 1 — which is exactly the mechanism by which a concurrent writer's stale reschedule is caught."

    Design: Difficulty/compensating_invariant/performance_measurement_visit_counters_conserve_under_cancel_reschedule_cycle
    """
    ctx, visit = _setup_single_scheduled_visit()
    member_id = ctx["member"]["id"]
    cancelled = validate_success(api.cancel_visit(
        visit["id"], {"cancellation_reason": "MEMBER_REQUEST"}, COORDINATOR
    ))
    assert get_measurement_for_member(member_id)["visits_cancelled"] == 1
    validate_success(api.reschedule_visit(
        visit["id"],
        {
            "scheduled_start": "2026-09-03T09:00:00Z",
            "scheduled_end": "2026-09-03T10:00:00Z",
            "expected_visit_version": cancelled["version"],
        },
        COORDINATOR,
    ))
    assert get_measurement_for_member(member_id)["visits_cancelled"] == 0


def test_visit_counters_sum_conserved_across_cycle(api):
    """PRD section 3.7: "The visit-completion component is `visits_completed` divided by the sum of `visits_completed`, `visits_no_show`, and `visits_cancelled`, again falling back to 1.0 when the denominator is empty."

    Design: Difficulty/compensating_invariant/performance_measurement_visit_counters_conserve_under_cancel_reschedule_cycle
    """
    ctx, visit = _setup_single_scheduled_visit()
    member_id = ctx["member"]["id"]
    cancelled = validate_success(api.cancel_visit(
        visit["id"], {"cancellation_reason": "MEMBER_REQUEST"}, COORDINATOR
    ))
    validate_success(api.reschedule_visit(
        visit["id"],
        {
            "scheduled_start": "2026-09-03T09:00:00Z",
            "scheduled_end": "2026-09-03T10:00:00Z",
            "expected_visit_version": cancelled["version"],
        },
        COORDINATOR,
    ))
    row = get_measurement_for_member(member_id)
    assert row["visits_completed"] == 0
    assert row["visits_no_show"] == 0
    assert row["visits_cancelled"] == 0, (
        "the rescheduled visit returned to SCHEDULED and is no longer terminal"
    )
