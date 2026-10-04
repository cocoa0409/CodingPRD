"""The passenger tracking lookup and the screening-window timing rules."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    set_clock, base_scenario, get_bag, get_area, get_flight, list_rows,
    make_sorted_bag, make_in_makeup_bag, make_passenger_headers,
    create_bag_payload, create_screening_payload, weigh_ok, screen_ok,
    make_transfer_bag, make_flight, create_connection_payload,
)


def test_tracking_lookup_returns_the_positional_bundle(api):
    """PRD §3.7: "The lookup returns the `tag_number`, the `custody_status`, the
    `screening_status`, the `last_scan_point` and `last_scan_utc` of the most
    recent capture, an `onboard` boolean, the `connection_status`, the
    `manual_sortation_delay_minutes` figure, and an `open_reports` count
    summarising the reports still being worked on the bag."

    Design: Corner/endpoints/tracking_lookup_returns_the_passenger_tracking_bundle
    """
    scenario = base_scenario()
    bag = make_in_makeup_bag(scenario, bag_index=0, induction_utc="2026-09-01T13:40:00Z")

    response = api.tracking_lookup(
        bag["tag_number"], make_passenger_headers(bag["passenger_ref"]))
    bundle = validate_success(response, 200)

    assert bundle["tag_number"] == bag["tag_number"]
    assert bundle["custody_status"] == "IN_MAKEUP"
    assert bundle["screening_status"] == "CLEARED"
    assert bundle["last_scan_point"] == "SORTATION"
    assert bundle["last_scan_utc"] == "2026-09-01T13:40:00Z"
    assert bundle["onboard"] is False, "the bag has not been loaded"
    assert bundle.get("connection_status") is None, "the bag carries no Connection row"
    assert bundle["open_reports"] == 0
    assert bundle["manual_sortation_delay_minutes"] == 0, "no outage is active"


def test_tracking_bundle_scan_trail_is_ordered_by_scan_utc(api):
    """PRD §3.7: "The scan trail that backs those last-scan fields is the bag's
    `scan_trail`, a passenger-visible chain of captures each carrying its
    `scan_point`, its `scan_source` and its `scan_utc`, ordered by `scan_utc`
    ascending with `created_at` ascending breaking ties."

    Design: Corner/endpoints/tracking_lookup_returns_the_passenger_tracking_bundle
    """
    scenario = base_scenario()
    bag = make_in_makeup_bag(scenario, bag_index=0, induction_utc="2026-09-01T13:40:00Z")

    bundle = get_success_data(api.tracking_lookup(
        bag["tag_number"], make_passenger_headers(bag["passenger_ref"])))
    trail = bundle["scan_trail"]
    assert [row["scan_point"] for row in trail] == ["INDUCTION", "SORTATION"], \
        "an alarm-free induction IS the clearance (PRD §3.2), so the trail carries no SCREENING capture"

    stamps = [row["scan_utc"] for row in trail]
    assert stamps == sorted(stamps), "the trail is ordered by scan_utc ascending"


def test_a_passenger_may_not_read_another_passengers_bag(api):
    """PRD §3.7: "A passenger may read only their own bags: the `Passenger` role's
    identity is entity-backed by `passenger_ref`, so the tracking lookup and the
    per-bag reads all compare the acting identity against that field and reject
    anything else with `ERR_FORBIDDEN_ROLE` (403)."

    Design: Corner/endpoints/tracking_lookup_returns_the_passenger_tracking_bundle
    """
    scenario = base_scenario()
    bag = make_in_makeup_bag(scenario, bag_index=0, induction_utc="2026-09-01T13:40:00Z")

    denied = api.tracking_lookup(bag["tag_number"], make_passenger_headers("PNR4M1T"))
    validate_error(denied, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


def test_a_screening_window_closes_exactly_twenty_minutes_later(api):
    """PRD §2.8: "A screening window is the half-open interval from a supplied
    `start_utc` to twenty minutes later"

    Design: Corner/state_machines/resolved_screening_reopen_requires_a_closed_window
    """
    scenario = base_scenario()
    bag = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], flight_id=scenario["f1"]),
        TEST_USERS["acceptance_agent_headers"]))
    weigh_ok(bag["id"], 48.0)

    event = get_success_data(api.create_screening(
        create_screening_payload(bag["id"], scenario["lane"], "2026-09-01T07:00:00Z"),
        TEST_USERS["screener_headers"]))
    assert event["end_utc"] == "2026-09-01T07:20:00Z"


def test_a_windows_bucket_is_the_floor_of_its_start_instant(api):
    """PRD §2.8: "the bucket is derived by flooring the window's start instant to
    twenty-minute granularity."

    Design: Corner/state_machines/resolved_screening_reopen_requires_a_closed_window
    """
    scenario = base_scenario()
    bag = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], flight_id=scenario["f1"]),
        TEST_USERS["acceptance_agent_headers"]))
    weigh_ok(bag["id"], 48.0)

    api.create_screening(
        create_screening_payload(bag["id"], scenario["lane"], "2026-09-01T07:00:00Z"),
        TEST_USERS["screener_headers"])
    refused = api.create_screening(
        create_screening_payload(bag["id"], scenario["lane"], "2026-09-01T07:00:00Z"),
        TEST_USERS["screener_headers"])
    validate_error(refused, ApiErrorId.ERR_LANE_INTERVAL_CONFLICT, 409)


def test_the_lane_tracks_the_latest_non_failed_window_end(api):
    """PRD §2.8: "a derived `last_event_end_utc` recording the latest `end_utc`
    among its non-`FAILED` screening events"

    Design: Corner/state_machines/resolved_screening_reopen_requires_a_closed_window
    """
    scenario = base_scenario()
    bag = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], flight_id=scenario["f1"]),
        TEST_USERS["acceptance_agent_headers"]))
    weigh_ok(bag["id"], 48.0)

    api.create_screening(
        create_screening_payload(bag["id"], scenario["lane"], "2026-09-01T07:00:00Z"),
        TEST_USERS["screener_headers"])
    lane = get_success_data(api.get_screening_lane(scenario["lane"],
                                                   TEST_USERS["screener_headers"]))
    assert lane["last_event_end_utc"] == "2026-09-01T07:20:00Z"


def test_a_refused_window_leaves_no_event_and_no_screening_change(api):
    """PRD §2.8: "Both refusals — `ERR_LANE_OFFLINE` and
    `ERR_LANE_INTERVAL_CONFLICT` — carry HTTP 409."
    PRD §2.13: "Later checks are never reached once an earlier one has failed."

    Design: Corner/state_machines/resolved_screening_reopen_requires_a_closed_window
    """
    scenario = base_scenario()
    bag = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], flight_id=scenario["f1"]),
        TEST_USERS["acceptance_agent_headers"]))
    weigh_ok(bag["id"], 48.0)
    api.create_screening(
        create_screening_payload(bag["id"], scenario["lane"], "2026-09-01T07:00:00Z"),
        TEST_USERS["screener_headers"])

    before_events = list_rows(api.list_lane_screenings(
        scenario["lane"], TEST_USERS["screener_headers"]))
    before_bag = get_bag(bag["id"])
    api.create_screening(
        create_screening_payload(bag["id"], scenario["lane"], "2026-09-01T07:00:00Z"),
        TEST_USERS["screener_headers"])
    after_events = list_rows(api.list_lane_screenings(
        scenario["lane"], TEST_USERS["screener_headers"]))
    assert len(after_events) == len(before_events), "no third row was written"

    after = get_bag(bag["id"])
    assert after["screening_status"] == before_bag["screening_status"], \
        "the refused window wrote no screening axis change"
    assert after["version"] == before_bag["version"], \
        "the refused window advanced no version"
    assert get_success_data(api.get_screening_lane(
        scenario["lane"], TEST_USERS["screener_headers"]))["last_event_end_utc"] == \
        "2026-09-01T07:20:00Z"