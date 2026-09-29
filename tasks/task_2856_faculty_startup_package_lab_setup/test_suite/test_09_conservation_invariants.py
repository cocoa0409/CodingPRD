"""Unwinds that must conserve cents exactly: an order cancellation and an early end."""

from test_helpers import fixtures
from test_helpers.assertions import (
    assert_balance_identity_for_all,
    assert_instant_equals,
    assert_row_amount_and_shares,
    assert_spend_down_ratio,
    assert_tranche_balances,
    assert_unit_balances,
    rows_for_source,
    rows_of_kind,
)

AWKWARD_QUOTE_CENTS = 12_345_679


def _placed_order_with_an_awkward_quote():
    """An order whose quote splits into fractional cents for all three funders."""
    scenario = fixtures.setup_base_package()
    space = fixtures.create_lab_space(building_code="BIO", room_number="230",
                                      space_class="DRY")
    order = fixtures.setup_placed_order(scenario["package_id"], space["id"],
                                        quoted_cents=AWKWARD_QUOTE_CENTS)
    return scenario, order


def test_an_awkward_quote_encumbers_with_the_largest_remainder_split():
    """The two leftover cents go to the largest fractional parts, not to a fixed funder.

    PRD 2.7: "Distribute the remainder by the largest fractional part first rule:
    sort the three funders by the discarded fractional part of their exact product
    in descending order, breaking any tie by the fixed funder ordering department,
    then college, then dean's office — never by identifier and never by creation
    timestamp — and give one extra cent to each of the first *remainder* funders in
    that order."

    Design: Difficulty/compensating_invariant/order_cancel_restores_tranche_budget_identity_with_no_drift
    """
    scenario, order = _placed_order_with_an_awkward_quote()

    rows = rows_of_kind(rows_for_source(fixtures.read_ledger(scenario["package_id"]),
                                        order["id"]), "ENCUMBRANCE")
    assert len(rows) == 1
    assert_row_amount_and_shares(rows[0], AWKWARD_QUOTE_CENTS, 5_555_555, 4_320_988,
                                 2_469_136)

    assert_tranche_balances(fixtures.read_tranche(scenario["tranche"]["equipment_capped"]["id"]),
                            encumbered_cents=AWKWARD_QUOTE_CENTS,
                            available_balance_cents=12_654_321)


def test_cancelling_the_order_releases_the_stored_shares_verbatim():
    """The release copies the encumbrance's own shares rather than re-splitting.

    PRD 2.7: "A RELEASE or DISBURSEMENT row that settles the *whole* of an open
    encumbrance copies, verbatim, the stored dept_share_cents, college_share_cents
    and dean_share_cents of the ENCUMBRANCE row it names in
    reverses_transaction_id."

    Design: Difficulty/compensating_invariant/order_cancel_restores_tranche_budget_identity_with_no_drift
    """
    scenario, order = _placed_order_with_an_awkward_quote()
    encumbrance = rows_of_kind(rows_for_source(fixtures.read_ledger(scenario["package_id"]),
                                               order["id"]), "ENCUMBRANCE")[0]

    cancelled = fixtures.cancel_order(order["id"])
    assert cancelled["status"] == "CANCELLED"

    releases = rows_of_kind(rows_for_source(fixtures.read_ledger(scenario["package_id"]),
                                            order["id"]), "RELEASE")
    assert len(releases) == 1
    assert releases[0]["reverses_transaction_id"] == encumbrance["id"]
    assert_row_amount_and_shares(releases[0], AWKWARD_QUOTE_CENTS, 5_555_555, 4_320_988,
                                 2_469_136)


def test_cancelling_the_order_restores_every_balance_without_a_cent_of_drift():
    """The cancellation leaves the tranche, the pools and the package exactly as before.

    PRD 2.9: "Equivalently, available_balance_cents is amount_cents plus
    carried_in_cents, less encumbered_cents, disbursed_cents, carried_out_cents,
    expired_cents and recaptured_cents."

    Design: Difficulty/compensating_invariant/order_cancel_restores_tranche_budget_identity_with_no_drift
    """
    scenario, order = _placed_order_with_an_awkward_quote()
    fixtures.cancel_order(order["id"])

    assert_tranche_balances(fixtures.read_tranche(scenario["tranche"]["equipment_capped"]["id"]),
                            encumbered_cents=0, disbursed_cents=0,
                            available_balance_cents=25_000_000)
    assert_tranche_balances(fixtures.read_tranche(scenario["tranche"]["equipment_full"]["id"]),
                            encumbered_cents=0, available_balance_cents=15_000_000)
    assert_balance_identity_for_all(fixtures.read_package_tranches(scenario["package_id"]))

    assert_unit_balances(fixtures.read_unit(scenario["department_id"]), committed_cents=0,
                         disbursed_cents=0, refunded_cents=0, reserved_cents=32_400_000)
    assert_unit_balances(fixtures.read_unit(scenario["college_id"]), committed_cents=0,
                         disbursed_cents=0, refunded_cents=0, reserved_cents=25_200_000)
    assert_unit_balances(fixtures.read_unit(scenario["dean_office_id"]), committed_cents=0,
                         disbursed_cents=0, refunded_cents=0, reserved_cents=14_400_000)

    package = fixtures.read_package(scenario["package_id"])
    assert package["total_encumbered_cents"] == 0
    assert package["total_available_cents"] == 72_000_000
    assert package["total_disbursed_cents"] == 0


