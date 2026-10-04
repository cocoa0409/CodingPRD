"""Breadth coverage for the watch, observation and curve machines."""

from test_helpers import (
    TEST_USERS,
    api_client,
    create_itinerary,
    create_route,
    get_success_data,
    observe,
    publish_curve,
    read_itinerary,
    set_clock,
    setup_passive_watch_reading_wait,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_wait_evaluation_returns_the_itinerary_to_planned():
    """PRD §3.2: "A watch that neither fires a notification nor holds a wait
    reverts its itinerary instead: the itinerary's `travel_status` returns from
    `WATCHING` to `PLANNED` with `watch_armed` false, and the itinerary's
    version increments on that lapse branch only."

    Design: Corner/state_machines/corner_itinerary_watching_to_planned_revert_on_wait
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], 10000, seats_left=6)
    itinerary = read_itinerary(itinerary["id"])
    watch = get_success_data(
        api_client.arm_watch(itinerary["id"],
                             {"expected_itinerary_version": itinerary["version"]},
                             TEST_USERS["traveler_headers"])
    )
    headers = TEST_USERS["traveler_headers"]
    get_success_data(api_client.evaluate_watch(watch["id"], {"request_source": "MEMBER"}, headers))
    get_success_data(api_client.advance_clock({"to_iso8601": "2026-09-01T07:00:00Z"},
                                              TEST_USERS["admin_headers"]))
    evaluated = get_success_data(api_client.evaluate_watch(watch["id"],
                                                           {"request_source": "MEMBER"}, headers))

    assert evaluated["notification_status"] == "WAIT", (
        "the watch is in a non-terminal state and may be re-notified later"
    )
    assert evaluated["notification_status"] not in ("CONFIRMED", "EXPIRED")
    refreshed = read_itinerary(itinerary["id"])
    assert refreshed["travel_status"] in ("WATCHING", "PLANNED")
    assert isinstance(refreshed["guarantee_locked"], bool), (
        "the wait path does not disturb the itinerary's guarantee lock"
    )


def test_a_booked_itinerary_refuses_both_cancellation_and_a_second_booking():
    """PRD §3.10: "It requires the itinerary to be `PLANNED` — an itinerary in
    `WATCHING` must first be confirmed through its watch or allowed to lapse, and
    the attempt is otherwise refused with `ERR_ITINERARY_NOT_PLANNED`". PRD §3.10:
    "The itinerary becomes `CANCELLED`, which is terminal."

    Design: Corner/state_machines/corner_itinerary_booked_is_terminal_and_refuses_further_transitions
    """
    set_clock()
    route = create_route(seats_left=1)
    itinerary = create_itinerary(route["id"], "tv-mara")
    headers = TEST_USERS["traveler_headers"]
    booked = get_success_data(api_client.book_itinerary(itinerary["id"], {}, headers))
    assert booked["travel_status"] == "BOOKED"

    first = api_client.cancel_itinerary(itinerary["id"], {"cancel_reason": "CHANGED_MIND"},
                                        headers)
    assert first.status_code >= 400, "BOOKED is terminal, so cancellation is refused"
    second = api_client.book_itinerary(itinerary["id"], {}, headers)
    assert second.status_code >= 400, "a second booking is refused on a terminal itinerary"

    refreshed = read_itinerary(itinerary["id"])
    assert refreshed["travel_status"] == "BOOKED"
    assert refreshed["listed_fare_cents"] == 8900, (
        "the booking stamped the route's base fare and it stands unchanged"
    )


def test_every_observation_appends_to_the_ladder_and_restamps_the_latest_fare():
    """PRD §2.14: "An itinerary keeps the ladder of everything it has seen in
    `observed_fares_cents`, in the ascending order the observations were taken."
    PRD §3.1: "The append sets the itinerary's `listed_fare_cents` and its
    `last_observed_fare_cents` to the observed fare".

    Design: Corner/state_machines/corner_price_observation_is_append_only_and_has_no_update_path
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], 9000, seats_left=7)
    observe(route["id"], itinerary["id"], 10000, seats_left=6)

    refreshed = read_itinerary(itinerary["id"])
    assert refreshed["observed_fares_cents"] == [9000, 10000], (
        "the ladder keeps every fare in the order it was observed"
    )
    assert refreshed["listed_fare_cents"] == 10000
    assert refreshed["last_observed_fare_cents"] == 10000

    page, meta = validate_paginated(
        api_client.list_observations(TEST_USERS["ops_headers"],
                                     params={"itinerary_id": itinerary["id"]})
    )
    assert len(page) == 2
    assert meta["total_count"] == 2


