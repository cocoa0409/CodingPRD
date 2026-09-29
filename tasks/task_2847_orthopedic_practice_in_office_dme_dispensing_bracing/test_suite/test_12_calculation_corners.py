"""How each derived figure treats a half cent, the order its buckets fill in,
which rows feed it, and whether it recounts or merely increments.
"""

from test_helpers import (
    assert_clinic_posture,
    assert_instant_equals,
    assert_money_fields,
    assert_responsibility,
    assert_shelf,
    build_practice,
    read_clinic,
    read_encounter,
    read_shelf,
    read_supplier,
    set_clock,
)
from test_helpers import factories as f


def test_a_coinsurance_line_of_exactly_half_a_cent_rounds_up_to_the_patient(api):
    """An odd allowed amount split evenly puts the half cent on the patient's side of
    the line, and the two shares still re-sum to the allowed amount exactly.

    PRD: "Wherever a monetary result would be fractional, the rounding method is
    **round half up** — a value exactly halfway between two whole cents rounds away
    from zero to the larger magnitude."

    Design: Corner/calculations/corner_coinsurance_half_cent_rounds_half_up_not_to_even
    """
    practice = build_practice(
        api, product={"allowed_amount_cents": 20601}, received_qty=6
    )
    encounter_id = practice.fitted_encounter(
        coverage={"covered": True, "deductible_remaining_cents": 0, "coinsurance_pct": 0.5}
    )

    delivered = practice.dispense(encounter_id)

    assert delivered["covered_units"] == 1
    assert_responsibility(
        delivered,
        patient_responsibility_cents=10301,
        billable_amount_cents=10300,
        responsibility_variant="INSURANCE_ASSIGNED",
    )
    assert (
        delivered["patient_responsibility_cents"] + delivered["billable_amount_cents"] == 20601
    )


def test_the_deductible_bucket_fills_before_coinsurance_is_applied(api):
    """With a deductible still outstanding, coinsurance is charged only on what the
    deductible did not absorb, which is a different number from charging coinsurance
    on the whole allowed amount.

    PRD: "The coinsurance base is the allowed total less whatever the deductible
    bucket took, and the coinsurance line is that base multiplied by the
    verification's `coinsurance_pct`, rounded half up to a whole cent on its own."

    Design: Corner/calculations/corner_patient_responsibility_fills_deductible_before_coinsurance
    """
    practice = build_practice(api, received_qty=6)
    encounter_id = practice.fitted_encounter(
        coverage={"covered": True, "deductible_remaining_cents": 8000, "coinsurance_pct": 0.2}
    )

    delivered = practice.dispense(encounter_id, signature_role="CAREGIVER")

    assert_responsibility(
        delivered,
        patient_responsibility_cents=10520,
        billable_amount_cents=10080,
        responsibility_variant="INSURANCE_ASSIGNED",
    )
    assert delivered["patient_responsibility_cents"] not in (12120, 4120)
    assert delivered["delivery_signature_role"] == "CAREGIVER"
    assert (
        delivered["patient_responsibility_cents"] + delivered["billable_amount_cents"] == 20600
    )


def test_a_returned_device_and_a_draft_sibling_are_both_outside_the_lookback(api):
    """Only a device the patient kept consumes the lifetime: after the first brace
    comes back and is restocked, a fresh verification for the same class reports no
    predecessor and succeeds, and a sibling draft is no candidate either.

    PRD: "The candidate set is every other dispensing encounter of the *same*
    patient whose `clinical_status` is `DELIVERED` and whose product shares this
    product's `same_or_similar_group`, gathered across every clinic of the practice."

    Design: Corner/calculations/corner_same_or_similar_lookback_ignores_returned_and_draft_encounters
    """
    practice = build_practice(api, received_qty=6)
    first_id = practice.reserved_encounter(
        coverage={"covered": True, "deductible_remaining_cents": 0, "coinsurance_pct": 0.5}
    )
    practice.fit(first_id, start_at="2026-08-01T09:00:00Z", end_at="2026-08-01T09:30:00Z")
    delivered = practice.dispense(first_id)
    assert_instant_equals(delivered["delivered_at"], "2026-08-01T00:00:00Z", "delivered_at")
    product_return = practice.open_return(first_id, reason="POOR_FIT")
    assert practice.inspect_return(product_return["id"])["status"] == "RESTOCKED"
    draft = practice.open_encounter()
    assert draft["clinical_status"] == "DRAFT"
    second_id = practice.documented_encounter()

    verification = practice.verify_coverage(
        second_id,
        covered=True,
        deductible_remaining_cents=0,
        coinsurance_pct=0.5,
        valid_for_days=30,
    )

    assert verification["same_or_similar_conflict"] is False
    assert verification["prior_delivered_encounter_id"] is None
    assert verification["prior_delivered_on"] is None
    assert verification["months_since_prior_delivery"] is None
    assert verification["verification_seq"] == 1
    assert read_encounter(api, second_id)["financial_status"] == "VERIFIED"
    assert read_encounter(api, first_id)["clinical_status"] == "RETURNED"


