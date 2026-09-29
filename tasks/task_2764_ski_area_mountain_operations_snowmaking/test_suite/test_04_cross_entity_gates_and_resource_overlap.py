"""Opening and start gates decided by another row, and competing claims on the
mountain's shared resources over time.

Two families of rule live in this file. The first decides an operation from the
live state of a row the request body never names: whether a terrain area may
open is decided by its serving lift, and whether a snowmaking session may start
is decided by its pump house. The second arbitrates claims that overlap in
time on one shared resource: the aggregate flow a pump house carries across a
window, and the turnaround a lift operator is owed between two shifts.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_OPERATOR_DOUBLE_BOOKED,
    ERR_PUMP_CAPACITY_EXCEEDED,
    ERR_PUMP_HOUSE_OFFLINE,
    ERR_SERVING_LIFT_NOT_OPEN,
)
from test_helpers.assertions import (
    assert_integer,
    assert_instant_equals,
    assert_number_equals,
    assert_one_decimal,
    assert_version_unchanged,
    assert_water_af,
    expected_capacity,
    expected_water_af,
)
from test_helpers.test_users import (
    DIRECTOR_HEADERS,
    LIFT_OPS_HEADERS,
    SNOWMAKING_HEADERS,
)

# ─── The season shape every recipe in this file reuses ────────────────────────

SEASON_OVERRIDES: Dict[str, Any] = {
    "season_label": "2026-27",
    "base_depth_policy": "MEAN_OF_STAKES",
    "water_right_seasonal_af": 250.000,
    "plant_max_gpm": 6000,
    "snowmaking_kwh_per_af": 620.0,
    "min_patrollers_per_open_area": 2,
    "groom_freshness_hours": 18,
}

LIFT_OVERRIDES: Dict[str, Any] = {
    "lift_code": "L1",
    "name": "Summit Express",
    "lift_type": "DETACHABLE",
    "wind_hold_threshold_mph": 40.0,
    "hourly_capacity_pph": 1800,
    "required_operator_count": 2,
}

AREA_OVERRIDES: Dict[str, Any] = {
    "trail_code": "T1",
    "name": "Sunbowl",
    "terrain_class": "BLUE",
    "acres": 18.0,
    "min_open_base_depth_in": 30,
    "avalanche_terrain": False,
}

OPENING_PAYLOAD = {"decision": "OPEN", "note": "first tracks"}


def _mountain_with_serving_lift_on_standby(mountain) -> Dict[str, Any]:
    """A published operating day whose one terrain area has cleared every gate on
    itself — base depth 40.0 against a minimum of 30, a completed groom, two
    available patrollers, no park and no avalanche terrain — while its serving
    lift is deliberately left on STANDBY with a current passing inspection."""
    state = mountain.ready_area(
        season_overrides=dict(SEASON_OVERRIDES),
        lift_overrides=dict(LIFT_OVERRIDES),
        area_overrides=dict(AREA_OVERRIDES),
        passes_completed=20,
        patroller_count=2,
    )
    day_plan = mountain.create_day_plan(
        state["season_id"], operating_date="2026-08-01", parking_stalls_total=500
    )
    mountain.publish_day_plan(day_plan["id"])
    mountain.post_weather(
        day_plan["id"], wind_speed_mph=10.0, wet_bulb_f=22.0, new_snow_in=0.0
    )
    state["day_plan_id"] = day_plan["id"]
    state["day_plan"] = mountain.day_plan(day_plan["id"])
    return state


def _open_the_serving_lift(mountain, state: Dict[str, Any]) -> Dict[str, Any]:
    """Move the serving lift STANDBY → OPEN, which is the only fact the blocked
    opening decision was missing."""
    lift = mountain.set_lift_status(state["lift_id"], "OPEN")
    assert lift["service_status"] == "OPEN", (
        f"Setup expected the serving lift on OPEN, got {lift['service_status']}"
    )
    return lift


def _plant_with_three_areas(mountain) -> Dict[str, Any]:
    """A season whose pump house PH1 (max_gpm 2400) supplies three terrain areas
    sharing one serving lift, so no supersede rule can perturb the peer set."""
    season = mountain.create_season(**SEASON_OVERRIDES)
    lift = mountain.create_lift(season["id"], **LIFT_OVERRIDES)
    area_one = mountain.create_terrain_area(
        season["id"], lift["id"], **AREA_OVERRIDES
    )
    area_two = mountain.create_terrain_area(
        season["id"],
        lift["id"],
        trail_code="T2",
        name="Meadow",
        terrain_class="GREEN",
        acres=14.0,
        min_open_base_depth_in=30,
        avalanche_terrain=False,
    )
    area_three = mountain.create_terrain_area(
        season["id"],
        lift["id"],
        trail_code="T3",
        name="Cirque",
        terrain_class="BLACK",
        acres=8.0,
        min_open_base_depth_in=30,
        avalanche_terrain=False,
    )
    pump_house = mountain.create_pump_house(
        season["id"],
        pump_house_code="PH1",
        name="Base Pumphouse",
        max_gpm=2400,
        gun_count=40,
        status="ONLINE",
    )
    return {
        "season_id": season["id"],
        "lift_id": lift["id"],
        "t1_id": area_one["id"],
        "t2_id": area_two["id"],
        "t3_id": area_three["id"],
        "pump_house_id": pump_house["id"],
    }


def _schedule_two_flow_peers(mountain, plant: Dict[str, Any]) -> None:
    """Peer A on T1 over [08:00, 12:00) at 1200 gpm and peer B on T2 over
    [10:00, 14:00) at 900 gpm — each individually inside the 2400 gpm ceiling."""
    mountain.schedule_session(
        plant["t1_id"],
        plant["pump_house_id"],
        window_start="2026-08-01T08:00:00Z",
        window_end="2026-08-01T12:00:00Z",
        gun_count=30,
        gpm=1200,
    )
    mountain.schedule_session(
        plant["t2_id"],
        plant["pump_house_id"],
        window_start="2026-08-01T10:00:00Z",
        window_end="2026-08-01T14:00:00Z",
        gun_count=24,
        gpm=900,
    )


# ─── A terrain area may only open behind a lift that is spinning ─────────────

def test_opening_a_fully_ready_area_is_refused_while_its_serving_lift_sits_on_standby(
    api, mountain
):
    """An area that has cleared every gate on itself still cannot open when the
    lift that serves it is not carrying guests uphill.

    The serving lift is open — `ERR_SERVING_LIFT_NOT_OPEN` (422), on the opening decision.

    Design: Difficulty/cross_entity_state_dependency/terrain_open_requires_serving_lift_open
    """
    state = _mountain_with_serving_lift_on_standby(mountain)
    assert mountain.area(state["area_id"])["opening_state"] == "READY", (
        "Setup expected the terrain area to have reached READY on its own gates"
    )
    assert mountain.lift(state["lift_id"])["service_status"] == "STANDBY", (
        "Setup expected the serving lift to still be on STANDBY"
    )

    response = api.decide_opening(
        state["area_id"], dict(OPENING_PAYLOAD), DIRECTOR_HEADERS
    )

    validate_error(response, ERR_SERVING_LIFT_NOT_OPEN)
    area = mountain.area(state["area_id"])
    assert area["opening_state"] == "READY", (
        "The refused decision must leave the area sitting in READY, not open it"
    )


def test_opening_the_same_area_succeeds_once_the_serving_lift_moves_to_open(
    api, mountain
):
    """Opening the serving lift is the only fact the refused decision was
    missing; replaying the identical decision then moves the area open.

    A successful opening moves the area `READY → OPEN`, or `PATROL_HOLD → OPEN` when the director explicitly reopens a held area.

    Design: Difficulty/cross_entity_state_dependency/terrain_open_requires_serving_lift_open
    """
    state = _mountain_with_serving_lift_on_standby(mountain)
    validate_error(
        api.decide_opening(state["area_id"], dict(OPENING_PAYLOAD), DIRECTOR_HEADERS),
        ERR_SERVING_LIFT_NOT_OPEN,
    )
    _open_the_serving_lift(mountain, state)

    response = api.decide_opening(
        state["area_id"], dict(OPENING_PAYLOAD), DIRECTOR_HEADERS
    )

    data = validate_success(response)
    assert data["opening_state"] == "OPEN", (
        f"The area should have moved READY → OPEN, got {data['opening_state']}"
    )
    assert mountain.area(state["area_id"])["opening_state"] == "OPEN", (
        "The persisted area should read OPEN after the accepted decision"
    )


def test_opening_behind_the_now_open_lift_counts_the_area_and_its_acres_on_the_day_plan(
    api, mountain
):
    """The open terrain tally on the operating day counts exactly the areas
    standing open and sums their acreage.

    Second, `open_terrain_count` is the number of the season's areas whose `opening_state` is `OPEN`, and `terrain_open_acres` is the sum of those areas' `acres`, rounded half up to one decimal place.

    Design: Difficulty/cross_entity_state_dependency/terrain_open_requires_serving_lift_open
    """
    state = _mountain_with_serving_lift_on_standby(mountain)
    before = mountain.day_plan(state["day_plan_id"])
    assert_integer(before["open_terrain_count"], 0)
    _open_the_serving_lift(mountain, state)

    validate_success(
        api.decide_opening(state["area_id"], dict(OPENING_PAYLOAD), DIRECTOR_HEADERS)
    )

    day_plan = validate_success(api.get_day_plan(state["day_plan_id"], DIRECTOR_HEADERS))
    assert_integer(day_plan["open_terrain_count"], 1)
    assert_one_decimal(day_plan["terrain_open_acres"], 18.0)


def test_the_open_lift_capacity_drives_the_carrying_capacity_waterfall_on_the_day_plan(
    api, mountain
):
    """With the lift open and the area open, the uphill capacity flows through
    the uncrowded carrying capacity into the guest capacity and the pool held
    back for non-passholders.

    Two open lifts of 1,100 and 700 people per hour serving three open areas of 18.0, 14.0 and 8.0 acres give 1,800 uphill, a `raw_ccc` of 1,080, a density of 27.0 which trips the reduction, a `guest_capacity` of 918, and a `non_season_pool` of 642.

    Design: Difficulty/cross_entity_state_dependency/terrain_open_requires_serving_lift_open
    """
    state = _mountain_with_serving_lift_on_standby(mountain)
    _open_the_serving_lift(mountain, state)

    validate_success(
        api.decide_opening(state["area_id"], dict(OPENING_PAYLOAD), DIRECTOR_HEADERS)
    )

    day_plan = validate_success(api.get_day_plan(state["day_plan_id"], DIRECTOR_HEADERS))
    assert_integer(day_plan["open_lift_capacity_pph"], 1800)
    assert_integer(day_plan["raw_ccc"], 1080)
    expected = expected_capacity(1800, 18.0)
    assert_integer(day_plan["guest_capacity"], expected["guest_capacity"])
    assert_integer(day_plan["guest_capacity"], 918)
    assert_integer(day_plan["non_season_pool"], expected["non_season_pool"])
    assert_integer(day_plan["non_season_pool"], 642)


# ─── A session may only start behind a pump house that is online ─────────────

PUMP_HOUSE_OVERRIDES: Dict[str, Any] = {
    "pump_house_code": "PH1",
    "name": "Base Pumphouse",
    "max_gpm": 2400,
    "gun_count": 40,
    "status": "ONLINE",
}


def _scheduled_session_on_the_open_mountain(mountain) -> Dict[str, Any]:
    """An open mountain carrying real weather at a wet bulb of 22.0, with one
    session scheduled over [05:00, 12:00) at 1200 gallons per minute."""
    state = mountain.open_mountain(
        season_overrides=dict(SEASON_OVERRIDES),
        lift_overrides=dict(LIFT_OVERRIDES),
        area_overrides=dict(AREA_OVERRIDES),
        wind_speed_mph=10.0,
        wet_bulb_f=22.0,
        with_pump_house=True,
        pump_house_overrides=dict(PUMP_HOUSE_OVERRIDES),
    )
    session = mountain.schedule_session(
        state["area_id"],
        state["pump_house_id"],
        window_start="2026-08-01T05:00:00Z",
        window_end="2026-08-01T12:00:00Z",
        gun_count=30,
        gpm=1200,
    )
    state["session_id"] = session["id"]
    state["session"] = session
    return state


def test_starting_a_scheduled_session_is_refused_while_its_pump_house_is_in_maintenance(
    api, mountain
):
    """A session whose water comes from a pump house pulled down for maintenance
    cannot be started, however cold the night is.

    Its `status` is either `ONLINE` (the default) or `MAINTENANCE`, and the `SnowmakingSupervisor` may toggle it later: moving a pump house to `MAINTENANCE` blocks new sessions on it and blocks any attempt to start or resume an existing one, both rejected with `ERR_PUMP_HOUSE_OFFLINE`, while sessions already running are left untouched and may still be paused or completed.

    Design: Difficulty/cross_entity_state_dependency/session_start_requires_pump_house_online
    """
    state = _scheduled_session_on_the_open_mountain(mountain)
    mountain.set_pump_house_status(state["pump_house_id"], "MAINTENANCE")
    mountain.set_clock("2026-08-01T05:00:00Z")

    response = api.set_session_status(
        state["session_id"], f.session_status_payload("RUNNING"), SNOWMAKING_HEADERS
    )

    validate_error(response, ERR_PUMP_HOUSE_OFFLINE)
    session = mountain.session(state["session_id"])
    assert session["state"] == "SCHEDULED", (
        f"The refused start must leave the session SCHEDULED, got {session['state']}"
    )
    assert session["started_at"] is None, (
        "A refused start must not stamp started_at"
    )
    pump_house = mountain.pump_house(state["pump_house_id"])
    assert_integer(pump_house["active_session_count"], 0)


def test_the_same_session_starts_once_the_pump_house_returns_to_online(api, mountain):
    """Bringing the pump house back online is the only fact the refused start was
    missing; the identical request then runs the guns.

    A successful start copies the active day plan's `wet_bulb_f` onto the session, stamps both `started_at` and `last_running_since` with the logical clock, increments the pump house's `active_session_count` by 1, and increments both the session's and the pump house's `version` by 1.

    Design: Difficulty/cross_entity_state_dependency/session_start_requires_pump_house_online
    """
    state = _scheduled_session_on_the_open_mountain(mountain)
    mountain.set_pump_house_status(state["pump_house_id"], "MAINTENANCE")
    mountain.set_clock("2026-08-01T05:00:00Z")
    validate_error(
        api.set_session_status(
            state["session_id"], f.session_status_payload("RUNNING"), SNOWMAKING_HEADERS
        ),
        ERR_PUMP_HOUSE_OFFLINE,
    )
    mountain.set_pump_house_status(state["pump_house_id"], "ONLINE")

    response = api.set_session_status(
        state["session_id"], f.session_status_payload("RUNNING"), SNOWMAKING_HEADERS
    )

    data = validate_success(response)
    assert data["state"] == "RUNNING", (
        f"The accepted start should move the session to RUNNING, got {data['state']}"
    )
    assert_instant_equals(data["started_at"], "2026-08-01T05:00:00Z")
    assert_instant_equals(data["last_running_since"], "2026-08-01T05:00:00Z")
    assert_one_decimal(data["wet_bulb_f"], 22.0)
    pump_house = mountain.pump_house(state["pump_house_id"])
    assert_integer(pump_house["active_session_count"], 1)


def test_a_session_started_after_the_pump_house_recovers_takes_the_wet_bulb_band_factor(
    api, mountain
):
    """The start that finally lands reads the operating day's wet bulb of 22.0
    and lands in the middle productivity band.

    Otherwise, a wet bulb above 24.0 sets `snow_yield_factor` to 0.60; a wet bulb at or below 24.0 but above 20.0 sets it to 0.85; and a wet bulb at or below 20.0 sets it to 1.00.

    Design: Difficulty/cross_entity_state_dependency/session_start_requires_pump_house_online
    """
    state = _scheduled_session_on_the_open_mountain(mountain)
    mountain.set_pump_house_status(state["pump_house_id"], "MAINTENANCE")
    mountain.set_clock("2026-08-01T05:00:00Z")
    validate_error(
        api.set_session_status(
            state["session_id"], f.session_status_payload("RUNNING"), SNOWMAKING_HEADERS
        ),
        ERR_PUMP_HOUSE_OFFLINE,
    )
    mountain.set_pump_house_status(state["pump_house_id"], "ONLINE")

    response = api.set_session_status(
        state["session_id"], f.session_status_payload("RUNNING"), SNOWMAKING_HEADERS
    )

    data = validate_success(response)
    assert_number_equals(data["snow_yield_factor"], 0.85, places=2)


# ─── Aggregate flow through one pump house across a shared timeline ──────────

def _candidate_over_the_busiest_span(plant: Dict[str, Any], api) -> Any:
    """Candidate C on T3 over [11:00, 13:00) at 400 gallons per minute, which
    stacks on top of both peers between 11:00 and 12:00."""
    version = validate_success(
        api.get_terrain_area(plant["t3_id"], SNOWMAKING_HEADERS)
    )["version"]
    return api.create_session(
        f.session_payload(
            plant["t3_id"],
            plant["pump_house_id"],
            version,
            window_start="2026-08-01T11:00:00Z",
            window_end="2026-08-01T13:00:00Z",
            gun_count=10,
            gpm=400,
        ),
        SNOWMAKING_HEADERS,
    )


def _candidate_touching_the_first_peer_end(plant: Dict[str, Any], api) -> Any:
    """Candidate D on T3 over [12:00, 14:00) at 300 gallons per minute, whose
    window opens at the exact instant peer A's window closes."""
    version = validate_success(
        api.get_terrain_area(plant["t3_id"], SNOWMAKING_HEADERS)
    )["version"]
    return api.create_session(
        f.session_payload(
            plant["t3_id"],
            plant["pump_house_id"],
            version,
            window_start="2026-08-01T12:00:00Z",
            window_end="2026-08-01T14:00:00Z",
            gun_count=8,
            gpm=300,
        ),
        SNOWMAKING_HEADERS,
    )


