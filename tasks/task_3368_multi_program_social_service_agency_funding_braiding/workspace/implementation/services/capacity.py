"""program_capacity_consumption.

enrolled_slots counts PENDING, ACTIVE and SUSPENDED rows; available_slots is
capacity_slots minus enrolled_slots, and a program is exhausted when that
value is at or below zero. active_slots is the reporting-only active_only_count
projection surfaced on program listings.
"""

import db

COUNTING_STATUSES = ("PENDING", "ACTIVE", "SUSPENDED")


def enrollments_for_program(program_id, statuses=COUNTING_STATUSES):
    return [
        row for row in db.rows("enrollments")
        if row.get("program_id") == program_id and row.get("status") in statuses
    ]


def enrolled_slots(program):
    return len(enrollments_for_program(program["id"]))


def active_slots(program):
    return len(enrollments_for_program(program["id"], ("ACTIVE",)))


def available_slots(program):
    return program.get("capacity_slots", 0) - enrolled_slots(program)


def capacity_exhausted(program):
    return available_slots(program) <= 0


def recompute_program(program):
    """Recomputed properties are mutations: they refresh updated_at and bump
    version, but only when the recomputation actually changes the value."""
    new_enrolled = enrolled_slots(program)
    new_active = active_slots(program)
    changed = (
        program.get("enrolled_slots") != new_enrolled
        or program.get("active_slots") != new_active
    )
    program["enrolled_slots"] = new_enrolled
    program["active_slots"] = new_active
    if changed:
        db.touch(program)
    return program


def open_enrollment_count(client):
    return len([
        row for row in db.rows("enrollments")
        if row.get("client_id") == client["id"] and row.get("status") in COUNTING_STATUSES
    ])


def recompute_client(client):
    new_count = open_enrollment_count(client)
    if client.get("open_enrollment_count") != new_count:
        client["open_enrollment_count"] = new_count
        db.touch(client)
    return client


def assert_slot_available(program):
    from errors import ApiError
    if capacity_exhausted(program):
        raise ApiError(
            "ERR_PROGRAM_CAPACITY_EXCEEDED",
            "Program %s has no available capacity slot." % program.get("name"),
        )
