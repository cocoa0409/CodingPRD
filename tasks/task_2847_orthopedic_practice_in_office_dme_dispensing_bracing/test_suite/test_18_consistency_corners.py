"""Derived state is never allowed to lag the write that produced it.

The receipt's own response already carries the recomputed shelf, and the
reservation — whose response is an encounter and therefore shows none of the
shelf numbers it moved — must leave the shelf and the computed clinic summary
correct for the very next request, with no settling step in between.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    CLINICAL_DELIVERED,
    CLINICAL_RESERVED,
    DISPENSING_ACTIVE,
    FINANCIAL_BILLED,
    FINANCIAL_VERIFIED,
    POSTURE_OK,
    POSTURE_STOCKOUT,
    assert_clinic_posture,
    assert_encounter_states,
    assert_money,
    assert_responsibility,
    assert_shelf,
    assert_unit_ledger_balances,
    build_practice,
    inventory_manager_headers,
    read_clinic,
    read_shelf,
    read_summary,
)
from test_helpers import factories as f


def test_a_write_and_the_read_that_follows_it_agree_on_every_derived_field(api):
    """A never-stocked shelf is a stockout that does not count against the clinic; the
    receipt's own body shows the recomputed posture; the reservation's body shows only
    the encounter, yet the shelf and the clinic summary read straight afterwards are
    already correct; and the dispense response carries its own money while the summary
    reconciles in the same request cycle.

    PRD: "This recomputation runs on every mutation of either `on_hand_qty` or
    `reserved_qty` — shelf creation, stock receipt, reservation, reservation release,
    dispense consumption and restocked return — and it consults only the single shelf
    being mutated, never a sibling shelf of the same clinic or the same product."

    PRD: "Computed read reconciling the clinic's unit ledger and cash ledger; every
    field is derived on demand and none is stored."

    Design: Corner/consistency_model/corner_immediate_consistency_of_derived_state_within_the_writing_response
    """
    practice = build_practice(
        api, par_level={"par_min_qty": 2, "par_max_qty": 20}, received_qty=None
    )
    shelf_created = read_shelf(api, practice.par_level_id)
    assert_shelf(
        shelf_created,
        on_hand_qty=0,
        reserved_qty=0,
        available_qty=0,
        stock_posture=POSTURE_STOCKOUT,
        lifetime_received_qty=0,
        version=1,
    )
    # A shelf that has never carried stock is a stockout the clinic does not count.
    assert_clinic_posture(
        read_clinic(api, practice.clinic_id),
        dispensing_status=DISPENSING_ACTIVE,
        stockout_par_level_count=0,
    )

    encounter_id = practice.verified_encounter(
        coverage={"covered": True, "deductible_remaining_cents": 0, "coinsurance_pct": 0.5}
    )

    # The receipt's own response is already recomputed: no second read is needed.
    receipt = validate_success(
        api.receive_stock(
            practice.par_level_id, f.stock_receipt_payload(4), inventory_manager_headers()
        ),
        201,
    )
    assert_shelf(
        receipt,
        on_hand_qty=4,
        reserved_qty=0,
        available_qty=4,
        stock_posture=POSTURE_OK,
        lifetime_received_qty=4,
        version=2,
    )
    assert_clinic_posture(
        read_clinic(api, practice.clinic_id),
        dispensing_status=DISPENSING_ACTIVE,
        stockout_par_level_count=0,
    )
    after_receipt = read_summary(api, practice.clinic_id)
    assert after_receipt["units_received_total"] == 4
    assert after_receipt["units_on_hand_total"] == 4
    assert after_receipt["units_accounted_total"] == 4
    assert_unit_ledger_balances(after_receipt)

    # The reservation answers with an encounter and shows no shelf numbers at all.
    reserved = validate_success(
        api.create_reservation(
            encounter_id, f.reservation_payload(receipt["version"]), practice.fitter_headers
        ),
        201,
    )
    assert_encounter_states(
        reserved, clinical_status=CLINICAL_RESERVED, financial_status=FINANCIAL_VERIFIED
    )
    assert reserved["id"] == encounter_id
    assert reserved["quantity"] == 1

    # The shelf read issued immediately afterwards is already correct.
    assert_shelf(
        read_shelf(api, practice.par_level_id),
        on_hand_qty=4,
        reserved_qty=1,
        available_qty=3,
        stock_posture=POSTURE_OK,
        version=3,
    )
    after_reservation = read_summary(api, practice.clinic_id)
    assert after_reservation["units_reserved_total"] == 1
    assert after_reservation["units_on_hand_total"] == 4
    assert after_reservation["units_dispensed_total"] == 0
    assert_unit_ledger_balances(after_reservation)

    practice.fit(encounter_id)
    delivered = practice.dispense(encounter_id)

    assert_encounter_states(
        delivered, clinical_status=CLINICAL_DELIVERED, financial_status=FINANCIAL_BILLED
    )
    assert_responsibility(
        delivered, patient_responsibility_cents=10300, billable_amount_cents=10300
    )

    after_dispense = read_summary(api, practice.clinic_id)
    assert after_dispense["units_on_hand_total"] == 3
    assert after_dispense["units_reserved_total"] == 0
    assert after_dispense["units_dispensed_total"] == 1
    assert after_dispense["units_accounted_total"] == 4
    assert_unit_ledger_balances(after_dispense)
    assert_money(after_dispense, "gross_charged_cents", 10300)
    assert_money(after_dispense, "net_cash_position_cents", 10300)
