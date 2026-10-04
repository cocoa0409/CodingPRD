"""Risk score provisional vs resolved variants (queue A dual_variant_calc)."""
from test_helpers import (
    OPERATOR,
    DESK,
    approved_authorization,
    create_dispute_payload,
    get_success_data,
    make_cardholder_headers,
    setup_provisioned_token,
)


def _setup_fraud_dispute(api, amount=25000):
    ns = setup_provisioned_token(api)
    auth = approved_authorization(api, ns["token"], amount_cents=amount,
                                  cryptogram="cgm-2", merchant_id="m-9")
    dispute = get_success_data(
        api.open_dispute(
            auth["id"], create_dispute_payload(amount, reason="FRAUD"), DESK
        )
    )
    ns["authorization"] = auth
    ns["dispute"] = dispute
    return ns


def test_open_fraud_dispute_risk_is_15_and_restricts_account(api):
    """PRD section 3.7: "plus a flat 15-point bonus for each OPEN dispute on
    the account" and "opening a FRAUD dispute has an immediate system effect:
    the funding CardAccount moves OPEN -> RESTRICTED". With zero declines and
    no lost device, the risk read returns exactly 15 while the dispute is OPEN.

    Design: Difficulty/dual_variant_calc/aggregate_risk_score_provisional_vs_resolved_variants_diverge
    """
    ns = _setup_fraud_dispute(api)
    risk = get_success_data(api.get_account_risk(ns["account"]["id"], DESK))
    assert risk["risk_score"] == 15, f"expected 15, got {risk['risk_score']}"
    account = get_success_data(api.get_card_account(ns["account"]["id"]))
    assert account["status"] == "RESTRICTED"


def test_resolved_fraud_dispute_risk_returns_to_zero(api):
    """PRD section 3.7: "either outcome of a FRAUD dispute flips the account
    back RESTRICTED -> OPEN" and the open-dispute bonus applies only to
    disputes in OPEN status. After resolving LOST, the same account's risk is
    0 — the resolved variant drops the 15-point bonus the provisional variant
    carried.

    Design: Difficulty/dual_variant_calc/aggregate_risk_score_provisional_vs_resolved_variants_diverge
    """
    ns = _setup_fraud_dispute(api)
    get_success_data(
        api.resolve_dispute(ns["dispute"]["id"], {"outcome": "LOST"}, OPERATOR)
    )
    risk = get_success_data(api.get_account_risk(ns["account"]["id"], DESK))
    assert risk["risk_score"] == 0, f"expected 0 after resolve, got {risk['risk_score']}"
    account = get_success_data(api.get_card_account(ns["account"]["id"]))
    assert account["status"] == "OPEN"
