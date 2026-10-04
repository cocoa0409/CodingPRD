"""Sortation scheduling, the manual-inspection gate and the outage rate limit."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    set_clock, base_scenario, get_bag, get_station, get_area, get_flight,
    list_rows, make_sorted_bag, make_in_makeup_bag, make_inspection_task,
    create_bag_payload, create_assign_makeup_payload, run_ops,
    declare_outage, clear_outage, create_special_item_payload, weigh_ok,
    screen_ok, board_and_depart, open_flight_for_sortation,
)


def test_assigning_makeup_onto_a_flight_that_is_no_longer_sorting_is_refused(api):
    """PRD §2.9: "Assignment onto a flight is refused unless the flight's `status`
    is `SCHEDULED` or `SORT_OPEN`, with `ERR_FLIGHT_NOT_SORTING` (HTTP 409)."
    PRD §3.6: "that flight must be in status `SCHEDULED` or `SORT_OPEN`
    (`ERR_FLIGHT_NOT_SORTING`, 409)"

    Design: Difficulty/cross_entity_state_dependency/bag_sortation_advance_depends_on_the_flight_status_and_the_clock
    """
    scenario = base_scenario()
    bag = make_sorted_bag(scenario)
    # PRD §2.9 names SCHEDULED and SORT_OPEN as the two admissible statuses, so
    # the refusal belongs to a flight that has left them — here one that has
    # already departed.
    board_and_depart(scenario)
    assert get_flight(scenario["f1"])["status"] == "DEPARTED"
    fresh = get_bag(bag["id"])

    response = api.assign_makeup(
        fresh["id"],
        create_assign_makeup_payload(fresh["version"], scenario["ma"], "2026-09-01T14:16:00Z"),
        TEST_USERS["sortation_agent_headers"])
    validate_error(response, ApiErrorId.ERR_FLIGHT_NOT_SORTING, 409)

    after = get_bag(bag["id"])
    assert after["custody_status"] == "SORTED", "the bag itself was perfectly sortable"


def test_the_same_assignment_succeeds_once_the_checkpoint_opens_the_flight(api):
    """PRD §2.9: "`sortation_open_utc` is derived as exactly 120 minutes before it
    and is the earliest instant a bag may be inducted for that flight"

    Design: Difficulty/cross_entity_state_dependency/bag_sortation_advance_depends_on_the_flight_status_and_the_clock
    """
    scenario = base_scenario()
    bag = make_sorted_bag(scenario)
    open_flight_for_sortation(scenario)
    assert get_flight(scenario["f1"])["status"] == "SORT_OPEN"

    fresh = get_bag(bag["id"])
    accepted = validate_success(api.assign_makeup(
        fresh["id"],
        create_assign_makeup_payload(fresh["version"], scenario["ma"], "2026-09-01T13:05:00Z"),
        TEST_USERS["sortation_agent_headers"]), 200)
    assert accepted["custody_status"] == "IN_MAKEUP"
    assert accepted["assigned_makeup_utc"] == "2026-09-01T13:05:00Z"


def test_loading_after_the_sortation_window_closes_is_refused(api):
    """PRD §2.9: "Induction and loading are refused once the current logical clock
    instant has passed `sortation_close_utc`, with `ERR_SORTATION_WINDOW_CLOSED`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/bag_sortation_advance_depends_on_the_flight_status_and_the_clock
    """
    scenario = base_scenario()
    bag = make_in_makeup_bag(scenario)

    set_clock("2026-09-01T14:20:00Z")
    response = api.load_bag(bag["id"], TEST_USERS["load_agent_headers"])
    validate_error(response, ApiErrorId.ERR_SORTATION_WINDOW_CLOSED, 409)

    after = get_bag(bag["id"])
    assert after["custody_status"] == "IN_MAKEUP", \
        "14:20 is past the 14:15 close, so the otherwise loadable bag is refused"


def test_delivering_a_bag_whose_flight_has_not_departed_is_refused(api):
    """PRD §2.9: "A bag whose flight has not reached `DEPARTED` may not be marked
    delivered, which is refused with `ERR_FLIGHT_NOT_DEPARTED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/bag_sortation_advance_depends_on_the_flight_status_and_the_clock
    """
    from test_helpers import make_loaded_bag

    scenario = base_scenario()
    bag = make_loaded_bag(scenario)

    response = api.deliver_bag(bag["id"], TEST_USERS["load_agent_headers"])
    validate_error(response, ApiErrorId.ERR_FLIGHT_NOT_DEPARTED, 409)


def test_a_suspended_station_refuses_a_load_before_the_state_check(api):
    """PRD §2.6: "While a station reads `SUSPENDED` — whether because a sortation
    outage is active or because its sorter is full — every sortation, loading and
    delivery write against a bag of custody at that station is refused with
    `ERR_STATION_SUSPENDED` and HTTP 409, and that refusal is applied before any
    state precondition is examined."

    Design: Difficulty/priority_pair_validation_conflict/station_suspended_beats_invalid_custody_state
    """
    scenario = base_scenario()
    bag = make_sorted_bag(scenario)
    assert bag["custody_status"] == "SORTED"

    declare_outage(scenario)
    response = api.load_bag(bag["id"], TEST_USERS["load_agent_headers"])
    validate_error(response, ApiErrorId.ERR_STATION_SUSPENDED, 409)


def test_the_suspended_station_refusal_leaves_the_bag_untouched(api):
    """PRD §2.12: "A mismatch between the supplied token and the parent entity's
    current `version` is rejected with `ERR_STALE_VERSION` and HTTP 412, and no
    part of the operation is applied."

    Design: Difficulty/priority_pair_validation_conflict/station_suspended_beats_invalid_custody_state
    """
    scenario = base_scenario()
    bag = make_sorted_bag(scenario)
    before = bag["version"]

    declare_outage(scenario)
    api.load_bag(bag["id"], TEST_USERS["load_agent_headers"])

    after = get_bag(bag["id"])
    assert after["custody_status"] == "SORTED"
    assert after["version"] == before


def test_clearing_the_outage_exposes_the_state_precondition_again(api):
    """PRD §2.13: "While a station reads `SUSPENDED` — whether because a sortation outage is active or because its sorter is full — every sortation, loading and delivery write against a bag of custody at that station is refused with `ERR_STATION_SUSPENDED` and HTTP 409"

    Design: Difficulty/priority_pair_validation_conflict/station_suspended_beats_invalid_custody_state
    """
    scenario = base_scenario()
    bag = make_sorted_bag(scenario)
    declare_outage(scenario)
    api.load_bag(bag["id"], TEST_USERS["load_agent_headers"])

    clear_outage(scenario)
    response = api.load_bag(bag["id"], TEST_USERS["load_agent_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)


def test_a_sortation_advance_is_refused_while_an_inspection_task_is_open(api):
    """PRD §2.13: "A sortation or load advance is refused while the bag has an open inspection task in status `QUEUED` or `IN_PROGRESS`, reported as `ERR_MANUAL_INSPECTION_REQUIRED` (409)."

    Design: Difficulty/transitive_cascade/manual_inspection_blocks_the_flight_and_the_override_costs_credit
    """
    scenario = base_scenario()
    bag, task = make_inspection_task(scenario)
    assert bag["custody_status"] == "IN_MAKEUP"
    assert task["status"] == "QUEUED"

    response = api.load_bag(bag["id"], TEST_USERS["load_agent_headers"])
    validate_error(response, ApiErrorId.ERR_MANUAL_INSPECTION_REQUIRED, 409)


def test_an_open_inspection_task_clears_the_flight_readiness_flag(api):
    """PRD §2.11: "A flight's `makeup_ready` flag is true only when two conditions
    hold together: the flight has no bag whose custody status is `HELD`, and none
    of its bags has an open manual inspection task in status `QUEUED` or
    `IN_PROGRESS`."

    Design: Difficulty/transitive_cascade/manual_inspection_blocks_the_flight_and_the_override_costs_credit
    """
    scenario = base_scenario()
    assert get_flight(scenario["f1"])["makeup_ready"] is True

    bag, task = make_inspection_task(scenario)
    assert get_flight(scenario["f1"])["makeup_ready"] is False, \
        "the open queued task cleared the readiness flag"


def test_resolving_the_task_restores_flight_readiness_and_queue_depth(api):
    """PRD §2.11: "`ESCALATED` and `RESOLVED` tasks do not block readiness, and a
    bag merely held at screening does block it."

    Design: Difficulty/transitive_cascade/manual_inspection_blocks_the_flight_and_the_override_costs_credit
    """
    scenario = base_scenario()
    # PRD §3.3: a task is resolved only while the screening event that raised it
    # is still ALARMED, so the task comes from the alarm route.
    from test_helpers import make_alarmed_inspection_task
    bag, event, task = make_alarmed_inspection_task(scenario)
    api.resolve_inspection(task["id"], "CLEARED", TEST_USERS["screener_headers"])
    assert get_station(scenario["st"])["manual_queue_depth"] == 0, \
        "the resolved task left the {QUEUED, IN_PROGRESS} set"

    # Clearing the task does not release the bag from HELD custody (PRD §3.3);
    # re-induction does, and the station's outage admits it.
    declare_outage(scenario)
    reinducted = weigh_ok(bag["id"], 48.0)
    assert reinducted["custody_status"] == "ACCEPTED"

    assert get_flight(scenario["f1"])["makeup_ready"] is True