def test_a_small_session_is_refused_when_its_window_stacks_two_peers_over_the_pump_ceiling(
    api, mountain
):
    """Each of the three flows fits under the pump house ceiling on its own, but
    the span from 11:00 to 12:00 would carry all three at once at 2500 gallons
    per minute against a ceiling of 2400.

    For each such span that intersects the proposed session's own window, add the proposed session's `gpm` to the `gpm` of every peer whose window starts before the span's end and ends after the span's start; if that sum exceeds the pump house's `max_gpm`, the request is refused with `ERR_PUMP_CAPACITY_EXCEEDED`.

    Design: Difficulty/resource_temporal_overlap/pump_house_aggregate_gpm_half_open_sweep_rejects_and_admits_touching_window
    """
    plant = _plant_with_three_areas(mountain)
    _schedule_two_flow_peers(mountain, plant)
    area_before = mountain.area(plant["t3_id"])

    response = _candidate_over_the_busiest_span(plant, api)

    validate_error(response, ERR_PUMP_CAPACITY_EXCEEDED)
    area = mountain.area(plant["t3_id"])
    assert_version_unchanged(area_before, area)
    assert area["opening_state"] == "CLOSED", (
        "The refused create must not move the terrain area out of CLOSED"
    )


def test_a_session_starting_exactly_when_a_peer_window_closes_is_admitted(api, mountain):
    """The same pump house that refused the overlapping window accepts a window
    that opens at the instant peer A's window closes, because the two never
    occupy a span together.

    Because overlap is half-open, a peer that ends exactly when a span begins is not an occupant of that span, and a boundary-aligned back-to-back schedule is therefore always admissible.

    Design: Difficulty/resource_temporal_overlap/pump_house_aggregate_gpm_half_open_sweep_rejects_and_admits_touching_window
    """
    plant = _plant_with_three_areas(mountain)
    _schedule_two_flow_peers(mountain, plant)
    validate_error(
        _candidate_over_the_busiest_span(plant, api), ERR_PUMP_CAPACITY_EXCEEDED
    )

    response = _candidate_touching_the_first_peer_end(plant, api)

    data = validate_success(response, expected_status=201)
    assert data["state"] == "SCHEDULED", (
        f"The admitted session should land in SCHEDULED, got {data['state']}"
    )
    assert_integer(data["gpm"], 300)


