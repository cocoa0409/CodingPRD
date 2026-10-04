"""Guard ordering: which error a request that fails two checks reports."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    get_success_data,
    read_driver,
    read_trip,
    set_clock,
    setup_scheduled_trip,
    setup_strike_cascade_scenario,
    validate_error,
)


def test_cross_district_release_lock_reports_forbidden_and_not_not_found():
    """PRD §2.1: "Authorisation is evaluated before any business rule: a caller
    who is not permitted to perform an operation never learns whether the target
    resource would have satisfied that operation's preconditions."
    PRD §3: "a caller who is not allowed to reach an operation never learns
    whether that operation's later business rules would have passed."
    PRD §2.1: "A request whose role is recognised but is not permitted to
    perform the requested operation is rejected with `ERR_FORBIDDEN` (HTTP
    403)."

    Design: Difficulty/priority_pair_validation_conflict/post_4xx_rider_refusal_outranks_open_alert_veto_on_release_lock
    """
    scenario = setup_scheduled_trip()
    trip = scenario["trip"]
    assert trip["trip_state"] == "SCHEDULED"
    assert trip["safety_state"] == "NORMAL"

    from test_helpers import make_driver_headers

    intruder = make_driver_headers(scenario["rider"]["id"])
    resp = api_client.release_lock(trip["id"], intruder)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    after = read_trip(trip["id"])
    assert after["safety_state"] == "NORMAL", (
        "no state may be mutated by a rejected request"
    )
    assert after["trip_state"] == "SCHEDULED"


def test_release_lock_is_not_reachable_by_the_driver_role_at_all():
    """PRD §2.1: "`Driver` is the narrowest role: it may act only on trips
    assigned to it and reads a student's contact detail only in masked form."
    PRD §2.1: "The `PlatformAdmin` role is a superset: every operation available
    to `DistrictAdmin` or `SupportCenterAgent` is also available to
    `PlatformAdmin`, alongside a small set of operations reserved to it alone —
    releasing a locked trip".

    Design: Difficulty/priority_pair_validation_conflict/post_4xx_rider_refusal_outranks_open_alert_veto_on_release_lock
    """
    scenario = setup_scheduled_trip()
    trip = scenario["trip"]
    driver_headers = scenario["driver_headers"]

    resp = api_client.release_lock(trip["id"], driver_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    district_admin = api_client.release_lock(
        trip["id"], TEST_USERS["district_admin_headers"]
    )
    validate_error(district_admin, ApiErrorId.ERR_FORBIDDEN)


def test_not_at_fault_resolution_while_over_the_threshold_is_refused():
    """PRD §3.9: "A not-at-fault resolution of an incident that is under review
    additionally requires the driver's strike count to be below the suspension
    threshold, because otherwise the resolution would lift a suspension that
    this incident did not cause; such an attempt is refused with
    `ERR_SUSPENSION_REQUIRES_FAULT` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/post_4xx_late_at_fault_adjudication_outranks_negative_strike_precheck
    """
    scenario = setup_strike_cascade_scenario(pre_strikes=3)
    driver_id = scenario["driver"]["id"]
    before = read_driver(driver_id)
    assert before["incident_strike_count"] == 3
    assert before["status"] == "SUSPENDED", (
        "three HIGH absences already suspended the driver"
    )

    incident = scenario["incident"]
    api_client.review_incident(incident["id"], TEST_USERS["support_center_headers"])

    resp = api_client.resolve_incident(
        incident["id"],
        {"resolution_note": "reconsidered", "adjudication": "NO_FAULT"},
        TEST_USERS["support_center_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_SUSPENSION_REQUIRES_FAULT)

    after = read_driver(driver_id)
    assert after["incident_strike_count"] == 3, (
        "the refused resolution must not move the strike count"
    )
    assert after["status"] == "SUSPENDED"


def test_a_resolution_without_an_adjudication_is_refused():
    """PRD §3.9: "a resolution submitted without any adjudication at all, or
    with an adjudication the source state forbids, is refused with
    `ERR_ADJUDICATION_REQUIRED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/post_4xx_late_at_fault_adjudication_outranks_negative_strike_precheck
    """
    scenario = setup_strike_cascade_scenario(pre_strikes=0)
    incident = scenario["incident"]
    # The incident opens REPORTED and may be resolved only with NO_FAULT.
    resp = api_client.resolve_incident(
        incident["id"],
        {"resolution_note": "driver at fault", "adjudication": "DRIVER_AT_FAULT"},
        TEST_USERS["support_center_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_ADJUDICATION_REQUIRED)

    checked = get_success_data(
        api_client.get_incident(incident["id"], TEST_USERS["support_center_headers"])
    )
    assert checked["status"] == "REPORTED"
    assert checked["adjudication"] is None