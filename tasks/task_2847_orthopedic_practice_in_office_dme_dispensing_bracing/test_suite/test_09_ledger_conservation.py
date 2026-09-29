"""Two ledgers a clinic must keep balanced no matter which path a device took:
the unit ledger, walked through reservation, release, dispense and restock, and
the cash ledger, walked through two returns that refund different amounts.
"""

from test_helpers import (
    add_patient,
    assert_clinic_posture,
    assert_money_fields,
    assert_shelf,
    assert_unit_ledger_balances,
    build_practice,
    read_clinic,
    read_encounter,
    read_shelf,
    read_summary,
)

COVERED = {"covered": True, "deductible_remaining_cents": 0, "coinsurance_pct": 0.5}


def test_a_released_reservation_leaves_every_unit_total_where_it_started(api):
    """Holding two units for an encounter moves them into the reserved column
    without leaving the on-hand column, and a rejected fitting hands them back
    with the ledger untouched.

    PRD: "`units_on_hand_total` sums `on_hand_qty` and `units_reserved_total` sums
    `reserved_qty`; reserved units are a **subset** of units on hand, held for
    named encounters but still physically present, and must never be added to the
    on-hand figure."

    Design: Difficulty/compensating_invariant/unit_ledger_conserved_across_reservation_release_dispense_and_restock
    """
    practice = build_practice(api)
    encounter_id = practice.reserved_encounter(quantity=2, coverage=COVERED)

    held = read_summary(api, practice.clinic_id)
    assert held["units_received_total"] == 10
    assert held["units_on_hand_total"] == 10
    assert held["units_reserved_total"] == 2
    assert held["units_dispensed_total"] == 0
    assert held["units_accounted_total"] == 10
    assert_unit_ledger_balances(held)

    practice.fit(
        encounter_id,
        start_at="2026-08-01T10:00:00Z",
        end_at="2026-08-01T10:30:00Z",
        outcome="REJECTED",
        adjustment_note="shell too narrow through the trochanter",
    )

    released = read_summary(api, practice.clinic_id)
    assert released["units_reserved_total"] == 0
    assert released["units_on_hand_total"] == 10
    assert released["units_dispensed_total"] == 0
    assert released["units_accounted_total"] == 10
    assert_unit_ledger_balances(released)
    assert read_encounter(api, encounter_id)["clinical_status"] == "DOCUMENTED"


def test_a_dispense_and_then_a_restock_return_the_units_to_the_shelf(api):
    """Dispensing moves two units out of the on-hand column and into the dispensed
    column, and a sellable return puts them back without ever changing what the
    clinic received.

    PRD: "`units_accounted_total` is then `units_on_hand_total` plus
    `units_dispensed_total` less `units_restocked_total`."

    Design: Difficulty/compensating_invariant/unit_ledger_conserved_across_reservation_release_dispense_and_restock
    """
    practice = build_practice(api)
    encounter_id = practice.reserved_encounter(quantity=2, coverage=COVERED)
    practice.fit(
        encounter_id, start_at="2026-08-01T11:00:00Z", end_at="2026-08-01T11:30:00Z"
    )
    practice.dispense(encounter_id)

    dispensed = read_summary(api, practice.clinic_id)
    assert dispensed["units_on_hand_total"] == 8
    assert dispensed["units_reserved_total"] == 0
    assert dispensed["units_dispensed_total"] == 2
    assert dispensed["units_restocked_total"] == 0
    assert dispensed["units_accounted_total"] == 10
    assert_unit_ledger_balances(dispensed)

    product_return = practice.open_return(encounter_id, reason="DEFECT")
    inspected = practice.inspect_return(product_return["id"], condition="SELLABLE")
    assert inspected["status"] == "RESTOCKED"
    assert inspected["restock_eligible"] is True
    assert inspected["quantity_returned"] == 2

    restocked = read_summary(api, practice.clinic_id)
    assert restocked["units_received_total"] == 10
    assert restocked["units_on_hand_total"] == 10
    assert restocked["units_dispensed_total"] == 2
    assert restocked["units_restocked_total"] == 2
    assert restocked["units_destroyed_total"] == 0
    assert restocked["units_accounted_total"] == 10
    assert_unit_ledger_balances(restocked)
    assert_shelf(
        read_shelf(api, practice.par_level_id),
        on_hand_qty=10,
        reserved_qty=0,
        stock_posture="OK",
    )
    assert_clinic_posture(
        read_clinic(api, practice.clinic_id), stockout_par_level_count=0
    )


