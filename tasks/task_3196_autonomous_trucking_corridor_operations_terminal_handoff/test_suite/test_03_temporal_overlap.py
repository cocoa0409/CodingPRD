"""Apron geometry and remote-support monitoring overlap arithmetic."""
import pytest

from prd_bench_local_runner.testing import validate_success, validate_error

from test_helpers import (
    api_client, ApiErrorId, TEST_USERS,
    setup_launched_corridor, create_run, request_window, submit_run, dispatch_run,
    make_prospect, create_remote_support_payload,
)


def _dispatch_ready_run(**kwargs):
    stack = setup_launched_corridor(**kwargs)
    run = create_run(stack)
    window = request_window(stack["origin"]["id"], run["id"], 500, 560,
                            buffer_minutes=25)
    submit_run(run["id"])
    run = dispatch_run(run["id"])
    window = validate_success(api_client.get_service_window(
        stack["origin"]["id"], window["id"], TEST_USERS["any_headers"]))
    return stack, run, window


# ─── resource_temporal_overlap / apron_hold_half_open_with_buffer ───────────

def test_touching_apron_windows_do_not_occupy(api, any_headers):
    """PRD §2.7: "A new window whose `window_start_minute` equals an existing
    window's effective end — that is, its end minute plus its buffer — is
    permitted, but any window that would share even a single minute with an
    existing approved or in-service window is refused with `ERR_APRON_OVERLAP`".

    An approved window 500..560 with buffer 25 occupies [500, 585), so a second
    window starting at 585 is permitted.

    Design: Difficulty/resource_temporal_overlap/apron_hold_half_open_with_buffer
    """
    stack, run, window_a = _dispatch_ready_run()
    window_b = request_window(stack["origin"]["id"], run["id"], 585, 605,
                              service_type="HANDOFF_INBOUND", handoff_duration_minutes=10)
    data = validate_success(api_client.approve_service_window(
        window_b["id"], TEST_USERS["terminal_manager_headers"]))
    assert data["window_status"] == "APPROVED", \
        "585 equals the approved window's effective end of 585 and is a touching window"


def test_apron_window_sharing_a_minute_is_refused(api, any_headers):
    """PRD §2.7: "any window that would share even a single minute with an
    existing approved or in-service window is refused with `ERR_APRON_OVERLAP`
    (409)".

    Design: Difficulty/resource_temporal_overlap/apron_hold_half_open_with_buffer
    """
    stack, run, window_a = _dispatch_ready_run()
    window_b = request_window(stack["origin"]["id"], run["id"], 584, 605,
                              service_type="HANDOFF_INBOUND", handoff_duration_minutes=10)
    resp = api_client.approve_service_window(window_b["id"], TEST_USERS["terminal_manager_headers"])
    validate_error(resp, ApiErrorId.ERR_APRON_OVERLAP, expected_status=409)


# ─── resource_temporal_overlap / remote_support_monitoring_buffer_expansion ─

def test_monitoring_window_clears_under_the_exact_interval_rule(api, any_headers):
    """PRD §2.7: "Under `GEOFENCE_ONLY` the collision test runs on the exact
    intervals after the apron buffer has been added."
    PRD §3.9: "A scheduled window begins with its `assignment_status` at
    `SCHEDULED`".

    A window 01:15Z..01:25Z scheduled 15 minutes after a 00:00Z..01:00Z window
    clears under GEOFENCE_ONLY.

    Design: Difficulty/resource_temporal_overlap/remote_support_monitoring_buffer_expansion
    """
    stack = setup_launched_corridor()
    run_a = create_run(stack)
    run_b = create_run(stack, window_start_epoch_day=13, window_end_epoch_day=15)
    operator = make_prospect(stack["origin"]["id"], "Mira Okafor", "REMOTE_SUPPORT")
    support = make_prospect(stack["origin"]["id"], "Sam Delgado", "REMOTE_SUPPORT")
    api_client.create_remote_support_assignment(
        create_remote_support_payload(stack["corridor"]["id"], run_a["id"],
                                      operator["id"], support["id"],
                                      monitoring_start_at="2026-10-01T00:00:00Z",
                                      monitoring_end_at="2026-10-01T01:00:00Z",
                                      geofence_type="GEOFENCE_ONLY"),
        TEST_USERS["remote_support_supervisor_headers"])
    data = validate_success(api_client.create_remote_support_assignment(
        create_remote_support_payload(stack["corridor"]["id"], run_b["id"],
                                      operator["id"], support["id"],
                                      monitoring_start_at="2026-10-01T01:15:00Z",
                                      monitoring_end_at="2026-10-01T01:25:00Z",
                                      geofence_type="GEOFENCE_ONLY"),
        TEST_USERS["remote_support_supervisor_headers"]), expected_status=201)
    assert data["assignment_status"] == "SCHEDULED"


