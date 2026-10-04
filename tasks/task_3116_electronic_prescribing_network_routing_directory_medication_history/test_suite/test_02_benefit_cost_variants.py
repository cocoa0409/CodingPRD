"""Benefit and formulary estimates: the provisional variant at the point of prescribing and
the final variant at fill time.

Both variants share a pinned evaluation order; they part company only on whether the brand
fee sits inside the basis the deductible credit is measured against, which moves the split
between patient and plan while leaving the sum unchanged.
"""
from test_helpers import (
    validate_success,
    set_clock,
    create_clinic,
    create_pharmacy,
    certify_participant,
    add_endpoint,
    create_payer,
    create_patient,
    grant_consent,
    create_prescription,
    open_benefit_check,
    reload_participant,
    make_pharmacy_headers,
    api_client,
)


def _priced_check():
    """A non-controlled NEW_RX order on the 2022011 standard, with an open benefit check
    against a payer plan whose deductible already stands at 4000 of 10000, and a patient
    holding an ACTIVE BOTH-scope consent."""
    set_clock()
    payer = create_payer()

    clinic = create_clinic()
    add_endpoint(
        clinic["id"], service_set="NEW_RX", endpoint_role="SENDER", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    clinic = certify_participant(clinic["id"])

    pharmacy = create_pharmacy()
    add_endpoint(
        pharmacy["id"], service_set="NEW_RX", endpoint_role="BOTH", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    pharmacy = certify_participant(pharmacy["id"])

    patient = create_patient(covered_plan_payer_id=payer["id"])
    grant_consent(patient["id"], scope="BOTH", duration_days=365)

    prescription = create_prescription(
        clinic["id"], pharmacy["id"], patient["id"], controlled_schedule="NON_CONTROLLED",
        message_standard="NCPDP_SCRIPT_2022011",
    )
    check = open_benefit_check(
        prescription["id"], payer["id"], clinic["id"], benchmark_price_cents=8000
    )
    return {
        "clinic": clinic, "pharmacy": pharmacy, "payer": payer,
        "patient": patient, "prescription": prescription, "check": check,
    }


def test_provisional_and_final_variants_split_the_same_total_differently(api):
    """PRD §3.9: "Under `PROVISIONAL` the credit is 3100 and the estimate splits patient
    3100 against plan 5200; under `FINAL` the credit is 3400 and the estimate splits patient
    3400 against plan 4900."
    PRD §3.9: "The split moves 300 cents from the plan to the patient while the sum stays at
    8300 in both variants."

    Design: Difficulty/dual_variant_calc/benefit_cost_estimate_dual_variant_on_benefit_check
    """
    ctx = _priced_check()
    check = ctx["check"]
    pharmacy_headers = make_pharmacy_headers(ctx["pharmacy"]["id"])

    assert check["deductible_met_snapshot_cents"] == 4000

    provisional = validate_success(
        api_client.evaluate_benefit_check(check["id"], pharmacy_headers), 200
    )
    assert provisional["pricing_variant"] == "PROVISIONAL"
    assert provisional["estimated_patient_pay_cents"] == 3100
    assert provisional["estimated_plan_pay_cents"] == 5200

    final = validate_success(
        api_client.complete_benefit_check(check["id"], pharmacy_headers), 200
    )
    assert final["pricing_variant"] == "FINAL"
    assert final["estimated_patient_pay_cents"] == 3400
    assert final["estimated_plan_pay_cents"] == 4900

    assert (
        provisional["estimated_patient_pay_cents"] + provisional["estimated_plan_pay_cents"]
        == final["estimated_patient_pay_cents"] + final["estimated_plan_pay_cents"]
        == 8300
    )


def test_settlement_advances_the_payer_deductible_by_the_final_variants_credit(api):
    """PRD §3.9: "Settlement at fill time sets `pricing_variant` `FINAL` and `check_status`
    `COMPLETE`, produces the final estimate, and advances the payer's
    `plan_deductible_met_cents` by the final variant's credit, saturating at
    `plan_deductible_cents`; settlement belongs exclusively to a `Pharmacy`."

    Design: Difficulty/dual_variant_calc/benefit_cost_estimate_dual_variant_on_benefit_check
    """
    ctx = _priced_check()
    check = ctx["check"]
    payer = ctx["payer"]
    pharmacy_headers = make_pharmacy_headers(ctx["pharmacy"]["id"])

    validate_success(api_client.evaluate_benefit_check(check["id"], pharmacy_headers), 200)
    before = reload_participant(payer["id"])
    assert before["plan_deductible_met_cents"] == 4000, (
        "the provisional evaluation does not advance the payer's deductible"
    )

    validate_success(api_client.complete_benefit_check(check["id"], pharmacy_headers), 200)

    after = reload_participant(payer["id"])
    # The final variant's credit is min(10000 - 4000, 3100 + 300) == 3400.
    assert after["plan_deductible_met_cents"] == 7400
    assert after["plan_deductible_met_cents"] <= after["plan_deductible_cents"]