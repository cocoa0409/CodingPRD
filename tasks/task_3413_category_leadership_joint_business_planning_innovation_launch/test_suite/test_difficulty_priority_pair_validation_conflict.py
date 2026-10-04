"""Difficulty queue — priority pairs where two validation rules bite at once.

The PRD runs its checks in a fixed pipeline order and reports the first
failure (PRD §2.9): on event lock the plan-activation state check stands ahead
of the fund-sufficiency fiscal check (PRD §3.2), and on launch execution the
phase-gate state check stands ahead of the launch-date temporal check
(PRD §3.5). Each test translates one difficulty-design instance and cites the
PRD rule it pins.
"""
from test_helpers import (
    ApiErrorId,
    assert_innovation_launch,
    assert_promotional_event,
    gate_all_phases,
    set_clock,
    setup_accepted_plan,
    setup_activated_plan,
    validate_error,
    validate_success,
)

_EVENT_PAYLOAD = {
    "name": "Spring Feature",
    "event_type": "FEATURE",
    "start_date": "2027-03-01T00:00:00Z",
    "end_date": "2027-03-10T00:00:00Z",
    "discount_depth_pct": 25,
}

_LAUNCH_PAYLOAD = {
    "product_name": "UltraTabs",
    "pack_family": "tabs",
    "launch_date": "2027-06-01T00:00:00Z",
    "total_trade_budget_cents": 500000,
}


def test_lock_on_unactivated_plan_reports_state_not_funds(api, manufacturer_planner_headers):
    """PRD §3.2: "When the `ManufacturerPlanner` locks a `PENCILED` event, the plan must first be `ACTIVATED` — locking against a plan in any other state fails with `ERR_PLAN_NOT_ACTIVATED` — and then the server computes the event's funding estimate."
    PRD §2.9: "The server evaluates checks in a fixed priority order and reports the first failure it encounters; a lower-priority problem is masked until every higher-priority problem is resolved."

    On an ACCEPTED (never ACTIVATED) plan no fund exists, so the fiscal floor
    would also fail — but the activation state check is evaluated first and
    ERR_PLAN_NOT_ACTIVATED wins; the event stays PENCILED.

    Design: Difficulty/priority_pair_validation_conflict/lock_event_state_beats_fiscal
    """
    scenario = setup_accepted_plan()
    plan_id = scenario["plan"]["id"]
    event = validate_success(
        api.create_event(plan_id, dict(_EVENT_PAYLOAD), manufacturer_planner_headers), 201
    )
    assert_promotional_event(event)

    validate_error(api.lock_event(event["id"], manufacturer_planner_headers), ApiErrorId.ERR_PLAN_NOT_ACTIVATED)

    events = validate_success(api.list_events(plan_id, manufacturer_planner_headers), 200)
    assert len(events) == 1
    assert events[0]["status"] == "PENCILED", (
        f"the rejected lock must not move the event, got {events[0]['status']}"
    )
    assert events[0]["estimated_cost_cents"] is None


def test_lock_after_activation_unmasks_the_fiscal_floor(api, manufacturer_planner_headers):
    """PRD §3.2: "When the `ManufacturerPlanner` locks a `PENCILED` event, the plan must first be `ACTIVATED` — locking against a plan in any other state fails with `ERR_PLAN_NOT_ACTIVATED` — and then the server computes the event's funding estimate."
    PRD §3.2: "if it exceeds the plan fund's `event_available_cents` at that instant, the lock is refused with `ERR_INSUFFICIENT_FUNDS` (HTTP 422)."

    With the state gate resolved by activation, the identical lock now reaches
    the fiscal check: the freshly created fund holds zero, the estimate
    exceeds it, and ERR_INSUFFICIENT_FUNDS fires — proving the fiscal rule was
    a live loser behind the state error, not an absent one.

    Design: Difficulty/priority_pair_validation_conflict/lock_event_state_beats_fiscal
    """
    scenario = setup_accepted_plan()
    plan_id = scenario["plan"]["id"]
    event = validate_success(
        api.create_event(plan_id, dict(_EVENT_PAYLOAD), manufacturer_planner_headers), 201
    )
    validate_error(api.lock_event(event["id"], manufacturer_planner_headers), ApiErrorId.ERR_PLAN_NOT_ACTIVATED)

    validate_success(
        api.activate_plan(plan_id, {"accrual_rate_pct": 4, "edlp_split_pct": 60}, manufacturer_planner_headers),
        200,
    )
    validate_error(api.lock_event(event["id"], manufacturer_planner_headers), ApiErrorId.ERR_INSUFFICIENT_FUNDS)

    events = validate_success(api.list_events(plan_id, manufacturer_planner_headers), 200)
    assert len(events) == 1
    assert events[0]["status"] == "PENCILED"


