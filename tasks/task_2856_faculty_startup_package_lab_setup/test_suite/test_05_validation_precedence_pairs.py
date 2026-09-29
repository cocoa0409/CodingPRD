"""Ordered validation: which of two live failures a request reports first."""

from test_helpers import api_client, fixtures, validate_error
from test_helpers.assertions import assert_tranche_balances, assert_unit_balances
from test_helpers.fixtures import BASE_PROPOSED_TOTAL_CENTS, BASE_TRANCHE_SPECS

BIG_PHASE = [
    {
        "sequence_no": 1,
        "name": "Gut and rebuild",
        "planned_start": "2026-08-10T00:00:00Z",
        "planned_end": "2026-11-30T00:00:00Z",
        "budget_cents": 60_000_000,
    },
]


def _bid_project_on_an_approved_package():
    """A 60,000,000 cent project out to bid on a package that is APPROVED, not ACTIVE."""
    scenario = fixtures.setup_approved_package(
        tranche_specs=BASE_TRANCHE_SPECS,
        proposed_total_cents=BASE_PROPOSED_TOTAL_CENTS,
    )
    scenario["faculty"] = fixtures.activate_faculty(scenario["faculty_id"])
    space = fixtures.create_lab_space(building_code="CHEM", room_number="401",
                                      space_class="WET")
    project, _ = fixtures.setup_scoped_project(
        scenario["package_id"], space["id"], phase_specs=BIG_PHASE,
        project_overrides={"scope_tier": "MODERATE", "estimate_cents": 60_000_000},
    )
    fixtures.solicit_bids(project["id"])
    return scenario, space, project


def test_award_reports_the_frozen_spend_axis_before_the_tranche_shortfall():
    """The spend-axis gate is checked before the money is looked for.

    PRD 2.13: "When it does, the rule with the lowest priority number in the ordered
    ladder below is the one reported, and no later rule is evaluated."

    PRD 3.4: "Every money-moving operation ... requires spend_status to be exactly
    SPENDING, and reports ERR_PACKAGE_SPEND_FROZEN when it is NOT_YET_AVAILABLE, FROZEN
    or SETTLED."

    Design: Difficulty/priority_pair_validation_conflict/award_spend_axis_frozen_outranks_insufficient_renovation_balance
    """
    scenario, _, project = _bid_project_on_an_approved_package()
    # The package is APPROVED but never activated, so the spend axis is still closed.
    assert fixtures.read_package(scenario["package_id"])["spend_status"] == "NOT_YET_AVAILABLE"

    response = api_client.award_renovation_project(
        project["id"], {"awarded_cents": 60_000_000}, scenario["headers"]["dean"]
    )
    validate_error(response, "ERR_PACKAGE_SPEND_FROZEN", expected_status=409)

    unchanged = fixtures.read_project(project["id"])
    assert unchanged["status"] == "BID"
    assert unchanged["awarded_cents"] is None


def test_award_reports_the_tranche_shortfall_once_the_spend_axis_is_open():
    """With the freeze lifted the identical award reaches the balance check and fails there.

    PRD 2.13: "ERR_INSUFFICIENT_TRANCHE_BALANCE (422) — the summed
    available_balance_cents of the eligible tranches is at least the amount to be
    encumbered."

    Design: Difficulty/priority_pair_validation_conflict/award_spend_axis_frozen_outranks_insufficient_renovation_balance
    """
    scenario, _, project = _bid_project_on_an_approved_package()
    fixtures.activate_package(scenario["package_id"])

    response = api_client.award_renovation_project(
        project["id"], {"awarded_cents": 60_000_000}, scenario["headers"]["dean"]
    )
    validate_error(response, "ERR_INSUFFICIENT_TRANCHE_BALANCE", expected_status=422)

    unchanged = fixtures.read_project(project["id"])
    assert unchanged["status"] == "BID"
    assert unchanged["awarded_cents"] is None

    assert_tranche_balances(fixtures.read_tranche(scenario["tranche"]["renovation"]["id"]),
                            encumbered_cents=0, available_balance_cents=12_000_000)
    assert_unit_balances(fixtures.read_unit(scenario["department_id"]), committed_cents=0)
    assert_unit_balances(fixtures.read_unit(scenario["college_id"]), committed_cents=0)
    assert_unit_balances(fixtures.read_unit(scenario["dean_office_id"]), committed_cents=0)


