"""Window geometry: the half-open driver rule against the closed rider rule."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    get_success_data,
    read_request,
    read_trip,
    set_clock,
    setup_driver_overlap_scenario,
    setup_rider_overlap_scenario,
    validate_error,
    validate_success,
)


def test_driver_availability_block_accepts_a_zero_minute_gap():
    """PRD §2.6: "Against a driver resource, windows are half-open: a candidate
    window occupies from its open instant up to but not including its close
    instant, so a window that begins exactly at another window's close is
    accepted and a gap of zero minutes is permitted."
    PRD §2.6: "An availability block or a generated series window that overlaps
    an interval already occupied by that driver under these semantics is refused
    with `ERR_DRIVER_WINDOW_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/driver_availability_block_uses_half_open_geometry_on_the_driver_resource
    """
    scenario = setup_driver_overlap_scenario()
    driver_id = scenario["driver"]["id"]
    district_id = scenario["district"]["id"]

    overlapping = api_client.block_driver_availability(
        district_id,
        {
            "driver_id": driver_id,
            "block_start_at": "2026-09-11T07:40:00Z",
            "block_end_at": "2026-09-11T07:55:00Z",
            "reason": "personal",
        },
        TEST_USERS["district_admin_headers"],
    )
    validate_error(overlapping, ApiErrorId.ERR_DRIVER_WINDOW_OVERLAP)

    touching = api_client.block_driver_availability(
        district_id,
        {
            "driver_id": driver_id,
            "block_start_at": "2026-09-11T07:50:00Z",
            "block_end_at": "2026-09-11T08:30:00Z",
            "reason": "personal",
        },
        TEST_USERS["district_admin_headers"],
    )
    validate_success(touching, 201)

    trip = read_trip(scenario["trip"]["id"])
    assert trip["trip_state"] == "DRIVER_EN_ROUTE", (
        "an accepted availability block must not mutate the existing trip"
    )
    assert trip["driver_id"] == driver_id


def test_closed_geometry_territory_is_still_the_driver_resource():
    """PRD §2.6: "Series-interval checking uses no additional buffer, so the
    boundary is evaluated at second precision."
    PRD §2.6: "Availability blocking applies an additional twenty-minute buffer
    when a driver's route segment is tested, while the series-to-series
    comparison applies none."

    Design: Difficulty/resource_temporal_overlap/driver_availability_block_uses_half_open_geometry_on_the_driver_resource
    """
    scenario = setup_driver_overlap_scenario()
    district_id = scenario["district"]["id"]
    driver_id = scenario["driver"]["id"]

    save_the_gap = api_client.block_driver_availability(
        district_id,
        {
            "driver_id": driver_id,
            "block_start_at": "2026-09-11T07:50:00Z",
            "block_end_at": "2026-09-11T08:30:00Z",
            "reason": "personal",
        },
        TEST_USERS["district_admin_headers"],
    )
    validate_success(save_the_gap, 201)
    assert isinstance(get_success_data(save_the_gap), list), (
        "a successful block returns the ride requests affected by it"
    )

    trip = read_trip(scenario["trip"]["id"])
    assert trip["driver_id"] == driver_id
    assert trip["trip_state"] == "DRIVER_EN_ROUTE"


def test_rider_resource_treats_a_touching_pair_as_a_collision():
    """PRD §2.6: "Against a rider resource, windows are closed on both ends: a
    trip window that merely touches an existing non-terminal window for the same
    student is a collision, because a student cannot leave one vehicle at the
    instant they are due in another. Such a booking is refused with
    `ERR_RIDER_WINDOW_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/rider_series_window_uses_closed_geometry_on_the_rider_resource
    """
    scenario = setup_rider_overlap_scenario()
    second = scenario["second_request"]
    assert second["status"] == "APPROVED"

    resp = api_client.schedule_ride_request(
        second["id"], {"scheduled_date": "2026-09-11"},
        TEST_USERS["district_admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_RIDER_WINDOW_OVERLAP)

    assert read_request(second["id"])["status"] == "APPROVED", (
        "the refused scheduling call must leave the request untouched"
    )
    assert read_trip(scenario["first_trip"]["id"])["trip_state"] == "SCHEDULED"


def test_rider_rule_uses_the_same_instants_as_the_driver_rule():
    """PRD §2.6: "Such a booking is refused with
    `ERR_RIDER_WINDOW_OVERLAP` (HTTP 409)."
    PRD §2.6: "the two checks are implemented separately even though they
    compare the same pair of instants."
    PRD §2.6: "Against a driver resource, windows are half-open ... so a window
    that begins exactly at another window's close is accepted".

    Design: Difficulty/resource_temporal_overlap/rider_series_window_uses_closed_geometry_on_the_rider_resource
    """
    scenario = setup_rider_overlap_scenario()

    # The identical touching pair is accepted on the driver resource, which the
    # driver-side scenario exercises in its own district.
    driver_scenario = setup_driver_overlap_scenario()
    accepted = api_client.block_driver_availability(
        driver_scenario["district"]["id"],
        {
            "driver_id": driver_scenario["driver"]["id"],
            "block_start_at": "2026-09-11T07:50:00Z",
            "block_end_at": "2026-09-11T08:30:00Z",
            "reason": "personal",
        },
        TEST_USERS["district_admin_headers"],
    )
    validate_success(accepted, 201)

    refused = api_client.schedule_ride_request(
        scenario["second_request"]["id"], {"scheduled_date": "2026-09-11"},
        TEST_USERS["district_admin_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_RIDER_WINDOW_OVERLAP)

    assert read_trip(scenario["first_trip"]["id"])["trip_state"] == "SCHEDULED", (
        "the rider-side refusal must not disturb the existing trip"
    )