def _active_appointment_to_be_ended_early():
    """A twelve-month lab manager priced so the monthly charge has a fractional cent."""
    scenario = fixtures.setup_base_package()
    appointment = fixtures.setup_active_staff_appointment(
        scenario["package_id"], appointment_type="LAB_MANAGER", fte=0.77,
        monthly_cost_cents=583_333, start_date="2026-09-01", end_date="2027-08-31",
    )
    assert appointment["encumbered_cents"] == 5_389_992
    return scenario, appointment


def test_an_early_end_disburses_the_served_months_and_releases_the_remainder():
    """Three served months are disbursed and the unserved nine are released.

    PRD 3.8: "The amount disbursed is the monthly charge multiplied by the months served,
    and the amount released is the encumbrance total less the amount disbursed."

    Design: Difficulty/compensating_invariant/appointment_early_end_conserves_committed_equals_encumbered_across_funders
    """
    scenario, appointment = _active_appointment_to_be_ended_early()

    ended = fixtures.end_staff_appointment(appointment["id"], "2026-11-30")
    assert ended["status"] == "ENDED"
    assert ended["encumbered_cents"] == 0
    assert_instant_equals(ended["ended_on"], "2026-08-01T00:00:00Z")

    rows = rows_for_source(fixtures.read_ledger(scenario["package_id"]), appointment["id"])
    disbursements = rows_of_kind(rows, "DISBURSEMENT")
    releases = rows_of_kind(rows, "RELEASE")
    assert len(disbursements) == 1
    assert len(releases) == 1
    assert_row_amount_and_shares(disbursements[0], 1_347_498, 606_374, 471_624, 269_500)


def test_the_paired_release_takes_the_per_funder_remainder_not_a_fresh_split():
    """Each release share is the encumbrance share minus the disbursed share, exactly.

    PRD 2.7: "then derives the paired RELEASE row's three shares as the per-funder
    arithmetic remainder: the stored encumbrance share minus the disbursed share."

    Design: Difficulty/compensating_invariant/appointment_early_end_conserves_committed_equals_encumbered_across_funders
    """
    scenario, appointment = _active_appointment_to_be_ended_early()
    encumbrance = rows_of_kind(rows_for_source(fixtures.read_ledger(scenario["package_id"]),
                                               appointment["id"]), "ENCUMBRANCE")[0]
    assert_row_amount_and_shares(encumbrance, 5_389_992, 2_425_497, 1_886_497, 1_077_998)

    fixtures.end_staff_appointment(appointment["id"], "2026-11-30")

    rows = rows_for_source(fixtures.read_ledger(scenario["package_id"]), appointment["id"])
    disbursement = rows_of_kind(rows, "DISBURSEMENT")[0]
    release = rows_of_kind(rows, "RELEASE")[0]
    assert_row_amount_and_shares(release, 4_042_494, 1_819_123, 1_414_873, 808_498)

    for field in ("dept_share_cents", "college_share_cents", "dean_share_cents"):
        assert disbursement[field] + release[field] == encumbrance[field]


def test_the_early_end_leaves_the_pools_and_the_package_conserved():
    """Every funder's committed exposure closes out into disbursed cents exactly.

    PRD 3.8: "Each funding unit's committed_cents falls and its disbursed_cents rises by
    the stored shares."

    Design: Difficulty/compensating_invariant/appointment_early_end_conserves_committed_equals_encumbered_across_funders
    """
    scenario, appointment = _active_appointment_to_be_ended_early()
    fixtures.end_staff_appointment(appointment["id"], "2026-11-30")

    assert_tranche_balances(fixtures.read_tranche(scenario["tranche"]["personnel"]["id"]),
                            encumbered_cents=0, disbursed_cents=1_347_498,
                            available_balance_cents=8_252_502)

    assert_unit_balances(fixtures.read_unit(scenario["department_id"]), committed_cents=0,
                         disbursed_cents=606_374)
    assert_unit_balances(fixtures.read_unit(scenario["college_id"]), committed_cents=0,
                         disbursed_cents=471_624)
    assert_unit_balances(fixtures.read_unit(scenario["dean_office_id"]), committed_cents=0,
                         disbursed_cents=269_500)

    package = fixtures.read_package(scenario["package_id"])
    assert package["total_disbursed_cents"] == 1_347_498
    assert package["total_available_cents"] == 70_652_502
    assert_spend_down_ratio(package["spend_down_ratio"], 0.0187)
