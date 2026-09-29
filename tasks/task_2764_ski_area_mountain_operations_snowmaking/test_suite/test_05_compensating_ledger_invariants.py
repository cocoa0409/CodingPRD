"""Compensating operations and the inventories they must hand back.

Two of the mountain's ledgers are inventories rather than event logs: the
season's snowmaking withdrawal, measured in acre-feet of water, and the
operating day's admission counters, measured in guest seats and parking
stalls. Both are consumed by a create and given back by a compensating
operation — a snowmaking session aborted by the wind cascade, and an access
reservation released at the guest services desk.

Every test here takes the figures before the consuming create, performs the
create and then the compensation, and requires the ledger to come back to the
figure it held beforehand rather than merely to something close to it. Because
a restored figure must not be the result of a row nobody wrote, the versions of
the rows the compensation touched are checked alongside the arithmetic.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.assertions import (
    as_number,
    assert_accounting_identity,
    assert_admission_counters,
    assert_energy_kwh,
    assert_instant_equals,
    assert_instant_field,
    assert_integer,
    assert_usd,
    assert_versions_advanced,
    assert_water_af,
    assert_water_ledger_identity,
    expected_capacity,
)
from test_helpers.factories import weather_payload
from test_helpers.test_users import (
    DIRECTOR_HEADERS,
    GUEST_SERVICES_HEADERS,
    SNOWMAKING_HEADERS,
)

# ─── Scenario shape shared by the water-ledger tests ──
# A lift whose wind hold threshold the trigger observation clears, so posting
# the wind is what drives the whole deterioration chain.
LIFT_OVERRIDES = {
    "wind_hold_threshold_mph": 40.0,
    "hourly_capacity_pph": 1800,
    "required_operator_count": 2,
}

# A seven-hour window at 1,200 gallons per minute reserves 1.547 acre-feet.
MORNING_SESSION = {
    "window_start": "2026-08-01T05:00:00Z",
    "window_end": "2026-08-01T12:00:00Z",
    "gun_count": 30,
    "gpm": 1200,
}
MORNING_RESERVED_AF = 1.547

# A seven-hour window at 700 gallons per minute reserves 0.902 acre-feet. It
# only touches the morning window, so it is never superseded by it.
AFTERNOON_SESSION = {
    "window_start": "2026-08-01T12:00:00Z",
    "window_end": "2026-08-01T19:00:00Z",
    "gun_count": 18,
    "gpm": 700,
}
AFTERNOON_RESERVED_AF = 0.902

SEASONAL_RIGHT_AF = 250.000
OPERATING_WET_BULB_F = 22.0
HOLDING_WIND_MPH = 55.0

# ─── Scenario shape shared by the admission tests ─────
# A deliberately tiny lift, so the day's carrying capacity is small enough to
# state exactly: 20 people per hour uphill.
SMALL_LIFT_OVERRIDES = {
    "wind_hold_threshold_mph": 40.0,
    "hourly_capacity_pph": 20,
    "required_operator_count": 2,
}
SEASON_PARTY = {
    "party_code": "PARTY-1",
    "pass_type": "SEASON",
    "party_size": 10,
    "vehicle_count": 4,
}
PARKING_STALLS_TOTAL = 500


def _plant_on_the_open_mountain(mountain):
    """The whole mountain standing open with an online pump house behind it."""
    return mountain.open_mountain(
        with_pump_house=True,
        lift_overrides=LIFT_OVERRIDES,
        wet_bulb_f=OPERATING_WET_BULB_F,
    )


def _post_holding_wind(api, day_plan_id):
    """Post an observation above the lift's hold threshold, which is the head
    of the chain that aborts the area's snowmaking."""
    return validate_success(
        api.post_weather(
            day_plan_id,
            weather_payload(HOLDING_WIND_MPH, OPERATING_WET_BULB_F, new_snow_in=0.0),
            DIRECTOR_HEADERS,
        )
    )


