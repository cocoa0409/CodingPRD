"""Two deep cascades: a separation settlement and a substantial completion."""

from test_helpers import fixtures
from test_helpers.assertions import (
    assert_date_equals,
    assert_instant_equals,
    assert_tranche_balances,
    assert_unit_balances,
)


def _package_with_active_appointment_awaiting_separation():
    """A twelve-month appointment encumbered, notice given, and the clock at the date."""
    scenario = fixtures.setup_base_package()
    appointment = fixtures.setup_active_staff_appointment(
        scenario["package_id"],
        appointment_type="LAB_MANAGER",
        fte=0.77,
        monthly_cost_cents=583_333,
        start_date="2026-09-01",
        end_date="2027-08-31",
    )
    fixtures.record_departure_notice(scenario["faculty_id"], "DEPARTURE", "2026-12-31")
    fixtures.set_clock("2026-12-31T00:00:00Z")
    return scenario, appointment


def test_separation_settles_the_package_and_ends_the_active_appointment():
    """The faculty transition drives the package settlement, which ends the appointment.

    PRD 3.9: "every StaffAppointment in ACTIVE moves to ENDED with an effective
    end_date of the clock, running exactly the same served-months and remainder
    arithmetic described in §3.8"

    Design: Difficulty/transitive_cascade/separation_depth_four_faculty_to_package_to_appointment_to_tranche_to_funder
    """
    scenario, appointment = _package_with_active_appointment_awaiting_separation()

    faculty = fixtures.separate_faculty(scenario["faculty_id"])
    assert faculty["appointment_status"] == "DEPARTED"
    assert_instant_equals(faculty["separated_on"], "2026-12-31T00:00:00Z")

    package = fixtures.read_package(scenario["package_id"])
    assert package["spend_status"] == "SETTLED"
    assert package["negotiation_status"] == "CLOSED_OUT"

    ended = fixtures.read_appointment(appointment["id"])
    assert ended["status"] == "ENDED"
    # PRD 3.9 pins the *effective* end_date used by the arithmetic to the clock, and the
    # served-months figure below is what proves it ran against 2026-12-31 (four served
    # months of the twelve committed). PRD never says the stored end_date field is
    # overwritten, and PRD 3.8's clamp against committed_months requires that the
    # original schedule survive, so the stored value is deliberately not asserted here.
    assert ended["disbursed_cents"] == 1_796_664
    assert ended["encumbered_cents"] == 0


def test_separation_drains_every_tranche_of_the_package():
    """The released encumbrance is disbursed for the served months and the rest recaptured.

    PRD 3.9: "In both variants RECAPTURE rows drain each such tranche to 0 and move
    it to RECAPTURED, split across the three original funders by the ordinary rule
    of §2.7, so the department, the college and the dean's office each recover
    exactly their own money."

    Design: Difficulty/transitive_cascade/separation_depth_four_faculty_to_package_to_appointment_to_tranche_to_funder
    """
    scenario, _ = _package_with_active_appointment_awaiting_separation()

    fixtures.separate_faculty(scenario["faculty_id"])

    personnel = fixtures.read_tranche(scenario["tranche"]["personnel"]["id"])
    assert_tranche_balances(personnel, status="RECAPTURED", disbursed_cents=1_796_664,
                            encumbered_cents=0, recaptured_cents=7_803_336,
                            available_balance_cents=0)

    for key in ("equipment_capped", "equipment_next_year"):
        tranche = fixtures.read_tranche(scenario["tranche"][key]["id"])
        assert tranche["status"] == "RECAPTURED"


def test_separation_leaves_only_the_disbursed_share_reserved_on_each_funder():
    """The terminal hop lands each funder unit's pool arithmetic on the disbursed share.

    PRD 2.8: "reserved_cents - the sum of this unit's largest-remainder share of
    total_committed_cents over every startup package with negotiation_status of
    APPROVED, ACTIVE or CLOSED_OUT that names this unit, minus this unit's share of
    every EXPIRY and every RECAPTURE ledger row."

    Design: Difficulty/transitive_cascade/separation_depth_four_faculty_to_package_to_appointment_to_tranche_to_funder
    """
    scenario, _ = _package_with_active_appointment_awaiting_separation()

    fixtures.separate_faculty(scenario["faculty_id"])

    assert_unit_balances(fixtures.read_unit(scenario["department_id"]), committed_cents=0,
                         disbursed_cents=808_499, refunded_cents=31_591_501,
                         reserved_cents=808_499)
    assert_unit_balances(fixtures.read_unit(scenario["college_id"]), committed_cents=0,
                         disbursed_cents=628_832, refunded_cents=24_571_168,
                         reserved_cents=628_832)
    assert_unit_balances(fixtures.read_unit(scenario["dean_office_id"]), committed_cents=0,
                         disbursed_cents=359_333, refunded_cents=14_040_667,
                         reserved_cents=359_333)

    package = fixtures.read_package(scenario["package_id"])
    assert package["recaptured_unspent_cents"] == 70_203_336
    assert package["total_disbursed_cents"] == 1_796_664
    assert (package["recaptured_unspent_cents"] + package["total_disbursed_cents"]
            == 72_000_000)
    assert package["transferred_balance_cents"] == 0
    assert package["college_holdback_cents"] == 0


