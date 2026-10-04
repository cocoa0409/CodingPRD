"""Aggregate risk score: weighted-sum evaluation order (queue A)."""
from test_helpers import (
    CRYPTOGRAM_DECLINE,
    OPERATOR,
    approved_authorization,
    authorize,
    create_dispute_payload,
    get_success_data,
    make_cardholder_headers,
    provision_second_token,
    setup_provisioned_token,
    validate_error,
)
from test_helpers import ApiErrorId


def _setup(api):
    ns = setup_provisioned_token(api)
    auth = approved_authorization(api, ns["token"], amount_cents=30000,
                                  cryptogram="cgm-ok")
    # PRD §3.7 gives 4 points per decline only to tokens that currently carry
    # an OPEN dispute. The assertion expects the disputed token to have zero
    # declines, so the two declines are accumulated on a second, undisputed
    # token of the same account (1 point each).
    token2 = provision_second_token(api, ns)
    # two declines (cryptogram literal DECLINE) — each increments decline_count
    get_success_data(authorize(api, token2, amount_cents=500,
                               cryptogram=CRYPTOGRAM_DECLINE, merchant_id="m-2"))
    get_success_data(authorize(api, token2, amount_cents=500,
                               cryptogram=CRYPTOGRAM_DECLINE, merchant_id="m-3"))
    ch = make_cardholder_headers(ns["cardholder"]["id"])
    get_success_data(
        api.open_dispute(auth["id"], create_dispute_payload(30000), ch)
    )
    get_success_data(api.report_device_lost(ns["device"]["id"], ch))
    return ns


def test_risk_weighted_sum_is_42(api):
    """PRD section 3.7: "The score is computed as: four points per decline
    accumulated by tokens of the account that currently carry an OPEN dispute;
    plus one point per decline accumulated by the account's other tokens; plus
    a flat 15-point bonus for each OPEN dispute on the account; plus a flat
    25-point bonus if any device bound to the account's tokens is currently
    reported lost." Here the disputed token has zero declines, the other-token
    term contributes 2 (two declines), one OPEN dispute adds 15, and the lost
    device adds 25: risk == 2*1 + 15 + 25 == 42.

    Design: Difficulty/combinatorial_formula/aggregate_risk_weighted_sum_evaluation_order_is_pinned
    """
    ns = _setup(api)
    risk = get_success_data(api.get_account_risk(ns["account"]["id"], OPERATOR))
    assert risk["risk_score"] == 42, (
        f"expected risk 42 (2 declines + 15 open-dispute + 25 lost), "
        f"got {risk['risk_score']}"
    )


def test_decline_counters_below_autosuspend_threshold(api):
    """PRD section 3.5: "When a token's consecutive_decline_count reaches 3 —
    the system's decline-streak threshold — the token auto-suspends." Two
    declines leave the token ACTIVE with decline_count 2 and
    consecutive_decline_count 2; only the later lost-device report suspends it.

    Design: Difficulty/combinatorial_formula/aggregate_risk_weighted_sum_evaluation_order_is_pinned
    """
    ns = _setup(api)
    token = get_success_data(api.get_payment_token(ns["token2"]["id"]))
    assert token["decline_count"] == 2
    assert token["consecutive_decline_count"] == 2
    # device lost report cascades suspension; the two declines alone did not
    assert token["suspension_count"] == 1
