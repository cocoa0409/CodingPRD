"""Breadth coverage for the error catalogue's reachable identifiers."""

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
    set_clock,
    validate_error,
)


def test_a_nonpositive_fare_and_an_out_of_range_deposit_are_both_malformed():
    """PRD §2.6: "a malformed body — a required field absent, a wrong type, an
    enum member outside its set, a deposit outside its permitted range, a fare
    below one cent, a payment amount above its ceiling, or a timestamp that will
    not parse as ISO 8601 — is rejected with `ERR_INVALID_REQUEST` (HTTP 400)".
    PRD §3.1: "requires a `fare_cents` of at least one cent".

    Design: Corner/entities/corner_itinerary_rejects_a_nonpositive_fare_or_a_bad_deposit_amount
    """
    set_clock()
    route = create_route()
    itinerary = create_itinerary(route["id"], "tv-mara")
    headers = TEST_USERS["traveler_headers"]

    below_floor = api_client.open_freeze(
        itinerary["id"],
        {"deposit_cents": 99, "disclosure_version": 1, "disclosure_acknowledged": True,
         "expected_itinerary_version": itinerary["version"]},
        headers)
    validate_error(below_floor, "ERR_INVALID_REQUEST", expected_status=400)

    zero_fare = api_client.create_observation(
        {"route_id": route["id"], "itinerary_id": itinerary["id"], "fare_cents": 0,
         "seats_left": 9},
        TEST_USERS["ops_headers"])
    validate_error(zero_fare, "ERR_INVALID_REQUEST", expected_status=400)
    assert read_itinerary(itinerary["id"])["observed_fares_cents"] == []


