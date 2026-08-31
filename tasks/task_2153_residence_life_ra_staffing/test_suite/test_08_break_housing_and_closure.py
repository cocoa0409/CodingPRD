"""Break stays, hall posture and the emergency-closure cascade."""
from test_helpers import (
    ApiErrorId,
    approve_break_housing,
    assert_break_housing_request,
    create_student,
    place_student,
    read_break_housing_request,
    read_building,
    read_floor,
    read_room,
    read_room_change_case,
    read_student,
    request_break_housing,
    setup_approved_break_stay,
    setup_hall_with_rooms,
    unique_email,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestEmergencyClosureCascade:
    def test_closure_takes_the_room_offline_and_revokes_the_break_stay(
        self, api, director_headers
    ):
        """PRD §3.9: "**Link one:** every room in the hall whose status is `AVAILABLE`
        or `OCCUPIED` records its current status into `pre_closure_status` and moves to
        `OFFLINE`."
        PRD §3.9: "**Link two:** each room that just went offline revokes every
        break-housing stay against it whose status is `APPROVED` or `CHECKED_IN`,
        moving those stays to `REVOKED` with `revocation_cause` set to
        `EMERGENCY_CLOSURE`."

        Design: Difficulty/transitive_cascade/emergency_closure_room_offline_then_break_revoked_then_relocation_case_then_student_pending
        """
        base = setup_approved_break_stay()

        closed = validate_success(
            api.set_building_posture(
                base["building"]["id"],
                {"target_posture": "EMERGENCY_CLOSED", "reason": "burst riser on floor 2"},
                director_headers,
            )
        )

        assert closed["posture"] == "EMERGENCY_CLOSED"
        room = read_room(base["room"]["id"])
        assert room["status"] == "OFFLINE"
        assert room["pre_closure_status"] == "OCCUPIED"
        stay = read_break_housing_request(base["stay"]["id"])
        assert_break_housing_request(stay)
        assert stay["status"] == "REVOKED"
        assert stay["revocation_cause"] == "EMERGENCY_CLOSURE"

    def test_closure_opens_a_system_relocation_case_and_flags_the_resident(
        self, api, director_headers
    ):
        """PRD §3.9: "**Link three:** each stay that just entered `REVOKED` opens a new
        room-change case for its resident, with `origin` `EMERGENCY_RELOCATION`,
        `from_room_id` set to the resident's `current_room_id`, `mediation_status`
        `NOT_REQUIRED`, `placement_status` already at `REQUESTED`, and
        `opened_by_user_id` recorded as the literal string `system`."
        PRD §3.9: "**Link four:** each resident with a case opened by link three has
        their `housing_status` set to `RELOCATION_PENDING`."
        PRD §3.9: "The **fan-out** runs alongside: every floor in the hall sets
        `programming_frozen` to true and re-derives its `programming_compliance_status`,
        and every inspection still `SCHEDULED` on a room that just went offline is moved
        to `CANCELLED`."

        Design: Difficulty/transitive_cascade/emergency_closure_room_offline_then_break_revoked_then_relocation_case_then_student_pending
        """
        base = setup_approved_break_stay()

        validate_success(
            api.set_building_posture(
                base["building"]["id"],
                {"target_posture": "EMERGENCY_CLOSED", "reason": "burst riser on floor 2"},
                director_headers,
            )
        )

        cases, meta = validate_paginated(
            api.list_room_change_cases(
                director_headers, params={"student_id": base["resident"]["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            f"the revoked stay must open exactly one relocation case, got "
            f"{meta['total_count']}"
        )
        case = read_room_change_case(cases[0]["id"])
        assert case["origin"] == "EMERGENCY_RELOCATION"
        assert case["placement_status"] == "REQUESTED"
        assert case["mediation_status"] == "NOT_REQUIRED"
        assert case["from_room_id"] == base["room"]["id"]
        assert case["opened_by_user_id"] == "system"
        assert read_student(base["resident"]["id"])["housing_status"] == "RELOCATION_PENDING"
        assert read_floor(base["floor"]["id"])["programming_frozen"] is True


class TestBreakHousingCapacityProjection:
    def test_sharing_only_a_boundary_date_still_fits_the_room_beds(
        self, api, director_headers
    ):
        """PRD §3.9: "Two stays on the same room collide when the first starts on or
        before the second ends and the second starts on or before the first ends, which
        means a stay ending on 2026-12-24 and a stay starting on 2026-12-24 *do*
        collide, because they share that date."
        PRD §3.9: "The server counts the room's other stays whose status is `APPROVED`
        or `CHECKED_IN` and which collide with the candidate's dates, adds one for the
        candidate itself, and approves while that projected total is at most the room's
        `bed_capacity`."

        Design: Difficulty/resource_temporal_overlap/break_housing_closed_interval_aggregate_bed_capacity
        """
        base = setup_hall_with_rooms(
            room_specs=[{"room_number": "201", "bed_capacity": 2}],
            break_housing_enabled=True,
        )
        room = base["rooms"][0]
        first_resident = create_student(full_name="Ada Kim", email=unique_email("adak"))
        second_resident = create_student(
            full_name="Bo Lin", email=unique_email("bo"), class_year="SOPHOMORE"
        )
        first = request_break_housing(
            first_resident["id"], room["id"],
            start_date="2026-12-18", end_date="2026-12-24", reason="thesis lab",
        )
        approve_break_housing(first["id"])
        second = request_break_housing(
            second_resident["id"], room["id"],
            start_date="2026-12-24", end_date="2026-12-30", reason="travel gap",
        )

        approved = validate_success(
            api.decide_break_housing_request(
                second["id"], {"decision": "APPROVE"}, director_headers
            )
        )

        assert approved["status"] == "APPROVED", (
            "a boundary-date collision alone does not block approval while beds remain"
        )
        assert read_room(room["id"])["break_hold_count"] == 2

    def test_a_third_colliding_stay_exceeds_the_projected_bed_count(
        self, api, director_headers
    ):
        """PRD §3.9: "A projection exceeding the room's beds is refused with
        `ERR_BREAK_HOUSING_CAPACITY`."
        PRD §3.9: "Stays that are `REQUESTED`, `DENIED`, `REVOKED` or `CLOSED` never
        occupy a bed and never enter the count."

        Design: Difficulty/resource_temporal_overlap/break_housing_closed_interval_aggregate_bed_capacity
        """
        base = setup_hall_with_rooms(
            room_specs=[{"room_number": "201", "bed_capacity": 2}],
            break_housing_enabled=True,
        )
        room = base["rooms"][0]
        ada = create_student(full_name="Ada Kim", email=unique_email("adak"))
        bo = create_student(
            full_name="Bo Lin", email=unique_email("bo"), class_year="SOPHOMORE"
        )
        cy = create_student(
            full_name="Cy Park", email=unique_email("cy"), class_year="SENIOR"
        )
        first = request_break_housing(
            ada["id"], room["id"],
            start_date="2026-12-18", end_date="2026-12-24", reason="thesis lab",
        )
        second = request_break_housing(
            bo["id"], room["id"],
            start_date="2026-12-24", end_date="2026-12-30", reason="travel gap",
        )
        third = request_break_housing(
            cy["id"], room["id"],
            start_date="2026-12-24", end_date="2026-12-26", reason="family",
        )
        fourth = request_break_housing(
            cy["id"], room["id"],
            start_date="2026-12-30", end_date="2027-01-02", reason="new year shift",
        )
        approve_break_housing(first["id"])
        approve_break_housing(second["id"])

        over_capacity = api.decide_break_housing_request(
            third["id"], {"decision": "APPROVE"}, director_headers
        )

        validate_error(over_capacity, ApiErrorId.ERR_BREAK_HOUSING_CAPACITY.value, 409)
        assert read_break_housing_request(third["id"])["status"] == "REQUESTED"

        non_colliding = validate_success(
            api.decide_break_housing_request(
                fourth["id"], {"decision": "APPROVE"}, director_headers
            )
        )
        assert non_colliding["status"] == "APPROVED"
        occupied_room = read_room(room["id"])
        assert occupied_room["break_hold_count"] == 3
        assert occupied_room["occupied_beds"] == 0, (
            "break holds never change term occupancy"
        )


def test_reopening_a_hall_replays_each_room_pre_closure_status(api, director_headers):
    """PRD §3.9: "Every room in the hall that is `OFFLINE` with a non-null
    `pre_closure_status` returns to exactly that stored status — a room that was
    `AVAILABLE` before the closure becomes `AVAILABLE` again and a room that was
    `OCCUPIED` becomes `OCCUPIED` again — and `pre_closure_status` is then cleared back
    to null."
    PRD §3.9: "Every floor sets `programming_frozen` back to false and re-derives its
    compliance status."
    PRD §3.9: "The hall clears `closure_reason` back to null."

    Design: Corner/state_machines/hall_reopen_replays_each_room_pre_closure_status
    """
    base = setup_hall_with_rooms(
        room_specs=[
            {"room_number": "201", "bed_capacity": 2},
            {"room_number": "202", "bed_capacity": 2},
        ]
    )
    occupied_room, empty_room = base["rooms"]
    resident = create_student(
        full_name="Bo Lin", email=unique_email("bo"), class_year="SOPHOMORE"
    )
    place_student(resident["id"], occupied_room["id"])
    validate_success(
        api.set_building_posture(
            base["building"]["id"],
            {"target_posture": "EMERGENCY_CLOSED", "reason": "roof failure"},
            director_headers,
        )
    )
    closed_occupied = read_room(occupied_room["id"])
    closed_empty = read_room(empty_room["id"])
    assert closed_occupied["status"] == "OFFLINE"
    assert closed_occupied["pre_closure_status"] == "OCCUPIED"
    assert closed_empty["status"] == "OFFLINE"
    assert closed_empty["pre_closure_status"] == "AVAILABLE"

    reopened = validate_success(
        api.set_building_posture(
            base["building"]["id"], {"target_posture": "OPEN"}, director_headers
        )
    )

    assert reopened["posture"] == "OPEN"
    assert reopened["closure_reason"] is None
    restored_occupied = read_room(occupied_room["id"])
    assert restored_occupied["status"] == "OCCUPIED"
    assert restored_occupied["pre_closure_status"] is None
    assert restored_occupied["occupied_beds"] == 1
    restored_empty = read_room(empty_room["id"])
    assert restored_empty["status"] == "AVAILABLE"
    assert restored_empty["pre_closure_status"] is None
    assert read_building(base["building"]["id"])["assigned_bed_count"] == 1
    assert read_floor(base["floor"]["id"])["programming_frozen"] is False


def test_moving_from_emergency_closed_to_restricted_is_not_a_declared_move(
    api, director_headers
):
    """PRD §3.9: "**`EMERGENCY_CLOSED → RESTRICTED` is not a declared move** and is
    refused with `ERR_INVALID_POSTURE_TRANSITION`, as is any other undeclared pairing."
    PRD §3.9: "Finally the hall stores the supplied `reason` as `closure_reason` and
    stamps `last_posture_change_at`."

    Design: Corner/state_machines/posture_from_emergency_closed_to_restricted_returns_invalid_posture_transition
    """
    base = setup_hall_with_rooms(room_specs=[])
    building_id = base["building"]["id"]
    validate_success(
        api.set_building_posture(
            building_id,
            {"target_posture": "EMERGENCY_CLOSED", "reason": "gas leak"},
            director_headers,
        )
    )

    response = api.set_building_posture(
        building_id,
        {"target_posture": "RESTRICTED", "reason": "partial reopening"},
        director_headers,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_POSTURE_TRANSITION.value, 409)
    hall = read_building(building_id)
    assert hall["posture"] == "EMERGENCY_CLOSED"
    assert hall["closure_reason"] == "gas leak"


def test_break_stay_approval_in_a_hall_without_break_housing_is_refused(
    api, director_headers
):
    """PRD §3.9: "`APPROVE` moves it to `APPROVED` and passes four gates: the hall
    owning the room must have `break_housing_enabled` true, and a hall that does not
    accept break stays refuses with `ERR_BREAK_HOUSING_DISABLED`; the hall's `posture`
    must be `OPEN`; the resident's `break_housing_eligible` must be true, and a resident
    who lost it to a conduct sanction is refused with `ERR_STUDENT_ON_PROBATION`; and
    the stay must fit the room's beds under the capacity projection below."
    PRD §3.9: "Approval refreshes the room's `break_hold_count`."

    Design: Corner/errors/break_housing_approval_in_a_hall_without_break_housing_returns_disabled
    """
    base = setup_hall_with_rooms(room_specs=[{"room_number": "201", "bed_capacity": 2}])
    room = base["rooms"][0]
    resident = create_student(full_name="Dee Sun", email=unique_email("dee"))
    stay = request_break_housing(
        resident["id"], room["id"],
        start_date="2026-12-18", end_date="2026-12-24", reason="no flights home",
    )

    response = api.decide_break_housing_request(
        stay["id"], {"decision": "APPROVE"}, director_headers
    )

    validate_error(response, ApiErrorId.ERR_BREAK_HOUSING_DISABLED.value, 409)
    refused = read_break_housing_request(stay["id"])
    assert refused["status"] == "REQUESTED"
    assert refused["decided_by_user_id"] is None
    assert read_room(room["id"])["break_hold_count"] == 0


def test_closure_cascade_is_visible_to_the_very_next_read(api, director_headers):
    """PRD §2.10: "Cascades are executed to completion within the request that triggers
    them, and every resource they touch is visible in its post-cascade state to the very
    next read."
    PRD §2.10: "There is no deferred or eventually-consistent settlement anywhere in
    this API."

    Design: Corner/consistency_model/closure_cascade_is_visible_without_any_re_read_delay
    """
    base = setup_hall_with_rooms(room_specs=[{"room_number": "201", "bed_capacity": 2}])
    room = base["rooms"][0]
    resident = create_student(full_name="Dee Sun", email=unique_email("dee"))
    place_student(resident["id"], room["id"])

    closed = validate_success(
        api.set_building_posture(
            base["building"]["id"],
            {"target_posture": "EMERGENCY_CLOSED", "reason": "structural inspection"},
            director_headers,
        )
    )

    assert closed["posture"] == "EMERGENCY_CLOSED"
    immediate_room = validate_success(api.get_room(room["id"], director_headers))
    assert immediate_room["status"] == "OFFLINE"
    assert immediate_room["pre_closure_status"] == "OCCUPIED"
    immediate_floor = validate_success(api.get_floor(base["floor"]["id"], director_headers))
    assert immediate_floor["programming_frozen"] is True
    assert read_student(resident["id"])["current_room_id"] == room["id"], (
        "closure does not evict residents"
    )
    assert read_building(base["building"]["id"])["assigned_bed_count"] == 1
