"""Cost allocation on a renovation project, and the two settlement variants."""

from test_helpers import fixtures
from test_helpers.assertions import (
    assert_tranche_balances,
    assert_unit_balances,
)

TWO_PHASES = [
    {
        "sequence_no": 1,
        "name": "Demolition",
        "planned_start": "2026-08-10T00:00:00Z",
        "planned_end": "2026-09-30T00:00:00Z",
        "budget_cents": 6_000_000,
    },
    {
        "sequence_no": 2,
        "name": "Casework install",
        "planned_start": "2026-10-02T00:00:00Z",
        "planned_end": "2026-11-30T00:00:00Z",
        "budget_cents": 6_000_000,
    },
]


def _awarded_moderate_project(scenario):
    """A MODERATE project of 12,000,000 cents on a fresh wet room, awarded in full."""
    space = fixtures.create_lab_space(building_code="CHEM", room_number="310",
                                      space_class="WET")
    project, phases = fixtures.setup_awarded_project(
        scenario["package_id"],
        space["id"],
        12_000_000,
        scenario["headers"]["dean"],
        phase_specs=TWO_PHASES,
        project_overrides={"scope_tier": "MODERATE", "estimate_cents": 12_000_000},
    )
    return space, project, phases


def _run_phases_to_completion(project_id, phases, actual_costs):
    for phase, actual_cost_cents in zip(phases, actual_costs):
        fixtures.start_phase(project_id, phase["id"])
        fixtures.complete_phase(project_id, phase["id"], actual_cost_cents)
    return fixtures.substantial_completion(project_id)


def test_moderate_award_stores_the_scope_estimate_allocation():
    """The award subsidises the awarded amount and encumbers the package's charge.

    PRD 3.6: "the subsidy percentage is 0 for a COSMETIC project, 25 for a MODERATE
    one and 40 for a GUT one."

    Design: Difficulty/dual_variant_calc/renovation_scope_estimate_vs_final_actual_divergence
    """
    scenario = fixtures.setup_base_package()
    space, project, _ = _awarded_moderate_project(scenario)

    assert project["subsidy_estimate_cents"] == 3_000_000
    assert project["package_charge_estimate_cents"] == 9_000_000

    tranche = fixtures.read_tranche(scenario["tranche"]["renovation"]["id"])
    assert_tranche_balances(tranche, encumbered_cents=9_000_000,
                            available_balance_cents=3_000_000)
    assert fixtures.read_space(space["id"])["status"] == "UNDER_RENOVATION"


def test_final_actual_allocation_diverges_from_the_scope_estimate():
    """An overrun beyond the tolerance charges the whole actual cost to the package.

    PRD 3.6: "package_charge_final_cents is actual_total_cents less
    subsidy_final_cents: the package is charged the whole actual cost, not the
    subsidisable portion."

    Design: Difficulty/dual_variant_calc/renovation_scope_estimate_vs_final_actual_divergence
    """
    scenario = fixtures.setup_base_package()
    _, project, phases = _awarded_moderate_project(scenario)

    completed = _run_phases_to_completion(project["id"], phases, [7_000_000, 6_500_000])

    assert completed["actual_total_cents"] == 13_500_000
    assert completed["subsidy_final_cents"] == 3_300_000
    assert completed["package_charge_final_cents"] == 10_200_000
    assert completed["cost_variance_cents"] == 1_200_000
    assert completed["subsidy_final_cents"] != completed["subsidy_estimate_cents"]
    assert completed["status"] == "COMPLETED"


def test_reconciliation_settles_the_award_and_charges_the_tolerated_overrun():
    """Reconciliation disburses the estimate and encumbers then disburses the overrun.

    PRD 3.6: "when cost_variance_cents is strictly greater than 0, a fresh waterfall
    pass encumbers the overrun and is immediately followed by a DISBURSEMENT of the
    same amount."

    Design: Difficulty/dual_variant_calc/renovation_scope_estimate_vs_final_actual_divergence
    """
    scenario = fixtures.setup_base_package()
    space, project, phases = _awarded_moderate_project(scenario)

    _run_phases_to_completion(project["id"], phases, [7_000_000, 6_500_000])

    tranche = fixtures.read_tranche(scenario["tranche"]["renovation"]["id"])
    assert_tranche_balances(tranche, disbursed_cents=10_200_000, encumbered_cents=0,
                            available_balance_cents=1_800_000)

    assert_unit_balances(fixtures.read_unit(scenario["department_id"]),
                         disbursed_cents=4_590_000, committed_cents=0)
    assert_unit_balances(fixtures.read_unit(scenario["college_id"]),
                         disbursed_cents=3_570_000, committed_cents=0)
    assert_unit_balances(fixtures.read_unit(scenario["dean_office_id"]),
                         disbursed_cents=2_040_000, committed_cents=0)

    assert fixtures.read_space(space["id"])["status"] == "ASSIGNED"


TWIN_TOTAL_CENTS = 24_000_003


