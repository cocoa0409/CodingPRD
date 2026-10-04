"""Difficulty queue A: dual-variant warranty credit (pro-rata vs flat)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    setup_claim_in_data_review,
    validate_success,
)

WARRANTY = TEST_USERS["warranty_reviewer_headers"]


def _decide_approved(claim_id):
    return api_client.decide_warranty_claim(
        claim_id,
        {"decision": "APPROVED", "review_notes": "approved after data review"},
        WARRANTY,
    )


def test_warranty_credit_pro_rata_gen3_scales_by_unused_wear(api):
    """PRD §3.8: "On approval, `replacement_credit_cents` is computed. For
    products of generation 3 or later the pro-rata variant applies: the unused
    fraction of wear is the larger of zero and (the product's `wear_days` minus
    the wear-days-used figure) divided by `wear_days`, and the credit is the
    floor of (`list_price_cents` multiplied by that unused fraction)."
    PRD §3.8: "Note that the credit calculation uses the patient-reported day
    index plus one as the wear-days-used figure — the failure day itself counts"

    gen 3, list 8900c, wear 14, index 6 -> used 7 -> floor(8900 * 7/14) = 4450.

    Design: Difficulty/dual_variant_calc/warranty_credit_pro_rata_vs_flat_replacement
    """
    ctx = setup_claim_in_data_review(
        failure_day_index=6,
        product_overrides={"generation": 3, "list_price_cents": 8900, "wear_days": 14},
    )
    approved = validate_success(_decide_approved(ctx["claim"]["id"]))
    assert approved["status"] == "APPROVED"
    assert approved["replacement_credit_cents"] == 4450


def test_warranty_credit_flat_replacement_gen2_full_list_price(api):
    """PRD §3.8: "For products of generation 2 or earlier the flat-replacement
    variant applies: the credit is the full `list_price_cents` regardless of
    wear. Both variants return integer cents."

    gen 2, list 5000c, wear 14, index 6 -> credit 5000 (full list price),
    diverging from the pro-rata variant on identically-shaped claims.

    Design: Difficulty/dual_variant_calc/warranty_credit_pro_rata_vs_flat_replacement
    """
    ctx_gen3 = setup_claim_in_data_review(
        failure_day_index=6,
        product_overrides={"generation": 3, "list_price_cents": 8900, "wear_days": 14},
    )
    ctx_gen2 = setup_claim_in_data_review(
        failure_day_index=6,
        product_overrides={"generation": 2, "list_price_cents": 5000, "wear_days": 14},
    )
    approved_gen3 = validate_success(_decide_approved(ctx_gen3["claim"]["id"]))
    approved_gen2 = validate_success(_decide_approved(ctx_gen2["claim"]["id"]))
    assert approved_gen2["replacement_credit_cents"] == 5000
    assert approved_gen3["replacement_credit_cents"] != approved_gen2["replacement_credit_cents"]
