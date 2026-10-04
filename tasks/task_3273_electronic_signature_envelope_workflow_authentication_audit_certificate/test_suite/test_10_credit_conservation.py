"""Credit conservation: the debit, the compensating refund and the null action."""

from test_helpers import (
    ADMIN_HEADERS,
    api_client,
    create_draft_envelope,
    make_account_headers,
    setup_account_and_policy,
    setup_unsent_draft,
    validate_success,
)


def _six_signer_specs():
    return [
        {
            "role": "APPROVER" if i >= 4 else "SIGNER",
            "email": f"r{i + 1}@example.com",
            "routing_order": 1,
            "auth_level": "EMAIL_ACCESS",
            "consent_accepted": True,
        }
        for i in range(6)
    ]


def _three_big_documents_payload():
    return [70, 70, 70]


class TestVoidRefundConservation:
    """§2.9: send debits exactly credit_spend_consumption; a void with
    refund_credit credits exactly the same computed value back."""

    def test_void_with_refund_restores_the_exact_balance(self, api):
        """PRD §3.7: "When `refund_credit` is true the owning account is
        compensated: its `credit_balance` is increased by the envelope's credit
        spend consumption and the account's `version` advances."
        PRD §2.9: "Sending an envelope debits that balance, and compensating a
        void credits it back".
        PRD §2.9: "the envelope's total page count, taken as the sum of the
        `page_count` of every document belonging to the envelope whose
        `is_certificate` is false".

        Design: Difficulty/compensating_invariant/void_with_refund_restores_account_credit_exactly
        """
        account, policy = setup_account_and_policy(credit_balance=1000)
        account_headers = make_account_headers(account["id"])
        envelope = create_draft_envelope(account, policy, subject="Refund invariant envelope")

        document_one = validate_success(
            api_client.add_document(envelope["id"], {"name": "D1.pdf", "page_count": 70}, account_headers),
            201,
        )
        validate_success(
            api_client.add_document(envelope["id"], {"name": "D2.pdf", "page_count": 70}, account_headers),
            201,
        )
        validate_success(
            api_client.add_document(envelope["id"], {"name": "D3.pdf", "page_count": 70}, account_headers),
            201,
        )
        first_recipient = None
        for index, spec in enumerate(_six_signer_specs()):
            recipient = validate_success(
                api_client.add_recipient(envelope["id"], spec, account_headers), 201
            )
            if index == 0:
                first_recipient = recipient
        validate_success(
            api_client.place_field(
                envelope["id"],
                {
                    "envelope_document_id": document_one["id"],
                    "recipient_id": first_recipient["id"],
                    "field_type": "SIGNATURE",
                    "required": True,
                    "page_number": 1,
                    "tab_order": 1,
                    "value": "R1",
                },
                account_headers,
            ),
            201,
        )

        balance_before = validate_success(
            api_client.get_account(account["id"], ADMIN_HEADERS), 200
        )["credit_balance"]

        sent = validate_success(api_client.send_envelope(envelope["id"], account_headers), 200)
        after_send = validate_success(api_client.get_account(account["id"], ADMIN_HEADERS), 200)
        assert after_send["credit_balance"] == balance_before - 21, (
            "the send must debit exactly 21 units (page_overage 19, recipient "
            f"overage 1, base 21): expected {balance_before - 21}, "
            f"got {after_send['credit_balance']}"
        )

        validate_success(
            api_client.void_envelope(
                envelope["id"],
                {
                    "expected_envelope_version": sent["version"],
                    "void_reason": "issued in error",
                    "refund_credit": True,
                },
                account_headers,
            ),
            200,
        )

        after_void = validate_success(api_client.get_account(account["id"], ADMIN_HEADERS), 200)
        assert after_void["credit_balance"] == balance_before, (
            "the compensating refund must restore the balance exactly: expected "
            f"{balance_before}, got {after_void['credit_balance']}"
        )

    def test_void_with_refund_leaves_the_envelope_voided(self, api):
        """PRD §3.7: "On success the envelope takes the `VOIDED` status with the
        `void_reason` captured, every recipient still in `WAITING`, `SENT`,
        `DELIVERED` or `SIGNING` moves to `VOIDED`".
        PRD §2.9: "compensating a void credits it back".

        Design: Difficulty/compensating_invariant/void_with_refund_restores_account_credit_exactly
        """
        account, policy = setup_account_and_policy(credit_balance=1000)
        account_headers = make_account_headers(account["id"])
        envelope = create_draft_envelope(account, policy, subject="Refund invariant envelope two")

        for index, pages in enumerate(_three_big_documents_payload()):
            validate_success(
                api_client.add_document(
                    envelope["id"], {"name": f"D{index + 1}.pdf", "page_count": pages}, account_headers
                ),
                201,
            )
        for spec in _six_signer_specs():
            validate_success(api_client.add_recipient(envelope["id"], spec, account_headers), 201)

        balance_before = validate_success(
            api_client.get_account(account["id"], ADMIN_HEADERS), 200
        )["credit_balance"]
        sent = validate_success(api_client.send_envelope(envelope["id"], account_headers), 200)
        voided = validate_success(
            api_client.void_envelope(
                envelope["id"],
                {
                    "expected_envelope_version": sent["version"],
                    "void_reason": "issued in error",
                    "refund_credit": True,
                },
                account_headers,
            ),
            200,
        )

        assert voided["status"] == "VOIDED", (
            f"the voided envelope takes the VOIDED status, got {voided['status']}"
        )
        recipients = validate_success(
            api_client.list_recipients(account_headers, {"envelope_id": envelope["id"]}), 200
        )
        assert all(r["status"] == "VOIDED" for r in recipients), (
            "every in-flight recipient moves to VOIDED with the void"
        )
        after = validate_success(api_client.get_account(account["id"], ADMIN_HEADERS), 200)
        assert after["credit_balance"] == balance_before, (
            "no residual debit may remain after a refunding void: expected "
            f"{balance_before}, got {after['credit_balance']}"
        )


