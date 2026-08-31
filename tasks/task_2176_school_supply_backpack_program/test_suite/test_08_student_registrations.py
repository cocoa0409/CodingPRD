"""Registering students, reserving kits, and working the waitlist."""

from test_helpers import (
    ApiErrorId,
    assert_student_registration,
    assert_unit_conservation,
    confirm_registration,
    create_registration,
    create_verified_registration,
    event_version,
    make_school_liaison_headers,
    move_cycle,
    move_event,
    move_registration,
    read_position,
    read_registration,
    setup_backpack_program,
    validate_error,
    validate_paginated,
    validate_success,
    waitlist_registration,
)
from test_helpers import TEST_USERS

PD = TEST_USERS["program_director_headers"]
WL = TEST_USERS["warehouse_lead_headers"]


def test_registration_inside_the_back_to_school_lead_time_is_rejected(api):
    """PRD §3.7: "The cadence-dependent lead time then applies, measured against the
    logical clock of §2.5: the interval from the current logical instant to the event's
    `window_start` must be at least forty-eight hours when the governing cycle's
    `cadence` is `BACK_TO_SCHOOL`, and at least two hours when it is `YEAR_ROUND`,
    otherwise `ERR_REGISTRATION_LEAD_TIME`."
    PRD §2.5: "It maintains a **logical clock** which, before any operator has moved it,
    reads exactly `2026-08-01T00:00:00Z`; it never falls back to real time."

    Design: Corner/validations/registration_inside_back_to_school_lead_time_is_rejected
    """
    program = setup_backpack_program(
        backpack_on_hand=0,
        seat_capacity=10,
        cadence="BACK_TO_SCHOOL",
        event_window_start="2026-08-02T00:00:00Z",
        event_window_end="2026-08-02T04:00:00Z",
    )

    response = api.create_student_registration(
        {
            "distribution_event_id": program.event_id,
            "student_reference": "S-001",
            "grade_band": "K_2",
            "guardian_name": "G One",
            "free_lunch_eligible": True,
        },
        make_school_liaison_headers(program.school_id),
    )
    validate_error(response, ApiErrorId.ERR_REGISTRATION_LEAD_TIME.value, expected_status=422)

    rows, _ = validate_paginated(api.list_event_student_registrations(program.event_id, PD))
    assert rows == []


def test_registration_grade_band_must_equal_the_event_band(api):
    """PRD §3.7: "Finally the student's `grade_band` must equal the event's
    `grade_band`, or `ERR_GRADE_BAND_MISMATCH` applies."

    Design: Corner/validations/registration_grade_band_must_match_the_event_band
    """
    program = setup_backpack_program(backpack_on_hand=2, seat_capacity=10)

    response = api.create_student_registration(
        {
            "distribution_event_id": program.event_id,
            "student_reference": "S-001",
            "grade_band": "G3_5",
            "guardian_name": "G One",
            "free_lunch_eligible": True,
        },
        make_school_liaison_headers(program.school_id),
    )
    validate_error(response, ApiErrorId.ERR_GRADE_BAND_MISMATCH.value, expected_status=422)

    rows, _ = validate_paginated(api.list_event_student_registrations(program.event_id, PD))
    assert rows == []


def test_verification_requires_free_lunch_or_income_evidence(api):
    """PRD §3.7: "Verification moves `PENDING` to `VERIFIED`. It requires the
    registration to be `PENDING`, requires the governing event to be `PUBLISHED`, and
    requires eligibility evidence: at least one of `free_lunch_eligible` or
    `income_verified` must be true, and a registration with neither is refused with
    `ERR_ELIGIBILITY_NOT_MET`."
    PRD §3.7: "The registration is created in `PENDING` with `verified_at` null and
    `reserved_unit_count` at 0."

    Design: Corner/validations/verification_requires_free_lunch_or_income_evidence
    """
    program = setup_backpack_program(backpack_on_hand=2, seat_capacity=10)
    registration = create_registration(
        program.event_id, program.school_id,
        student_reference="S-001", free_lunch_eligible=False, income_verified=False,
    )

    response = move_registration(
        registration["id"], program.event_id, program.school_id, "VERIFIED"
    )
    validate_error(response, ApiErrorId.ERR_ELIGIBILITY_NOT_MET.value, expected_status=422)

    reread = read_registration(registration["id"])
    assert_student_registration(reread)
    assert reread["eligibility_status"] == "PENDING"
    assert reread["verified_at"] is None


