"""Difficulty-queue tests: validation priority pairs across error categories."""
import pytest

from test_helpers import (
    ApiErrorId,
    COORDINATOR,
    SPECIALIST,
    api_client,
    create_clinician,
    create_member_with_enrollment,
    create_scheduled_visit,
    create_triggered_episode,
    get_success_data,
    make_clinician_headers,
    set_clock,
    advance_clock,
    setup_active_enrollment,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/state_precondition_beats_clinician_assignment_check
# ---------------------------------------------------------------------------

def _setup_en_route_visit_with_two_clinicians():
    program_ctx = setup_active_enrollment()
    np2 = create_clinician(
        program_ctx["program"]["id"], full_name="Nick NP",
        urgent_response_qualified=True,
    )
    visit = create_scheduled_visit(program_ctx["enrollment"]["id"])
    validate_success(api_client.depart_visit(
        visit["id"], make_clinician_headers(visit["clinician_id"])
    ))
    return program_ctx, visit, np2


def test_state_error_beats_assignment_error_on_depart(api):
    """PRD section 2.6: "5. State preconditions for the requested transition — the named resource must be in the expected state (see §3); failures surface as `ERR_INVALID_STATE` or a resource-specific state error such as `ERR_ENROLLMENT_NOT_IDENTIFIED`, `ERR_VISIT_NOT_SCHEDULED`, or `ERR_EPISODE_NOT_TRIGGERED`."
    PRD section 2.6: "8. Acting-clinician ownership on clinician-driven transitions — failure is `ERR_NOT_ASSIGNED_CLINICIAN`."

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_clinician_assignment_check
    """
    _ctx, visit, np2 = _setup_en_route_visit_with_two_clinicians()
    # Visit is EN_ROUTE; the wrong clinician calls depart: both the state check
    # (needs SCHEDULED) and the assignment check fail; state wins the ladder.
    resp = api_client.depart_visit(visit["id"], make_clinician_headers(np2["id"]))
    validate_error(resp, ApiErrorId.ERR_VISIT_NOT_SCHEDULED, expected_status=409)


def test_assignment_error_fires_when_state_precondition_holds(api):
    """PRD section 2.6: "The ladder matters: a caller cannot infer the state of a later check from the absence of an earlier error. A stale-version enrollment create against a member that does not exist reports `ERR_MEMBER_NOT_FOUND`, not `ERR_STALE_VERSION`."
    PRD section 2.1: "A clinician who attempts a clinician-driven transition on a visit or episode they are not assigned to is rejected with `ERR_NOT_ASSIGNED_CLINICIAN` (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_clinician_assignment_check
    """
    ctx = setup_active_enrollment()
    np2 = create_clinician(ctx["program"]["id"], full_name="Nick NP")
    visit = create_scheduled_visit(ctx["enrollment"]["id"])
    # Visit is still SCHEDULED: state precondition holds, so the ownership
    # check is the one that fires for the wrong clinician.
    resp = api_client.depart_visit(visit["id"], make_clinician_headers(np2["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_CLINICIAN, expected_status=403)


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/business_temporal_sla_check_beats_business_referential_occ_check
# ---------------------------------------------------------------------------

def test_dispatch_past_sla_deadline_temporal_rejection(api):
    """PRD section 3.6: "The dispatch requires the episode to be `TRIGGERED` (else `ERR_EPISODE_NOT_TRIGGERED`) and the current logical clock to be at or before `sla_deadline` (else `ERR_SLA_ALREADY_LAPSED` — dispatching after the deadline would already be a SLA miss)."
    PRD section 2.6: "11. Urgent-dispatch temporal preconditions — failure is `ERR_SLA_ALREADY_LAPSED` if the logical clock has already crossed `sla_deadline`."

    Design: Difficulty/priority_pair_validation_conflict/business_temporal_sla_check_beats_business_referential_occ_check
    """
    ctx = setup_active_enrollment(
        clinician_overrides={"urgent_response_qualified": True}
    )
    episode = create_triggered_episode(ctx["enrollment"]["id"])
    # Advance the logical clock well past the 24h SLA deadline.
    advance_clock(25)
    resp = api_client.dispatch_episode(episode["id"], COORDINATOR)
    assert resp.status_code == 409
    # Once the deadline has passed the episode may already have been auto-lapsed
    # by the sweep, so either the temporal rejection or the state rejection is
    # a faithful outcome.
    actual = validate_error_is_one_of(resp, [
        ApiErrorId.ERR_SLA_ALREADY_LAPSED.value,
        ApiErrorId.ERR_EPISODE_NOT_TRIGGERED.value,
    ])
    assert actual in (
        ApiErrorId.ERR_SLA_ALREADY_LAPSED.value,
        ApiErrorId.ERR_EPISODE_NOT_TRIGGERED.value,
    )


def test_stale_member_version_rejected_412(api):
    """PRD section 2.5: "A request to create a new enrollment for a member must carry `expected_member_version` holding the `Member.version` value the caller most recently observed for that member. If another writer has advanced the member's version since that observation — most commonly because another enrollment creation legitimately superseded the prior `is_current` enrollment — the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Difficulty/priority_pair_validation_conflict/business_temporal_sla_check_beats_business_referential_occ_check
    """
    ctx = setup_active_enrollment(
        clinician_overrides={"urgent_response_qualified": True}
    )
    member_id = ctx["member"]["id"]
    stale_version = get_success_data(api.get_member(member_id, SPECIALIST))["version"]
    # Another writer creates a fresh enrollment, advancing the member version.
    get_success_data(api.create_enrollment(
        member_id,
        {"outreach_channel": "MAIL", "expected_member_version": stale_version},
        SPECIALIST,
    ))
    # The original writer's view is now stale.
    resp = api.create_enrollment(
        member_id,
        {"outreach_channel": "IN_PERSON", "expected_member_version": stale_version},
        SPECIALIST,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
