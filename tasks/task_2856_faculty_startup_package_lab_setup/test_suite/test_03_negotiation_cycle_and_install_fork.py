"""The negotiation cycle against the spend axis, and the installation fork and join."""

from test_helpers import fixtures
from test_helpers.assertions import (
    assert_power_kw,
    assert_tranche_balances,
    assert_unit_balances,
)


def test_counter_voids_the_endorsement_and_revision_closes_the_cycle_to_draft():
    """The cycle returns to DRAFT with the round counter advanced and signatures cleared.

    PRD 3.3: "Countering has one non-obvious secondary effect: it voids the endorsement
    by clearing endorsed_by_user_id back to null."

    Design: Difficulty/non_linear_state_machine/package_negotiation_cycle_with_independent_spend_axis
    """
    scenario = fixtures.setup_base_draft()
    package_id = scenario["package_id"]

    fixtures.submit_package(package_id)
    fixtures.endorse_package(package_id, scenario["department_id"])

    countered = fixtures.counter_package(package_id, 69_600_000, scenario["headers"]["dean"])
    assert countered["negotiation_status"] == "COUNTERED"
    assert countered["counter_total_cents"] == 69_600_000
    assert countered["endorsed_by_user_id"] is None

    revised = fixtures.revise_package(package_id, 69_600_000)
    assert revised["negotiation_status"] == "DRAFT"
    assert revised["proposed_total_cents"] == 69_600_000
    assert revised["negotiation_round"] == 2
    assert revised["proposed_by_user_id"] is None


def _second_lap_to_active(scenario):
    """Counter, revise, withdraw the discretionary tranche and re-run the signatures."""
    package_id = scenario["package_id"]
    fixtures.submit_package(package_id)
    fixtures.endorse_package(package_id, scenario["department_id"])
    fixtures.counter_package(package_id, 69_600_000, scenario["headers"]["dean"])
    fixtures.revise_package(package_id, 69_600_000)
    fixtures.withdraw_tranche(package_id, scenario["tranche"]["discretionary"]["id"])
    fixtures.submit_package(package_id)
    fixtures.endorse_package(package_id, scenario["department_id"])
    return fixtures.approve_package(package_id, scenario["college_id"])


def test_negotiation_axis_reaches_approved_while_the_spend_axis_has_not_moved():
    """Approval advances the negotiation only; spending is a separate axis on the same row.

    PRD 3.4: "The negotiation axis alone never authorises spending."

    Design: Difficulty/non_linear_state_machine/package_negotiation_cycle_with_independent_spend_axis
    """
    scenario = fixtures.setup_base_draft()

    approved = _second_lap_to_active(scenario)
    assert approved["negotiation_status"] == "APPROVED"
    assert approved["spend_status"] == "NOT_YET_AVAILABLE"

    fixtures.activate_faculty(scenario["faculty_id"])
    activated = fixtures.activate_package(scenario["package_id"])
    assert activated["negotiation_status"] == "ACTIVE"
    assert activated["spend_status"] == "SPENDING"

    fixtures.record_departure_notice(scenario["faculty_id"], "OUTSIDE_OFFER", "2026-12-31")
    frozen = fixtures.read_package(scenario["package_id"])
    assert frozen["negotiation_status"] == "ACTIVE"
    assert frozen["spend_status"] == "FROZEN"


def test_withdrawing_a_tranche_lowers_the_commitment_the_pools_reserve():
    """The five surviving tranches are what the funder units reserve at approval.

    PRD 3.3: "each funder unit's reserved_cents rises by exactly its computed share of
    total_committed_cents, with available_pool_cents re-derived accordingly."

    Design: Difficulty/non_linear_state_machine/package_negotiation_cycle_with_independent_spend_axis
    """
    scenario = fixtures.setup_base_draft()

    approved = _second_lap_to_active(scenario)
    assert approved["total_committed_cents"] == 69_600_000

    assert_unit_balances(fixtures.read_unit(scenario["department_id"]),
                         reserved_cents=31_320_000)
    assert_unit_balances(fixtures.read_unit(scenario["college_id"]),
                         reserved_cents=24_360_000)
    assert_unit_balances(fixtures.read_unit(scenario["dean_office_id"]),
                         reserved_cents=13_920_000)