MODERATE_PHASE = [
    {
        "sequence_no": 1,
        "name": "Casework",
        "planned_start": "2026-08-10T00:00:00Z",
        "planned_end": "2026-10-30T00:00:00Z",
        "budget_cents": 12_000_000,
    },
]


def _delivered_order_into_an_unassigned_room_under_renovation():
    """A delivered order aimed at a room that is both unassigned and being renovated."""
    scenario = fixtures.setup_base_package()
    space = fixtures.create_lab_space(building_code="CHEM", room_number="402",
                                      space_class="WET")
    order = fixtures.setup_received_order(scenario["package_id"], space["id"],
                                          quoted_cents=5_000_000, required_power_kw=20.0,
                                          required_fume_hoods=1)
    project, _ = fixtures.setup_awarded_project(
        scenario["package_id"], space["id"], 12_000_000, scenario["headers"]["dean"],
        phase_specs=MODERATE_PHASE,
        project_overrides={"scope_tier": "MODERATE", "estimate_cents": 12_000_000},
    )
    assert fixtures.read_space(space["id"])["status"] == "UNDER_RENOVATION"
    return scenario, space, order, project


def test_install_reports_the_missing_assignment_before_the_room_status():
    """With no assignment at all, the occupancy gate is reported ahead of the room status.

    PRD 2.13: "ERR_SPACE_NOT_ASSIGNED_TO_FACULTY (422) — the order's
    install_space_id is covered by a room assignment in status ACTIVE whose
    faculty_id equals the package's faculty_id and whose half-open window contains
    the clock."

    Design: Difficulty/priority_pair_validation_conflict/install_missing_assignment_outranks_room_under_renovation
    """
    scenario, _, order, _ = _delivered_order_into_an_unassigned_room_under_renovation()

    response = api_client.install_equipment_order(order["id"],
                                                 scenario["headers"]["facilities"])
    validate_error(response, "ERR_SPACE_NOT_ASSIGNED_TO_FACULTY", expected_status=422)
    assert fixtures.read_order(order["id"])["status"] == "DELIVERED"


def test_install_reports_the_room_status_once_the_assignment_is_active():
    """Satisfying the occupancy gate exposes the renovation status underneath it.

    PRD 2.13: "ERR_SPACE_NOT_READY_FOR_INSTALL (409) — the install_space_id room is
    in LabSpace status ASSIGNED; a room still UNDER_RENOVATION, or DECOMMISSIONED,
    cannot receive equipment even when the faculty member holds an assignment on
    it."

    Design: Difficulty/priority_pair_validation_conflict/install_missing_assignment_outranks_room_under_renovation
    """
    scenario, space, order, _ = _delivered_order_into_an_unassigned_room_under_renovation()

    current = fixtures.read_space(space["id"])
    assignment = fixtures.propose_space_assignment(current, scenario["faculty_id"])
    fixtures.activate_space_assignment(assignment["id"])
    assert fixtures.read_space(space["id"])["status"] == "UNDER_RENOVATION"

    response = api_client.install_equipment_order(order["id"],
                                                 scenario["headers"]["facilities"])
    validate_error(response, "ERR_SPACE_NOT_READY_FOR_INSTALL", expected_status=409)

    assert fixtures.read_order(order["id"])["status"] == "DELIVERED"
    assert_unit_balances(fixtures.read_unit(scenario["department_id"]),
                         committed_cents=6_300_000, disbursed_cents=0)
    assert_unit_balances(fixtures.read_unit(scenario["college_id"]),
                         committed_cents=4_900_000, disbursed_cents=0)
    assert_unit_balances(fixtures.read_unit(scenario["dean_office_id"]),
                         committed_cents=2_800_000, disbursed_cents=0)
