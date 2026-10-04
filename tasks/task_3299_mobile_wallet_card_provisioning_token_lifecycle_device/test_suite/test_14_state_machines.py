"""Corner: state machine instances — issuer activation, token double-suspend,
dispute terminal lockdown, account CLOSED lockdown, session initial state."""
from test_helpers import (
    ADMIN,
    OPERATOR,
    ApiErrorId,
    approved_authorization,
    create_agreement_payload,
    create_dispute_payload,
    create_issuer_payload,
    get_success_data,
    make_cardholder_headers,
    open_session,
    reset_clock,
    setup_account_and_artifact,
    setup_cardholder,
    setup_device,
    setup_issuer_active,
    setup_provisioned_token,
    validate_error,
)


def test_issuer_activate_with_active_agreement_succeeds(api):
    """PRD section 3.1: "an issuer may move from DRAFT to ACTIVE only when at
    least one IssuerAgreement under it is in ACTIVE status."

    Design: Corner/state_machines/issuer_activate_with_active_agreement_succeeds
    """
    reset_clock(api)
    issuer = get_success_data(api.create_issuer(create_issuer_payload(), ADMIN))
    assert issuer["status"] == "DRAFT"
    v0 = issuer["version"]
    agr = get_success_data(api.create_agreement(
        create_agreement_payload(issuer["id"]), ADMIN))
    get_success_data(api.activate_agreement(agr["id"], ADMIN))
    issuer = get_success_data(api.activate_issuer(issuer["id"], ADMIN))
    assert issuer["status"] == "ACTIVE"
    assert issuer["version"] > v0


def test_issuer_activate_without_active_agreement_returns_agreement_required(api):
    """PRD section 3.1: "an issuer may move from DRAFT to ACTIVE only when at
    least one IssuerAgreement under it is in ACTIVE status. Activating an
    issuer without one is rejected with ERR_AGREEMENT_REQUIRED."

    Design: Corner/state_machines/issuer_activate_without_active_agreement_returns_agreement_required
    """
    reset_clock(api)
    issuer = get_success_data(api.create_issuer(create_issuer_payload(), ADMIN))
    get_success_data(api.create_agreement(
        create_agreement_payload(issuer["id"]), ADMIN))  # left PENDING
    resp = api.activate_issuer(issuer["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_REQUIRED)
    issuer = get_success_data(api.get_issuer(issuer["id"]))
    assert issuer["status"] == "DRAFT"


def test_token_suspend_from_suspended_returns_invalid_state(api):
    """PRD section 3.5: "Suspending a token — ACTIVE -> SUSPENDED — requires
    the token to be ACTIVE (else ERR_INVALID_STATE), increments its
    suspension_count by one, and appends a SUSPENSION event." A second suspend
    from SUSPENDED fails and does not double-count.

    Design: Corner/state_machines/token_suspend_from_suspended_returns_invalid_state
    """
    ns = setup_provisioned_token(api)
    ch = make_cardholder_headers(ns["cardholder"]["id"])
    d, t = ns["device"]["id"], ns["token"]["id"]
    get_success_data(api.suspend_token(d, t, ch))
    resp = api.suspend_token(d, t, ch)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    token = get_success_data(api.get_payment_token(t))
    assert token["suspension_count"] == 1


def test_dispute_resolve_is_rejected_once_terminal(api):
    """PRD section 3.7: "Resolution is an IssuerOperator decision expressed as
    an outcome of WON or LOST against an OPEN dispute (any other state fails
    ERR_INVALID_STATE)." Resolving an already-WON dispute again is rejected
    and the dispute stays WON.

    Design: Corner/state_machines/dispute_resolve_is_idempotent_once_terminal
    """
    ns = setup_provisioned_token(api)
    auth = approved_authorization(api, ns["token"], amount_cents=12000,
                                  cryptogram="cgm-7")
    ch = make_cardholder_headers(ns["cardholder"]["id"])
    dispute = get_success_data(
        api.open_dispute(auth["id"], create_dispute_payload(12000), ch))
    get_success_data(api.resolve_dispute(dispute["id"], {"outcome": "WON"}, OPERATOR))
    resp = api.resolve_dispute(dispute["id"], {"outcome": "LOST"}, OPERATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    dispute = get_success_data(api.get_dispute(dispute["id"]))
    assert dispute["status"] == "WON"


def test_card_account_terminal_close_locks_all_transitions(api):
    """PRD section 3.3: "Accounts are born OPEN; the full status set is OPEN,
    RESTRICTED, REISSUED, and the terminal CLOSED." Closing an OPEN account
    moves it to terminal CLOSED; reissue and a second close from CLOSED are
    state-machine rejections (409).

    Design: Corner/state_machines/card_account_terminal_close_locks_all_transitions
    """
    reset_clock(api)
    ch = setup_cardholder(api)
    issuer, _agr = setup_issuer_active(api)
    account, _art = setup_account_and_artifact(api, ch, issuer)
    get_success_data(api.close_card_account(account["id"], OPERATOR))
    resp = api.reissue_card_account(account["id"], OPERATOR)
    e1 = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    resp = api.close_card_account(account["id"], OPERATOR)
    e2 = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    account = get_success_data(api.get_card_account(account["id"]))
    assert account["status"] == "CLOSED"


def test_provisioning_session_starts_verification_required(api):
    """PRD section 3.4: "A created session lands in INITIATED and immediately,
    automatically, transitions to VERIFICATION_REQUIRED. Its expires_at is
    computed at creation as exactly 24 hours after created_at, measured on the
    logical clock."

    Design: Corner/state_machines/provisioning_session_starts_verification_required_after_auto_step
    """
    reset_clock(api)
    ch = setup_cardholder(api)
    issuer, _agr = setup_issuer_active(api)
    device = setup_device(api, ch)
    account, artifact = setup_account_and_artifact(api, ch, issuer)
    session = open_session(api, device, artifact, ch)
    assert session["status"] == "VERIFICATION_REQUIRED"
    assert session["verification_attempt_count"] == 0
    assert session["expires_at"] == "2026-09-02T00:00:00Z"
