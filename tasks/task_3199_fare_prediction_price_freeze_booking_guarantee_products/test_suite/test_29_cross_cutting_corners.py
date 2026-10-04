"""Breadth coverage for the cross-cutting complexity layers."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_freeze_in_state,
    create_itinerary,
    create_route,
    get_success_data,
    observe,
    publish_curve,
    read_freeze,
    read_itinerary,
    read_route,
    set_clock,
    setup_route_with_armed_watch_and_frozen_freeze,
    validate_error,
)


def test_creating_a_freeze_with_a_superseded_parent_version_is_refused():
    """PRD §2.12: "Opening a price freeze against an itinerary requires the
    request to carry `expected_itinerary_version` matching the itinerary's
    current `version`." PRD §2.12: "a value that no longer matches the parent's
    current version is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/corner_stale_itinerary_version_on_freeze_creation_is_rejected
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    headers = TEST_USERS["traveler_headers"]
    stale_version = itinerary["version"]

    # The first creation legitimately supersedes the itinerary's remaining
    # guarantee exposure and advances its version.
    get_success_data(
        api_client.open_freeze(
            itinerary["id"],
            {"deposit_cents": 250, "disclosure_version": 1, "disclosure_acknowledged": True,
             "expected_itinerary_version": stale_version},
            headers)
    )
    current = read_itinerary(itinerary["id"])
    assert current["version"] > stale_version, (
        "the itinerary's version advanced on the first creation"
    )

    res = api_client.open_freeze(
        itinerary["id"],
        {"deposit_cents": 300, "disclosure_version": 1, "disclosure_acknowledged": True,
         "expected_itinerary_version": stale_version},
        headers)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_replaying_the_same_payload_with_the_current_version_succeeds():
    """PRD §2.12: "In every one of these five cases the field is mandatory
    rather than optional, and a value that no longer matches the parent's current
    version is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/corner_stale_itinerary_version_on_freeze_creation_is_rejected
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    headers = TEST_USERS["traveler_headers"]
    payload = {"deposit_cents": 300, "disclosure_version": 1, "disclosure_acknowledged": True,
               "expected_itinerary_version": itinerary["version"]}

    get_success_data(api_client.open_freeze(itinerary["id"], dict(payload), headers))
    refused = api_client.open_freeze(itinerary["id"], dict(payload), headers)
    validate_error(refused, "ERR_STALE_VERSION", expected_status=412)

    refreshed = read_itinerary(itinerary["id"])
    accepted = get_success_data(
        api_client.open_freeze(
            itinerary["id"],
            {"deposit_cents": 300, "disclosure_version": 1, "disclosure_acknowledged": True,
             "expected_itinerary_version": refreshed["version"]},
            headers)
    )
    assert accepted["status"] == "DRAFT", (
        "the refusal is about the version, not about the payload"
    )


def test_the_clock_advance_sweep_expires_the_freeze_but_not_the_watch():
    """PRD §2.13: "Advancing the clock is what expires freezes past their
    `freeze_expires_at`, lapsing watches past their `expires_at`". PRD §3.2: "an
    `expires_at` equal to the watched itinerary's `departure_date` — the watch
    must resolve before the flight, so its window is the itinerary's own."

    Design: Corner/cross_cutting_complexity_layers/corner_clock_advance_drives_the_deferred_sweep
    """
    set_clock()
    route, itinerary, watch, freeze = setup_route_with_armed_watch_and_frozen_freeze(
        observation_fare_cents=10000)
    get_success_data(api_client.advance_clock({"to_iso8601": "2026-09-16T00:00:00Z"},
                                              TEST_USERS["admin_headers"]))

    assert read_freeze(freeze["id"])["status"] == "EXPIRED", (
        "the freeze window closed fourteen days after activation"
    )
    refreshed_watch = get_success_data(api_client.get_watch(watch["id"],
                                                            TEST_USERS["traveler_headers"]))
    assert refreshed_watch["notification_status"] == "ARMED", (
        "the watch's own window runs to the departure date, not to the freeze's"
    )
    refreshed_itinerary = read_itinerary(itinerary["id"])
    assert refreshed_itinerary["guarantee_locked"] is False
    assert refreshed_itinerary["watch_armed"] is True


def test_a_further_advance_expires_the_watch_as_well():
    """PRD §3.2: "If the clock runs past the watch's `expires_at` the watch goes
    to `EXPIRED`."

    Design: Corner/cross_cutting_complexity_layers/corner_clock_advance_drives_the_deferred_sweep
    """
    set_clock()
    route, itinerary, watch, freeze = setup_route_with_armed_watch_and_frozen_freeze(
        observation_fare_cents=10000)
    get_success_data(api_client.advance_clock({"to_iso8601": "2026-10-02T00:00:00Z"},
                                              TEST_USERS["admin_headers"]))
    expired = get_success_data(api_client.get_watch(watch["id"], TEST_USERS["traveler_headers"]))
    assert expired["notification_status"] == "EXPIRED"
    assert read_itinerary(itinerary["id"])["watch_armed"] is False


def test_the_two_fare_fields_track_the_same_observation():
    """PRD §3.1: "The append sets the itinerary's `listed_fare_cents` and its
    `last_observed_fare_cents` to the observed fare". PRD §2.14: "An itinerary
    keeps the ladder of everything it has seen in `observed_fares_cents`, in the
    ascending order the observations were taken."

    Design: Corner/cross_cutting_complexity_layers/corner_itinerary_derived_fields_never_drift_from_their_source
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], 10500, seats_left=5)
    get_success_data(
        api_client.publish_curve(
            {"route_id": route["id"], "price_date": "2026-09-01T00:00:00Z",
             "each_day_prices_cents": [19800, 21000, 22000, 23000, 24000],
             "seats_left_at_each_day": [9, 8, 6, 4, 2]},
            TEST_USERS["ops_headers"])
    )
    refreshed = read_itinerary(itinerary["id"])
    assert refreshed["listed_fare_cents"] == 10500
    assert refreshed["last_observed_fare_cents"] == 10500
    assert refreshed["observed_fares_cents"] == [10500]


