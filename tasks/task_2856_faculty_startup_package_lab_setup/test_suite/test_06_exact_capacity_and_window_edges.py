"""Boundaries taken exactly: capacity equal to the requirement, and a window's last instant."""

from test_helpers import api_client, fixtures, validate_error
from test_helpers.assertions import (
    assert_row_amount_and_shares,
    assert_tranche_balances,
    assert_unit_balances,
    rows_for_source,
    rows_of_kind,
)
from test_helpers.factories import place_equipment_order_payload


def test_waterfall_accepts_a_set_whose_capacity_exactly_equals_the_requirement():
    """Two open tranches summing to the quote exactly are both accepted.

    PRD 3.4: "Capacity exactly equal to the required amount is accepted: the last
    tranche is drained to an available_balance_cents of exactly 0 and stays OPEN."

    Design: Difficulty/boundary_precision_check/waterfall_capacity_exactly_equals_required_then_one_cent_over
    """
    scenario = fixtures.setup_base_package()
    space = fixtures.create_lab_space(building_code="CHEM", room_number="510")

    order = fixtures.setup_placed_order(scenario["package_id"], space["id"],
                                        quoted_cents=40_000_000)
    assert order["status"] == "ORDERED"

    assert_tranche_balances(fixtures.read_tranche(scenario["tranche"]["equipment_capped"]["id"]),
                            status="OPEN", encumbered_cents=25_000_000,
                            available_balance_cents=0)
    assert_tranche_balances(fixtures.read_tranche(scenario["tranche"]["equipment_full"]["id"]),
                            status="OPEN", encumbered_cents=15_000_000,
                            available_balance_cents=0)
    assert_tranche_balances(fixtures.read_tranche(scenario["tranche"]["equipment_next_year"]["id"]),
                            status="SCHEDULED", encumbered_cents=0,
                            available_balance_cents=8_000_000)


def test_an_exactly_covered_order_writes_one_encumbrance_row_per_accepted_tranche():
    """The two accepted tranches produce two rows, each split across the three funders.

    PRD 3.4: "When the capacity check passes, the waterfall walks the ordered
    candidates taking from each the lesser of the amount still outstanding and that
    tranche's available_balance_cents, writing one ENCUMBRANCE row per tranche
    actually consumed and stopping as soon as the outstanding amount reaches 0."

    Design: Difficulty/boundary_precision_check/waterfall_capacity_exactly_equals_required_then_one_cent_over
    """
    scenario = fixtures.setup_base_package()
    space = fixtures.create_lab_space(building_code="CHEM", room_number="510")
    order = fixtures.setup_placed_order(scenario["package_id"], space["id"],
                                        quoted_cents=40_000_000)

    rows = rows_of_kind(rows_for_source(fixtures.read_ledger(scenario["package_id"]),
                                        order["id"]), "ENCUMBRANCE")
    assert len(rows) == 2
    assert_row_amount_and_shares(rows[0], 25_000_000, 11_250_000, 8_750_000, 5_000_000)
    assert_row_amount_and_shares(rows[1], 15_000_000, 6_750_000, 5_250_000, 3_000_000)

    assert_unit_balances(fixtures.read_unit(scenario["department_id"]),
                         committed_cents=18_000_000)
    assert_unit_balances(fixtures.read_unit(scenario["college_id"]),
                         committed_cents=14_000_000)
    assert_unit_balances(fixtures.read_unit(scenario["dean_office_id"]),
                         committed_cents=8_000_000)


