"""Volunteers, interpretive programs, and assignments: background clearance
gating, the 365-day expiry boundary, the expiry cascade, capacity and
uniqueness guards, and assignment into completed programs.
"""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error,
    create_unit, create_volunteer, create_cleared_volunteer, clear_volunteer,
    create_program, get_program, create_assignment, get_assignment,
    create_assignment_payload,
    advance_clock,
)

VC = TEST_USERS["volunteer_coordinator_headers"]


def test_volunteer_expiry_releases_assignment_cancels_program(api):
    """PRD §3.6: "That expiry cascades: every assignment of the volunteer
    still `ACTIVE` is released to `RELEASED`, and every program still
    `SCHEDULED` whose remaining count of active assignments drops below its
    `min_volunteers` because of those releases is cancelled to `CANCELLED`,
    releasing its own remaining active assignments in the second hop."
    PRD §3.6: "Clearance lasts 365 days: when the clock date reaches or
    passes the date exactly 365 days after `cleared_on` — the boundary day
    itself expires — the volunteer moves from `CLEARED` to `EXPIRED`."

    Design: Difficulty/transitive_cascade/volunteer_expiry_releases_assignment_cancels_program
    """
    unit = create_unit(name="Visitor Center Unit", habitat_type="MIXED",
                       acreage=500)
    advance_clock("2026-09-10T00:00:00Z")
    v1 = create_cleared_volunteer(full_name="Vol One", email="v1@x.com")
    v2 = create_cleared_volunteer(full_name="Vol Two", email="v2@x.com")
    assert v1["cleared_on"] == "2026-09-10"
    program = create_program(
        unit["id"], title="Marsh Walk", program_date="2027-12-01",
        min_volunteers=2, max_volunteers=5)
    as1 = create_assignment(program["id"], v1["id"])
    as2 = create_assignment(program["id"], v2["id"])

    advance_clock("2027-09-10T00:00:00Z")
    after1 = get_assignment(as1["id"])
    assert after1["status"] == "RELEASED", (
        "the expiring volunteer's ACTIVE assignment must be released "
        "(boundary: cleared_on 2026-09-10 + 365 days = 2027-09-10 expires)")
    program_after = get_program(unit["id"], program["id"])
    assert program_after["status"] == "CANCELLED", (
        "losing an assignment below min_volunteers 2 must cancel the "
        "SCHEDULED program")
    after2 = get_assignment(as2["id"])
    assert after2["status"] == "RELEASED", (
        "the program cancellation must release the other volunteer's "
        "assignment in the second hop")


def test_assignment_gated_by_volunteer_background_state(api):
    """PRD §3.6: "Three business guards then apply in the §2.6 order: the
    referenced volunteer's `background_status` must be `CLEARED`, else
    `ERR_VOLUNTEER_NOT_CLEARED`; the volunteer may hold at most one `ACTIVE`
    assignment on the program, so a second active assignment for the same
    volunteer is rejected with `ERR_DUPLICATE_ASSIGNMENT`; and the program
    must have headroom — creating an assignment when the program already
    carries `max_volunteers` active assignments is rejected with
    `ERR_PROGRAM_CAPACITY_EXCEEDED`."

    Design: Difficulty/cross_entity_state_dependency/assignment_gated_by_volunteer_background_state
    """
    unit = create_unit(name="Visitor Center Unit", habitat_type="MIXED",
                       acreage=500)
    volunteer = create_volunteer(full_name="Vol One", email="v1@x.com")
    assert volunteer["background_status"] == "PENDING"
    program = create_program(
        unit["id"], title="Owl Prowl", program_date="2026-12-01",
        min_volunteers=1, max_volunteers=3)
    blocked = api_client.create_assignment(
        program["id"], create_assignment_payload(volunteer["id"]), VC)
    validate_error(blocked, ApiErrorId.ERR_VOLUNTEER_NOT_CLEARED)
    clear_volunteer(volunteer["id"])
    assignment = create_assignment(program["id"], volunteer["id"])
    assert assignment["status"] == "ACTIVE", (
        "the identical assignment call must succeed once the volunteer is "
        "CLEARED")


