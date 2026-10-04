"""Occupancy rules: one resource slot, one holder at a time."""

from test_helpers import (
    TEST_USERS,
    api_client,
    create_itinerary,
    create_route,
    get_success_data,
    read_hedging_position,
    set_clock,
    setup_change_protection_with_held_option,
    validate_error,
    validate_error_is_one_of,
)


def test_a_second_hedging_position_on_the_same_triple_is_refused():
    """PRD §3.9: "The region will not hold unlimited coverage: the route may
    carry only one position per coverage date and per locked fare, and a second
    position on the same combination of route, coverage date and locked fare is
    refused with `ERR_HEDGE_DUPLICATE_COVERAGE`."

    Design: Difficulty/resource_temporal_overlap/overlap_hedge_coverage_occupancy_is_a_half_open_day
    """
    set_clock()
    route = create_route()
    first = get_success_data(
        api_client.open_hedging_position(
            {"route_id": route["id"], "coverage_date": "2026-09-15T00:00:00Z",
             "hedge_price_cents": 9000, "contract_quantity_cents": 500000,
             "expected_route_version": route["version"]},
            TEST_USERS["risk_analyst_headers"])
    )
    route = get_success_data(api_client.get_route(route["id"], TEST_USERS["admin_headers"]))
    res = api_client.open_hedging_position(
        {"route_id": route["id"], "coverage_date": "2026-09-15T00:00:00Z",
         "hedge_price_cents": 9000, "contract_quantity_cents": 400000,
         "expected_route_version": route["version"]},
        TEST_USERS["risk_analyst_headers"])
    validate_error(res, "ERR_HEDGE_DUPLICATE_COVERAGE")


def test_the_collision_is_a_refusal_rather_than_a_merge():
    """PRD §3.9: "the route may carry only one position per coverage date and
    per locked fare".

    Design: Difficulty/resource_temporal_overlap/overlap_hedge_coverage_occupancy_is_a_half_open_day
    """
    set_clock()
    route = create_route()
    first = get_success_data(
        api_client.open_hedging_position(
            {"route_id": route["id"], "coverage_date": "2026-09-15T00:00:00Z",
             "hedge_price_cents": 9000, "contract_quantity_cents": 500000,
             "expected_route_version": route["version"]},
            TEST_USERS["risk_analyst_headers"])
    )
    route = get_success_data(api_client.get_route(route["id"], TEST_USERS["admin_headers"]))
    api_client.open_hedging_position(
        {"route_id": route["id"], "coverage_date": "2026-09-15T00:00:00Z",
         "hedge_price_cents": 9000, "contract_quantity_cents": 400000,
         "expected_route_version": route["version"]},
        TEST_USERS["risk_analyst_headers"])

    unchanged = read_hedging_position(first["id"])
    assert unchanged["contract_quantity_cents"] == 500000, (
        "the refused second position applied no amendment to the incumbent"
    )
    listed = get_success_data(
        api_client.list_hedging_positions(TEST_USERS["risk_analyst_headers"],
                                          params={"route_id": route["id"]})
    )
    assert len(listed) >= 1


def test_an_identical_payload_on_a_different_route_succeeds():
    """PRD §3.9: "the route may carry only one position per coverage date and
    per locked fare".

    Design: Difficulty/resource_temporal_overlap/overlap_hedge_coverage_occupancy_is_a_half_open_day
    """
    set_clock()
    route_a = create_route(origin_airport="SFO", destination_airport="JFK",
                           flight_number="HA101")
    route_b = create_route(origin_airport="SFO", destination_airport="BOS",
                           flight_number="HA102")
    first = get_success_data(
        api_client.open_hedging_position(
            {"route_id": route_a["id"], "coverage_date": "2026-09-15T00:00:00Z",
             "hedge_price_cents": 9000, "contract_quantity_cents": 500000,
             "expected_route_version": route_a["version"]},
            TEST_USERS["risk_analyst_headers"])
    )
    route_b = get_success_data(api_client.get_route(route_b["id"], TEST_USERS["admin_headers"]))
    second = get_success_data(
        api_client.open_hedging_position(
            {"route_id": route_b["id"], "coverage_date": "2026-09-15T00:00:00Z",
             "hedge_price_cents": 9000, "contract_quantity_cents": 400000,
             "expected_route_version": route_b["version"]},
            TEST_USERS["risk_analyst_headers"])
    )
    assert second["id"] != first["id"], (
        "the occupancy key is the whole triple, so a different route is a different slot"
    )


