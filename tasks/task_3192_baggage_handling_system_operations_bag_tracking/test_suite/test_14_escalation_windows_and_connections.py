"""Posture-driven escalation, lane window timing and the connection screening gate."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    set_clock, base_scenario, get_bag, get_station, get_area, get_flight,
    list_rows, make_sorted_bag, make_in_makeup_bag, make_flight,
    make_inspection_task,
    create_bag_payload, create_assign_makeup_payload, create_screening_payload,
    create_connection_payload, create_special_item_payload, weigh_ok, screen_ok,
    run_ops,
)


def test_filling_the_last_make_up_slot_congests_the_station(api):
    """PRD §2.6: "Otherwise, if the free make-up slots remaining across the
    station's active areas have fallen to fifteen percent of total capacity or
    below — where the threshold is computed as that fraction of the total rounded
    up to a whole slot"

    Design: Difficulty/transitive_cascade/makeup_area_exhaustion_escalates_the_manual_queue
    """
    scenario = base_scenario(makeup_capacity_slots=2)
    first = make_in_makeup_bag(scenario, bag_index=0,
                               induction_utc="2026-09-01T13:12:00Z")
    area = get_area(scenario["ma"])
    assert area["occupied_slots"] == 1
    assert area["free_slots"] == 1

    second = make_in_makeup_bag(scenario, bag_index=1,
                                induction_utc="2026-09-01T13:36:00Z")
    area = get_area(scenario["ma"])
    assert area["occupied_slots"] == 2
    assert area["free_slots"] == 0

    station = get_station(scenario["st"])
    assert station["posture"] == "CONGESTED", \
        "the free-slot check flipped the posture, not the assign-makeup call itself"


def test_an_overdue_queued_task_escalates_once_the_station_congests(api):
    """PRD §3.13: "It escalates overdue inspection work: manual inspection tasks
    still in status `QUEUED` or `IN_PROGRESS` whose `due_utc` has arrived are
    moved to `ESCALATED`, but only while the station's posture is `CONGESTED` or
    `SUSPENDED` — a station running normally does not escalate its queue."

    Design: Difficulty/transitive_cascade/makeup_area_exhaustion_escalates_the_manual_queue
    """
    scenario = base_scenario(makeup_capacity_slots=2)
    task_bag, task = make_inspection_task(
        scenario, item_type="MOBILITY_DEVICE", induction_utc="2026-09-01T13:12:00Z")

    set_clock("2026-09-01T13:30:00Z")
    run_ops(scenario["st"])
    still_queued = get_success_data(api.get_inspection(
        task["id"], TEST_USERS["screener_headers"]))
    assert still_queued["status"] == "QUEUED", \
        "a station reading OPEN does not escalate its queue, however overdue"

    second = make_in_makeup_bag(scenario, bag_index=1, screen_start_utc="2026-09-01T07:40:00Z",
                                induction_utc="2026-09-01T13:36:00Z")
    assert get_station(scenario["st"])["posture"] == "CONGESTED"

    set_clock("2026-09-01T14:00:00Z")
    run_ops(scenario["st"])
    escalated = get_success_data(api.get_inspection(
        task["id"], TEST_USERS["screener_headers"]))
    assert escalated["status"] == "ESCALATED"


def test_escalation_removes_the_task_from_the_station_queue_depth(api):
    """PRD §2.11: "tasks that have been `RESOLVED` or `ESCALATED` are excluded."
    PRD §2.11: "manual inspection tasks whose status is `QUEUED` or
    `IN_PROGRESS`"

    Design: Difficulty/transitive_cascade/makeup_area_exhaustion_escalates_the_manual_queue
    """
    scenario = base_scenario(makeup_capacity_slots=2)
    task_bag, task = make_inspection_task(
        scenario, item_type="MOBILITY_DEVICE", induction_utc="2026-09-01T13:12:00Z")
    make_in_makeup_bag(scenario, bag_index=1, screen_start_utc="2026-09-01T07:40:00Z",
                       induction_utc="2026-09-01T13:36:00Z")

    set_clock("2026-09-01T14:00:00Z")
    run_ops(scenario["st"])
    assert get_success_data(api.get_inspection(
        task["id"], TEST_USERS["screener_headers"]))["status"] == "ESCALATED"

    station = get_station(scenario["st"])
    assert station["manual_queue_depth"] == 0, \
        "the escalated task left the {QUEUED, IN_PROGRESS} set"


def test_a_window_starting_exactly_at_the_previous_end_is_admitted(api):
    """PRD §2.8: "a lane may host a back-to-back window that starts at exactly
    the instant another window ends, and that adjacency is legal."

    Design: Difficulty/resource_temporal_overlap/screening_lane_windows_are_strict_half_open_with_no_buffer
    """
    scenario = base_scenario()
    bag = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], flight_id=scenario["f1"]),
        TEST_USERS["acceptance_agent_headers"]))
    weigh_ok(bag["id"], 48.0)

    first = get_success_data(api.create_screening(
        create_screening_payload(bag["id"], scenario["lane"], "2026-09-01T07:00:00Z"),
        TEST_USERS["screener_headers"]))
    assert first["end_utc"] == "2026-09-01T07:20:00Z"

    adjacent = validate_success(api.create_screening(
        create_screening_payload(bag["id"], scenario["lane"], "2026-09-01T07:20:00Z"),
        TEST_USERS["screener_headers"]), 201)
    assert adjacent["end_utc"] == "2026-09-01T07:40:00Z"


def test_a_window_landing_in_an_occupied_identity_bucket_is_refused(api):
    """PRD §2.8: "What the lane may not do is host two different non-`FAILED`
    windows in the same twenty-minute identity bucket, where the bucket is derived
    by flooring the window's start instant to twenty-minute granularity."

    Design: Difficulty/resource_temporal_overlap/screening_lane_windows_are_strict_half_open_with_no_buffer
    """
    scenario = base_scenario()
    bag = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], flight_id=scenario["f1"]),
        TEST_USERS["acceptance_agent_headers"]))
    weigh_ok(bag["id"], 48.0)
    api.create_screening(
        create_screening_payload(bag["id"], scenario["lane"], "2026-09-01T07:00:00Z"),
        TEST_USERS["screener_headers"])
    before_bag = get_bag(bag["id"])

    refused = api.create_screening(
        create_screening_payload(bag["id"], scenario["lane"], "2026-09-01T07:00:00Z"),
        TEST_USERS["screener_headers"])
    validate_error(refused, ApiErrorId.ERR_LANE_INTERVAL_CONFLICT, 409)

    after = get_bag(bag["id"])
    assert after["screening_status"] == before_bag["screening_status"], \
        "the refusal wrote no screening axis change"
    assert after["version"] == before_bag["version"], \
        "the refusal advanced no version"


def test_the_lane_adjacency_is_not_offered_to_a_make_up_area(api):
    """PRD §2.7: "the requested interval is the half-open span beginning at the
    requested induction instant floored to the buffer granularity and ending one
    interval-length later. Any existing occupied interval that falls in the same
    identity bucket conflicts with the claim regardless of how far apart the two
    intervals actually are"

    Design: Difficulty/resource_temporal_overlap/screening_lane_windows_are_strict_half_open_with_no_buffer
    """
    scenario = base_scenario(makeup_capacity_slots=4)
    # A sorted bag whose clearance has been torn up by the screening-axis cycle
    # edge: custody SORTED, screening IN_LINE, so the make-up claim is refused at
    # the clearance rung rather than at the interval-conflict rung.
    first = make_sorted_bag(scenario)
    noted = validate_success(api.update_bag(
        first["id"], {"expected_bag_version": first["version"],
                      "anomaly_note": "post-sortation X-ray recheck requested"},
        TEST_USERS["screener_headers"]), 200)
    assert noted["custody_status"] == "SORTED"
    assert noted["screening_status"] == "IN_LINE"

    set_clock("2026-09-01T13:48:00Z")
    refused = api.assign_makeup(
        noted["id"],
        create_assign_makeup_payload(noted["version"], scenario["ma"],
                                     "2026-09-01T13:48:00Z"),
        TEST_USERS["sortation_agent_headers"])
    validate_error(refused, ApiErrorId.ERR_SCREENING_NOT_CLEARED, 409)


def test_a_positive_slack_connection_is_still_gated_by_the_bag_screening(api):
    """PRD §2.13: "A bag whose screening status is
    `ALARMED`, `FAILED` or `IN_INSPECTION` may not advance past the screening
    stage."
    PRD §2.13: "It guards make-up assignment, loading, and connection
    confirmation."

    Design: Difficulty/cross_entity_state_dependency/connection_confirmation_depends_on_the_bag_screening_state
    """
    from test_helpers import make_transfer_bag

    scenario = base_scenario()
    onward = make_flight(scenario, flight_number="DL1788", bank_code="B2")
    bag, connection, onward, event = make_transfer_bag(
        scenario, onward_flight=onward, required_mct_minutes=75, alarmed=True)
    assert connection["connect_slack_minutes"] == 75, "the connection's own fields are fine"

    refused = api.confirm_connection(connection["id"], TEST_USERS["transfer_agent_headers"])
    validate_error(refused, ApiErrorId.ERR_SCREENING_NOT_CLEARED, 409)

    after = get_success_data(api.get_connection(
        connection["id"], TEST_USERS["transfer_agent_headers"]))
    assert after["status"] == "PENDING"


def test_the_confirm_succeeds_once_the_alarm_is_cleared(api):
    """PRD §3.8: "requires a slack of zero or more (`ERR_MCT_VIOLATION`, 409), and
    requires the bag's screening status to be `CLEARED`
    (`ERR_SCREENING_NOT_CLEARED`, 409). A successful confirmation moves the
    connection to `CONFIRMED`"

    Design: Difficulty/cross_entity_state_dependency/connection_confirmation_depends_on_the_bag_screening_state
    """
    from test_helpers import make_transfer_bag

    scenario = base_scenario()
    onward = make_flight(scenario, flight_number="DL1788", bank_code="B2")
    bag, connection, onward, event = make_transfer_bag(
        scenario, onward_flight=onward, required_mct_minutes=75, alarmed=True)
    api.resolve_screening(event["id"], "CLEARED", TEST_USERS["screener_headers"])

    confirmed = validate_success(api.confirm_connection(
        connection["id"], TEST_USERS["transfer_agent_headers"]), 200)
    assert confirmed["status"] == "CONFIRMED", \
        "the refusal tracked the bag's screening axis and not the connection's fields"


def test_a_negative_fifteen_slack_is_the_rush_procedure_boundary(api):
    """PRD §3.8: "Declaring rush is available from `PENDING`, from `CONFIRMED` and
    from `REACCOMMODATED`, and it requires a slack of at least negative fifteen
    minutes"

    Design: Difficulty/cross_entity_state_dependency/connection_confirmation_depends_on_the_bag_screening_state
    """
    from test_helpers import make_transfer_bag

    scenario = base_scenario()
    onward = make_flight(scenario, flight_number="DL1788", bank_code="B2")
    bag, connection, onward = make_transfer_bag(
        scenario, onward_flight=onward, required_mct_minutes=165)
    assert connection["connect_slack_minutes"] == -15

    rushed = validate_success(api.declare_rush(connection["id"],
                                               TEST_USERS["transfer_agent_headers"]), 200)
    assert rushed["status"] == "RUSH"
    assert rushed.get("rush_declared_utc") is not None, \
        "the declaration stamps the current logical clock instant"