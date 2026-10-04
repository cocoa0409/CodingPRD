"""Compensating invariants — forward + compensation leave a conserved
quantity unchanged.

Two conserved quantities are exercised: ACTIVE PayrollEmployee headcount
(suspend/resume cycle), and the categorized-transaction pool (rule
pause/resume round-trip).
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers.fixtures import (
    add_bank_connection,
    add_category,
    add_employee,
    add_payroll,
    add_rule,
    create_plus_plan,
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


class TestSuspendResumePreservesHeadcount:
    """Subscription suspend cascades payroll PAUSED but does NOT touch
    PayrollEmployee.employment_status; resume compensates the addon."""

    def _setup_suspended_with_employees(self, client, employee_count=2):
        plan = create_plus_plan(client)
        scenario = setup_company_with_active_subscription(
            client, plan_id=plan["id"], legal_name="Upsilon Corp"
        )
        company = scenario["company"]
        admin = scenario["admin"]
        subscription = scenario["subscription"]

        payroll = add_payroll(client, company["id"], admin["id"], "SELF_SERVICE")
        employees = []
        for i in range(employee_count):
            employees.append(
                add_employee(
                    client, company["id"], admin["id"], payroll["id"],
                    legal_name="Emp {0}".format(i),
                    hire_date="2026-09-01T00:00:00Z",
                )
            )
        invoice = issue_invoice_now(client, company["id"], subscription["id"])
        set_clock(client, "2026-11-07T00:00:00Z")
        sub = get_subscription(client, company["id"])
        assert sub["lifecycle_status"] == "SUSPENDED"
        return scenario, payroll, employees, invoice

    def _active_employee_count(self, client, company_id):
        response = client.list_payroll_employees(
            company_id, headers=PLATFORM_ADMIN,
            params={"employment_status": "ACTIVE"},
        )
        body = response.json()
        rows = body.get("data") if isinstance(body, dict) else []
        return len(rows) if isinstance(rows, list) else None

    def test_suspend_resume_round_trip_preserves_headcount(self, client):
        """PRD 3.3: "If any invoice stays `PAST_DUE` for thirty days or
        longer, the subscription is suspended: ... the payroll add-on
        cascades from `ACTIVE` to `PAUSED`, ... Suspension unwinds when all
        invoices are settled — or when the primary admin resumes explicitly
        once no invoice remains in `ISSUED` or `PAST_DUE`: the subscription
        returns to `ACTIVE`, the payroll add-on compensates by moving
        `PAUSED` back to `ACTIVE`".

        Design: Difficulty/compensating_invariant/suspension_resume_preserves_employee_headcount
        """
        reset_clock(client)
        scenario, payroll, employees, invoice = self._setup_suspended_with_employees(
            client, employee_count=2
        )
        company = scenario["company"]
        admin = scenario["admin"]
        admin_headers = scenario["admin_headers"]

        pre_count = self._active_employee_count(client, company["id"])
        assert pre_count == 2

        # Settle the (PAST_DUE) invoice through the platform's simulated
        # payment driver — PRD pins the manual pay endpoint to ISSUED invoices
        # only — then resume.
        pay = client.simulate_payment(
            invoice["id"], "SUCCEEDED", headers=PLATFORM_ADMIN
        )
        assert pay.status_code in (200, 201), (
            "payment simulation failed: {0}".format(pay.text)
        )
        client.resume_subscription(company["id"], headers=admin_headers)

        post_count = self._active_employee_count(client, company["id"])
        assert post_count == 2, (
            "suspend+resume must not change ACTIVE employee count"
        )

        payroll_after = get_success_data(
            client.get_payroll(company["id"], headers=PLATFORM_ADMIN)
        )
        assert payroll_after["addon_status"] == "ACTIVE"

    def test_suspended_alone_keeps_employees_active(self, client):
        """PRD 3.3: "the payroll add-on cascades from `ACTIVE` to `PAUSED`"
        — only the add-on is paused; the employees' employment_status is
        untouched.

        Design: Difficulty/compensating_invariant/suspension_resume_preserves_employee_headcount
        """
        reset_clock(client)
        scenario, payroll, employees, _invoice = self._setup_suspended_with_employees(
            client, employee_count=2
        )
        company = scenario["company"]

        payroll_view = get_success_data(
            client.get_payroll(company["id"], headers=PLATFORM_ADMIN)
        )
        assert payroll_view["addon_status"] == "PAUSED"

        # Every employee is still ACTIVE.
        for emp in employees:
            emp_after = get_success_data(
                client.get_payroll_employee(company["id"], emp["id"],
                                              headers=PLATFORM_ADMIN)
            )
            assert emp_after["employment_status"] == "ACTIVE"


class TestRulePauseResumePreservesCategorizedPool:
    """Pausing a rule does not un-categorize already-categorized txns;
    resuming re-evaluates the UNCATEGORIZED pool only."""

    def _setup_categorized_and_paused_rule(self, client):
        plan = create_plus_plan(client)
        scenario = setup_company_with_active_subscription(
            client, plan_id=plan["id"], legal_name="Phi Corp"
        )
        company = scenario["company"]
        admin = scenario["admin"]
        admin_headers = scenario["admin_headers"]

        connection = add_bank_connection(
            client, company["id"], admin["id"],
            institution_name="Chase", external_account_mask="3333",
        )
        category = add_category(
            client, company["id"], admin["id"], name="Coffee", tax_line="SCH-C-L24"
        )
        rule = add_rule(
            client, company["id"], admin["id"], category["id"],
            rule_name="Coffee rule", match_field="PAYEE_CONTAINS",
            match_value="COFFEE", priority=1, auto_apply=True,
        )
        # First txn matches and is auto-categorized.
        txn1 = ingest_txn(
            client, company["id"], connection["id"],
            posted_at="2026-09-10T00:00:00Z", amount_cents=-500,
            payee_raw="COFFEE BEAN",
        )
        return scenario, connection, category, rule, txn1

    def test_pause_does_not_uncategorize_prior_matches(self, client):
        """PRD 3.6: "A rule may be paused from `ACTIVE` — pausing a rule not
        in `ACTIVE` is rejected with `ERR_RULE_NOT_PAUSABLE` (HTTP 400)".
        Pausing affects future evaluations only; it does not reverse prior
        categorizations.

        Design: Difficulty/compensating_invariant/rule_pause_resume_preserves_uncategorized_count
        """
        reset_clock(client)
        scenario, connection, category, rule, txn1 = (
            self._setup_categorized_and_paused_rule(client)
        )
        company = scenario["company"]
        admin = scenario["admin"]
        admin_headers = scenario["admin_headers"]

        # Verify txn1 is CATEGORIZED before pause.
        txn1_before = get_success_data(
            client.get_bank_transaction(company["id"], txn1["id"],
                                          headers=PLATFORM_ADMIN)
        )
        assert txn1_before["txn_status"] == "CATEGORIZED"

        # Pause the rule.
        pause_response = client.pause_categorization_rule(
            company["id"], rule["id"], headers=admin_headers
        )
        assert pause_response.status_code in (200, 201)

        # Ingest a second matching txn while the rule is paused.
        txn2 = ingest_txn(
            client, company["id"], connection["id"],
            posted_at="2026-09-11T00:00:00Z", amount_cents=-600,
            payee_raw="COFFEE SHOP",
        )
        assert txn2["txn_status"] == "UNCATEGORIZED", (
            "rule is paused; new ingestion must not auto-apply"
        )

        # txn1 must still be CATEGORIZED — pause does not revert it.
        txn1_after = get_success_data(
            client.get_bank_transaction(company["id"], txn1["id"],
                                          headers=PLATFORM_ADMIN)
        )
        assert txn1_after["txn_status"] == "CATEGORIZED"

    def test_resume_reapplies_rule_to_uncategorized_pool(self, client):
        """PRD 3.6: "Creating or resuming a rule re-evaluates the company's
        `UNCATEGORIZED` transactions against it".

        Design: Difficulty/compensating_invariant/rule_pause_resume_preserves_uncategorized_count
        """
        reset_clock(client)
        scenario, connection, category, rule, txn1 = (
            self._setup_categorized_and_paused_rule(client)
        )
        company = scenario["company"]
        admin = scenario["admin"]
        admin_headers = scenario["admin_headers"]

        # Pause the rule and ingest a second txn while paused.
        client.pause_categorization_rule(
            company["id"], rule["id"], headers=admin_headers
        )
        txn2 = ingest_txn(
            client, company["id"], connection["id"],
            posted_at="2026-09-11T00:00:00Z", amount_cents=-600,
            payee_raw="COFFEE SHOP",
        )
        assert txn2["txn_status"] == "UNCATEGORIZED"

        # Resume the rule; the UNCATEGORIZED pool is re-evaluated.
        resume_response = client.resume_categorization_rule(
            company["id"], rule["id"], headers=admin_headers
        )
        assert resume_response.status_code in (200, 201)

        txn2_after = get_success_data(
            client.get_bank_transaction(company["id"], txn2["id"],
                                          headers=PLATFORM_ADMIN)
        )
        assert txn2_after["txn_status"] == "CATEGORIZED"
        assert txn2_after.get("category_id") == category["id"]
        assert txn2_after.get("matched_rule_id") == rule["id"]

        # txn1 (categorized before pause) is unchanged.
        txn1_after = get_success_data(
            client.get_bank_transaction(company["id"], txn1["id"],
                                          headers=PLATFORM_ADMIN)
        )
        assert txn1_after["txn_status"] == "CATEGORIZED"