class TestUnsentDraftConservation:
    """§2.9: the debit happens at send, so an abandoned draft is credit-neutral."""

    def test_drafting_without_sending_debits_nothing(self, api):
        """PRD §2.9: "Every account holds a spendable integer balance in
        `credit_balance`, initialized to 1000 for a new account. Sending an
        envelope debits that balance".
        PRD §3.1: "Content is then assembled into the draft. Documents are added
        one at a time with a file `name` and a `page_count` of at least one".

        Design: Difficulty/compensating_invariant/unsent_envelope_cancel_leaves_credit_untouched
        """
        ctx = setup_unsent_draft(subject="Never sent envelope")
        account, envelope = ctx["account"], ctx["envelope"]

        after = validate_success(api_client.get_account(account["id"], ADMIN_HEADERS), 200)
        assert after["credit_balance"] == 1000, (
            "no send occurred, so credit_spend_consumption was never debited; "
            f"expected 1000, got {after['credit_balance']}"
        )
        current = validate_success(
            api_client.get_envelope(envelope["id"], make_account_headers(account["id"])), 200
        )
        assert current["status"] == "CREATED", (
            f"the envelope remains a draft, got {current['status']}"
        )

    def test_the_draft_sequence_is_credit_neutral(self, api):
        """PRD §2.9: "Sending an envelope debits that balance".
        PRD §3.1: "A new account opens in `ACTIVE` status with a `credit_balance`
        of 1000 credit units".

        Design: Difficulty/compensating_invariant/unsent_envelope_cancel_leaves_credit_untouched
        """
        ctx = setup_unsent_draft(subject="Never sent envelope two")
        account = ctx["account"]

        # A second, larger draft is assembled and likewise never dispatched.
        policy = ctx["policy"]
        account_headers = make_account_headers(account["id"])
        second = create_draft_envelope(account, policy, subject="Never sent envelope three")
        validate_success(
            api_client.add_document(
                second["id"], {"name": "Huge.pdf", "page_count": 900}, account_headers
            ),
            201,
        )
        validate_success(
            api_client.add_recipient(
                second["id"],
                {
                    "role": "SIGNER",
                    "email": "never2@example.com",
                    "routing_order": 1,
                    "auth_level": "EMAIL_ACCESS",
                    "consent_accepted": True,
                },
                account_headers,
            ),
            201,
        )

        after = validate_success(api_client.get_account(account["id"], ADMIN_HEADERS), 200)
        assert after["credit_balance"] == 1000, (
            "the draft-plus-abandon sequence is credit-neutral: expected 1000, "
            f"got {after['credit_balance']}"
        )


def test_send_side_effects_are_immediately_visible(api):
    """PRD §3.2: "Every recipient at routing order 1 moves to `SENT` with
    `auth_status` `PENDING`, the provisional identity risk scores for the whole
    envelope are recomputed, a `SENT` audit event is appended, and the
    envelope's `version` advances by one."
    PRD §2.9: "Sending an envelope debits that balance".

    Design: Corner/consistency_model/immediate_visibility_of_send_side_effects
    """
    from test_helpers import setup_single_signer_envelope

    ctx = setup_single_signer_envelope(credit_balance=11000, page_count=6)
    account, envelope, recipient = ctx["account"], ctx["envelope"], ctx["recipient"]
    account_headers = make_account_headers(account["id"])

    balance_before = validate_success(
        api_client.get_account(account["id"], ADMIN_HEADERS), 200
    )["credit_balance"]

    sent = validate_success(api_client.send_envelope(envelope["id"], account_headers), 200)
    assert sent["status"] == "SENT", (
        f"the send response itself must report SENT, got {sent['status']}"
    )

    recipient_after = validate_success(
        api_client.get_recipient(recipient["id"], account_headers), 200
    )
    assert recipient_after["status"] == "SENT", (
        f"an immediate read shows the routing_order-1 recipient SENT, got {recipient_after['status']}"
    )

    balance_after = validate_success(
        api_client.get_account(account["id"], ADMIN_HEADERS), 200
    )["credit_balance"]
    # 6 pages is within the 25-page allowance and one signer is within the free
    # five, so the debit is the single base unit.
    assert balance_after == balance_before - 1, (
        f"the debit is observable immediately: expected {balance_before - 1}, "
        f"got {balance_after}"
    )