def test_a_curve_supersession_moves_the_curve_fields_without_touching_the_fare_fields():
    """PRD §2.14: "An observation is born in `OBSERVED` and never leaves it; the
    feed is append-only". PRD §3.1: "re-derives `demand_curve_price_cents`,
    `each_day_disruption_fare_cents` and `fare_tier_ceiling_cents` from the
    route's most recently published curve".

    Design: Corner/cross_cutting_complexity_layers/corner_itinerary_derived_fields_never_drift_from_their_source
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], 10500, seats_left=5)
    before = read_itinerary(itinerary["id"])
    get_success_data(
        api_client.publish_curve(
            {"route_id": route["id"], "price_date": "2026-09-01T00:00:00Z",
             "each_day_prices_cents": [19800, 21000, 22000, 23000, 24000],
             "seats_left_at_each_day": [9, 8, 6, 4, 2]},
            TEST_USERS["ops_headers"])
    )
    after = read_itinerary(itinerary["id"])
    assert after["demand_curve_price_cents"] == 19800
    assert before["demand_curve_price_cents"] == 8200
    assert after["listed_fare_cents"] == before["listed_fare_cents"] == 10500, (
        "the observation-derived fields and the curve-derived fields never "
        "overwrite each other's source"
    )


def test_an_observation_is_readable_in_the_very_next_request():
    """PRD §3.1: "A read of any resource therefore always reflects the latest
    transition rather than a snapshot, because a status change is a mutation like
    any other and advances `updated_at` and `version`."

    Design: Corner/cross_cutting_complexity_layers/corner_observation_chain_and_curve_publication_are_immediately_visible
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], 14000, seats_left=4)
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=250)

    # The read issued in the next request already carries the re-derivation.
    got = read_freeze(freeze["id"])
    assert got["capped_impact_cents"] > 0, (
        "no reconciliation window stands between the observation and the read"
    )
    assert read_itinerary(itinerary["id"])["listed_fare_cents"] == 14000
    assert read_route(route["id"])["reserved_exposure_cents"] == pytest.approx(
        got["capped_impact_cents"], abs=0.02
    )


def test_a_curve_publication_is_visible_in_the_very_next_request():
    """PRD §3.1: "Nothing in this API is deleted. Every lifecycle is expressed as
    status movement". PRD §2.14: "Publication flips the route's `curve_published`
    flag to true and re-derives the route's `highest_curve_price_cents` and each
    itinerary's forecast-derived fields."

    Design: Corner/cross_cutting_complexity_layers/corner_observation_chain_and_curve_publication_are_immediately_visible
    """
    set_clock()
    route = create_route()
    itinerary = create_itinerary(route["id"], "tv-mara")
    assert read_itinerary(itinerary["id"])["demand_curve_price_cents"] == 0

    publish_curve(route["id"])
    refreshed = read_itinerary(itinerary["id"])
    assert refreshed["demand_curve_price_cents"] == 8200
    assert refreshed["fare_tier_ceiling_cents"] == 30000, (
        "a day-zero price of 8200 sits below the strict 20000 tier boundary"
    )
    assert read_route(route["id"])["curve_published"] is True