def _room_with_two_delivered_orders(scenario):
    """A 100 kW room holding two delivered orders that cannot both fit its power."""
    space = fixtures.create_lab_space(building_code="CHEM", room_number="204",
                                      space_class="WET", power_kw_capacity=100.0,
                                      fume_hood_count=2, chilled_water_available=True,
                                      floor_load_psf=250)
    fixtures.create_active_assignment(space, scenario["faculty_id"])
    order_a = fixtures.setup_received_order(
        scenario["package_id"], space["id"], quoted_cents=5_000_000,
        item_description="Cryostat", required_power_kw=60.0, required_fume_hoods=1,
        required_floor_load_psf=120,
    )
    order_b = fixtures.setup_received_order(
        scenario["package_id"], space["id"], quoted_cents=3_000_000,
        item_description="Glovebox", required_power_kw=50.0, required_fume_hoods=1,
        required_floor_load_psf=120,
    )
    return space, order_a, order_b


def test_installation_takes_the_installed_branch_and_loads_the_room():
    """A feasible installation disburses the encumbrance and raises the room's load.

    PRD 3.7: "The room's installed_power_kw and installed_fume_hoods are re-derived as
    the running sums over that room's INSTALLED orders only."

    Design: Difficulty/non_linear_state_machine/equipment_delivered_fork_to_blocked_and_join_back_to_installed
    """
    scenario = fixtures.setup_base_package()
    space, order_a, _ = _room_with_two_delivered_orders(scenario)

    installed = fixtures.install_order(order_a["id"])
    assert installed["status"] == "INSTALLED"
    assert installed["disbursed_cents"] == 5_000_000
    assert installed["encumbered_cents"] == 0

    room = fixtures.read_space(space["id"])
    assert_power_kw(room["installed_power_kw"], 60.00)
    assert room["installed_fume_hoods"] == 1


def test_installation_forks_to_utility_blocked_without_moving_a_cent():
    """The blocked branch returns 200, names the first failing check and changes nothing.

    PRD 3.7: "On failure the order moves DELIVERED to UTILITY_BLOCKED with
    utility_block_reason set to the first failing check, and the divergent side-effect
    set is precisely that nothing else happens: no ledger row is written, nothing is
    disbursed, the encumbrance stays open with the money still committed, and the room's
    installed_power_kw and installed_fume_hoods are unchanged."

    Design: Difficulty/non_linear_state_machine/equipment_delivered_fork_to_blocked_and_join_back_to_installed
    """
    scenario = fixtures.setup_base_package()
    space, order_a, order_b = _room_with_two_delivered_orders(scenario)

    fixtures.install_order(order_a["id"])
    blocked = fixtures.install_order(order_b["id"])

    assert blocked["status"] == "UTILITY_BLOCKED"
    assert blocked["utility_block_reason"] == "POWER"
    assert blocked["encumbered_cents"] == 3_000_000
    assert blocked["disbursed_cents"] == 0

    room = fixtures.read_space(space["id"])
    assert_power_kw(room["installed_power_kw"], 60.00)


def test_a_utility_upgrade_rejoins_the_blocked_order_to_installed():
    """The two branches rejoin at INSTALLED once the room's envelope is raised.

    PRD 3.7: "On success the order moves DELIVERED to INSTALLED (or UTILITY_BLOCKED to
    INSTALLED, which is the join point of the fork and behaves identically),
    installed_on is stamped from the clock, and utility_block_reason is set to null."

    Design: Difficulty/non_linear_state_machine/equipment_delivered_fork_to_blocked_and_join_back_to_installed
    """
    scenario = fixtures.setup_base_package()
    space, order_a, order_b = _room_with_two_delivered_orders(scenario)

    fixtures.install_order(order_a["id"])
    fixtures.install_order(order_b["id"])

    upgraded = fixtures.upgrade_utilities(space["id"], power_kw_capacity=150.0,
                                          fume_hood_count=2,
                                          chilled_water_available=True,
                                          floor_load_psf=250)
    assert_power_kw(upgraded["power_kw_capacity"], 150.00)
    assert_power_kw(upgraded["installed_power_kw"], 60.00)
    assert upgraded["status"] == "ASSIGNED"

    joined = fixtures.install_order(order_b["id"])
    assert joined["status"] == "INSTALLED"
    assert joined["utility_block_reason"] is None

    room = fixtures.read_space(space["id"])
    assert_power_kw(room["installed_power_kw"], 110.00)
    assert room["installed_fume_hoods"] == 2

    assert_tranche_balances(fixtures.read_tranche(scenario["tranche"]["equipment_capped"]["id"]),
                            encumbered_cents=0, disbursed_cents=8_000_000,
                            available_balance_cents=17_000_000)
    assert_unit_balances(fixtures.read_unit(scenario["department_id"]),
                         disbursed_cents=3_600_000)
    assert_unit_balances(fixtures.read_unit(scenario["college_id"]),
                         disbursed_cents=2_800_000)
    assert_unit_balances(fixtures.read_unit(scenario["dean_office_id"]),
                         disbursed_cents=1_600_000)