def test_launch_with_unpassed_gates_reports_gates_not_date(api, manufacturer_planner_headers):
    """PRD §3.5: "The state check comes first: every child phase must stand at `GATE_PASSED`, and a launch attempted with any gate unpassed fails with `ERR_PHASE_GATES_INCOMPLETE` (HTTP 409) regardless of the calendar."
    PRD §2.9: "Executing a launch checks the phase gates before it checks the calendar: a launch with an unpassed gate reports `ERR_PHASE_GATES_INCOMPLETE` even if its date has also not arrived, and only a fully gated launch can ever see `ERR_LAUNCH_DATE_NOT_REACHED`."

    All four phases still PENDING and the logical clock still before the
    launch date: the gate error wins; the launch stays PLANNING.

    Design: Difficulty/priority_pair_validation_conflict/launch_state_beats_temporal
    """
    scenario = setup_activated_plan()
    launch = validate_success(
        api.create_launch(scenario["plan"]["id"], dict(_LAUNCH_PAYLOAD), manufacturer_planner_headers),
        201,
    )

    validate_error(api.execute_launch(launch["id"], manufacturer_planner_headers), ApiErrorId.ERR_PHASE_GATES_INCOMPLETE)

    refreshed = validate_success(api.get_launch(launch["id"], manufacturer_planner_headers), 200)
    assert_innovation_launch(refreshed)
    assert refreshed["status"] == "PLANNING", (
        f"the rejected launch must not move, got {refreshed['status']}"
    )
    assert refreshed["launched_at"] is None


def test_fully_gated_launch_then_sees_the_date_check(api, manufacturer_planner_headers):
    """PRD §3.5: "Only then does the temporal check apply: the logical clock must have reached the `launch_date`, else the attempt fails with `ERR_LAUNCH_DATE_NOT_REACHED` (HTTP 422)."
    PRD §2.9: "Executing a launch checks the phase gates before it checks the calendar: a launch with an unpassed gate reports `ERR_PHASE_GATES_INCOMPLETE` even if its date has also not arrived, and only a fully gated launch can ever see `ERR_LAUNCH_DATE_NOT_REACHED`."
    PRD §3.5: "A successful execution moves the launch `PLANNING → LAUNCHED`, stamps `launched_at` from the logical clock, and increments the launch's `version`."

    With every phase GATE_PASSED but the clock still at its 2026-09-01 start,
    the temporal loser surfaces; advancing the clock to the launch date then
    lets the very same launch execute.

    Design: Difficulty/priority_pair_validation_conflict/launch_state_beats_temporal
    """
    scenario = setup_activated_plan()
    launch = validate_success(
        api.create_launch(scenario["plan"]["id"], dict(_LAUNCH_PAYLOAD), manufacturer_planner_headers),
        201,
    )
    gate_all_phases(launch["id"])

    validate_error(api.execute_launch(launch["id"], manufacturer_planner_headers), ApiErrorId.ERR_LAUNCH_DATE_NOT_REACHED)

    set_clock("2027-06-01T00:00:00Z")
    launched = validate_success(api.execute_launch(launch["id"], manufacturer_planner_headers), 200)
    assert_innovation_launch(launched)
    assert launched["status"] == "LAUNCHED"
    assert launched["launched_at"] is not None
