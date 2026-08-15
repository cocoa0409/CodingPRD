"""State-machine guards and uniqueness-scope release on client, carrier,
shipment, and invoice lifecycles.

Covers PRD §2.8 state legality and the client lifecycle gate, §3.1
termination preconditions, §3.2 carrier onboarding/offboarding, and §3.3
uniqueness scopes that release on void.
"""
from test_helpers import (
    ADMIN,
    ANALYST,
    FINANCE,
    ApiErrorId,
    build_cleared_invoice,
    capture_invoice,
    create_active_client,
    create_carrier,
    create_invoice,
    create_shipment,
    get_invoice,
    rate_invoice,
    set_clock,
    setup_standard_chain,
    validate_error,
    validate_success,
)


class TestInvoiceStateGuards:
    def test_capture_on_cleared_invoice_is_invalid_state(self, api):
        """PRD §3.3: "Capture (`RECEIVED` → `CAPTURED`) is an `AuditAnalyst`
        action and requires the owning client to be `ACTIVE`, failing with
        `ERR_CLIENT_NOT_ACTIVE` otherwise." Capture is declared only from
        RECEIVED, and PRD §2.8: "**State legality.** The target resource must be
        in a state that permits the requested transition; failures yield
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/invoice_capture_from_cleared_returns_invalid_state
        """
        chain = setup_standard_chain()
        invoice = build_cleared_invoice(chain)
        assert invoice["audit_status"] == "CLEARED", "Setup failed: not CLEARED"
        res = api.capture_invoice(invoice["id"], ANALYST)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        current = get_invoice(invoice["id"])
        assert current["audit_status"] == "CLEARED"

    def test_voided_invoice_is_terminal_on_audit_dimension(self, api):
        """PRD §3.3: "An invoice that should never have entered the system can
        be voided while it is `RECEIVED` or `CAPTURED`, moving it to audit
        status `VOIDED`, terminal on the audit dimension; voiding releases the
        `invoice_number` back into the uniqueness scope so a corrected invoice
        may reuse it." From VOIDED no further transition is declared, so rate
        and void both fail per PRD §2.8 stage 6 (`ERR_INVALID_STATE`).

        Design: Corner/state_machines/voided_invoice_terminal_lockdown
        """
        chain = setup_standard_chain(with_contract=False)
        invoice = create_invoice(chain["client"]["id"], chain["carrier"]["id"])
        validate_success(api.void_invoice(invoice["id"], ANALYST), 200)
        res_rate = api.rate_invoice(invoice["id"], {}, ANALYST)
        validate_error(res_rate, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        res_void = api.void_invoice(invoice["id"], ANALYST)
        validate_error(res_void, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_invoice_number_released_into_uniqueness_scope_after_void(self, api):
        """PRD §3.3: "the `invoice_number` must not repeat another non-voided
        invoice of the same client and carrier (`ERR_DUPLICATE_INVOICE_NUMBER`,
        and this exact-duplicate rejection happens at creation time, before the
        invoice ever reaches capture)". PRD §3.3: "voiding releases the
        `invoice_number` back into the uniqueness scope so a corrected invoice
        may reuse it."

        Design: Corner/entities/invoice_number_released_after_void
        """
        chain = setup_standard_chain(with_contract=False)
        first = create_invoice(
            chain["client"]["id"], chain["carrier"]["id"], invoice_number="INV-DUP"
        )
        capture_invoice(first["id"])
        dup = api.create_invoice(
            chain["client"]["id"],
            {
                "carrier_id": chain["carrier"]["id"],
                "invoice_number": "INV-DUP",
                "invoice_date": "2026-08-03",
                "currency": "USD",
                "billed_total_minor": 100,
                "lines": [{"charge_code": "OTHER", "billed_amount_minor": 100}],
            },
            ANALYST,
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_INVOICE_NUMBER, expected_status=409)
        validate_success(api.void_invoice(first["id"], ANALYST), 200)
        recreated = create_invoice(
            chain["client"]["id"],
            chain["carrier"]["id"],
            invoice_number="INV-DUP",
            billed_total_minor=100,
            lines=[{"charge_code": "OTHER", "billed_amount_minor": 100}],
        )
        assert recreated["id"] != first["id"]
        assert recreated["invoice_number"] == "INV-DUP"


class TestCarrierLifecycle:
    def test_approve_onboard_twice_is_invalid_state(self, api):
        """PRD §3.2: "A carrier starts `PENDING_ONBOARD`; onboarding approval
        moves it to `ACTIVE`." Approval is declared only from PENDING_ONBOARD,
        so a second approval fails per PRD §2.8 stage 6: "The target resource
        must be in a state that permits the requested transition; failures
        yield `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/carrier_approve_twice_rejected
        """
        set_clock()
        client = create_active_client()
        carrier = create_carrier(client["id"])
        validate_success(api.approve_carrier_onboard(carrier["id"], ADMIN), 200)
        res = api.approve_carrier_onboard(carrier["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_offboard_blocked_while_invoices_open(self, api):
        """PRD §3.2: "offboarding moves either `ACTIVE` or `SUSPENDED` →
        `OFFBOARDED` — but only once the carrier holds no invoice with
        `payment_status` `UNPAID` or `SCHEDULED`; open invoices block
        offboarding with `ERR_CARRIER_HAS_OPEN_INVOICES`."

        Design: Corner/validations/carrier_offboard_with_open_invoices_rejected
        """
        chain = setup_standard_chain()
        invoice = build_cleared_invoice(chain)
        assert invoice["payment_status"] == "UNPAID", "Setup failed: not UNPAID"
        res = api.offboard_carrier(chain["carrier"]["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_CARRIER_HAS_OPEN_INVOICES, expected_status=409)


class TestShipmentUniqueness:
    def test_pro_number_reused_while_live_then_released_after_void(self, api):
        """PRD §3.3: "A PRO number is unique per client and carrier among
        shipments that have not been voided: reusing a live one fails with
        `ERR_DUPLICATE_PRO_NUMBER`." PRD §3.3: "Voiding moves `REGISTERED` →
        `VOIDED` and is allowed only while no non-voided invoice references the
        shipment — attempting it otherwise fails with `ERR_INVALID_STATE` — and
        voiding releases the PRO number back into the uniqueness scope."

        Design: Corner/entities/pro_number_uniqueness_and_release_after_void
        """
        chain = setup_standard_chain(with_contract=False)
        first = create_shipment(
            chain["client"]["id"], chain["carrier"]["id"], pro_number="PRO-1"
        )
        dup = api.create_shipment(
            chain["client"]["id"],
            {
                "carrier_id": chain["carrier"]["id"],
                "pro_number": "PRO-1",
                "ship_date": "2026-08-02",
                "origin_country": "US",
                "dest_country": "CA",
                "mode": "LTL",
                "actual_weight_kg": 10,
            },
            ANALYST,
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_PRO_NUMBER, expected_status=409)
        validate_success(api.void_shipment(first["id"], ANALYST), 200)
        recreated = create_shipment(
            chain["client"]["id"], chain["carrier"]["id"], pro_number="PRO-1"
        )
        assert recreated["id"] != first["id"]
        assert recreated["pro_number"] == "PRO-1"


class TestClientLifecycleGate:
    def test_suspended_client_rejects_business_mutation(self, api):
        """PRD §2.8: "**Client lifecycle gate.** Business mutations on a
        client's resources require the client to be `ACTIVE`; failures yield
        `ERR_CLIENT_NOT_ACTIVE` (HTTP 409). The gate applies to every mutating
        operation under a client scope except the client lifecycle transitions
        themselves and the logical clock."

        Design: Corner/validations/client_suspended_blocks_business_mutation
        """
        chain = setup_standard_chain(with_contract=False)
        validate_success(api.suspend_client(chain["client"]["id"], ADMIN), 200)
        res = api.create_invoice(
            chain["client"]["id"],
            {
                "carrier_id": chain["carrier"]["id"],
                "invoice_number": "INV-X",
                "invoice_date": "2026-08-03",
                "currency": "USD",
                "billed_total_minor": 100,
                "lines": [{"charge_code": "OTHER", "billed_amount_minor": 100}],
            },
            ANALYST,
        )
        validate_error(res, ApiErrorId.ERR_CLIENT_NOT_ACTIVE, expected_status=409)

    def test_terminate_blocked_with_outstanding_liability(self, api):
        """PRD §3.1: "Termination moves `ACTIVE` → `TERMINATED`, the terminal
        state, and is only granted to a settled ledger: the account's
        `outstanding_liability_minor` must be zero and no invoice may remain
        with `payment_status` `UNPAID` or `SCHEDULED`; otherwise termination is
        refused with `ERR_CLIENT_NOT_SETTLED`."

        Design: Corner/validations/client_terminate_with_liability_rejected
        """
        chain = setup_standard_chain()
        build_cleared_invoice(chain)
        res = api.terminate_client(chain["client"]["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_CLIENT_NOT_SETTLED, expected_status=409)


class TestWriteOffGuard:
    def test_write_off_requires_cleared_audit(self, api):
        """PRD §3.8: "a `FinanceController` may write off an invoice whose
        audit stands `CLEARED` while payment is still `UNPAID`, moving payment
        to `WRITTEN_OFF` (`ERR_INVOICE_NOT_PAYABLE` when the preconditions are
        unmet)". A RATED invoice fails the audit-status precondition.

        Design: Corner/state_machines/write_off_unrated_invoice_rejected
        """
        chain = setup_standard_chain()
        shipment = create_shipment(chain["client"]["id"], chain["carrier"]["id"])
        invoice = create_invoice(
            chain["client"]["id"],
            chain["carrier"]["id"],
            shipment_id=shipment["id"],
        )
        capture_invoice(invoice["id"])
        rated = rate_invoice(invoice["id"])
        assert rated["audit_status"] == "RATED", "Setup failed: not RATED"
        res = api.write_off_invoice(invoice["id"], FINANCE)
        validate_error(res, ApiErrorId.ERR_INVOICE_NOT_PAYABLE, expected_status=409)
        current = get_invoice(invoice["id"])
        assert current["payment_status"] == "UNPAID"