def test_the_admitted_touching_session_reserves_water_for_its_whole_declared_window(
    api, mountain
):
    """The boundary-touching window is billed for every one of its declared
    minutes at its committed flow.

    The session's `planned_minutes` is the number of whole minutes between `window_start` and `window_end`, and the water it reserves follows directly: the committed flow in gallons per minute is multiplied by `planned_minutes` to give gallons, that total is divided by the 325,851 gallons that make up one acre-foot, and the quotient is rounded half up to three decimal places to give `water_af_reserved`.

    Design: Difficulty/resource_temporal_overlap/pump_house_aggregate_gpm_half_open_sweep_rejects_and_admits_touching_window
    """
    plant = _plant_with_three_areas(mountain)
    _schedule_two_flow_peers(mountain, plant)
    validate_error(
        _candidate_over_the_busiest_span(plant, api), ERR_PUMP_CAPACITY_EXCEEDED
    )

    data = validate_success(
        _candidate_touching_the_first_peer_end(plant, api), expected_status=201
    )

    assert_integer(data["planned_minutes"], 120)
    assert_water_af(data["water_af_reserved"], expected_water_af(300, 120))
    assert_water_af(data["water_af_reserved"], 0.110)


def test_the_committed_peak_after_the_touching_admission_comes_from_a_peer_only_span(
    api, mountain
):
    """The recomputed peak is 2100 gallons per minute over the span from 10:00 to
    12:00, which the newly admitted session never occupies at all.

    Once the request is accepted, `peak_committed_gpm` on that pump house is recomputed as the greatest summed flow of its occupants over **every** adjacent span of that timeline — not merely the spans the new session touches — where the occupant set is the peers plus the newly accepted session, filtered to rows whose window starts before the span's end and ends after the span's start.

    Design: Difficulty/resource_temporal_overlap/pump_house_aggregate_gpm_half_open_sweep_rejects_and_admits_touching_window
    """
    plant = _plant_with_three_areas(mountain)
    _schedule_two_flow_peers(mountain, plant)
    validate_error(
        _candidate_over_the_busiest_span(plant, api), ERR_PUMP_CAPACITY_EXCEEDED
    )
    validate_success(
        _candidate_touching_the_first_peer_end(plant, api), expected_status=201
    )

    pump_house = validate_success(
        api.get_pump_house(plant["pump_house_id"], SNOWMAKING_HEADERS)
    )

    assert_integer(pump_house["peak_committed_gpm"], 2100)
    assert_integer(pump_house["active_session_count"], 0)


