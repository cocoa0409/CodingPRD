"""Difficulty queue: transitive cascades — appeal ADJUSTED depth-3 chain and
the settlement-execution depth-2 chain."""
from test_helpers import (
    api_client, validate_success, validate_paginated, get_success_data,
    setup_priced_claim, open_case, place_offer, counter_case,
    find_settlement_for_case,
)


def _setup_appeal_under_review(ref="I1", patient=5000):
    """Priced claim + appeal moved SUBMITTED -> UNDER_REVIEW."""
    env = setup_priced_claim(claim_overrides={"external_claim_ref": ref,
                                              "patient_responsibility_cents": patient})
    appeal = get_success_data(api_client.create_appeal(
        env["claim"]["id"],
        {"determination_id": env["determination"]["id"],
         "appeal_reason": "units miscounted"},
        env["ctx"]["provider_rep"]))
    get_success_data(api_client.start_review_appeal(appeal["id"],
                                                    env["ctx"]["payer_rep"]))
    env["appeal"] = appeal
    return env


def test_appeal_adjusted_creates_superseding_determination():
    """PRD §3.8: "An `outcome` of adjusted requires `adjusted_amount_cents`
    greater than zero and no more than the claim's `billed_amount_cents`, moves
    the appeal to `RE_REVIEWED_ADJUSTED`, and fires a three-hop cascade: a new
    `RepricingDetermination` is created with the methodology copied from the
    appealed determination, superseding the previously active one; the prior
    determination's status flips to `SUPERSEDED`; and the claim's
    `allowed_amount_cents`, `payer_liability_cents`, and `savings_cents` are
    recomputed from the adjusted amount with the claim's `version`
    incrementing."

    Design: Difficulty/transitive_cascade/appeal_adjusted_cascades_determination_supersede_and_claim_recompute
    """
    env = _setup_appeal_under_review()
    ctx = env["ctx"]
    resolved = validate_success(api_client.resolve_appeal(
        env["appeal"]["id"],
        {"outcome": "ADJUSTED", "adjusted_amount_cents": 44000},
        ctx["payer_rep"]), 200)
    assert resolved["status"] == "RE_REVIEWED_ADJUSTED"

    dets, _ = validate_paginated(
        api_client.list_claim_determinations(env["claim"]["id"], ctx["payer_rep"]))
    assert len(dets) == 2
    active = [d for d in dets if d["status"] == "ACTIVE"]
    superseded = [d for d in dets if d["status"] == "SUPERSEDED"]
    assert len(active) == 1 and len(superseded) == 1
    assert active[0]["supersedes_determination_id"] == env["determination"]["id"]
    assert superseded[0]["id"] == env["determination"]["id"]
    assert active[0]["methodology"] == "PERCENT_OF_MEDICARE"


def test_appeal_adjusted_recomputes_claim_amounts():
    """PRD §3.8: "the claim's `allowed_amount_cents`, `payer_liability_cents`,
    and `savings_cents` are recomputed from the adjusted amount with the claim's
    `version` incrementing."
    PRD §3.8: "The claim itself remains in `PRICED` through an adjusted
    re-review — the appeal re-prices in place rather than moving the claim
    through a visible status change."

    Design: Difficulty/transitive_cascade/appeal_adjusted_cascades_determination_supersede_and_claim_recompute
    """
    env = _setup_appeal_under_review(ref="I2")
    ctx = env["ctx"]
    before = validate_success(api_client.get_claim(env["claim"]["id"],
                                                   ctx["payer_rep"]), 200)
    validate_success(api_client.resolve_appeal(
        env["appeal"]["id"],
        {"outcome": "ADJUSTED", "adjusted_amount_cents": 44000},
        ctx["payer_rep"]), 200)
    after = validate_success(api_client.get_claim(env["claim"]["id"],
                                                  ctx["payer_rep"]), 200)
    assert after["status"] == "PRICED"
    assert after["allowed_amount_cents"] == 44000
    assert after["payer_liability_cents"] == 44000 - 5000
    assert after["savings_cents"] == 60000 - 44000 + 5000
    assert after["version"] == before["version"] + 1


def _setup_signed_by_payer(ref="J1"):
    """Case accepted by provider at payer offer 40000; settlement payer-signed."""
    env = setup_priced_claim(claim_overrides={"external_claim_ref": ref,
                                              "patient_responsibility_cents": 0})
    case = open_case(env["claim"]["id"], env["ctx"])
    get_success_data(place_offer(case["id"], 40000, case["version"], env["ctx"]))
    get_success_data(api_client.accept_negotiation_case(
        case["id"], env["ctx"]["provider_rep"]))
    settlement = find_settlement_for_case(case["id"], env["ctx"])
    get_success_data(api_client.sign_settlement_agreement(
        settlement["id"], env["ctx"]["payer_rep"]))
    env["case"] = case
    env["settlement"] = settlement
    return env


def test_second_signature_executes_and_settles_claim():
    """PRD §3.6: "The second signature — which requires the other party to have
    already signed and the underlying claim not yet `FINALIZED` — moves the
    agreement to `EXECUTED`. Execution sets `balance_billing_prohibited` true
    (patient responsibility stays exactly as recorded on the claim) and fires
    two cascades: first the claim transitions `PRICED` to `SETTLED`, its
    `allowed_amount_cents` is replaced by the agreement's `settled_amount_cents`
    with `payer_liability_cents` and `savings_cents` recomputed from the new
    allowed amount, and a new `RepricingDetermination` with `methodology`
    `NEGOTIATED` and `policy_id` null is created superseding the previously
    active determination; second, the parent `NegotiationCase` transitions
    `ACCEPTED` to `SETTLED` as the cascade's next hop."

    Design: Difficulty/transitive_cascade/settlement_execution_cascades_claim_settled_then_case_settled
    """
    env = _setup_signed_by_payer()
    executed = validate_success(api_client.sign_settlement_agreement(
        env["settlement"]["id"], env["ctx"]["provider_rep"]), 200)
    assert executed["status"] == "EXECUTED"
    assert executed["balance_billing_prohibited"] is True

    claim = validate_success(api_client.get_claim(
        env["claim"]["id"], env["ctx"]["payer_rep"]), 200)
    assert claim["status"] == "SETTLED"
    assert claim["allowed_amount_cents"] == 40000

    case = validate_success(api_client.get_negotiation_case(
        env["case"]["id"], env["ctx"]["payer_rep"]), 200)
    assert case["status"] == "SETTLED"


def test_second_signature_writes_negotiated_determination():
    """PRD §3.6: "a new `RepricingDetermination` with `methodology` `NEGOTIATED`
    and `policy_id` null is created superseding the previously active
    determination"
    PRD §2.9: "Determinations created through negotiation carry `methodology`
    `NEGOTIATED` with `policy_id` null"

    Design: Difficulty/transitive_cascade/settlement_execution_cascades_claim_settled_then_case_settled
    """
    env = _setup_signed_by_payer(ref="J2")
    validate_success(api_client.sign_settlement_agreement(
        env["settlement"]["id"], env["ctx"]["provider_rep"]), 200)
    dets, _ = validate_paginated(api_client.list_claim_determinations(
        env["claim"]["id"], env["ctx"]["payer_rep"]))
    assert len(dets) == 2
    active = [d for d in dets if d["status"] == "ACTIVE"]
    assert len(active) == 1
    assert active[0]["methodology"] == "NEGOTIATED"
    assert active[0]["policy_id"] is None