def test_an_adjacent_coverage_date_does_not_collide():
    """PRD §3.9: "the route may carry only one position per coverage date and
    per locked fare, and a second position on the same combination of route,
    coverage date and locked fare is refused with `ERR_HEDGE_DUPLICATE_COVERAGE`."

    Design: Difficulty/resource_temporal_overlap/overlap_hedge_coverage_occupancy_is_a_half_open_day
    """
    set_clock()
    route = create_route()
    get_success_data(
        api_client.open_hedging_position(
            {"route_id": route["id"], "coverage_date": "2026-09-15T00:00:00Z",
             "hedge_price_cents": 9000, "contract_quantity_cents": 500000,
             "expected_route_version": route["version"]},
            TEST_USERS["risk_analyst_headers"])
    )
    route = get_success_data(api_client.get_route(route["id"], TEST_USERS["admin_headers"]))
    adjacent = get_success_data(
        api_client.open_hedging_position(
            {"route_id": route["id"], "coverage_date": "2026-09-16T00:00:00Z",
             "hedge_price_cents": 9000, "contract_quantity_cents": 400000,
             "expected_route_version": route["version"]},
            TEST_USERS["risk_analyst_headers"])
    )
    assert adjacent["status"] == "OPEN"
    assert adjacent["coverage_date"].startswith("2026-09-16")


def test_accepting_a_second_option_while_a_hold_is_live_is_refused():
    """PRD §3.7: "Acceptance requires the option's `departure_date` to be
    strictly in the future, and a departure date that is not a legal replacement
    is refused at the referential gate described in §2.6."

    Design: Difficulty/resource_temporal_overlap/overlap_option_hold_occupies_a_resource_window
    """
    set_clock()
    route, itinerary, protection, change_event, option = \
        setup_change_protection_with_held_option()
    headers = TEST_USERS["traveler_otis_headers"]
    sibling = get_success_data(
        api_client.offer_option(
            {"change_event_id": change_event["id"], "departure_date": "2026-12-07T00:00:00Z",
             "option_fare_cents": 13200},
            headers)
    )
    res = api_client.accept_option(sibling["id"], {}, headers)
    validate_error_is_one_of(res, ["ERR_OPTION_HOLD_LAPSED", "ERR_INVALID_STATE",
                                   "ERR_OPTION_NOT_OFFERED"])
    assert get_success_data(api_client.get_option(sibling["id"], headers))["status"] \
        == "OFFERED"


def test_the_option_hold_is_a_closed_twenty_four_hour_window():
    """PRD §3.7: "Accepting the selected option opens a 24-hour hold: the option
    becomes `HELD` with its `hold_expires_at` set to the current instant plus 24
    hours and the event moves to `HELD` with `option_hold_expires_at` stamped to
    the same instant."

    Design: Difficulty/resource_temporal_overlap/overlap_option_hold_occupies_a_resource_window
    """
    set_clock()
    route, itinerary, protection, change_event, option = \
        setup_change_protection_with_held_option()
    assert option["hold_expires_at"] == "2026-09-02T00:00:00.000Z", (
        "the hold is stamped exactly 24 hours after acceptance"
    )
    assert change_event["option_hold_expires_at"] == "2026-09-02T00:00:00.000Z", (
        "the event and the option share one hold instant"
    )


def test_the_window_reverts_rather_than_merging_when_it_closes():
    """PRD §3.7: "the event returns to `OPTION_SELECTED`, the option's hold
    stops being live and the option becomes `EXPIRED`".

    Design: Difficulty/resource_temporal_overlap/overlap_option_hold_occupies_a_resource_window
    """
    set_clock()
    route, itinerary, protection, change_event, option = \
        setup_change_protection_with_held_option()
    headers = TEST_USERS["traveler_otis_headers"]
    get_success_data(api_client.advance_clock({"to_iso8601": "2026-09-02T12:00:00Z"},
                                              TEST_USERS["admin_headers"]))
    expired_option = get_success_data(api_client.get_option(option["id"], headers))
    reverted_event = get_success_data(api_client.get_change_event(change_event["id"], headers))

    assert expired_option["status"] == "EXPIRED", "the hold reverts rather than extends"
    assert reverted_event["status"] == "OPTION_SELECTED"
    assert reverted_event["option_hold_expires_at"] is None
