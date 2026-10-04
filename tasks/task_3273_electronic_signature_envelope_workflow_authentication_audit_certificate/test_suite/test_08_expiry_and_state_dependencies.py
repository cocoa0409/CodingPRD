"""Expiry guards and the cross-entity dependency between recipient and envelope."""

from test_helpers import (
    ADMIN_HEADERS,
    api_client,
    get_recipient,
    make_account_headers,
    make_recipient_headers,
    setup_multi_document_envelope,
    setup_sent_single_signer,
    validate_error,
    validate_success,
)


def test_expire_before_the_deadline_is_refused(api):
    """PRD §3.7: "The envelope must be in `SENT` or `DELIVERED`, must not be
    under a legal hold, and the logical clock must have reached or passed the
    envelope's `expires_at`".

    Design: Corner/cross_cutting_complexity_layers/scheduled_expiry_after_clock_advance_expires_in_flight_envelope
    """
    ctx = setup_sent_single_signer(
        subject="Early expiry envelope",
        expires_after_days=30,
        pin_epoch=True,
    )
    account, envelope = ctx["account"], ctx["envelope"]
    account_headers = make_account_headers(account["id"])

    # The deadline is 2026-10-01T23:59:59Z; the clock is still inside the window.
    api_client.set_current_utc({"to_iso8601": "2026-09-30T00:00:00Z"}, ADMIN_HEADERS)

    res = api_client.expire_envelope(
        envelope["id"], {"expected_envelope_version": envelope["version"]}, account_headers
    )
    assert res.status_code >= 400, (
        f"expiring before the deadline must be refused, got {res.status_code}"
    )

    after = validate_success(api_client.get_envelope(envelope["id"], account_headers), 200)
    assert after["status"] == "SENT", (
        f"the refused expiry leaves the envelope in flight, got {after['status']}"
    )


def test_recipient_cannot_sign_once_the_envelope_is_voided(api):
    """PRD §3.5: "Declining is therefore terminal for the envelope as a whole".
    PRD §2.6: "Once terminal, an envelope is immutable: any operation that
    requires mutability and targets a terminal envelope is rejected with
    `ERR_ENVELOPE_TERMINAL` (HTTP 409)."
    PRD §2.7: "State guards come next: envelope mutability against terminal
    status (priority 11, `ERR_ENVELOPE_TERMINAL`, HTTP 409), the legal-hold
    freeze (priority 12, `ERR_LEGAL_HOLD_FROZEN`, HTTP 409), the transition's
    permitted from-set including the completion requirement that every signer
    and approver already be finished (priority 13, `ERR_INVALID_ENVELOPE_STATE`,
    HTTP 409), recipient actionability (priority 14, `ERR_RECIPIENT_TERMINAL`,
    HTTP 409) and the presence of an open signing session (priority 15,
    `ERR_SESSION_CLOSED`, HTTP 409)."

    A recipient that is otherwise fully ready is still gated by the owning
    envelope's state, because the recipient's legal transition set requires the
    envelope to be in `SENT` or `DELIVERED`.

    Design: Difficulty/cross_entity_state_dependency/recipient_sign_requires_envelope_in_flight
    """
    ctx = setup_sent_single_signer(subject="Guard envelope")
    account, envelope, recipient = ctx["account"], ctx["envelope"], ctx["recipient"]
    account_headers = make_account_headers(account["id"])

    validate_success(
        api_client.open_signing_session(
            recipient["id"],
            {"consent_to_electronic_records": True},
            make_recipient_headers(recipient["id"]),
        ),
        201,
    )

    voided = validate_success(
        api_client.void_envelope(
            envelope["id"],
            {
                "expected_envelope_version": envelope["version"],
                "void_reason": "sender withdrew",
                "refund_credit": False,
            },
            account_headers,
        ),
        200,
    )
    assert voided["status"] == "VOIDED", "the setup must leave the envelope VOIDED"

    res = api_client.sign_recipient(
        recipient["id"], make_recipient_headers(recipient["id"])
    )
    assert res.status_code >= 400, (
        f"a signer on a terminal envelope must be refused, got {res.status_code}"
    )

    after = get_recipient(recipient["id"], account)
    assert after["status"] != "SIGNED", (
        "the recipient was cascaded out of flight and cannot sign, "
        f"got {after['status']}"
    )


