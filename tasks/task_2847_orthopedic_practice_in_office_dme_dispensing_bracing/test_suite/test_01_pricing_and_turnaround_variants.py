"""Two calculations that each answer differently depending on which of two
declared bases the request lands on: patient responsibility under the
insurance-assigned versus the cash self-pay variant, and the fabrication
turnaround score on the promised-delivery basis versus the elapsed basis.
"""

from test_helpers import (
    assert_encounter_states,
    assert_instant_equals,
    assert_money,
    assert_responsibility,
    build_practice,
    read_supplier,
    set_clock,
)
from test_helpers import factories as f


def test_insurance_assigned_responsibility_is_half_the_allowed_amount(api):
    """A covered encounter with no deductible and half coinsurance splits the
    allowed amount evenly between the patient and the payer.

    PRD: "The coinsurance base is the allowed total less whatever the deductible
    bucket took, and the coinsurance line is that base multiplied by the
    verification's `coinsurance_pct`, rounded half up to a whole cent on its own."

    Design: Difficulty/dual_variant_calc/patient_responsibility_insurance_vs_abn_cash_variant_divergence
    """
    practice = build_practice(api)
    encounter_id = practice.fitted_encounter(
        coverage={"covered": True, "deductible_remaining_cents": 0, "coinsurance_pct": 0.5}
    )

    delivered = practice.dispense(encounter_id)

    assert delivered["covered_units"] == 1
    assert_responsibility(
        delivered,
        patient_responsibility_cents=10300,
        billable_amount_cents=10300,
        responsibility_variant="INSURANCE_ASSIGNED",
    )
    assert_encounter_states(delivered, clinical_status="DELIVERED", financial_status="BILLED")


def test_cash_self_pay_responsibility_comes_from_the_signed_notice(api):
    """With no coverable unit the same device is priced from the beneficiary
    notice's cash quote instead of the payer's allowed amount, and the payer's
    share collapses to nothing.

    PRD: "Under `ABN_CASH_SELFPAY` — which applies when `covered_units` is 0,
    whether because the verification says not covered or because authorization
    approved zero coverable units — there is no insurance line at all."

    Design: Difficulty/dual_variant_calc/patient_responsibility_insurance_vs_abn_cash_variant_divergence
    """
    practice = build_practice(api)
    encounter_id = practice.verified_encounter(coverage={"covered": False})

    notice = practice.issue_abn(encounter_id)
    assert_money(notice, "unit_net_price_cents", 11765)
    assert_money(notice, "estimated_subtotal_cents", 11765)
    assert_money(notice, "dispensing_fee_cents", 2500)
    assert_money(notice, "estimated_cost_cents", 14265)
    practice.sign_abn(notice["id"], option="OPTION_1")

    practice.reserve(encounter_id)
    practice.fit(encounter_id)
    delivered = practice.dispense(encounter_id)

    assert delivered["covered_units"] == 0
    assert_responsibility(
        delivered,
        patient_responsibility_cents=14265,
        billable_amount_cents=0,
        responsibility_variant="ABN_CASH_SELFPAY",
    )
    assert_encounter_states(delivered, clinical_status="DELIVERED", financial_status="BILLED")


def test_projected_turnaround_score_is_measured_against_the_promised_days(api):
    """The projected score is stamped at the first delivery and penalises only
    the days by which that shipment overran the supplier's promise.

    PRD: "The **projected** figure, written at first delivery, measures
    `first_delivery_days` as the whole days from `submitted_at` to
    `first_delivered_at`, floored; its lateness is that count less the promised
    days, or 0 when the count does not exceed the promise; and
    `projected_turnaround_score` is 100 less 4 points per late day, floored at 0."

    Design: Difficulty/dual_variant_calc/supplier_turnaround_promised_basis_vs_elapsed_basis_divergence
    """
    practice = build_practice(
        api, product_factory=f.custom_afo_product_payload, with_shelf=False
    )
    encounter_id = practice.documented_encounter()
    order = practice.place_fab_order(encounter_id)
    assert order["status"] == "SUBMITTED"
    assert order["promised_turnaround_days_snapshot"] == 10

    practice.fabrication_event(order["id"], "ACCEPT_ORDER")
    set_clock(api, "2026-08-14T00:00:00Z")
    delivered = practice.fabrication_event(order["id"], "DELIVER_TO_CLINIC")

    assert delivered["status"] == "READY_FOR_FITTING"
    assert delivered["first_delivery_days"] == 13
    assert delivered["projected_turnaround_score"] == 88
    assert delivered["final_turnaround_score"] is None
    assert_instant_equals(delivered["first_delivered_at"], "2026-08-14T00:00:00Z")
    assert read_supplier(api, practice.supplier_id)["turnaround_score"] == 100


def test_final_turnaround_score_adds_the_rework_penalty_on_the_elapsed_basis(api):
    """The final score is measured over the whole elapsed interval, including the
    rework round, and carries a further penalty for that round; the first
    delivery stamp is left where it was.

    PRD: "The **final** figure, written at acceptance, measures
    `total_elapsed_days` as the whole days from `submitted_at` to `accepted_at`,
    floored — an interval that includes every rework round — computes its
    lateness the same way, and sets `final_turnaround_score` to 100 less 4 points
    per late day less a further 6 points per adjustment round recorded in
    `adjustment_rounds`, again floored at 0."

    Design: Difficulty/dual_variant_calc/supplier_turnaround_promised_basis_vs_elapsed_basis_divergence
    """
    practice = build_practice(
        api, product_factory=f.custom_afo_product_payload, with_shelf=False
    )
    encounter_id = practice.documented_encounter()
    order_id = practice.place_fab_order(encounter_id)["id"]

    practice.fabrication_event(order_id, "ACCEPT_ORDER")
    set_clock(api, "2026-08-14T00:00:00Z")
    practice.fabrication_event(order_id, "DELIVER_TO_CLINIC")
    practice.fitting_check(order_id, "REQUEST_ADJUSTMENT", note="medial trimline rubs")
    practice.fabrication_event(order_id, "ACCEPT_ORDER")
    set_clock(api, "2026-08-20T00:00:00Z")
    redelivered = practice.fabrication_event(order_id, "DELIVER_TO_CLINIC")
    assert_instant_equals(redelivered["first_delivered_at"], "2026-08-14T00:00:00Z")
    assert redelivered["first_delivery_days"] == 13
    assert redelivered["projected_turnaround_score"] == 88

    set_clock(api, "2026-08-22T00:00:00Z")
    accepted = practice.fitting_check(order_id, "ACCEPT")

    assert accepted["status"] == "ACCEPTED"
    assert accepted["adjustment_rounds"] == 1
    assert accepted["total_elapsed_days"] == 21
    assert accepted["final_turnaround_score"] == 50
    assert accepted["projected_turnaround_score"] == 88
    assert_instant_equals(accepted["first_delivered_at"], "2026-08-14T00:00:00Z")

    supplier = read_supplier(api, practice.supplier_id)
    assert supplier["accepted_fab_order_count"] == 1
    assert supplier["turnaround_score"] == 50
