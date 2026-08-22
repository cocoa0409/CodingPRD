"""Interval geometry: the buffered half-open equipment test, the bare closed
agent test, the closed service-hold test and the bank window."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_certified_agent,
    create_flight_bank,
    create_gse_unit,
    create_open_station,
    create_turn,
    get_agent,
    get_flight_bank,
    get_gse_unit,
    get_turn,
    get_turn_resource,
    make_duty_officer_headers,
    schedule_service_hold,
    validate_error,
    validate_success,
)


def api_create(payload):
    """Create an occupation with an explicitly chosen expected_turn_version."""
    return api_client.create_turn_resource(payload, make_duty_officer_headers())


def _gse_payload(turn, gse_unit_id, window_start, window_end):
    return {"turn_id": turn["id"], "resource_kind": "GSE",
            "gse_unit_id": gse_unit_id, "window_start": window_start,
            "window_end": window_end,
            "expected_turn_version": turn["version"]}


def _agent_payload(turn, agent_id, window_start, window_end):
    return {"turn_id": turn["id"], "resource_kind": "AGENT",
            "agent_id": agent_id, "role_on_turn": "RAMP",
            "window_start": window_start, "window_end": window_end,
            "expected_turn_version": turn["version"]}


# ---------------------------------------------------------------------------
# Queue A: resource_temporal_overlap / gse_buffered_half_open_interval_adjacency
# ---------------------------------------------------------------------------

def _setup_tug_with_one_occupation():
    """TUG-01 already carries [06:00, 06:20) at a station whose repositioning
    buffer is 20 minutes."""
    station = create_open_station(gse_reposition_buffer_minutes=20)
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    gse = create_gse_unit(station["id"], condition_score=95,
                          service_interval_cycles=25, cycles_since_service=0)
    first = validate_success(api_create(
        _gse_payload(turn, gse["id"], "2026-04-10T06:00:00Z",
                     "2026-04-10T06:20:00Z")), 201)
    return station, get_turn(turn["id"]), gse, first



def test_equipment_occupation_inside_the_repositioning_buffer_conflicts(api):
    """PRD §3.6: "A proposed occupation conflicts with an existing occupation
    on the same unit — considering only rows whose `status` is `RESERVED` or
    `COMMITTED`, since released and cancelled rows never conflict — when the
    proposed start is strictly earlier than the existing end plus the buffer
    **and** the existing start is strictly earlier than the proposed end plus
    the buffer."
    PRD §3.1: "`gse_reposition_buffer_minutes` is the repositioning time
    appended to the end of every equipment occupation before that unit may be
    occupied again; it defaults to 20 and may not be negative."

    Design: Difficulty/resource_temporal_overlap/gse_buffered_half_open_interval_adjacency
    """
    _station, turn, gse, _first = _setup_tug_with_one_occupation()

    resp = api_create(_gse_payload(turn, gse["id"], "2026-04-10T06:39:00Z",
                                   "2026-04-10T07:00:00Z"))
    validate_error(resp, ApiErrorId.ERR_GSE_WINDOW_CONFLICT, 409)
    assert get_gse_unit(gse["id"])["committed_occupation_minutes"] == 20


def test_equipment_occupation_exactly_one_buffer_later_is_admissible(api):
    """PRD §3.6: "Both comparisons are strict, which means an occupation that
    begins exactly the buffer's worth of minutes after another one ends is
    admissible."
    PRD §3.7: "That figure is immediately added to the relevant ledger — a
    unit's `committed_occupation_minutes` for an equipment occupation, an
    agent's `assigned_duty_minutes` for an agent occupation — and both ledgers
    are, by definition, the sum of `occupied_minutes` over that resource's
    occupations whose `status` is `RESERVED` or `COMMITTED`; released and
    cancelled occupations contribute nothing."

    Design: Difficulty/resource_temporal_overlap/gse_buffered_half_open_interval_adjacency
    """
    _station, turn, gse, first = _setup_tug_with_one_occupation()

    second = validate_success(api_create(
        _gse_payload(turn, gse["id"], "2026-04-10T06:40:00Z",
                     "2026-04-10T07:00:00Z")), 201)
    assert second["occupied_minutes"] == 20
    assert get_turn_resource(first["id"])["status"] == "RESERVED"
    assert get_turn_resource(second["id"])["status"] == "RESERVED"
    assert get_gse_unit(gse["id"])["committed_occupation_minutes"] == 40

    turn = get_turn(turn["id"])
    assert turn["assigned_gse_count"] == 2
    assert turn["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Queue A: resource_temporal_overlap / agent_bare_closed_interval_touching_endpoints
# ---------------------------------------------------------------------------

def _setup_agent_with_one_duty():
    """Agent E001 already carries the closed duty interval [06:00, 06:20]."""
    station = create_open_station(gse_reposition_buffer_minutes=20)
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    agent = create_certified_agent(station["id"])
    first = validate_success(api_create(
        _agent_payload(turn, agent["id"], "2026-04-10T06:00:00Z",
                       "2026-04-10T06:20:00Z")), 201)
    return station, get_turn(turn["id"]), agent, first


def test_agent_duty_touching_the_previous_end_instant_conflicts(api):
    """PRD §3.7: "The **duty-overlap test** treats an agent's committed
    interval as a bare closed interval with no buffer of any kind: a proposed
    occupation conflicts with an existing occupation for the same agent — again
    considering only rows at `RESERVED` or `COMMITTED` — when the proposed
    `window_start` is at or before the existing `window_end` **and** the
    existing `window_start` is at or before the proposed `window_end`."
    PRD §3.7: "Touching endpoints do conflict, and the collision is refused
    with `ERR_AGENT_DUTY_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/agent_bare_closed_interval_touching_endpoints
    """
    _station, turn, agent, _first = _setup_agent_with_one_duty()

    resp = api_create(_agent_payload(turn, agent["id"], "2026-04-10T06:20:00Z",
                                     "2026-04-10T06:40:00Z"))
    validate_error(resp, ApiErrorId.ERR_AGENT_DUTY_OVERLAP, 409)
    assert get_agent(agent["id"])["assigned_duty_minutes"] == 20


def test_agent_duty_starting_one_minute_after_the_end_is_admissible(api):
    """PRD §3.7: "This is deliberately different arithmetic from the equipment
    test in Section 3.6, which is half-open and buffered."
    PRD §3.7: "An accepted occupation lands at `RESERVED`. Its
    `occupied_minutes` is the elapsed time from `window_start` to `window_end`
    in whole minutes, rounded down."

    Design: Difficulty/resource_temporal_overlap/agent_bare_closed_interval_touching_endpoints
    """
    _station, turn, agent, first = _setup_agent_with_one_duty()

    second = validate_success(api_create(
        _agent_payload(turn, agent["id"], "2026-04-10T06:21:00Z",
                       "2026-04-10T06:40:00Z")), 201)
    assert second["occupied_minutes"] == 19
    assert get_turn_resource(first["id"])["status"] == "RESERVED"
    assert get_turn_resource(second["id"])["status"] == "RESERVED"
    assert get_agent(agent["id"])["assigned_duty_minutes"] == 39

    turn = get_turn(turn["id"])
    assert turn["assigned_agent_count"] == 2
    assert turn["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Queue B: validations / gse_occupation_touching_a_booked_future_service_hold_is_rejected
# ---------------------------------------------------------------------------

def test_occupation_inside_a_booked_future_hold_is_refused(api):
    """PRD §3.6: "Scheduling a hold whose `hold_start` is strictly after the
    current logical clock is the interesting case: the window is recorded
    exactly the same way, but the unit's `status` stays `AVAILABLE`, because
    the hold is merely booked and the unit can still work turnarounds before
    that window opens."
    PRD §3.6: "The **service-hold test** is a closed interval with no buffer at
    all: when the unit carries a non-null `service_hold_start`, a proposed
    occupation conflicts if its `window_start` is at or before
    `service_hold_end` **and** `service_hold_start` is at or before its
    `window_end`."

    Design: Corner/validations/gse_occupation_touching_a_booked_future_service_hold_is_rejected
    """
    station = create_open_station(gse_reposition_buffer_minutes=20)
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    gse = create_gse_unit(station["id"])
    booked = schedule_service_hold(gse["id"], hold_start="2026-04-10T06:00:00Z",
                                   hold_end="2026-04-10T08:00:00Z")
    assert booked["status"] == "AVAILABLE", (
        "a hold booked for a future start does not change the unit's status")

    resp = api_create(_gse_payload(turn, gse["id"], "2026-04-10T06:30:00Z",
                                   "2026-04-10T07:00:00Z"))
    validate_error(resp, ApiErrorId.ERR_GSE_SERVICE_HOLD_CONFLICT, 409)

    accepted = validate_success(api_create(
        _gse_payload(turn, gse["id"], "2026-04-10T09:00:00Z",
                     "2026-04-10T09:30:00Z")), 201)
    assert accepted["occupied_minutes"] == 30
    assert accepted["status"] == "RESERVED"
    assert get_gse_unit(gse["id"])["committed_occupation_minutes"] == 30


# ---------------------------------------------------------------------------
# Queue B: validations / turn_scheduled_outside_bank_window_is_rejected
# ---------------------------------------------------------------------------

def test_turn_scheduled_past_the_bank_window_end_is_refused(api):
    """PRD §3.4: "The scheduled window must sit inside the bank's own window:
    `scheduled_in` earlier than the bank's `window_start`, or `scheduled_out`
    later than the bank's `window_end`, is refused with
    `ERR_TURN_WINDOW_OUTSIDE_BANK`. Both bank boundaries are inclusive."

    Design: Corner/validations/turn_scheduled_outside_bank_window_is_rejected
    """
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=1)

    resp = api.create_turn(
        {"station_id": station["id"], "flight_bank_id": bank["id"],
         "flight_number": "LX318", "turn_type": "TOWING_ONLY",
         "scheduled_in": "2026-04-10T22:10:00Z",
         "scheduled_out": "2026-04-10T22:30:00Z"},
        make_duty_officer_headers())
    validate_error(resp, ApiErrorId.ERR_TURN_WINDOW_OUTSIDE_BANK, 409)
    assert get_flight_bank(bank["id"])["turn_count"] == 0
