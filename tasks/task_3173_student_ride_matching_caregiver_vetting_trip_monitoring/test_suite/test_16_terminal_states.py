"""Terminal-state behaviour: the incident void path and the replay guard."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    get_success_data,
    read_driver,
    set_clock,
    setup_strike_cascade_scenario,
    validate_error,
    validate_success,
)


def test_a_second_void_of_an_already_voided_incident_is_refused():
    """PRD §3.9: "`VOIDED` is terminal for an incident, and every later attempt
    to review, resolve, reopen or void a voided incident is refused with
    `ERR_ALREADY_TERMINAL` (HTTP 409) rather than the ordinary wrong-state
    error."
    PRD §2.5: "a resource that has already reached a terminal state for the
    dimension in question reports `ERR_ALREADY_TERMINAL` (HTTP 409) rather than
    the ordinary wrong-state error `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/validations/state_precondition_outranks_the_note_rule_on_incident_void
    """
    scenario = setup_strike_cascade_scenario(pre_strikes=0)
    incident = scenario["incident"]
    assert incident["status"] == "REPORTED"

    validate_success(
        api_client.void_incident(
            incident["id"], {"reason": "logged in error"},
            TEST_USERS["support_center_headers"],
        )
    )
    voided = get_success_data(
        api_client.get_incident(incident["id"], TEST_USERS["support_center_headers"])
    )
    assert voided["status"] == "VOIDED"

    replay = api_client.void_incident(
        incident["id"], {"reason": ""}, TEST_USERS["support_center_headers"]
    )
    validate_error(replay, ApiErrorId.ERR_ALREADY_TERMINAL)

    after = get_success_data(
        api_client.get_incident(incident["id"], TEST_USERS["support_center_headers"])
    )
    assert after["status"] == "VOIDED"

    alerts = get_success_data(
        api_client.list_incident_alerts(
            incident["id"], TEST_USERS["support_center_headers"]
        )
    )
    assert all(alert["status"] == "RESOLVED" for alert in alerts), (
        "voiding closes every alert linked to the incident"
    )


def test_replaying_an_identical_at_fault_resolution_does_not_double_count():
    """PRD §3.9: "Every resolution records the adjudication on the incident and
    recomputes its student impact score."
    PRD §3.3: "the recomputed strike count reaches the three-strike suspension
    threshold".

    Design: Corner/cross_cutting_layers/repeated_identical_incident_resolution_is_refused_by_state_not_by_a_lock
    """
    scenario = setup_strike_cascade_scenario(pre_strikes=0)
    incident = scenario["incident"]
    validate_success(
        api_client.review_incident(incident["id"], TEST_USERS["support_center_headers"])
    )
    resolved = validate_success(
        api_client.resolve_incident(
            incident["id"],
            {"resolution_note": "driver at fault", "adjudication": "DRIVER_AT_FAULT"},
            TEST_USERS["support_center_headers"],
        )
    )
    assert resolved["status"] == "RESOLVED"

    driver_after_first = read_driver(scenario["driver"]["id"])
    assert driver_after_first["incident_strike_count"] == 1
    score_after_first = resolved["student_impact_score"]

    replay = api_client.resolve_incident(
        incident["id"],
        {"resolution_note": "driver at fault", "adjudication": "DRIVER_AT_FAULT"},
        TEST_USERS["support_center_headers"],
    )
    validate_error(replay, ApiErrorId.ERR_INVALID_STATE)

    driver_after_replay = read_driver(scenario["driver"]["id"])
    assert driver_after_replay["incident_strike_count"] == 1, (
        "the replay must never double-count the strike"
    )
    after = get_success_data(
        api_client.get_incident(incident["id"], TEST_USERS["support_center_headers"])
    )
    assert after["status"] == "RESOLVED"
    assert after["adjudication"] == "DRIVER_AT_FAULT"
    assert after["student_impact_score"] == score_after_first, (
        "the impact score is unchanged by the replay"
    )


def test_a_reported_incident_refuses_a_driver_at_fault_adjudication():
    """PRD §3.9: "A `REPORTED` incident may be resolved only with a `NO_FAULT`
    adjudication — an incident resolved at the reported stage with a
    driver-at-fault verdict is refused with `ERR_ADJUDICATION_REQUIRED` (HTTP
    422)."

    Design: Corner/cross_cutting_layers/repeated_identical_incident_resolution_is_refused_by_state_not_by_a_lock
    """
    scenario = setup_strike_cascade_scenario(pre_strikes=0)
    incident = scenario["incident"]
    assert incident["status"] == "REPORTED"

    resp = api_client.resolve_incident(
        incident["id"],
        {"resolution_note": "driver at fault", "adjudication": "DRIVER_AT_FAULT"},
        TEST_USERS["support_center_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_ADJUDICATION_REQUIRED)

    after = get_success_data(
        api_client.get_incident(incident["id"], TEST_USERS["support_center_headers"])
    )
    assert after["status"] == "REPORTED"
    assert after["adjudication"] is None
    assert read_driver(scenario["driver"]["id"])["incident_strike_count"] == 0