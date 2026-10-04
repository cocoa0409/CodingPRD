"""Student focus lists and caseloads: the cyclic assign/unassign machine, the
twelve-student caseload boundary, the placement and service gates, and the
double-assign conflict."""

from test_helpers import (
    ApiErrorId,
    fixtures,
    get_success_data,
    validate_error,
)
from test_helpers.test_users import PROGRAM_MANAGER_HEADERS


def _world_with_student(api, ref="S01"):
    world = fixtures.setup_deployed_world(api)
    student = fixtures.create_student(api, world["school"]["id"], ref)
    return world, student


class TestCaseloadCycle:
    def test_student_caseload_reassign_cycle(self, api):
        """PRD §3.5: "The caseload machine is cyclic: re-assigning a student
        after an unassign is allowed, and the new `assigned_start_date` simply
        begins a fresh interval on top of the closed one."

        Design: Corner/state_machines/student_caseload_reassign_cycle
        """
        fixtures.set_clock(api)
        world, student = _world_with_student(api)
        member_id = world["member"]["id"]

        first = fixtures.assign_caseload(api, student["id"], member_id)
        assert first["caseload_status"] == "ASSIGNED"
        assert first["assigned_start_date"] == "2026-09-01"

        released = fixtures.unassign_caseload(api, student["id"])
        assert released["caseload_status"] == "UNASSIGNED"
        assert released["assigned_end_date"] == "2026-09-01"
        assert released["assigned_member_id"] is None

        reassigned = fixtures.assign_caseload(api, student["id"], member_id)
        assert reassigned["caseload_status"] == "ASSIGNED"
        assert reassigned["assigned_member_id"] == member_id


class TestCaseloadGates:
    def test_caseload_double_assign_conflict(self, api):
        """PRD §3.5: "And the student must not already be `ASSIGNED`, else
        `ERR_STUDENT_CASELOAD_CONFLICT` — note that the capacity check
        precedes the already-assigned check when both would fail."

        Design: Corner/validations/caseload_double_assign_conflict
        """
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        school = fixtures.create_active_school(api, site["id"])
        team = fixtures.create_team(api, school["id"])
        member1 = fixtures.create_active_member(api, site["id"])
        fixtures.assign_member(api, team["id"], member1["id"])
        member2 = fixtures.add_active_member(
            api, site["id"], "app-riley", "Riley Brooks",
            date_of_birth="2004-02-11", education_level="SOME_COLLEGE",
        )
        fixtures.assign_member(api, team["id"], member2["id"])
        fixtures.deploy_team(api, team["id"])
        student = fixtures.create_student(api, school["id"], "S01")
        fixtures.assign_caseload(api, student["id"], member1["id"])

        # Both members are eligible and placed; only the conflict can fire.
        blocked = api.caseload_student(
            student["id"], {"action": "ASSIGN", "corps_member_id": member2["id"]}, PROGRAM_MANAGER_HEADERS
        )
        validate_error(blocked, ApiErrorId.ERR_STUDENT_CASELOAD_CONFLICT.value)

        after = get_success_data(api.list_school_students(school["id"], PROGRAM_MANAGER_HEADERS))
        mine = [s for s in after if s["id"] == student["id"]]
        assert mine and mine[0]["assigned_member_id"] == member1["id"]

    def test_caseload_assign_requires_member_placed_and_active(self, api):
        """PRD §3.5: "The member must be placed at the student's school —
        holding an `ACTIVE` team assignment whose team's school is the
        student's school and whose team is `DEPLOYED` or `UNDERSTAFFED` — else
        `ERR_MEMBER_NOT_PLACED`."

        Design: Difficulty/cross_entity_state_dependency/caseload_assign_requires_member_placed_and_active
        """
        fixtures.set_clock(api)
        world, student = _world_with_student(api)
        placed = world["member"]
        unplaced = fixtures.add_active_member(
            api, world["site"]["id"], "app-riley", "Riley Brooks",
            date_of_birth="2004-02-11", education_level="SOME_COLLEGE",
        )

        # ACTIVE but holds no assignment anywhere: only the placement gate fires.
        blocked = api.caseload_student(
            student["id"], {"action": "ASSIGN", "corps_member_id": unplaced["id"]}, PROGRAM_MANAGER_HEADERS
        )
        validate_error(blocked, ApiErrorId.ERR_MEMBER_NOT_PLACED.value)

        placed_resp = fixtures.assign_caseload(api, student["id"], placed["id"])
        assert placed_resp["caseload_status"] == "ASSIGNED"
        assert placed_resp["assigned_member_id"] == placed["id"]

    def test_caseload_assign_rejects_suspended_member(self, api):
        """PRD §3.5: "The target member must have `service_status` of
        `ACTIVE` (else `ERR_MEMBER_NOT_ACTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/caseload_assign_requires_member_placed_and_active
        """
        fixtures.set_clock(api)
        world, student = _world_with_student(api)
        member = world["member"]

        # Service suspension leaves the assignment in place, so the member is
        # still placed and only the service gate can fire.
        fixtures.suspend_member_service(api, member["id"])
        blocked = api.caseload_student(
            student["id"], {"action": "ASSIGN", "corps_member_id": member["id"]}, PROGRAM_MANAGER_HEADERS
        )
        validate_error(blocked, ApiErrorId.ERR_MEMBER_NOT_ACTIVE.value)


