"""Boundary precision: thresholds pinned at their exact edge.

Covers the inclusive proficiency gate at exactly eighty percent and the
empty-collection edge of the interface validation pass rate.
"""

import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    assert_cost_precision,
    get_success_data,
    get_department,
    get_interface_channel,
    create_program,
    create_interface_channel,
    create_interface_message_payload,
    setup_department_with_cleared_staff,
    set_clock,
    TRAINING,
    INTERFACE,
    ANALYST,
)


# ===========================================================================
# r6_proficiency_gate_at_exactly_eighty_percent_opens
# ===========================================================================

def test_four_cleared_of_five_staffers_reports_exactly_eighty_and_opens_the_gate(api, analyst_headers):
    """PRD §3.4: "The department's proficiency measure is
    `proficiency_cleared_ratio`, the count of the department's staff whose status
    is `PROFICIENCY_VERIFIED` or `CREDENTIALED` — a figure the department also
    publishes as `proficiency_cleared_count` — expressed as a percentage of the
    department's `required_staff_count` and rounded half-up to two decimal
    places."
    PRD §3.4: "The gate itself, `proficiency_gate_open`, is true when the ratio is
    at least 80.00 — the boundary value is inclusive."

    Four verified staffers out of a required count of five is exactly 80.00, and
    the boundary opens the gate.

    Design: Difficulty/boundary_precision_check/r6_proficiency_gate_at_exactly_eighty_percent_opens
    """
    ctx = setup_department_with_cleared_staff(
        application_code="PHARM", required_staff_count=5, cleared_count=4,
        department_code="PHARM", curriculum_code="PHM100", exam_score=85,
    )

    dept = get_department(ctx["dept"]["id"], analyst_headers)
    assert dept["proficiency_cleared_count"] == 4
    assert dept["proficiency_cleared_ratio"] == pytest.approx(80.00, abs=0.01), (
        f"4 of 5 cleared is exactly 80.00; got {dept['proficiency_cleared_ratio']}"
    )
    assert dept["proficiency_gate_open"] is True, "the 80.00 boundary is inclusive"


def test_the_gate_boundary_admits_the_close_call_and_the_ratio_is_not_denominator_blind(api, analyst_headers, training_headers):
    """PRD §3.4: "Closing the gate to declare a department ready for go-live
    requires the gate to be open and the department's
    `build_blocking_defect_count` to be 0".
    PRD §3.4: "Staff in `REGISTERED`, `TRAINING_ASSIGNED`, `TRAINED` or
    `PROFICIENCY_FAILED` contribute nothing to the numerator while still counting
    in the denominator, so an untrained population drags the ratio down."

    The close call succeeds at the boundary, and the ratio is not 100.00 because
    the required count of five staffs the denominator beyond the four cleared.

    Design: Difficulty/boundary_precision_check/r6_proficiency_gate_at_exactly_eighty_percent_opens
    """
    ctx = setup_department_with_cleared_staff(
        application_code="PHARM", required_staff_count=5, cleared_count=4,
        department_code="PHARM", curriculum_code="PHM100", exam_score=85,
    )

    closed = validate_success(
        api.close_proficiency_gate(ctx["dept"]["id"], training_headers), 200
    )
    assert closed["status"] == "READY_FOR_GO_LIVE"
    assert closed["proficiency_cleared_ratio"] == pytest.approx(80.00, abs=0.01)
    assert closed["proficiency_cleared_ratio"] != pytest.approx(100.00, abs=0.01), (
        "the required_staff_count of 5 counts all five staffers, not just the four cleared"
    )
    assert closed["proficiency_cleared_ratio"] >= 80.00
    assert_cost_precision(closed["proficiency_cleared_ratio"])


def test_the_department_the_ratio_slid_is_the_one_the_close_recovers(api, analyst_headers, training_headers):
    """PRD §3.4: "A department whose ratio falls below the gate while it is
    `TRAINING_IN_PROGRESS` slides into `REMEDIATION_REQUIRED` on its own".
    PRD §3.4: "Closing the gate to declare a department ready for go-live requires
    the gate to be open and the department's `build_blocking_defect_count` to be
    0".

    A department that slid into `REMEDIATION_REQUIRED` and whose ratio has since
    reached the boundary is the department the close declares ready, so the close
    is admissible from that state as well as from `TRAINING_IN_PROGRESS`.

    Design: Difficulty/boundary_precision_check/r6_proficiency_gate_at_exactly_eighty_percent_opens
    """
    ctx = setup_department_with_cleared_staff(
        application_code="PHARM", required_staff_count=5, cleared_count=4,
        department_code="PHARM", curriculum_code="PHM100", exam_score=85,
    )
    slid = get_department(ctx["dept"]["id"], analyst_headers)
    assert slid["status"] == "REMEDIATION_REQUIRED", (
        "the fourth cleared staffer is the exam whose ratio reached the boundary"
    )
    assert slid["proficiency_gate_open"] is True

    closed = validate_success(
        api.close_proficiency_gate(ctx["dept"]["id"], training_headers), 200
    )
    assert closed["status"] == "READY_FOR_GO_LIVE"