def _two_billed_encounters(api):
    """One clinic with two separately billed single-unit encounters, each charging
    the patient the same covered share."""
    practice = build_practice(api)
    second_patient = add_patient(practice, full_name="Joel Pike")
    first = practice.delivered_encounter(
        coverage=COVERED, start_at="2026-08-01T09:00:00Z", end_at="2026-08-01T09:30:00Z"
    )
    second = practice.delivered_encounter(
        coverage=COVERED,
        patient_id=second_patient["id"],
        start_at="2026-08-01T11:00:00Z",
        end_at="2026-08-01T11:30:00Z",
    )
    for encounter_id in (first, second):
        assert read_encounter(api, encounter_id)["patient_responsibility_cents"] == 10300
    return practice, first, second


def test_a_full_refund_moves_cash_out_without_erasing_what_was_charged(api):
    """A defective device is refunded to the cent, and the amount originally
    charged stays on the gross line while the net position falls to nothing.

    PRD: "`gross_charged_cents` sums `patient_responsibility_cents` over the
    clinic's encounters in `BILLED` or `REFUNDED` — a refund does **not** remove an
    encounter from this total, because `patient_responsibility_cents` records what
    was charged and is never zeroed; only `billable_amount_cents` is zeroed on
    refund."

    Design: Difficulty/compensating_invariant/cash_ledger_conserved_as_refund_plus_restock_fee_across_two_returns
    """
    practice, first, _second = _two_billed_encounters(api)

    billed = read_summary(api, practice.clinic_id)
    assert_money_fields(
        billed,
        gross_charged_cents=20600,
        refunded_cents=0,
        restock_fee_retained_cents=0,
        net_cash_position_cents=20600,
    )

    product_return = practice.open_return(first, reason="DEFECT")
    inspected = practice.inspect_return(product_return["id"], condition="SELLABLE")

    assert_money_fields(
        inspected,
        device_component_cents=8755,
        fitting_component_cents=1545,
        device_refund_cents=8755,
        fitting_refund_cents=1545,
        refund_cents=10300,
        restock_fee_cents=0,
    )
    refunded_encounter = read_encounter(api, first)
    assert refunded_encounter["financial_status"] == "REFUNDED"
    assert refunded_encounter["patient_responsibility_cents"] == 10300
    assert refunded_encounter["billable_amount_cents"] == 0

    after = read_summary(api, practice.clinic_id)
    assert_money_fields(
        after,
        gross_charged_cents=20600,
        refunded_cents=10300,
        restock_fee_retained_cents=0,
        net_cash_position_cents=10300,
    )


def test_once_both_encounters_are_returned_the_net_position_is_exactly_the_fees(api):
    """A second return that carries a restock fee leaves the practice holding only
    that fee, because every refund and fee together reconstruct what was charged.

    PRD: "Because every inspected return satisfies `refund_cents` plus
    `restock_fee_cents` equalling the source encounter's
    `patient_responsibility_cents` exactly, the cash ledger reconciles by
    construction: once every billed encounter at a clinic has been returned and
    inspected, `net_cash_position_cents` equals `restock_fee_retained_cents` to the
    cent, and the only cash the practice has retained is the fees it charged."

    Design: Difficulty/compensating_invariant/cash_ledger_conserved_as_refund_plus_restock_fee_across_two_returns
    """
    practice, first, second = _two_billed_encounters(api)

    free_return = practice.open_return(first, reason="DEFECT")
    practice.inspect_return(free_return["id"], condition="SELLABLE")
    charged_return = practice.open_return(second, reason="POOR_FIT")
    charged = practice.inspect_return(charged_return["id"], condition="SELLABLE")

    assert_money_fields(
        charged,
        device_component_cents=8755,
        fitting_component_cents=1545,
        device_refund_cents=7880,
        fitting_refund_cents=1468,
        refund_cents=9348,
        restock_fee_cents=952,
    )
    assert charged["refund_cents"] + charged["restock_fee_cents"] == 10300

    summary = read_summary(api, practice.clinic_id)
    assert_money_fields(
        summary,
        gross_charged_cents=20600,
        refunded_cents=19648,
        restock_fee_retained_cents=952,
        net_cash_position_cents=952,
    )
    assert summary["net_cash_position_cents"] == summary["restock_fee_retained_cents"]
    for encounter_id in (first, second):
        encounter = read_encounter(api, encounter_id)
        assert encounter["financial_status"] == "REFUNDED"
        assert encounter["billable_amount_cents"] == 0