def test_the_supplier_average_moves_only_when_the_order_is_accepted(api):
    """A late order already carries its own projected score once it reaches the
    clinic, yet the supplier's reputation stays untouched until the fitter accepts
    the device.

    PRD: "Orders in `SUBMITTED`, `IN_FABRICATION`, `READY_FOR_FITTING`,
    `ADJUSTMENT_REQUESTED` and `CANCELLED` are excluded from both the count and the
    average — which means cancelling a badly late order removes it from the
    supplier's reputation entirely."

    Design: Corner/calculations/corner_supplier_turnaround_rollup_counts_only_accepted_orders
    """
    practice = build_practice(
        api, product_factory=f.custom_afo_product_payload, with_shelf=False
    )
    encounter_id = practice.documented_encounter()
    order = practice.place_fab_order(encounter_id)
    assert_instant_equals(order["submitted_at"], "2026-08-01T00:00:00Z", "submitted_at")
    previous = set_clock(api, "2026-08-21T00:00:00Z")
    assert_instant_equals(previous["previous_utc"], "2026-08-01T00:00:00Z", "previous_utc")

    accepted_order = practice.fabrication_event(order["id"], "ACCEPT_ORDER")
    delivered = practice.fabrication_event(order["id"], "DELIVER_TO_CLINIC")

    assert accepted_order["status"] == "IN_FABRICATION"
    assert delivered["status"] == "READY_FOR_FITTING"
    assert_instant_equals(delivered["first_delivered_at"], "2026-08-21T00:00:00Z")
    assert delivered["first_delivery_days"] == 20
    assert delivered["projected_turnaround_score"] == 60
    assert delivered["final_turnaround_score"] is None
    midway = read_supplier(api, practice.supplier_id)
    assert midway["turnaround_score"] == 100
    assert midway["accepted_fab_order_count"] == 0

    final = practice.fitting_check(order["id"], "ACCEPT")

    assert final["status"] == "ACCEPTED"
    assert_instant_equals(final["accepted_at"], "2026-08-21T00:00:00Z", "accepted_at")
    assert final["total_elapsed_days"] == 20
    assert final["adjustment_rounds"] == 0
    assert final["final_turnaround_score"] == 60
    rolled_up = read_supplier(api, practice.supplier_id)
    assert rolled_up["turnaround_score"] == 60
    assert rolled_up["accepted_fab_order_count"] == 1


def test_the_clinic_stockout_count_falls_back_to_zero_after_a_restock(api):
    """Draining the only stocked shelf restricts the clinic, and a restocked return
    drives the same aggregate back down in the very response that puts the unit
    back — which an implementation that only ever increments could not do.

    PRD: "The input is `stockout_par_level_count`, a **full recount** — not an
    increment — of that clinic's shelves whose `stock_posture` is `STOCKOUT` and
    whose `lifetime_received_qty` is greater than 0."

    Design: Corner/calculations/corner_clinic_stockout_count_reverses_after_restocked_return
    """
    practice = build_practice(api, par_level={"par_min_qty": 1}, received_qty=1)
    assert_shelf(
        practice.par_level, on_hand_qty=1, stock_posture="OK", lifetime_received_qty=1
    )
    assert_clinic_posture(
        read_clinic(api, practice.clinic_id),
        dispensing_status="ACTIVE",
        stockout_par_level_count=0,
    )
    encounter_id = practice.fitted_encounter(
        coverage={"covered": True, "deductible_remaining_cents": 0, "coinsurance_pct": 0.5}
    )

    delivered = practice.dispense(encounter_id)

    assert delivered["patient_responsibility_cents"] == 10300
    assert_shelf(
        read_shelf(api, practice.par_level_id),
        on_hand_qty=0,
        reserved_qty=0,
        stock_posture="STOCKOUT",
    )
    assert_clinic_posture(
        read_clinic(api, practice.clinic_id),
        dispensing_status="RESTRICTED",
        stockout_par_level_count=1,
    )

    product_return = practice.open_return(
        encounter_id, reason="POOR_FIT", return_note="medial edge digs in"
    )
    inspected = practice.inspect_return(product_return["id"], condition="SELLABLE")

    assert inspected["status"] == "RESTOCKED"
    assert_money_fields(inspected, refund_cents=9348, restock_fee_cents=952)
    assert_shelf(
        read_shelf(api, practice.par_level_id),
        on_hand_qty=1,
        stock_posture="OK",
        lifetime_received_qty=1,
    )
    assert_clinic_posture(
        read_clinic(api, practice.clinic_id),
        dispensing_status="ACTIVE",
        stockout_par_level_count=0,
    )