def test_assignment_into_completed_program_rejected(api):
    """PRD §3.6: "The program must still be `SCHEDULED` — assigning into a
    cancelled or completed program violates the state machine and is rejected
    with `ERR_INVALID_STATE`."
    PRD §3.6: "And the clock completes it: once the clock date passes
    `program_date`, a still-`SCHEDULED` program moves to `COMPLETED`, and
    every assignment still `ACTIVE` on it completes as well."

    Design: Corner/state_machines/assignment_into_completed_program_rejected
    """
    unit = create_unit(name="Visitor Center Unit", habitat_type="MIXED",
                       acreage=500)
    volunteer = create_cleared_volunteer(full_name="Vol One", email="v1@x.com")
    program = create_program(
        unit["id"], title="Owl Prowl", program_date="2026-10-01",
        min_volunteers=1, max_volunteers=3)
    advance_clock("2026-10-02T00:00:00Z")
    program_after = get_program(unit["id"], program["id"])
    assert program_after["status"] == "COMPLETED", (
        "the clock past program_date must auto-complete the program")
    resp = api_client.create_assignment(
        program["id"], create_assignment_payload(volunteer["id"]), VC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_volunteer_expiry_boundary_day_before_and_day_of(api):
    """PRD §3.6: "Clearance lasts 365 days: when the clock date reaches or
    passes the date exactly 365 days after `cleared_on` — the boundary day
    itself expires — the volunteer moves from `CLEARED` to `EXPIRED`."

    Design: Corner/state_machines/volunteer_expiry_boundary_day_before_and_day_of
    """
    unit = create_unit(name="Visitor Center Unit", habitat_type="MIXED",
                       acreage=500)
    advance_clock("2026-09-10T00:00:00Z")
    volunteer = create_cleared_volunteer(full_name="Vol One", email="v1@x.com")
    assert volunteer["cleared_on"] == "2026-09-10"
    program1 = create_program(
        unit["id"], title="P1", program_date="2027-12-01",
        min_volunteers=1, max_volunteers=3)
    program2 = create_program(
        unit["id"], title="P2", program_date="2027-12-02",
        min_volunteers=1, max_volunteers=3)

    advance_clock("2027-09-09T00:00:00Z")
    assignment = create_assignment(program1["id"], volunteer["id"])
    assert assignment["status"] == "ACTIVE", (
        "on cleared_on + 364 the clearance is still valid")

    advance_clock("2027-09-10T00:00:00Z")
    released = get_assignment(assignment["id"])
    assert released["status"] == "RELEASED", (
        "on cleared_on + 365 the boundary day itself expires the volunteer "
        "and releases the assignment")
    resp = api_client.create_assignment(
        program2["id"], create_assignment_payload(volunteer["id"]), VC)
    validate_error(resp, ApiErrorId.ERR_VOLUNTEER_NOT_CLEARED)


def test_duplicate_assignment_rejected(api):
    """PRD §3.6: "Three business guards then apply in the §2.6 order: the
    referenced volunteer's `background_status` must be `CLEARED`, else
    `ERR_VOLUNTEER_NOT_CLEARED`; the volunteer may hold at most one `ACTIVE`
    assignment on the program, so a second active assignment for the same
    volunteer is rejected with `ERR_DUPLICATE_ASSIGNMENT`; and the program
    must have headroom — creating an assignment when the program already
    carries `max_volunteers` active assignments is rejected with
    `ERR_PROGRAM_CAPACITY_EXCEEDED`."

    Design: Corner/validations/duplicate_assignment_rejected
    """
    unit = create_unit(name="Visitor Center Unit", habitat_type="MIXED",
                       acreage=500)
    volunteer = create_cleared_volunteer(full_name="Vol One", email="v1@x.com")
    program = create_program(
        unit["id"], title="Owl Prowl", program_date="2026-12-01",
        min_volunteers=1, max_volunteers=3)
    create_assignment(program["id"], volunteer["id"])
    resp = api_client.create_assignment(
        program["id"], create_assignment_payload(volunteer["id"]), VC)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ASSIGNMENT)


def test_program_capacity_boundary_rejected(api):
    """PRD §3.6: "and the program must have headroom — creating an assignment
    when the program already carries `max_volunteers` active assignments is
    rejected with `ERR_PROGRAM_CAPACITY_EXCEEDED`."

    Design: Corner/validations/program_capacity_boundary_rejected
    """
    unit = create_unit(name="Visitor Center Unit", habitat_type="MIXED",
                       acreage=500)
    v1 = create_cleared_volunteer(full_name="Vol One", email="v1@x.com")
    v2 = create_cleared_volunteer(full_name="Vol Two", email="v2@x.com")
    program = create_program(
        unit["id"], title="Owl Prowl", program_date="2026-12-01",
        min_volunteers=1, max_volunteers=1)
    first = create_assignment(program["id"], v1["id"])
    assert first["status"] == "ACTIVE", (
        "count 0 < max 1: the first assignment must succeed")
    resp = api_client.create_assignment(
        program["id"], create_assignment_payload(v2["id"]), VC)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_CAPACITY_EXCEEDED)
