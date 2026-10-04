"""Difficulty-queue tests: boundary precision (SLA time, clinician capacity) and
temporal interval semantics (half-open visit windows, closed SLA bound)."""
import pytest

from test_helpers import (
    ApiErrorId,
    COORDINATOR,
    advance_clock,
    api_client,
    arrive_episode,
    create_clinician,
    create_dispatched_episode,
    create_scheduled_visit,
    create_triggered_episode,
    dispatch_episode,
    get_success_data,
    make_clinician_headers,
    set_clock,
    setup_active_enrollment,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/urgent_episode_sla_boundary_exact_equality_met_vs_just_past_lapsed
# ---------------------------------------------------------------------------

def _setup_two_dispatched_episodes():
    ctx = setup_active_enrollment(
        clinician_overrides={"urgent_response_qualified": True}
    )
    create_clinician(
        ctx["program"]["id"], full_name="Nick NP", urgent_response_qualified=True
    )
    enr_id = ctx["enrollment"]["id"]
    ep1 = create_dispatched_episode(enr_id, trigger_source="MEMBER_CALL")
    ep2 = create_dispatched_episode(enr_id, trigger_source="PCP_ALERT")
    return ctx, ep1, ep2


def test_sla_met_true_when_on_scene_at_exact_deadline(api):
    """PRD section 3.6: "Arrival moves the episode to `ON_SCENE`, stamps `on_scene_at` with the current logical clock, and computes `sla_met` as the boolean outcome of `on_scene_at` being at or before `sla_deadline`."

    Design: Difficulty/boundary_precision_check/urgent_episode_sla_boundary_exact_equality_met_vs_just_past_lapsed
    """
    _ctx, ep1, _ep2 = _setup_two_dispatched_episodes()
    # Episodes triggered at the default clock 2026-09-01T00:00:00Z with a 24h SLA;
    # arrival at exactly the deadline satisfies the inclusive <= comparison.
    set_clock("2026-09-02T00:00:00Z")
    arrived = validate_success(api.arrive_episode(
        ep1["id"], make_clinician_headers(ep1["dispatched_clinician_id"])
    ))
    assert arrived["on_scene_at"] is not None
    assert arrived["sla_met"] is True, (
        "arrival at exactly sla_deadline must satisfy the at-or-before comparison"
    )


def test_sla_met_false_one_second_past_deadline(api):
    """PRD section 3.6: "Arrival moves the episode to `ON_SCENE`, stamps `on_scene_at` with the current logical clock, and computes `sla_met` as the boolean outcome of `on_scene_at` being at or before `sla_deadline`."

    Design: Difficulty/boundary_precision_check/urgent_episode_sla_boundary_exact_equality_met_vs_just_past_lapsed
    """
    _ctx, _ep1, ep2 = _setup_two_dispatched_episodes()
    # Setting the clock (as opposed to advancing hours) does not run the lapse
    # sweep, so a DISPATCHED episode can still record a late arrival.
    set_clock("2026-09-02T00:00:01Z")
    arrived = validate_success(api.arrive_episode(
        ep2["id"], make_clinician_headers(ep2["dispatched_clinician_id"])
    ))
    assert arrived["sla_met"] is False, (
        "arrival one second past sla_deadline must fail the at-or-before comparison"
    )


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/clinician_capacity_max_daily_visits_equality_blocks_assignment
# ---------------------------------------------------------------------------

def _setup_clinician_at_capacity():
    ctx = setup_active_enrollment(clinician_overrides={"max_daily_visits": 2})
    enr_id = ctx["enrollment"]["id"]
    create_scheduled_visit(enr_id, start="2026-09-02T09:00:00Z", end="2026-09-02T10:00:00Z")
    create_scheduled_visit(enr_id, start="2026-09-02T11:00:00Z", end="2026-09-02T12:00:00Z")
    return ctx


def test_third_visit_rejected_when_clinician_at_capacity(api):
    """PRD section 2.9: "A clinician is only eligible for an assignment if their `home_zip` is in the program's `service_geography_zips` list, their `status` is `ACTIVE`, and their `active_daily_visit_count` is strictly less than `max_daily_visits`. When the eligible pool is empty, the assignment is rejected with `ERR_NO_AVAILABLE_CLINICIAN` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/clinician_capacity_max_daily_visits_equality_blocks_assignment
    """
    ctx = _setup_clinician_at_capacity()
    clinician = get_success_data(api.get_clinician(ctx["np"]["id"], COORDINATOR))
    assert clinician["active_daily_visit_count"] == 2

    resp = api.create_visit(
        {
            "enrollment_id": ctx["enrollment"]["id"],
            "visit_type": "ROUTINE_FOLLOWUP",
            "scheduled_start": "2026-09-02T14:00:00Z",
            "scheduled_end": "2026-09-02T15:00:00Z",
        },
        COORDINATOR,
    )
    validate_error(resp, ApiErrorId.ERR_NO_AVAILABLE_CLINICIAN, expected_status=409)


def test_rejected_over_capacity_visit_is_not_created(api):
    """PRD section 3.5: "An empty pool is rejected with `ERR_NO_AVAILABLE_CLINICIAN`."

    Design: Difficulty/boundary_precision_check/clinician_capacity_max_daily_visits_equality_blocks_assignment
    """
    ctx = _setup_clinician_at_capacity()
    resp = api.create_visit(
        {
            "enrollment_id": ctx["enrollment"]["id"],
            "visit_type": "ROUTINE_FOLLOWUP",
            "scheduled_start": "2026-09-02T14:00:00Z",
            "scheduled_end": "2026-09-02T15:00:00Z",
        },
        COORDINATOR,
    )
    validate_error(resp, ApiErrorId.ERR_NO_AVAILABLE_CLINICIAN, expected_status=409)
    visits = validate_success(api.list_visits(
        COORDINATOR, params={"enrollment_id": ctx["enrollment"]["id"]}
    ))
    assert len(visits) == 2, (
        f"the rejected third visit must not be persisted, got {len(visits)} visits"
    )


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/visit_window_half_open_overlap_on_same_clinician
# ---------------------------------------------------------------------------

def test_overlapping_windows_rejected_on_same_clinician(api):
    """PRD section 2.10: "Two visit windows are considered overlapping when they intersect under half-open interval semantics: a window covering the half-open interval `[scheduled_start, scheduled_end)` overlaps another window on the same clinician if and only if the two half-open intervals share at least one instant."
    PRD section 2.10: "The check runs against every other visit currently in `SCHEDULED`, `EN_ROUTE`, or `IN_PROGRESS` status assigned to the same clinician, and a violation is reported as `ERR_VISIT_TIME_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/visit_window_half_open_overlap_on_same_clinician
    """
    ctx = setup_active_enrollment(clinician_overrides={"max_daily_visits": 10})
    enr_id = ctx["enrollment"]["id"]
    create_scheduled_visit(enr_id, start="2026-09-02T09:00:00Z", end="2026-09-02T10:00:00Z")

    # Interior overlap [09:30, 10:30)
    resp = api.create_visit(
        {
            "enrollment_id": enr_id,
            "visit_type": "ROUTINE_FOLLOWUP",
            "scheduled_start": "2026-09-02T09:30:00Z",
            "scheduled_end": "2026-09-02T10:30:00Z",
        },
        COORDINATOR,
    )
    validate_error(resp, ApiErrorId.ERR_VISIT_TIME_OVERLAP, expected_status=409)

    # Leading-edge overlap [08:00, 09:30)
    resp = api.create_visit(
        {
            "enrollment_id": enr_id,
            "visit_type": "ROUTINE_FOLLOWUP",
            "scheduled_start": "2026-09-02T08:00:00Z",
            "scheduled_end": "2026-09-02T09:30:00Z",
        },
        COORDINATOR,
    )
    validate_error(resp, ApiErrorId.ERR_VISIT_TIME_OVERLAP, expected_status=409)


def test_back_to_back_window_allowed_on_same_clinician(api):
    """PRD section 2.10: "Back-to-back visits — where one's `scheduled_end` equals the other's `scheduled_start` — do not overlap."

    Design: Difficulty/resource_temporal_overlap/visit_window_half_open_overlap_on_same_clinician
    """
    ctx = setup_active_enrollment(clinician_overrides={"max_daily_visits": 10})
    enr_id = ctx["enrollment"]["id"]
    create_scheduled_visit(enr_id, start="2026-09-02T09:00:00Z", end="2026-09-02T10:00:00Z")
    adjacent = validate_success(api.create_visit(
        {
            "enrollment_id": enr_id,
            "visit_type": "ROUTINE_FOLLOWUP",
            "scheduled_start": "2026-09-02T10:00:00Z",
            "scheduled_end": "2026-09-02T11:00:00Z",
        },
        COORDINATOR,
    ), expected_status=201)
    assert adjacent["id"]
    visits = validate_success(api.list_visits(COORDINATOR, params={"enrollment_id": enr_id}))
    assert len(visits) == 2


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/urgent_episode_sla_deadline_uses_closed_interval_temporal_semantics
# ---------------------------------------------------------------------------

def test_dispatch_at_exact_sla_deadline_succeeds(api):
    """PRD section 3.6: "The dispatch requires the episode to be `TRIGGERED` (else `ERR_EPISODE_NOT_TRIGGERED`) and the current logical clock to be at or before `sla_deadline` (else `ERR_SLA_ALREADY_LAPSED` — dispatching after the deadline would already be a SLA miss)."

    Design: Difficulty/resource_temporal_overlap/urgent_episode_sla_deadline_uses_closed_interval_temporal_semantics
    """
    ctx = setup_active_enrollment(
        clinician_overrides={"urgent_response_qualified": True, "max_daily_visits": 10}
    )
    episode = create_triggered_episode(ctx["enrollment"]["id"])
    # Triggered at 2026-09-01T00:00:00Z with a 24h SLA; set the clock to exactly
    # the deadline — the closed at-or-before bound admits this dispatch.
    set_clock("2026-09-02T00:00:00Z")
    dispatched = validate_success(api.dispatch_episode(episode["id"], COORDINATOR))
    assert dispatched["status"] == "DISPATCHED"


def test_dispatch_one_second_past_sla_deadline_rejected(api):
    """PRD section 3.6: "The dispatch requires the episode to be `TRIGGERED` (else `ERR_EPISODE_NOT_TRIGGERED`) and the current logical clock to be at or before `sla_deadline` (else `ERR_SLA_ALREADY_LAPSED` — dispatching after the deadline would already be a SLA miss)."

    Design: Difficulty/resource_temporal_overlap/urgent_episode_sla_deadline_uses_closed_interval_temporal_semantics
    """
    ctx = setup_active_enrollment(
        clinician_overrides={"urgent_response_qualified": True, "max_daily_visits": 10}
    )
    episode = create_triggered_episode(ctx["enrollment"]["id"])
    set_clock("2026-09-02T00:00:01Z")
    resp = api.dispatch_episode(episode["id"], COORDINATOR)
    assert resp.status_code == 409
    validate_error_is_one_of(resp, [
        ApiErrorId.ERR_SLA_ALREADY_LAPSED.value,
        ApiErrorId.ERR_EPISODE_NOT_TRIGGERED.value,
    ])