class TestCaseloadBoundary:
    def _fill_to_twelve(self, api, world):
        member_id = world["member"]["id"]
        students = [
            fixtures.create_student(api, world["school"]["id"], f"S{i:02d}") for i in range(1, 14)
        ]
        for student in students[:12]:
            fixtures.assign_caseload(api, student["id"], member_id)
        return students

    def test_caseload_twelfth_succeeds_thirteenth_rejected(self, api):
        """PRD §3.5: "The member's caseload must have room:
        `active_caseload_count` below 12, meaning the twelfth assignment
        succeeds and the thirteenth is rejected with `ERR_CASELOAD_FULL`."

        Design: Difficulty/boundary_precision_check/caseload_twelfth_succeeds_thirteenth_rejected
        """
        fixtures.set_clock(api)
        world = fixtures.setup_deployed_world(api)
        member_id = world["member"]["id"]
        students = self._fill_to_twelve(api, world)

        member = fixtures.get_member(api, member_id)
        assert member["active_caseload_count"] == 12

        blocked = api.caseload_student(
            students[12]["id"], {"action": "ASSIGN", "corps_member_id": member_id}, PROGRAM_MANAGER_HEADERS
        )
        validate_error(blocked, ApiErrorId.ERR_CASELOAD_FULL.value)

        after = fixtures.get_member(api, member_id)
        assert after["active_caseload_count"] == 12

    def test_caseload_capacity_freed_by_unassign(self, api):
        """PRD §3.5: "An `action` of `UNASSIGN` — which takes no member — sets
        `assigned_end_date` to the clock date, clears `assigned_member_id`,
        and decrements the member's `active_caseload_count`."

        Design: Difficulty/boundary_precision_check/caseload_twelfth_succeeds_thirteenth_rejected
        """
        fixtures.set_clock(api)
        world = fixtures.setup_deployed_world(api)
        member_id = world["member"]["id"]
        students = self._fill_to_twelve(api, world)

        released = fixtures.unassign_caseload(api, students[0]["id"])
        assert released["caseload_status"] == "UNASSIGNED"
        assert fixtures.get_member(api, member_id)["active_caseload_count"] == 11

        # With room again, the thirteenth student now assigns cleanly.
        assigned = fixtures.assign_caseload(api, students[12]["id"], member_id)
        assert assigned["caseload_status"] == "ASSIGNED"
        assert fixtures.get_member(api, member_id)["active_caseload_count"] == 12