def test_season_water_ledger_returns_to_its_pre_create_figures_when_the_wind_cascade_aborts_a_scheduled_session(
    api, mountain
):
    """Aborting a scheduled session releases its whole reservation and draws nothing, so the season ledger reads exactly what it read before the session was created.

    Creating a session adds its planned reservation to `water_reserved_af`; completing a session removes that reservation and adds the metered actual to `water_used_af`; aborting a session removes the reservation and adds nothing at all, which returns the ledger exactly to its pre-create value.

    Design: Difficulty/compensating_invariant/season_water_ledger_conserved_across_session_abort
    """
    state = _plant_on_the_open_mountain(mountain)

    before = mountain.season(state["season_id"])
    assert_water_af(before["water_reserved_af"], 0.000)
    assert_water_af(before["water_used_af"], 0.000)
    assert_water_af(before["snow_produced_swe_af"], 0.000)
    assert_water_ledger_identity(before)

    session = mountain.schedule_session(
        state["area_id"], state["pump_house_id"], **AFTERNOON_SESSION
    )
    assert_water_af(session["water_af_reserved"], AFTERNOON_RESERVED_AF)

    reserved = mountain.season(state["season_id"])
    assert_water_af(reserved["water_reserved_af"], AFTERNOON_RESERVED_AF)
    assert_water_ledger_identity(reserved)

    _post_holding_wind(api, state["day_plan_id"])

    aborted = mountain.session(session["id"])
    assert aborted["state"] == "ABORTED", (
        f"Expected the scheduled session to be aborted by the hold, got {aborted['state']}"
    )

    after = mountain.season(state["season_id"])
    assert as_number(after["water_reserved_af"]) == as_number(
        before["water_reserved_af"]
    ), (
        f"water_reserved_af must return to its pre-create figure "
        f"{before['water_reserved_af']}, got {after['water_reserved_af']}"
    )
    assert as_number(after["water_used_af"]) == as_number(before["water_used_af"]), (
        f"an aborted session adds nothing to water_used_af: expected "
        f"{before['water_used_af']}, got {after['water_used_af']}"
    )
    assert as_number(after["snow_produced_swe_af"]) == as_number(
        before["snow_produced_swe_af"]
    ), (
        f"an aborted session adds nothing to snow_produced_swe_af: expected "
        f"{before['snow_produced_swe_af']}, got {after['snow_produced_swe_af']}"
    )
    assert_water_af(after["water_reserved_af"], 0.000)
    assert_water_af(after["water_used_af"], 0.000)
    assert_water_af(after["water_right_seasonal_af"], SEASONAL_RIGHT_AF)
    assert_water_ledger_identity(after)


def _morning_session_running_when_the_wind_arrives(api, mountain):
    """Schedule the morning session, start the guns at 05:00, then post the
    holding wind at 07:00 so the session is aborted out of RUNNING."""
    state = _plant_on_the_open_mountain(mountain)
    session = mountain.schedule_session(
        state["area_id"], state["pump_house_id"], **MORNING_SESSION
    )
    mountain.set_clock("2026-08-01T05:00:00Z")
    mountain.drive_session(session["id"], "RUNNING")
    mountain.set_clock("2026-08-01T07:00:00Z")
    return state, session


def test_a_session_aborted_by_the_terrain_hold_is_never_priced_and_meters_nothing(
    api, mountain
):
    """Every metered figure of an aborted session is forced flat, whatever the guns had already produced.

    The session's `ended_at` is stamped, `abort_reason` records `TERRAIN_HOLD`, `SUPERSEDED` or `SEASON_CLOSE`, and every metered figure is forced flat: `water_af_actual` 0.000, `snow_swe_af` 0.000, `energy_kwh` 0.000 and `energy_cost_usd` 0.00 — an aborted session is never priced, however many minutes it ran.

    Design: Difficulty/compensating_invariant/season_water_ledger_conserved_across_session_abort
    """
    state, session = _morning_session_running_when_the_wind_arrives(api, mountain)

    _post_holding_wind(api, state["day_plan_id"])

    aborted = mountain.session(session["id"])
    assert aborted["state"] == "ABORTED", (
        f"Expected the running session to be aborted by the hold, got {aborted['state']}"
    )
    assert aborted["abort_reason"] == "TERRAIN_HOLD", (
        f"Expected abort_reason TERRAIN_HOLD, got {aborted['abort_reason']!r}"
    )
    assert_instant_field(aborted["ended_at"])
    assert_water_af(aborted["water_af_actual"], 0.000)
    assert_water_af(aborted["snow_swe_af"], 0.000)
    assert_energy_kwh(aborted["energy_kwh"], 0.000)
    assert_usd(aborted["energy_cost_usd"], 0.00)