def test_sealing_requires_every_signer_and_approver_terminal(api):
    """PRD §3.6: "It is available only when the envelope is in `DELIVERED` and
    every recipient of the envelope whose role is `SIGNER` or `APPROVER` has
    already reached `SIGNED` or `APPROVED`; an envelope that does not meet that
    completeness condition is refused with `ERR_INVALID_ENVELOPE_STATE`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/envelope_complete_requires_all_recipients_terminal
    """
    ctx = setup_multi_document_envelope(
        [7],
        [
            {
                "role": "SIGNER",
                "email": "done@example.com",
                "routing_order": 1,
                "auth_level": "EMAIL_ACCESS",
                "consent_accepted": True,
            },
            {
                "role": "SIGNER",
                "email": "pending@example.com",
                "routing_order": 1,
                "auth_level": "EMAIL_ACCESS",
                "consent_accepted": True,
            },
        ],
        routing_mode="PARALLEL",
        subject="Aggregate gate envelope",
    )
    account, envelope = ctx["account"], ctx["envelope"]
    done, pending = ctx["recipients"]
    account_headers = make_account_headers(account["id"])

    validate_success(api_client.send_envelope(envelope["id"], account_headers), 200)
    validate_success(
        api_client.feed_envelope(
            envelope["id"], {"feed_event": "DELIVERED"}, account_headers
        ),
        200,
    )

    validate_success(
        api_client.open_signing_session(
            done["id"],
            {"consent_to_electronic_records": True},
            make_recipient_headers(done["id"]),
        ),
        201,
    )
    signed = validate_success(
        api_client.sign_recipient(done["id"], make_recipient_headers(done["id"])), 200
    )
    assert signed["status"] == "SIGNED"

    validate_success(
        api_client.open_signing_session(
            pending["id"],
            {"consent_to_electronic_records": True},
            make_recipient_headers(pending["id"]),
        ),
        201,
    )
    pending_row = get_recipient(pending["id"], account)
    assert pending_row["status"] == "SIGNING", (
        f"one signer is still mid-ceremony, got {pending_row['status']}"
    )

    current = validate_success(api_client.get_envelope(envelope["id"], account_headers), 200)
    res = api_client.complete_envelope(
        envelope["id"],
        {"expected_envelope_version": current["version"]},
        account_headers,
    )
    validate_error(res, "ERR_INVALID_ENVELOPE_STATE")
    assert res.status_code == 409

    after = validate_success(api_client.get_envelope(envelope["id"], account_headers), 200)
    assert after["status"] == "DELIVERED", (
        f"the envelope did not advance, got {after['status']}"
    )
    assert after["is_sealed"] is False, "the refused seal must not set is_sealed"