SINGLE_PHASE = [
    {
        "sequence_no": 1,
        "name": "Finishes",
        "planned_start": "2026-08-10T00:00:00Z",
        "planned_end": "2026-09-30T00:00:00Z",
        "budget_cents": 10_000_000,
    },
]


def _cosmetic_project_awaiting_substantial_completion():
    """A cosmetic project finished 1,000,000 cents under its award, room still closed."""
    scenario = fixtures.setup_base_package()
    space = fixtures.create_lab_space(building_code="CHEM", room_number="212",
                                      space_class="WET")
    assignment = fixtures.propose_space_assignment(space, scenario["faculty_id"])
    project, phases = fixtures.setup_awarded_project(
        scenario["package_id"], space["id"], 10_000_000, scenario["headers"]["dean"],
        phase_specs=SINGLE_PHASE,
        project_overrides={"scope_tier": "COSMETIC", "estimate_cents": 10_000_000},
    )
    fixtures.start_phase(project["id"], phases[0]["id"])
    fixtures.complete_phase(project["id"], phases[0]["id"], 9_000_000)
    return scenario, space, assignment, project


def test_substantial_completion_reconciles_an_underrun_against_the_estimate():
    """An underrun releases the surplus and reports a negative cost variance.

    PRD 3.6: "Finally, cost_variance_cents is package_charge_final_cents less
    package_charge_estimate_cents, and a positive variance means the package absorbs
    more than it encumbered."

    Design: Difficulty/transitive_cascade/substantial_completion_depth_three_project_to_space_to_assignment
    """
    scenario, space, assignment, project = _cosmetic_project_awaiting_substantial_completion()

    assert fixtures.read_space(space["id"])["status"] == "UNDER_RENOVATION"
    assert fixtures.read_assignment(assignment["id"])["status"] == "PROPOSED"

    completed = fixtures.substantial_completion(project["id"])
    assert completed["status"] == "COMPLETED"
    assert completed["actual_total_cents"] == 9_000_000
    assert completed["subsidy_final_cents"] == 0
    assert completed["package_charge_final_cents"] == 9_000_000
    assert completed["cost_variance_cents"] == -1_000_000


def test_substantial_completion_reopens_the_room_and_promotes_its_proposed_assignment():
    """The room's return to service promotes the in-window proposal without a client call.

    PRD 3.6: "The room finally moves UNDER_RENOVATION to ASSIGNED, and every PROPOSED
    assignment on that room whose half-open window contains the clock is promoted to
    ACTIVE, with allocated_share_pct re-derived."

    Design: Difficulty/transitive_cascade/substantial_completion_depth_three_project_to_space_to_assignment
    """
    scenario, space, assignment, project = _cosmetic_project_awaiting_substantial_completion()

    fixtures.substantial_completion(project["id"])

    room = fixtures.read_space(space["id"])
    assert room["status"] == "ASSIGNED"
    assert room["allocated_share_pct"] == 100
    assert fixtures.read_assignment(assignment["id"])["status"] == "ACTIVE"


def test_substantial_completion_settles_the_renovation_ledger_chain():
    """The settlement disburses the actual cost and clears every funder's exposure.

    PRD 3.6: "First, the award's ENCUMBRANCE rows are settled: per tranche, a
    DISBURSEMENT row for the lesser of package_charge_final_cents and
    package_charge_estimate_cents, and a RELEASE row for any unspent remainder, each
    mirroring the stored split of the row it reverses under the settlement rule of
    §2.7"

    Design: Difficulty/transitive_cascade/substantial_completion_depth_three_project_to_space_to_assignment
    """
    scenario, _, _, project = _cosmetic_project_awaiting_substantial_completion()

    fixtures.substantial_completion(project["id"])

    assert_tranche_balances(fixtures.read_tranche(scenario["tranche"]["renovation"]["id"]),
                            encumbered_cents=0, disbursed_cents=9_000_000,
                            available_balance_cents=3_000_000)

    assert_unit_balances(fixtures.read_unit(scenario["department_id"]),
                         disbursed_cents=4_050_000, committed_cents=0)
    assert_unit_balances(fixtures.read_unit(scenario["college_id"]),
                         disbursed_cents=3_150_000, committed_cents=0)
    assert_unit_balances(fixtures.read_unit(scenario["dean_office_id"]),
                         disbursed_cents=1_800_000, committed_cents=0)
