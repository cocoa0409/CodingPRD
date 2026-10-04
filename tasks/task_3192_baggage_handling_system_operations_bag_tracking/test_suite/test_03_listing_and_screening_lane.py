"""Listing/pagination and the screening-lane interval rules."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    create_bag_payload, create_screening_payload, ApiErrorId, TEST_USERS,
    set_clock, base_scenario, list_rows, get_area, get_flight,
)


def test_bags_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "List endpoints accept a `limit` query parameter giving the
    maximum number of items to return; when omitted it defaults to 10, and it is
    constrained to a minimum of 1 and a maximum of 100."
    PRD §2.3: "The pagination-related fields `limit`, `offset`, `total_count` and
    `has_more` are reported in the `meta` object of the response envelope for
    list endpoints."

    Design: Corner/entities/bags_list_paginates_and_reports_total_count_and_has_more
    """
    scenario = base_scenario()
    for index in range(3):
        api.create_bag(create_bag_payload(
            scenario["st"], flight_id=scenario["f1"],
            passenger_ref=f"PNR{index}X2Q",
            itinerary_type="INTERNATIONAL" if index == 2 else "DOMESTIC"),
            TEST_USERS["acceptance_agent_headers"])

    first_page = api.list_bags(TEST_USERS["acceptance_agent_headers"],
                               {"flight_id": scenario["f1"], "limit": 2, "offset": 0})
    rows, meta = validate_paginated(first_page)
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    last_page = api.list_bags(TEST_USERS["acceptance_agent_headers"],
                              {"flight_id": scenario["f1"], "limit": 2, "offset": 2})
    rows2, meta2 = validate_paginated(last_page)
    assert len(rows2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_bags_list_defaults_the_page_size_and_rejects_a_limit_above_100(api):
    """PRD §2.3: "when omitted it defaults to 10, and it is constrained to a
    minimum of 1 and a maximum of 100. A second query parameter, `offset`, gives
    the number of items to skip and defaults to 0."

    Design: Corner/entities/bags_list_paginates_and_reports_total_count_and_has_more
    """
    scenario = base_scenario()
    rows, meta = validate_paginated(
        api.list_bags(TEST_USERS["acceptance_agent_headers"],
                      {"flight_id": scenario["f1"]}))
    assert meta["limit"] == 10, "the omitted limit defaults to 10"
    assert meta["offset"] == 0, "the omitted offset defaults to 0"

    over = api.list_bags(TEST_USERS["acceptance_agent_headers"],
                         {"flight_id": scenario["f1"], "limit": 101})
    assert over.status_code == 400, \
        f"a limit of 101 exceeds the declared maximum and must be refused, got {over.status_code}"


def test_screening_window_ends_exactly_twenty_minutes_after_it_opens(api):
    """PRD §2.8: "A screening window is the half-open interval from a supplied
    `start_utc` to twenty minutes later"

    Design: Corner/state_machines/resolved_screening_reopen_requires_a_closed_window
    """
    scenario = base_scenario()
    bag = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], flight_id=scenario["f1"]),
        TEST_USERS["acceptance_agent_headers"]))
    api.weigh_bag(bag["id"], 48.0, TEST_USERS["acceptance_agent_headers"])

    event = get_success_data(api.create_screening(
        create_screening_payload(bag["id"], scenario["lane"], "2026-09-01T07:40:00Z"),
        TEST_USERS["screener_headers"]))
    assert event["start_utc"] == "2026-09-01T07:40:00Z"
    assert event["end_utc"] == "2026-09-01T08:00:00Z", \
        "end_utc is start_utc plus twenty minutes"


def test_reopen_before_the_window_closes_is_refused(api):
    """PRD §2.8: "the strict half-open span `[start_utc, end_utc)` with no
    changeover buffer"

    Design: Corner/state_machines/resolved_screening_reopen_requires_a_closed_window
    """
    scenario = base_scenario()
    bag = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], flight_id=scenario["f1"]),
        TEST_USERS["acceptance_agent_headers"]))
    api.weigh_bag(bag["id"], 48.0, TEST_USERS["acceptance_agent_headers"])
    event = get_success_data(api.create_screening(
        create_screening_payload(bag["id"], scenario["lane"], "2026-09-01T07:40:00Z"),
        TEST_USERS["screener_headers"]))

    set_clock("2026-09-01T07:00:00Z")
    response = api.reopen_screening(event["id"], TEST_USERS["screener_headers"])
    validate_error(response, ApiErrorId.ERR_SCREENING_WINDOW_CLOSED, 409)