def test_buffered_geofence_expands_and_refuses_the_same_window(api, any_headers):
    """PRD §2.7: "Under `GEOFENCE_PLUS_BUFFER` the interval is first expanded
    multiplicatively by 1.5 before screening, so a monitoring window that clears
    under the exact test can still be rejected under the buffered one."

    The new 01:00Z..01:10Z window touches the existing 00:00Z..01:00Z window and
    clears the exact test, but the 01:00Z end expands to 01:30Z, swallowing it.

    Design: Difficulty/resource_temporal_overlap/remote_support_monitoring_buffer_expansion
    """
    stack = setup_launched_corridor()
    run_a = create_run(stack)
    run_b = create_run(stack, window_start_epoch_day=13, window_end_epoch_day=15)
    operator = make_prospect(stack["origin"]["id"], "Mira Okafor", "REMOTE_SUPPORT")
    support = make_prospect(stack["origin"]["id"], "Sam Delgado", "REMOTE_SUPPORT")
    api_client.create_remote_support_assignment(
        create_remote_support_payload(stack["corridor"]["id"], run_a["id"],
                                      operator["id"], support["id"],
                                      monitoring_start_at="2026-10-01T00:00:00Z",
                                      monitoring_end_at="2026-10-01T01:00:00Z",
                                      geofence_type="GEOFENCE_ONLY"),
        TEST_USERS["remote_support_supervisor_headers"])
    resp = api_client.create_remote_support_assignment(
        create_remote_support_payload(stack["corridor"]["id"], run_b["id"],
                                      operator["id"], support["id"],
                                      monitoring_start_at="2026-10-01T01:00:00Z",
                                      monitoring_end_at="2026-10-01T01:10:00Z",
                                      geofence_type="GEOFENCE_PLUS_BUFFER"),
        TEST_USERS["remote_support_supervisor_headers"])
    validate_error(resp, ApiErrorId.ERR_MONITOR_OVERLAP, expected_status=409)


# ─── boundary_precision_check / apron_capacity_reached_exactly_is_accepted ──

def test_apron_capacity_reached_exactly_is_accepted(api, any_headers):
    """PRD §3.9: "the terminal's `reserved_apron_units` plus the new window's
    length with its buffer must not exceed the terminal's `apron_capacity`, or
    the approval is refused with `ERR_APRON_CAPACITY_EXCEEDED` (409)".

    With apron_capacity 2 and one approved 75-minute window (1.25 units), a
    second window of exactly 45 minutes brings the reading to exactly 2.00 and
    is accepted — the rule is inclusive at the capacity value.

    Design: Difficulty/boundary_precision_check/apron_capacity_reached_exactly_is_accepted
    """
    stack = setup_launched_corridor(origin_capacity=2)
    run_a = create_run(stack, window_start_epoch_day=10, window_end_epoch_day=12)
    request_window(stack["origin"]["id"], run_a["id"], 100, 175,
                   handoff_duration_minutes=20, buffer_minutes=0)
    submit_run(run_a["id"])
    dispatch_run(run_a["id"])
    run_b = create_run(stack, window_start_epoch_day=14, window_end_epoch_day=16)
    submit_run(run_b["id"])
    dispatch_run(run_b["id"])
    window_b = request_window(stack["origin"]["id"], run_b["id"], 500, 545,
                              service_type="HANDOFF_INBOUND", handoff_duration_minutes=20)
    data = validate_success(api_client.approve_service_window(
        window_b["id"], TEST_USERS["terminal_manager_headers"]))
    assert data["window_status"] == "APPROVED"
    terminal = validate_success(api_client.get_terminal(stack["origin"]["id"], any_headers))
    assert terminal["reserved_apron_units"] == pytest.approx(2.0, abs=0.01), \
        "occupancy exactly equals apron_capacity and the capacity rule is inclusive"


