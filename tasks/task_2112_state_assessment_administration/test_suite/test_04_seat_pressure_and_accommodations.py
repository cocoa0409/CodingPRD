"""Seat pressure arithmetic and the accommodation review split."""
from test_helpers import (
    ApiErrorId,
    TEST_CALENDAR,
    code_accommodations,
    create_accommodation_coding_payload,
    create_accommodation_decision_payload,
    create_session,
    create_transition_payload,
    decide_accommodations,
    deliver_lot_to_school,
    expected_effective_seat_capacity,
    make_district_coordinator_headers,
    make_proctor_headers,
    make_school_coordinator_headers,
    move_session,
    read_registration,
    read_session,
    register_student,
    session_checkout,
    set_clock,
    setup_program,
    setup_program_with_certified_proctor,
    setup_seat_pressure_session,
    setup_staffed_session,
    validate_error,
    validate_success,
)


def test_third_separate_setting_coding_breaches_the_effective_capacity(api):
    """PRD §3.4: "On the demand side, a registration is said to need a separate
    setting when any code currently on it is one of the three catalogued codes
    that require one. Such a registration has `seats_required` of 3 — one seat
    for the student plus 2 additional seats charged for the separate setting —
    and every other registration has `seats_required` of 1."
    PRD §3.4: "The penalty is computed by taking the session's
    `separate_setting_count`, subtracting the two separate settings a single
    proctor can absorb for free, dividing the remainder by 3, rounding that
    quotient up to the next whole number, treating any negative or zero result
    as zero, and multiplying by 4 seats."
    PRD §3.4: "After applying the request, `seats_consumed` may not exceed
    `effective_seat_capacity`; if it would, the whole request is rejected with
    `ERR_SESSION_CAPACITY_EXCEEDED` and nothing is written."

    Design: Difficulty/combinatorial_formula/effective_seat_capacity_nested_min_ceil_penalty_mode_a
    """
    ctx = setup_seat_pressure_session(seat_capacity=10, max_concurrent_seats=60)
    before = read_session(ctx["session"]["id"])
    assert before["separate_setting_count"] == 2
    assert before["seats_consumed"] == 7, "3 + 3 + 1 across the three live seats"
    assert before["effective_seat_capacity"] == 10, (
        "two separate settings are absorbed for free, so the penalty is still 0")

    third = ctx["registrations"][2]
    response = api.code_accommodations(
        third["id"], create_accommodation_coding_payload(["SMALL_GROUP"]),
        make_school_coordinator_headers(ctx["school"]["id"]))
    validate_error(response, ApiErrorId.ERR_SESSION_CAPACITY_EXCEEDED.value, 422)

    after = read_session(ctx["session"]["id"])
    assert after["seats_consumed"] == 7, "nothing is written when the gate fires"
    assert after["effective_seat_capacity"] == 10
    assert after["separate_setting_count"] == 2
    assert read_registration(third["id"])["accommodation_codes"] == [], (
        "the rejected coding call must leave the code list untouched")


def test_freeing_a_separate_setting_lets_the_same_coding_through(api):
    """PRD §3.4: "The session's `separate_setting_count` is the number of live
    registrations needing a separate setting, and its `seats_consumed` is the
    sum of `seats_required` across all live registrations."
    PRD §3.4: "The session's `effective_seat_capacity` is the smaller-of-the-two
    ceiling minus that penalty, floored at 0 so it never goes negative."
    PRD §3.4: "If every submitted code is standard-tier, the registration moves
    straight to `APPROVED` with no district involvement."

    Design: Difficulty/combinatorial_formula/effective_seat_capacity_nested_min_ceil_penalty_mode_a
    """
    ctx = setup_seat_pressure_session(seat_capacity=10, max_concurrent_seats=60)
    second, third = ctx["registrations"][1], ctx["registrations"][2]

    code_accommodations(second["id"], ["EXTENDED_TIME"], ctx["school"]["id"])

    accepted = validate_success(api.code_accommodations(
        third["id"], create_accommodation_coding_payload(["SMALL_GROUP"]),
        make_school_coordinator_headers(ctx["school"]["id"])))
    assert accepted["accommodation_status"] == "APPROVED", (
        "SMALL_GROUP is standard-tier and needs no district review")
    assert accepted["seats_required"] == 3

    session = read_session(ctx["session"]["id"])
    assert session["separate_setting_count"] == 2
    assert session["seats_consumed"] == 7, "3 + 1 + 3 across the three live seats"
    assert session["effective_seat_capacity"] == 10
    assert session["effective_seat_capacity"] == expected_effective_seat_capacity(
        10, 60, session["separate_setting_count"])
    assert read_registration(second["id"])["seats_required"] == 1