def test_back_to_back_window_at_the_exact_end_instant_is_legal(api):
    """PRD §2.8: "a lane may host a back-to-back window that starts at exactly
    the instant another window ends, and that adjacency is legal."

    Design: Corner/state_machines/resolved_screening_reopen_requires_a_closed_window
    """
    scenario = base_scenario()
    bag = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], flight_id=scenario["f1"]),
        TEST_USERS["acceptance_agent_headers"]))
    api.weigh_bag(bag["id"], 48.0, TEST_USERS["acceptance_agent_headers"])

    first = get_success_data(api.create_screening(
        create_screening_payload(bag["id"], scenario["lane"], "2026-09-01T07:00:00Z"),
        TEST_USERS["screener_headers"]))
    assert first["end_utc"] == "2026-09-01T07:20:00Z"

    adjacent = api.create_screening(
        create_screening_payload(bag["id"], scenario["lane"], "2026-09-01T07:20:00Z"),
        TEST_USERS["screener_headers"])
    second = validate_success(adjacent, 201)
    assert second["end_utc"] == "2026-09-01T07:40:00Z"


def test_a_second_window_in_the_same_identity_bucket_is_refused(api):
    """PRD §2.8: "What the lane may not do is host two different non-`FAILED`
    windows in the same twenty-minute identity bucket, where the bucket is
    derived by flooring the window's start instant to twenty-minute granularity."
    PRD §2.8: "Both refusals — `ERR_LANE_OFFLINE` and
    `ERR_LANE_INTERVAL_CONFLICT` — carry HTTP 409."

    Design: Corner/state_machines/resolved_screening_reopen_requires_a_closed_window
    """
    scenario = base_scenario()
    bag = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], flight_id=scenario["f1"]),
        TEST_USERS["acceptance_agent_headers"]))
    api.weigh_bag(bag["id"], 48.0, TEST_USERS["acceptance_agent_headers"])

    api.create_screening(
        create_screening_payload(bag["id"], scenario["lane"], "2026-09-01T07:00:00Z"),
        TEST_USERS["screener_headers"])
    collision = api.create_screening(
        create_screening_payload(bag["id"], scenario["lane"], "2026-09-01T07:00:00Z"),
        TEST_USERS["screener_headers"])
    validate_error(collision, ApiErrorId.ERR_LANE_INTERVAL_CONFLICT, 409)


def test_lane_last_event_end_utc_tracks_non_failed_windows(api):
    """PRD §2.8: "a derived `last_event_end_utc` recording the latest `end_utc`
    among its non-`FAILED` screening events, or null when the lane has hosted
    none."

    Design: Corner/state_machines/resolved_screening_reopen_requires_a_closed_window
    """
    scenario = base_scenario()
    assert get_success_data(api.get_screening_lane(
        scenario["lane"], TEST_USERS["screener_headers"])).get("last_event_end_utc") is None

    bag = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], flight_id=scenario["f1"]),
        TEST_USERS["acceptance_agent_headers"]))
    api.weigh_bag(bag["id"], 48.0, TEST_USERS["acceptance_agent_headers"])
    api.create_screening(
        create_screening_payload(bag["id"], scenario["lane"], "2026-09-01T07:00:00Z"),
        TEST_USERS["screener_headers"])
    api.create_screening(
        create_screening_payload(bag["id"], scenario["lane"], "2026-09-01T07:20:00Z"),
        TEST_USERS["screener_headers"])

    lane = get_success_data(api.get_screening_lane(
        scenario["lane"], TEST_USERS["screener_headers"]))
    assert lane["last_event_end_utc"] == "2026-09-01T07:40:00Z"


def test_an_offline_lane_refuses_a_new_window(api):
    """PRD §2.8: "The lane's status must also be `ACTIVE`; no new window may be
    opened on a lane reading `OFFLINE`."

    Design: Corner/state_machines/resolved_screening_reopen_requires_a_closed_window
    """
    scenario = base_scenario()
    api.take_lane_offline(scenario["lane"], TEST_USERS["platform_admin_headers"])

    bag = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], flight_id=scenario["f1"]),
        TEST_USERS["acceptance_agent_headers"]))
    api.weigh_bag(bag["id"], 48.0, TEST_USERS["acceptance_agent_headers"])
    response = api.create_screening(
        create_screening_payload(bag["id"], scenario["lane"], "2026-09-01T07:00:00Z"),
        TEST_USERS["screener_headers"])
    validate_error(response, ApiErrorId.ERR_LANE_OFFLINE, 409)