"""Business-rule guards: referential constraints, duty separation and credit."""

from test_helpers import (
    ADMIN_HEADERS,
    api_client,
    make_account_headers,
    make_recipient_headers,
    setup_risk_peer_envelope,
    setup_routing_gap_envelope,
    setup_sent_single_signer,
    setup_signing_recipient,
    setup_single_signer_envelope,
    setup_voided_and_held_envelope,
    validate_error,
    validate_success,
)


def test_duplicate_recipient_email_at_same_routing_order_rejected(api):
    """PRD §3.1: "Two recipients of the same envelope may not share an `email`
    at the same `routing_order`; such an attempt is refused with
    `ERR_DUPLICATE_RECIPIENT` (HTTP 409)."

    Design: Corner/validations/duplicate_recipient_email_same_order_rejected
    """
    ctx = setup_single_signer_envelope(subject="Duplicate envelope")
    account, envelope = ctx["account"], ctx["envelope"]
    account_headers = make_account_headers(account["id"])

    first = validate_success(
        api_client.add_recipient(
            envelope["id"],
            {
                "role": "SIGNER",
                "email": "dup@example.com",
                "routing_order": 1,
                "auth_level": "EMAIL_ACCESS",
                "consent_accepted": True,
            },
            account_headers,
        ),
        201,
    )
    assert first["email"] == "dup@example.com"

    res = api_client.add_recipient(
        envelope["id"],
        {
            "role": "SIGNER",
            "email": "dup@example.com",
            "routing_order": 1,
            "auth_level": "EMAIL_ACCESS",
            "consent_accepted": True,
        },
        account_headers,
    )
    validate_error(res, "ERR_DUPLICATE_RECIPIENT")
    assert res.status_code == 409


def test_signer_sealing_its_own_envelope_is_refused(api):
    """PRD §2.4: "The account that triggers sealing must not be the identity
    that authenticated and signed any recipient of that same envelope. When the
    sealing identity is also a signing identity for the envelope, the seal is
    refused with `ERR_SOD_VIOLATION` (HTTP 403) and the envelope is left
    untouched."
    PRD §2.7: "Authentication headers are checked first (priority 1 and 2,
    `ERR_UNAUTHENTICATED`, HTTP 401), then the acting role's permission on the
    operation (priority 3, `ERR_FORBIDDEN`, HTTP 403). Segregation of duties is
    evaluated next (priority 4, `ERR_SOD_VIOLATION`, HTTP 403)."

    The rule compares identities, so the same `X-User-ID` is presented at both
    the signing call (Recipient role) and the sealing call (Account role): the
    sealing identity is therefore also a signing identity for the envelope.

    Design: Corner/validations/sod_violation_when_signer_seals_own_envelope
    """
    ctx = setup_single_signer_envelope(subject="SoD envelope")
    account, envelope, recipient = ctx["account"], ctx["envelope"], ctx["recipient"]
    account_headers = make_account_headers(account["id"])

    validate_success(api_client.send_envelope(envelope["id"], account_headers), 200)
    validate_success(
        api_client.feed_envelope(
            envelope["id"], {"feed_event": "DELIVERED"}, account_headers
        ),
        200,
    )

    # The signing identity is the recipient's own identifier.
    signer_headers = make_recipient_headers(recipient["id"])
    validate_success(
        api_client.open_signing_session(
            recipient["id"],
            {"consent_to_electronic_records": True},
            signer_headers,
        ),
        201,
    )
    signed = validate_success(
        api_client.sign_recipient(recipient["id"], signer_headers), 200
    )
    assert signed["status"] == "SIGNED", "the signing identity must have signed a recipient"

    current = validate_success(
        api_client.get_envelope(envelope["id"], account_headers), 200
    )

    # The sealing identity is that same identifier, so it is a signing identity
    # for this envelope and the seal is refused at priority 4.
    res = api_client.complete_envelope(
        envelope["id"],
        {"expected_envelope_version": current["version"]},
        make_account_headers(recipient["id"]),
    )
    validate_error(res, "ERR_SOD_VIOLATION")
    assert res.status_code == 403


