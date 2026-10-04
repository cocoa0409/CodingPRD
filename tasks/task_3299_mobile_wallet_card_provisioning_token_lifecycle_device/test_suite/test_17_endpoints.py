"""Corner: endpoints — default card replacement, idempotent provisioning replay,
reissue successor, token audit event ordering."""
from test_helpers import (
    OPERATOR,
    approved_authorization,
    get_success_data,
    make_cardholder_headers,
    provision_second_token,
    setup_provisioned_token,
    validate_paginated,
    validate_success,
)


def test_set_default_card_replaces_previous_default(api):
    """PRD section 3.5: "Each device may designate exactly one default payment
    card ... Setting a new default replaces whatever default_card_id previously
    held; there is no multi-default."

    Design: Corner/endpoints/set_default_card_replaces_previous_default
    """
    ns = setup_provisioned_token(api)
    token2 = provision_second_token(api, ns)
    ch = make_cardholder_headers(ns["cardholder"]["id"])
    d = ns["device"]["id"]
    dev = get_success_data(api.get_device(d))
    dev = get_success_data(api.set_default_card(
        d, {"token_id": ns["token"]["id"],
            "expected_device_version": dev["version"]}, ch))
    assert dev["default_card_id"] == ns["token"]["id"]
    dev = get_success_data(api.set_default_card(
        d, {"token_id": token2["id"],
            "expected_device_version": dev["version"]}, ch))
    assert dev["default_card_id"] == token2["id"]
    for tid in (ns["token"]["id"], token2["id"]):
        assert get_success_data(api.get_payment_token(tid))["status"] == "ACTIVE"


def test_provisioning_create_replays_on_same_idempotency_key(api):
    """PRD section 3.4: "Idempotency (priority 7) makes retries safe: the same
    idempotency_key on the same device replays the original session unchanged,
    while the same key with a different payload is ERR_IDEMPOTENCY_CONFLICT."

    Design: Corner/endpoints/provisioning_create_replays_on_same_idempotency_key
    """
    from test_helpers import (open_session, reset_clock, setup_account_and_artifact,
                              setup_cardholder, setup_device, setup_issuer_active)
    reset_clock(api)
    ch = setup_cardholder(api)
    issuer, _agr = setup_issuer_active(api)
    device = setup_device(api, ch)
    account, artifact = setup_account_and_artifact(api, ch, issuer)
    session = open_session(api, device, artifact, ch, idem_key="prov-a")
    ch_h = make_cardholder_headers(ch["id"])
    resp = api.create_provisioning_session(
        device["id"],
        {"card_artifact_id": artifact["id"], "idempotency_key": "prov-a"}, ch_h)
    replay = get_success_data(resp)
    assert replay["id"] == session["id"]


def test_reissue_creates_successor_and_deactivates_old_tokens(api):
    """PRD section 3.3: "Reissuing creates a successor CardAccount in OPEN
    status whose reissue_of_account_id points back at the predecessor, flips
    the predecessor to REISSUED, deactivates every artifact on the predecessor,
    and deactivates every ACTIVE or SUSPENDED token on the predecessor with
    deactivated_reason CARD_REISSUE, appending a DEACTIVATION event per token".

    Design: Corner/endpoints/reissue_creates_successor_and_deactivates_old_tokens
    """
    ns = setup_provisioned_token(api)
    resp = api.reissue_card_account(ns["account"]["id"], OPERATOR)
    successor = validate_success(resp, expected_status=201)
    assert successor["status"] == "OPEN"
    assert successor["reissue_of_account_id"] == ns["account"]["id"]
    old = get_success_data(api.get_card_account(ns["account"]["id"]))
    assert old["status"] == "REISSUED"
    token = get_success_data(api.get_payment_token(ns["token"]["id"]))
    assert token["status"] == "DEACTIVATED"
    assert token["deactivated_reason"] == "CARD_REISSUE"


def test_token_events_list_is_append_only_audit_trail(api):
    """PRD section 2.12: "Every PaymentToken accumulates an append-only audit
    stream of TokenEvent records" and "Every state change or counter-affecting
    decision on a token that the workflows of section 3 describe as 'appending
    a TokenEvent' must produce exactly one such record". Tokenization appends
    ACTIVATION, an approved authorization appends AUTHORIZATION_APPROVED, and a
    suspend appends SUSPENSION — in that order.

    Design: Corner/endpoints/token_events_list_is_append_only_audit_trail
    """
    ns = setup_provisioned_token(api)
    approved_authorization(api, ns["token"], amount_cents=1000, cryptogram="cgm-ev")
    ch = make_cardholder_headers(ns["cardholder"]["id"])
    get_success_data(api.suspend_token(ns["device"]["id"], ns["token"]["id"], ch))
    events, _meta = validate_paginated(api.list_token_events(ns["token"]["id"]))
    types = [e["event_type"] for e in events]
    assert types == ["ACTIVATION", "AUTHORIZATION_APPROVED", "SUSPENSION"], (
        f"unexpected event sequence: {types}"
    )
    for e in events:
        assert e["payment_token_id"] == ns["token"]["id"]