def test_duplicate_student_reference_on_one_event_is_rejected(api):
    """PRD §3.7: "Uniqueness follows: at most one registration may exist for a given
    pairing of `distribution_event_id` and `student_reference` among registrations
    whose `eligibility_status` is anything other than `WITHDRAWN`, so a withdrawn
    registration frees the reference for reuse and a live one does not; a repeat is
    `ERR_DUPLICATE_STUDENT_REGISTRATION`."

    Design: Corner/validations/duplicate_student_reference_on_one_event_is_rejected
    """
    program = setup_backpack_program(backpack_on_hand=2, seat_capacity=10)
    first = create_registration(
        program.event_id, program.school_id, student_reference="S-001", guardian_name="G One"
    )

    response = api.create_student_registration(
        {
            "distribution_event_id": program.event_id,
            "student_reference": "S-001",
            "grade_band": "K_2",
            "guardian_name": "G Other",
            "income_verified": True,
        },
        make_school_liaison_headers(program.school_id),
    )
    validate_error(
        response, ApiErrorId.ERR_DUPLICATE_STUDENT_REGISTRATION.value, expected_status=409
    )

    rows, _ = validate_paginated(api.list_event_student_registrations(program.event_id, PD))
    assert len(rows) == 1
    assert rows[0]["id"] == first["id"]


def test_confirmation_beyond_the_seat_capacity_is_rejected(api):
    """PRD §3.7: "Both require the registration's `eligibility_status` to currently be
    `VERIFIED` or `WAITLISTED`, both require the event to be `PUBLISHED`, both require
    the event's `confirmed_count` to be strictly less than its `seat_capacity` — a full
    house is `ERR_EVENT_CAPACITY_FULL` — and both require that, for every line of the
    event's published needs list, the position's `on_hand_qty` be at least that line's
    `qty_per_student`, since a partial kit is no kit; a shortfall is
    `ERR_INSUFFICIENT_INVENTORY`."

    Design: Corner/validations/confirmation_beyond_seat_capacity_is_rejected
    """
    program = setup_backpack_program(backpack_on_hand=2, seat_capacity=1)
    first = create_verified_registration(
        program.event_id, program.school_id, student_reference="S-001", guardian_name="G One"
    )
    second = create_verified_registration(
        program.event_id, program.school_id, student_reference="S-002", guardian_name="G Two"
    )
    confirm_registration(first["id"], program.event_id, program.school_id)

    response = move_registration(
        second["id"], program.event_id, program.school_id, "CONFIRMED"
    )
    validate_error(response, ApiErrorId.ERR_EVENT_CAPACITY_FULL.value, expected_status=409)

    assert read_registration(second["id"])["eligibility_status"] == "VERIFIED"
    event = validate_success(api.get_distribution_event(program.event_id, PD))
    assert event["confirmed_count"] == 1
    position = read_position(program.cycle_id, program.backpack_id)
    assert position["on_hand_qty"] == 1
    assert position["reserved_qty"] == 1


def test_a_rejected_registration_cannot_be_verified_afterwards(api):
    """PRD §3.7: "A registration move that is not declared from the registration's
    current `eligibility_status` is rejected with `ERR_INVALID_REGISTRATION_STATE`, and
    — as §2.7 sets out — that check is made before the governing event's own status
    precondition, which fails with `ERR_INVALID_EVENT_STATE`."
    PRD §3.7: "A `PENDING` registration may instead be moved to `REJECTED`, which
    requires only that it be `PENDING` and which increments the event's and the
    registration's `version` by 1 apiece."

    Design: Corner/state_machines/rejected_registration_cannot_be_verified_afterwards
    """
    program = setup_backpack_program(backpack_on_hand=2, seat_capacity=10)
    registration = create_registration(program.event_id, program.school_id, student_reference="S-001")
    validate_success(
        move_registration(registration["id"], program.event_id, program.school_id, "REJECTED")
    )

    response = move_registration(
        registration["id"], program.event_id, program.school_id, "VERIFIED"
    )
    validate_error(
        response, ApiErrorId.ERR_INVALID_REGISTRATION_STATE.value, expected_status=409
    )

    assert read_registration(registration["id"])["eligibility_status"] == "REJECTED"
    assert validate_success(api.get_distribution_event(program.event_id, PD))["status"] == "PUBLISHED"


def test_stale_distribution_event_version_is_rejected(api):
    """PRD §2.8: "If the supplied value does not equal the event's current `version`,
    the request is rejected with `ERR_STALE_EVENT_VERSION` and HTTP 412, and nothing is
    written."

    Design: Corner/cross_cutting_complexity_layers/stale_distribution_event_version_is_rejected_with_412
    """
    program = setup_backpack_program(backpack_on_hand=0, seat_capacity=10)
    first = create_registration(
        program.event_id, program.school_id, student_reference="S-001", guardian_name="G One"
    )
    second = create_registration(
        program.event_id, program.school_id, student_reference="S-002", guardian_name="G Two"
    )
    observed = event_version(program.event_id, program.school_id)

    validate_success(
        move_registration(
            first["id"], program.event_id, program.school_id, "VERIFIED",
            expected_version=observed,
        )
    )

    response = move_registration(
        second["id"], program.event_id, program.school_id, "VERIFIED",
        expected_version=observed,
    )
    validate_error(response, ApiErrorId.ERR_STALE_EVENT_VERSION.value, expected_status=412)

    assert read_registration(second["id"])["eligibility_status"] == "PENDING"
    assert read_registration(first["id"])["eligibility_status"] == "VERIFIED"


