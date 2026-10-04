"""Cascades: strike-driven suspension and fingerprint revocation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    get_success_data,
    read_driver,
    read_trip,
    set_clock,
    setup_fingerprint_revocation_scenario,
    setup_strike_cascade_scenario,
    validate_error,
    validate_success,
)


def test_at_fault_resolution_raises_the_strike_and_suspends_the_driver():
    """PRD §3.9: "A driver-at-fault resolution cascades. The driver's incident
    strike count rises by one, and if the recomputed count reaches the
    three-strike suspension threshold the driver is suspended."
    PRD §3.9: "This is the third hop of the strike cascade — an incident is
    resolved, the driver's strike count rises, the driver is suspended, and the
    driver's unstarted trips are cancelled".

    Design: Difficulty/transitive_cascade/at_fault_resolution_cascades_into_driver_suspension_then_trip_cancellation
    """
    scenario = setup_strike_cascade_scenario(pre_strikes=2)
    assert scenario["driver"]["incident_strike_count"] == 2, (
        "the driver starts one strike below the suspension threshold"
    )
    incident = scenario["incident"]
    assert incident["status"] == "REPORTED"
    assert incident["adjudication"] is None

    validate_success(
        api_client.review_incident(
            incident["id"], TEST_USERS["support_center_headers"]
        )
    )
    resolved = validate_success(
        api_client.resolve_incident(
            incident["id"],
            {"resolution_note": "driver confirmed at fault",
             "adjudication": "DRIVER_AT_FAULT"},
            TEST_USERS["support_center_headers"],
        )
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["adjudication"] == "DRIVER_AT_FAULT"

    driver = read_driver(scenario["driver"]["id"])
    assert driver["incident_strike_count"] == 3, (
        "hop one: the at-fault resolution moves the count from two to three"
    )
    assert driver["status"] == "SUSPENDED", (
        "hop two: the strike count crossing the threshold alone suspends the driver"
    )


def test_suspension_cascade_cancels_only_the_suspended_drivers_unstarted_trips():
    """PRD §3.3: "every trip for that driver still sitting in `SCHEDULED` or
    `DRIVER_EN_ROUTE` is cancelled — with the assigned driver cleared, the
    claimed operator cleared, the acceptance instant cleared, any pinned
    candidate cleared, and the trip's safety posture locked".
    PRD §3.3: "the district's scheduled-trip total is decremented once for every
    trip cancelled by that cascade."

    Design: Difficulty/transitive_cascade/at_fault_resolution_cascades_into_driver_suspension_then_trip_cancellation
    """
    scenario = setup_strike_cascade_scenario(pre_strikes=2)
    district = scenario["district"]
    scoped = scenario["scoped_trip"]
    other = scenario["other_trip"]
    assert scoped["trip_state"] == "DRIVER_EN_ROUTE"
    assert other["trip_state"] == "DRIVER_EN_ROUTE"
    load_before = district["trips_scheduled_total"]

    validate_success(
        api_client.review_incident(
            scenario["incident"]["id"], TEST_USERS["support_center_headers"]
        )
    )
    validate_success(
        api_client.resolve_incident(
            scenario["incident"]["id"],
            {"resolution_note": "driver confirmed at fault",
             "adjudication": "DRIVER_AT_FAULT"},
            TEST_USERS["support_center_headers"],
        )
    )

    cancelled = read_trip(scoped["id"])
    assert cancelled["trip_state"] == "CANCELLED", (
        "hop three: the suspended driver's unstarted trip is cancelled"
    )
    assert cancelled["driver_id"] is None
    assert cancelled["claimed_by_user_id"] is None
    assert cancelled["accepted_at"] is None
    assert cancelled["candidate_driver_id"] is None
    assert cancelled["safety_state"] == "LOCKED"

    surviving = read_trip(other["id"])
    assert surviving["trip_state"] == "DRIVER_EN_ROUTE", (
        "the cascade is scoped to the suspended driver and never touches another driver"
    )
    assert surviving["driver_id"] == scenario["other_driver"]["id"]
    assert surviving["safety_state"] == "NORMAL"

    district_after = get_success_data(
        api_client.get_district(district["id"], TEST_USERS["district_admin_headers"])
    )
    assert district_after["trips_scheduled_total"] == load_before - 1, (
        "the district load is decremented once per trip cancelled by the cascade"
    )


def test_revoking_a_cleared_fingerprint_clearance_suspends_and_cancels():
    """PRD §3.3.1: "Failing a check that is already `CLEARED` is the revocation
    path, and it is available only for the three revocation-eligible types —
    `FINGERPRINT_FBI`, `FINGERPRINT_STATE` and `SEX_OFFENDER_REGISTRY`".
    PRD §3.3.1: "Revoking a cleared fingerprint clearance moves the driver to
    `SUSPENDED`, recomputes the approved seat count, and cancels every trip for
    that driver still in `SCHEDULED` or `DRIVER_EN_ROUTE`, clearing the assigned
    driver and locking the trip's safety posture."

    Design: Difficulty/transitive_cascade/cleared_fingerprint_revocation_cascades_into_suspension_then_series_failure
    """
    scenario = setup_fingerprint_revocation_scenario()
    check = scenario["clearance"]
    assert check["check_type"] == "FINGERPRINT_FBI"
    assert check["result"] == "CLEARED"
    assert scenario["driver"]["status"] == "ACTIVE"
    assert scenario["driver"]["approved_seat_count"] == 6
    assert scenario["trip"]["trip_state"] == "DRIVER_EN_ROUTE"

    failed = validate_success(
        api_client.fail_background_check(check["id"], TEST_USERS["district_admin_headers"])
    )
    assert failed["result"] == "FAILED", "hop one: the revocation fails the check itself"

    driver = read_driver(scenario["driver"]["id"])
    assert driver["status"] == "SUSPENDED", (
        "hop two: revoking the clearance moves the driver to SUSPENDED"
    )

    trip = read_trip(scenario["trip"]["id"])
    assert trip["trip_state"] == "CANCELLED", (
        "hop three: the revocation cancels the driver's unstarted trip"
    )
    assert trip["driver_id"] is None
    assert trip["safety_state"] == "LOCKED"


def test_revocation_leaves_the_strike_count_untouched():
    """PRD §3.9: "Driver strikes themselves are a derived count rather than a
    stored tally. A driver's strike count is the number of that driver's safety
    incidents adjudicated at fault, plus the number of that driver's trips whose
    exception is `RIDER_NOT_PRESENT` or `RIDER_REFUSED_BOARDING` and whose
    safety posture is `LOCKED`."
    PRD §3.3: "A newly onboarded driver begins in `PENDING` status with a zero
    `approved_seat_count`, a null `compliance_expires_at` and a zero
    `incident_strike_count`."

    Design: Difficulty/transitive_cascade/cleared_fingerprint_revocation_cascades_into_suspension_then_series_failure
    """
    scenario = setup_fingerprint_revocation_scenario()
    before = read_driver(scenario["driver"]["id"])
    assert before["incident_strike_count"] == 0

    validate_success(
        api_client.fail_background_check(
            scenario["clearance"]["id"], TEST_USERS["district_admin_headers"]
        )
    )

    after = read_driver(scenario["driver"]["id"])
    assert after["incident_strike_count"] == 0, (
        "the seat-count hop drove this cascade, not the strike hop"
    )
    assert after["status"] == "SUSPENDED"
    assert after["compliance_expires_at"] is None