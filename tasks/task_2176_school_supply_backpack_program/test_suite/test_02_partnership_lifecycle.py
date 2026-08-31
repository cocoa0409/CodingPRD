"""Partnering with a school, archiving it, and the four-hop suspension cascade."""

from test_helpers import (
    ApiErrorId,
    assert_pct_equals,
    assert_unit_conservation,
    confirm_registration,
    create_registration,
    create_school,
    move_school,
    read_position,
    read_registration,
    setup_backpack_program,
    validate_error,
    validate_success,
    verify_registration,
)
from test_helpers import TEST_USERS

PD = TEST_USERS["program_director_headers"]


def test_school_cannot_jump_from_prospect_straight_to_active(api):
    """PRD §3.1: "Moving to `MOU_PENDING` requires the school to be in `PROSPECT`.
    Moving from `MOU_PENDING` to `ACTIVE` requires the school to be in `MOU_PENDING`
    and to have a `max_concurrent_seats` of at least 1."
    PRD §2.7: "9. State legality: the requested transition is declared from the
    entity's current state and the requested `target_status` is a legal member of that
    entity's enumeration."

    Design: Corner/state_machines/school_direct_prospect_to_active_is_rejected
    """
    school = create_school()

    response = move_school(school["id"], "ACTIVE")
    validate_error(response, ApiErrorId.ERR_INVALID_SCHOOL_STATE.value, expected_status=409)

    reread = validate_success(api.get_school(school["id"], PD))
    assert reread["partnership_status"] == "PROSPECT"
    assert reread["version"] == 1, "a rejected transition must not bump the version"


def test_archived_school_is_terminal(api):
    """PRD §3.1: "On success every needs list of the school still in `PUBLISHED` moves
    to `RETIRED`, the school's `target_student_count` is recomputed and therefore
    becomes 0, and the school's `version` is incremented by 1. `ARCHIVED` is terminal."

    Design: Corner/state_machines/archived_school_is_terminal_and_rejects_further_transitions
    """
    school = create_school()
    validate_success(move_school(school["id"], "MOU_PENDING"))
    validate_success(move_school(school["id"], "ACTIVE"))
    validate_success(move_school(school["id"], "ARCHIVED"))

    response = move_school(school["id"], "ACTIVE")
    validate_error(response, ApiErrorId.ERR_INVALID_SCHOOL_STATE.value, expected_status=409)

    reread = validate_success(api.get_school(school["id"], PD))
    assert reread["partnership_status"] == "ARCHIVED"


def test_suspension_cancels_the_published_event_and_withdraws_its_registration(api):
    """PRD §3.1: "A school in `ACTIVE` moved to `SUSPENDED` triggers, at hop one, the
    cancellation of every one of its distribution events whose status is `DRAFT` or
    `PUBLISHED`, each moving to `CANCELLED`; events already in `LOCKED`, `CLOSED` or
    `CANCELLED` are left exactly as they are."
    PRD §3.1: "Hop two, caused by hop one, withdraws every student registration on
    each just-cancelled event whose `eligibility_status` is `PENDING`, `VERIFIED`,
    `CONFIRMED` or `WAITLISTED`, moving each to `WITHDRAWN`."

    Design: Difficulty/transitive_cascade/school_suspension_four_hop_cascade_releases_reserved_units
    """
    program = setup_backpack_program(backpack_on_hand=2, seat_capacity=5)
    registration = create_registration(program.event_id, program.school_id, free_lunch_eligible=True)
    verify_registration(registration["id"], program.event_id, program.school_id)
    confirm_registration(registration["id"], program.event_id, program.school_id)

    school = validate_success(move_school(program.school_id, "SUSPENDED"))
    assert school["partnership_status"] == "SUSPENDED"

    event = validate_success(api.get_distribution_event(program.event_id, PD))
    assert event["status"] == "CANCELLED", "hop one must cancel the PUBLISHED event"

    reread = read_registration(registration["id"])
    assert reread["eligibility_status"] == "WITHDRAWN", "hop two must withdraw the registration"


def test_suspension_releases_reserved_units_and_recomputes_the_interim_index(api):
    """PRD §3.1: "Hop three, caused by hop two, releases the reservations of exactly
    those registrations that were `CONFIRMED` at hop two: for every line of the event's
    published needs list, that line's `qty_per_student` is subtracted from the
    position's `reserved_qty` and added back to its `on_hand_qty`, and the
    registration's `reserved_unit_count` becomes 0."
    PRD §3.1: "Hop four, caused by hop three, recomputes `total_items_on_hand` for
    every drive cycle whose position moved."
    PRD §3.9: "The base score is then fifty-five hundredths of the served ratio, plus
    thirty hundredths of the fill quality, plus fifteen hundredths of the equity
    weight."

    Design: Difficulty/transitive_cascade/school_suspension_four_hop_cascade_releases_reserved_units
    """
    program = setup_backpack_program(backpack_on_hand=2, seat_capacity=5, title_i_pct=0.80)
    registration = create_registration(program.event_id, program.school_id, free_lunch_eligible=True)
    verify_registration(registration["id"], program.event_id, program.school_id)
    confirm_registration(registration["id"], program.event_id, program.school_id)

    validate_success(move_school(program.school_id, "SUSPENDED"))

    reread = read_registration(registration["id"])
    assert reread["reserved_unit_count"] == 0

    position = read_position(program.cycle_id, program.backpack_id)
    assert position["on_hand_qty"] == 2, "the reserved backpack must return to the shelf"
    assert position["reserved_qty"] == 0
    assert_unit_conservation(position)

    cycle = validate_success(api.get_drive_cycle(program.cycle_id, PD))
    assert cycle["total_items_on_hand"] == 2

    school = validate_success(api.get_school(program.school_id, PD))
    assert school["students_served_interim_count"] == 0
    assert_pct_equals(school["impact_index_interim"], 12.00, "impact_index_interim")