def test_the_seal_refusal_is_caused_by_recipient_incompleteness(api):
    """PRD §3.6: "It is available only when the envelope is in `DELIVERED` and every
    recipient of the envelope whose role is `SIGNER` or `APPROVER` has already
    reached `SIGNED` or `APPROVED`; an envelope that does not meet that
    completeness condition is refused with `ERR_INVALID_ENVELOPE_STATE`
    (HTTP 409)."
    PRD §2.7: "the transition's permitted from-set including the completion
    requirement that every signer and approver already be finished (priority 13,
    `ERR_INVALID_ENVELOPE_STATE`, HTTP 409)".
    PRD §3.6: "Every required field placement on the envelope must hold a value,
    or the attempt is refused with `ERR_FIELD_REQUIRED` (HTTP 422)." — so the
    refusal below cannot be attributed to a missing field value.

    Design: Difficulty/cross_entity_state_dependency/envelope_complete_requires_all_recipients_terminal
    """
    ctx = setup_multi_document_envelope(
        [7],
        [
            {
                "role": "SIGNER",
                "email": "done@example.com",
                "routing_order": 1,
                "auth_level": "EMAIL_ACCESS",
                "consent_accepted": True,
            },
            {
                "role": "SIGNER",
                "email": "pending@example.com",
                "routing_order": 1,
                "auth_level": "EMAIL_ACCESS",
                "consent_accepted": True,
            },
        ],
        routing_mode="PARALLEL",
        subject="Aggregate gate envelope two",
    )
    account, envelope = ctx["account"], ctx["envelope"]
    done, pending = ctx["recipients"]
    account_headers = make_account_headers(account["id"])

    validate_success(api_client.send_envelope(envelope["id"], account_headers), 200)
    validate_success(
        api_client.feed_envelope(envelope["id"], {"feed_event": "DELIVERED"}, account_headers),
        200,
    )
    validate_success(
        api_client.open_signing_session(
            done["id"],
            {"consent_to_electronic_records": True},
            make_recipient_headers(done["id"]),
        ),
        201,
    )
    validate_success(
        api_client.sign_recipient(done["id"], make_recipient_headers(done["id"])), 200
    )
    validate_success(
        api_client.open_signing_session(
            pending["id"],
            {"consent_to_electronic_records": True},
            make_recipient_headers(pending["id"]),
        ),
        201,
    )

    # Every required field placement already holds a value, so the only unmet
    # completeness condition is the still-open signer.
    fields = validate_success(
        api_client.list_fields(account_headers, {"envelope_id": envelope["id"]}), 200
    )
    required = [f for f in fields if f.get("required")]
    assert required, "the setup must place required fields"
    assert all(f["value"] is not None for f in required), (
        "no required field is null, so ERR_FIELD_REQUIRED cannot be the cause"
    )

    current = validate_success(api_client.get_envelope(envelope["id"], account_headers), 200)
    res = api_client.complete_envelope(
        envelope["id"],
        {"expected_envelope_version": current["version"]},
        account_headers,
    )
    validate_error(res, "ERR_INVALID_ENVELOPE_STATE")
    assert res.status_code == 409


def test_the_void_cascade_removes_the_recipients_ability_to_sign(api):
    """PRD §3.7: "On success the envelope takes the `VOIDED` status with the
    `void_reason` captured, every recipient still in `WAITING`, `SENT`,
    `DELIVERED` or `SIGNING` moves to `VOIDED`".
    PRD §2.6: "When an in-flight envelope is voided, every recipient still in
    `WAITING`, `SENT`, `DELIVERED` or `SIGNING` moves to `VOIDED`, and every
    open signing session belonging to one of those recipients moves to
    `EXPIRED`."

    The recipient is fully prepared — authenticated-free, consented, with a
    filled SIGNATURE field and an OPEN session — yet the envelope-level decision
    alone removes its ability to complete.

    Design: Difficulty/cross_entity_state_dependency/recipient_sign_requires_envelope_in_flight
    """
    ctx = setup_sent_single_signer(subject="Guard envelope two")
    account, envelope, recipient = ctx["account"], ctx["envelope"], ctx["recipient"]
    account_headers = make_account_headers(account["id"])

    session = validate_success(
        api_client.open_signing_session(
            recipient["id"],
            {"consent_to_electronic_records": True},
            make_recipient_headers(recipient["id"]),
        ),
        201,
    )
    assert session["status"] == "OPEN"

    voided = validate_success(
        api_client.void_envelope(
            envelope["id"],
            {
                "expected_envelope_version": envelope["version"],
                "void_reason": "sender withdrew",
                "refund_credit": False,
            },
            account_headers,
        ),
        200,
    )
    assert voided["status"] == "VOIDED", "the envelope is VOIDED before the trigger"

    after = get_recipient(recipient["id"], account)
    assert after["status"] == "VOIDED", (
        "the void cascade removed the recipient from flight, "
        f"got {after['status']}"
    )
    closed = validate_success(
        api_client.get_session(session["id"], account_headers), 200
    )
    assert closed["status"] == "EXPIRED", (
        f"the open session moves to EXPIRED with the void, got {closed['status']}"
    )

    res = api_client.sign_recipient(
        recipient["id"], make_recipient_headers(recipient["id"])
    )
    assert res.status_code >= 400, (
        f"a recipient on a VOIDED envelope cannot sign, got {res.status_code}"
    )
