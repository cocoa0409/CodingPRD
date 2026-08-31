"""Resource versioning, the two stale-view guards and the logical clock."""
from test_helpers import (
    ApiErrorId,
    create_ra,
    create_room_change_case_payload,
    create_room_inspection_payload,
    create_student,
    open_room_change_case,
    place_student,
    read_building,
    read_room_change_case,
    request_placement,
    room_version,
    setup_hall_with_rooms,
    student_version,
    unique_email,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_scheduling_an_inspection_on_a_stale_room_version_is_rejected(api, director_headers):
    """PRD §2.8: "Scheduling a room inspection requires `expected_room_version` as a
    mandatory field of the request, carrying the client's last observed `version` of the
    target `Room`. If that value does not equal the room's current `version`, the
    request is rejected with `ERR_STALE_ROOM_VERSION` (HTTP 412)."
    PRD §3.6: "Because the supersession makes the room's recent history load-bearing,
    this is one of the two operations guarded by a version expectation, and the act of
    scheduling advances the room's own `version`."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_room_version_on_inspection_create_returns_stale_room_version
    """
    base = setup_hall_with_rooms(room_specs=[{"room_number": "201", "bed_capacity": 2}])
    room = base["rooms"][0]
    stale_version = room["version"]
    staff = create_ra(floor_id=base["floor"]["id"])
    resident = create_student(full_name="Dee Sun", email=unique_email("dee"))
    place_student(resident["id"], room["id"])

    stale = api.create_room_inspection(
        create_room_inspection_payload(
            room["id"],
            stale_version,
            inspection_type="HEALTH_SAFETY",
            scheduled_for="2026-08-10T09:00:00Z",
        ),
        staff["ra_headers"],
    )

    validate_error(stale, ApiErrorId.ERR_STALE_ROOM_VERSION.value, 412)
    _, meta = validate_paginated(
        api.list_room_inspections(director_headers, params={"room_id": room["id"]})
    )
    assert meta["total_count"] == 0, "the rejected create must schedule nothing"

    current_version = room_version(room["id"])
    accepted = validate_success(
        api.create_room_inspection(
            create_room_inspection_payload(
                room["id"],
                current_version,
                inspection_type="HEALTH_SAFETY",
                scheduled_for="2026-08-10T09:00:00Z",
            ),
            staff["ra_headers"],
        ),
        201,
    )
    assert accepted["status"] == "SCHEDULED"
    assert room_version(room["id"]) > current_version, (
        "scheduling advances the room's own version"
    )


def test_opening_a_case_on_a_stale_resident_version_is_rejected(api, director_headers):
    """PRD §2.8: "Opening a room-change case requires `expected_student_version` as a
    mandatory field, carrying the client's last observed `version` of the target
    `Student`. A mismatch with the student's current `version` is rejected with
    `ERR_STALE_STUDENT_VERSION` (HTTP 412)."
    PRD §2.8: "The reasoning is the same: opening a case supersedes and cancels the
    student's prior requested case, and a client working from a stale view of the
    student would cancel a case it never observed."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_student_version_on_case_create_returns_stale_student_version
    """
    base = setup_hall_with_rooms(
        room_specs=[
            {"room_number": "201", "bed_capacity": 2},
            {"room_number": "202", "bed_capacity": 2},
        ]
    )
    room_201, room_202 = base["rooms"]
    resident = create_student(full_name="Dee Sun", email=unique_email("dee"))
    place_student(resident["id"], room_202["id"])
    stale_version = student_version(resident["id"])
    first_case = open_room_change_case(resident["id"], room_202["id"])
    first_case = request_placement(first_case["id"], room_201["id"])

    response = api.create_room_change_case(
        create_room_change_case_payload(resident["id"], room_202["id"], stale_version),
        director_headers,
    )

    validate_error(response, ApiErrorId.ERR_STALE_STUDENT_VERSION.value, 412)
    _, meta = validate_paginated(
        api.list_room_change_cases(director_headers, params={"student_id": resident["id"]})
    )
    assert meta["total_count"] == 1, "the rejected create must open no second case"
    survivor = read_room_change_case(first_case["id"])
    assert survivor["placement_status"] == "REQUESTED", (
        "the refused create superseded nothing"
    )
    assert survivor["to_room_id"] == room_201["id"]


def test_version_advances_by_exactly_one_on_each_mutation_and_not_on_reads(
    api, director_headers
):
    """PRD §2.4: "All fourteen resource types additionally carry `updated_at`, refreshed
    to the current instant on every mutation, and `version`, an integer that begins at 1
    when the resource is created and increases by exactly one on each subsequent
    mutation."

    Design: Corner/cross_cutting_complexity_layers/entity_version_increments_by_one_on_each_mutation
    """
    base = setup_hall_with_rooms(room_specs=[])
    hall = base["building"]
    assert hall["version"] == 1

    read_back = validate_success(api.get_building(hall["id"], director_headers))
    assert read_back["version"] == 1, "a read is not a mutation"

    restricted = validate_success(
        api.set_building_posture(
            hall["id"],
            {"target_posture": "RESTRICTED", "reason": "elevator outage"},
            director_headers,
        )
    )
    assert restricted["version"] == 2

    reopened = validate_success(
        api.set_building_posture(hall["id"], {"target_posture": "OPEN"}, director_headers)
    )
    assert reopened["version"] == 3
    final = read_building(hall["id"])
    assert final["posture"] == "OPEN"
    assert final["closure_reason"] is None


def test_logical_clock_starts_at_the_declared_default_instant(api, director_headers):
    """PRD §2.5: "Before any operator sets it, that clock reads exactly
    `2026-08-01T00:00:00Z`, which is also the term start instant used by the
    backward-looking duty-load figure."
    PRD §2.5: "An administrative capability lets a `ResidenceDirector` move the clock to
    a supplied instant, passed as `to_iso8601`; the response reports the new
    `current_utc` alongside the `previous_utc` it replaced."
    PRD §2.5: "Moving the clock mutates no entity — it changes only what subsequent
    window, deadline and depreciation evaluations see."

    Design: Corner/endpoints/logical_clock_defaults_to_2026_08_01_before_any_set_call
    """
    base = setup_hall_with_rooms(room_specs=[])
    hall = base["building"]

    moved = validate_success(
        api.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"}, director_headers)
    )

    assert moved["previous_utc"].startswith("2026-08-01T00:00:00"), (
        f"the clock must start at the declared default, got {moved['previous_utc']}"
    )
    assert moved["current_utc"].startswith("2026-09-01T00:00:00")
    assert read_building(hall["id"])["version"] == 1, (
        "the clock endpoint mutates no entity"
    )
