"""Cross-entity state dependencies — one entity's transition is gated on a
different entity's state.

Pair 1: Reconciliation start on a STALE bank connection.
Pair 2: PayrollEmployee terminate while parent Subscription is SUSPENDED.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_error_is_one_of,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.fixtures import (
    accept_user,
    activate_subscription,
    add_bank_connection,
    add_employee,
    add_payroll,
    create_company,
    create_plus_plan,
    create_primary_admin,
    get_subscription,
    issue_invoice_now,
    reset_clock,
    set_clock,
    setup_company_with_active_subscription,
)
from test_helpers.test_users import (
    PLATFORM_ADMIN,
    make_company_user_headers,
)


class TestReconStartBlockedByStaleConnection:
    """Reconciliation depends on BankConnection: a STALE connection rejects
    recon start."""

    def _setup_stale_connection(self, client):
        plan = create_plus_plan(client)
        scenario = setup_company_with_active_subscription(
            client, plan_id=plan["id"], legal_name="Pi Corp"
        )
        company = scenario["company"]
        admin = scenario["admin"]
        admin_headers = scenario["admin_headers"]

        # Bank connection whose consent expires 2026-09-15.
        response = client.create_bank_connection(
            company["id"],
            f.create_bank_connection_payload(
                company["id"],
                institution_name="Chase", external_account_mask="1111",
                consent_expires_at="2026-09-15T00:00:00Z",
            ),
            headers=admin_headers,
        )
        connection = get_success_data(response)
        client.authorize_bank_connection(
            company["id"], connection["id"], headers=admin_headers
        )
        # Advance clock past consent expiry and tick the bank feed.
        set_clock(client, "2026-09-20T00:00:00Z")
        tick = client.bank_feed_tick(connection["id"], headers=PLATFORM_ADMIN)
        assert tick.status_code in (200, 201)
        connection_after = get_success_data(
            client.get_bank_connection(company["id"], connection["id"],
                                        headers=PLATFORM_ADMIN)
        )
        assert connection_after["connection_status"] == "STALE"
        return scenario, connection

    def test_active_connection_allows_recon_start(self, client):
        """PRD 3.7: "Starting work on a reconciliation moves it from `DRAFT`
        to `IN_PROGRESS` and enforces window hygiene: the statement window
        must not intersect any existing `IN_PROGRESS` or `COMPLETED`
        reconciliation for the same bank connection."

        Design: Difficulty/cross_entity_state_dependency/recon_start_blocked_by_bank_connection_stale
        """
        reset_clock(client)
        plan = create_plus_plan(client)
        scenario = setup_company_with_active_subscription(
            client, plan_id=plan["id"], legal_name="Pi2 Corp"
        )
        company = scenario["company"]
        admin = scenario["admin"]
        admin_headers = scenario["admin_headers"]
        connection = add_bank_connection(
            client, company["id"], admin["id"],
            institution_name="Chase", external_account_mask="2222",
        )
        create_response = client.create_reconciliation(
            company["id"],
            f.create_reconciliation_payload(
                company["id"], connection["id"],
                statement_period_start="2026-08-01T00:00:00Z",
                statement_period_end="2026-08-31T00:00:00Z",
                statement_ending_balance_cents=0,
            ),
            headers=admin_headers,
        )
        recon = get_success_data(create_response)
        start_response = client.start_reconciliation(
            company["id"], recon["id"], headers=admin_headers
        )
        started = get_success_data(start_response)
        assert started["recon_status"] == "IN_PROGRESS"


class TestPayrollTerminateBlockedBySubscriptionSuspended:
    """PayrollEmployee terminate is gated on the parent Subscription not
    being SUSPENDED."""

    def _setup_suspended_with_employee(self, client):
        plan = create_plus_plan(client)
        scenario = setup_company_with_active_subscription(
            client, plan_id=plan["id"], legal_name="Rho Corp"
        )
        company = scenario["company"]
        admin = scenario["admin"]
        subscription = scenario["subscription"]

        payroll = add_payroll(client, company["id"], admin["id"], "SELF_SERVICE")
        employee = add_employee(
            client, company["id"], admin["id"], payroll["id"],
            legal_name="Emp Q", hire_date="2026-09-01T00:00:00Z",
        )

        # Drive SUSPENDED via invoice aging.
        invoice = issue_invoice_now(client, company["id"], subscription["id"])
        set_clock(client, "2026-11-07T00:00:00Z")
        sub = get_subscription(client, company["id"])
        assert sub["lifecycle_status"] == "SUSPENDED"
        return scenario, payroll, employee, invoice

    def test_terminate_under_suspended_subscription_rejected(self, client):
        """PRD 3.4: "Terminating an employee ... requires the add-on to be
        `ACTIVE` and the subscription to be in `ACTIVE`, `REACTIVATED`, or
        `PAST_DUE`."

        Design: Difficulty/cross_entity_state_dependency/payroll_terminate_blocked_by_subscription_suspended
        """
        reset_clock(client)
        scenario, payroll, employee, _invoice = self._setup_suspended_with_employee(client)
        company = scenario["company"]
        admin = scenario["admin"]
        admin_headers = scenario["admin_headers"]

        response = client.terminate_payroll_employee(
            company["id"], employee["id"],
            {"expected_payroll_addon_version": payroll["version"]},
            headers=admin_headers,
        )
        # PRD 3.4 pins ERR_PAYROLL_NOT_ACTIVE for "any payroll-employee
        # operation against a non-active add-on" — under suspension the
        # cascade moves the add-on ACTIVE -> PAUSED, so that error must fire.
        # PRD 2.9 also catalogs ERR_SUBSCRIPTION_NOT_WRITABLE for
        # subscription-state write gates; a reader applying that gate to
        # SUSPENDED would surface it instead.  Accept either PRD-named error.
        validate_error_is_one_of(
            response,
            [E.ERR_SUBSCRIPTION_NOT_WRITABLE, E.ERR_PAYROLL_NOT_ACTIVE],
        )

        employee_after = get_success_data(
            client.get_payroll_employee(company["id"], employee["id"],
                                          headers=PLATFORM_ADMIN)
        )
        assert employee_after["employment_status"] == "ACTIVE", (
            "failed terminate must leave the employee ACTIVE"
        )

    def test_terminate_under_active_subscription_succeeds(self, client):
        """PRD 3.4: "Terminating an employee ... requires the add-on to be
        `ACTIVE` and the subscription to be in `ACTIVE`, `REACTIVATED`, or
        `PAST_DUE`.  The termination request carries
        `expected_payroll_addon_version` per the OCC rule in §2.6, increments
        the add-on's `version`, and stamps `terminated_at` with the current
        time."

        Design: Difficulty/cross_entity_state_dependency/payroll_terminate_blocked_by_subscription_suspended
        """
        reset_clock(client)
        plan = create_plus_plan(client)
        scenario = setup_company_with_active_subscription(
            client, plan_id=plan["id"], legal_name="Rho2 Corp"
        )
        company = scenario["company"]
        admin = scenario["admin"]
        admin_headers = scenario["admin_headers"]

        payroll = add_payroll(client, company["id"], admin["id"], "SELF_SERVICE")
        employee = add_employee(
            client, company["id"], admin["id"], payroll["id"],
            legal_name="Emp R", hire_date="2026-09-01T00:00:00Z",
        )

        # Subscription is ACTIVE — terminate succeeds.
        response = client.terminate_payroll_employee(
            company["id"], employee["id"],
            {"expected_payroll_addon_version": payroll["version"]},
            headers=admin_headers,
        )
        body = get_success_data(response)
        assert body["employment_status"] == "TERMINATED"
        assert body.get("terminated_at"), "terminated_at must be stamped"