def test_one_cent_beyond_the_exhausted_capacity_is_refused_whole():
    """A single cent more than the open capacity fails all-or-nothing.

    PRD 3.4: "The capacity of the set is the sum of the candidates'
    available_balance_cents; if that capacity is strictly less than the required
    amount the request is rejected with ERR_INSUFFICIENT_TRANCHE_BALANCE and no
    partial encumbrance is written at all, because the waterfall is all-or-nothing."

    Design: Difficulty/boundary_precision_check/waterfall_capacity_exactly_equals_required_then_one_cent_over
    """
    scenario = fixtures.setup_base_package()
    space = fixtures.create_lab_space(building_code="CHEM", room_number="510")
    fixtures.setup_placed_order(scenario["package_id"], space["id"],
                                quoted_cents=40_000_000)

    one_cent = fixtures.create_order(scenario["package_id"], space["id"], quoted_cents=1)
    package = fixtures.read_package(scenario["package_id"])
    response = api_client.place_equipment_order(
        one_cent["id"], place_equipment_order_payload(package["version"]),
        scenario["headers"]["dean_office"],
    )
    validate_error(response, "ERR_INSUFFICIENT_TRANCHE_BALANCE", expected_status=422)

    assert fixtures.read_order(one_cent["id"])["status"] == "REQUESTED"
    assert rows_for_source(fixtures.read_ledger(scenario["package_id"]), one_cent["id"]) == []

    settled = fixtures.read_package(scenario["package_id"])
    assert settled["total_encumbered_cents"] == 40_000_000
    assert settled["total_available_cents"] == 32_000_000


def _personnel_package_with_two_queued_appointments():
    """Two two-month appointments on the FY2027 personnel tranche, both PROPOSED."""
    scenario = fixtures.setup_base_package()
    first = fixtures.create_staff_appointment(
        scenario["package_id"], appointment_type="POSTDOC", fte=1.00,
        monthly_cost_cents=200_000, start_date="2027-07-01", end_date="2027-08-31",
    )
    second = fixtures.create_staff_appointment(
        scenario["package_id"], appointment_type="POSTDOC", fte=1.00,
        monthly_cost_cents=200_000, start_date="2027-09-01", end_date="2027-10-31",
    )
    return scenario, first, second


def test_an_activation_inside_the_window_encumbers_the_personnel_tranche():
    """Activating while the clock is inside the tranche's window encumbers it normally.

    PRD 3.8: "Activation by the dean's office moves the appointment PROPOSED →
    ACTIVE and encumbers that total."

    Design: Difficulty/boundary_precision_check/personnel_tranche_window_closes_exactly_at_expires_on_instant
    """
    scenario, first, _ = _personnel_package_with_two_queued_appointments()

    activated = fixtures.activate_staff_appointment(first["id"])
    assert activated["status"] == "ACTIVE"
    assert activated["encumbered_cents"] == 400_000

    assert_tranche_balances(fixtures.read_tranche(scenario["tranche"]["personnel"]["id"]),
                            status="OPEN", encumbered_cents=400_000,
                            available_balance_cents=9_200_000)
    assert_unit_balances(fixtures.read_unit(scenario["department_id"]), committed_cents=180_000)
    assert_unit_balances(fixtures.read_unit(scenario["college_id"]), committed_cents=140_000)
    assert_unit_balances(fixtures.read_unit(scenario["dean_office_id"]), committed_cents=80_000)


def test_the_window_closes_exactly_at_expires_on_so_the_tranche_stops_being_a_candidate():
    """At the expires_on instant itself the tranche is out of the window, not merely short.

    PRD 3.4: "Given a required amount and a required category, the candidate set is
    every tranche of that package whose category matches, whose status is exactly
    OPEN, and whose half-open availability window contains the clock; SCHEDULED,
    OBLIGATED, CARRIED_FORWARD, EXPIRED and RECAPTURED tranches never participate."

    Design: Difficulty/boundary_precision_check/personnel_tranche_window_closes_exactly_at_expires_on_instant
    """
    scenario, first, second = _personnel_package_with_two_queued_appointments()
    fixtures.activate_staff_appointment(first["id"])

    fixtures.set_clock("2027-07-01T00:00:00Z")
    response = api_client.activate_staff_appointment(second["id"],
                                                     scenario["headers"]["dean_office"])
    validate_error(response, "ERR_NO_OPEN_TRANCHE", expected_status=422)

    assert fixtures.read_appointment(second["id"])["status"] == "PROPOSED"
    assert_tranche_balances(fixtures.read_tranche(scenario["tranche"]["personnel"]["id"]),
                            status="OPEN", encumbered_cents=400_000,
                            available_balance_cents=9_200_000)
