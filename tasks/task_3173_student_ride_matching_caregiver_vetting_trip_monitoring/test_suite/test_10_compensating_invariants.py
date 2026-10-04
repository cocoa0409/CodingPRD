"""Conserved quantities across compensating action pairs."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    get_success_data,
    read_driver,
    read_trip,
    set_clock,
    setup_scheduled_trip,
    setup_vetted_driver_only,
    validate_error,
    validate_success,
)


def test_cancel_then_restore_returns_the_district_load_to_its_prior_value():
    """PRD §3.11: "A district's `trips_scheduled_total` counts the district's
    live scheduled load — every trip whose movement state is not `CANCELLED` —
    so a cancellation decrements it and a restoration increments it".
    PRD §3.8: "Restoration clears the driver, the claiming user, the acceptance
    instant and any exception record, and raises the district's scheduled-trip
    total back by one."

    Design: Difficulty/compensating_invariant/cancellation_and_restore_preserve_the_district_scheduled_load
    """
    scenario = setup_scheduled_trip()
    district_id = scenario["district"]["id"]
    trip_id = scenario["trip"]["id"]

    before = get_success_data(
        api_client.get_district(district_id, TEST_USERS["district_admin_headers"])
    )
    assert before["trips_scheduled_total"] == 1

    validate_success(
        api_client.cancel_trip(
            trip_id, {"reason": "district closed the campus"},
            TEST_USERS["district_admin_headers"],
        )
    )
    during = get_success_data(
        api_client.get_district(district_id, TEST_USERS["district_admin_headers"])
    )
    assert during["trips_scheduled_total"] == 0, (
        "cancellation borrows exactly one unit from the district's live load"
    )

    validate_success(
        api_client.restore_trip(trip_id, TEST_USERS["district_admin_headers"])
    )
    after = get_success_data(
        api_client.get_district(district_id, TEST_USERS["district_admin_headers"])
    )
    assert after["trips_scheduled_total"] == 1, (
        "the compensating pair leaves the conserved quantity with no drift"
    )


def test_the_restored_trip_is_indistinguishable_from_a_freshly_scheduled_one():
    """PRD §3.8: "Restoration clears the driver, the claiming user, the
    acceptance instant and any exception record, and raises the district's
    scheduled-trip total back by one."
    PRD §3.11: "a cancellation decrements it and a restoration increments it".

    Design: Difficulty/compensating_invariant/cancellation_and_restore_preserve_the_district_scheduled_load
    """
    scenario = setup_scheduled_trip()
    district_id = scenario["district"]["id"]
    trip_id = scenario["trip"]["id"]

    validate_success(
        api_client.cancel_trip(
            trip_id, {"reason": "campus closed"},
            TEST_USERS["district_admin_headers"],
        )
    )
    cancelled = read_trip(trip_id)
    assert cancelled["trip_state"] == "CANCELLED"

    validate_success(
        api_client.restore_trip(trip_id, TEST_USERS["district_admin_headers"])
    )
    restored = read_trip(trip_id)
    assert restored["trip_state"] == "SCHEDULED"
    assert restored["driver_id"] is None
    assert restored["claimed_by_user_id"] is None
    assert restored["accepted_at"] is None
    assert restored["exception_code"] is None

    rows = get_success_data(
        api_client.list_district_trips(district_id, TEST_USERS["district_admin_headers"])
    )
    assert len(rows) == 1, "the same trip row is reused rather than duplicated"


def test_deactivate_then_reactivate_returns_the_whole_seat_pool():
    """PRD §3.3: "A `DistrictAdmin` may deactivate the driver, moving them to
    `INACTIVE` with a zeroed approved seat count".

    Design: Difficulty/compensating_invariant/deactivation_and_reactivation_preserve_the_fleet_seat_pool
    """
    scenario = setup_vetted_driver_only(seat_capacity=6, seat_count=6)
    driver_id = scenario["driver"]["id"]

    before = read_driver(driver_id)
    assert before["approved_seat_count"] == 6
    assert before["status"] == "ACTIVE"

    validate_success(
        api_client.deactivate_driver(driver_id, TEST_USERS["district_admin_headers"])
    )
    during = read_driver(driver_id)
    assert during["status"] == "INACTIVE"
    assert during["approved_seat_count"] == 0, (
        "the forward action debits the whole seat pool"
    )

    # INACTIVE is terminal for the driver dimension (PRD §2.5), so the
    # compensating reactivation is refused rather than returning the seat pool.
    resp = api_client.reactivate_driver(
        driver_id, TEST_USERS["district_admin_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
    assert read_driver(driver_id)["approved_seat_count"] == 0


def test_the_seat_pool_pair_leaves_the_clearance_dates_untouched():
    """PRD §2.4: "Otherwise it is the earlier of two instants — the earliest
    `expires_on` among the driver's `CLEARED` fingerprint-type background checks,
    and the latest `expires_on` among the driver's `PASSED` vehicle
    inspections."
    PRD §3.3: "Reactivation of a suspended driver is available to a
    `DistrictAdmin` only while the driver's compliance expiry still falls
    strictly after the logical clock instant".

    Design: Difficulty/compensating_invariant/deactivation_and_reactivation_preserve_the_fleet_seat_pool
    """
    scenario = setup_vetted_driver_only()
    driver_id = scenario["driver"]["id"]

    before = read_driver(driver_id)
    assert before["compliance_expires_at"] is not None

    validate_success(
        api_client.deactivate_driver(driver_id, TEST_USERS["district_admin_headers"])
    )
    during = read_driver(driver_id)
    assert during["compliance_expires_at"] is None, (
        "an INACTIVE driver reports no compliance expiry at all"
    )

    # Neither action touches the clearance dates; the forward hop reports no
    # expiry and INACTIVE is terminal, so the compensating hop is refused.
    resp = api_client.reactivate_driver(
        driver_id, TEST_USERS["district_admin_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)

    after = read_driver(driver_id)
    assert after["compliance_expires_at"] is None
    assert after["approved_seat_count"] == 0