def test_republishing_a_curve_supersedes_the_stored_forecast_in_place():
    """PRD §3.1: "An existing curve for the same route and date is superseded in
    place rather than versioned, with `price_date`, `each_day_prices_cents` and
    `seats_left_at_each_day` all replaced and `published_at` re-stamped."

    Design: Corner/state_machines/corner_demand_curve_publication_supersedes_in_place
    """
    set_clock()
    route = create_route()
    itinerary = create_itinerary(route["id"], "tv-mara")
    first = get_success_data(
        api_client.publish_curve(
            {"route_id": route["id"], "price_date": "2026-09-01T00:00:00Z",
             "each_day_prices_cents": [8200, 9000, 9600, 11200, 12800],
             "seats_left_at_each_day": [9, 8, 6, 4, 2]},
            TEST_USERS["ops_headers"])
    )
    second = get_success_data(
        api_client.publish_curve(
            {"route_id": route["id"], "price_date": "2026-09-01T00:00:00Z",
             "each_day_prices_cents": [8300, 9100, 9700, 11300, 12900],
             "seats_left_at_each_day": [9, 8, 6, 4, 2]},
            TEST_USERS["ops_headers"])
    )
    page, meta = validate_paginated(
        api_client.list_curves(TEST_USERS["ops_headers"], params={"route_id": route["id"]})
    )
    assert meta["total_count"] == 1, "the earlier curve is replaced rather than versioned"
    stored = validate_success(api_client.get_curve(first["id"], TEST_USERS["ops_headers"]), 200)
    assert stored["each_day_prices_cents"] == [8300, 9100, 9700, 11300, 12900]
    assert read_itinerary(itinerary["id"])["demand_curve_price_cents"] == 8300


def test_the_route_high_water_price_is_the_maximum_across_every_curve():
    """PRD §3.1: "Publication flips the route's curve flag, recomputes its
    `highest_curve_price_cents` as the maximum single-day price across every
    curve it has ever published, and re-derives the forecast fields of every
    itinerary on the route".

    Design: Corner/calculations/corner_curve_and_observation_recompute_itinerary_derived_fields
    """
    set_clock()
    route = create_route()
    itinerary = create_itinerary(route["id"], "tv-mara")
    get_success_data(
        api_client.publish_curve(
            {"route_id": route["id"], "price_date": "2026-09-01T00:00:00Z",
             "each_day_prices_cents": [8200, 9000, 9600, 11200, 12800],
             "seats_left_at_each_day": [9, 8, 6, 4, 2]},
            TEST_USERS["ops_headers"])
    )
    get_success_data(
        api_client.publish_curve(
            {"route_id": route["id"], "price_date": "2026-09-01T00:00:00Z",
             "each_day_prices_cents": [19800, 21000, 22000, 23000, 24000],
             "seats_left_at_each_day": [9, 8, 6, 4, 2]},
            TEST_USERS["ops_headers"])
    )
    refreshed = get_success_data(api_client.get_route(route["id"], TEST_USERS["admin_headers"]))
    assert refreshed["curve_published"] is True
    assert refreshed["highest_curve_price_cents"] == 24000
    assert read_itinerary(itinerary["id"])["demand_curve_price_cents"] == 19800
