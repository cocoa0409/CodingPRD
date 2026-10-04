"""Cross-entity state dependencies (queue A): resume gating and artifact asymmetry."""
from test_helpers import (
    ApiErrorId,
    OPERATOR,
    approved_authorization,
    authorize,
    create_dispute_payload,
    get_success_data,
    make_cardholder_headers,
    setup_provisioned_token,
    validate_error,
)


def _suspended_token_with_restricted_account(api):
    ns = setup_provisioned_token(api)
    ch = make_cardholder_headers(ns["cardholder"]["id"])
    auth = approved_authorization(api, ns["token"], amount_cents=15000,
                                  cryptogram="cgm-4")
    get_success_data(api.suspend_token(ns["device"]["id"], ns["token"]["id"], ch))
    dispute = get_success_data(
        api.open_dispute(auth["id"], create_dispute_payload(15000, reason="FRAUD"), ch)
    )
    return ns, dispute, ch


def test_resume_blocked_while_account_restricted(api):
    """PRD section 3.5: "Resuming — SUSPENDED -> ACTIVE — is deliberately
    harder: the device must be HEALTHY ..., the funding account must be OPEN
    (else ERR_CARD_ACCOUNT_RESTRICTED), and the token must actually be
    SUSPENDED." A FRAUD dispute restricts the account, so resume fails.

    Design: Difficulty/cross_entity_state_dependency/token_resume_gated_by_card_account_open
    """
    ns, _dispute, ch = _suspended_token_with_restricted_account(api)
    resp = api.resume_token(ns["device"]["id"], ns["token"]["id"], ch)
    validate_error(resp, ApiErrorId.ERR_CARD_ACCOUNT_RESTRICTED)


def test_resume_succeeds_after_dispute_resolves_account_open(api):
    """PRD section 3.7: "either outcome of a FRAUD dispute flips the account
    back RESTRICTED -> OPEN" and section 3.5: "Resuming — SUSPENDED -> ACTIVE
    — ... the funding account must be OPEN (else ERR_CARD_ACCOUNT_RESTRICTED)".
    After the dispute resolves LOST, the same resume succeeds and the token
    reads back ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/token_resume_gated_by_card_account_open
    """
    ns, dispute, ch = _suspended_token_with_restricted_account(api)
    get_success_data(api.resolve_dispute(dispute["id"], {"outcome": "LOST"}, OPERATOR))
    token = get_success_data(
        api.resume_token(ns["device"]["id"], ns["token"]["id"], ch)
    )
    assert token["status"] == "ACTIVE"


def test_artifact_suspend_cascades_to_bound_token(api):
    """PRD section 3.3: "Artifact suspension — ACTIVE -> SUSPENDED — requires
    the parent account to be OPEN (else ERR_INVALID_STATE) and cascades: every
    ACTIVE token bound to that artifact moves to SUSPENDED, each with
    suspension_count incremented and a SUSPENSION event appended."

    Design: Difficulty/cross_entity_state_dependency/artifact_suspend_cascades_to_token_but_resume_does_not
    """
    ns = setup_provisioned_token(api)
    get_success_data(api.suspend_artifact(ns["artifact"]["id"], OPERATOR))
    token = get_success_data(api.get_payment_token(ns["token"]["id"]))
    assert token["status"] == "SUSPENDED"
    assert token["suspension_count"] == 1


def test_artifact_resume_does_not_resume_token(api):
    """PRD section 3.3: "Resuming an artifact — SUSPENDED -> ACTIVE — likewise
    requires an OPEN account and, notably, does not resume the tokens; like
    found-devices, recovered plastic does not imply trusted credentials."
    After artifact resume the token remains SUSPENDED and an authorization
    attempt fails with ERR_TOKEN_NOT_ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/artifact_suspend_cascades_to_token_but_resume_does_not
    """
    ns = setup_provisioned_token(api)
    get_success_data(api.suspend_artifact(ns["artifact"]["id"], OPERATOR))
    get_success_data(api.resume_artifact(ns["artifact"]["id"], OPERATOR))
    token = get_success_data(api.get_payment_token(ns["token"]["id"]))
    assert token["status"] == "SUSPENDED"
    resp = authorize(api, token, amount_cents=100, cryptogram="cgm-x")
    validate_error(resp, ApiErrorId.ERR_TOKEN_NOT_ACTIVE)
