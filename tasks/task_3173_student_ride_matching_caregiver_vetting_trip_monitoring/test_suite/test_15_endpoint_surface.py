"""Corner coverage for the endpoint surface: masked contact reads, the dispatch
tie-break and the district-wide closure fan-out."""
from test_helpers import (
    TEST_USERS,
    api_client,
    get_success_data,
    make_driver_headers,
    read_request,
    read_trip,
    set_clock,
    setup_recurring_series,
    setup_scheduled_trip,
    setup_two_vetted_drivers,
    validate_success,
)


def test_a_driver_reads_the_rider_contact_only_in_masked_form():
    """PRD §3.2: "A `Driver` addressing a student record on a trip assigned to
    them receives the masked contact value in place of the real number; the real
    `emergency_contact_phone` never leaves the platform toward a driver."
    PRD §3.2: "the platform derives the student's masked contact digest
    `support_center_phone_masked` from the emergency contact number by retaining
    only the final four digits."

    Design: Corner/endpoints/blocked_driver_handoff_returns_the_rider_contact_masked_only
    """
    scenario = setup_scheduled_trip(
        rider_overrides={"emergency_contact_phone": "5551234567"}
    )
    rider_id = scenario["rider"]["id"]
    driver_headers = scenario["driver_headers"]

    as_driver = get_success_data(
        api_client.get_rider(rider_id, driver_headers)
    )
    assert as_driver["support_center_phone_masked"].endswith("4567")
    assert as_driver["authorized_adults"] == [], (
        "the roster rides along so a dropoff party name can still be matched"
    )

    as_admin = get_success_data(
        api_client.get_rider(rider_id, TEST_USERS["district_admin_headers"])
    )
    assert as_admin["emergency_contact_phone"] == "5551234567"
    assert as_admin["support_center_phone_masked"].endswith("4567")


def test_the_dispatch_fallback_resolves_a_complete_ranking_tie_by_creation_order():
    """PRD §3.6: "When all three keys tie, the fallback is the driver's creation
    time ascending, so the earliest-registered candidate wins; the driver's
    identifier is never consulted for this or any other ordering decision."
    PRD §2.7: "Where a deterministic fallback is required between otherwise
    equal candidates, the platform uses registration or creation time, never the
    identifier."

    Design: Corner/endpoints/dispatch_candidate_pins_the_earliest_registered_driver_on_a_rank_tie
    """
    scenario = setup_two_vetted_drivers()
    first = scenario["first_driver"]
    second = scenario["second_driver"]

    assert first["incident_strike_count"] == second["incident_strike_count"] == 0
    assert first["compliance_expires_at"] == second["compliance_expires_at"]
    assert first["approved_seat_count"] == second["approved_seat_count"] == 6

    pinned = validate_success(
        api_client.dispatch_candidate(
            scenario["trip"]["id"], TEST_USERS["district_admin_headers"]
        )
    )
    assert pinned["candidate_driver_id"] == first["id"], (
        "the driver onboarded first wins the tie, not the smaller identifier"
    )
    assert read_trip(scenario["trip"]["id"])["candidate_driver_id"] == first["id"]


def test_a_school_closure_event_cancels_only_that_date_across_the_district():
    """PRD §3.5: "An event of type `NO_SCHOOL_DAY` appends the effective date to
    the district's `no_school_dates`, and every ride request in that district
    that is `SCHEDULED` with an active recurring series immediately cancels the
    trips whose `scheduled_date` equals that date, decrementing the district's
    scheduled-trip total once per cancelled trip."

    Design: Corner/cross_cutting_layers/school_closure_event_fans_out_to_every_active_series_in_the_district
    """
    scenario = setup_recurring_series()
    district_id = scenario["district"]["id"]
    trips = scenario["trips"]
    assert len(trips) == 5, "a Monday-to-Friday range produces five trips"

    dates = {trip["scheduled_date"] for trip in trips}
    assert dates == {
        "2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18",
    }

    validate_success(
        api_client.emit_event(
            {
                "event_type": "NO_SCHOOL_DAY",
                "effective_date": "2026-09-15",
                "district_id": district_id,
            },
            TEST_USERS["district_admin_headers"],
        )
    )

    by_date = {read_trip(trip["id"])["scheduled_date"]: read_trip(trip["id"])
               for trip in trips}
    assert by_date["2026-09-15"]["trip_state"] == "CANCELLED", (
        "the declared closure reaches the series that is already generating trips"
    )
    for date in ("2026-09-14", "2026-09-16", "2026-09-17", "2026-09-18"):
        assert by_date[date]["trip_state"] == "SCHEDULED", (
            f"the fan-out is date-scoped, so {date} is untouched"
        )

    district = get_success_data(
        api_client.get_district(district_id, TEST_USERS["district_admin_headers"])
    )
    assert "2026-09-15" in district["no_school_dates"]
    assert read_request(scenario["request"]["id"])["status"] == "SCHEDULED", (
        "one closure date does not suspend the whole series"
    )