"""Trip cross-entity gates: the parent request state and the restore path."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    get_success_data,
    read_request,
    read_trip,
    set_clock,
    setup_recurring_series,
    validate_error,
    validate_success,
)


def test_restore_is_refused_while_the_parent_series_is_suspended():
    """PRD §3.8: "a `DistrictAdmin` may return a `CANCELLED` trip to
    `SCHEDULED`, but only while the parent request is still `SCHEDULED` —
    otherwise the attempt is refused with `ERR_REQUEST_NOT_SCHEDULED` (HTTP
    409)".
    PRD §3.5: "A `DistrictAdmin` may suspend a recurring series, moving the
    request to `SERIES_SUSPENDED` with the series flag cleared and cancelling
    every trip for that request still sitting in `SCHEDULED` or
    `DRIVER_EN_ROUTE`".

    Design: Difficulty/cross_entity_state_dependency/trip_restore_gated_by_the_parent_ride_request_state
    """
    scenario = setup_recurring_series(series_no_school_dates=("2026-09-15", "2026-09-17"))
    request = scenario["request"]
    trips = scenario["trips"]
    assert len(trips) == 3, "a five-day range less two no-school dates produces three trips"

    validate_success(
        api_client.suspend_series(request["id"], TEST_USERS["district_admin_headers"])
    )
    suspended = read_request(request["id"])
    assert suspended["status"] == "SERIES_SUSPENDED"
    assert suspended["recurring_series_active"] is False

    resp = api_client.restore_trip(
        trips[0]["id"], TEST_USERS["district_admin_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_SCHEDULED)

    untouched = read_trip(trips[0]["id"])
    assert untouched["trip_state"] == "CANCELLED", (
        "the refused restore must leave the cancelled trip in place"
    )


def test_the_same_restore_succeeds_once_the_parent_returns_to_scheduled():
    """PRD §3.5: "A successful resume returns the request to `SCHEDULED`,
    reactivates the series flag, and generates one trip per included date."
    PRD §3.8: "Restoration clears the driver, the claiming user, the acceptance
    instant and any exception record, and raises the district's scheduled-trip
    total back by one."
    PRD §3.11: "a series that is suspended and then resumed reads the same total
    as an untouched series while holding twice as many trip rows."

    Design: Difficulty/cross_entity_state_dependency/trip_restore_gated_by_the_parent_ride_request_state
    """
    scenario = setup_recurring_series(series_no_school_dates=("2026-09-15", "2026-09-17"))
    request = scenario["request"]
    trips = scenario["trips"]

    # History is retained deliberately: PRD §3.5 says the included-date set is
    # "further excluded ... when a trip for the same request already sits on that
    # date in a state other than `CANCELLED`", so cancelled rows for the same
    # dates do not suppress them and the resumed series regenerates the dates.
    assert len(trips) == 3, "a five-day range less two no-school dates produces three trips"

    validate_success(
        api_client.suspend_series(request["id"], TEST_USERS["district_admin_headers"])
    )
    district = get_success_data(
        api_client.get_district(
            scenario["district"]["id"], TEST_USERS["district_admin_headers"]
        )
    )
    assert district["trips_scheduled_total"] == 0, (
        "suspension cancels the three scheduled trips and decrements the load three times"
    )

    validate_success(
        api_client.resume_series(request["id"], TEST_USERS["district_admin_headers"])
    )
    resumed = read_request(request["id"])
    assert resumed["status"] == "SCHEDULED"
    assert resumed["recurring_series_active"] is True

    validate_success(
        api_client.restore_trip(trips[0]["id"], TEST_USERS["district_admin_headers"])
    )
    restored = read_trip(trips[0]["id"])
    assert restored["trip_state"] == "SCHEDULED"
    assert restored["driver_id"] is None
    assert restored["accepted_at"] is None
    assert restored["exception_code"] is None

    after = get_success_data(
        api_client.get_district(
            scenario["district"]["id"], TEST_USERS["district_admin_headers"]
        )
    )
    assert after["trips_scheduled_total"] == 4, (
        "three freshly generated trips plus the one restored trip"
    )

    rows = get_success_data(
        api_client.list_district_trips(
            scenario["district"]["id"], TEST_USERS["district_admin_headers"]
        )
    )
    assert len(rows) == 6, (
        "the cancelled rows still exist, so the district holds six trip rows while its live load reads four"
    )