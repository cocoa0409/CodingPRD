"""Validation priority ordering between the screening gate and the lower rungs."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    set_clock, base_scenario, get_bag, get_area, get_flight, make_flight,
    list_rows, make_sorted_bag, create_bag_payload, create_assign_makeup_payload,
    create_connection_payload, create_screening_payload, weigh_ok, screen_ok,
    raise_alarm, make_transfer_bag, declare_outage, board_and_depart,
    make_alarmed_bag,
)


def test_uncleared_screening_outranks_the_oversize_screening_envelope(api):
    """PRD §2.13: "A bag whose screening status is
    `ALARMED`, `FAILED` or `IN_INSPECTION` may not advance past the screening
    stage. This is checked ahead of every custody-advance state precondition and
    is reported as `ERR_SCREENING_NOT_CLEARED` (409)."
    PRD §2.13: "the declared weight must not exceed the carrier's `max_excess_weight_lb` plus 20 pounds, and the declared `linear_in` must not exceed 130 inches."

    Design: Difficulty/priority_pair_validation_conflict/uncleared_screening_beats_oversize_screening_envelope
    """
    scenario = base_scenario()
    # A sorted bag whose clearance has been torn up by a screening-axis cycle
    # edge: custody SORTED, screening IN_LINE.  The make-up claim is refused at
    # the clearance rung, not at the state rung.
    bag = make_sorted_bag(scenario)
    noted = validate_success(api.update_bag(
        bag["id"], {"expected_bag_version": bag["version"],
                    "anomaly_note": "post-sortation X-ray recheck requested"},
        TEST_USERS["screener_headers"]), 200)
    assert noted["custody_status"] == "SORTED"
    assert noted["screening_status"] == "IN_LINE"

    response = api.assign_makeup(
        noted["id"],
        create_assign_makeup_payload(noted["version"], scenario["ma"],
                                     "2026-09-01T07:20:00Z"),
        TEST_USERS["sortation_agent_headers"])
    validate_error(response, ApiErrorId.ERR_SCREENING_NOT_CLEARED, 409)

    after = get_bag(bag["id"])
    assert after["screening_status"] == "IN_LINE"
    assert after["custody_status"] == "SORTED"


def test_the_oversize_refusal_is_not_the_reported_failure_here(api):
    """PRD §3.2: "Weighing is refused outright if the bag's `linear_in` exceeds
    130 inches, with `ERR_BAG_OVERSIZE`."
    PRD §2.13: "they are evaluated in a fixed priority order, and the first failure is the error the caller sees. Later checks are never reached once an earlier one has failed."

    Design: Difficulty/priority_pair_validation_conflict/uncleared_screening_beats_oversize_screening_envelope
    """
    scenario = base_scenario()
    bag = make_sorted_bag(scenario)
    noted = validate_success(api.update_bag(
        bag["id"], {"expected_bag_version": bag["version"],
                    "anomaly_note": "post-sortation X-ray recheck requested"},
        TEST_USERS["screener_headers"]), 200)

    response = api.assign_makeup(
        noted["id"],
        create_assign_makeup_payload(noted["version"], scenario["ma"],
                                     "2026-09-01T07:20:00Z"),
        TEST_USERS["sortation_agent_headers"])
    body = response.json()
    reported = body.get("data", {}).get("error_id")
    assert reported != "ERR_BAG_OVERSIZE", \
        "the screening gate surfaces ahead of the size envelope check"


def test_clearing_the_alarm_exposes_the_envelope_or_outage_rung_below(api):
    """PRD §3.5: "it is refused unless one of two conditions holds: either the
    station's `outage_active` is true, or the bag's screening status is currently
    `ALARMED` or `CLEARED`. Neither condition holding yields
    `ERR_OUTAGE_NOT_ACTIVE` with HTTP 409."

    Design: Difficulty/priority_pair_validation_conflict/uncleared_screening_beats_oversize_screening_envelope
    """
    scenario = base_scenario()
    bag, event = make_alarmed_bag(scenario)
    api.resolve_screening(event["id"], "CLEARED", TEST_USERS["screener_headers"])

    # PRD §3.5: re-induction is permitted for a held bag whose screening status
    # is ALARMED or CLEARED (or while the station outage is active).  This bag is
    # CLEARED, so re-induction is admitted rather than refused, and the re-weigh
    # leaves the bag back at the counter with its screening axis restarted.
    reinducted = weigh_ok(bag["id"], 48.0)
    assert reinducted["custody_status"] == "ACCEPTED"
    assert reinducted["screening_status"] == "IN_LINE"


def test_the_screening_gate_outranks_the_minimum_connect_time_gate(api):
    """PRD §2.13: "Screening clearance gate."
    PRD §2.13: "Make-up interval claim."
    PRD §2.13: "Later checks are never reached once an earlier one has failed."

    Design: Corner/validations/mct_violation_outranks_screening_not_cleared_on_connection_confirm
    """
    scenario = base_scenario()
    onward = make_flight(scenario, flight_number="DL1788", bank_code="B2")
    bag, connection, onward, event = make_transfer_bag(
        scenario, onward_flight=onward, required_mct_minutes=165, alarmed=True)
    assert connection["connect_slack_minutes"] == -15

    refused = api.confirm_connection(connection["id"], TEST_USERS["transfer_agent_headers"])
    validate_error(refused, ApiErrorId.ERR_SCREENING_NOT_CLEARED, 409)

    after = get_success_data(api.get_connection(
        connection["id"], TEST_USERS["transfer_agent_headers"]))
    assert after["status"] == "PENDING"
    assert get_bag(bag["id"])["screening_status"] == "ALARMED"


def test_the_connect_time_gate_surfaces_once_the_screening_gate_is_satisfied(api):
    """PRD §3.8: "requires a slack of zero or more (`ERR_MCT_VIOLATION`, 409)"
    PRD §2.13: "Later checks are never reached once an earlier one has failed."

    Design: Corner/validations/mct_violation_outranks_screening_not_cleared_on_connection_confirm
    """
    scenario = base_scenario()
    onward = make_flight(scenario, flight_number="DL1788", bank_code="B2")
    bag, connection, onward, event = make_transfer_bag(
        scenario, onward_flight=onward, required_mct_minutes=165, alarmed=True)
    api.resolve_screening(event["id"], "CLEARED", TEST_USERS["screener_headers"])

    refused = api.confirm_connection(connection["id"], TEST_USERS["transfer_agent_headers"])
    validate_error(refused, ApiErrorId.ERR_MCT_VIOLATION, 409)


def test_a_connection_slack_can_recover_through_re_accommodation(api):
    """PRD §3.8: "An accepted re-accommodation replaces the connection's
    `onward_flight_id`, recomputes `connect_slack_minutes` against the replacement
    flight's schedule, moves the connection to `REACCOMMODATED`"

    Design: Corner/validations/mct_violation_outranks_screening_not_cleared_on_connection_confirm
    """
    scenario = base_scenario()
    onward = make_flight(scenario, flight_number="DL1788", bank_code="B2")
    later = make_flight(scenario, flight_number="DL1790", bank_code="B3",
                        scheduled_departure_utc="2026-09-01T19:30:00Z")
    bag, connection, onward = make_transfer_bag(
        scenario, onward_flight=onward, required_mct_minutes=165)
    api.declare_rush(connection["id"], TEST_USERS["transfer_agent_headers"])

    set_clock("2026-09-01T18:00:00Z")
    from test_helpers import run_ops
    run_ops(scenario["st"])
    missed = get_success_data(api.get_connection(
        connection["id"], TEST_USERS["transfer_agent_headers"]))
    assert missed["status"] == "MISSED", \
        "the checkpoint marks a connection missed once the onward window shuts"

    moved = validate_success(api.reaccommodate_connection(
        connection["id"], later["id"], TEST_USERS["transfer_agent_headers"]), 201)
    assert moved["status"] == "REACCOMMODATED"
    assert moved["connect_slack_minutes"] == 105, "150 minutes minus the required 45 is not it"


def test_a_negative_slack_confirmation_is_refused_as_a_connect_time_violation(api):
    """PRD §3.8: "requires a slack of zero or more (`ERR_MCT_VIOLATION`, 409)"

    Design: Corner/validations/minimum_connect_time_rejects_a_negative_slack_confirmation
    """
    scenario = base_scenario()
    onward = make_flight(scenario, flight_number="DL1788", bank_code="B2")
    bag, connection, onward = make_transfer_bag(
        scenario, onward_flight=onward, required_mct_minutes=165)
    assert connection["connect_slack_minutes"] == -15

    refused = api.confirm_connection(connection["id"], TEST_USERS["transfer_agent_headers"])
    validate_error(refused, ApiErrorId.ERR_MCT_VIOLATION, 409)

    after = get_success_data(api.get_connection(
        connection["id"], TEST_USERS["transfer_agent_headers"]))
    assert after["status"] == "PENDING"