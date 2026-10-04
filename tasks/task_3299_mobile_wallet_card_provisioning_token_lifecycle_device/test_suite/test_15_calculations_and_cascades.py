"""Corner: conditional cascade, risk ledger sync, fee boundary/precision,
risk cap saturation."""
from test_helpers import (
    ADMIN,
    DESK,
    OPERATOR,
    approved_authorization,
    create_dispute_payload,
    get_success_data,
    make_cardholder_headers,
    provision_second_token,
    reset_clock,
    setup_cardholder,
    setup_device,
    setup_issuer_active,
    setup_provisioned_token,
    validate_paginated,
)


def test_issuer_suspend_cascade_suspends_only_active_tokens(api):
    """PRD section 3.7: "Suspending an ACTIVE issuer — ACTIVE -> SUSPENDED —
    cascades: every ACTIVE payment token with that issuer_id moves to
    SUSPENDED, each with suspension_count incremented and a SUSPENSION event
    appended." An already-DEACTIVATED token on the same issuer is untouched.

    Design: Corner/state_machines/issuer_suspend_cascade_suspends_only_active_tokens
    """
    ns = setup_provisioned_token(api)
    token2 = provision_second_token(api, ns)
    ch = make_cardholder_headers(ns["cardholder"]["id"])
    get_success_data(api.deactivate_token(ns["device"]["id"], token2["id"], ch))
    get_success_data(api.suspend_issuer(ns["issuer"]["id"], ADMIN))
    t1 = get_success_data(api.get_payment_token(ns["token"]["id"]))
    t2 = get_success_data(api.get_payment_token(token2["id"]))
    assert t1["status"] == "SUSPENDED"
    assert t2["status"] == "DEACTIVATED"
    assert t2["suspension_count"] == 0


def test_dispute_open_recomputes_risk_open_disputed_cents(api):
    """PRD section 3.7: "The system tracks open exposure per account as
    total_disputed_cents — the sum of amount_cents over disputes in OPEN
    status traced to that account". The account risk read returns
    "risk_score, open_dispute_count, and open_disputed_cents" and reflects the
    new dispute immediately.

    Design: Corner/state_machines/dispute_open_recomputes_risk_open_disputed_cents
    """
    ns = setup_provisioned_token(api)
    auth = approved_authorization(api, ns["token"], amount_cents=7000,
                                  cryptogram="cgm-8")
    get_success_data(
        api.open_dispute(auth["id"], create_dispute_payload(
            7000, reason="GOODS_NOT_RECEIVED"), DESK)
    )
    risk = get_success_data(api.get_account_risk(ns["account"]["id"], DESK))
    assert risk["open_disputed_cents"] == 7000
    assert risk["open_dispute_count"] == 1


def test_issuer_fee_floor_applies_at_boundary_below_and_above(api):
    """PRD section 3.6: "the raw fee is the amount_cents multiplied by the
    agreement's fee_bps and divided by 10000 with floor division (truncation
    toward zero); the result is then capped from above by fee_cap_cents (the
    smaller of the raw fee and the cap is kept), and finally floored from below
    by fee_floor_cents (the larger of the capped value and the floor is kept)."
    With fee_bps 100, cap 900, floor 50: 4999 -> 50 (raw 49 below floor),
    5000 -> 50 (raw equals floor), 5100 -> 51. Approved total == 151.

    Design: Corner/calculations/issuer_fee_floor_applies_at_boundary_below_and_above
    """
    ns = setup_provisioned_token(api, fee_bps=100, fee_cap_cents=900,
                                 fee_floor_cents=50, express_supported=False,
                                 card_product="CREDIT")
    approved_authorization(api, ns["token"], amount_cents=4999, cryptogram="c1")
    approved_authorization(api, ns["token"], amount_cents=5000, cryptogram="c2",
                           merchant_id="m-2")
    approved_authorization(api, ns["token"], amount_cents=5100, cryptogram="c3",
                           merchant_id="m-3")
    proj = get_success_data(api.get_fee_projection(ns["issuer"]["id"], OPERATOR))
    assert proj["approved_fee_cents"] == 151
    assert proj["authorization_count"] == 3


def test_risk_score_capped_at_100_with_open_dispute_bonuses(api):
    """PRD section 3.7: "The score is computed as: four points per decline
    accumulated by tokens of the account that currently carry an OPEN dispute;
    plus one point per decline accumulated by the account's other tokens; plus
    a flat 15-point bonus for each OPEN dispute on the account; plus a flat
    25-point bonus if any device bound to the account's tokens is currently
    reported lost. The result is capped at 100 and can never go below zero."
    Four OPEN disputes + lost device = 4*15+25 = 85; a fifth OPEN dispute
    saturates the cap at exactly 100.

    Design: Corner/calculations/risk_score_capped_at_100_with_open_dispute_bonuses
    """
    ns = setup_provisioned_token(api)
    ch = make_cardholder_headers(ns["cardholder"]["id"])
    auths = []
    for i in range(5):
        auths.append(approved_authorization(
            api, ns["token"], amount_cents=1000 * (i + 1),
            cryptogram=f"ok{i+1}", merchant_id=f"m-{i+1}"))
    reasons = ["UNRECOGNIZED", "DUPLICATE", "GOODS_NOT_RECEIVED", "UNRECOGNIZED"]
    for i in range(4):
        get_success_data(api.open_dispute(
            auths[i]["id"], create_dispute_payload(1000 * (i + 1), reason=reasons[i]), ch))
    get_success_data(api.report_device_lost(ns["device"]["id"], ch))
    risk = get_success_data(api.get_account_risk(ns["account"]["id"], DESK))
    assert risk["risk_score"] == 85, f"expected 85, got {risk['risk_score']}"
    get_success_data(api.open_dispute(
        auths[4]["id"], create_dispute_payload(5000, reason="DUPLICATE"), DESK))
    risk = get_success_data(api.get_account_risk(ns["account"]["id"], DESK))
    assert risk["risk_score"] == 100, f"expected cap 100, got {risk['risk_score']}"


def test_fee_projection_precision_is_floor_division(api):
    """PRD section 2.8: "Fee computation uses floor division — the raw fee is
    the amount multiplied by the agreement's basis-point rate and divided by
    ten thousand, truncated toward zero — and rounding-half-up is never used
    anywhere in fee accrual or projection." Amount 999 at 150 bps yields
    floor(14.985) == 14, not 15.

    Design: Corner/calculations/fee_projection_precision_is_floor_division_integer_cents
    """
    ns = setup_provisioned_token(api, card_product="CREDIT")
    approved_authorization(api, ns["token"], amount_cents=999, cryptogram="cgm-p")
    proj = get_success_data(api.get_fee_projection(ns["issuer"]["id"], OPERATOR))
    assert proj["approved_fee_cents"] == 14
