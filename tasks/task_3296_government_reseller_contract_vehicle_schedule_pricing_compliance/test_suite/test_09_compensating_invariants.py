"""Compensating invariants: dispute ledger zero-drift; invoice void zero-drift."""
from test_helpers import (
    TEST_USERS,
    create_cleared_order,
    create_delivered_order,
    create_dispute,
    create_issued_invoice,
    create_order,
    setup_active_chain,
    validate_success,
)

CM = TEST_USERS["contracts_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
FIN = TEST_USERS["finance_ops_headers"]
OPS = TEST_USERS["reseller_ops_headers"]


class TestDisputeLedgerInvariant:
    def test_reject_resolution_restores_ledger_to_zero(self, api):
        """PRD §3.9: "An outcome of REJECT moves the dispute to REJECTED and
        applies a compensating adjustment: the agreement's
        dispute_credit_cents is reduced by the original amount, undoing the
        raise-time credit, so a rejected dispute nets to zero on the ledger."

        Design: Difficulty/compensating_invariant/dispute_ledger_invariant_resolve_reject_zero_drift
        """
        _, agreement, vehicle, price_list = setup_active_chain()
        order = create_order(vehicle["id"], price_list["id"])
        dispute = create_dispute(order["id"], kind="BILLING_ERROR", amount_cents=-150000)
        mid = validate_success(api.get_agreement(agreement["id"], CO))
        assert mid["dispute_credit_cents"] == -150000
        resp = api.resolve_dispute(dispute["id"], "REJECT", CO)
        dispute = validate_success(resp)
        assert dispute["status"] == "REJECTED"
        agreement = validate_success(api.get_agreement(agreement["id"], CO))
        assert agreement["dispute_credit_cents"] == 0

    def test_reject_resolution_restores_good_standing(self, api):
        """PRD §3.9: "All three resolutions recompute posture and increment
        the dispute's version; RESOLVED_CREDIT, RESOLVED_DEBIT, and REJECTED
        are all terminal."
        PRD §2.6: "otherwise, if dispute_credit_cents is strictly less than
        -100000 (that is, net debt has crossed $1,000.00), posture is ON_HOLD;
        otherwise posture is GOOD_STANDING."
        Design: Difficulty/compensating_invariant/dispute_ledger_invariant_resolve_reject_zero_drift
        """
        _, agreement, vehicle, price_list = setup_active_chain()
        order = create_order(vehicle["id"], price_list["id"])
        dispute = create_dispute(order["id"], kind="BILLING_ERROR", amount_cents=-150000)
        mid = validate_success(api.get_agreement(agreement["id"], CO))
        assert mid["posture"] == "ON_HOLD"
        api.resolve_dispute(dispute["id"], "REJECT", CO)
        agreement = validate_success(api.get_agreement(agreement["id"], CO))
        assert agreement["posture"] == "GOOD_STANDING"
        assert agreement["dispute_credit_cents"] == 0

    def test_raise_then_reject_is_net_zero_over_pair(self, api):
        """PRD §3.9: "Raising a dispute immediately adds its signed
        amount_cents to the parent agreement's dispute_credit_cents and
        recomputes the agreement's posture — open disputes count toward the
        ledger."
        PRD §3.9: "a rejected dispute nets to zero on the ledger."

        Design: Difficulty/compensating_invariant/dispute_ledger_invariant_resolve_reject_zero_drift
        """
        _, agreement, vehicle, price_list = setup_active_chain()
        before = validate_success(api.get_agreement(agreement["id"], CO))
        assert before["dispute_credit_cents"] == 0
        order = create_order(vehicle["id"], price_list["id"])
        dispute = create_dispute(order["id"], kind="BILLING_ERROR", amount_cents=-150000)
        api.resolve_dispute(dispute["id"], "REJECT", CO)
        after = validate_success(api.get_agreement(agreement["id"], CO))
        assert after["dispute_credit_cents"] == before["dispute_credit_cents"]
        assert after["posture"] == before["posture"] == "GOOD_STANDING"


class TestInvoiceVoidInvariant:
    def _setup_invoiced(self, api):
        _, agreement, vehicle, price_list = setup_active_chain()
        order = create_delivered_order(vehicle["id"], price_list["id"])
        invoice = create_issued_invoice(order["id"], period_label="2026-10")
        return agreement, order, invoice

    def _period_report(self, api, agreement_id, period_label):
        data, _meta = self._list_reports(api, agreement_id, period_label)
        assert len(data) >= 1, "Setup failed: expected an auto-upserted sales report"
        return data[0]

    def _list_reports(self, api, agreement_id, period_label):
        from prd_bench_local_runner.testing import validate_paginated
        return validate_paginated(api.list_sales_reports(
            FIN, params={"agreement_id": agreement_id, "period_label": period_label},
        ))

    def test_issue_adds_amount_to_period_report(self, api):
        """PRD §3.8: "If no DRAFT sales report exists for the (agreement,
        period_label) pair, one is upserted in DRAFT. The report's
        total_sales_cents is the sum of amount_cents across invoices for the
        period on orders routed through the agreement (order to vehicle to
        agreement), counting only invoices in ISSUED, PAID, or OVERDUE — VOID
        invoices are excluded."

        Design: Difficulty/compensating_invariant/invoice_void_invariant_sales_report_total_zero_drift
        """
        agreement, order, invoice = self._setup_invoiced(api)
        assert invoice["amount_cents"] == order["order_total_cents"] + order["teaming_surcharge_cents"]
        report = self._period_report(api, agreement["id"], "2026-10")
        assert report["total_sales_cents"] == 10000

    def test_void_subtracts_amount_back_to_zero(self, api):
        """PRD §3.8: "A FinanceOps operator may also void an ISSUED invoice;
        voiding moves the invoice to VOID (terminal), reverts the source
        order's billing status from INVOICED back to DELIVERED, subtracts the
        invoice's amount_cents from the period's total_sales_cents, and
        recomputes sb_goal_met."

        Design: Difficulty/compensating_invariant/invoice_void_invariant_sales_report_total_zero_drift
        """
        agreement, order, invoice = self._setup_invoiced(api)
        resp = api.void_invoice(invoice["id"], FIN)
        invoice = validate_success(resp)
        assert invoice["status"] == "VOID"
        order = validate_success(api.get_order(order["id"], OPS))
        assert order["billing_status"] == "DELIVERED"
        report = self._period_report(api, agreement["id"], "2026-10")
        assert report["total_sales_cents"] == 0

    def test_issue_void_pair_nets_to_zero(self, api):
        """PRD §3.8: "voiding moves the invoice to VOID (terminal), reverts
        the source order's billing status from INVOICED back to DELIVERED,
        subtracts the invoice's amount_cents from the period's
        total_sales_cents, and recomputes sb_goal_met."
        PRD §3.8: "counting only invoices in ISSUED, PAID, or OVERDUE — VOID
        invoices are excluded."

        Design: Difficulty/compensating_invariant/invoice_void_invariant_sales_report_total_zero_drift
        """
        agreement, order, invoice = self._setup_invoiced(api)
        report_after_issue = self._period_report(api, agreement["id"], "2026-10")
        assert report_after_issue["total_sales_cents"] == 10000
        api.void_invoice(invoice["id"], FIN)
        report_after_void = validate_success(
            api.get_sales_report(report_after_issue["id"], FIN)
        )
        assert report_after_void["total_sales_cents"] == 0
        invoice = validate_success(api.get_invoice(invoice["id"], FIN))
        assert invoice["status"] == "VOID"
        order = validate_success(api.get_order(order["id"], OPS))
        assert order["billing_status"] == "DELIVERED"