def test_apron_capacity_overshoot_is_refused(api, any_headers):
    """PRD §3.9: "an approval that would push occupancy past capacity is refused
    with `ERR_APRON_CAPACITY_EXCEEDED` (409)".

    A third 30-minute window would take the reading to 2.50, past the capacity
    of 2.

    Design: Difficulty/boundary_precision_check/apron_capacity_reached_exactly_is_accepted
    """
    stack = setup_launched_corridor(origin_capacity=2)
    run_a = create_run(stack, window_start_epoch_day=10, window_end_epoch_day=12)
    request_window(stack["origin"]["id"], run_a["id"], 100, 175,
                   handoff_duration_minutes=20)
    submit_run(run_a["id"])
    dispatch_run(run_a["id"])
    run_b = create_run(stack, window_start_epoch_day=14, window_end_epoch_day=16)
    submit_run(run_b["id"])
    dispatch_run(run_b["id"])
    window_b = request_window(stack["origin"]["id"], run_b["id"], 500, 545,
                              service_type="HANDOFF_INBOUND", handoff_duration_minutes=20)
    api_client.approve_service_window(window_b["id"], TEST_USERS["terminal_manager_headers"])
    run_c = create_run(stack, window_start_epoch_day=18, window_end_epoch_day=20)
    submit_run(run_c["id"])
    dispatch_run(run_c["id"])
    window_c = request_window(stack["origin"]["id"], run_c["id"], 900, 930,
                              service_type="HANDOFF_INBOUND", handoff_duration_minutes=20)
    resp = api_client.approve_service_window(window_c["id"], TEST_USERS["terminal_manager_headers"])
    validate_error(resp, ApiErrorId.ERR_APRON_CAPACITY_EXCEEDED, expected_status=409)


# ─── corner: cross_cutting/cascading_side_effects_move_apron_windows_on_requeue

def test_requeue_reverts_approved_windows_and_empties_occupancy(api, any_headers):
    """PRD §3.3: "Requeueing returns every `APPROVED` apron window on the run to
    `REQUESTED`, recomputes the owning terminal's `reserved_apron_units`
    downward".
    PRD §3.3: "A `DISPATCH_READY` run can be requeued to `READINESS_PENDING`,
    and the step is only available while the corridor posture is `RESTRICTED`".

    The corridor is driven to RESTRICTED before the requeue is exercised.

    Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_move_apron_windows_on_run_plan_requeue
    """
    stack, run, window = _dispatch_ready_run(weather_profile="HIGH_WIND",
                                             weather_risk_score=55)
    corridor = validate_success(api_client.get_corridor(stack["corridor"]["id"], any_headers))
    assert corridor["posture"] == "RESTRICTED"
    api_client.requeue_run_plan(run["id"], TEST_USERS["carrier_dispatcher_headers"])
    win = validate_success(api_client.get_service_window(
        stack["origin"]["id"], window["id"], any_headers))
    terminal = validate_success(api_client.get_terminal(stack["origin"]["id"], any_headers))
    assert win["window_status"] == "REQUESTED"
    assert terminal["reserved_apron_units"] == 0


# ─── corner: rbac/carrier_dispatcher_cannot_approve_an_apron_window ────────

def test_carrier_dispatcher_cannot_approve_an_apron_window(api, any_headers):
    """PRD §2.1: "A request whose role is well-formed but not permitted for the
    operation it targets is refused with `ERR_UNAUTHORIZED` and an HTTP 403."

    Apron approval is exclusive to the TerminalManager role.

    Design: Corner/rbac/carrier_dispatcher_cannot_approve_an_apron_window
    """
    stack, run, window = _dispatch_ready_run()
    window_b = request_window(stack["origin"]["id"], run["id"], 585, 605,
                              service_type="HANDOFF_INBOUND", handoff_duration_minutes=10)
    resp = api_client.approve_service_window(window_b["id"],
                                             TEST_USERS["carrier_dispatcher_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)
    win = validate_success(api_client.get_service_window(
        stack["origin"]["id"], window_b["id"], any_headers))
    assert win["window_status"] == "REQUESTED"
    data = validate_success(api_client.approve_service_window(
        window_b["id"], TEST_USERS["terminal_manager_headers"]))
    assert data["window_status"] == "APPROVED"


# ─── corner: errors/stale_run_plan_version_on_dispatch_ready ────────────────

def test_stale_run_plan_version_on_dispatch_ready_is_refused(api, any_headers,
                                                             carrier_dispatcher_headers):
    """PRD §3.3: "The request must carry `expected_run_plan_version`; a run plan
    whose `version` has advanced since the dispatcher last read it — because an
    apron window approval or a rate recalculation has already touched the plan —
    is refused with `ERR_STALE_VERSION` at HTTP 412."
    PRD §2.9: "The rejection is a pure equality test against the current
    version".

    Design: Corner/errors/stale_run_plan_version_on_dispatch_ready_returns_precondition_failed
    """
    stack = setup_launched_corridor()
    run = create_run(stack)
    submit_run(run["id"])
    run_v = validate_success(api_client.get_run_plan(run["id"], any_headers))["version"]
    validate_success(api_client.dispatch_ready_run_plan(
        run["id"], carrier_dispatcher_headers, {"expected_run_plan_version": run_v}))
    resp = api_client.dispatch_ready_run_plan(
        run["id"], carrier_dispatcher_headers, {"expected_run_plan_version": run_v})
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    data = validate_success(api_client.get_run_plan(run["id"], any_headers))
    assert data["run_status"] == "DISPATCH_READY"