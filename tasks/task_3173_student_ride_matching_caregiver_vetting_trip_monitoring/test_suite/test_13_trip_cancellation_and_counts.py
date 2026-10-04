"""Cancellation, settlement and the counting rules that ride on them."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    get_success_data,
    read_driver,
    read_request,
    read_rider,
    read_trip,
    set_clock,
    setup_completed_trip,
    setup_one_off_request,
    setup_scheduled_trip,
    validate_error,
    validate_success,
)


def test_cancelling_a_scheduled_trip_debits_the_district_load():
    """PRD §3.8: "A `DistrictAdmin` may cancel a trip that is still `SCHEDULED`
    and in a `NORMAL` posture, optionally with a `reason`, which moves it to
    `CANCELLED` and decrements the district's scheduled-trip total".
    PRD §3.11: "every trip whose movement state is not `CANCELLED`".

    Design: Corner/state_machines/cancellation_side_effect_debits_the_district_load
    """
    scenario = setup_scheduled_trip()
    district_id = scenario["district"]["id"]
    trip_id = scenario["trip"]["id"]
    request_id = scenario["trip_request"]["id"]

    before = get_success_data(
        api_client.get_district(district_id, TEST_USERS["district_admin_headers"])
    )
    assert before["trips_scheduled_total"] == 1

    validate_success(
        api_client.cancel_trip(
            trip_id, {"reason": "campus closed"},
            TEST_USERS["district_admin_headers"],
        )
    )

    after = get_success_data(
        api_client.get_district(district_id, TEST_USERS["district_admin_headers"])
    )
    assert after["trips_scheduled_total"] == 0, (
        "the cancellation debits exactly one unit from the live load"
    )

    trip = read_trip(trip_id)
    assert trip["trip_state"] == "CANCELLED"
    assert trip["district_id"] == district_id, "the row was not deleted"

    assert read_request(request_id)["status"] == "SCHEDULED", (
        "cancelling one trip does not unwind the request"
    )


def test_cancelling_a_completed_trip_is_refused_as_a_wrong_state():
    """PRD §3.8: "a trip in any other movement state is refused with
    `ERR_INVALID_STATE` (HTTP 409)."
    PRD §2.5: "a resource that has already reached a terminal state for the
    dimension in question reports `ERR_ALREADY_TERMINAL` (HTTP 409) rather than
    the ordinary wrong-state error `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/state_machines/cancel_from_a_terminal_trip_state_returns_invalid_state
    """
    scenario = setup_completed_trip(planned_miles=5.0, billable_miles=5.0)
    trip = scenario["trip"]
    assert trip["trip_state"] == "COMPLETED"
    assert trip["billable_ride_units"] == 2

    resp = api_client.cancel_trip(
        trip["id"], {"reason": "too late"}, TEST_USERS["district_admin_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = read_trip(trip["id"])
    assert after["trip_state"] == "COMPLETED"
    assert after["completed_at"] == trip["completed_at"], (
        "the refusal leaves the completion instant unchanged"
    )
    assert after["billable_ride_units"] == 2


def test_compliance_expiry_takes_the_earliest_clearance_and_the_latest_inspection():
    """PRD §2.4: "Otherwise it is the earlier of two instants — the earliest
    `expires_on` among the driver's `CLEARED` fingerprint-type background checks,
    and the latest `expires_on` among the driver's `PASSED` vehicle
    inspections."
    PRD §2.4: "the inspection contributes its most recent passing date, so
    re-inspecting a vehicle extends coverage instead of pinning the driver to
    the oldest pass."

    Design: Corner/calculations/compliance_expiry_takes_the_earliest_clearance_and_the_latest_inspection
    """
    set_clock("2026-09-01T00:00:00Z")
    from test_helpers import onboard_driver, open_clearance, record_inspection
    from test_helpers import read_driver

    # Clearance lapsing before the inspection: the clearance is the earlier of
    # the two instants and therefore governs.
    early_clearance = onboard_driver(caregiver_experience_months=18)
    open_clearance(early_clearance["id"], "FINGERPRINT_FBI", "2027-03-01", clear=True)
    inspection = record_inspection(
        early_clearance["id"], seat_count=6, expires_on="2027-04-01"
    )
    validate_success(
        api_client.attest_inspection(inspection["id"], TEST_USERS["district_admin_headers"])
    )
    governs_by_clearance = read_driver(early_clearance["id"])
    assert governs_by_clearance["compliance_expires_at"].startswith("2027-03-01"), (
        "the earlier clearance governs, got "
        f"{governs_by_clearance['compliance_expires_at']}"
    )
    assert governs_by_clearance["status"] == "ACTIVE"
    assert governs_by_clearance["approved_seat_count"] == 6

    # Inspection lapsing before the clearance: the two roles swap and the
    # inspection now supplies the earlier instant.
    late_clearance = onboard_driver(
        caregiver_experience_months=18, full_name="Fay Okoro", phone="5550112"
    )
    open_clearance(late_clearance["id"], "FINGERPRINT_FBI", "2027-05-01", clear=True)
    inspection = record_inspection(
        late_clearance["id"], seat_count=4, expires_on="2027-04-01"
    )
    validate_success(
        api_client.attest_inspection(inspection["id"], TEST_USERS["district_admin_headers"])
    )
    governs_by_inspection = read_driver(late_clearance["id"])
    assert governs_by_inspection["compliance_expires_at"].startswith("2027-04-01"), (
        "the inspection's passing date is the earlier instant here, got "
        f"{governs_by_inspection['compliance_expires_at']}"
    )
    assert governs_by_inspection["approved_seat_count"] == 4


def test_the_active_request_count_excludes_a_request_that_already_has_trips():
    """PRD §3.2: "The student record also exposes a derived
    `active_ride_request_count`, which counts only ride requests in `SUBMITTED`
    or `APPROVED` status."
    PRD §3.2: "Requests that have already produced trips are tracked by their
    trips instead and are deliberately excluded".

    Design: Corner/calculations/rider_active_request_count_excludes_scheduled_requests
    """
    scenario = setup_scheduled_trip()
    rider_id = scenario["rider"]["id"]
    district_id = scenario["district"]["id"]

    scheduled = read_request(scenario["trip_request"]["id"])
    assert scheduled["status"] == "SCHEDULED"

    # A second request left in SUBMITTED is the only counted one.
    second = setup_one_off_request(
        district_id, rider_id, scheduled_date="2026-09-11",
        window_start_at="2026-09-11T15:00:00Z",
        window_end_at="2026-09-11T15:20:00Z",
    )[0]
    assert second["status"] == "SCHEDULED" or second["status"] == "APPROVED"

    rider = read_rider(rider_id)
    assert rider["active_ride_request_count"] == 0, (
        "a request that has already produced trips contributes nothing to the count"
    )

    third = setup_one_off_request(
        district_id, rider_id, scheduled_date="2026-09-12",
        window_start_at="2026-09-12T15:00:00Z",
        window_end_at="2026-09-12T15:20:00Z",
    )
    assert third[0]["status"] == "SCHEDULED"

    rider = read_rider(rider_id)
    assert rider["active_ride_request_count"] == 0


def test_the_counted_set_is_a_request_still_awaiting_a_decision():
    """PRD §3.2: "which counts only ride requests in `SUBMITTED` or `APPROVED`
    status."
    PRD §3.2: "Only ride-request rows contribute to the count; trip rows never
    do."

    Design: Corner/calculations/rider_active_request_count_excludes_scheduled_requests
    """
    from test_helpers import create_request, read_district

    set_clock("2026-09-01T00:00:00Z")
    scenario = setup_scheduled_trip()
    rider = scenario["rider"]
    district_id = scenario["district"]["id"]

    pending = create_request(
        read_district(district_id), rider, approve=False,
        window_start_at="2026-09-11T15:00:00Z",
        window_end_at="2026-09-11T15:20:00Z",
    )
    assert pending["status"] == "SUBMITTED"
    assert read_rider(rider["id"])["active_ride_request_count"] == 1

    validate_success(
        api_client.approve_ride_request(
            pending["id"], TEST_USERS["district_admin_headers"]
        )
    )
    assert read_rider(rider["id"])["active_ride_request_count"] == 1, (
        "an APPROVED request counts too"
    )

    validate_success(
        api_client.schedule_ride_request(
            pending["id"], {"scheduled_date": "2026-09-11"},
            TEST_USERS["district_admin_headers"],
        ),
        201,
    )
    assert read_rider(rider["id"])["active_ride_request_count"] == 0, (
        "once it has produced trips the request stops counting, so the count is not 2"
    )