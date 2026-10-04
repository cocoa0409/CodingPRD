"""Launch gating (state, weather, window), separation sequencing, deployment
bubble-up, and anomaly-gated re-execution."""
from test_helpers import (
    ApiErrorId,
    confirm_assignment,
    get_assignment,
    get_contract,
    get_mission,
    launch_mission,
    list_separation_events,
    publish_exclusion_window,
    review_assignment,
    set_clock,
    setup_launched_mission,
    setup_locked_mission,
    setup_range_scheduled_mission,
    validate_error,
    validate_success,
    verify_assignment,
    api_client,
)
from test_helpers.test_users import TEST_USERS

MOPS = TEST_USERS["mission_ops_headers"]
SAFETY = TEST_USERS["safety_headers"]


def _setup_locked_with_weather_hold():
    """MANIFEST_LOCKED mission (no slot ever confirmed) plus a WEATHER hold on
    CCAFS; clock advanced into the hold."""
    ctx = setup_locked_mission()
    publish_exclusion_window(
        scope_type="RANGE", scope_value="CCAFS", kind="WEATHER",
        start_utc="2026-10-15T00:00:00Z", end_utc="2026-10-16T00:00:00Z",
    )
    set_clock("2026-10-15T12:00:00Z")
    return ctx


def test_launch_in_wrong_state_reports_state_error_not_weather(api):
    """PRD §3.6: "The gates run in pipeline order. State comes first: a mission
    not in `RANGE_SCHEDULED` is rejected with `ERR_INVALID_STATE`."
    PRD §2.6: "Every request passes through the same validation pipeline, and the
    stages run in a fixed order: a failure at an earlier stage masks every later
    check, so the response always carries the first applicable rejection."

    Design: Difficulty/priority_pair_validation_conflict/launch_in_wrong_state_with_weather_hold_reports_state_error
    """
    ctx = _setup_locked_with_weather_hold()
    resp = api_client.launch_mission(ctx["mission"]["id"], MOPS)
    err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert err["error_id"] != "ERR_WEATHER_HOLD", (
        "the priority-7 state check fires even though the clock is inside the WEATHER window"
    )


