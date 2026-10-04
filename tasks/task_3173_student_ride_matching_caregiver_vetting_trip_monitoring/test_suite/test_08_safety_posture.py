"""The trip safety posture dimension: its gates and its reverse release loop."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    get_success_data,
    read_trip,
    set_clock,
    setup_locked_in_transit_trip,
    validate_error,
    validate_success,
)


def test_a_high_alert_locks_the_posture_without_rewriting_the_movement_state():
    """PRD §2.5: "it drops into `LOCKED` when a reported absence grades `HIGH`,
    when a trip alert of `HIGH` severity is created against it, or when an
    active driver-suspension cascade cancels the trip."
    PRD §2.5: "while a trip's `safety_state` is `DISCREPANCY` or `LOCKED`, every
    attempt to advance `trip_state` out of `AWAITING_STUDENT`, `STUDENT_ONBOARD`
    or `IN_TRANSIT` is refused with `ERR_TRIP_DISCREPANCY_LOCK` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/trip_safety_dimension_walks_its_reverse_release_loop
    """
    scenario = setup_locked_in_transit_trip(absence_count=3)
    trip = scenario["trip"]

    assert scenario["driver"]["incident_strike_count"] == 3
    assert scenario["driver"]["status"] == "SUSPENDED", (
        "three HIGH absences cross the suspension threshold"
    )
    assert trip["trip_state"] == "IN_TRANSIT", (
        "a suspension cascade cancels only SCHEDULED and DRIVER_EN_ROUTE trips, "
        "so the in-transit trip survives"
    )
    assert trip["safety_state"] == "LOCKED"

    severities = {alert["severity"] for alert in scenario["alerts"]}
    assert "HIGH" in severities, (
        f"the synthesized alert is escalated to HIGH, got {severities}"
    )


def test_a_locked_posture_refuses_every_movement_advance():
    """PRD §2.5: "The posture gates the movement: while a trip's `safety_state`
    is `DISCREPANCY` or `LOCKED`, every attempt to advance `trip_state` out of
    `AWAITING_STUDENT`, `STUDENT_ONBOARD` or `IN_TRANSIT` is refused with
    `ERR_TRIP_DISCREPANCY_LOCK` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/trip_safety_dimension_walks_its_reverse_release_loop
    """
    scenario = setup_locked_in_transit_trip(absence_count=3)
    trip = scenario["trip"]
    assert trip["trip_state"] == "IN_TRANSIT"
    assert trip["safety_state"] == "LOCKED"

    resp = api_client.depart_trip(
        trip["id"], scenario["driver_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_TRIP_DISCREPANCY_LOCK)

    after = read_trip(trip["id"])
    assert after["trip_state"] == "IN_TRANSIT", (
        "a refused advance leaves the movement state where it was"
    )
    assert after["safety_state"] == "LOCKED"


def test_lock_release_is_refused_while_any_alert_is_open():
    """PRD §2.5: "A trip in `LOCKED` can reach `NORMAL` only when a
    `PlatformAdmin` releases the lock, and only when every alert raised against
    that trip has been resolved; otherwise the release is refused with
    `ERR_OPEN_ALERTS` (HTTP 409)."
    PRD §3.9: "A `PlatformAdmin` may release a trip lock, returning a `LOCKED`
    trip to `NORMAL`, but only when every alert on that trip is already
    resolved".

    Design: Difficulty/non_linear_state_machine/trip_safety_dimension_walks_its_reverse_release_loop
    """
    scenario = setup_locked_in_transit_trip(absence_count=3)
    trip = scenario["trip"]

    open_alerts = [
        alert for alert in get_success_data(
            api_client.list_trip_alerts(trip["id"], TEST_USERS["support_center_headers"])
        )
        if alert["status"] == "OPEN"
    ]
    assert open_alerts, "the locked trip must carry at least one OPEN alert"

    resp = api_client.release_lock(trip["id"], TEST_USERS["platform_admin_headers"])
    validate_error(resp, ApiErrorId.ERR_OPEN_ALERTS)
    assert read_trip(trip["id"])["safety_state"] == "LOCKED", (
        "the refused release must leave the posture untouched"
    )


def test_the_reverse_loop_runs_in_two_hops_once_every_alert_is_resolved():
    """PRD §2.5: "Recovery is deliberately asymmetric between the two degraded
    postures. A `SupportCenterAgent` may clear a discrepancy — returning the
    trip from `DISCREPANCY` to `NORMAL` — but only once the trip has reached
    `COMPLETED`; the same action against a locked trip moves it only as far as
    `DISCREPANCY`."
    PRD §2.5: "A trip in `LOCKED` can reach `NORMAL` only when a `PlatformAdmin`
    releases the lock".

    Design: Difficulty/non_linear_state_machine/trip_safety_dimension_walks_its_reverse_release_loop
    """
    scenario = setup_locked_in_transit_trip(absence_count=3)
    trip = scenario["trip"]

    alerts = get_success_data(
        api_client.list_trip_alerts(trip["id"], TEST_USERS["support_center_headers"])
    )
    for alert in alerts:
        if alert["status"] == "OPEN":
            validate_success(
                api_client.resolve_alert(
                    alert["id"], TEST_USERS["support_center_headers"]
                )
            )

    intermediate = validate_success(
        api_client.resolve_discrepancy(
            trip["id"], TEST_USERS["support_center_headers"]
        )
    )
    assert intermediate["safety_state"] == "DISCREPANCY", (
        "clearing a locked trip moves it only as far as DISCREPANCY"
    )

    released = validate_success(
        api_client.release_lock(trip["id"], TEST_USERS["platform_admin_headers"])
    )
    assert released["safety_state"] == "NORMAL", (
        "the second hop of the reverse loop returns the trip to NORMAL"
    )
    assert released["trip_state"] == "IN_TRANSIT", (
        "neither recovery hop rewrites the movement dimension"
    )