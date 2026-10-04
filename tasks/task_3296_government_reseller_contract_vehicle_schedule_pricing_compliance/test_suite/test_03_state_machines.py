"""Non-linear state machines: Order's parallel dimensions, PriceList's cycle."""
from test_helpers import (
    TEST_USERS,
    create_cleared_order,
    create_delivered_order,
    create_issued_invoice,
    setup_active_chain,
    validate_success,
)

CM = TEST_USERS["contracts_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
OPS = TEST_USERS["reseller_ops_headers"]
FIN = TEST_USERS["finance_ops_headers"]


class TestOrderParallelDimensions:
    def test_full_billing_chain_leaves_compliance_cleared(self, api):
        """PRD §3.6: "A new order begins with its compliance_status field at
        DRAFT and its billing_status field at UNBILLED — two parallel status
        dimensions that evolve independently — with origin_flag initially
        NOT_APPLICABLE and subcontract_cents at zero."

        Design: Difficulty/non_linear_state_machine/order_parallel_compliance_billing_dimensions
        """
        _, _, vehicle, price_list = setup_active_chain()
        order = create_cleared_order(vehicle["id"], price_list["id"])
        resp = api.deliver_order(order["id"], OPS)
        order = validate_success(resp)
        assert order["billing_status"] == "DELIVERED"
        assert order["compliance_status"] == "CLEARED"
        invoice = create_issued_invoice(order["id"])
        order = validate_success(api.get_order(order["id"], OPS))
        assert order["billing_status"] == "INVOICED"
        assert order["compliance_status"] == "CLEARED"
        resp = api.pay_invoice(invoice["id"], FIN)
        invoice = validate_success(resp)
        assert invoice["status"] == "PAID"
        order = validate_success(api.get_order(order["id"], OPS))
        assert order["billing_status"] == "PAID"
        assert order["compliance_status"] == "CLEARED"

    def test_invoice_pay_moves_both_invoice_and_order(self, api):
        """PRD §3.8: "A FinanceOps operator records payment against an ISSUED
        or OVERDUE invoice, moving it to PAID; the source order's billing
        status moves to PAID in step, and the sales report totals are
        unchanged because the invoice was already counted at issue."

        Design: Difficulty/non_linear_state_machine/order_parallel_compliance_billing_dimensions
        """
        _, _, vehicle, price_list = setup_active_chain()
        order = create_delivered_order(vehicle["id"], price_list["id"])
        invoice = create_issued_invoice(order["id"])
        order = validate_success(api.get_order(order["id"], OPS))
        assert order["billing_status"] == "INVOICED"
        resp = api.pay_invoice(invoice["id"], FIN)
        validate_success(resp)
        invoice = validate_success(api.get_invoice(invoice["id"], FIN))
        assert invoice["status"] == "PAID"
        order = validate_success(api.get_order(order["id"], OPS))
        assert order["billing_status"] == "PAID"
        assert order["compliance_status"] == "CLEARED"


class TestPriceListCyclicRevisionLoop:
    def test_active_reopen_resubmit_reactivate_cycle(self, api):
        """PRD §3.3: "A ContractsManager may reopen an ACTIVE list, moving it
        back to DRAFT for revision — a cyclic loop that allows a list to be
        edited and resubmitted."

        Design: Difficulty/non_linear_state_machine/price_list_cyclic_revision_loop
        """
        _, _, _, price_list = setup_active_chain()
        resp = api.reopen_price_list(price_list["id"], CM)
        pl = validate_success(resp)
        assert pl["status"] == "DRAFT"
        v_after_reopen = pl["version"]
        resp = api.submit_price_list(price_list["id"], CM)
        pl = validate_success(resp)
        assert pl["status"] == "SUBMITTED"
        resp = api.activate_price_list(price_list["id"], CO)
        pl = validate_success(resp)
        assert pl["status"] == "ACTIVE"

    def test_version_monotonically_increases_across_cycle(self, api):
        """PRD §2.4: "Any mutation of the entity — a state transition, a
        patch, a cascade side-effect from a parent — bumps version by one and
        refreshes updated_at."

        Design: Difficulty/non_linear_state_machine/price_list_cyclic_revision_loop
        """
        _, _, _, price_list = setup_active_chain()
        v_initial = price_list["version"]
        pl = validate_success(api.reopen_price_list(price_list["id"], CM))
        v_reopen = pl["version"]
        assert v_reopen > v_initial
        pl = validate_success(api.submit_price_list(price_list["id"], CM))
        v_resubmit = pl["version"]
        assert v_resubmit > v_reopen
        pl = validate_success(api.activate_price_list(price_list["id"], CO))
        assert pl["version"] > v_resubmit
        assert pl["status"] == "ACTIVE"