def _twin_packages_awaiting_separation():
    """Two byte-identical packages, one resigning and one transferring internally."""
    units = fixtures.setup_mini_units()
    receiving_department = fixtures.create_sibling_department(units["college"]["id"])
    people = {}
    for key, intent, name in (
        ("departure", "DEPARTURE", "Ada Reyes"),
        ("transfer", "INTERNAL_TRANSFER", "Bo Nakamura"),
    ):
        faculty = fixtures.create_candidate_faculty(units["department"]["id"], full_name=name)
        package = fixtures.create_draft_package(
            faculty["id"], units["dean_office"]["id"],
            proposed_total_cents=TWIN_TOTAL_CENTS,
        )
        tranche = fixtures.add_tranche(package["id"], amount_cents=TWIN_TOTAL_CENTS)
        fixtures.negotiate_to_approved(package["id"], units)
        fixtures.activate_faculty(faculty["id"])
        fixtures.activate_package(package["id"])
        fixtures.record_departure_notice(
            faculty["id"], intent, "2026-09-01",
            target_funding_unit_id=receiving_department["id"] if intent == "INTERNAL_TRANSFER" else None,
        )
        people[key] = {"faculty": faculty, "package": package, "tranche": tranche}
    fixtures.set_clock("2026-09-01T00:00:00Z")
    return units, receiving_department, people


def test_departure_recapture_keeps_the_whole_unspent_balance_in_the_original_pools():
    """A plain resignation recaptures everything and transfers nothing.

    PRD 3.9: "all of it stays in the original pools: recaptured_unspent_cents is set
    to the whole unspent balance, and both transferred_balance_cents and
    college_holdback_cents are 0."

    Design: Difficulty/dual_variant_calc/separation_departure_recapture_vs_internal_transfer_divergence
    """
    _, _, people = _twin_packages_awaiting_separation()
    leaver = people["departure"]

    faculty = fixtures.separate_faculty(leaver["faculty"]["id"])
    assert faculty["appointment_status"] == "DEPARTED"

    package = fixtures.read_package(leaver["package"]["id"])
    assert package["settlement_variant"] == "DEPARTURE_RECAPTURE"
    assert package["recaptured_unspent_cents"] == TWIN_TOTAL_CENTS
    assert package["transferred_balance_cents"] == 0
    assert package["college_holdback_cents"] == 0

    assert_tranche_balances(fixtures.read_tranche(leaver["tranche"]["id"]),
                            status="RECAPTURED", recaptured_cents=TWIN_TOTAL_CENTS,
                            available_balance_cents=0)


def test_internal_transfer_holds_back_fifteen_percent_and_credits_the_receiving_unit():
    """An internal transfer keeps the holdback and moves the rest with the faculty member.

    PRD 3.9: "college_holdback_cents is the unspent balance multiplied by 15 percent,
    divided by 100 and rounded half up to whole cents; transferred_balance_cents is the
    unspent balance less that holdback, so the two always sum to the unspent balance
    exactly; and recaptured_unspent_cents is set to the holdback alone, not to the whole
    balance."

    Design: Difficulty/dual_variant_calc/separation_departure_recapture_vs_internal_transfer_divergence
    """
    _, receiving_department, people = _twin_packages_awaiting_separation()
    mover = people["transfer"]

    faculty = fixtures.separate_faculty(mover["faculty"]["id"])
    assert faculty["appointment_status"] == "TRANSFERRED_INTERNAL"

    package = fixtures.read_package(mover["package"]["id"])
    assert package["settlement_variant"] == "INTERNAL_TRANSFER"
    assert package["college_holdback_cents"] == 3_600_000
    assert package["transferred_balance_cents"] == 20_400_003
    assert package["recaptured_unspent_cents"] == 3_600_000
    assert (package["college_holdback_cents"] + package["transferred_balance_cents"]
            == TWIN_TOTAL_CENTS)

    credited = fixtures.read_unit(receiving_department["id"])
    assert credited["cost_share_pool_cents"] == 120_400_003


def test_both_settlement_variants_unwind_the_three_funder_pools_identically():
    """The recapture against the original funders is the same in both variants.

    PRD 3.9: "In both variants RECAPTURE rows drain each such tranche to 0 and move
    it to RECAPTURED, split across the three original funders by the ordinary rule
    of §2.7, so the department, the college and the dean's office each recover
    exactly their own money."

    Design: Difficulty/dual_variant_calc/separation_departure_recapture_vs_internal_transfer_divergence
    """
    units, _, people = _twin_packages_awaiting_separation()

    fixtures.separate_faculty(people["departure"]["faculty"]["id"])
    fixtures.separate_faculty(people["transfer"]["faculty"]["id"])

    leaver_package = fixtures.read_package(people["departure"]["package"]["id"])
    mover_package = fixtures.read_package(people["transfer"]["package"]["id"])
    assert (leaver_package["recaptured_unspent_cents"]
            != mover_package["recaptured_unspent_cents"])

    assert_unit_balances(fixtures.read_unit(units["department"]["id"]),
                         reserved_cents=0, refunded_cents=21_600_002)
    assert_unit_balances(fixtures.read_unit(units["college"]["id"]),
                         reserved_cents=0, refunded_cents=16_800_002)
    assert_unit_balances(fixtures.read_unit(units["dean_office"]["id"]),
                         reserved_cents=0, refunded_cents=9_600_002)