def test_the_reservation_of_a_session_aborted_out_of_running_is_released_while_the_metered_draw_is_left_untouched(
    api, mountain
):
    """The aborted session's whole planned reservation comes back out of the season's reserved figure and its drawn figure does not move.

    Its `water_af_reserved` is subtracted from the season's `water_reserved_af` as a compensating release while `water_used_af` is left untouched, which returns the season ledger to exactly the value it held before the session was created.

    Design: Difficulty/compensating_invariant/season_water_ledger_conserved_across_session_abort
    """
    state, session = _morning_session_running_when_the_wind_arrives(api, mountain)

    running_season = mountain.season(state["season_id"])
    assert_water_af(running_season["water_reserved_af"], MORNING_RESERVED_AF)
    assert_water_af(running_season["water_used_af"], 0.000)

    _post_holding_wind(api, state["day_plan_id"])

    aborted = mountain.session(session["id"])
    assert_water_af(aborted["water_af_reserved"], MORNING_RESERVED_AF)

    after = mountain.season(state["season_id"])
    assert_water_af(after["water_reserved_af"], 0.000)
    assert_water_af(after["water_used_af"], 0.000)
    assert_water_ledger_identity(after)


def test_the_compensating_release_writes_the_session_the_pump_house_and_the_season_rather_than_silently_restoring_them(
    api, mountain
):
    """The rows the abort touches each move on by one version, so the restored ledger figure is a real write and not a row nobody edited.

    The session's, the pump house's and the season's `version` each increment by 1.

    Design: Difficulty/compensating_invariant/season_water_ledger_conserved_across_session_abort
    """
    state = _plant_on_the_open_mountain(mountain)
    session = mountain.schedule_session(
        state["area_id"], state["pump_house_id"], **AFTERNOON_SESSION
    )

    session_before = mountain.session(session["id"])
    pump_house_before = mountain.pump_house(state["pump_house_id"])
    season_before = mountain.season(state["season_id"])
    assert as_number(pump_house_before["peak_committed_gpm"]) == float(
        AFTERNOON_SESSION["gpm"]
    ), (
        "the scheduled session should be committing its flow before the hold: "
        f"got {pump_house_before['peak_committed_gpm']}"
    )

    _post_holding_wind(api, state["day_plan_id"])

    session_after = mountain.session(session["id"])
    pump_house_after = mountain.pump_house(state["pump_house_id"])
    season_after = mountain.season(state["season_id"])

    assert_versions_advanced(session_before, session_after, by=1)
    assert_versions_advanced(pump_house_before, pump_house_after, by=1)
    assert season_after["version"] > season_before["version"], (
        "releasing the reservation is a write on the season row: version stayed at "
        f"{season_before['version']}"
    )
    assert as_number(pump_house_after["peak_committed_gpm"]) == 0.0, (
        "an aborted session occupies no flow, so the committed peak recomputes to "
        f"zero: got {pump_house_after['peak_committed_gpm']}"
    )
    assert_water_af(season_after["water_reserved_af"], 0.000)