def test_standard_codes_auto_approve_while_a_specialized_code_routes_to_review(api):
    """PRD §3.4: "Review routing follows directly from the tiers present in the
    submitted list. If the submitted list is empty, the registration's
    `accommodation_status` becomes `NONE`. If any submitted code is
    specialized-tier, the registration moves to `REQUESTED` and waits for the
    district — the school that codes may never approve. If every submitted code
    is standard-tier, the registration moves straight to `APPROVED` with no
    district involvement."
    PRD §3.4: "`EXTENDED_TIME` is a standard-tier code that does not require a
    separate setting. `SMALL_GROUP` is a standard-tier code that does require
    one. `ASSISTIVE_TECH` is a standard-tier code that does not require one.
    `SEPARATE_ROOM` is a specialized-tier code that does require one.
    `READ_ALOUD` and `SCRIBE` are specialized-tier codes that do not require
    one. `BRAILLE_FORM` is a specialized-tier code that does require one."
    PRD §3.4: "The list may hold at most five entries, may not repeat an entry,
    and may only draw on the seven catalogued codes; a violation of any of those
    is `ERR_INVALID_REQUEST`."

    Design: Corner/calculations/standard_only_codes_auto_approve_while_specialized_codes_route_to_review
    """
    ctx = setup_program(district_code="NG-1018", school_code="EB-01",
                        lot_code="LOT-X1", seal_start=3500)
    session = create_session(ctx["window"]["id"], ctx["school"]["id"],
                             room_code="R101", seat_capacity=20)
    first = register_student(session["id"], ctx["school"]["id"],
                             student_state_id="S00000001")
    second = register_student(session["id"], ctx["school"]["id"],
                              student_state_id="S00000002",
                              guardian_email="g2@fam.example")

    standard = validate_success(api.code_accommodations(
        first["id"],
        create_accommodation_coding_payload(["EXTENDED_TIME", "ASSISTIVE_TECH"]),
        make_school_coordinator_headers(ctx["school"]["id"])))
    assert standard["accommodation_status"] == "APPROVED"
    assert standard["accommodation_codes"] == ["EXTENDED_TIME", "ASSISTIVE_TECH"]
    assert standard["seats_required"] == 1, "neither standard code needs a room"

    specialized = validate_success(api.code_accommodations(
        second["id"], create_accommodation_coding_payload(["SCRIBE"]),
        make_school_coordinator_headers(ctx["school"]["id"])))
    assert specialized["accommodation_status"] == "REQUESTED"
    assert specialized["seats_required"] == 1, "SCRIBE does not need a separate setting"

    pressured = read_session(session["id"])
    assert pressured["separate_setting_count"] == 0
    assert pressured["seats_consumed"] == 2

    duplicate = api.code_accommodations(
        second["id"],
        create_accommodation_coding_payload(
            ["EXTENDED_TIME", "SCRIBE", "EXTENDED_TIME"]),
        make_school_coordinator_headers(ctx["school"]["id"]))
    validate_error(duplicate, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    assert read_registration(second["id"])["accommodation_codes"] == ["SCRIBE"], (
        "the rejected list must not replace the standing one")


def test_a_seat_still_awaiting_district_review_blocks_the_room_from_opening(api):
    """PRD §3.6: "No registration on the session may still have an
    `accommodation_status` of `REQUESTED`, because a student whose accommodation
    package is still awaiting the district cannot be tested — that failure is
    `ERR_ACCOMMODATION_NOT_APPROVED`."
    PRD §3.4: "Approval moves `REQUESTED → APPROVED`; rejection moves
    `REQUESTED → REJECTED`. Either way the supplied text is stored in
    `accommodation_decision_note` and the registration's `version` increments."
    PRD §3.4: "On the demand side, a registration is said to need a separate
    setting when any code currently on it is one of the three catalogued codes
    that require one. Such a registration has `seats_required` of 3 — one seat
    for the student plus 2 additional seats charged for the separate setting —
    and every other registration has `seats_required` of 1."

    Design: Corner/validations/pending_accommodation_review_blocks_session_activation
    """
    ctx = setup_program_with_certified_proctor(
        district_code="NG-1031", school_code="QK-01", lot_code="LOT-V3",
        seal_start=4700)
    deliver_lot_to_school(ctx)
    built = setup_staffed_session(
        ctx, room_code="R101",
        students=[{"student_state_id": "S00000001", "grade": 10}],
        schedule=False)
    registration = built["registrations"][0]
    code_accommodations(registration["id"], ["SEPARATE_ROOM"], ctx["school"]["id"])
    session = move_session(built["session"]["id"], "SCHEDULED",
                           school_id=ctx["school"]["id"])
    session_checkout(ctx["lot"]["id"], ctx["proctor"]["id"], session["id"], 4)
    set_clock(TEST_CALENDAR["SESSION_START"])

    blocked = api.transition_session(
        session["id"], create_transition_payload("ACTIVE"),
        make_proctor_headers(ctx["proctor"]["id"]))
    validate_error(blocked, ApiErrorId.ERR_ACCOMMODATION_NOT_APPROVED.value, 422)
    assert read_session(session["id"])["status"] == "SCHEDULED"

    decided = validate_success(api.decide_accommodations(
        registration["id"],
        create_accommodation_decision_payload("APPROVE", note="IEP verified."),
        make_district_coordinator_headers(ctx["district"]["id"])))
    assert decided["accommodation_status"] == "APPROVED"
    assert decided["accommodation_decision_note"] == "IEP verified."
    assert decided["seats_required"] == 3, "SEPARATE_ROOM requires a separate setting"

    pressured = read_session(session["id"])
    assert pressured["separate_setting_count"] == 1
    assert pressured["seats_consumed"] == 3

    opened = validate_success(api.transition_session(
        session["id"], create_transition_payload("ACTIVE"),
        make_proctor_headers(ctx["proctor"]["id"])))
    assert opened["status"] == "ACTIVE"


def test_coding_and_deciding_accommodations_belong_to_different_roles(api):
    """PRD §2.11: "A `SchoolTestCoordinator` codes accommodations but may never
    decide them. A `DistrictTestCoordinator` decides accommodations but may
    never code them, and may never record a score."
    PRD §2.7: "**Role authorization**, including sub-operation ownership on the
    three multiplexing endpoints described in §2.1. Failure:
    `ERR_ROLE_NOT_PERMITTED` (403)."
    PRD §3.4: "Approval moves `REQUESTED → APPROVED`; rejection moves
    `REQUESTED → REJECTED`. Either way the supplied text is stored in
    `accommodation_decision_note` and the registration's `version` increments."

    Design: Corner/rbac/accommodation_coding_and_deciding_are_split_between_two_roles
    """
    ctx = setup_program(district_code="NG-1038", school_code="YW-01",
                        lot_code="LOT-T1", seal_start=5500)
    session = create_session(ctx["window"]["id"], ctx["school"]["id"],
                             room_code="R101", seat_capacity=20)
    registration = register_student(session["id"], ctx["school"]["id"],
                                    student_state_id="S00000001")
    code_accommodations(registration["id"], ["READ_ALOUD"], ctx["school"]["id"])

    district_codes = api.code_accommodations(
        registration["id"], create_accommodation_coding_payload(["EXTENDED_TIME"]),
        make_district_coordinator_headers(ctx["district"]["id"]))
    validate_error(district_codes, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    school_decides = api.decide_accommodations(
        registration["id"], create_accommodation_decision_payload("APPROVE"),
        make_school_coordinator_headers(ctx["school"]["id"]))
    validate_error(school_decides, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    rejected = validate_success(api.decide_accommodations(
        registration["id"],
        create_accommodation_decision_payload(
            "REJECT", note="No documentation on file."),
        make_district_coordinator_headers(ctx["district"]["id"])))
    assert rejected["accommodation_status"] == "REJECTED"
    assert rejected["accommodation_codes"] == ["READ_ALOUD"]
    assert rejected["accommodation_decision_note"] == "No documentation on file."


def test_cancelling_a_session_settles_its_seat_pressure_in_the_same_response(api):
    """PRD §3.6: "Both `DRAFT → CANCELLED` and `SCHEDULED → CANCELLED` behave
    identically: the `status` becomes `CANCELLED`, every registration on the
    session whose `attendance_status` is still `PENDING` moves
    `PENDING → WITHDRAWN`, the session then recomputes `seats_consumed`,
    `separate_setting_count`, and `effective_seat_capacity` over the surviving
    roster, and the session's `version` increments."
    PRD §3.6: "Withdrawn registrations stop contributing their `seats_required`
    to the session's demand."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/consistency_model/cancellation_cascade_is_visible_in_the_same_response
    """
    ctx = setup_program_with_certified_proctor(
        district_code="NG-1043", school_code="CR-01", lot_code="LOT-T4",
        seal_start=5800)
    built = setup_staffed_session(
        ctx, room_code="R101",
        students=[{"student_state_id": "S00000001", "grade": 10}],
        schedule=False)
    registration = built["registrations"][0]
    code_accommodations(registration["id"], ["SMALL_GROUP"], ctx["school"]["id"])
    session = move_session(built["session"]["id"], "SCHEDULED",
                           school_id=ctx["school"]["id"])

    cancelled = validate_success(api.transition_session(
        session["id"], create_transition_payload("CANCELLED",
                                                 reason="Room flooded."),
        make_school_coordinator_headers(ctx["school"]["id"])))

    assert cancelled["status"] == "CANCELLED"
    assert cancelled["seats_consumed"] == 0, (
        "the cancel response already carries the recomputed demand")
    assert cancelled["separate_setting_count"] == 0
    assert cancelled["effective_seat_capacity"] == 20

    withdrawn = validate_success(api.get_registration(
        registration["id"], make_school_coordinator_headers(ctx["school"]["id"])))
    assert withdrawn["attendance_status"] == "WITHDRAWN"
    assert withdrawn["accommodation_status"] == "APPROVED", (
        "the accommodation axis is untouched by the withdrawal")
    assert withdrawn["seats_required"] == 3
