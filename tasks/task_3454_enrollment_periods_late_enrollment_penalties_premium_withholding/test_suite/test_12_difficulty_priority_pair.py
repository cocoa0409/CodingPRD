"""Difficulty coverage: validation-priority pairs — when two rules fail on
one request, the check the PRD runs first reports the error."""

from test_helpers import (
    ApiErrorId,
    advance_clock_and_run_cycle,
    enroll,
    enrollment_payload,
    make_beneficiary_headers,
    pay_invoice_in_full,
    pay_invoice_payload,
    register_beneficiary,
    set_clock,
    setup_billed_enrollment,
    validate_error,
)


class TestNoOpenWindowBeatsDuplicateEnrollment:
    """An enrollment request that violates both the window rule and the
    duplicate-part rule must surface the window error."""

    def _setup_active_part_b(self, client):
        set_clock(client, "2025-06-10T00:00:00Z")
        beneficiary = register_beneficiary(
            client, date_of_birth="1960-06-10", full_name="Polly Priority"
        )
        enroll(client, beneficiary, part="PART_B")
        advance_clock_and_run_cycle(client, "2025-07-05T00:00:00Z")
        return beneficiary

    def test_no_window_and_duplicate_yields_window_error(self, client):
        """PRD section 3.2: "Three checks share this endpoint and are
        evaluated in a pinned order: first whether any enrollment window
        governs the clock month, then whether a duplicate enrollment exists,
        then whether the requested part is supported." PRD section 2.8: "a
        request that would fail two checks is rejected with the error from the
        check that runs first."

        Design: Difficulty/priority_pair_validation_conflict/no_open_window_beats_duplicate_enrollment
        """
        beneficiary = self._setup_active_part_b(client)
        # Clock 2026-06: IEP [2025-03, 2025-09] expired, no SEP, not GEP
        # season — and an ACTIVE PART_B enrollment already exists.
        set_clock(client, "2026-06-10T00:00:00Z")
        response = client.create_enrollment(
            enrollment_payload(beneficiary["id"], "PART_B"),
            headers=make_beneficiary_headers(beneficiary["id"]),
        )
        validate_error(response, ApiErrorId.ERR_NO_OPEN_ENROLLMENT_WINDOW)

    def test_duplicate_part_surfaces_when_window_governs(self, client):
        """PRD section 3.2: "A new enrollment is rejected with
        `ERR_DUPLICATE_ENROLLMENT` when any other CoverageEnrollment already
        exists for the same beneficiary and the same `part` in `PENDING` or
        `ACTIVE` status." PRD section 3.2: "Failing both, the calendar General
        Enrollment Period governs during January through March."

        Design: Difficulty/priority_pair_validation_conflict/no_open_window_beats_duplicate_enrollment
        """
        beneficiary = self._setup_active_part_b(client)
        set_clock(client, "2027-02-10T00:00:00Z")  # GEP governs the clock
        response = client.create_enrollment(
            enrollment_payload(beneficiary["id"], "PART_B"),
            headers=make_beneficiary_headers(beneficiary["id"]),
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_ENROLLMENT)


class TestInvoiceStateBeatsPaymentAmountMismatch:
    """Paying an already-PAID invoice with a wrong amount violates both the
    payable-state guard and the exact-amount guard; the state guard wins."""

    def test_pay_paid_invoice_reports_state_not_amount(self, client):
        """PRD section 3.7: "Two guards apply in order: the invoice must be
        payable — `ISSUED` or `PAST_DUE`, with `PAID`, `CANCELLED`, and
        `WRITTEN_OFF` rejected as `ERR_INVOICE_NOT_PAYABLE` — and then the
        payment must equal the invoice's `outstanding_cents` exactly, neither
        partial nor overpaid, otherwise `ERR_PAYMENT_AMOUNT_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/invoice_state_beats_payment_amount_mismatch
        """
        beneficiary, _enrollment, invoice = setup_billed_enrollment(client)
        paid = pay_invoice_in_full(client, invoice)
        assert paid["status"] == "PAID"
        assert paid["outstanding_cents"] == 0

        response = client.pay_invoice(
            invoice["id"],
            pay_invoice_payload(1),
            headers=make_beneficiary_headers(beneficiary["id"]),
        )
        validate_error(response, ApiErrorId.ERR_INVOICE_NOT_PAYABLE)

    def test_wrong_amount_on_payable_invoice_reports_mismatch(self, client):
        """PRD section 2.8: "**Fiscal exactness** — payment amount equality,
        `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422), is always the last check on
        the payment endpoint, so a payment with a wrong amount against a
        payable invoice reports the mismatch rather than any business rule."

        Design: Difficulty/priority_pair_validation_conflict/invoice_state_beats_payment_amount_mismatch
        """
        beneficiary, _enrollment, invoice = setup_billed_enrollment(client)
        assert invoice["status"] == "ISSUED"
        response = client.pay_invoice(
            invoice["id"],
            pay_invoice_payload(18000),
            headers=make_beneficiary_headers(beneficiary["id"]),
        )
        validate_error(response, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)
