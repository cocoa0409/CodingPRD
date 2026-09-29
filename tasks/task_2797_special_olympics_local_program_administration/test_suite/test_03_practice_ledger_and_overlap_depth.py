"""Attendance thresholds, session/athlete overlap semantics and the minute ledger."""

from test_helpers import (
    ApiErrorId,
    fixtures as fx,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_instant_equals
from test_helpers.fixtures import CD, PM


def _fifty_minute_session_world():
    """A 50-minute session — required_minutes is ceil(50 × 0.75) = 38."""
    world = fx.setup_session_ready_world(
        session_overrides={"duration_minutes": 50},
        athlete_specs=[
            {"athlete": {"legal_name": "Maya Foster", "birth_date": "2004-03-09"}},
            {"athlete": {"legal_name": "Ivan Petrov", "birth_date": "2003-10-01"}},
        ],
        attendance_clock="2026-09-10T10:00:00Z")
    return world


def test_01_thirty_seven_minutes_falls_one_tick_short_of_the_requirement():
    """The inclusive comparison rejects 37 against a required 38.

    PRD §3.4: "the server computes `required_minutes` as three quarters of the
    session's `duration_minutes`, **rounded up** to the next whole minute" and
    "a 50-minute session requires exactly 38 minutes, so an athlete present for
    38 minutes is `COUNTED` while one present for 37 is `NOT_COUNTED`", the
    `NOT_COUNTED` row's "`counted_minutes` is 0".

    Design: Difficulty/boundary_precision_check/attendance_counted_minutes_threshold_boundary
    """
    world = _fifty_minute_session_world()
    session, athletes = world["session"], world["athletes"]
    record = fx.record_attendance(session["id"], athletes[0]["id"],
                                  session["version"], minutes_present=37)
    assert record["required_minutes"] == 38
    assert record["status"] == "NOT_COUNTED"
    assert record["counted_minutes"] == 0

    athlete = validate_success(api_client.get_athlete(athletes[0]["id"], PM))
    assert athlete["cumulative_practice_minutes"] == 0
    assert athlete["counted_session_count"] == 0
    assert fx.get_program(world["program"]["id"])["program_practice_minutes"] == 0


def test_02_thirty_eight_minutes_meets_the_requirement_exactly():
    """One tick more flips the row and every ledger above it.

    PRD §3.4: "the athlete's `cumulative_practice_minutes` becomes the sum of
    `counted_minutes` over all of that athlete's attendance rows in `COUNTED`
    status across every season", and "The session's `recorded_attendance_count`
    increments — counting both `COUNTED` and `NOT_COUNTED` rows".

    Design: Difficulty/boundary_precision_check/attendance_counted_minutes_threshold_boundary
    """
    world = _fifty_minute_session_world()
    session, athletes = world["session"], world["athletes"]
    fx.record_attendance(session["id"], athletes[0]["id"], session["version"],
                         minutes_present=37)
    record_b = fx.record_attendance(session["id"], athletes[1]["id"],
                                    fx.session_version(session["id"]),
                                    minutes_present=38)
    assert record_b["required_minutes"] == 38
    assert record_b["status"] == "COUNTED"
    assert record_b["counted_minutes"] == 38

    athlete_b = validate_success(api_client.get_athlete(athletes[1]["id"], PM))
    assert athlete_b["cumulative_practice_minutes"] == 38
    assert athlete_b["counted_session_count"] == 1
    assert fx.get_program(world["program"]["id"])["program_practice_minutes"] == 38

    stored = validate_success(api_client.get_practice_session(session["id"], PM))
    assert stored["recorded_attendance_count"] == 2


def _cancelled_session_and_held_athlete():
    """A VOIDED session plus an athlete on medical HOLD — two live violations."""
    world = fx.setup_session_ready_world(
        athlete_specs=[
            {"athlete": {"legal_name": "Maya Foster", "birth_date": "2004-03-09"}}])
    cancelled = validate_success(api_client.cancel_practice_session(
        world["session"]["id"], f.cancel_session_payload(void_reason_code="WEATHER"),
        PM))
    fx.put_athlete_on_urgent_hold(
        world["athletes"][0]["id"], screened_on="2026-08-01",
        finding_note="Uncontrolled hypertension, immediate referral")
    fx.set_clock("2026-09-10T10:00:00Z")
    world["cancelled_version"] = cancelled["version"]
    return world


def test_03_cancelled_session_state_outranks_the_athletes_medical_hold():
    """The state error at priority 6 wins over the safety error at priority 8.

    PRD §2.6: band 6 is "**State preconditions of the target resource**,
    including stale-version rejection" and band 8 is "**Business safety** —
    medical clearance, attestation completeness, exam recency, protective-
    behaviours rules", so the state error is reported first.

    Design: Difficulty/priority_pair_validation_conflict/session_state_precedes_athlete_medical_safety
    """
    world = _cancelled_session_and_held_athlete()
    payload = f.create_attendance_payload(world["athletes"][0]["id"],
                                          world["cancelled_version"],
                                          minutes_present=50)
    response = api_client.create_attendance_record(world["session"]["id"],
                                                   payload, PM)
    error = validate_error(
        response, ApiErrorId.ERR_SESSION_NOT_OPEN_FOR_ATTENDANCE.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_ATHLETE_MEDICAL_HOLD.value
    assert error["error_id"] != ApiErrorId.ERR_STALE_SESSION_VERSION.value


def test_04_the_refused_attendance_call_writes_nothing():
    """A rejected write leaves the session and both ledgers exactly as they were.

    PRD §2.9: on a session write "Both endpoints increment the parent's `version`
    by one on success", so a refused call leaves the version and the counters
    exactly where they were.

    Design: Difficulty/priority_pair_validation_conflict/session_state_precedes_athlete_medical_safety
    """
    world = _cancelled_session_and_held_athlete()
    payload = f.create_attendance_payload(world["athletes"][0]["id"],
                                          world["cancelled_version"],
                                          minutes_present=50)
    validate_error(
        api_client.create_attendance_record(world["session"]["id"], payload, PM),
        ApiErrorId.ERR_SESSION_NOT_OPEN_FOR_ATTENDANCE.value, 409)

    listing = api_client.list_session_attendance_records(world["session"]["id"], PM)
    assert listing.json()["meta"]["total_count"] == 0
    session = validate_success(
        api_client.get_practice_session(world["session"]["id"], PM))
    assert session["status"] == "VOIDED"
    assert session["recorded_attendance_count"] == 0
    athlete = validate_success(
        api_client.get_athlete(world["athletes"][0]["id"], PM))
    assert athlete["cumulative_practice_minutes"] == 0
    assert athlete["counted_session_count"] == 0


def test_05_a_session_inside_the_coachs_fifteen_minute_buffer_is_refused():
    """The 10:00-11:00 session reserves [09:45, 11:15) for its credential.

    PRD §3.4: "a **15-minute buffer** surrounds every session that credential
    already holds in `SCHEDULED` or `HELD` status, so the existing session
    occupies the half-open interval running from 15 minutes before its start up
    to, but not including, 15 minutes after its end … If those two intervals
    overlap at all, the request is refused with `ERR_COACH_SESSION_OVERLAP`
    (409)."

    Design: Difficulty/resource_temporal_overlap/coach_credential_buffered_half_open_overlap
    """
    world = fx.setup_practice_ready_program()
    first = fx.schedule_session(world["season"]["id"], world["credential"]["id"],
                                scheduled_start="2026-09-10T10:00:00Z",
                                duration_minutes=60)
    assert_instant_equals(first["scheduled_end"], "2026-09-10T11:00:00.000Z",
                          "scheduled_end")
    assert first["status"] == "SCHEDULED"

    clashing = f.create_practice_session_payload(
        world["season"]["id"], world["credential"]["id"],
        scheduled_start="2026-09-10T11:10:00Z", duration_minutes=30)
    validate_error(api_client.create_practice_session(clashing, PM),
                   ApiErrorId.ERR_COACH_SESSION_OVERLAP.value, 409)

    listing = api_client.list_practice_sessions(
        PM, params={"season_id": world["season"]["id"]})
    assert listing.json()["meta"]["total_count"] == 1


def test_06_a_session_starting_at_the_buffer_boundary_is_accepted():
    """Half-open on the right: 11:15 belongs to the newcomer.

    PRD §3.4: "Because the buffered interval is closed on the left and open on
    the right, a gap of exactly 15 minutes between one session's end and the next
    session's start is permitted"; and `counts_toward_minimum` "is true when the
    duration is at least 45 minutes and the session has not been voided".

    Design: Difficulty/resource_temporal_overlap/coach_credential_buffered_half_open_overlap
    """
    world = fx.setup_practice_ready_program()
    first = fx.schedule_session(world["season"]["id"], world["credential"]["id"],
                                scheduled_start="2026-09-10T10:00:00Z",
                                duration_minutes=60)
    clashing = f.create_practice_session_payload(
        world["season"]["id"], world["credential"]["id"],
        scheduled_start="2026-09-10T11:10:00Z", duration_minutes=30)
    validate_error(api_client.create_practice_session(clashing, PM),
                   ApiErrorId.ERR_COACH_SESSION_OVERLAP.value, 409)

    boundary = f.create_practice_session_payload(
        world["season"]["id"], world["credential"]["id"],
        scheduled_start="2026-09-10T11:15:00Z", duration_minutes=30)
    second = validate_success(api_client.create_practice_session(boundary, PM), 201)
    assert second["status"] == "SCHEDULED"
    assert_instant_equals(second["scheduled_end"], "2026-09-10T11:45:00.000Z",
                          "scheduled_end")
    assert second["counts_toward_minimum"] is False
    assert first["counts_toward_minimum"] is True

    listing = api_client.list_practice_sessions(
        PM, params={"season_id": world["season"]["id"]})
    assert listing.json()["meta"]["total_count"] == 2


def _two_coach_back_to_back_world():
    """Back-to-back sessions under two credentials, one athlete already on the first."""
    world = fx.setup_practice_ready_program()
    second_coach = fx.setup_program_with_second_coach(
        world, screening_overrides={"vendor_reference": "BGS-1004"})
    athlete, _form = fx.create_active_athlete(world["program"]["id"])
    session_1 = fx.schedule_session(world["season"]["id"],
                                    world["credential"]["id"],
                                    scheduled_start="2026-09-10T10:00:00Z",
                                    duration_minutes=60)
    session_2 = fx.schedule_session(world["season"]["id"],
                                    second_coach["credential"]["id"],
                                    scheduled_start="2026-09-10T11:00:00Z",
                                    duration_minutes=60)
    fx.set_clock("2026-09-10T11:00:00Z")
    record = fx.record_attendance(session_1["id"], athlete["id"],
                                  session_1["version"], minutes_present=60)
    world.update({"athlete": athlete, "session_1": session_1,
                  "session_2": session_2, "record": record,
                  "session_2_version": session_2["version"]})
    return world


def test_07_closed_athlete_intervals_that_merely_touch_do_collide():
    """The athlete rule has no buffer and closed endpoints, unlike the coach rule.

    PRD §3.4: "if the athlete already has a `COUNTED` or `NOT_COUNTED` attendance
    row on another session … whose **closed** interval from its start through its
    end intersects this session's closed interval, the request is refused with
    `ERR_ATHLETE_SESSION_OVERLAP` (409) — no buffer applies to athletes, but
    sessions that merely touch endpoints do conflict."

    Design: Difficulty/resource_temporal_overlap/athlete_closed_interval_no_buffer_overlap
    """
    world = _two_coach_back_to_back_world()
    payload = f.create_attendance_payload(world["athlete"]["id"],
                                          world["session_2_version"],
                                          minutes_present=60)
    error = validate_error(
        api_client.create_attendance_record(world["session_2"]["id"], payload, PM),
        ApiErrorId.ERR_ATHLETE_SESSION_OVERLAP.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_COACH_SESSION_OVERLAP.value
    assert world["session_1"]["coach_credential_id"] != \
        world["session_2"]["coach_credential_id"]


def test_08_the_refused_overlap_leaves_the_second_session_and_ledgers_intact():
    """Only the first session's minutes are in the ledgers.

    PRD §3.4: the program figure "must always equal the sum of `counted_minutes`
    over every `COUNTED` attendance row belonging to the program's athletes";
    PRD §2.9: "Both endpoints increment the parent's `version` by one on
    success".

    Design: Difficulty/resource_temporal_overlap/athlete_closed_interval_no_buffer_overlap
    """
    world = _two_coach_back_to_back_world()
    payload = f.create_attendance_payload(world["athlete"]["id"],
                                          world["session_2_version"],
                                          minutes_present=60)
    validate_error(
        api_client.create_attendance_record(world["session_2"]["id"], payload, PM),
        ApiErrorId.ERR_ATHLETE_SESSION_OVERLAP.value, 409)

    untouched = validate_success(
        api_client.get_practice_session(world["session_2"]["id"], PM))
    assert untouched["recorded_attendance_count"] == 0
    assert untouched["status"] == "SCHEDULED"
    assert untouched["version"] == world["session_2_version"]

    assert world["record"]["status"] == "COUNTED"
    assert world["record"]["counted_minutes"] == 60
    athlete = validate_success(api_client.get_athlete(world["athlete"]["id"], PM))
    assert athlete["cumulative_practice_minutes"] == 60
    assert athlete["counted_session_count"] == 1
    assert fx.get_program(world["program"]["id"])["program_practice_minutes"] == 60


def _session_with_two_counted_rows():
    """110 counted minutes spread over two athletes on one 60-minute session."""
    world = fx.setup_session_ready_world(
        athlete_specs=[
            {"athlete": {"legal_name": "Maya Foster", "birth_date": "2004-03-09"}},
            {"athlete": {"legal_name": "Ivan Petrov", "birth_date": "2003-10-01"}},
        ],
        attendance_clock="2026-09-10T10:00:00Z")
    session = world["session"]
    record_a = fx.record_attendance(session["id"], world["athletes"][0]["id"],
                                    session["version"], minutes_present=60)
    record_b = fx.record_attendance(session["id"], world["athletes"][1]["id"],
                                    fx.session_version(session["id"]),
                                    minutes_present=50)
    world["record_a"], world["record_b"] = record_a, record_b
    return world


def test_09_cancelling_a_session_voids_its_rows_but_keeps_their_history():
    """The compensation zeroes counted_minutes and preserves the observed inputs.

    PRD §3.4: cancelling a session in `HELD` "unwinds everything beneath it:
    every attendance row of the session in `COUNTED` or `NOT_COUNTED` status
    becomes `VOIDED` with its `counted_minutes` set to 0", the stored
    `required_minutes` being kept "so that a later change to the session can
    never rewrite history".

    Design: Difficulty/compensating_invariant/session_cancel_conserves_practice_minute_ledger
    """
    world = _session_with_two_counted_rows()
    assert world["record_a"]["counted_minutes"] == 60
    assert world["record_b"]["counted_minutes"] == 50

    cancelled = validate_success(api_client.cancel_practice_session(
        world["session"]["id"],
        f.cancel_session_payload(void_reason_code="WEATHER"), PM))
    assert cancelled["status"] == "VOIDED"
    assert cancelled["void_reason_code"] == "WEATHER"

    rows = api_client.list_session_attendance_records(
        world["session"]["id"], PM, params={"limit": 100}).json()["data"]
    by_id = {row["id"]: row for row in rows}
    row_a = by_id[world["record_a"]["id"]]
    row_b = by_id[world["record_b"]["id"]]
    assert row_a["status"] == "VOIDED" and row_a["counted_minutes"] == 0
    assert row_a["minutes_present"] == 60 and row_a["required_minutes"] == 45
    assert row_b["status"] == "VOIDED" and row_b["counted_minutes"] == 0
    assert row_b["minutes_present"] == 50


def test_10_cancellation_removes_exactly_the_minutes_it_created():
    """Every level of the ledger returns to its pre-attendance value.

    PRD §3.4: "each affected athlete decrements `cumulative_practice_minutes` by
    exactly the minutes reversed and `counted_session_count` by the number of
    formerly-`COUNTED` rows reversed; and because the athlete ledgers changed,
    the program's `program_practice_minutes` is recomputed so the conservation
    invariant continues to hold."

    Design: Difficulty/compensating_invariant/session_cancel_conserves_practice_minute_ledger
    """
    world = _session_with_two_counted_rows()
    assert fx.get_program(world["program"]["id"])["program_practice_minutes"] == 110

    validate_success(api_client.cancel_practice_session(
        world["session"]["id"],
        f.cancel_session_payload(void_reason_code="WEATHER"), PM))

    for athlete in world["athletes"]:
        after = validate_success(api_client.get_athlete(athlete["id"], PM))
        assert after["cumulative_practice_minutes"] == 0
        assert after["counted_session_count"] == 0
    assert fx.get_program(world["program"]["id"])["program_practice_minutes"] == 0
    season = validate_success(api_client.get_season(world["season"]["id"], CD))
    assert season["status"] == "PRACTICE_OPEN"