def test_the_deposit_range_admits_both_of_its_ends():
    """PRD §3.3: "opens a freeze manifest against an itinerary by supplying a
    `deposit_cents` between 100 and 5000 inclusive".

    Design: Corner/entities/corner_itinerary_rejects_a_nonpositive_fare_or_a_bad_deposit_amount
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    headers = TEST_USERS["traveler_headers"]
    at_floor = get_success_data(
        api_client.open_freeze(
            itinerary["id"],
            {"deposit_cents": 100, "disclosure_version": 1, "disclosure_acknowledged": True,
             "expected_itinerary_version": itinerary["version"]},
            headers)
    )
    assert at_floor["deposit_cents"] == 100
    refreshed = read_itinerary(itinerary["id"])
    at_ceiling = get_success_data(
        api_client.open_freeze(
            itinerary["id"],
            {"deposit_cents": 5000, "disclosure_version": 1, "disclosure_acknowledged": True,
             "expected_itinerary_version": refreshed["version"]},
            headers)
    )
    assert at_ceiling["deposit_cents"] == 5000


def test_a_price_observation_across_the_wrong_route_is_refused():
    """PRD §2.5: "The referential, constraint, disclosure and schema-existence
    family closes the order: `ERR_PRODUCT_TYPE_MISMATCH`,
    `ERR_HEDGE_DUPLICATE_COVERAGE`, `ERR_DUPLICATE_SEQUENCE_INDEX`,
    `ERR_DISCLOSURE_NOT_ACKNOWLEDGED` and `ERR_PRICE_FIELD_MISSING`." PRD §2.6:
    "A price observation whose itinerary does not belong to the route named in
    the same request fails with `ERR_ROUTE_ITINERARY_MISMATCH`."

    Design: Corner/entities/corner_entity_foreign_keys_use_the_canonical_declaration_and_resolve
    """
    set_clock()
    route_a = create_route(origin_airport="SFO", destination_airport="JFK",
                           flight_number="HA101")
    route_b = create_route(origin_airport="SFO", destination_airport="DEN",
                           flight_number="HA103", base_fare_cents=6400)
    itinerary = create_itinerary(route_a["id"], "tv-mara")

    res = api_client.create_observation(
        {"route_id": route_b["id"], "itinerary_id": itinerary["id"], "fare_cents": 9000,
         "seats_left": 9},
        TEST_USERS["ops_headers"])
    validate_error(res, "ERR_ROUTE_ITINERARY_MISMATCH")
    assert read_itinerary(itinerary["id"])["route_id"] == route_a["id"], (
        "the itinerary was never re-parented"
    )


def test_a_watch_may_not_be_armed_before_a_curve_is_published():
    """PRD §3.2: "Arming requires the itinerary to be `PLANNED`, requires that
    at least one demand curve has been published for the route, and requires the
    acting traveler to own the itinerary."

    Design: Corner/cross_cutting_complexity_layers/corner_watch_cannot_be_armed_on_an_unpublished_curve
    """
    set_clock()
    route = create_route(base_fare_cents=6400)
    itinerary = create_itinerary(route["id"], "tv-mara")

    res = api_client.arm_watch(itinerary["id"],
                               {"expected_itinerary_version": itinerary["version"]},
                               TEST_USERS["traveler_headers"])
    validate_error(res, "ERR_CURVE_UNPUBLISHED", expected_status=409)
    assert get_success_data(api_client.get_route(route["id"],
                                                 TEST_USERS["admin_headers"])
                            )["curve_published"] is False


def test_the_same_arming_succeeds_once_a_curve_exists():
    """PRD §2.14: "Publication flips the route's `curve_published` flag to true".

    Design: Corner/cross_cutting_complexity_layers/corner_watch_cannot_be_armed_on_an_unpublished_curve
    """
    set_clock()
    route = create_route(base_fare_cents=6400)
    itinerary = create_itinerary(route["id"], "tv-mara")
    publish_curve(route["id"],
                  each_day_prices_cents=[5200, 5600, 6000, 6600, 7200],
                  seats_left_at_each_day=[9, 8, 7, 5, 3])
    assert get_success_data(api_client.get_route(route["id"],
                                                 TEST_USERS["admin_headers"])
                            )["curve_published"] is True
    armed = get_success_data(
        api_client.arm_watch(itinerary["id"],
                             {"expected_itinerary_version": read_itinerary(
                                 itinerary["id"])["version"]},
                             TEST_USERS["traveler_headers"])
    )
    assert armed["notification_status"] == "ARMED"
    refreshed = read_itinerary(itinerary["id"])
    assert refreshed["watch_armed"] is True
    assert refreshed["version"] == 3, (
        "the version advanced on publication and again on the successful call"
    )


def test_a_claim_cannot_be_filed_against_a_freeze_whose_fare_did_not_rise():
    """PRD §3.5: "if the freeze's `overshoot_cents` is zero the filing is
    refused with `ERR_NO_OVERSHOOT` (HTTP 422), because a frozen fare that did
    not rise above the manifest has nothing to settle."

    Design: Corner/errors/corner_price_field_missing_is_reached_only_when_earlier_gates_pass
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], 8900, seats_left=8)
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=250)
    res = api_client.file_claim({"freeze_id": freeze["id"], "market_price_cents": 8900},
                                TEST_USERS["traveler_headers"])
    validate_error(res, "ERR_NO_OVERSHOOT", expected_status=422)
    refreshed = read_freeze(freeze["id"])
    assert refreshed["status"] == "FROZEN", (
        "the refused filing never moved the freeze out of service"
    )
    assert refreshed["overshoot_cents"] == 0