def test_the_season_water_ledger_holds_the_reservations_of_the_two_peers_and_the_admission(
    api, mountain
):
    """Only the three accepted reservations sit in the ledger; the refused
    overlapping window reserved nothing.

    Creating a session adds its planned reservation to `water_reserved_af`; completing a session removes that reservation and adds the metered actual to `water_used_af`; aborting a session removes the reservation and adds nothing at all, which returns the ledger exactly to its pre-create value.

    Design: Difficulty/resource_temporal_overlap/pump_house_aggregate_gpm_half_open_sweep_rejects_and_admits_touching_window
    """
    plant = _plant_with_three_areas(mountain)
    _schedule_two_flow_peers(mountain, plant)
    validate_error(
        _candidate_over_the_busiest_span(plant, api), ERR_PUMP_CAPACITY_EXCEEDED
    )
    validate_success(
        _candidate_touching_the_first_peer_end(plant, api), expected_status=201
    )

    season = validate_success(api.get_season(plant["season_id"], SNOWMAKING_HEADERS))

    assert_water_af(season["water_reserved_af"], 1.657)


# ─── One operator owed a turnaround between two shifts ───────────────────────

def _lift_with_a_morning_operator(mountain) -> Dict[str, Any]:
    """A lift whose operator OP-1 already holds the top-operator slot for the
    morning shift [06:00, 14:00)."""
    season = mountain.create_season(**SEASON_OVERRIDES)
    lift = mountain.create_lift(season["id"], **LIFT_OVERRIDES)
    peer = mountain.assign_operator(
        lift["id"],
        operator_code="OP-1",
        role_on_lift="TOP_OP",
        shift_start="2026-08-01T06:00:00Z",
        shift_end="2026-08-01T14:00:00Z",
    )
    return {
        "season_id": season["id"],
        "lift_id": lift["id"],
        "peer_assignment_id": peer["id"],
    }


