"""Retail store donation programs, pickup scheduling windows, and misses."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_pickup,
    assert_store_program,
    certify_member,
    complete_audit,
    create_audit,
    create_certified_member,
    create_member,
    create_store_program,
    make_member_headers,
    miss_pickup,
    schedule_pickup,
    setup_program_with_pickups,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_program_created_pending_blocks_pickup_until_certification(api):
    """PRD §3.9: "a member already `CERTIFIED` gets an `ACTIVE` program
    immediately, while a member in `PENDING_CERTIFICATION` or `PROBATION` gets a
    `PENDING` program that becomes `ACTIVE` later, when the member is certified."
    PRD §2.8: "A member in `PENDING_CERTIFICATION` may not bid and may not schedule
    pickups, and is rejected with `ERR_MEMBER_NOT_CERTIFIED` (HTTP 403)."

    Design: Difficulty/cross_entity_state_dependency/program_activation_gated_by_member_certification
    """
    member = create_member(api)
    audit = create_audit(api, member["id"])
    complete_audit(api, audit["id"])
    assert member["certification_status"] == "PENDING_CERTIFICATION"

    program = create_store_program(api, member, pickup_frequency="WEEKLY")
    assert_store_program(program)
    assert program["program_status"] == "PENDING"

    res = api.schedule_pickup(
        program["id"],
        {"scheduled_date": "2026-09-10T00:00:00Z",
         "window_start": "2026-09-10T08:00:00Z",
         "window_end": "2026-09-10T12:00:00Z"},
        make_member_headers(member["id"]),
    )
    validate_error(res, ApiErrorId.ERR_MEMBER_NOT_CERTIFIED)


def test_certification_activates_pending_program_and_pickup_succeeds(api):
    """PRD §3.1.2: "Certification sets the member to `CERTIFIED`, sets the member's
    `audit_score` to the weighted score of that latest passed comprehensive audit,
    and immediately activates the member's retail store programs: every one of its
    programs sitting in `PENDING` becomes `ACTIVE`, and those programs become
    eligible for new pickups while the pickup windows they already hold are left
    untouched."
    PRD §3.9: "A successful schedule creates the pickup in `SCHEDULED` status with
    `collected_lbs` at zero."

    Design: Difficulty/cross_entity_state_dependency/program_activation_gated_by_member_certification
    """
    member = create_member(api)
    audit = create_audit(api, member["id"])
    complete_audit(api, audit["id"])
    program = create_store_program(api, member, pickup_frequency="WEEKLY")
    assert program["program_status"] == "PENDING"

    certify_member(api, member["id"])
    program_after = validate_success(api.get_store_program(program["id"], ADMIN), 200)
    assert program_after["program_status"] == "ACTIVE"

    pickup = schedule_pickup(
        api, program_after, member,
        "2026-09-10T00:00:00Z", "2026-09-10T08:00:00Z", "2026-09-10T12:00:00Z",
    )
    assert_pickup(pickup)
    assert pickup["pickup_status"] == "SCHEDULED"
    assert pickup["collected_lbs"] == 0


def test_pickup_starting_20_hours_after_previous_rejected(api):
    """PRD §3.9: "The window must not overlap another `SCHEDULED` pickup of the
    same program, and it must also respect the network's route-spacing rule — the
    same program's next pickup may not begin less than 24 hours after this pickup's
    window ends, so a program cannot be scheduled for two back-to-back runs on the
    same day; both collisions are rejected with `ERR_PICKUP_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/pickup_window_24h_buffer_on_program
    """
    member = create_certified_member(api)
    program = create_store_program(api, member, pickup_frequency="DAILY")
    schedule_pickup(api, program, member,
                    "2026-09-10T00:00:00Z", "2026-09-10T08:00:00Z",
                    "2026-09-10T12:00:00Z")

    res = api.schedule_pickup(
        program["id"],
        {"scheduled_date": "2026-09-11T00:00:00Z",
         "window_start": "2026-09-11T08:00:00Z",
         "window_end": "2026-09-11T12:00:00Z"},
        make_member_headers(member["id"]),
    )
    validate_error(res, ApiErrorId.ERR_PICKUP_WINDOW_OVERLAP)


def test_pickup_exactly_24_hours_after_previous_accepted(api):
    """PRD §3.9: "The window must not overlap another `SCHEDULED` pickup of the
    same program, and it must also respect the network's route-spacing rule — the
    same program's next pickup may not begin less than 24 hours after this pickup's
    window ends, so a program cannot be scheduled for two back-to-back runs on the
    same day; both collisions are rejected with `ERR_PICKUP_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/pickup_window_24h_buffer_on_program
    """
    member = create_certified_member(api)
    program = create_store_program(api, member, pickup_frequency="DAILY")
    first = schedule_pickup(api, program, member,
                            "2026-09-10T00:00:00Z", "2026-09-10T08:00:00Z",
                            "2026-09-10T12:00:00Z")

    second = schedule_pickup(api, program, member,
                             "2026-09-11T00:00:00Z", "2026-09-11T12:00:00Z",
                             "2026-09-11T16:00:00Z")
    assert second["pickup_status"] == "SCHEDULED"

    first_after = validate_success(api.list_program_pickups(program["id"], ADMIN), 200)
    assert len(first_after) == 2
    assert [p["id"] for p in first_after if p["id"] == first["id"]][0]
    assert first_after[0]["pickup_status"] == "SCHEDULED"


def test_two_misses_leave_program_active(api):
    """PRD §3.9: "Marking a `SCHEDULED` pickup missed sets it to `MISSED` and then
    re-evaluates the program's reliability: the program's consecutive-missed count
    is recomputed over its pickups taken in `scheduled_date` ascending order, with
    `created_at` ascending breaking ties between pickups scheduled for the same
    date, counting the run of `MISSED` pickups that ends at the most recent one."

    Design: Corner/cross_cutting_complexity_layers/third_consecutive_missed_pickup_suspends_program
    """
    member = create_certified_member(api)
    program, pickups = setup_program_with_pickups(api, member, [
        ("2026-09-10T00:00:00Z", "2026-09-10T06:00:00Z", "2026-09-10T08:00:00Z"),
        ("2026-09-11T00:00:00Z", "2026-09-11T08:00:00Z", "2026-09-11T10:00:00Z"),
        ("2026-09-12T00:00:00Z", "2026-09-12T10:00:00Z", "2026-09-12T12:00:00Z"),
    ])
    assert program["program_status"] == "ACTIVE"

    first = miss_pickup(api, pickups[0]["id"], member)
    second = miss_pickup(api, pickups[1]["id"], member)
    assert first["pickup_status"] == "MISSED"
    assert second["pickup_status"] == "MISSED"

    program_after = validate_success(api.get_store_program(program["id"], ADMIN), 200)
    assert program_after["program_status"] == "ACTIVE"


def test_third_consecutive_miss_suspends_program(api):
    """PRD §3.9: "If that run reaches three, the program's `program_status` becomes
    `SUSPENDED` and every one of the program's remaining `SCHEDULED` pickups is
    marked `MISSED` as well."

    Design: Corner/cross_cutting_complexity_layers/third_consecutive_missed_pickup_suspends_program
    """
    member = create_certified_member(api)
    program, pickups = setup_program_with_pickups(api, member, [
        ("2026-09-10T00:00:00Z", "2026-09-10T06:00:00Z", "2026-09-10T08:00:00Z"),
        ("2026-09-11T00:00:00Z", "2026-09-11T08:00:00Z", "2026-09-11T10:00:00Z"),
        ("2026-09-12T00:00:00Z", "2026-09-12T10:00:00Z", "2026-09-12T12:00:00Z"),
        ("2026-09-13T00:00:00Z", "2026-09-13T12:00:00Z", "2026-09-13T14:00:00Z"),
    ])

    miss_pickup(api, pickups[0]["id"], member)
    miss_pickup(api, pickups[1]["id"], member)
    third = miss_pickup(api, pickups[2]["id"], member)
    assert third["pickup_status"] == "MISSED"

    program_after = validate_success(api.get_store_program(program["id"], ADMIN), 200)
    assert program_after["program_status"] == "SUSPENDED"

    remaining = validate_success(api.list_program_pickups(program["id"], ADMIN), 200)
    assert len(remaining) == 4
    assert {p["pickup_status"] for p in remaining} == {"MISSED"}
