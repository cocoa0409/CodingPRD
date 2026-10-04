"""Facility reservation overlap: per-type buffers and half-open interval edges."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    BRANCH_DIRECTOR_HEADERS,
    PROGRAM_COORDINATOR_HEADERS,
    make_member_headers,
)
from test_helpers import fixtures


def _setup_space(api, name="Gym", kind="GYM"):
    world = fixtures.setup_association_and_branch(api)
    space = fixtures.create_space(api, world["branch"]["id"], name=name, kind=kind, capacity=100, dropin_capacity=20)
    world["space"] = space
    return world


def test_buffers_block_adjacent_program_but_touching_maintenance_is_allowed(api):
    """A RENTAL's 30-minute buffer blocks a PROGRAM starting 20 minutes after
    it, while a zero-buffer MAINTENANCE starting exactly at the rental's end
    still conflicts with the buffered end - and one starting exactly at the
    buffered end does not.

    PRD §3.6: "Each type carries a fixed setup-and-teardown `buffer_minutes`
    applied to both ends of the interval: 15 minutes for `PROGRAM`, 30 minutes
    for `RENTAL`, and zero for `MAINTENANCE` and `BLACKOUT`."
    PRD §3.6: "The director's approval moves the reservation `REQUESTED` →
    `APPROVED` only when no already-`APPROVED` reservation on the same space has
    a buffered interval — its `start_at` minus its buffer through its `end_at`
    plus its buffer — that intersects this request's buffered interval; an
    overlap is `ERR_SPACE_CONFLICT`. Buffered intervals that merely touch, one
    ending exactly when the other begins, are allowed."

    Design: Difficulty/resource_temporal_overlap/rental_buffer_blocks_adjacent_program_but_zero_buffer_maintenance_touches
    """
    world = _setup_space(api)
    renter = fixtures.create_member(
        api, world["branch"]["id"], full_name="Renter Ron", email="ron@x.com", birth_date="1980-01-01"
    )

    # APPROVED RENTAL 09:00-10:00 -> buffered window [08:30, 10:30).
    rental = fixtures.create_reservation(
        api, world["space"]["id"], make_member_headers(renter["id"]),
        reservation_type="RENTAL",
        start_at="2026-09-15T09:00:00Z", end_at="2026-09-15T10:00:00Z",
        renter_member_id=renter["id"],
    )
    get_success_data(api.approve_reservation(rental["id"], BRANCH_DIRECTOR_HEADERS))

    # PROGRAM 10:20-11:00 -> buffered [10:05, 11:15) intersects the rental's buffered end.
    program_res = fixtures.create_reservation(
        api, world["space"]["id"], PROGRAM_COORDINATOR_HEADERS,
        reservation_type="PROGRAM",
        start_at="2026-09-15T10:20:00Z", end_at="2026-09-15T11:00:00Z",
    )
    validate_error(api.approve_reservation(program_res["id"], BRANCH_DIRECTOR_HEADERS), "ERR_SPACE_CONFLICT")

    # MAINTENANCE 10:00-10:30 -> zero buffer, still inside the rental's buffered window.
    maint_inside = fixtures.create_reservation(
        api, world["space"]["id"], BRANCH_DIRECTOR_HEADERS,
        reservation_type="MAINTENANCE",
        start_at="2026-09-15T10:00:00Z", end_at="2026-09-15T10:30:00Z",
    )
    validate_error(api.approve_reservation(maint_inside["id"], BRANCH_DIRECTOR_HEADERS), "ERR_SPACE_CONFLICT")

    # MAINTENANCE 10:30-11:00 touches the buffered end exactly: allowed.
    maint_touching = fixtures.create_reservation(
        api, world["space"]["id"], BRANCH_DIRECTOR_HEADERS,
        reservation_type="MAINTENANCE",
        start_at="2026-09-15T10:30:00Z", end_at="2026-09-15T11:00:00Z",
    )
    approved = get_success_data(api.approve_reservation(maint_touching["id"], BRANCH_DIRECTOR_HEADERS))
    assert approved["status"] == "APPROVED"


def test_touching_endpoints_of_equally_buffered_types_are_allowed(api):
    """Two RENTALs whose buffered intervals meet end-to-start do not conflict.

    PRD §3.6: "Buffered intervals that merely touch, one ending exactly when the
    other begins, are allowed."

    Design: Difficulty/resource_temporal_overlap/rental_buffer_blocks_adjacent_program_but_zero_buffer_maintenance_touches
    """
    world = _setup_space(api)
    renter = fixtures.create_member(
        api, world["branch"]["id"], full_name="Renter Ron", email="ron@x.com", birth_date="1980-01-01"
    )
    renter_headers = make_member_headers(renter["id"])

    # First rental 09:00-10:00 -> buffered [08:30, 10:30).
    first = fixtures.create_reservation(
        api, world["space"]["id"], renter_headers,
        reservation_type="RENTAL",
        start_at="2026-09-15T09:00:00Z", end_at="2026-09-15T10:00:00Z",
        renter_member_id=renter["id"],
    )
    get_success_data(api.approve_reservation(first["id"], BRANCH_DIRECTOR_HEADERS))

    # Second rental 11:00-12:00 -> buffered [10:30, 12:30): touches exactly.
    second = fixtures.create_reservation(
        api, world["space"]["id"], renter_headers,
        reservation_type="RENTAL",
        start_at="2026-09-15T11:00:00Z", end_at="2026-09-15T12:00:00Z",
        renter_member_id=renter["id"],
    )
    approved = get_success_data(api.approve_reservation(second["id"], BRANCH_DIRECTOR_HEADERS))
    assert approved["status"] == "APPROVED"


def test_sessions_on_disjoint_weeks_hold_reservations_at_identical_times(api):
    """Reservation conflicts compare concrete datetimes, so two sessions sharing
    a space and a daily time but running on disjoint weeks both approve.

    PRD §3.6: "The director's approval moves the reservation `REQUESTED` →
    `APPROVED` only when no already-`APPROVED` reservation on the same space has
    a buffered interval — its `start_at` minus its buffer through its `end_at`
    plus its buffer — that intersects this request's buffered interval; an
    overlap is `ERR_SPACE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/session_date_intervals_overlap_only_on_shared_days_not_shared_space_names
    """
    world = fixtures.setup_association_and_branch(api)
    space = fixtures.create_space(api, world["branch"]["id"], name="Studio 2", kind="STUDIO", capacity=30, dropin_capacity=5)
    program = fixtures.create_program(
        api, world["branch"]["id"], name="Yoga", kind="SPORTS", base_fee_cents=2_000, member_priority_days=0
    )
    session_a = fixtures.create_session(
        api, program["id"], space["id"], start_on="2026-09-21", end_on="2026-09-25",
        time_start="07:00", time_end="08:00", capacity=12,
    )
    session_b = fixtures.create_session(
        api, program["id"], space["id"], start_on="2026-09-28", end_on="2026-10-02",
        time_start="07:00", time_end="08:00", capacity=12,
    )

    res_a = fixtures.create_reservation(
        api, space["id"], PROGRAM_COORDINATOR_HEADERS,
        reservation_type="PROGRAM",
        start_at="2026-09-21T07:00:00Z", end_at="2026-09-21T08:00:00Z",
        session_id=session_a["id"],
    )
    get_success_data(api.approve_reservation(res_a["id"], BRANCH_DIRECTOR_HEADERS))

    # Identical daily time one week later: concrete datetimes are disjoint.
    res_b = fixtures.create_reservation(
        api, space["id"], PROGRAM_COORDINATOR_HEADERS,
        reservation_type="PROGRAM",
        start_at="2026-09-28T07:00:00Z", end_at="2026-09-28T08:00:00Z",
        session_id=session_b["id"],
    )
    approved = get_success_data(api.approve_reservation(res_b["id"], BRANCH_DIRECTOR_HEADERS))
    assert approved["status"] == "APPROVED"

    assert get_success_data(api.get_reservation(res_a["id"], BRANCH_DIRECTOR_HEADERS))["status"] == "APPROVED"
    assert get_success_data(api.get_reservation(res_b["id"], BRANCH_DIRECTOR_HEADERS))["status"] == "APPROVED"


def test_overlapping_sessions_on_same_space_conflict_on_the_shared_datetime(api):
    """Two reservations on the same space and the SAME concrete datetime do
    conflict, even though each belongs to a different session.

    PRD §3.6: "an overlap is `ERR_SPACE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/session_date_intervals_overlap_only_on_shared_days_not_shared_space_names
    """
    world = fixtures.setup_association_and_branch(api)
    space = fixtures.create_space(api, world["branch"]["id"], name="Studio 2", kind="STUDIO", capacity=30, dropin_capacity=5)
    program = fixtures.create_program(
        api, world["branch"]["id"], name="Yoga", kind="SPORTS", base_fee_cents=2_000, member_priority_days=0
    )
    session_a = fixtures.create_session(
        api, program["id"], space["id"], start_on="2026-09-21", end_on="2026-09-25",
        time_start="07:00", time_end="08:00", capacity=12,
    )
    session_b = fixtures.create_session(
        api, program["id"], space["id"], start_on="2026-09-21", end_on="2026-09-25",
        time_start="07:00", time_end="08:00", capacity=12,
    )

    res_a = fixtures.create_reservation(
        api, space["id"], PROGRAM_COORDINATOR_HEADERS,
        reservation_type="PROGRAM",
        start_at="2026-09-21T07:00:00Z", end_at="2026-09-21T08:00:00Z",
        session_id=session_a["id"],
    )
    get_success_data(api.approve_reservation(res_a["id"], BRANCH_DIRECTOR_HEADERS))

    res_b = fixtures.create_reservation(
        api, space["id"], PROGRAM_COORDINATOR_HEADERS,
        reservation_type="PROGRAM",
        start_at="2026-09-21T07:00:00Z", end_at="2026-09-21T08:00:00Z",
        session_id=session_b["id"],
    )
    validate_error(api.approve_reservation(res_b["id"], BRANCH_DIRECTOR_HEADERS), "ERR_SPACE_CONFLICT")