def _afternoon_shift(roster: Dict[str, Any], shift_start: str) -> Dict[str, Any]:
    """The same operator asked to take the mid-load slot until 18:00."""
    return f.staff_assignment_payload(
        roster["lift_id"],
        operator_code="OP-1",
        role_on_lift="MID_LOAD",
        shift_start=shift_start,
        shift_end="2026-08-01T18:00:00Z",
    )


def test_an_operator_handed_a_second_shift_fifteen_minutes_later_is_refused(api, mountain):
    """A quarter-hour between the end of one shift and the start of the next
    denies the operator the half-hour turnaround, even though the two shifts do
    not overlap by a single second.

    Separately, the same `operator_code` may not hold two `ASSIGNED` assignments whose shifts come within a half-hour turnaround of one another: two shifts conflict when the new shift starts before 30 minutes after the peer's end **and** 30 minutes after the new shift's end falls after the peer's start, and such a request is refused with `ERR_OPERATOR_DOUBLE_BOOKED`.

    Design: Difficulty/resource_temporal_overlap/operator_turnaround_buffer_rejects_thirty_minute_gap_on_lift_staff_assignment
    """
    roster = _lift_with_a_morning_operator(mountain)

    response = api.create_lift_staff_assignment(
        _afternoon_shift(roster, "2026-08-01T14:15:00Z"), LIFT_OPS_HEADERS
    )

    validate_error(response, ERR_OPERATOR_DOUBLE_BOOKED)
    rows, _meta = validate_paginated(
        api.list_lift_staff_assignments(roster["lift_id"], LIFT_OPS_HEADERS)
    )
    assert len(rows) == 1, (
        f"The refused assignment must not join the roster, found {len(rows)} rows"
    )
    assert rows[0]["state"] == "ASSIGNED", (
        "The morning assignment must be left untouched by the refused request"
    )


