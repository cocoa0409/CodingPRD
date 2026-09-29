"""Gates that read another entity's state: room renovation status, faculty status."""

from test_helpers import api_client, fixtures, validate_error
from test_helpers.assertions import (
    assert_instant_equals,
    assert_power_kw,
    assert_tranche_balances,
    assert_unit_balances,
    rows_for_source,
    rows_of_kind,
)

CASEWORK_PHASE = [
    {
        "sequence_no": 1,
        "name": "Casework",
        "planned_start": "2026-08-10T00:00:00Z",
        "planned_end": "2026-10-30T00:00:00Z",
        "budget_cents": 12_000_000,
    },
]


def _delivered_order_in_an_assigned_room_being_renovated():
    """The room is properly assigned to the faculty member but is under renovation."""
    scenario = fixtures.setup_base_package()
    space, assignment = fixtures.setup_assigned_space(
        scenario, space_overrides={"building_code": "CHEM", "room_number": "601",
                                   "space_class": "WET"},
    )
    order = fixtures.setup_received_order(scenario["package_id"], space["id"],
                                          quoted_cents=5_000_000, required_power_kw=20.0,
                                          required_fume_hoods=1)
    project, phases = fixtures.setup_awarded_project(
        scenario["package_id"], space["id"], 12_000_000, scenario["headers"]["dean"],
        phase_specs=CASEWORK_PHASE,
        project_overrides={"scope_tier": "MODERATE", "estimate_cents": 12_000_000},
    )
    assert assignment["status"] == "ACTIVE"
    assert order["status"] == "DELIVERED"
    return scenario, space, order, project, phases


def test_install_is_refused_while_the_assigned_room_is_under_renovation():
    """A room mid-renovation is not installable even though the occupancy is in order.

    PRD 3.5: "While a room is UNDER_RENOVATION, equipment installation into it is
    refused with ERR_SPACE_NOT_READY_FOR_INSTALL."

    Design: Difficulty/cross_entity_state_dependency/equipment_install_gated_by_lab_space_renovation_status
    """
    scenario, space, order, _, _ = _delivered_order_in_an_assigned_room_being_renovated()
    assert fixtures.read_space(space["id"])["status"] == "UNDER_RENOVATION"

    response = api_client.install_equipment_order(order["id"],
                                                 scenario["headers"]["facilities"])
    validate_error(response, "ERR_SPACE_NOT_READY_FOR_INSTALL", expected_status=409)

    blocked = fixtures.read_order(order["id"])
    assert blocked["status"] == "DELIVERED"
    assert blocked["installed_on"] is None
    room = fixtures.read_space(space["id"])
    assert_power_kw(room["installed_power_kw"], 0)
    assert room["installed_fume_hoods"] == 0


def test_the_same_install_succeeds_once_the_renovation_reopens_the_room():
    """Closing out the renovation flips the gate and the identical call installs.

    PRD 3.7: "On success the order moves DELIVERED to INSTALLED (or UTILITY_BLOCKED to
    INSTALLED, which is the join point of the fork and behaves identically), installed_on
    is stamped from the clock, and utility_block_reason is set to null."

    Design: Difficulty/cross_entity_state_dependency/equipment_install_gated_by_lab_space_renovation_status
    """
    scenario, space, order, project, phases = _delivered_order_in_an_assigned_room_being_renovated()

    fixtures.start_phase(project["id"], phases[0]["id"])
    fixtures.complete_phase(project["id"], phases[0]["id"], 12_000_000)
    completed = fixtures.substantial_completion(project["id"])
    assert completed["cost_variance_cents"] == 0
    assert fixtures.read_space(space["id"])["status"] == "ASSIGNED"

    installed = fixtures.install_order(order["id"], scenario["headers"]["facilities"])
    assert installed["status"] == "INSTALLED"
    assert installed["utility_block_reason"] is None
    assert_instant_equals(installed["installed_on"], "2026-08-01T00:00:00Z")

    room = fixtures.read_space(space["id"])
    assert_power_kw(room["installed_power_kw"], 20.00)
    assert room["installed_fume_hoods"] == 1