def test_waitlisting_a_confirmed_student_gives_the_seat_and_the_units_back(api):
    """PRD §3.7: "Coming from `CONFIRMED` the move is the compensating leg of the unit
    conservation identity: for every line of the needs list, `qty_per_student` is
    subtracted from `reserved_qty` and added back to `on_hand_qty`, the registration's
    `reserved_unit_count` becomes 0, the event's `confirmed_count` and `waitlist_count`
    are refreshed, the school's `students_served_interim_count` and
    `impact_index_interim` are recomputed, the cycle's `total_items_on_hand` is
    recomputed, and `version` is incremented by 1 on the registration, the event, the
    positions, the cycle and the school."

    Design: Difficulty/non_linear_state_machine/registration_confirmed_waitlisted_confirmed_cycle
    """
    program = setup_backpack_program(backpack_on_hand=1, seat_capacity=1)
    registration = create_verified_registration(program.event_id, program.school_id)
    confirm_registration(registration["id"], program.event_id, program.school_id)

    waitlisted = waitlist_registration(registration["id"], program.event_id, program.school_id)
    assert waitlisted["eligibility_status"] == "WAITLISTED"
    assert waitlisted["reserved_unit_count"] == 0

    position = read_position(program.cycle_id, program.backpack_id)
    assert position["on_hand_qty"] == 1, "the released backpack is back on the shelf"
    assert position["reserved_qty"] == 0
    assert_unit_conservation(position)


def test_a_waitlisted_student_can_be_confirmed_again_on_the_same_row(api):
    """PRD §3.7: "Confirmation is reachable from `VERIFIED` and from `WAITLISTED`, and
    the two paths are specified identically."
    PRD §3.7: "Confirmation is the forward leg of the unit conservation identity: for
    every line, `qty_per_student` is subtracted from `on_hand_qty` and added to
    `reserved_qty`, leaving both sides of the identity untouched."
    PRD §3.7: "The registration's `reserved_unit_count` is set to the sum of
    `qty_per_student` over the needs list's lines, the event's `confirmed_count` and
    `waitlist_count` are refreshed, and the school's `students_served_interim_count`
    and `impact_index_interim` are recomputed."

    Design: Difficulty/non_linear_state_machine/registration_confirmed_waitlisted_confirmed_cycle
    """
    program = setup_backpack_program(backpack_on_hand=1, seat_capacity=1)
    registration = create_verified_registration(program.event_id, program.school_id)
    confirm_registration(registration["id"], program.event_id, program.school_id)
    waitlist_registration(registration["id"], program.event_id, program.school_id)

    reconfirmed = confirm_registration(registration["id"], program.event_id, program.school_id)
    assert reconfirmed["eligibility_status"] == "CONFIRMED"
    assert reconfirmed["reserved_unit_count"] == 1

    position = read_position(program.cycle_id, program.backpack_id)
    assert position["on_hand_qty"] == 0
    assert position["reserved_qty"] == 1
    assert_unit_conservation(position)

    event = validate_success(api.get_distribution_event(program.event_id, PD))
    assert event["confirmed_count"] == 1
    assert event["waitlist_count"] == 0


def test_the_reservation_leg_moves_units_without_disturbing_either_side(api):
    """PRD §2.9: "For every position, the sum of `on_hand_qty`, `reserved_qty`,
    `distributed_qty` and `damaged_qty` equals the sum of `accepted_donated_qty`,
    `purchased_received_qty` and `adjustment_qty`."
    PRD §3.7: "Confirmation is the forward leg of the unit conservation identity: for
    every line, `qty_per_student` is subtracted from `on_hand_qty` and added to
    `reserved_qty`, leaving both sides of the identity untouched."

    Design: Difficulty/compensating_invariant/confirm_then_waitlist_conserves_physical_units
    """
    program = setup_backpack_program(backpack_on_hand=3, seat_capacity=4)
    registration = create_verified_registration(program.event_id, program.school_id)

    confirm_registration(registration["id"], program.event_id, program.school_id)

    position = validate_success(api.get_inventory_position(program.position_id, WL))
    assert position["on_hand_qty"] == 2
    assert position["reserved_qty"] == 1
    assert position["adjustment_qty"] == 3
    assert_unit_conservation(position)


