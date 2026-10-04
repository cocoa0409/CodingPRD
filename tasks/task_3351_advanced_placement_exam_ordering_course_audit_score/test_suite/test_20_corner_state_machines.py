"""Invalid and terminal transitions on four different machines."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    MID_REGULAR_CLOCK_UTC,
    REVIEWER,
    api_client,
    calibrate_reader,
    create_audit,
    create_order,
    create_registration,
    create_school,
    get_order,
    get_registration,
    get_school,
    host_headers,
    recruit_reader,
    set_clock,
    setup_approved_school,
    setup_open_order,
    transition_registration,
    validate_error,
    validate_paginated,
)


def _school_audits(school_id):
    data, _meta = validate_paginated(
        api_client.list_course_audits(ADMIN, params={"school_id": school_id})
    )
    return data


def test_course_audit_cannot_jump_from_submitted_straight_to_approved():
    """PRD §3.1: "Review is a two-step movement."
    PRD §3.1: "From `IN_REVIEW`, a `CourseAuditReviewer` may move the audit to `APPROVED` only when the actor is not the submitter, `decision_notes` is non-empty, `review_round` is at least 1, and the owning school's test-center dimension is `ACTIVE`."
    PRD §2.6: "| 7 | The entity's current status admits the requested `to_status` | `ERR_INVALID_STATE` | 409 |"

    Design: Corner/state_machines/course_audit_invalid_transition_submitted_to_approved
    """
    school = create_school()
    audit = create_audit(school)

    response = api_client.transition_course_audit(
        audit["id"],
        {
            "to_status": "APPROVED",
            "expected_course_audit_version": audit["version"],
            "decision_notes": "looks fine",
        },
        REVIEWER,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)

    stored = _school_audits(school["id"])[0]
    assert stored["status"] == "SUBMITTED"
    assert stored["version"] == audit["version"]
    assert get_school(school["id"])["program_label_authorized"] is False


def test_cancelled_registration_cannot_be_reconfirmed():
    """PRD §3.3: "`CANCELLED` and `INVALIDATED` are the registration's terminal states."
    PRD §3.3: "Cancelling a registration in `REGISTERED`, `FEE_PENDING` or `CONFIRMED` sets `refundable_cents` to the 18000-cent base exam fee"
    PRD §2.6: "| 7 | The entity's current status admits the requested `to_status` | `ERR_INVALID_STATE` | 409 |"

    Design: Corner/state_machines/exam_registration_terminal_cancelled_rejects_confirmed
    """
    bundle = setup_open_order(clock=MID_REGULAR_CLOCK_UTC)
    registration = create_registration(
        bundle["order"], bundle["student"], bundle["school"], exam_subject="AP-CHEM"
    )
    registration = transition_registration(registration, "CONFIRMED", school=bundle["school"])
    registration = transition_registration(registration, "CANCELLED", school=bundle["school"])

    response = api_client.transition_exam_registration(
        registration["id"], {"to_status": "CONFIRMED"}, host_headers(bundle["school"])
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)

    after = get_registration(registration["id"])
    assert after["status"] == "CANCELLED"
    assert after["refundable_cents"] == 18000


def test_inactive_reader_cannot_return_to_calibrating():
    """PRD §3.7: "A `CALIBRATED` reader with no assigned scores may be retired to `INACTIVE` by a `PlatformAdmin`, which sets `load_status` to `INACTIVE`; `INACTIVE` is the reader's terminal state."
    PRD §2.6: "| 7 | The entity's current status admits the requested `to_status` | `ERR_INVALID_STATE` | 409 |"

    Design: Corner/state_machines/reader_terminal_inactive_rejects_calibrating
    """
    from test_helpers import get_success_data

    reader = calibrate_reader(recruit_reader("AP-STAT"))
    retired = get_success_data(
        api_client.transition_reader(reader["id"], {"to_status": "INACTIVE"}, ADMIN)
    )
    assert retired["calibration_status"] == "INACTIVE"

    response = api_client.transition_reader(reader["id"], {"to_status": "CALIBRATING"}, ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)

    after = get_success_data(api_client.get_reader(reader["id"], ADMIN))
    assert after["calibration_status"] == "INACTIVE"
    assert after["load_status"] == "INACTIVE"


def test_voided_order_cannot_be_reopened():
    """PRD §3.2: "`DELIVERED` and `VOIDED` are the order's terminal states."
    PRD §3.2: "A coordinator may void a `DRAFT` or an `OPEN` order"
    PRD §2.6: "| 7 | The entity's current status admits the requested `to_status` | `ERR_INVALID_STATE` | 409 |"

    Design: Corner/state_machines/exam_order_terminal_voided_rejects_open
    """
    from test_helpers import get_success_data

    bundle = setup_approved_school()
    set_clock(MID_REGULAR_CLOCK_UTC)
    order = create_order(bundle["school"], bundle["audit"])

    voided = get_success_data(
        api_client.transition_exam_order(
            order["id"],
            {"to_status": "VOIDED", "expected_exam_order_version": order["version"]},
            host_headers(bundle["school"]),
        )
    )
    assert voided["status"] == "VOIDED"

    response = api_client.transition_exam_order(
        order["id"],
        {"to_status": "OPEN", "expected_exam_order_version": voided["version"]},
        host_headers(bundle["school"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)

    assert get_order(order["id"])["status"] == "VOIDED"
    assert get_school(bundle["school"]["id"])["program_label_authorized"] is True
