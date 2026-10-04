"""Optimistic concurrency control and the immutability of refused transitions."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    set_clock, base_scenario, get_bag, get_station, get_area, get_flight,
    list_rows, weigh_ok, make_sorted_bag, make_loaded_bag, make_in_makeup_bag,
    screen_ok, create_bag_payload, create_assign_makeup_payload,
)


def test_a_stale_bag_version_on_the_correction_write_is_refused(api):
    """PRD §2.12: "Editing a bag's particulars through the bag correction write
    requires `expected_bag_version`, which must equal the target bag's current
    `version`."
    PRD §2.12: "A mismatch between the supplied token and the parent entity's
    current `version` is rejected with `ERR_STALE_VERSION` and HTTP 412, and no
    part of the operation is applied."

    Design: Corner/cross_cutting_complexity_layers/bag_mutation_with_a_stale_version_is_rejected
    """
    scenario = base_scenario()
    bag = make_sorted_bag(scenario)
    assert bag["version"] == 3, "acceptance, weigh and the clean screening each advanced the bag"

    stale = api.update_bag(
        bag["id"], {"expected_bag_version": bag["version"] - 1, "weight_lb": 49},
        TEST_USERS["screener_headers"])
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

    after = get_bag(bag["id"])
    assert after["weight_lb"] == 48, "no part of the rejected operation is applied"
    assert after["version"] == bag["version"]


def test_the_current_version_token_is_accepted(api):
    """PRD §2.12: "the version token is a non-optional input field."

    Design: Corner/cross_cutting_complexity_layers/bag_mutation_with_a_stale_version_is_rejected
    """
    scenario = base_scenario()
    bag = make_sorted_bag(scenario)

    accepted = validate_success(api.update_bag(
        bag["id"], {"expected_bag_version": bag["version"], "weight_lb": 49},
        TEST_USERS["screener_headers"]), 200)
    assert accepted["weight_lb"] == 49
    assert accepted["version"] == bag["version"] + 1

    replay = api.update_bag(
        bag["id"], {"expected_bag_version": bag["version"], "weight_lb": 50},
        TEST_USERS["screener_headers"])
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION, 412)


def test_a_stale_version_on_makeup_assignment_is_refused(api):
    """PRD §2.12: "Assigning a make-up interval requires `expected_bag_version`
    as well, matching the same bag's current `version`."
    PRD §3.5: "Every one of these writes advances the bag's `version`, which is
    exactly why the version tokens described in §2.12 go stale so readily."

    Design: Corner/cross_cutting_complexity_layers/makeup_assignment_with_a_stale_version_is_rejected
    """
    scenario = base_scenario()
    bag = make_sorted_bag(scenario)
    observed = bag["version"]

    # PRD §2.4: a row's `version` "increments by one on every modification to the
    # row", and §2.12 observes that a bag's version "advances legitimately
    # whenever its screening axis is written ... so a client that read the bag
    # before any of those and then writes back is carrying a stale view".
    api.add_scan(bag["id"], {"scan_point": "MAKEUP"}, TEST_USERS["sortation_agent_headers"])
    assert get_bag(bag["id"])["version"] == observed + 1

    set_clock("2026-09-01T13:00:00Z")
    stale = api.assign_makeup(
        bag["id"],
        create_assign_makeup_payload(observed, scenario["ma"], "2026-09-01T13:12:00Z"),
        TEST_USERS["sortation_agent_headers"])
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

    after = get_bag(bag["id"])
    assert after["custody_status"] == "SORTED"


def test_the_refreshed_version_token_lands_the_makeup_assignment(api):
    """PRD §3.6: "An accepted claim moves the bag's custody to `IN_MAKEUP`,
    writes the target into `makeup_area_id`, and records the supplied
    `induction_utc` into `assigned_makeup_utc`"

    Design: Corner/cross_cutting_complexity_layers/makeup_assignment_with_a_stale_version_is_rejected
    """
    scenario = base_scenario()
    bag = make_sorted_bag(scenario)
    observed = bag["version"]

    note = validate_success(api.update_bag(
        bag["id"], {"expected_bag_version": observed, "anomaly_note": "post-sortation recheck"},
        TEST_USERS["screener_headers"]), 200)
    assert note["version"] == observed + 1, \
        "the anomaly note on the screening axis advanced the bag"

    # The anomaly note tore up the clearance (CLEARED -> IN_LINE), so the bag is
    # re-screened cleanly, which clears it again and restores the sortation stage.
    screen_ok(bag["id"], scenario["lane"], "2026-09-01T07:40:00Z")
    cleared = get_bag(bag["id"])
    assert cleared["screening_status"] == "CLEARED"

    set_clock("2026-09-01T13:00:00Z")
    accepted = validate_success(api.assign_makeup(
        bag["id"],
        create_assign_makeup_payload(cleared["version"], scenario["ma"], "2026-09-01T13:12:00Z"),
        TEST_USERS["sortation_agent_headers"]), 200)
    assert accepted["custody_status"] == "IN_MAKEUP"
    assert accepted["assigned_makeup_utc"] == "2026-09-01T13:12:00Z"
    assert get_area(scenario["ma"])["occupied_slots"] == 1


def test_a_stale_version_on_report_reopen_is_refused(api):
    """PRD §3.11: "Reopening also demands the `expected_report_version` token
    described in §2.12, and a stale token is refused with `ERR_STALE_VERSION`
    (412)."

    Design: Corner/cross_cutting_complexity_layers/bag_mutation_with_a_stale_version_is_rejected
    """
    from test_helpers import delivered_bag_with_report, report_through_compensated

    scenario = base_scenario()
    _, bag, report = delivered_bag_with_report(scenario)
    compensated = report_through_compensated(scenario, report["id"])

    stale = api.reopen_report(report["id"], compensated["version"] - 1,
                              TEST_USERS["baggage_service_agent_headers"])
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

    still = get_success_data(api.get_report(report["id"],
                                            TEST_USERS["baggage_service_agent_headers"]))
    assert still["status"] == "COMPENSATED"


def test_refused_transitions_leave_every_derived_counter_untouched(api):
    """PRD §2.4: "Derived attributes — a bag's `priority_score`, a station's
    `posture`, a flight's `makeup_ready` — are mutations like any other"
    PRD §2.6: "The bag count that drives this rule is the count of the station's
    bags whose custody status is one of `ACCEPTED`, `SCREENING`, `SORTED`,
    `IN_MAKEUP`, `LOADED` or `HELD`"

    Design: Corner/consistency_model/invalid_transition_refusals_leave_every_derived_counter_untouched
    """
    scenario = base_scenario()
    bag = make_loaded_bag(scenario)
    station_before = get_station(scenario["st"])

    second_load = api.load_bag(bag["id"], TEST_USERS["load_agent_headers"])
    validate_error(second_load, ApiErrorId.ERR_INVALID_STATE, 409)

    weigh_refused = api.weigh_bag(bag["id"], 48.5, TEST_USERS["acceptance_agent_headers"])
    validate_error(weigh_refused, ApiErrorId.ERR_INVALID_STATE, 409)

    fresh = get_bag(bag["id"])
    refused_assign = api.assign_makeup(
        bag["id"],
        create_assign_makeup_payload(fresh["version"], scenario["ma"],
                                     "2026-09-01T13:48:00Z"),
        TEST_USERS["sortation_agent_headers"])
    validate_error(refused_assign, ApiErrorId.ERR_INVALID_STATE, 409)

    after = get_bag(bag["id"])
    station_after = get_station(scenario["st"])
    assert after["custody_status"] == "LOADED"
    assert after["version"] == fresh["version"]
    assert station_after["active_bag_count"] == 1
    assert station_after["version"] == station_before["version"]
    assert get_flight(scenario["f1"])["loaded_bag_count"] == 1
    assert get_area(scenario["ma"])["occupied_slots"] == 0

    scans = list_rows(api.list_bag_scans(bag["id"], TEST_USERS["load_agent_headers"]))
    assert len(scans) == 4, \
        "weigh INDUCTION, SCREENING, MAKEUP and LOAD; no refusal appends one"