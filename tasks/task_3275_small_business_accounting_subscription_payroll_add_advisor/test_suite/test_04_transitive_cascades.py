"""Transitive cascade chains from subscription cancel and firm suspend.

Cancellation cascades depth-by-depth: payroll CANCELLED, grants REVOKED,
bank connections DISCONNECTED, integrations DISCONNECTED, company READ_ONLY.
Then the read-only window expiring drives a second cascade to
CANCELLED_EXPIRED + PURGED + exports EXPIRED.

Firm suspend is a different trigger: it revokes the firm's grants without
flipping billing_owner on billed subscriptions.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers.fixtures import (
    accept_user,
    activate_subscription,
    add_bank_connection,
    add_payroll,
    cancel_subscription,
    create_company,
    create_firm,
    create_firm_user,
    create_plus_plan,
    create_primary_admin,
    get_subscription,
    issue_and_accept_grant,
    reset_clock,
    set_clock,
    setup_company_with_active_subscription,
    transfer_billing_to_firm,
)
from test_helpers import factories as f
from test_helpers.test_users import (
    PLATFORM_ADMIN,
    make_accountant_user_headers,
    make_company_user_headers,
)


class TestCancelCascadeChain:
    """Subscription cancel cascades across payroll, grants, connections,
    integrations, company — and the read-only expiry cascades exports."""

    def _setup_rich_company(self, client):
        plan = create_plus_plan(client)
        scenario = setup_company_with_active_subscription(
            client, plan_id=plan["id"], legal_name="Junction Corp"
        )
        company = scenario["company"]
        admin = scenario["admin"]
        admin_headers = scenario["admin_headers"]
        subscription = scenario["subscription"]

        # Payroll addon
        payroll = add_payroll(client, company["id"], admin["id"], "SELF_SERVICE")

        # Access grant
        firm = create_firm(client, firm_name="Gold Cascade Firm")
        firm_admin = create_firm_user(
            client, firm["id"], is_firm_admin=True, email="admin@cascade.example"
        )
        grant = issue_and_accept_grant(
            client, company["id"], admin["id"], firm["id"], firm_admin["id"],
            access_level="FULL_BOOKKEEPING",
        )

        # Bank connection
        connection = add_bank_connection(client, company["id"], admin["id"])

        # App integration (LINKED -> ACTIVE)
        integration_response = client.create_integration(
            company["id"],
            f.create_integration_payload(company["id"]),
            headers=admin_headers,
        )
        integration = get_success_data(integration_response)
        activate_response = client.activate_integration(
            company["id"], integration["id"], headers=admin_headers
        )
        integration = get_success_data(activate_response)

        # Export request marked READY
        export_response = client.create_export_request(
            company["id"],
            f.create_export_payload(company["id"], admin["id"]),
            headers=admin_headers,
        )
        export = get_success_data(export_response)
        client.mark_export_ready(company["id"], export["id"], headers=PLATFORM_ADMIN)

        return scenario, payroll, grant, connection, integration, export

    def test_cancel_cascades_payroll_grants_connections_integrations_company(self, client):
        """PRD 3.3: "cancellation lands in `CANCELLED_READ_ONLY` with a wide
        cascade: `cancelled_at` is set to now and `read_only_expires_at` to
        365 days hence; the payroll add-on moves to its terminal `CANCELLED`;
        every `ACTIVE` access grant is revoked; every bank connection is
        disconnected; every app integration is disconnected with its
        unresolved sync conflicts left `OPEN` and its `conflict_count`
        preserved for audit; the company drops to `READ_ONLY`."

        Design: Difficulty/transitive_cascade/cancel_cascade_subscription_to_payroll_to_export_expiry
        """
        reset_clock(client)
        scenario, payroll, grant, connection, integration, export = (
            self._setup_rich_company(client)
        )
        company = scenario["company"]
        admin = scenario["admin"]

        cancel_subscription(client, company["id"], admin["id"])

        payroll_after = get_success_data(
            client.get_payroll(company["id"], headers=PLATFORM_ADMIN)
        )
        assert payroll_after["addon_status"] == "CANCELLED"

        grant_after = get_success_data(
            client.get_access_grant(company["id"], grant["id"], headers=PLATFORM_ADMIN)
        )
        assert grant_after["grant_status"] == "REVOKED"

        connection_after = get_success_data(
            client.get_bank_connection(company["id"], connection["id"],
                                        headers=PLATFORM_ADMIN)
        )
        assert connection_after["connection_status"] == "DISCONNECTED"

        integration_after = get_success_data(
            client.get_integration(company["id"], integration["id"],
                                    headers=PLATFORM_ADMIN)
        )
        assert integration_after["integration_status"] == "DISCONNECTED"

        company_after = get_success_data(
            client.get_company(company["id"], headers=PLATFORM_ADMIN)
        )
        assert company_after["company_status"] == "READ_ONLY"

    def test_read_only_expiry_cascades_to_cancelled_expired_and_export_expired(self, client):
        """PRD 3.3: "When the clock finally passes `read_only_expires_at`
        without reactivation, the subscription reaches `CANCELLED_EXPIRED`,
        the company is `PURGED`, and every export request still `PENDING` or
        `READY` is expired."

        Design: Difficulty/transitive_cascade/cancel_cascade_subscription_to_payroll_to_export_expiry
        """
        reset_clock(client)
        scenario, payroll, grant, connection, integration, export = (
            self._setup_rich_company(client)
        )
        company = scenario["company"]
        admin = scenario["admin"]

        cancel_subscription(client, company["id"], admin["id"])

        # Advance past the 365-day read-only window.
        set_clock(client, "2027-09-02T00:00:00Z")

        sub = get_subscription(client, company["id"])
        assert sub["lifecycle_status"] == "CANCELLED_EXPIRED"

        company_after = get_success_data(
            client.get_company(company["id"], headers=PLATFORM_ADMIN)
        )
        assert company_after["company_status"] == "PURGED"

        export_after = get_success_data(
            client.get_export_request(company["id"], export["id"],
                                       headers=PLATFORM_ADMIN)
        )
        assert export_after["export_status"] == "EXPIRED"


class TestFirmSuspendCascade:
    """Firm suspend revokes that firm's grants without touching billing_owner."""

    def test_suspend_revokes_active_grants(self, client):
        """PRD 3.10: "Suspending a firm — `ACTIVE` to `SUSPENDED` — revokes
        every `ACTIVE` access grant issued to its advisors and flags the
        wholesale discount as inapplicable on the next invoice for every
        subscription the firm bills, until reactivation."

        Design: Difficulty/transitive_cascade/firm_suspend_cascade_to_grants_and_discount
        """
        reset_clock(client)
        plan = create_plus_plan(client)
        scenario = setup_company_with_active_subscription(
            client, plan_id=plan["id"], legal_name="Kappa Corp"
        )
        company = scenario["company"]
        admin = scenario["admin"]

        firm = create_firm(
            client, firm_name="K Firm", wholesale_discount_pct=0.20,
            proadvisor_tier="GOLD",
        )
        firm_admin = create_firm_user(
            client, firm["id"], is_firm_admin=True, email="admin@k.example"
        )
        transfer_billing_to_firm(client, scenario, firm, firm_admin)

        grant = issue_and_accept_grant(
            client, company["id"], admin["id"], firm["id"], firm_admin["id"],
            access_level="FULL_BOOKKEEPING",
        )
        assert grant["grant_status"] == "ACTIVE"

        # Suspend the firm.
        response = client.suspend_firm(firm["id"], headers=PLATFORM_ADMIN)
        assert response.status_code in (200, 201)

        grant_after = get_success_data(
            client.get_access_grant(company["id"], grant["id"], headers=PLATFORM_ADMIN)
        )
        assert grant_after["grant_status"] == "REVOKED"

    def test_suspend_does_not_flip_billing_owner(self, client):
        """PRD 3.10: "Suspending a firm — `ACTIVE` to `SUSPENDED` — revokes
        every `ACTIVE` access grant issued to its advisors and flags the
        wholesale discount as inapplicable on the next invoice for every
        subscription the firm bills, until reactivation."

        The subscription's billing_owner is unchanged by suspension; only
        the discount's applicability is gated.

        Design: Difficulty/transitive_cascade/firm_suspend_cascade_to_grants_and_discount
        """
        reset_clock(client)
        plan = create_plus_plan(client)
        scenario = setup_company_with_active_subscription(
            client, plan_id=plan["id"], legal_name="Lambda Corp"
        )
        company = scenario["company"]

        firm = create_firm(
            client, firm_name="K2 Firm", wholesale_discount_pct=0.20,
            proadvisor_tier="GOLD",
        )
        firm_admin = create_firm_user(
            client, firm["id"], is_firm_admin=True, email="admin@k2.example"
        )
        transfer_billing_to_firm(client, scenario, firm, firm_admin)

        sub_before = get_subscription(client, company["id"])
        assert sub_before["billing_owner"] == "FIRM"

        client.suspend_firm(firm["id"], headers=PLATFORM_ADMIN)

        sub_after = get_subscription(client, company["id"])
        assert sub_after["billing_owner"] == "FIRM", (
            "firm suspend does not flip billing_owner; it only gates the discount"
        )
        assert sub_after["billing_firm_id"] == firm["id"]
