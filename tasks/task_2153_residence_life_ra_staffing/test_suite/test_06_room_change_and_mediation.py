"""Roommate mediation, the placement track and moving a resident."""
from test_helpers import (
    ApiErrorId,
    assert_room_change_case,
    create_room_change_case_payload,
    create_student,
    open_room_change_case,
    place_student,
    read_building,
    read_room,
    read_room_change_case,
    read_student,
    request_placement,
    setup_completed_move,
    setup_conflict_case_at_mediation_cap,
    setup_hall_with_rooms,
    setup_requested_placement,
    student_version,
    unique_email,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPlacementApprovalPostureGate:
    def test_placement_approval_is_refused_while_the_hall_is_restricted(
        self, api, director_headers
    ):
        """PRD §2.11: "Six families of operation require the owning hall to be `OPEN`:
        placing a resident into a room, deciding a room-change placement, completing a
        room-change placement, deciding a break-housing request, driving break-housing
        occupancy, and running a consolidation."
        PRD §2.11: "Attempting any of these while the hall is `RESTRICTED` or
        `EMERGENCY_CLOSED` is refused with `ERR_BUILDING_NOT_OPEN` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/placement_approval_gated_by_target_building_posture
        """
        base = setup_requested_placement()
        validate_success(
            api.set_building_posture(
                base["building"]["id"],
                {"target_posture": "RESTRICTED", "reason": "elevator outage"},
                director_headers,
            )
        )

        response = api.placement_decision(
            base["case"]["id"], {"decision": "APPROVE"}, director_headers
        )

        validate_error(response, ApiErrorId.ERR_BUILDING_NOT_OPEN.value, 409)
        refused = read_room_change_case(base["case"]["id"])
        assert refused["placement_status"] == "REQUESTED"
        assert refused["mediation_status"] == "NOT_REQUIRED"

    def test_reopening_the_hall_lets_the_identical_approval_succeed(
        self, api, director_headers
    ):
        """PRD §3.9: "`OPEN → RESTRICTED` and `RESTRICTED → OPEN` are the mild pair:
        the first stores the supplied `reason` as `closure_reason` and stamps
        `last_posture_change_at` with the logical clock, and thereafter new placements
        into the hall's rooms are refused with `ERR_BUILDING_NOT_OPEN`; the second
        clears `closure_reason` back to null and re-stamps `last_posture_change_at`."
        PRD §3.7: "A director then approves or denies a `REQUESTED` placement with a
        `decision` and an optional `reason`."

        Design: Difficulty/cross_entity_state_dependency/placement_approval_gated_by_target_building_posture
        """
        base = setup_requested_placement()
        building_id = base["building"]["id"]
        validate_success(
            api.set_building_posture(
                building_id,
                {"target_posture": "RESTRICTED", "reason": "elevator outage"},
                director_headers,
            )
        )
        validate_error(
            api.placement_decision(
                base["case"]["id"], {"decision": "APPROVE"}, director_headers
            ),
            ApiErrorId.ERR_BUILDING_NOT_OPEN.value,
            409,
        )

        reopened = validate_success(
            api.set_building_posture(
                building_id, {"target_posture": "OPEN"}, director_headers
            )
        )
        approved = validate_success(
            api.placement_decision(
                base["case"]["id"], {"decision": "APPROVE"}, director_headers
            )
        )

        assert_room_change_case(approved)
        assert approved["placement_status"] == "APPROVED"
        assert approved["mediation_status"] == "NOT_REQUIRED", (
            "a placement action never writes the mediation dimension"
        )
        assert read_room(base["target_room"]["id"])["occupied_beds"] == 0, (
            "approval alone moves no bed"
        )
        assert reopened["posture"] == "OPEN"
        assert read_building(building_id)["posture"] == "OPEN"


class TestPlacementRevertConservesBeds:
    def test_revert_restores_each_room_to_its_pre_move_occupancy(self, api, director_headers):
        """PRD §3.7: "It sets the resident's `current_room_id` back to
        `reverted_from_room_id`, decrements the target room's `occupied_beds` and
        increments the origin room's, and moves the case to `REVERTED`."
        PRD §3.7: "Every room touched by the forward move returns to the exact
        `occupied_beds` figure it held before completion, and the hall's
        `assigned_bed_count` is identical end to end."

        Design: Difficulty/compensating_invariant/building_assigned_bed_count_conserved_across_move_and_revert
        """
        base = setup_completed_move()
        room_201, room_202 = base["room_201"], base["room_202"]
        assert read_room(room_201["id"])["occupied_beds"] == 1
        assert read_room(room_202["id"])["occupied_beds"] == 2
        assert read_student(base["mover"]["id"])["current_room_id"] == room_202["id"]

        reverted = validate_success(
            api.placement_revert(
                base["case"]["id"],
                {"reason": "target room flooded overnight"},
                director_headers,
            )
        )

        assert reverted["placement_status"] == "REVERTED"
        assert read_room(room_201["id"])["occupied_beds"] == 2
        assert read_room(room_202["id"])["occupied_beds"] == 1
        mover = read_student(base["mover"]["id"])
        assert mover["current_room_id"] == room_201["id"]
        assert mover["housing_status"] == "ASSIGNED"

    def test_assigned_bed_count_is_identical_before_and_after_the_revert(
        self, api, director_headers
    ):
        """PRD §3.7: "**The hall's `assigned_bed_count` is unchanged by the move**,
        because a transfer neither creates nor destroys an occupied bed; only
        floor-level `occupied_beds` figures shift when the two rooms sit on different
        floors."
        PRD §3.7: "The case first records `reverted_from_room_id` as the current
        `from_room_id`, preserving the exact origin so a reversal can restore it."

        Design: Difficulty/compensating_invariant/building_assigned_bed_count_conserved_across_move_and_revert
        """
        base = setup_completed_move()
        building_id = base["building"]["id"]
        before = read_building(building_id)
        assert before["assigned_bed_count"] == 3
        assert before["bed_capacity"] == 4

        reverted = validate_success(
            api.placement_revert(
                base["case"]["id"],
                {"reason": "target room flooded overnight"},
                director_headers,
            )
        )

        after = read_building(building_id)
        assert after["assigned_bed_count"] == 3, (
            f"the headcount must be conserved end to end, got {after['assigned_bed_count']}"
        )
        assert after["bed_capacity"] == 4
        assert reverted["reverted_from_room_id"] == base["room_201"]["id"]
        assert read_room(base["room_201"]["id"])["status"] == "OCCUPIED"
        assert read_room(base["room_202"]["id"])["status"] == "OCCUPIED"


def test_fourth_mediation_session_is_refused_at_the_three_round_cap(api, director_headers):
    """PRD §3.7: "It is permitted only while `mediation_round` is strictly below the
    three-round cap; a fourth session draws `ERR_MEDIATION_ROUND_LIMIT`."
    PRD §3.7: "`RECORD_SESSION` carries an `outcome` of `AGREEMENT` or `IMPASSE`; both
    increment `mediation_round` by one, and they move the case from `SESSION_SCHEDULED`
    to `AGREEMENT_REACHED` and `IMPASSE` respectively."

    Design: Corner/state_machines/mediation_session_scheduling_capped_at_three_rounds
    """
    base = setup_conflict_case_at_mediation_cap()
    case = base["case"]
    assert case["mediation_round"] == 3

    response = api.mediation_action(
        case["id"],
        {"action": "SCHEDULE_SESSION", "session_at": "2026-08-10T15:00:00Z"},
        director_headers,
    )

    validate_error(response, ApiErrorId.ERR_MEDIATION_ROUND_LIMIT.value, 409)
    after = read_room_change_case(case["id"])
    assert after["mediation_round"] == 3
    assert after["mediation_status"] == "IMPASSE"
    assert after["placement_status"] == "NONE", (
        "a mediation action never writes the placement dimension"
    )


def test_opening_a_new_case_supersedes_the_prior_requested_one(api, director_headers):
    """PRD §3.7: "Opening a case also supersedes the resident's own history: any
    earlier room-change case for the same resident still sitting at `placement_status`
    `REQUESTED` is moved to `CANCELLED`, and the new case records that cancelled case's
    identifier as `superseded_case_id`."
    PRD §3.7: "the case begins with `placement_status` at `NONE`, `to_room_id` and
    `reverted_from_room_id` null, `mediation_round` at zero and `session_at` null."

    Design: Corner/state_machines/new_room_change_case_supersedes_the_prior_requested_case
    """
    base = setup_hall_with_rooms(
        room_specs=[
            {"room_number": "201", "bed_capacity": 2},
            {"room_number": "202", "bed_capacity": 2},
            {"room_number": "203", "bed_capacity": 2},
        ]
    )
    room_201, room_202, _ = base["rooms"]
    resident = create_student(full_name="Dee Sun", email=unique_email("dee"))
    place_student(resident["id"], room_202["id"])
    first_case = open_room_change_case(resident["id"], room_202["id"])
    first_case = request_placement(first_case["id"], room_201["id"])

    response = api.create_room_change_case(
        create_room_change_case_payload(
            resident["id"], room_202["id"], student_version(resident["id"])
        ),
        director_headers,
    )
    second_case = validate_success(response, 201)

    superseded = read_room_change_case(first_case["id"])
    assert superseded["placement_status"] == "CANCELLED"
    assert superseded["to_room_id"] == room_201["id"], (
        "the cancelled case keeps its target for audit"
    )
    assert second_case["superseded_case_id"] == first_case["id"]
    assert second_case["placement_status"] == "NONE"
    assert second_case["mediation_status"] == "NOT_REQUIRED"
    _, meta = validate_paginated(
        api.list_room_change_cases(director_headers, params={"student_id": resident["id"]})
    )
    assert meta["total_count"] == 2
    assert read_room(room_201["id"])["occupied_beds"] == 0
    assert read_room(room_202["id"])["occupied_beds"] == 1


def test_case_opened_from_a_room_the_resident_does_not_occupy_is_refused(
    api, director_headers
):
    """PRD §3.7: "The declared `from_room_id` must equal the resident's actual
    `current_room_id`, and the eventual target must not be the room they already
    occupy; either breach is `ERR_STUDENT_NOT_IN_ROOM` (HTTP 422)."

    Design: Corner/validations/room_change_case_from_a_room_the_student_does_not_occupy_returns_student_not_in_room
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

    response = api.create_room_change_case(
        create_room_change_case_payload(
            resident["id"], room_201["id"], student_version(resident["id"])
        ),
        director_headers,
    )

    validate_error(response, ApiErrorId.ERR_STUDENT_NOT_IN_ROOM.value, 422)
    _, meta = validate_paginated(
        api.list_room_change_cases(director_headers, params={"student_id": resident["id"]})
    )
    assert meta["total_count"] == 0, "the refused create must leave no case behind"
    assert read_student(resident["id"])["current_room_id"] == room_202["id"]
