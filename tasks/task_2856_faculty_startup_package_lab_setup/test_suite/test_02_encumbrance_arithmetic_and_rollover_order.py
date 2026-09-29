"""Appointment pricing arithmetic and the pinned order of the year-end rollover."""

from test_helpers import fixtures
from test_helpers.assertions import (
    assert_spend_down_ratio,
    assert_tranche_balances,
    assert_unit_balances,
)
from test_helpers.constants import (
    FY2027_AVAILABLE_ON,
    FY2027_EXPIRES_ON,
    FY2028_AVAILABLE_ON,
    FY2028_EXPIRES_ON,
)


def _lab_manager_appointment(scenario):
    """A twelve-month lab manager whose weighted monthly charge has a fractional cent."""
    return fixtures.create_staff_appointment(
        scenario["package_id"],
        appointment_type="LAB_MANAGER",
        fte=0.77,
        monthly_cost_cents=583_333,
        start_date="2026-09-01",
        end_date="2027-08-31",
    )


def test_appointment_encumbrance_rounds_the_monthly_charge_before_multiplying():
    """The monthly charge is rounded first, then multiplied by the committed months.

    PRD 3.8: "The full-time-equivalent-weighted monthly charge is rounded half up to
    whole cents first, and only then multiplied by the month count."

    Design: Difficulty/combinatorial_formula/staff_encumbrance_round_per_month_then_multiply
    """
    scenario = fixtures.setup_base_package()
    appointment = _lab_manager_appointment(scenario)

    activated = fixtures.activate_staff_appointment(appointment["id"])

    assert activated["status"] == "ACTIVE"
    assert activated["committed_months"] == 12
    assert activated["encumbered_cents"] == 5_389_992
    assert activated["encumbered_cents"] != 5_389_997


def test_appointment_encumbrance_lands_on_the_personnel_tranche_and_three_funders():
    """The encumbrance total reaches the PERSONNEL tranche and the three funder units.

    PRD 3.8: "The waterfall then writes one ENCUMBRANCE row per PERSONNEL tranche
    consumed, and each funding unit's committed_cents rises by its stored share."

    Design: Difficulty/combinatorial_formula/staff_encumbrance_round_per_month_then_multiply
    """
    scenario = fixtures.setup_base_package()
    appointment = _lab_manager_appointment(scenario)

    fixtures.activate_staff_appointment(appointment["id"])

    assert_tranche_balances(fixtures.read_tranche(scenario["tranche"]["personnel"]["id"]),
                           encumbered_cents=5_389_992,
                           available_balance_cents=4_210_008)

    department = fixtures.read_unit(scenario["department_id"])
    college = fixtures.read_unit(scenario["college_id"])
    dean_office = fixtures.read_unit(scenario["dean_office_id"])
    assert_unit_balances(department, committed_cents=2_425_497)
    assert_unit_balances(college, committed_cents=1_886_497)
    assert_unit_balances(dean_office, committed_cents=1_077_998)
    assert (department["committed_cents"] + college["committed_cents"]
            + dean_office["committed_cents"] == 5_389_992)


ROLLOVER_TRANCHES = [
    {
        "key": "equipment_2027",
        "category": "EQUIPMENT",
        "fiscal_year": 2027,
        "amount_cents": 12_000_000,
        "available_on": FY2027_AVAILABLE_ON,
        "expires_on": FY2027_EXPIRES_ON,
        "carryforward_policy": "FULL",
    },
    {
        "key": "equipment_2028",
        "category": "EQUIPMENT",
        "fiscal_year": 2028,
        "amount_cents": 5_000_000,
        "available_on": FY2028_AVAILABLE_ON,
        "expires_on": FY2028_EXPIRES_ON,
        "carryforward_policy": "NONE",
    },
    {
        "key": "personnel_2027",
        "category": "PERSONNEL",
        "fiscal_year": 2027,
        "amount_cents": 3_000_000,
        "available_on": FY2027_AVAILABLE_ON,
        "expires_on": FY2027_EXPIRES_ON,
        "carryforward_policy": "NONE",
    },
]