def test_a_variance_free_renovation_writes_no_reconciliation_row():
    """When the final charge equals the estimate the settlement is the disbursement alone.

    PRD 3.6: "When cost_variance_cents is exactly 0 no reconciliation row is written
    at all, and when it is negative the surplus is released back to the tranches
    that carried the estimate."

    Design: Difficulty/cross_entity_state_dependency/equipment_install_gated_by_lab_space_renovation_status
    """
    scenario, space, order, project, phases = _delivered_order_in_an_assigned_room_being_renovated()

    fixtures.start_phase(project["id"], phases[0]["id"])
    fixtures.complete_phase(project["id"], phases[0]["id"], 12_000_000)
    fixtures.substantial_completion(project["id"])
    fixtures.install_order(order["id"], scenario["headers"]["facilities"])

    project_rows = rows_for_source(fixtures.read_ledger(scenario["package_id"]), project["id"])
    assert len(rows_of_kind(project_rows, "ENCUMBRANCE")) == 1
    assert len(rows_of_kind(project_rows, "DISBURSEMENT")) == 1
    assert len(project_rows) == 2

    assert_tranche_balances(fixtures.read_tranche(scenario["tranche"]["renovation"]["id"]),
                            disbursed_cents=9_000_000, available_balance_cents=3_000_000)
    assert_tranche_balances(fixtures.read_tranche(scenario["tranche"]["equipment_capped"]["id"]),
                            disbursed_cents=5_000_000, available_balance_cents=20_000_000)

    assert_unit_balances(fixtures.read_unit(scenario["department_id"]),
                         disbursed_cents=6_300_000, committed_cents=0)
    assert_unit_balances(fixtures.read_unit(scenario["college_id"]),
                         disbursed_cents=4_900_000, committed_cents=0)
    assert_unit_balances(fixtures.read_unit(scenario["dean_office_id"]),
                         disbursed_cents=2_800_000, committed_cents=0)


def _room_with_a_candidate_and_a_departing_faculty_member():
    """One arriving candidate with no package, one active holder who has given notice."""
    scenario = fixtures.setup_mini_active()
    arriving = fixtures.create_candidate_faculty(scenario["department_id"],
                                                 full_name="Bo Nakamura")
    fixtures.record_departure_notice(scenario["faculty_id"], "OUTSIDE_OFFER", "2027-06-30")
    space = fixtures.create_lab_space(building_code="CHEM", room_number="602",
                                      space_class="DRY")
    return scenario, arriving, space


def test_a_room_may_be_promised_to_a_candidate_who_has_not_arrived():
    """A candidate with no package at all is an admissible occupant.

    PRD 3.5: "The faculty member must be in appointment_status ACTIVE or CANDIDATE - a
    room may legitimately be promised before arrival - and anything else yields
    ERR_FACULTY_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/space_assignment_admissibility_gated_by_faculty_appointment_status
    """
    scenario, arriving, space = _room_with_a_candidate_and_a_departing_faculty_member()
    assert fixtures.read_faculty(arriving["id"])["appointment_status"] == "CANDIDATE"

    assignment = fixtures.propose_space_assignment(space, arriving["id"], share_pct=40)
    assert assignment["status"] == "PROPOSED"
    assert assignment["released_on"] is None

    activated = fixtures.activate_space_assignment(assignment["id"])
    assert activated["status"] == "ACTIVE"
    room = fixtures.read_space(space["id"])
    assert room["status"] == "ASSIGNED"
    assert room["allocated_share_pct"] == 40


def test_a_faculty_member_under_notice_may_not_be_given_a_room():
    """Notice given closes the room-assignment door on the faculty gate alone.

    PRD 2.13: "DEPARTURE_NOTICE, DEPARTED and TRANSFERRED_INTERNAL are never allowed."

    PRD 2.13: "This rule is the only reachable faculty gate on POST /space-assignments,
    which carries no spend-authority precondition and is therefore never shadowed by
    priority 18."

    PRD 3.9: "The faculty member's package with negotiation_status ACTIVE moves
    spend_status SPENDING -> FROZEN."

    Design: Difficulty/cross_entity_state_dependency/space_assignment_admissibility_gated_by_faculty_appointment_status
    """
    scenario, _, space = _room_with_a_candidate_and_a_departing_faculty_member()
    assert fixtures.read_faculty(scenario["faculty_id"])["appointment_status"] == "DEPARTURE_NOTICE"
    # The notice froze the package, and the assignment create has no spend gate, so the
    # faculty gate at priority 21 is still the rule that fires.
    assert fixtures.read_package(scenario["package_id"])["spend_status"] == "FROZEN"

    response = api_client.create_space_assignment(
        {
            "space_id": space["id"],
            "faculty_id": scenario["faculty_id"],
            "share_pct": 60,
            "effective_from": "2026-08-01T00:00:00Z",
            "expected_space_version": space["version"],
        },
        scenario["headers"]["dean_office"],
    )
    validate_error(response, "ERR_FACULTY_NOT_ACTIVE", expected_status=409)

    room = fixtures.read_space(space["id"])
    assert room["status"] == "AVAILABLE"
    assert room["allocated_share_pct"] == 0
    assert room["version"] == space["version"]
    assert_tranche_balances(fixtures.read_tranche(scenario["tranche"]["equipment"]["id"]),
                            available_balance_cents=20_000_000, encumbered_cents=0)
