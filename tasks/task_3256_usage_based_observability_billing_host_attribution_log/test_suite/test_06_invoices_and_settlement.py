"""Invoices: per-line rounding, pinned sum order, lifecycle, and period
settlement (PRD §2.7, §3.9)."""
from test_helpers import (
    ApiErrorId,
    assert_invoice_line,
    get_meter_accumulator,
    post_usage,
    setup_account_with_period,
    setup_closed_period_with_draft_invoice,
    setup_paid_invoice,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import BA, close_period, create_active_commitment


def _lines(api, account_id, invoice_id):
    lines = validate_success(api.list_invoice_lines(account_id, invoice_id, BA))
    for line in lines:
        assert_invoice_line(line)
    return lines


class TestPerLineRounding:
    def test_committed_and_overage_rounded_separately_then_summed(self, api):
        """PRD §3.9: "for each line, the committed portion's amount is the line's
        committed quantity times the commitment's `committed_unit_rate_cents`,
        rounded half-up to integer cents; the overage portion's amount is the
        overage quantity times the `overage_unit_rate_cents`, rounded half-up to
        integer cents; and the line's `amount_cents` is the sum of those two
        already-rounded amounts."

        Design: Difficulty/combinatorial_formula/invoice_total_per_line_rounding_then_sum
        """
        account, period = setup_account_with_period(name="Rounding Test")
        commitment, account = create_active_commitment(
            account["id"], meter="INFRA_HOST", committed_quantity=4,
            committed_rate=13, overage_rate=26,
        )
        post_usage(account["id"], period["id"], "INFRA_HOST", 4)
        close_period(account["id"], period["id"])
        invoices = validate_success(
            api.list_invoices_flat(BA, params={"billing_period_id": period["id"]})
        )
        invoice_id = invoices[0]["id"]
        issued = validate_success(api.issue_invoice(account["id"], invoice_id, BA))
        lines = _lines(api, account["id"], invoice_id)
        host_lines = [l for l in lines if l["meter"] == "INFRA_HOST"]
        assert len(host_lines) == 1
        # 4 units x 13 cents committed = 52; 0 overage x 26 = 0; line = 52 + 0.
        assert host_lines[0]["rated_quantity"] == 4
        assert host_lines[0]["amount_cents"] == 52
        # The invoice total is the plain sum of the already-rounded line amounts.
        assert issued["total_amount_cents"] == sum(l["amount_cents"] for l in lines)

    def test_total_is_plain_sum_of_rounded_lines(self, api):
        """PRD §2.7: "When an invoice is issued, each line's amount is fully
        computed and rounded first; the invoice's `total_amount_cents` is the plain
        sum of the already-rounded line amounts. Summing unrounded line values and
        rounding once at the end is explicitly forbidden — the two orders can differ
        by cents, and the pinned order is per-line-then-sum."

        Design: Difficulty/combinatorial_formula/invoice_total_per_line_rounding_then_sum
        """
        account, period = setup_account_with_period(name="Pin Sum")
        commitment, account = create_active_commitment(
            account["id"], meter="TRACE", committed_quantity=3,
            committed_rate=7, overage_rate=11,
        )
        post_usage(account["id"], period["id"], "TRACE", 3)
        post_usage(account["id"], period["id"], "SYNTHETIC", 2)
        close_period(account["id"], period["id"])
        invoices = validate_success(
            api.list_invoices_flat(BA, params={"billing_period_id": period["id"]})
        )
        invoice_id = invoices[0]["id"]
        issued = validate_success(api.issue_invoice(account["id"], invoice_id, BA))
        lines = _lines(api, account["id"], invoice_id)
        assert any(l["meter"] == "TRACE" for l in lines)
        assert issued["total_amount_cents"] == sum(l["amount_cents"] for l in lines)
        assert issued["status"] == "ISSUED"


class TestInvoiceLifecycle:
    def test_pay_from_draft_rejected(self, api):
        """PRD §3.9: "A `BillingAdmin` issues a draft invoice, moving it from
        `DRAFT` to `ISSUED`." "From `ISSUED`, the invoice reaches a terminal state
        in one of two ways: payment moves it to `PAID` ..., or voiding moves it to
        `VOID`."
        PRD §2.5: "Entity state preconditions. The action-specific state machine
        precondition must hold ... — otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/invalid_transition_invoice_pay_from_draft
        """
        account, period, invoice = setup_closed_period_with_draft_invoice(
            name="Inv", usage=[("TRACE", 1)]
        )
        assert invoice["status"] == "DRAFT"
        resp = api.pay_invoice(account["id"], invoice["id"], BA)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_void_from_draft_rejected(self, api):
        """PRD §3.9: "From `ISSUED`, the invoice reaches a terminal state in one of
        two ways: payment moves it to `PAID` ..., or voiding moves it to `VOID`."
        PRD §2.5: "Entity state preconditions. The action-specific state machine
        precondition must hold ... — otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/invalid_transition_invoice_pay_from_draft
        """
        account, period, invoice = setup_closed_period_with_draft_invoice(
            name="InvVoid", usage=[("TRACE", 1)]
        )
        resp = api.void_invoice(account["id"], invoice["id"], BA)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_paid_invoice_cannot_be_voided(self, api):
        """PRD §3.9: "From `ISSUED`, the invoice reaches a terminal state in one of
        two ways: payment moves it to `PAID` (and keeps the account's `standing` at
        `GOOD`), or voiding moves it to `VOID`."
        PRD §2.5: "Entity state preconditions. The action-specific state machine
        precondition must hold ... — otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/terminal_state_lockdown_paid_invoice_cannot_void
        """
        account, period, invoice = setup_paid_invoice(
            name="PaidInv", usage=[("TRACE", 1)]
        )
        assert invoice["status"] == "PAID"
        resp = api.void_invoice(account["id"], invoice["id"], BA)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_paid_invoice_cannot_be_repaid(self, api):
        """PRD §3.9: "From `ISSUED`, the invoice reaches a terminal state in one of
        two ways: payment moves it to `PAID` (and keeps the account's `standing` at
        `GOOD`), or voiding moves it to `VOID`."

        Design: Corner/state_machines/terminal_state_lockdown_paid_invoice_cannot_void
        """
        account, period, invoice = setup_paid_invoice(
            name="PaidInv2", usage=[("TRACE", 1)]
        )
        resp = api.pay_invoice(account["id"], invoice["id"], BA)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        # Paying keeps the account's standing at GOOD.
        account = validate_success(api.get_billing_account(account["id"], BA))
        assert account["standing"] == "GOOD"


class TestPeriodSettlement:
    def test_settle_requires_invoice_terminal(self, api):
        """PRD §3.9: "a `BillingAdmin` settles the period, moving it from `CLOSED`
        to the terminal `SETTLED` state; settlement requires the period's invoice to
        be `PAID` or `VOID`."
        PRD §2.5: "Entity state preconditions. The action-specific state machine
        precondition must hold ... — otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/terminal_state_lockdown_paid_invoice_cannot_void
        """
        account, period, invoice = setup_closed_period_with_draft_invoice(
            name="Settle Gate", usage=[("TRACE", 1)]
        )
        # Invoice still DRAFT: settle must be refused.
        resp = api.settle_billing_period(account["id"], period["id"], BA)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_settle_after_payment_locks_period(self, api):
        """PRD §3.9: "With the invoice terminal, a `BillingAdmin` settles the
        period, moving it from `CLOSED` to the terminal `SETTLED` state; settlement
        requires the period's invoice to be `PAID` or `VOID`. Settling locks all
        usage records and meter accumulators under the period against further
        mutation."

        Design: Corner/state_machines/terminal_state_lockdown_paid_invoice_cannot_void
        """
        from test_helpers import setup_settled_period

        account, period, invoice = setup_settled_period(
            name="Settled", usage=[("TRACE", 2)], pay=True
        )
        assert period["status"] == "SETTLED"
        assert invoice["status"] == "PAID"
        # A settled period rejects any further usage write.
        resp = api.create_usage_record(
            account["id"], period["id"], {"meter": "TRACE", "quantity": 1},
            {"X-User-ID": "ia", "X-User-Role": "IngestionAgent"},
        )
        validate_error(resp, ApiErrorId.ERR_PERIOD_CLOSED.value)
