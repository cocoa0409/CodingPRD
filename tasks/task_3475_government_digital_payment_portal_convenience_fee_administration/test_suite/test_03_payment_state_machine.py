"""PaymentTransaction lifecycle: atomic authorize, capture stamps, void
terminality, method-gated returns/chargebacks, and state-vs-fiscal ordering."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_transaction,
    authorize,
    capture,
    create_chargeback_payload,
    create_quote,
    create_refund_payload,
    get_quote,
    get_transaction,
    list_batches,
    make_agency_admin_headers,
    make_payer_headers,
    open_and_close_batch,
    open_batch,
    close_batch,
    pay,
    pay_and_capture,
    set_clock,
    setup_cf_checkout,
    setup_captured_card,
    setup_captured_echeck,
    setup_open_card_quote,
    validate_error,
    validate_paginated,
    validate_success,
    void_transaction,
)

PA = TEST_USERS["platform_admin_headers"]
AA_LEAD = make_agency_admin_headers("aa-lead")


def _parse(ts):
    from datetime import datetime
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    raise AssertionError(f"unparseable timestamp {ts!r}")


class TestAuthorizeCreatesAuthorized:
    def test_transaction_created_directly_in_authorized(self, api):
        """PRD §3.4: "A successful authorization creates the payment
        transaction in `AUTHORIZED` status and flips the quote from `OPEN` to
        `CONSUMED`."

        Design: Corner/state_machines/transaction_created_directly_in_authorized
        """
        ctx = setup_open_card_quote()
        resp = api_client.authorize_payment(
            {"quote_id": ctx["quote"]["id"], "instrument_id": ctx["card"]["id"]},
            make_payer_headers(ctx["payer"]["id"]),
        )
        txn = validate_success(resp, 201)
        assert_transaction(txn)
        assert txn["funds_status"] == "AUTHORIZED"
        assert txn["representment_count"] == 0
        assert txn["refunded_cents"] == 0
        assert txn["charged_back_cents"] == 0
        assert txn["remaining_refundable_cents"] == 100000
        assert txn["current_batch_id"] is None
        assert txn["agency_id"] == ctx["agency"]["id"]
        assert txn["service_id"] == ctx["service"]["id"]
        assert txn["payer_id"] == ctx["payer"]["id"]
        assert txn["method"] == "CARD"
        assert txn["fee_model"] == "CONVENIENCE_FEE"
        assert get_quote(ctx["quote"]["id"], ctx["payer"]["id"])["status"] == "CONSUMED"


class TestCaptureStamps:
    def test_capture_stamps_clock_and_value_date(self, api):
        """PRD §3.4: "Capture — by `AgencyAdmin` or `PlatformAdmin` — moves the
        transaction from `AUTHORIZED` to `CAPTURED`, stamps `captured_at` from
        the logical clock, and computes `value_date`, the deposit-eligibility
        date: the capture calendar date plus the method lag, one day for
        `CARD`, one day for `WALLET`, and two days for `ECHECK`, rendered as
        `YYYY-MM-DD`."

        Design: Corner/state_machines/capture_stamps_clock_and_value_date
        """
        ctx = setup_cf_checkout(with_card=True, with_echeck=True)
        set_clock("2026-09-10T00:00:00Z")
        card_paid = pay(ctx["service"]["id"], ctx["payer"]["id"], ctx["card"]["id"], 100000, "CARD")
        ech_paid = pay(ctx["service"]["id"], ctx["payer"]["id"], ctx["echeck"]["id"], 50000, "ECHECK")
        card_txn = capture(card_paid["transaction"]["id"])
        ech_txn = capture(ech_paid["transaction"]["id"])
        assert card_txn["funds_status"] == "CAPTURED"
        assert _parse(card_txn["captured_at"]) == _parse("2026-09-10T00:00:00Z")
        assert card_txn["value_date"] == "2026-09-11"  # CARD lag 1 day
        assert ech_txn["funds_status"] == "CAPTURED"
        assert ech_txn["value_date"] == "2026-09-12"  # ECHECK lag 2 days
        assert card_txn["version"] == 2 and ech_txn["version"] == 2


class TestVoidTerminality:
    def test_void_after_capture_rejected_invalid_state(self, api):
        """PRD §3.4: "Voiding an `AUTHORIZED` transaction is terminal: the
        transaction moves to `VOIDED`, the authorization is released, and it
        can never be captured, settled, refunded, returned or charged back —
        any later funds-flow operation against it reports `ERR_INVALID_STATE`."

        Design: Corner/state_machines/void_after_capture_rejected_invalid_state
        """
        ctx = setup_captured_card()
        resp = api_client.void_transaction(ctx["transaction"]["id"], AA_LEAD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_transaction(ctx["transaction"]["id"])["funds_status"] == "CAPTURED"

    def test_voided_terminal_lockdown(self, api):
        """PRD §3.4: "Voiding an `AUTHORIZED` transaction is terminal: the
        transaction moves to `VOIDED`, the authorization is released, and it
        can never be captured, settled, refunded, returned or charged back —
        any later funds-flow operation against it reports `ERR_INVALID_STATE`."

        Design: Corner/state_machines/voided_terminal_lockdown
        """
        ctx = setup_cf_checkout(with_echeck=True)
        paid = pay(ctx["service"]["id"], ctx["payer"]["id"], ctx["echeck"]["id"], 50000, "ECHECK")
        txn = paid["transaction"]
        void_transaction(txn["id"])
        assert get_transaction(txn["id"])["funds_status"] == "VOIDED"
        for resp in (
            api_client.capture_transaction(txn["id"], AA_LEAD),
            api_client.ach_return_transaction(txn["id"], PA),
            api_client.re_present_transaction(txn["id"], AA_LEAD),
        ):
            validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        final = get_transaction(txn["id"])
        assert final["funds_status"] == "VOIDED"
        assert final["representment_count"] == 0
        assert list_batches(ctx["agency"]["id"]) == [], "no batch may be auto-created for a VOIDED txn"

    def test_second_capture_rejected_not_idempotent(self, api):
        """PRD §2.8: "`ERR_INVALID_STATE` for any other impermissible state —
        including authorizing a quote that is already `CONSUMED` or `VOIDED`,
        capturing a `VOIDED` transaction, deciding an already-decided refund,
        or recording an outcome on an `OPENED` chargeback before its
        deadline."

        Design: Corner/state_machines/second_capture_rejected_not_idempotent
        """
        ctx = setup_captured_card(capture_clock="2026-09-10T00:00:00Z")
        first = ctx["transaction"]
        set_clock("2026-09-12T00:00:00Z")
        resp = api_client.capture_transaction(first["id"], AA_LEAD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_transaction(first["id"])
        assert _parse(after["captured_at"]) == _parse("2026-09-10T00:00:00Z")
        assert after["value_date"] == "2026-09-11", "the later clock must not leak into the first capture"


class TestMethodGatedOperations:
    def test_return_not_permitted_on_card(self, api):
        """PRD §3.6: "An ACH return can be recorded — by `PlatformAdmin` —
        against a transaction in `SETTLED` or `RE_PRESENTED`, and only for an
        `ECHECK` payment; a return against any other method is rejected with
        `ERR_RETURN_NOT_PERMITTED`."

        Design: Corner/errors/err_return_not_permitted_on_card
        """
        ctx = setup_captured_card(capture_clock="2026-09-10T00:00:00Z")
        batch = open_and_close_batch(ctx["agency"]["id"], "2026-09-11")
        settled = get_transaction(ctx["transaction"]["id"])
        assert settled["funds_status"] == "SETTLED"
        resp = api_client.ach_return_transaction(settled["id"], PA)
        validate_error(resp, ApiErrorId.ERR_RETURN_NOT_PERMITTED)
        after = get_transaction(settled["id"])
        assert after["funds_status"] == "SETTLED"
        assert after["current_batch_id"] == batch["id"]

    def test_chargeback_not_permitted_on_echeck(self, api):
        """PRD §3.7: "Chargebacks exist only for `CARD` transactions in a
        fundable state — `CAPTURED`, `SETTLED` or `RE_PRESENTED`; any other
        method or state is rejected with `ERR_CHARGEBACK_NOT_PERMITTED`".

        Design: Corner/errors/err_chargeback_not_permitted_on_echeck
        """
        ctx = setup_captured_echeck()
        resp = api_client.create_chargeback(
            create_chargeback_payload(ctx["transaction"]["id"], "FRAUD"), PA
        )
        validate_error(resp, ApiErrorId.ERR_CHARGEBACK_NOT_PERMITTED)


class TestRefundStateBeatsFiscal:
    def _voided_card_txn(self):
        ctx = setup_cf_checkout(with_card=True)
        paid = pay(ctx["service"]["id"], ctx["payer"]["id"], ctx["card"]["id"], 100000, "CARD")
        void_transaction(paid["transaction"]["id"])
        return ctx, paid["transaction"]

    def test_refund_on_voided_transaction_rejected_invalid_state(self, api):
        """PRD §3.7: "The underlying transaction must be in `CAPTURED`,
        `SETTLED` or `RE_PRESENTED`; any other funds state is rejected with
        `ERR_INVALID_STATE`."
        PRD §2.8: "When a single request would fail several checks, the checks
        are evaluated in a fixed priority order and the request reports the
        error of the check with the lowest priority number."

        Design: Difficulty/priority_pair_validation_conflict/refund_on_voided_state_beats_amount_fiscal
        """
        ctx, txn = self._voided_card_txn()
        resp = api_client.create_refund(
            create_refund_payload(txn["id"], 99999999, reason="dual failure probe"),
            AA_LEAD,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_refund_on_voided_persists_nothing(self, api):
        """PRD §3.7: "any other funds state is rejected with
        `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/refund_on_voided_state_beats_amount_fiscal
        """
        ctx, txn = self._voided_card_txn()
        resp = api_client.create_refund(
            create_refund_payload(txn["id"], 99999999, reason="dual failure probe"),
            AA_LEAD,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        data, _ = validate_paginated(api_client.list_transaction_refunds(txn["id"], PA))
        assert data == [], "no refund row may be created against a VOIDED transaction"
        assert get_transaction(txn["id"])["funds_status"] == "VOIDED"
