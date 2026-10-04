"""Non-linear state machines: the Subscription cycle and the BankTransaction
cycle with a parallel axis.

The Subscription cycle is ACTIVE -> SUSPENDED -> ACTIVE via invoice aging +
resume; the BankTransaction cycle is UNCATEGORIZED -> CATEGORIZED ->
UNCATEGORIZED -> EXCLUDED -> UNCATEGORIZED with reconciled_in_id as the
gating axis.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers.fixtures import (
    add_bank_connection,
    add_category,
    add_payroll,
    create_plus_plan,
    create_primary_admin,
    create_simple_start_plan,
    create_company,
    accept_user,
    activate_subscription,
    get_subscription,
    ingest_txn,
    issue_invoice_now,
    reset_clock,
    set_clock,
    setup_company_with_active_subscription,
)
from test_helpers.test_users import (
    PLATFORM_ADMIN,
    make_company_user_headers,
)


class TestSubscriptionCyclicLoop:
    """ACTIVE -> SUSPENDED -> ACTIVE round trip with payroll compensation."""

    def _drive_to_suspended(self, client, company_id, admin_id, subscription_id):
        """Issue an invoice, let it age past 30 days, then read the sub."""
        invoice = issue_invoice_now(client, company_id, subscription_id)
        set_clock(client, "2026-11-07T00:00:00Z")
        sub = get_subscription(client, company_id)
        return invoice, sub

    def _settle_via_payment_simulation(self, client, invoice_id):
        """Settle an invoice through the platform's simulated payment driver.

        PRD 3.5 pins the manual pay endpoint to ISSUED invoices only
        ("Attempting to pay an invoice that is not ISSUED ... is rejected
        with ERR_INVOICE_NOT_PAYABLE"), so the PRD-named payment path that
        can settle a PAST_DUE invoice is the payment simulation driver:
        "a second driver simulates a payment outcome ... against an invoice
        identified by invoice_id and outcome: on SUCCEEDED the invoice moves
        ... to PAID".
        """
        response = client.simulate_payment(
            invoice_id, "SUCCEEDED", headers=PLATFORM_ADMIN
        )
        assert response.status_code in (200, 201), (
            "payment simulation failed: {0}".format(response.text)
        )
        return response

    def test_active_suspended_active_cycle_with_payroll_compensation(self, client):
        """PRD 3.3: "If any invoice stays `PAST_DUE` for thirty days or
        longer, the subscription is suspended: `ACTIVE` or `PAST_DUE` gives
        way to `SUSPENDED`, the payroll add-on cascades from `ACTIVE` to
        `PAUSED`, every `ACTIVE` bank connection goes `STALE`, and
        `billing_status` drops to `UNPAID`. Suspension unwinds when all
        invoices are settled — or when the primary admin resumes explicitly
        once no invoice remains in `ISSUED` or `PAST_DUE`: the subscription
        returns to `ACTIVE`, the payroll add-on compensates by moving
        `PAUSED` back to `ACTIVE`, `billing_status` returns to `CURRENT`,
        but the bank connections stay `STALE`."

        Design: Difficulty/non_linear_state_machine/subscription_cyclic_active_suspended_active_loop
        """
        reset_clock(client)
        plan = create_simple_start_plan(client)
        company = create_company(client, plan["id"], legal_name="Eta Corp")
        admin = create_primary_admin(client, company["id"])
        accept_user(client, company["id"], admin["id"])
        subscription = activate_subscription(client, company["id"], admin["id"])
        payroll = add_payroll(client, company["id"], admin["id"], "SELF_SERVICE")

        # Drive SUSPENDED via invoice aging.
        invoice, suspended = self._drive_to_suspended(
            client, company["id"], admin["id"], subscription["id"]
        )
        assert suspended["lifecycle_status"] == "SUSPENDED"
        payroll_view = get_success_data(
            client.get_payroll(company["id"], headers=PLATFORM_ADMIN)
        )
        assert payroll_view["addon_status"] == "PAUSED"

        # Settle the (now PAST_DUE) invoice via the payment simulation driver,
        # then resume.
        pay_response = self._settle_via_payment_simulation(client, invoice["id"])
        resume_response = client.resume_subscription(
            company["id"], headers=make_company_user_headers(admin["id"])
        )
        assert resume_response.status_code in (200, 201)
        resumed = get_success_data(resume_response)
        assert resumed["lifecycle_status"] == "ACTIVE"

        payroll_after = get_success_data(
            client.get_payroll(company["id"], headers=PLATFORM_ADMIN)
        )
        assert payroll_after["addon_status"] == "ACTIVE"

    def test_cycle_does_not_enter_cancelled_states(self, client):
        """PRD 3.3: "Suspension unwinds when all invoices are settled — or
        when the primary admin resumes explicitly once no invoice remains in
        `ISSUED` or `PAST_DUE`: the subscription returns to `ACTIVE`".

        Design: Difficulty/non_linear_state_machine/subscription_cyclic_active_suspended_active_loop
        """
        reset_clock(client)
        plan = create_simple_start_plan(client)
        company = create_company(client, plan["id"], legal_name="Eta2 Corp")
        admin = create_primary_admin(client, company["id"])
        accept_user(client, company["id"], admin["id"])
        subscription = activate_subscription(client, company["id"], admin["id"])

        invoice, suspended = self._drive_to_suspended(
            client, company["id"], admin["id"], subscription["id"]
        )
        assert suspended["lifecycle_status"] == "SUSPENDED"
        assert suspended["lifecycle_status"] not in (
            "CANCELLED_READ_ONLY", "CANCELLED_EXPIRED",
        )

        self._settle_via_payment_simulation(client, invoice["id"])
        resumed_response = client.resume_subscription(
            company["id"], headers=make_company_user_headers(admin["id"])
        )
        resumed = get_success_data(resumed_response)
        assert resumed["lifecycle_status"] == "ACTIVE"
        assert resumed["lifecycle_status"] != "REACTIVATED", (
            "ACTIVE-from-SUSPENDED is the cycle path; REACTIVATED is reserved "
            "for the cancel-then-reactivate path"
        )


class TestBankTransactionCycleWithParallelAxis:
    """UNCATEGORIZED -> CATEGORIZED -> UNCATEGORIZED -> EXCLUDED -> UNCATEGORIZED
    while reconciled_in_id stays null."""

    def _setup_uncategorized_txn(self, client):
        plan = create_plus_plan(client)
        scenario = setup_company_with_active_subscription(
            client, plan_id=plan["id"], legal_name="Iota Corp"
        )
        company = scenario["company"]
        admin = scenario["admin"]
        connection = add_bank_connection(client, company["id"], admin["id"])
        category = add_category(
            client, company["id"], admin["id"], name="Meals", tax_line="SCH-C-L23"
        )
        txn = ingest_txn(
            client, company["id"], connection["id"],
            posted_at="2026-09-15T00:00:00Z", amount_cents=-5000,
            payee_raw="CHIPOTLE #123",
        )
        return scenario, connection, category, txn

    def test_categorize_uncategorize_exclude_unexclude_cycle(self, client):
        """PRD 3.6: "A `CATEGORIZED` transaction can be sent back to
        `UNCATEGORIZED`, clearing both fields, or excluded entirely from
        `UNCATEGORIZED`, `RULE_SUGGESTED`, or `CATEGORIZED`; an `EXCLUDED`
        transaction no longer counts toward reconciliation totals and can
        later be restored to `UNCATEGORIZED`."

        Design: Difficulty/non_linear_state_machine/bank_transaction_parallel_dims_recon_lock_independence
        """
        reset_clock(client)
        scenario, connection, category, txn = self._setup_uncategorized_txn(client)
        company = scenario["company"]
        admin = scenario["admin"]
        admin_headers = make_company_user_headers(admin["id"])

        # UNCATEGORIZED -> CATEGORIZED
        r1 = client.categorize_bank_transaction(
            company["id"], txn["id"], {"category_id": category["id"]},
            headers=admin_headers,
        )
        assert get_success_data(r1)["txn_status"] == "CATEGORIZED"

        # CATEGORIZED -> UNCATEGORIZED
        r2 = client.uncategorize_bank_transaction(
            company["id"], txn["id"], headers=admin_headers
        )
        assert get_success_data(r2)["txn_status"] == "UNCATEGORIZED"

        # UNCATEGORIZED -> EXCLUDED
        r3 = client.exclude_bank_transaction(
            company["id"], txn["id"], headers=admin_headers
        )
        assert get_success_data(r3)["txn_status"] == "EXCLUDED"

        # EXCLUDED -> UNCATEGORIZED
        r4 = client.unexclude_bank_transaction(
            company["id"], txn["id"], headers=admin_headers
        )
        final_txn = get_success_data(r4)
        assert final_txn["txn_status"] == "UNCATEGORIZED"
        assert final_txn.get("reconciled_in_id") is None, (
            "parallel axis (reconciled_in_id) untouched by the cycle"
        )

    def test_uncategorize_clears_category_and_matched_rule(self, client):
        """PRD 3.6: "A `CATEGORIZED` transaction can be sent back to
        `UNCATEGORIZED`, clearing both fields".

        Design: Difficulty/non_linear_state_machine/bank_transaction_parallel_dims_recon_lock_independence
        """
        reset_clock(client)
        scenario, connection, category, txn = self._setup_uncategorized_txn(client)
        company = scenario["company"]
        admin = scenario["admin"]
        admin_headers = make_company_user_headers(admin["id"])

        client.categorize_bank_transaction(
            company["id"], txn["id"], {"category_id": category["id"]},
            headers=admin_headers,
        )
        r = client.uncategorize_bank_transaction(
            company["id"], txn["id"], headers=admin_headers
        )
        body = get_success_data(r)
        assert body["txn_status"] == "UNCATEGORIZED"
        assert body.get("category_id") is None
        assert body.get("matched_rule_id") is None