def test_a_claim_filed_while_the_freeze_is_still_draft_is_refused_on_state():
    """PRD §2.5: "The segregation audit comes next and outranks every state
    check ... Only then are state gates consulted: whether the target resource
    sits in a state the requested transition can leave (`ERR_INVALID_STATE`)".

    Design: Corner/errors/corner_price_field_missing_is_reached_only_when_earlier_gates_pass
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], 14000, seats_left=4)
    freeze = create_freeze_in_state(itinerary["id"], "DRAFT", deposit_cents=250)
    res = api_client.file_claim({"freeze_id": freeze["id"], "market_price_cents": 16500},
                                TEST_USERS["traveler_headers"])
    validate_error(res, "ERR_INVALID_STATE")
    assert read_freeze(freeze["id"])["status"] == "DRAFT"


def test_a_context_free_request_cannot_reach_the_price_field_gate():
    """PRD §2.5: "First, a request that violates a low-priority rule and a
    high-priority rule reports the high-priority one".

    Design: Corner/errors/corner_price_field_missing_is_reached_only_when_earlier_gates_pass
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], 14000, seats_left=4)
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=250)
    claim = get_success_data(
        api_client.file_claim({"freeze_id": freeze["id"], "market_price_cents": 16500},
                              TEST_USERS["traveler_headers"])
    )
    res = api_client.settle_claim(claim["id"], {"expected_claim_version": claim["version"]}, {})
    validate_error(res, "ERR_MISSING_OR_INVALID_CONTEXT_HEADER", expected_status=400)
    refreshed = read_claim_shallow(claim["id"])
    assert refreshed["claim_status"] == "FILED", (
        "the request never reached a state or schema gate"
    )


def read_claim_shallow(claim_id: str) -> dict:
    return get_success_data(
        api_client.get_claim(claim_id, TEST_USERS["adjuster_rosa_headers"])
    )


def test_the_duration_metric_costs_nothing_for_a_shift_of_three_days():
    """PRD §3.8: "The duration metric counts days: a shift of zero days or fewer
    counts as 0, one day counts as 1, two as 2, three as 3, and any shift of
    more than three days counts as three plus the number of extra days divided
    by two and rounded up to a whole day."

    Design: Corner/calculations/corner_duration_metric_is_free_below_three_days
    """
    set_clock()
    route = create_route(origin_airport="ORD", destination_airport="LHR",
                         flight_number="HA707", region="MIDWEST", base_fare_cents=13200,
                         peak_price_day_index=0, seats_left=6,
                         fare_band_cents=[9000, 12000, 15000, 17000, 19000])
    publish_curve(route["id"], each_day_prices_cents=[9000, 9000, 9000, 9000, 9000],
                  seats_left_at_each_day=[6, 6, 6, 6, 6])
    itinerary = create_itinerary(route["id"], "tv-otis", departure_date="2026-12-01T00:00:00Z")
    headers = TEST_USERS["traveler_otis_headers"]
    protection = get_success_data(
        api_client.quote_protection(
            {"itinerary_id": itinerary["id"], "product_type": "CHANGE",
             "cancellation_disruption_probability": 0.70, "disclosure_version": 1,
             "disclosure_acknowledged": True},
            headers)
    )
    get_success_data(
        api_client.activate_protection(protection["id"],
                                       {"expected_protection_version": protection["version"]},
                                       headers)
    )
    three_day = get_success_data(
        api_client.file_change_event(
            {"protection_id": protection["id"], "new_departure_date": "2026-12-04T00:00:00Z",
             "gap_direction": "ORIGIN_DIRECTION"},
            headers)
    )
    get_success_data(
        api_client.cancel_change_event(three_day["id"], {"cancel_reason": "CHANGED_MIND"}, headers)
    )
    five_day = get_success_data(
        api_client.file_change_event(
            {"protection_id": protection["id"], "new_departure_date": "2026-12-06T00:00:00Z",
             "gap_direction": "ORIGIN_DIRECTION"},
            headers)
    )

    assert three_day["day_shift"] == 3 and three_day["disruption_days"] == 3
    assert five_day["day_shift"] == 5 and five_day["disruption_days"] == 4, (
        "one extra day of shift costs one extra day of entitlement"
    )
    assert get_success_data(api_client.get_protection(protection["id"], headers)
                            )["duration_consumed_days"] == 0, (
        "no day is consumed until a change event actually settles"
    )
    assert get_success_data(api_client.get_protection(protection["id"], headers)
                            )["lifecycle_status"] == "CHANGE_IN_PROGRESS"