# ===========================================================================
# r6_interface_pass_rate_empty_set_is_not_a_pass
# ===========================================================================

def test_a_channel_with_no_decided_messages_reports_zero_and_cannot_close(api, interface_headers):
    """PRD §3.6: "When no message has yet been decided the rate is 0.00 rather
    than undefined — an empty measurement is not a pass."
    PRD §3.6: "No facility may be granted cutover readiness, no program may
    finalize its validation phase, and no cutover step may complete while any
    interface channel of the program remains short of `VALIDATED`; the refusal
    carries `ERR_CHANNEL_NOT_VALIDATED` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/r6_interface_pass_rate_empty_set_is_not_a_pass
    """
    set_clock()
    prog = create_program()
    channel = create_interface_channel(
        prog["id"], channel_type="IMAGING", external_system="Visage",
        message_format="DICOM", throughput_per_hour=200, max_latency_minutes=10,
    )
    get_success_data(api_client.begin_channel_build(channel["id"], interface_headers))
    get_success_data(api_client.begin_message_validation(channel["id"], interface_headers))

    refused = api.complete_channel_validation(channel["id"], interface_headers)
    validate_error(refused, ApiErrorId.ERR_CHANNEL_NOT_VALIDATED, expected_status=422)

    read = get_interface_channel(channel["id"], interface_headers)
    assert read["interface_message_validation_pass_rate"] == pytest.approx(0.00, abs=0.01), (
        "an empty measurement reads 0.00, and 0.00 is not a pass"
    )
    assert read["status"] == "IN_MESSAGE_VALIDATION"


def test_nineteen_validated_and_one_rejected_lands_exactly_on_the_pass_floor(api, interface_headers):
    """PRD §3.6: "The pass rate is computed per epoch: it divides
    `validated_message_count` by the sum of `validated_message_count` and
    `rejected_message_count`, expressed as a percentage and rounded half-up to
    two decimals, and it counts only messages decided in the current epoch."
    PRD §3.6: "closing validation — the last of which requires the channel's
    `interface_message_validation_pass_rate` to have reached at least 95.00 and
    moves the channel to the terminal `VALIDATED`."

    19 of 20 decided messages is exactly 95.00, and the inclusive floor admits
    it. The single rejection is injected while the channel is still BUILDING,
    because the fall to `VALIDATION_FAILED` applies only to a channel that is
    currently `IN_MESSAGE_VALIDATION`.

    Design: Difficulty/boundary_precision_check/r6_interface_pass_rate_empty_set_is_not_a_pass
    """
    set_clock()
    prog = create_program()
    channel = create_interface_channel(
        prog["id"], channel_type="IMAGING", external_system="Visage",
        message_format="DICOM", throughput_per_hour=200, max_latency_minutes=10,
    )
    get_success_data(api_client.begin_channel_build(channel["id"], interface_headers))

    # One message that arrived far too slowly is rejected before validation opens.
    get_success_data(api_client.receive_message(
        channel["id"],
        create_interface_message_payload(
            message_code="DICOM_STOW", direction="INBOUND", sent_utc="2026-08-31T00:00:00Z"
        ),
        interface_headers,
    ))
    get_success_data(api_client.begin_message_validation(channel["id"], interface_headers))

    for _ in range(19):
        message = get_success_data(api_client.receive_message(
            channel["id"],
            create_interface_message_payload(
                message_code="DICOM_STOW", direction="INBOUND", sent_utc="2026-09-01T00:00:00Z"
            ),
            interface_headers,
        ))
        get_success_data(api_client.validate_message(message["id"], interface_headers))

    read = get_interface_channel(channel["id"], interface_headers)
    assert read["validated_message_count"] == 19
    assert read["rejected_message_count"] == 1
    assert read["interface_message_validation_pass_rate"] == pytest.approx(95.00, abs=0.01), (
        f"19 of 20 is exactly 95.00; got {read['interface_message_validation_pass_rate']}"
    )

    closed = validate_success(api.complete_channel_validation(channel["id"], interface_headers), 200)
    assert closed["status"] == "VALIDATED", "95.00 meets the floor inclusively"