def test_the_same_operator_is_accepted_when_the_gap_is_exactly_half_an_hour(api, mountain):
    """Moving the second shift a quarter-hour later gives exactly the half-hour
    turnaround, and the boundary falls on the admissible side.

    Separately, the same `operator_code` may not hold two `ASSIGNED` assignments whose shifts come within a half-hour turnaround of one another: two shifts conflict when the new shift starts before 30 minutes after the peer's end **and** 30 minutes after the new shift's end falls after the peer's start, and such a request is refused with `ERR_OPERATOR_DOUBLE_BOOKED`.

    Design: Difficulty/resource_temporal_overlap/operator_turnaround_buffer_rejects_thirty_minute_gap_on_lift_staff_assignment
    """
    roster = _lift_with_a_morning_operator(mountain)
    validate_error(
        api.create_lift_staff_assignment(
            _afternoon_shift(roster, "2026-08-01T14:15:00Z"), LIFT_OPS_HEADERS
        ),
        ERR_OPERATOR_DOUBLE_BOOKED,
    )

    response = api.create_lift_staff_assignment(
        _afternoon_shift(roster, "2026-08-01T14:30:00Z"), LIFT_OPS_HEADERS
    )

    data = validate_success(response, expected_status=201)
    assert data["state"] == "ASSIGNED", (
        f"The admitted assignment should be ASSIGNED, got {data['state']}"
    )
    assert_instant_equals(data["shift_start"], "2026-08-01T14:30:00Z")
    rows, _meta = validate_paginated(
        api.list_lift_staff_assignments(
            roster["lift_id"], LIFT_OPS_HEADERS, state="ASSIGNED"
        )
    )
    assert len(rows) == 2, (
        f"Both shifts should now stand on the roster, found {len(rows)} rows"
    )
