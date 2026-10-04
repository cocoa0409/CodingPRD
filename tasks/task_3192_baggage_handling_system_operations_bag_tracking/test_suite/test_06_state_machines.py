"""State machines: refusals, idempotency, and the two non-linear cycles."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    set_clock, base_scenario, get_bag, get_area, get_flight, list_rows,
    create_bag_payload, create_scan_payload, weigh_ok, make_sorted_bag,
    make_alarmed_bag, make_failed_screening_bag, make_inspection_task,
    make_transfer_bag, delivered_bag_with_report, report_through_delivered,
    report_through_compensated, cycle_report_to_closed,
)


def test_a_weigh_against_a_sorted_bag_is_refused(api):
    """PRD §3.2: "An `AcceptanceAgent` supplies the measured `scale_weight_lb`,
    and a bag in the `ACCEPTED` custody state advances to `SCREENING`"
    PRD §2.13: "The target resource must be in a state that admits the requested transition, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/bag_weigh_from_sorted_returns_invalid_state
    """
    scenario = base_scenario()
    bag = make_sorted_bag(scenario)
    assert bag["custody_status"] == "SORTED"
    assert bag["screening_status"] == "CLEARED"

    response = api.weigh_bag(bag["id"], 48.5, TEST_USERS["acceptance_agent_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)


def test_a_refused_weigh_leaves_the_bag_particulars_untouched(api):
    """PRD §2.12: "A mismatch between the supplied token and the parent entity's
    current `version` is rejected with `ERR_STALE_VERSION` and HTTP 412, and no
    part of the operation is applied."
    PRD §3.2: "The `excess_weight_fee_cents` is computed by the rule below, the
    `handling_charge_cents` is set to its provisional figure by §3.4"

    Design: Corner/state_machines/bag_weigh_from_sorted_returns_invalid_state
    """
    scenario = base_scenario()
    bag = make_sorted_bag(scenario)
    before_version = bag["version"]

    api.weigh_bag(bag["id"], 48.5, TEST_USERS["acceptance_agent_headers"])

    after = get_bag(bag["id"])
    assert after["custody_status"] == "SORTED"
    assert after["screening_status"] == "CLEARED"
    assert after["scale_weight_lb"] == 48.0, "the refused weigh must not move the scale reading"
    assert after["version"] == before_version, "a refused transition advances no version"


def test_a_queued_inspection_task_cannot_be_claimed_twice(api):
    """PRD §3.3: "A `Screener` claims a queued task, which moves it to
    `IN_PROGRESS` and stamps the acting screener into `assigned_to`; a task may
    only be claimed while it is `QUEUED`"

    Design: Corner/state_machines/manual_inspection_task_cannot_be_claimed_twice
    """
    from test_helpers import make_alarmed_inspection_task

    scenario = base_scenario()
    bag, event, task = make_alarmed_inspection_task(scenario)

    first = validate_success(api.claim_inspection(task["id"],
                                                  TEST_USERS["screener_headers"]), 200)
    assert first["status"] == "IN_PROGRESS"

    second = api.claim_inspection(task["id"], TEST_USERS["screener_headers"])
    validate_error(second, ApiErrorId.ERR_INVALID_STATE, 409)


def test_the_queue_depth_still_counts_an_in_progress_task(api):
    """PRD §2.11: "The station's `manual_queue_depth` counts the station's manual
    inspection tasks whose status is `QUEUED` or `IN_PROGRESS`"

    Design: Corner/state_machines/manual_inspection_task_cannot_be_claimed_twice
    """
    from test_helpers import make_alarmed_inspection_task

    scenario = base_scenario()
    bag, event, task = make_alarmed_inspection_task(scenario)

    before = get_success_data(api.get_station(scenario["st"],
                                              TEST_USERS["platform_admin_headers"]))
    assert before["manual_queue_depth"] == 1

    api.claim_inspection(task["id"], TEST_USERS["screener_headers"])
    after = get_success_data(api.get_station(scenario["st"],
                                             TEST_USERS["platform_admin_headers"]))
    assert after["manual_queue_depth"] == 1, "IN_PROGRESS is still inside the counted set"


def test_an_alarmed_screening_event_cannot_be_resolved_twice(api):
    """PRD §3.2: "supplying the resolution through the alarm-resolution
    operation, which requires the event to actually be in `ALARMED` status — an
    attempt to resolve an event that is not alarmed is refused with
    `ERR_SCREENING_EVENT_NOT_ALARMED` (409)."

    Design: Corner/state_machines/screening_event_cannot_be_resolved_twice
    """
    scenario = base_scenario()
    bag, event = make_alarmed_bag(scenario)

    first = validate_success(api.resolve_screening(event["id"], "CLEARED",
                                                   TEST_USERS["screener_headers"]), 200)
    assert first["status"] == "CLEARED"
    assert first["resolution_outcome"] == "CLEARED"

    second = api.resolve_screening(event["id"], "REJECTED", TEST_USERS["screener_headers"])
    validate_error(second, ApiErrorId.ERR_SCREENING_EVENT_NOT_ALARMED, 409)

    kept = get_success_data(api.get_screening(event["id"], TEST_USERS["screener_headers"]))
    assert kept["resolution_outcome"] == "CLEARED", "the refusal must not overwrite the outcome"


def test_a_refused_resolution_leaves_the_bag_screening_axis_alone(api):
    """PRD §3.2: "A `CLEARED` outcome records `resolution_outcome` as `CLEARED`, stamps the acting screener into `resolved_by`, moves the event to `CLEARED`, and advances a bag still in `SCREENING` custody to `SORTED`"
    PRD §3.2: "a bag that had already been dropped to `HELD` keeps its held custody, and its alarm clearance alone does not release it"

    Design: Corner/state_machines/screening_event_cannot_be_resolved_twice
    """
    scenario = base_scenario()
    bag, event = make_alarmed_bag(scenario)
    assert bag["custody_status"] == "HELD"
    api.resolve_screening(event["id"], "CLEARED", TEST_USERS["screener_headers"])
    cleared = get_bag(bag["id"])
    api.resolve_screening(event["id"], "REJECTED", TEST_USERS["screener_headers"])

    after = get_bag(bag["id"])
    assert after["screening_status"] == "CLEARED"
    assert after["custody_status"] == cleared["custody_status"], \
        "the refused resolution changed neither axis"


def test_accessory_bag_screening_axis_cycles_cleared_back_to_in_line(api):
    """PRD §3.5: "A bag whose screening status is currently `CLEARED` is
    re-induced: its screening status moves back to `IN_LINE` and a scan capture
    at the `SCREENING` point is appended."

    Design: Difficulty/non_linear_state_machine/bag_screening_axis_cycles_cleared_back_to_in_line
    """
    scenario = base_scenario()
    bag = make_sorted_bag(scenario)
    assert bag["screening_status"] == "CLEARED"

    response = api.update_bag(
        bag["id"], {"expected_bag_version": bag["version"],
                    "anomaly_note": "post-sortation X-ray recheck requested"},
        TEST_USERS["screener_headers"])
    updated = validate_success(response, 200)
    assert updated["screening_status"] == "IN_LINE", \
        "the CLEARED -> IN_LINE cycle edge is what makes the axis non-linear"


def test_failed_bag_screening_axis_cycles_to_in_inspection_and_stays_held(api):
    """PRD §3.5: "A bag whose screening status is currently `FAILED` is instead
    re-inspected: its screening status moves to `IN_INSPECTION` and its custody
    status stays `HELD` while it reads `IN_INSPECTION`."

    Design: Difficulty/non_linear_state_machine/bag_screening_axis_cycles_cleared_back_to_in_line
    """
    scenario = base_scenario()
    bag, event = make_failed_screening_bag(scenario)
    assert bag["screening_status"] == "FAILED"
    assert bag["custody_status"] == "HELD"

    response = api.update_bag(
        bag["id"], {"expected_bag_version": bag["version"],
                    "anomaly_note": "reopen for secondary inspection"},
        TEST_USERS["screener_headers"])
    updated = validate_success(response, 200)
    assert updated["screening_status"] == "IN_INSPECTION"
    assert updated["custody_status"] == "HELD", \
        "IN_INSPECTION is not CLEARED, so the custody axis stays held"


def test_an_anomaly_note_from_in_line_is_refused(api):
    """PRD §2.13: "The target resource must be in a state that admits the requested transition, else `ERR_INVALID_STATE` (409)."
    PRD §3.5: "This is permitted only while the bag's custody status is
    `ACCEPTED`, `SCREENING`, `SORTED` or `HELD`; anything else is refused with
    `ERR_INVALID_STATE` (409)."

    Design: Difficulty/non_linear_state_machine/bag_screening_axis_cycles_cleared_back_to_in_line
    """
    scenario = base_scenario()
    bag = make_sorted_bag(scenario)
    first = validate_success(api.update_bag(
        bag["id"], {"expected_bag_version": bag["version"],
                    "anomaly_note": "first recheck"},
        TEST_USERS["screener_headers"]), 200)
    assert first["screening_status"] == "IN_LINE"

    second = api.update_bag(
        bag["id"], {"expected_bag_version": first["version"],
                    "anomaly_note": "second recheck"},
        TEST_USERS["screener_headers"])
    validate_error(second, ApiErrorId.ERR_INVALID_STATE, 409)


def test_a_report_cycles_from_closed_back_to_investigating(api):
    """PRD §3.11: "The full path runs `REPORTED` to `INVESTIGATING` to
    `DELIVERY_ARRANGED` to `DELIVERED` to `COMPENSATED` to `CLOSED`, with a
    `REOPENED` state reachable from both `COMPENSATED` and `CLOSED` and exiting
    back to `INVESTIGATING`."

    Design: Difficulty/non_linear_state_machine/mishandled_report_cycles_closed_back_to_investigating
    """
    scenario = base_scenario()
    _, bag, report = delivered_bag_with_report(scenario)
    closed = cycle_report_to_closed(scenario, report["id"])
    assert closed["status"] == "CLOSED"

    reopened = validate_success(api.reopen_report(
        report["id"], closed["version"], TEST_USERS["baggage_service_agent_headers"]), 200)
    assert reopened["status"] == "REOPENED"

    investigating = validate_success(api.investigate_report(
        report["id"], TEST_USERS["baggage_service_agent_headers"]), 200)
    assert investigating["status"] == "INVESTIGATING"


def test_reopening_a_compensated_report_zeroes_the_settled_amounts(api):
    """PRD §3.11: "Reopening a compensated report is a compensating action, not a
    status edit: besides moving the report to `REOPENED` and setting
    `claim_status` back to `FILED`, it zeroes both `compensation_settled_cents`
    and `approved_cents`, returns `final_liability_cents` to its provisional
    haircut figure"

    Design: Difficulty/non_linear_state_machine/mishandled_report_cycles_closed_back_to_investigating
    """
    scenario = base_scenario()
    _, bag, report = delivered_bag_with_report(scenario)
    compensated = report_through_compensated(scenario, report["id"])
    assert compensated["status"] == "COMPENSATED"
    assert compensated["compensation_settled_cents"] > 0

    reopened = validate_success(api.reopen_report(
        report["id"], compensated["version"],
        TEST_USERS["baggage_service_agent_headers"]), 200)
    assert reopened["status"] == "REOPENED"
    assert reopened["compensation_settled_cents"] == 0
    assert reopened["approved_cents"] == 0
    assert reopened["claim_status"] == "FILED"


def test_reopening_from_investigating_is_refused(api):
    """PRD §2.13: "The target resource must be in a state that admits the requested transition, else `ERR_INVALID_STATE` (409)."
    PRD §3.11: "with a `REOPENED` state reachable from both `COMPENSATED` and
    `CLOSED`"

    Design: Difficulty/non_linear_state_machine/mishandled_report_cycles_closed_back_to_investigating
    """
    scenario = base_scenario()
    _, bag, report = delivered_bag_with_report(scenario)
    investigating = get_success_data(api.investigate_report(
        report["id"], TEST_USERS["baggage_service_agent_headers"]))
    assert investigating["status"] == "INVESTIGATING"

    response = api.reopen_report(
        report["id"], investigating["version"],
        TEST_USERS["baggage_service_agent_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)