def test_the_season_accounting_rollup_counts_the_completed_draw_and_treats_the_aborted_reservation_as_released(
    api, mountain
):
    """One completed session and one session aborted by the hold leave the season rollup reporting the completed draw, nothing reserved and the whole released allowance still available.

    A season with one completed session of 1.326 acre-feet actual water and 1.127 acre-feet of snow water equivalent, one aborted session whose 0.900 acre-feet were released, and a seasonal right of 250.000 acre-feet reports 1.326 used, 0.000 reserved, 1.127 produced and 248.674 remaining.

    Design: Difficulty/compensating_invariant/season_water_ledger_conserved_across_session_abort
    """
    state = _plant_on_the_open_mountain(mountain)
    morning = mountain.schedule_session(
        state["area_id"], state["pump_house_id"], **MORNING_SESSION
    )
    afternoon = mountain.schedule_session(
        state["area_id"], state["pump_house_id"], **AFTERNOON_SESSION
    )
    assert_water_af(morning["water_af_reserved"], MORNING_RESERVED_AF)
    assert_water_af(afternoon["water_af_reserved"], AFTERNOON_RESERVED_AF)

    completed = mountain.run_session_cycle(
        morning["id"],
        [
            ("2026-08-01T05:00:00Z", "RUNNING"),
            ("2026-08-01T07:00:00Z", "PAUSED"),
            ("2026-08-01T09:00:00Z", "RUNNING"),
            ("2026-08-01T13:00:00Z", "COMPLETED"),
        ],
    )
    assert completed["state"] == "COMPLETED", (
        f"Expected the morning session to complete, got {completed['state']}"
    )
    assert_integer(completed["accumulated_run_minutes"], 360)
    assert_water_af(completed["water_af_actual"], 1.326)
    assert_water_af(completed["snow_swe_af"], 1.127)

    _post_holding_wind(api, state["day_plan_id"])

    released = mountain.session(afternoon["id"])
    assert released["state"] == "ABORTED", (
        f"Expected the still-scheduled afternoon session to abort, got {released['state']}"
    )

    rollup = validate_success(
        api.get_season_snow_accounting(state["season_id"], SNOWMAKING_HEADERS)
    )
    assert_water_af(rollup["water_used_af"], 1.326)
    assert_water_af(rollup["water_reserved_af"], 0.000)
    assert_water_af(rollup["snow_produced_swe_af"], 1.127)
    assert_water_af(rollup["water_right_remaining_af"], 248.674)
    assert_water_af(rollup["water_right_seasonal_af"], SEASONAL_RIGHT_AF)
    assert_integer(rollup["completed_session_count"], 1)
    assert_integer(rollup["aborted_session_count"], 1)
    assert_accounting_identity(rollup)


def _small_mountain_open_for_admission(mountain):
    """A published, fully open operating day whose one small lift makes the
    day's carrying capacity 12 guests and its non-season pool 8."""
    state = mountain.open_mountain(lift_overrides=SMALL_LIFT_OVERRIDES)
    capacity = expected_capacity(
        SMALL_LIFT_OVERRIDES["hourly_capacity_pph"], 18.0
    )
    day_plan = mountain.day_plan(state["day_plan_id"])
    assert_integer(day_plan["guest_capacity"], capacity["guest_capacity"])
    assert_integer(day_plan["non_season_pool"], capacity["non_season_pool"])
    assert_integer(day_plan["parking_stalls_total"], PARKING_STALLS_TOTAL)
    state["capacity"] = capacity
    return state


def _reservations_of(api, day_plan_id):
    """Every reservation row of one operating day, in created_at order."""
    rows, _meta = validate_paginated(
        api.list_day_plan_reservations(day_plan_id, GUEST_SERVICES_HEADERS)
    )
    return rows


def test_checking_a_confirmed_party_in_at_the_gate_moves_no_admission_counter(
    api, mountain
):
    """A party that consumed its seats and stalls at confirmation consumes exactly the same seats and stalls once it is checked in.

    Check-in changes no counter, because a checked-in party consumed its seat and its stalls at confirmation.

    Design: Difficulty/compensating_invariant/day_plan_parking_and_admission_counters_conserved_across_release
    """
    state = _small_mountain_open_for_admission(mountain)
    reservation = mountain.create_reservation(state["day_plan_id"], **SEASON_PARTY)
    assert reservation["state"] == "CONFIRMED", (
        f"A party of {SEASON_PARTY['party_size']} fits the day's capacity, got "
        f"{reservation['state']}"
    )
    assert_integer(reservation["allocated_stalls"], SEASON_PARTY["vehicle_count"])

    before = mountain.day_plan(state["day_plan_id"])
    assert_integer(before["admitted_guest_count"], SEASON_PARTY["party_size"])
    assert_integer(before["non_season_admitted_count"], 0)
    assert_integer(before["waitlisted_guest_count"], 0)
    assert_integer(before["parking_stalls_used"], SEASON_PARTY["vehicle_count"])

    checked_in = validate_success(
        api.check_in_reservation(reservation["id"], GUEST_SERVICES_HEADERS)
    )
    assert checked_in["state"] == "CHECKED_IN", (
        f"Expected the party to be checked in, got {checked_in['state']}"
    )

    after = mountain.day_plan(state["day_plan_id"])
    for counter in (
        "admitted_guest_count",
        "non_season_admitted_count",
        "waitlisted_guest_count",
        "parking_stalls_used",
    ):
        assert_integer(after[counter], before[counter])
    assert_admission_counters(after, _reservations_of(api, state["day_plan_id"]))