def test_the_compensating_leg_restores_the_position_exactly(api):
    """PRD §2.9: "Note the consequence for reservations: moving units from
    `on_hand_qty` into `reserved_qty` and back again shifts terms only on the left-hand
    side, so both sides must be untouched by any reserve or release."
    PRD §3.7: "Coming from `CONFIRMED` the move is the compensating leg of the unit
    conservation identity: for every line of the needs list, `qty_per_student` is
    subtracted from `reserved_qty` and added back to `on_hand_qty`, the registration's
    `reserved_unit_count` becomes 0, the event's `confirmed_count` and `waitlist_count`
    are refreshed, the school's `students_served_interim_count` and
    `impact_index_interim` are recomputed, the cycle's `total_items_on_hand` is
    recomputed, and `version` is incremented by 1 on the registration, the event, the
    positions, the cycle and the school."

    Design: Difficulty/compensating_invariant/confirm_then_waitlist_conserves_physical_units
    """
    program = setup_backpack_program(backpack_on_hand=3, seat_capacity=4)
    registration = create_verified_registration(program.event_id, program.school_id)
    confirm_registration(registration["id"], program.event_id, program.school_id)

    waitlist_registration(registration["id"], program.event_id, program.school_id)

    position = validate_success(api.get_inventory_position(program.position_id, WL))
    assert position["on_hand_qty"] == 3
    assert position["reserved_qty"] == 0
    assert position["distributed_qty"] == 0
    assert position["damaged_qty"] == 0
    assert position["adjustment_qty"] == 3
    assert_unit_conservation(position)

    assert read_registration(registration["id"])["reserved_unit_count"] == 0
    assert validate_success(api.get_drive_cycle(program.cycle_id, PD))["total_items_on_hand"] == 3


def _locked_full_event_scenario():
    """A one-seat event, already full with one CONFIRMED student and a second student
    left at VERIFIED, then locked with the cycle in DISTRIBUTION."""
    program = setup_backpack_program(backpack_on_hand=4, seat_capacity=1)
    first = create_verified_registration(
        program.event_id, program.school_id, student_reference="S-001", guardian_name="G One"
    )
    second = create_verified_registration(
        program.event_id, program.school_id, student_reference="S-002", guardian_name="G Two"
    )
    confirm_registration(first["id"], program.event_id, program.school_id)
    validate_success(move_cycle(program.cycle_id, "SORTING"))
    validate_success(move_cycle(program.cycle_id, "DISTRIBUTION"))
    validate_success(move_event(program.event_id, program.school_id, "LOCKED"))
    return program, second


def test_locked_event_state_is_reported_rather_than_the_full_house(api):
    """PRD §3.7: "Both require the registration's `eligibility_status` to currently be
    `VERIFIED` or `WAITLISTED`, both require the event to be `PUBLISHED`, both require
    the event's `confirmed_count` to be strictly less than its `seat_capacity` — a full
    house is `ERR_EVENT_CAPACITY_FULL` — and both require that, for every line of the
    event's published needs list, the position's `on_hand_qty` be at least that line's
    `qty_per_student`, since a partial kit is no kit; a shortfall is
    `ERR_INSUFFICIENT_INVENTORY`."
    PRD §2.7: "The registration's own from-state is checked **first** and fails with
    `ERR_INVALID_REGISTRATION_STATE`; only when that passes is the event's status
    precondition examined, failing with `ERR_INVALID_EVENT_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/locked_event_state_beats_seat_capacity_full
    """
    program, second = _locked_full_event_scenario()

    response = move_registration(
        second["id"], program.event_id, program.school_id, "CONFIRMED"
    )
    validate_error(response, ApiErrorId.ERR_INVALID_EVENT_STATE.value, expected_status=409)


def test_the_capacity_rule_never_masks_the_earlier_state_rule(api):
    """PRD §2.7: "25. Seat capacity when a registration is confirmed —
    `ERR_EVENT_CAPACITY_FULL`, 409."
    PRD §2.7: "Every rule in this system has a fixed priority, the rules are evaluated
    in strictly ascending priority order, and **the first rule that fails decides the
    response** — no later rule can override or mask an earlier one, and no earlier rule
    may be skipped because a later one looks more specific."

    Design: Difficulty/priority_pair_validation_conflict/locked_event_state_beats_seat_capacity_full
    """
    program, second = _locked_full_event_scenario()

    response = move_registration(
        second["id"], program.event_id, program.school_id, "CONFIRMED"
    )
    error = response.json()["data"]
    assert error["error_id"] != ApiErrorId.ERR_EVENT_CAPACITY_FULL.value, (
        "the seat-capacity rule sits below the state rule in the ladder"
    )
    assert error["error_id"] == ApiErrorId.ERR_INVALID_EVENT_STATE.value

    assert read_registration(second["id"])["eligibility_status"] == "VERIFIED"
    event = validate_success(api.get_distribution_event(program.event_id, PD))
    assert event["confirmed_count"] == 1
