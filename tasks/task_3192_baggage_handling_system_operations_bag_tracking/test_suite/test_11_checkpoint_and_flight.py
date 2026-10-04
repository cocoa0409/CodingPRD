"""The operations checkpoint, the flight timeline and station run_ops sweeps."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    set_clock, base_scenario, get_bag, get_station, get_area, get_flight,
    list_rows, make_sorted_bag, make_in_makeup_bag, make_loaded_bag,
    create_bag_payload, create_assign_makeup_payload, board_and_depart,
    run_ops, create_flight_payload, make_flight,
)


def test_a_stale_accepted_bag_expires_on_the_second_checkpoint(api):
    """PRD §3.13: "any bag of the station whose custody status is still
    `ACCEPTED` and whose `ops_run_index_at_acceptance` is at least two behind the
    station's current `ops_run_index` is moved to `HELD` custody with a screening
    status of `FAILED`"

    Design: Corner/endpoints/station_run_ops_expires_a_stale_accepted_bag
    """
    scenario = base_scenario()
    old = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], passenger_ref="PNR9K3L"),
        TEST_USERS["acceptance_agent_headers"]))

    run_ops(scenario["st"])
    run_ops(scenario["st"])
    fresh = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], passenger_ref="PNR7X2Q"),
        TEST_USERS["acceptance_agent_headers"]))

    station = get_success_data(run_ops(scenario["st"]))
    assert station["ops_run_index"] == 3

    expired = get_bag(old["id"])
    assert expired["custody_status"] == "HELD"
    assert expired["screening_status"] == "FAILED"
    assert get_bag(fresh["id"])["custody_status"] == "ACCEPTED", \
        "a bag accepted in the immediately preceding run lags by only one"


def test_an_expired_bag_stays_in_the_active_population(api):
    """PRD §2.6: "The bag count that drives this rule is the count of the
    station's bags whose custody status is one of `ACCEPTED`, `SCREENING`,
    `SORTED`, `IN_MAKEUP`, `LOADED` or `HELD`"
    PRD §3.13: "Running it increments the station's `ops_run_index` — a monotone
    counter, starting at zero, that only ever increases"

    Design: Corner/endpoints/station_run_ops_expires_a_stale_accepted_bag
    """
    scenario = base_scenario()
    old = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], passenger_ref="PNR9K3L"),
        TEST_USERS["acceptance_agent_headers"]))
    run_ops(scenario["st"])
    run_ops(scenario["st"])
    api.create_bag(create_bag_payload(scenario["st"], passenger_ref="PNR7X2Q"),
                   TEST_USERS["acceptance_agent_headers"])
    run_ops(scenario["st"])

    station = get_station(scenario["st"])
    assert station["active_bag_count"] == 2, "a held bag remains physically inside the station"

    scans = list_rows(api.list_bag_scans(old["id"], TEST_USERS["acceptance_agent_headers"]))
    assert scans == [], "the expiry appends no scan capture"


def test_cancelling_a_flight_releases_the_make_up_slots_it_was_building(api):
    """PRD §3.13: "Cancelling releases the flight's sorted bags back into the
    sortation pool: every bag whose `flight_id` is this flight and whose custody
    status is `SORTED` or `IN_MAKEUP` has its custody status returned to `SORTED`
    and both its `flight_id` and its `makeup_area_id` cleared, so it carries no
    flight assignment and holds no make-up slot."

    Design: Corner/endpoints/flight_cancel_clears_the_makeup_areas_it_was_building
    """
    scenario = base_scenario(makeup_capacity_slots=2)
    first = make_in_makeup_bag(scenario, bag_index=0,
                               induction_utc="2026-09-01T13:12:00Z")
    second = make_in_makeup_bag(scenario, bag_index=1,
                                induction_utc="2026-09-01T13:36:00Z")
    set_clock("2026-09-01T12:30:00Z")
    run_ops(scenario["st"])
    set_clock("2026-09-01T13:05:00Z")
    run_ops(scenario["st"])

    assert get_flight(scenario["f1"])["status"] == "SORT_OPEN"
    assert get_area(scenario["ma"])["occupied_slots"] == 2

    cancelled = validate_success(api.cancel_flight(scenario["f1"],
                                                   TEST_USERS["platform_admin_headers"]), 200)
    assert cancelled["status"] == "CANCELLED"

    assert get_area(scenario["ma"])["occupied_slots"] == 0
    assert get_area(scenario["ma"])["free_slots"] == 2
    for bag in (first, second):
        after = get_bag(bag["id"])
        assert after["custody_status"] == "SORTED"
        assert after.get("makeup_area_id") is None
        assert after.get("flight_id") is None


def test_a_cancelled_flight_returns_the_station_to_open_posture(api):
    """PRD §3.13: "The affected make-up areas' slot ledgers are recomputed and
    the station's posture is recomputed afterwards, since the released bags have
    given their slots back."

    Design: Corner/endpoints/flight_cancel_clears_the_makeup_areas_it_was_building
    """
    scenario = base_scenario(makeup_capacity_slots=2)
    make_in_makeup_bag(scenario, bag_index=0, induction_utc="2026-09-01T13:12:00Z")
    make_in_makeup_bag(scenario, bag_index=1, induction_utc="2026-09-01T13:36:00Z")
    set_clock("2026-09-01T12:30:00Z")
    run_ops(scenario["st"])
    set_clock("2026-09-01T13:05:00Z")
    run_ops(scenario["st"])
    api.cancel_flight(scenario["f1"], TEST_USERS["platform_admin_headers"])

    station = get_station(scenario["st"])
    assert station["posture"] == "OPEN", "the slots came back, so the congested bound no longer bites"
    assert station["active_bag_count"] == 2


def test_derived_counters_are_correct_in_the_mutating_response_itself(api):
    """PRD §2.11: "Several aggregates are recomputed whenever their inputs move,
    and they are read from the owning resource rather than recomputed by the
    caller."

    Design: Corner/consistency_model/computed_counters_are_visible_in_the_same_response_that_mutates_them
    """
    scenario = base_scenario()
    bag = make_sorted_bag(scenario)

    set_clock("2026-09-01T13:40:00Z")
    assigned = validate_success(api.assign_makeup(
        bag["id"],
        create_assign_makeup_payload(bag["version"], scenario["ma"], "2026-09-01T13:40:00Z"),
        TEST_USERS["sortation_agent_headers"]), 200)
    assert assigned["custody_status"] == "IN_MAKEUP"

    area_after_assign = get_area(scenario["ma"])
    assert area_after_assign["occupied_slots"] == 1, \
        "the area reads 1 right after the assignment, with no follow-up write"

    loaded = validate_success(api.load_bag(assigned["id"],
                                           TEST_USERS["load_agent_headers"]), 200)
    area_after_load = get_area(scenario["ma"])
    assert area_after_load["occupied_slots"] == 0, "LOADED releases the slot"
    assert get_flight(scenario["f1"])["loaded_bag_count"] == 1
    assert get_station(scenario["st"])["active_bag_count"] == 1, \
        "LOADED remains inside the station envelope"


def test_a_flight_derives_its_sortation_window_from_the_scheduled_departure(api):
    """PRD §2.9: "`sortation_open_utc` is derived as exactly 120 minutes before it
    and is the earliest instant a bag may be inducted for that flight;
    `sortation_close_utc` is derived as exactly 45 minutes before it"

    Design: Corner/calculations/connection_slack_minutes_truncates_the_departure_difference
    """
    scenario = base_scenario()
    onward = make_flight(scenario, flight_number="DL1788", bank_code="B2",
                         scheduled_departure_utc="2026-09-01T17:32:30Z")
    flight = get_flight(onward["id"])
    assert flight["sortation_open_utc"] == "2026-09-01T15:32:30Z"
    assert flight["sortation_close_utc"] == "2026-09-01T16:47:30Z"
    assert flight["status"] == "SCHEDULED"
    assert flight["makeup_ready"] is True, "a flight with no bags reads ready"


def test_the_sortation_checkpoint_opens_a_scheduled_flight(api):
    """PRD §3.13: "A `SCHEDULED` flight becomes `SORT_OPEN` once the current
    logical clock instant reaches its `sortation_open_utc`, so bags may begin to
    be inducted against it."

    Design: Difficulty/cross_entity_state_dependency/bag_sortation_advance_depends_on_the_flight_status_and_the_clock
    """
    scenario = base_scenario()
    assert get_flight(scenario["f1"])["status"] == "SCHEDULED"

    set_clock("2026-09-01T12:00:00Z")
    run_ops(scenario["st"])
    assert get_flight(scenario["f1"])["status"] == "SCHEDULED", \
        "13:00 is the open instant and the clock has not reached it"

    set_clock("2026-09-01T13:05:00Z")
    run_ops(scenario["st"])
    assert get_flight(scenario["f1"])["status"] == "SORT_OPEN"