def _package_at_the_carryforward_boundary():
    """Half of the commitment is encumbered and fiscal year 2027 has just elapsed."""
    scenario = fixtures.setup_active_package(
        tranche_specs=ROLLOVER_TRANCHES, proposed_total_cents=20_000_000
    )
    space = fixtures.create_lab_space(building_code="CHEM", room_number="140",
                                      space_class="DRY")
    fixtures.setup_placed_order(scenario["package_id"], space["id"],
                               quoted_cents=10_000_000)
    fixtures.set_clock("2027-07-01T00:00:00Z")
    return scenario


def test_rollover_reads_the_eligibility_ratio_before_writing_any_row():
    """The pre-rollover ratio sits exactly on the threshold, so carryforward is eligible.

    PRD 3.9: "Carryforward is permitted only when that ratio is at or above 0.5000 - a
    package that has committed or spent half of its total commitment has earned the
    right to roll money forward."

    Design: Difficulty/combinatorial_formula/year_end_rollover_obligation_before_carryforward_order
    """
    scenario = _package_at_the_carryforward_boundary()

    before = fixtures.read_package(scenario["package_id"])
    assert_spend_down_ratio(before["spend_down_ratio"], 0.5000)

    fixtures.rollover_fiscal_year(scenario["package_id"], 2027)

    destination = fixtures.read_tranche(scenario["tranche"]["equipment_2028"]["id"])
    assert_tranche_balances(destination, status="OPEN", carried_in_cents=2_000_000,
                            available_balance_cents=7_000_000)

    after = fixtures.read_package(scenario["package_id"])
    assert after["total_committed_cents"] == 20_000_000


def test_rollover_obligates_the_encumbered_tranche_yet_still_sweeps_its_balance():
    """The OBLIGATED label wins while steps 4 to 6 still drain the available balance.

    PRD 3.9: "The OBLIGATED label outranks the CARRIED_FORWARD and EXPIRED labels that
    step 6 would otherwise assign: the status stays OBLIGATED until the last
    encumbrance on it settles, at which point the tranche auto-transitions OBLIGATED to
    EXPIRED."

    Design: Difficulty/combinatorial_formula/year_end_rollover_obligation_before_carryforward_order
    """
    scenario = _package_at_the_carryforward_boundary()

    fixtures.rollover_fiscal_year(scenario["package_id"], 2027)

    subject = fixtures.read_tranche(scenario["tranche"]["equipment_2027"]["id"])
    assert_tranche_balances(subject, status="OBLIGATED", encumbered_cents=10_000_000,
                            carried_out_cents=2_000_000, available_balance_cents=0)


def test_rollover_expires_the_non_carrying_tranche_and_returns_money_to_the_pools():
    """A NONE-policy tranche expires its residue and refunds each funder's share.

    PRD 3.9: "For every EXPIRY row written, each funding unit's reserved_cents falls
    and its refunded_cents rises by that row's stored share, returning the money to the
    pool."

    Design: Difficulty/combinatorial_formula/year_end_rollover_obligation_before_carryforward_order
    """
    scenario = _package_at_the_carryforward_boundary()

    fixtures.rollover_fiscal_year(scenario["package_id"], 2027)

    assert_tranche_balances(fixtures.read_tranche(scenario["tranche"]["personnel_2027"]["id"]),
                            status="EXPIRED", expired_cents=3_000_000,
                            available_balance_cents=0)

    assert_unit_balances(fixtures.read_unit(scenario["department_id"]),
                         refunded_cents=1_350_000, reserved_cents=7_650_000)
    assert_unit_balances(fixtures.read_unit(scenario["college_id"]),
                         refunded_cents=1_050_000, reserved_cents=5_950_000)
    assert_unit_balances(fixtures.read_unit(scenario["dean_office_id"]),
                         refunded_cents=600_000, reserved_cents=3_400_000)
