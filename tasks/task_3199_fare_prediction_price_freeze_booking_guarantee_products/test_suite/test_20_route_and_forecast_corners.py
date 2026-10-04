"""Breadth coverage for the route, itinerary and forecast resources."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_itinerary,
    create_route,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    observe,
    publish_curve,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_route_registration_returns_the_declared_zero_state_and_starts_active():
    """PRD §3.1: "Registration leaves the route `ACTIVE` and its exposure books
    empty, ready for the demand-curve feed." PRD §2.14: "A newly registered
    route starts `ACTIVE`, with an empty `posture_reason_code`, a
    `peak_day_demand_multiplier` of 1.0, `war_chest_cents`,
    `reserved_exposure_cents` and `available_exposure_cents` all at 0,
    `open_freeze_count` at 0, `curve_published` false and
    `highest_curve_price_cents` at 0."

    Design: Corner/entities/corner_route_create_returns_every_declared_field_and_starts_active
    """
    set_clock()
    route = validate_success(
        api_client.create_route(
            {"origin_airport": "SFO", "destination_airport": "JFK",
             "flight_number": "HA101", "region": "WEST", "base_fare_cents": 8900,
             "fare_band_cents": [7000, 8000, 9000, 10000, 11000],
             "peak_price_day_index": 4, "seats_left": 9,
             "disclosure_headline": "Fare products are optional and separate from the ticket"},
            TEST_USERS["admin_headers"]),
        201,
    )
    assert is_valid_uuid(route["id"])
    assert is_iso8601_timestamp(route["created_at"])
    assert is_iso8601_timestamp(route["updated_at"])
    assert route["posture"] == "ACTIVE"
    assert route["posture_reason_code"] == ""
    assert route["version"] == 1
    assert route["war_chest_cents"] == 0
    assert route["reserved_exposure_cents"] == 0
    assert route["available_exposure_cents"] == 0
    assert route["open_freeze_count"] == 0
    assert route["curve_published"] is False
    assert route["highest_curve_price_cents"] == 0
    assert route["peak_day_demand_multiplier"] == pytest.approx(1.0, abs=0.001)


def test_route_registration_supplies_the_documented_defaults_for_omitted_keys():
    """PRD §2.14: "a `travel_class` drawn from `ECO`, `PREMIUM` or `BUSINESS`
    and defaulting to `ECO` ... a `volatility_index` defaulting to 0.20 that
    scales shock distances when the route is stressed, a `hedge_ratio_pct`
    defaulting to 0.60 ... a `max_guarantee_exposure_cents` defaulting to 50000
    ... and the protection-pricing inputs `default_disruption_probability`
    (0.25), `disruption_severity_index` (0.1429), `protection_base_rate` (0.25),
    `protection_floor_rate` (0.20) and `cancel_minimum_disruption` (0.30)."

    Design: Corner/entities/corner_route_create_with_allowed_fields_defaults_to_low_disruption_listing
    """
    set_clock()
    route = get_success_data(
        api_client.create_route(
            {"origin_airport": "SFO", "destination_airport": "JFK",
             "flight_number": "HA101", "region": "WEST", "base_fare_cents": 8900,
             "fare_band_cents": [7000, 8000, 9000, 10000, 11000],
             "disclosure_headline": "d"},
            TEST_USERS["admin_headers"])
    )
    assert route["travel_class"] == "ECO"
    assert route["volatility_index"] == pytest.approx(0.20, abs=0.0001)
    assert route["hedge_ratio_pct"] == pytest.approx(0.60, abs=0.0001)
    assert route["max_guarantee_exposure_cents"] == 50000
    assert route["default_disruption_probability"] == pytest.approx(0.25, abs=0.0001)
    assert route["disruption_severity_index"] == pytest.approx(0.1429, abs=0.0001)
    assert route["protection_base_rate"] == pytest.approx(0.25, abs=0.0001)
    assert route["protection_floor_rate"] == pytest.approx(0.20, abs=0.0001)
    assert route["cancel_minimum_disruption"] == pytest.approx(0.30, abs=0.0001)
    assert route["peak_price_day_index"] == 0


def test_supplying_one_optional_key_overrides_only_that_key():
    """PRD §3.1: "Only the mandatory keys must be present; every parameter not
    supplied takes its declared default."

    Design: Corner/entities/corner_route_create_with_allowed_fields_defaults_to_low_disruption_listing
    """
    set_clock()
    route = get_success_data(
        api_client.create_route(
            {"origin_airport": "SFO", "destination_airport": "BOS",
             "flight_number": "HA102", "region": "WEST", "base_fare_cents": 9100,
             "fare_band_cents": [7000, 8000, 9000, 10000, 11000],
             "hedge_ratio_pct": 0.9, "disclosure_headline": "d"},
            TEST_USERS["admin_headers"])
    )
    assert route["hedge_ratio_pct"] == pytest.approx(0.90, abs=0.0001)
    assert route["max_guarantee_exposure_cents"] == 50000
    assert route["cancel_minimum_disruption"] == pytest.approx(0.30, abs=0.0001)
    assert route["peak_day_demand_multiplier"] == pytest.approx(1.0, abs=0.001)


def test_route_list_paginates_and_reports_the_filtered_total():
    """PRD §2.3: "`limit` caps how many items are returned in one page; it
    defaults to 10, and may be set no lower than 1 and no higher than 100.
    `offset` skips that many items from the front of the result set and defaults
    to 0." PRD §2.3: "`total_count` reflects the full size of the filtered
    result set, not the size of the returned page, which is what makes
    `has_more` meaningful."

    Design: Corner/entities/corner_routes_list_paginates_and_reports_total_count_and_has_more
    """
    set_clock()
    for index, payload in enumerate([
        {"origin_airport": "SFO", "destination_airport": "JFK", "flight_number": "HA101",
         "region": "WEST", "disclosure_headline": "d1"},
        {"origin_airport": "SFO", "destination_airport": "BOS", "flight_number": "HA102",
         "region": "WEST", "disclosure_headline": "d2"},
        {"origin_airport": "ORD", "destination_airport": "LHR", "flight_number": "HA707",
         "region": "MIDWEST", "disclosure_headline": "d3"},
    ]):
        get_success_data(
            api_client.create_route(
                {"origin_airport": payload["origin_airport"],
                 "destination_airport": payload["destination_airport"],
                 "flight_number": payload["flight_number"], "region": payload["region"],
                 "base_fare_cents": 8900,
                 "fare_band_cents": [7000, 8000, 9000, 10000, 11000],
                 "peak_price_day_index": 4, "seats_left": 9,
                 "disclosure_headline": payload["disclosure_headline"]},
                TEST_USERS["admin_headers"])
        )

    page, meta = validate_paginated(
        api_client.list_routes(TEST_USERS["ops_headers"], params={"limit": 2, "offset": 0})
    )
    assert len(page) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    tail, tail_meta = validate_paginated(
        api_client.list_routes(TEST_USERS["ops_headers"], params={"limit": 2, "offset": 2})
    )
    assert len(tail) == 1
    assert tail_meta["total_count"] == 3
    assert tail_meta["has_more"] is False

    everything, default_meta = validate_paginated(
        api_client.list_routes(TEST_USERS["ops_headers"])
    )
    assert len(everything) == 3
    assert default_meta["limit"] == 10
    assert default_meta["offset"] == 0


def test_itinerary_creation_leaves_its_fare_fields_empty():
    """PRD §3.10: "Creation stamps the `booking_date` from the current clock
    instant and leaves the itinerary `PLANNED` with its fare fields empty:
    `listed_fare_cents`, `last_observed_fare_cents`, `observed_fares_cents`,
    `demand_curve_price_cents`, `each_day_disruption_fare_cents` and
    `fare_tier_ceiling_cents` all start at zero or empty."

    Design: Corner/entities/corner_service_offsets_create_returns_fee_transit_snapshot
    """
    set_clock()
    route = create_route(base_fare_cents=6400)
    itinerary = validate_success(
        api_client.create_itinerary(
            {"route_id": route["id"], "departure_date": "2026-10-01T00:00:00Z",
             "traveler_user_id": "tv-mara"},
            TEST_USERS["traveler_headers"]),
        201,
    )
    assert itinerary["travel_status"] == "PLANNED"
    assert itinerary["booking_date"] == "2026-09-01T00:00:00.000Z"
    assert itinerary["listed_fare_cents"] == 0
    assert itinerary["last_observed_fare_cents"] == 0
    assert itinerary["observed_fares_cents"] == []
    assert itinerary["demand_curve_price_cents"] == 0
    assert itinerary["each_day_disruption_fare_cents"] == 0
    assert itinerary["fare_tier_ceiling_cents"] == 0
    assert itinerary["watch_armed"] is False


def test_the_forecast_fields_stay_zero_until_a_curve_is_published():
    """PRD §2.14: "Until a curve exists, an itinerary's
    `demand_curve_price_cents`, `each_day_disruption_fare_cents` and
    `fare_tier_ceiling_cents` all read 0, and an itinerary's `listed_fare_cents`
    and `last_observed_fare_cents` read 0 until the first live observation
    arrives."

    Design: Corner/entities/corner_itinerary_derived_fields_are_zero_until_their_sources_exist
    """
    set_clock()
    route = create_route()
    itinerary = create_itinerary(route["id"], "tv-mara")
    before = get_success_data(api_client.get_itinerary(itinerary["id"],
                                                       TEST_USERS["traveler_headers"]))
    assert before["listed_fare_cents"] == 0
    assert before["demand_curve_price_cents"] == 0
    assert before["each_day_disruption_fare_cents"] == 0

    observe(route["id"], itinerary["id"], 10200, seats_left=5)
    after = get_success_data(api_client.get_itinerary(itinerary["id"],
                                                      TEST_USERS["traveler_headers"]))
    assert after["listed_fare_cents"] == 10200
    assert after["last_observed_fare_cents"] == 10200
    assert after["observed_fares_cents"] == [10200]


def test_freeze_creation_derives_the_cap_and_tier_fields_from_the_route():
    """PRD §3.3: "The manifest pins `manifest_fare_cents` from the route's
    `base_fare_cents` at that instant, and sets `cap_cents` to the manifest fare
    multiplied by 1.4 and rounded half-up to two decimal places — the company's
    absorption ceiling for this freeze." PRD §3.3: "A freeze created in this way
    sits in `DRAFT` until it is activated."

    Design: Corner/entities/corner_price_freeze_computed_cap_and_tier_fields_ignore_input
    """
    set_clock()
    route = create_route(base_fare_cents=8800)
    itinerary = create_itinerary(route["id"], "tv-mara")
    freeze = get_success_data(
        api_client.open_freeze(
            itinerary["id"],
            {"deposit_cents": 250, "disclosure_version": 1, "disclosure_acknowledged": True,
             "expected_itinerary_version": itinerary["version"]},
            TEST_USERS["traveler_headers"])
    )
    assert freeze["manifest_fare_cents"] == 8800
    assert freeze["cap_cents"] == pytest.approx(12320.00, abs=0.01)
    assert freeze["status"] == "DRAFT"
    assert freeze["freeze_date"] is None
    assert freeze["freeze_expires_at"] is None
    assert get_success_data(api_client.get_itinerary(itinerary["id"],
                                                     TEST_USERS["traveler_headers"])
                            )["guarantee_locked"] is True
