"""Difficulty queue: compensating invariants — payer aggregate fees conserved
across issue/void, and the negotiation offer ledger preserved across
accept+void."""
from test_helpers import (
    api_client, validate_success, get_success_data,
    create_payer, create_provider, create_medicare_entry, create_policy,
    create_claim, add_line, reprice, issue_invoice,
    setup_priced_claim, open_case, place_offer, counter_case,
    find_settlement_for_case,
    create_claim_payload, create_claim_line_payload,
    create_medicare_entry_payload, create_repricing_policy_payload,
    make_payer_admin_headers, make_payer_rep_headers,
    TEST_USERS,
)

OPS = TEST_USERS["ops_admin_headers"]


def _setup_two_finalized_claims():
    """
    Claim S: billed 60000, allowed 33000, patient 5000 -> savings 32000
             -> raw fee min(20000,32000)*0.25 + 12000*0.20 = 7400 -> capped 5000.
    Claim T: billed 20000, allowed 15000, patient 0 -> savings 5000 -> fee 1250.
    """
    payer = create_payer(transparency_reporting_enabled=True)
    provider = create_provider(npi="1000000021")
    create_medicare_entry(procedure_code="99283", region_code="R1")
    create_medicare_entry(procedure_code="99285", region_code="R1",
                          base_rate_cents=10000, geographic_adjustment_factor=1.00)
    ctx = {
        "payer_admin": make_payer_admin_headers(payer["id"]),
        "payer_rep": make_payer_rep_headers(payer["id"]),
    }
    create_policy(payer, ctx)

    claim_s = create_claim(payer, provider, ctx, external_claim_ref="S1",
                           patient_responsibility_cents=5000)
    add_line(claim_s["id"], ctx)
    get_success_data(reprice(claim_s["id"], claim_s["version"] + 1, ctx))
    get_success_data(api_client.finalize_claim(claim_s["id"], ctx["payer_rep"]))

    claim_t = create_claim(payer, provider, ctx, external_claim_ref="T1",
                           patient_responsibility_cents=0)
    add_line(claim_t["id"], ctx, procedure_code="99285", quantity_units=1,
             unit_charge_cents=20000)
    get_success_data(reprice(claim_t["id"], claim_t["version"] + 1, ctx))
    get_success_data(api_client.finalize_claim(claim_t["id"], ctx["payer_rep"]))
    return payer, provider, ctx, claim_s, claim_t


def test_tiered_fee_math_and_cap_on_issue():
    """PRD §3.9: "On issue, the per-claim fee is computed by a tiered waterfall
    over the claim's `savings_cents`: the first 20000 cents of savings are
    charged at 0.25, any savings beyond the first 20000 cents are charged at
    0.20, the sum of the two tier amounts is rounded half-up to whole cents per
    claim, and that rounded figure is capped at the payer's
    `fee_cap_cents_per_claim`."
    PRD §3.9: "The invoice's `gross_fee_cents` is the sum of the per-claim fees,
    and `aggregate_fee_cents` — the running sum of `gross_fee_cents` across all
    non-voided invoices of the same payer — is recomputed on every issue."

    Design: Difficulty/compensating_invariant/settle_and_void_invoice_leave_aggregate_fees_unchanged
    """
    payer, provider, ctx, claim_s, claim_t = _setup_two_finalized_claims()
    fi1 = issue_invoice(payer["id"], [claim_s["id"]])
    assert fi1["gross_fee_cents"] == 5000, (
        "savings 32000 -> raw 7400 capped at fee_cap 5000")
    assert fi1["aggregate_fee_cents"] == 5000

    fi2 = issue_invoice(payer["id"], [claim_t["id"]])
    assert fi2["gross_fee_cents"] == 1250, "savings 5000 x 0.25"
    assert fi2["aggregate_fee_cents"] == 6250