def test_rejected_launch_leaves_mission_and_events_untouched(api):
    """PRD §3.6: "State comes first: a mission not in `RANGE_SCHEDULED` is
    rejected with `ERR_INVALID_STATE`."
    PRD §3.6: "The system then creates one separation event per assignment that
    is `INTEGRATED` at launch"

    Design: Difficulty/priority_pair_validation_conflict/launch_in_wrong_state_with_weather_hold_reports_state_error
    """
    ctx = _setup_locked_with_weather_hold()
    resp = api_client.launch_mission(ctx["mission"]["id"], MOPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_mission(ctx["mission"]["id"])["status"] == "MANIFEST_LOCKED"
    events = validate_success(
        api_client.list_separation_events(MOPS, params={"mission_id": ctx["mission"]["id"]}),
        200,
    )
    assert events == [], "a rejected launch creates no separation events"


def test_launch_at_weather_window_start_is_blocked(api):
    """PRD §3.5: "Every exclusion window is the half-open interval from
    `start_utc` (inclusive) to `end_utc` (exclusive), with `end_utc` strictly
    after `start_utc`: an instant exactly at `start_utc` falls inside the
    window, while an instant exactly at `end_utc` is already clear of it."
    PRD §3.6: "Safety comes next: any `WEATHER` exclusion window scoped to the
    confirmed slot's `range_code` whose `start_utc` is at or before t and whose
    `end_utc` is strictly after t holds the launch with `ERR_WEATHER_HOLD`
    (HTTP 422)"

    Design: Difficulty/boundary_precision_check/launch_at_weather_window_start_blocked_at_window_end_allowed
    """
    ctx = setup_range_scheduled_mission()
    publish_exclusion_window(
        scope_type="RANGE", scope_value="CCAFS", kind="WEATHER",
        start_utc="2026-10-15T12:00:00Z", end_utc="2026-10-15T13:00:00Z",
    )
    set_clock("2026-10-15T12:00:00Z")
    resp = api_client.launch_mission(ctx["mission"]["id"], MOPS)
    validate_error(resp, ApiErrorId.ERR_WEATHER_HOLD)
    assert get_mission(ctx["mission"]["id"])["status"] == "RANGE_SCHEDULED"


def test_launch_at_weather_window_end_is_clear(api):
    """PRD §3.5: "an instant exactly at `start_utc` falls inside the window,
    while an instant exactly at `end_utc` is already clear of it."
    PRD §3.6: "The first event in this order is commanded at an `offset_seconds`
    of zero"

    Design: Difficulty/boundary_precision_check/launch_at_weather_window_start_blocked_at_window_end_allowed
    """
    ctx = setup_range_scheduled_mission()
    publish_exclusion_window(
        scope_type="RANGE", scope_value="CCAFS", kind="WEATHER",
        start_utc="2026-10-15T12:00:00Z", end_utc="2026-10-15T13:00:00Z",
    )
    set_clock("2026-10-15T12:00:00Z")
    blocked = api_client.launch_mission(ctx["mission"]["id"], MOPS)
    validate_error(blocked, ApiErrorId.ERR_WEATHER_HOLD)

    set_clock("2026-10-15T13:00:00Z")
    launched = launch_mission(ctx["mission"]["id"])
    assert launched["status"] == "LAUNCHED"
    slots = validate_success(
        api_client.list_mission_range_slots(ctx["mission"]["id"], MOPS), 200
    )
    assert slots[0]["status"] == "CONSUMED"
    events = list_separation_events(ctx["mission"]["id"])
    assert len(events) == 1
    assert events[0]["sequence_index"] == 0
    assert events[0]["offset_seconds"] == 0
    assert events[0]["status"] == "PLANNED"


def test_launch_before_window_open_rejected(api):
    """PRD §3.6: "Temporal containment comes last: t must fall within the
    mission's window on closed bounds and within the confirmed slot's window on
    closed bounds, either failure producing `ERR_LAUNCH_WINDOW_VIOLATION`
    (422)."

    Design: Corner/errors/launch_before_window_open_rejected
    """
    ctx = setup_range_scheduled_mission()
    set_clock("2026-10-09T00:00:00Z")
    resp = api_client.launch_mission(ctx["mission"]["id"], MOPS)
    validate_error(resp, ApiErrorId.ERR_LAUNCH_WINDOW_VIOLATION)
    assert get_mission(ctx["mission"]["id"])["status"] == "RANGE_SCHEDULED"
    slots = validate_success(
        api_client.list_mission_range_slots(ctx["mission"]["id"], MOPS), 200
    )
    assert slots[0]["status"] == "CONFIRMED"
    events = validate_success(
        api_client.list_separation_events(MOPS, params={"mission_id": ctx["mission"]["id"]}),
        200,
    )
    assert events == []


def test_deployment_success_bubbles_contract_fulfilled_and_mission_completed(api):
    """PRD §3.6: "Reporting `EXECUTED` against a `PLANNED` event cascades
    upward: the event's assignment moves from `INTEGRATED` to `DEPLOYED` and its
    payload from `MANIFESTED` to `DEPLOYED`, each incrementing its `version`;
    and the bubble-up continues — if every payload of the assignment's contract
    is now `DEPLOYED`, the contract moves from `MANIFESTED` to `FULFILLED` with
    a version increment, and if every separation event of the mission has
    reached `EXECUTED`, the mission moves from `LAUNCHED` to `COMPLETED`, again
    with a version increment."

    Design: Corner/state_machines/deployment_success_bubbles_contract_fulfilled_and_mission_completed
    """
    ctx = setup_launched_mission()
    ev1 = ctx["separation_events"][0]
    resp = api_client.report_separation_outcome(ev1["id"], {"outcome": "EXECUTED"}, MOPS)
    executed = validate_success(resp, 200)
    assert executed["status"] == "EXECUTED"
    assert get_assignment(ctx["assignments"][0]["id"])["status"] == "DEPLOYED"
    payloads = validate_success(
        api_client.list_contract_payloads(ctx["contract"]["id"], MOPS), 200
    )
    assert payloads[0]["status"] == "DEPLOYED"
    assert get_contract(ctx["contract"]["id"])["status"] == "FULFILLED"
    assert get_mission(ctx["mission"]["id"])["status"] == "COMPLETED"

    repeat = api_client.report_separation_outcome(ev1["id"], {"outcome": "EXECUTED"}, MOPS)
    validate_error(repeat, ApiErrorId.ERR_INVALID_STATE)


def test_anomalous_event_reexecution_gated_by_anomaly_resolution(api):
    """PRD §3.6: "An event in `ANOMALOUS` may later be reported `EXECUTED`, but
    only once every anomaly of the mission stands in `RESOLVED`, else the report
    is rejected with `ERR_ANOMALIES_UNRESOLVED` (HTTP 409); a successful late
    execution then runs the same deployment and bubble-up effects as a clean
    one."
    PRD §3.6: "An anomalous report creates an anomaly record in `OPEN` status,
    its `mission_id` copied from the separation event and its `category` and
    `severity` taken from the report."

    Design: Corner/state_machines/anomalous_event_reexecution_gated_by_anomaly_resolution
    """
    ctx = setup_launched_mission()
    ev1 = ctx["separation_events"][0]
    resp = api_client.report_separation_outcome(
        ev1["id"],
        {"outcome": "ANOMALOUS", "anomaly_category": "SEPARATION", "anomaly_severity": "HIGH"},
        MOPS,
    )
    validate_success(resp, 200)
    anomalies = validate_success(
        api_client.list_mission_anomalies(ctx["mission"]["id"], MOPS), 200
    )
    assert len(anomalies) == 1
    an1 = anomalies[0]
    assert an1["status"] == "OPEN"
    assert an1["category"] == "SEPARATION" and an1["severity"] == "HIGH"
    assert an1["mission_id"] == ctx["mission"]["id"]

    blocked = api_client.report_separation_outcome(ev1["id"], {"outcome": "EXECUTED"}, MOPS)
    validate_error(blocked, ApiErrorId.ERR_ANOMALIES_UNRESOLVED)

    api_client.transition_anomaly(an1["id"], {"to_state": "UNDER_INVESTIGATION"}, MOPS)
    api_client.transition_anomaly(an1["id"], {"to_state": "ESCALATED"}, SAFETY)
    api_client.transition_anomaly(an1["id"], {"to_state": "UNDER_INVESTIGATION"}, SAFETY)
    resolved = validate_success(
        api_client.transition_anomaly(
            an1["id"],
            {"to_state": "RESOLVED", "disposition": "NOMINAL",
             "resolution_notes": "telemetry gap only; separation confirmed by ground track"},
            MOPS,
        ),
        200,
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["disposition"] == "NOMINAL"

    retry = api_client.report_separation_outcome(ev1["id"], {"outcome": "EXECUTED"}, MOPS)
    executed = validate_success(retry, 200)
    assert executed["status"] == "EXECUTED"
    assert get_mission(ctx["mission"]["id"])["status"] == "COMPLETED"


def test_separation_sequence_orders_stack_desc_with_same_interface_gap(api):
    """PRD §3.6: "assignments are ordered by their dispenser port's
    `stack_position` descending — the tip of the stack deploys first — with ties
    broken by the assignment's `created_at` in ascending order; identifiers are
    never used for ordering. The first event in this order is commanded at an
    `offset_seconds` of zero, and each subsequent event's `offset_seconds`
    equals the previous event's offset plus a base gap of 30 seconds, plus an
    additional 15 seconds whenever two consecutive payloads share the same
    `interface_class`."

    Design: Corner/calculations/separation_sequence_orders_stack_desc_with_same_interface_gap
    """
    ctx = setup_launched_mission(
        port_specs=[
            {},
            {"port_code": "DSP-B", "stack_position": 3, "max_mass_kg": 100,
             "supported_interface_classes": ["CUBESAT"]},
            {"port_code": "DSP-C", "stack_position": 2, "max_mass_kg": 100,
             "supported_interface_classes": ["RING_24", "CUBESAT"]},
        ],
        payload_specs=[
            {"payload_name": "PL_A", "mass_kg": 100, "volume_m3": 2.0},
            {"payload_name": "PL_B", "mass_kg": 40, "volume_m3": 0.5,
             "interface_class": "CUBESAT"},
            {"payload_name": "PL_C", "mass_kg": 30, "volume_m3": 0.4,
             "interface_class": "CUBESAT"},
        ],
    )
    a_a, a_b, a_c = [a["id"] for a in ctx["assignments"]]
    events = list_separation_events(ctx["mission"]["id"])
    assert len(events) == 3, "one event per INTEGRATED assignment"
    assert [e["assignment_id"] for e in events] == [a_a, a_b, a_c], (
        "stack_position DESC: tip of the stack deploys first"
    )
    assert events[0]["sequence_index"] == 0 and events[0]["offset_seconds"] == 0
    assert events[1]["sequence_index"] == 1 and events[1]["offset_seconds"] == 30, (
        "base gap 30: RING_15 predecessor differs from CUBESAT"
    )
    assert events[2]["sequence_index"] == 2 and events[2]["offset_seconds"] == 75, (
        "30 base + 15 same-interface gap: events 1 and 2 are both CUBESAT"
    )
    for event in events:
        assert event["status"] == "PLANNED"