def test_releasing_a_checked_in_party_returns_the_day_s_seats_and_stalls_to_their_pre_admission_figures(
    api, mountain, initial_clock
):
    """Releasing the only admitted party zeroes its allocated stalls and hands back exactly the seats and stalls it held.

    The row moves to `RELEASED` — admissible from `CONFIRMED`, `CHECKED_IN` or `WAITLISTED` — with `released_at` stamped and `allocated_stalls` zeroed, after which the day's counters are recomputed, freeing whatever seats and stalls the party held.

    Design: Difficulty/compensating_invariant/day_plan_parking_and_admission_counters_conserved_across_release
    """
    state = _small_mountain_open_for_admission(mountain)
    before = mountain.day_plan(state["day_plan_id"])
    assert_integer(before["admitted_guest_count"], 0)
    assert_integer(before["parking_stalls_used"], 0)

    reservation = mountain.create_reservation(state["day_plan_id"], **SEASON_PARTY)
    mountain.check_in(reservation["id"])
    admitted = mountain.day_plan(state["day_plan_id"])
    assert_integer(admitted["admitted_guest_count"], SEASON_PARTY["party_size"])
    assert_integer(admitted["parking_stalls_used"], SEASON_PARTY["vehicle_count"])

    released = validate_success(
        api.release_reservation(reservation["id"], GUEST_SERVICES_HEADERS)
    )
    assert released["state"] == "RELEASED", (
        f"Expected the checked-in party to be released, got {released['state']}"
    )
    assert_integer(released["allocated_stalls"], 0)
    assert_instant_equals(released["released_at"], initial_clock)

    after = mountain.day_plan(state["day_plan_id"])
    for counter in (
        "admitted_guest_count",
        "non_season_admitted_count",
        "waitlisted_guest_count",
        "parking_stalls_used",
    ):
        assert_integer(after[counter], before[counter])
    assert_integer(after["admitted_guest_count"], 0)
    assert_integer(after["parking_stalls_used"], 0)
    assert_admission_counters(after, _reservations_of(api, state["day_plan_id"]))

    assert_integer(after["guest_capacity"], before["guest_capacity"])
    assert_integer(after["non_season_pool"], before["non_season_pool"])

    confirmed, meta = validate_paginated(
        api.list_day_plan_reservations(
            state["day_plan_id"], GUEST_SERVICES_HEADERS, state="CONFIRMED"
        )
    )
    assert confirmed == [], (
        f"No party is holding a seat after the release, got {len(confirmed)} confirmed rows"
    )
    assert_integer(meta["total_count"], 0)


def test_releasing_a_party_writes_both_the_reservation_and_the_operating_day_it_frees(
    api, mountain
):
    """The restored counters are the result of a real write on the day plan, not a figure left alone.

    A release increments the reservation's `version` and the day plan's `version` by 1 each.

    Design: Difficulty/compensating_invariant/day_plan_parking_and_admission_counters_conserved_across_release
    """
    state = _small_mountain_open_for_admission(mountain)
    reservation = mountain.create_reservation(state["day_plan_id"], **SEASON_PARTY)
    mountain.check_in(reservation["id"])

    reservation_before = mountain.reservation(reservation["id"])
    day_plan_before = mountain.day_plan(state["day_plan_id"])

    validate_success(api.release_reservation(reservation["id"], GUEST_SERVICES_HEADERS))

    reservation_after = mountain.reservation(reservation["id"])
    day_plan_after = mountain.day_plan(state["day_plan_id"])

    assert_versions_advanced(reservation_before, reservation_after, by=1)
    assert_versions_advanced(day_plan_before, day_plan_after, by=1)
    assert_integer(day_plan_after["parking_stalls_used"], 0)