def test_void_restores_aggregate_to_pre_issue_value():
    """PRD §3.9: "Issued invoices can later be voided, moving them to `VOIDED`;
    voiding does not delete any transparency report already published, and
    voiding recomputes `aggregate_fee_cents` across the payer's remaining
    non-voided invoices."
    PRD §3.9: "`aggregate_fee_cents` — the running sum of `gross_fee_cents`
    across all non-voided invoices of the same payer"

    Design: Difficulty/compensating_invariant/settle_and_void_invoice_leave_aggregate_fees_unchanged
    """
    payer, provider, ctx, claim_s, claim_t = _setup_two_finalized_claims()
    fi1 = issue_invoice(payer["id"], [claim_s["id"]])
    fi2 = issue_invoice(payer["id"], [claim_t["id"]])
    assert fi2["aggregate_fee_cents"] == 6250

    voided = validate_success(api_client.void_fee_invoice(fi2["id"], OPS), 200)
    assert voided["status"] == "VOIDED"
    fi1_after = validate_success(api_client.get_fee_invoice(fi1["id"], OPS), 200)
    assert fi1_after["gross_fee_cents"] == 5000
    assert fi1_after["aggregate_fee_cents"] == 5000, (
        "aggregate must return to the FI1-only value after FI2 is voided")


def test_settlement_void_preserves_offer_ledger():
    """PRD §3.6: "voiding moves the agreement to `VOIDED` and, as the
    compensating action, reverts the `NegotiationCase` from `ACCEPTED` back to
    `COUNTERED` with `current_offer_cents` unchanged."
    PRD §3.5: "A valid counter moves the case from `OFFER_PENDING` to
    `COUNTERED`, sets `current_offer_cents` to the counter, and increments
    `round_count`."

    Design: Difficulty/compensating_invariant/settlement_void_preserves_current_offer_quantity
    """
    env = setup_priced_claim(claim_overrides={"external_claim_ref": "U1",
                                              "patient_responsibility_cents": 0},
                             npi="1000000022")
    case = open_case(env["claim"]["id"], env["ctx"])
    get_success_data(place_offer(case["id"], 30000, case["version"], env["ctx"]))
    get_success_data(counter_case(case["id"], 50000, env["ctx"]))
    get_success_data(api_client.accept_negotiation_case(
        case["id"], env["ctx"]["payer_rep"]))
    settlement = find_settlement_for_case(case["id"], env["ctx"])

    validate_success(api_client.void_settlement_agreement(
        settlement["id"], env["ctx"]["payer_rep"]), 200)
    case_after = validate_success(api_client.get_negotiation_case(
        case["id"], env["ctx"]["payer_rep"]), 200)
    assert case_after["status"] == "COUNTERED"
    assert case_after["current_offer_cents"] == 50000
    assert case_after["round_count"] == 1


def test_settlement_void_leaves_claim_priced():
    """PRD §3.6: "If no signature has been recorded yet, a `PayerRep` may void
    the agreement instead: voiding moves the agreement to `VOIDED` and, as the
    compensating action, reverts the `NegotiationCase` from `ACCEPTED` back to
    `COUNTERED` with `current_offer_cents` unchanged."
    PRD §3.6: "The second signature — which requires the other party to have
    already signed and the underlying claim not yet `FINALIZED` — moves the
    agreement to `EXECUTED`."

    Design: Difficulty/compensating_invariant/settlement_void_preserves_current_offer_quantity
    """
    env = setup_priced_claim(claim_overrides={"external_claim_ref": "U2",
                                              "patient_responsibility_cents": 0},
                             npi="1000000023")
    case = open_case(env["claim"]["id"], env["ctx"])
    get_success_data(place_offer(case["id"], 30000, case["version"], env["ctx"]))
    get_success_data(counter_case(case["id"], 50000, env["ctx"]))
    get_success_data(api_client.accept_negotiation_case(
        case["id"], env["ctx"]["payer_rep"]))
    settlement = find_settlement_for_case(case["id"], env["ctx"])

    validate_success(api_client.void_settlement_agreement(
        settlement["id"], env["ctx"]["payer_rep"]), 200)
    claim = validate_success(api_client.get_claim(
        env["claim"]["id"], env["ctx"]["payer_rep"]), 200)
    assert claim["status"] == "PRICED", "no settle cascade may fire on void"
    assert claim["allowed_amount_cents"] == 33000
