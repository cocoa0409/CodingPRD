"""CardAccount OPEN<->RESTRICTED cycle driven by FRAUD disputes (queue A)."""
from test_helpers import (
    OPERATOR,
    approved_authorization,
    create_dispute_payload,
    get_success_data,
    make_cardholder_headers,
    setup_provisioned_token,
)


def test_fraud_dispute_drives_account_open_restricted_open(api):
    """PRD section 3.7: "opening a FRAUD dispute has an immediate system
    effect: the funding CardAccount moves OPEN -> RESTRICTED" and "either
    outcome of a FRAUD dispute flips the account back RESTRICTED -> OPEN."
    The cycle is driven by the dispute workflow, not by a direct account call.

    Design: Difficulty/non_linear_state_machine/card_account_open_restricted_open_cycle_via_fraud_dispute
    """
    ns = setup_provisioned_token(api)
    auth = approved_authorization(api, ns["token"], amount_cents=40000,
                                  cryptogram="cgm-3")
    ch = make_cardholder_headers(ns["cardholder"]["id"])
    dispute = get_success_data(
        api.open_dispute(auth["id"], create_dispute_payload(40000, reason="FRAUD"), ch)
    )
    account = get_success_data(api.get_card_account(ns["account"]["id"]))
    assert account["status"] == "RESTRICTED"
    get_success_data(api.resolve_dispute(dispute["id"], {"outcome": "WON"}, OPERATOR))
    account = get_success_data(api.get_card_account(ns["account"]["id"]))
    assert account["status"] == "OPEN"


def test_second_fraud_dispute_repeats_the_cycle(api):
    """PRD section 3.7: "opening a FRAUD dispute has an immediate system
    effect: the funding CardAccount moves OPEN -> RESTRICTED" and "either
    outcome of a FRAUD dispute flips the account back RESTRICTED -> OPEN."
    After one full OPEN->RESTRICTED->OPEN cycle, a second FRAUD dispute on a
    later approved authorization drives the account OPEN->RESTRICTED again.

    Design: Difficulty/non_linear_state_machine/card_account_open_restricted_open_cycle_via_fraud_dispute
    """
    ns = setup_provisioned_token(api)
    ch = make_cardholder_headers(ns["cardholder"]["id"])
    auth1 = approved_authorization(api, ns["token"], amount_cents=40000,
                                   cryptogram="cgm-3")
    d1 = get_success_data(
        api.open_dispute(auth1["id"], create_dispute_payload(40000, reason="FRAUD"), ch)
    )
    get_success_data(api.resolve_dispute(d1["id"], {"outcome": "LOST"}, OPERATOR))
    assert get_success_data(api.get_card_account(ns["account"]["id"]))["status"] == "OPEN"
    auth2 = approved_authorization(api, ns["token"], amount_cents=5000,
                                   cryptogram="cgm-4", merchant_id="m-2")
    get_success_data(
        api.open_dispute(auth2["id"], create_dispute_payload(5000, reason="FRAUD"), ch)
    )
    account = get_success_data(api.get_card_account(ns["account"]["id"]))
    assert account["status"] == "RESTRICTED"