def test_high_risk_peer_raises_the_signing_bar(api):
    """PRD §3.4: "if that maximum is at least 80, the acting recipient's
    `auth_level` must be `ID_DOCUMENT`. A recipient whose level falls below the
    required bar is refused with `ERR_AUTH_LEVEL_TOO_LOW` (HTTP 422)."
    PRD §2.10: "The score begins from a base that depends on the level: ten for
    `EMAIL_ACCESS`, thirty for `ACCESS_CODE`, fifty-five for `KBA` and eighty
    for `ID_DOCUMENT`."

    Design: Corner/validations/auth_level_too_low_after_high_risk_peer_returns_422
    """
    ctx = setup_risk_peer_envelope(
        peer_auth_level="ID_DOCUMENT",
        target_auth_level="EMAIL_ACCESS",
        authenticate_peer=True,
    )
    account, peer, target = ctx["account"], ctx["peer"], ctx["target"]

    assert peer["auth_status"] == "AUTHENTICATED", "the peer must be authenticated"
    assert peer["auth_risk_score"] >= 80, (
        "an identity-verified ID_DOCUMENT peer scores 95, so it must sit at or "
        f"above the 80 escalation bar, got {peer['auth_risk_score']}"
    )

    res = api_client.sign_recipient(
        target["id"], make_recipient_headers(target["id"])
    )
    validate_error(res, "ERR_AUTH_LEVEL_TOO_LOW")
    assert res.status_code == 422


def test_signing_without_an_open_session_is_refused(api):
    """PRD §3.5: "a recipient with no open session is refused with
    `ERR_SESSION_CLOSED` (HTTP 409)."
    PRD §3.3: "Opening a session additionally requires that the envelope be in
    `SENT` or `DELIVERED`".

    Design: Corner/errors/sign_without_open_session_rejected
    """
    ctx = setup_sent_single_signer(subject="No session envelope")
    account, recipient = ctx["account"], ctx["recipient"]

    sessions = validate_success(
        api_client.list_sessions(
            make_account_headers(account["id"]), {"recipient_id": recipient["id"]}
        ),
        200,
    )
    assert sessions == [], "no signing session exists before the trigger"

    res = api_client.sign_recipient(
        recipient["id"], make_recipient_headers(recipient["id"])
    )
    validate_error(res, "ERR_SESSION_CLOSED")
    assert res.status_code == 409


def test_insufficient_credit_blocks_the_send(api):
    """PRD §3.2: "Separately, the owning account must be able to pay: if its
    `credit_balance` is below the envelope's credit spend consumption as
    described in §2.9, the send is refused with `ERR_INSUFFICIENT_CREDIT`
    (HTTP 402)."

    Design: Corner/errors/insufficient_credit_blocks_send
    """
    ctx = setup_single_signer_envelope(
        credit_balance=5, page_count=300, subject="Credit envelope"
    )
    account, envelope = ctx["account"], ctx["envelope"]

    res = api_client.send_envelope(envelope["id"], make_account_headers(account["id"]))
    validate_error(res, "ERR_INSUFFICIENT_CREDIT")
    assert res.status_code == 402

    after = validate_success(
        api_client.get_envelope(envelope["id"], make_account_headers(account["id"])), 200
    )
    assert after["status"] == "CREATED", (
        f"the send did not commit, so the envelope stays CREATED, got {after['status']}"
    )


