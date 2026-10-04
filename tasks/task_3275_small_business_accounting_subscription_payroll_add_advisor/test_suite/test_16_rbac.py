"""Corner / rbac — accountant users are grant-scoped; without a grant (or
with too narrow a grant) shared operations are denied.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
)

from test_helpers import api_errors as E
from test_helpers.fixtures import (
    add_bank_connection,
    add_category,
    add_employee,
    add_payroll,
    create_firm,
    create_firm_user,
    create_plus_plan,
    ingest_txn,
    issue_and_accept_grant,
    reset_clock,
    setup_company_with_active_subscription,
)
from test_helpers.test_users import make_accountant_user_headers


class TestAccountantWithoutGrant:
    def test_accountant_user_without_grant_cannot_categorize(self, client):
        """PRD 2.1: "An `AccountantUser` acts on a client company's data
        only while holding an `AccessGrant` in `ACTIVE` status at the
        required `access_level`: `FULL_BOOKKEEPING` for bookkeeping,
        reconciliation, conflict resolution, invoice payment, and export
        downloads; `PAYROLL_ONLY` suffices (in addition to
        `FULL_BOOKKEEPING`) for payroll employee create and terminate;
        `REPORTS_READ_ONLY` grants reads only."

        Design: Corner/rbac/accountant_user_without_grant_cannot_categorize
        """
        reset_clock(client)
        plan = create_plus_plan(client)
        scenario = setup_company_with_active_subscription(
            client, plan_id=plan["id"], legal_name="NoGrant Co"
        )
        company = scenario["company"]
        admin = scenario["admin"]
        admin_headers = scenario["admin_headers"]

        # Build a firm with an accountant who has NO grant on this company.
        firm = create_firm(client, firm_name="No Grant Firm")
        no_grant_advisor = create_firm_user(
            client, firm["id"], is_firm_admin=False, email="ng@f.example",
            full_name="No Grant",
        )

        connection = add_bank_connection(client, company["id"], admin["id"])
        category = add_category(
            client, company["id"], admin["id"], name="CatA", tax_line="A"
        )
        txn = ingest_txn(
            client, company["id"], connection["id"],
            posted_at="2026-09-10T00:00:00Z", amount_cents=-50,
            payee_raw="TEST",
        )

        response = client.categorize_bank_transaction(
            company["id"], txn["id"], {"category_id": category["id"]},
            headers=make_accountant_user_headers(no_grant_advisor["id"]),
        )
        validate_error(response, E.ERR_FORBIDDEN_FOR_ROLE)


class TestReportsReadOnlyCannotTerminate:
    def test_reports_read_only_grant_cannot_terminate_employee(self, client):
        """PRD 2.1: "`PAYROLL_ONLY` suffices (in addition to
        `FULL_BOOKKEEPING`) for payroll employee create and terminate;
        `REPORTS_READ_ONLY` grants reads only."

        Design: Corner/rbac/reports_read_only_grant_cannot_terminate_employee
        """
        reset_clock(client)
        plan = create_plus_plan(client)
        scenario = setup_company_with_active_subscription(
            client, plan_id=plan["id"], legal_name="RO Co"
        )
        company = scenario["company"]
        admin = scenario["admin"]

        firm = create_firm(client, firm_name="RO Firm")
        advisor = create_firm_user(
            client, firm["id"], is_firm_admin=True, email="ro@f.example",
            full_name="RO Advisor",
        )
        issue_and_accept_grant(
            client, company["id"], admin["id"], firm["id"], advisor["id"],
            access_level="REPORTS_READ_ONLY",
        )

        payroll = add_payroll(client, company["id"], admin["id"], "SELF_SERVICE")
        employee = add_employee(
            client, company["id"], admin["id"], payroll["id"],
            legal_name="E", hire_date="2026-09-01T00:00:00Z",
        )

        response = client.terminate_payroll_employee(
            company["id"], employee["id"],
            {"expected_payroll_addon_version": payroll["version"]},
            headers=make_accountant_user_headers(advisor["id"]),
        )
        validate_error(response, E.ERR_FORBIDDEN_FOR_ROLE)
