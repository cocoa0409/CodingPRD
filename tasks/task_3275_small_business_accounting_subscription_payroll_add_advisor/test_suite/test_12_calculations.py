"""Corner / calculations — derived tax_filing_status and the rule selector's
created_at tie-break.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers.fixtures import (
    add_bank_connection,
    add_category,
    add_employee,
    add_payroll,
    add_rule,
    create_plus_plan,
    ingest_txn,
    reset_clock,
    set_clock,
    setup_company_with_active_subscription,
)
from test_helpers.test_users import PLATFORM_ADMIN


class TestTaxFilingStatus:
    def test_tax_filing_status_aggregates_correctly(self, client):
        """PRD 3.4: "If the add-on has no `ACTIVE` employees, the status is
        `NOT_READY`. Otherwise, if any bank connection of the company is
        `STALE` or `REVOKED`, the status is `NOT_READY`. Otherwise, if any
        reconciliation of the company is `IN_PROGRESS` with a
        `statement_period_end` more than 45 days in the past, the status is
        `PENALTY_RISK`. Otherwise, if all invoices of the trailing three
        months are `PAID`, the status is `FILED_CURRENT`. In every remaining
        case the status is `READY`."

        Design: Corner/calculations/tax_filing_status_aggregates_correctly
        """
        reset_clock(client)
        plan = create_plus_plan(client)
        scenario = setup_company_with_active_subscription(
            client, plan_id=plan["id"], legal_name="Tax Co"
        )
        company = scenario["company"]
        admin = scenario["admin"]

        payroll = add_payroll(client, company["id"], admin["id"], "SELF_SERVICE")

        # No ACTIVE employees -> NOT_READY.
        view0 = get_success_data(
            client.get_payroll(company["id"], headers=PLATFORM_ADMIN)
        )
        assert view0["tax_filing_status"] == "NOT_READY"

        # Add one employee -> READY (no STALE connections, no too-old recons,
        # and no three-month invoice history yet).
        add_employee(
            client, company["id"], admin["id"], payroll["id"],
            legal_name="New Emp", hire_date="2026-09-01T00:00:00Z",
        )
        view1 = get_success_data(
            client.get_payroll(company["id"], headers=PLATFORM_ADMIN)
        )
        assert view1["tax_filing_status"] == "READY"


class TestRuleSelectorTieBreak:
    def test_rule_match_selector_priority_tiebreak_uses_created_at(self, client):
        """PRD 3.6: "Among the matching rules the winner is the one with the
        lowest `priority`; ties are broken by the rule's `created_at`,
        earlier first — never by identifier."

        Design: Corner/calculations/rule_match_selector_priority_tiebreak_uses_created_at
        """
        reset_clock(client)
        plan = create_plus_plan(client)
        scenario = setup_company_with_active_subscription(
            client, plan_id=plan["id"], legal_name="TieBreak Co"
        )
        company = scenario["company"]
        admin = scenario["admin"]
        connection = add_bank_connection(client, company["id"], admin["id"])
        cat_a = add_category(client, company["id"], admin["id"],
                              name="CatA", tax_line="A")
        cat_b = add_category(client, company["id"], admin["id"],
                              name="CatB", tax_line="B")
        # RuleA created first at priority 5.
        rule_a = add_rule(
            client, company["id"], admin["id"], cat_a["id"],
            rule_name="RuleA", match_field="PAYEE_CONTAINS",
            match_value="SHOP", priority=5, auto_apply=True,
        )
        # Advance the clock so RuleB is unambiguously newer.
        set_clock(client, "2026-09-01T00:01:00Z")
        rule_b = add_rule(
            client, company["id"], admin["id"], cat_b["id"],
            rule_name="RuleB", match_field="PAYEE_CONTAINS",
            match_value="SHOP", priority=5, auto_apply=True,
        )

        # Ingest a txn matching both rules — RuleA wins by created_at ASC.
        txn = ingest_txn(
            client, company["id"], connection["id"],
            posted_at="2026-09-10T00:00:00Z", amount_cents=-100,
            payee_raw="LOCAL SHOP",
        )
        assert txn["txn_status"] == "CATEGORIZED"
        assert txn.get("category_id") == cat_a["id"], (
            "created_at tie-break: RuleA (earlier) wins over RuleB"
        )
        assert txn.get("matched_rule_id") == rule_a["id"]
        assert txn.get("matched_rule_id") != rule_b["id"]