class TestValidationPriority:
    """§2.7: "the system applies its validation rules in a fixed ascending
    priority order, and the first rule that fails determines the response —
    later rules are not evaluated and cannot mask an earlier failure." """

    def test_terminal_state_outranks_the_legal_hold_freeze(self, api):
        """PRD §2.7: "State guards come next: envelope mutability against
        terminal status (priority 11, `ERR_ENVELOPE_TERMINAL`, HTTP 409), the
        legal-hold freeze (priority 12, `ERR_LEGAL_HOLD_FROZEN`, HTTP 409)".
        PRD §2.6: "Once terminal, an envelope is immutable: any operation that
        requires mutability and targets a terminal envelope is rejected with
        `ERR_ENVELOPE_TERMINAL` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/send_voided_and_held_envelope_returns_409_state_error
        """
        ctx = setup_voided_and_held_envelope(subject="Priority envelope")
        account, envelope = ctx["account"], ctx["envelope"]

        assert envelope["status"] == "VOIDED", "the setup must leave the envelope VOIDED"
        assert envelope["legal_hold"] is True, "the setup must place a legal hold"

        res = api_client.send_envelope(envelope["id"], make_account_headers(account["id"]))
        validate_error(res, "ERR_ENVELOPE_TERMINAL")
        assert res.status_code == 409

    def test_the_state_error_is_the_one_reported(self, api):
        """PRD §2.7: "the first rule that fails determines the response — later
        rules are not evaluated and cannot mask an earlier failure."
        PRD §2.6: "An operation whose envelope is simply in the wrong
        non-terminal state for the transition it requests is rejected instead
        with `ERR_INVALID_ENVELOPE_STATE` (HTTP 409)." — the voided envelope is
        terminal, so the terminal guard speaks, not the hold guard.

        Design: Difficulty/priority_pair_validation_conflict/send_voided_and_held_envelope_returns_409_state_error
        """
        ctx = setup_voided_and_held_envelope(subject="Priority envelope two")
        account, envelope = ctx["account"], ctx["envelope"]

        res = api_client.send_envelope(envelope["id"], make_account_headers(account["id"]))
        body = validate_error(res, "ERR_ENVELOPE_TERMINAL")
        assert body is None or body.get("error_id") != "ERR_LEGAL_HOLD_FROZEN", (
            "the priority-11 state rule outranks the priority-12 legal-hold rule"
        )

    def test_routing_gap_outranks_insufficient_credit(self, api):
        """PRD §2.7: "Structural constraints then apply, in this order: field
        completeness (priority 24, `ERR_FIELD_REQUIRED`, HTTP 422), recipient
        email/routing-order uniqueness (priority 25, `ERR_DUPLICATE_RECIPIENT`,
        HTTP 409), the contiguous routing-order set (priority 26,
        `ERR_ROUTING_ORDER_GAP`, HTTP 422)".
        PRD §2.7: "and credit sufficiency (priority 31, `ERR_INSUFFICIENT_CREDIT`,
        HTTP 402)".
        PRD §3.2: "A sequential envelope's signer and approver recipients must
        occupy a contiguous run of routing positions".

        Design: Difficulty/priority_pair_validation_conflict/send_with_routing_gap_and_insufficient_credit_returns_422_gap
        """
        ctx = setup_routing_gap_envelope(subject="Gap envelope")
        account, envelope = ctx["account"], ctx["envelope"]

        res = api_client.send_envelope(envelope["id"], make_account_headers(account["id"]))
        validate_error(res, "ERR_ROUTING_ORDER_GAP")
        assert res.status_code == 422

    def test_the_gap_error_is_the_one_reported(self, api):
        """PRD §3.2: "the set of `routing_order` values among recipients whose
        role is `SIGNER` or `APPROVER` must equal the full set from one up to
        the largest value present, with no gap; a gap is refused with
        `ERR_ROUTING_ORDER_GAP` (HTTP 422)."
        PRD §2.7: "later rules are not evaluated and cannot mask an earlier
        failure."

        Design: Difficulty/priority_pair_validation_conflict/send_with_routing_gap_and_insufficient_credit_returns_422_gap
        """
        ctx = setup_routing_gap_envelope(subject="Gap envelope two")
        account, envelope = ctx["account"], ctx["envelope"]

        res = api_client.send_envelope(envelope["id"], make_account_headers(account["id"]))
        body = validate_error(res, "ERR_ROUTING_ORDER_GAP")
        assert body is None or body.get("error_id") != "ERR_INSUFFICIENT_CREDIT", (
            "the priority-26 constraint outranks the priority-31 fiscal rule"
        )

    def test_consent_guard_outranks_the_expiry_instant(self, api):
        """PRD §2.7: "The assurance and consent guards occupy the middle of the ladder:
        the level-escalation rule (priority 16, `ERR_AUTH_LEVEL_TOO_LOW`,
        HTTP 422), the authentication-satisfied rule (priority 17,
        `ERR_AUTH_REQUIRED`, HTTP 422), the knowledge-based-question attempt cap
        (priority 18, `ERR_AUTH_MAX_ATTEMPTS`, HTTP 422), the consent requirement
        (priority 19, `ERR_CONSENT_REQUIRED`, HTTP 422) and the access-code match
        (priority 20, `ERR_INVALID_ACCESS_CODE`, HTTP 401)."
        PRD §2.7: "Temporal guards follow — routing release (priority 21,
        `ERR_ROUTING_NOT_RELEASED`, HTTP 422), the envelope expiry instant
        (priority 22, `ERR_ENVELOPE_EXPIRED`, HTTP 409) and retention eligibility
        (priority 23, `ERR_RETENTION_NOT_EXPIRED`, HTTP 409)."
        PRD §3.5: "Consent that has not been captured is refused with
        `ERR_CONSENT_REQUIRED` (HTTP 422)".

        Design: Difficulty/priority_pair_validation_conflict/sign_past_expiry_without_consent_returns_422_consent
        """
        ctx = setup_sent_single_signer(
            subject="Expiry consent envelope",
            consent_accepted=False,
            expires_after_days=30,
            pin_epoch=True,
        )
        account, recipient = ctx["account"], ctx["recipient"]

        validate_success(
            api_client.open_signing_session(
                recipient["id"],
                {"consent_to_electronic_records": False},
                make_recipient_headers(recipient["id"]),
            ),
            201,
        )

        # 2026-10-01T23:59:59Z is the deadline; the clock is moved past it.
        api_client.set_current_utc({"to_iso8601": "2026-10-05T00:00:00Z"}, ADMIN_HEADERS)

        res = api_client.sign_recipient(
            recipient["id"], make_recipient_headers(recipient["id"])
        )
        validate_error(res, "ERR_CONSENT_REQUIRED")
        assert res.status_code == 422

    def test_the_consent_error_is_the_one_reported(self, api):
        """PRD §2.7: "later rules are not evaluated and cannot mask an earlier
        failure."
        PRD §3.5: "As at authentication, an envelope whose `expires_at` has
        passed refuses the action with `ERR_ENVELOPE_EXPIRED` (HTTP 409)." —
        the consent guard sits above that temporal guard.

        Design: Difficulty/priority_pair_validation_conflict/sign_past_expiry_without_consent_returns_422_consent
        """
        ctx = setup_sent_single_signer(
            subject="Expiry consent envelope two",
            consent_accepted=False,
            expires_after_days=30,
            pin_epoch=True,
        )
        recipient = ctx["recipient"]

        validate_success(
            api_client.open_signing_session(
                recipient["id"],
                {"consent_to_electronic_records": False},
                make_recipient_headers(recipient["id"]),
            ),
            201,
        )
        api_client.set_current_utc({"to_iso8601": "2026-10-05T00:00:00Z"}, ADMIN_HEADERS)

        res = api_client.sign_recipient(
            recipient["id"], make_recipient_headers(recipient["id"])
        )
        body = validate_error(res, "ERR_CONSENT_REQUIRED")
        assert body is None or body.get("error_id") != "ERR_ENVELOPE_EXPIRED", (
            "the priority-19 safety rule outranks the priority-22 temporal rule"
        )

    def test_unsatisfied_authentication_blocks_the_signature(self, api):
        """PRD §3.4: "When a recipient whose level is `ACCESS_CODE`, `KBA` or
        `ID_DOCUMENT` attempts to sign, its `auth_status` must be `AUTHENTICATED`;
        when the recipient's level is `EMAIL_ACCESS` and the delivered email link
        is its only credential, either `AUTHENTICATED` or still-`PENDING` is
        accepted. A recipient that has not met its own requirement is refused
        with `ERR_AUTH_REQUIRED` (HTTP 422)."

        Design: Corner/validations/auth_level_too_low_after_high_risk_peer_returns_422
        """
        ctx = setup_signing_recipient(
            auth_level="KBA",
            authenticate=False,
            subject="Auth required envelope",
        )
        recipient = ctx["recipient"]
        assert recipient["auth_status"] == "PENDING", (
            f"the KBA recipient has not authenticated yet, got {recipient['auth_status']}"
        )

        res = api_client.sign_recipient(
            recipient["id"], make_recipient_headers(recipient["id"])
        )
        validate_error(res, "ERR_AUTH_REQUIRED")
        assert res.status_code == 422

    def test_email_access_signer_may_sign_while_pending(self, api):
        """PRD §3.4: "when the recipient's level is `EMAIL_ACCESS` and the
        delivered email link is its only credential, either `AUTHENTICATED` or
        still-`PENDING` is accepted."

        Design: Corner/validations/auth_level_too_low_after_high_risk_peer_returns_422
        """
        ctx = setup_signing_recipient(
            auth_level="EMAIL_ACCESS",
            authenticate=False,
            subject="Email access signer envelope",
        )
        recipient = ctx["recipient"]
        assert recipient["auth_level"] == "EMAIL_ACCESS"
        assert recipient["auth_status"] == "PENDING"

        signed = validate_success(
            api_client.sign_recipient(
                recipient["id"], make_recipient_headers(recipient["id"])
            ),
            200,
        )
        assert signed["status"] == "SIGNED", (
            "an EMAIL_ACCESS recipient needs no prior authentication, "
            f"got {signed['status']}"
        )
