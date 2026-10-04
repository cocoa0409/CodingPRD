"""Dual-variant pricing — list vs wholesale, and provisional vs final payroll.

The two difficulty instances in this file pin the two pricing variants to
their literal cent values.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers.fixtures import (
    accept_user,
    activate_subscription,
    create_advanced_plan,
    create_company,
    create_firm,
    create_firm_user,
    create_plus_plan,
    create_primary_admin,
    get_subscription,
    issue_invoice_now,
    reset_clock,
    set_clock,
    setup_company_with_active_subscription,
    transfer_billing_to_firm,
)
from test_helpers.test_users import (
    PLATFORM_ADMIN,
    make_accountant_user_headers,
    make_company_user_headers,
)


class TestListVsWholesaleDivergence:
    """Two same-plan subscriptions — one CLIENT-billed, one FIRM-billed —
    quote different monthly prices."""

    def test_list_price_client_billing_matches_plan_list(self, client):
        """PRD 3.5: "The effective monthly price of a subscription — the
        `monthly_price_cents` quoted on reads and previews — is the plan's
        `list_price_cents` when the client is billed."

        Design: Difficulty/dual_variant_calc/subscription_price_list_vs_wholesale_divergence
        """
        reset_clock(client)
        plan = create_plus_plan(client)
        scenario = setup_company_with_active_subscription(
            client, plan_id=plan["id"], legal_name="Alpha Corp"
        )
        subscription = get_subscription(client, scenario["company"]["id"])
        assert subscription["billing_owner"] == "CLIENT"
        assert subscription["monthly_price_cents"] == 8000, (
            "CLIENT-billed subscription must quote list_price_cents verbatim"
        )

    def test_wholesale_firm_billing_uses_discount(self, client):
        """PRD 3.5: "When a firm is billed, the wholesale discount applies:
        the effective discount percentage is the firm's
        `wholesale_discount_pct` capped at the ceiling of its
        `proadvisor_tier` — 0.20 for `SILVER`, 0.35 for `GOLD`, 0.50 for
        `PLATINUM` — and the price is the list price times one minus that
        capped percentage, rounded half-up to whole cents."

        Design: Difficulty/dual_variant_calc/subscription_price_list_vs_wholesale_divergence
        """
        reset_clock(client)
        plan = create_plus_plan(client)
        scenario = setup_company_with_active_subscription(
            client, plan_id=plan["id"], legal_name="Beta Corp"
        )
        firm = create_firm(
            client,
            firm_name="Gold Tier CPA LLP",
            wholesale_discount_pct=0.30,
            proadvisor_tier="GOLD",
        )
        firm_admin = create_firm_user(
            client, firm["id"], is_firm_admin=True, email="admin@gold.example"
        )
        transfer_billing_to_firm(client, scenario, firm, firm_admin)
        subscription = get_subscription(client, scenario["company"]["id"])
        assert subscription["billing_owner"] == "FIRM"
        assert subscription["billing_firm_id"] == firm["id"]
        # round_half_up(8000 * (1 - 0.30)) = 5600
        assert subscription["monthly_price_cents"] == 5600


class TestPayrollPerEmployeeProvisionalVsFinal:
    """The provisional quote is flat (current count * fee); the final invoice
    is day-by-day with per-line rounding."""

    def test_invoice_uses_day_by_day_proration(self, client):
        """PRD 3.5: "For each day from `period_start` up to but not including
        `period_end`, count the employees who were `ACTIVE` on that day —
        an employee counts on a day when their `hire_date` is on or before
        it and their `terminated_at` is either unset or strictly after it.
        Multiply that day's count by `per_employee_fee_cents`, divide by 30
        — the billing month is always thirty days regardless of calendar
        length — and round that day's amount half-up to whole cents.  The
        invoice line is the sum of those per-day rounded amounts."

        Design: Difficulty/dual_variant_calc/payroll_per_employee_provisional_vs_final
        """
        reset_clock(client)
        plan = create_plus_plan(client)
        scenario = setup_company_with_active_subscription(
            client, plan_id=plan["id"], legal_name="Gamma Corp"
        )
        company = scenario["company"]
        admin = scenario["admin"]
        subscription = scenario["subscription"]

        from test_helpers.fixtures import add_employee, add_payroll

        payroll = add_payroll(client, company["id"], admin["id"], "SELF_SERVICE")
        add_employee(
            client, company["id"], admin["id"], payroll["id"],
            legal_name="Emp One", hire_date="2026-09-01T00:00:00Z",
        )
        add_employee(
            client, company["id"], admin["id"], payroll["id"],
            legal_name="Emp Two", hire_date="2026-09-16T00:00:00Z",
        )
        set_clock(client, "2026-10-01T00:00:00Z")
        invoice = issue_invoice_now(client, company["id"], subscription["id"])

        # Emp One: 30 days * 600/30 = 600.  Emp Two: 15 days (Sep 16..30)
        # * 600/30 = 300.  Sum = 900 (round-per-line then sum).
        assert invoice["payroll_per_employee_cents"] == 900
        assert invoice["payroll_base_cents"] == 4500

    def test_invoice_differs_from_provisional_estimate(self, client):
        """PRD 3.5: "A mid-month preview, such as the one behind
        `monthly_price_cents` after a plan change, uses the cheaper
        provisional estimate instead: the current count of `ACTIVE`
        employees times the per-employee fee, with no day-by-day walk; the
        provisional figure can differ from the final invoice line by a few
        cents, and the invoice line is the authoritative number."

        Design: Difficulty/dual_variant_calc/payroll_per_employee_provisional_vs_final
        """
        reset_clock(client)
        plan = create_plus_plan(client)
        scenario = setup_company_with_active_subscription(
            client, plan_id=plan["id"], legal_name="Delta Corp"
        )
        company = scenario["company"]
        admin = scenario["admin"]
        subscription = scenario["subscription"]

        from test_helpers.fixtures import add_employee, add_payroll

        payroll = add_payroll(client, company["id"], admin["id"], "SELF_SERVICE")
        add_employee(
            client, company["id"], admin["id"], payroll["id"],
            legal_name="Emp One", hire_date="2026-09-01T00:00:00Z",
        )
        add_employee(
            client, company["id"], admin["id"], payroll["id"],
            legal_name="Emp Two", hire_date="2026-09-16T00:00:00Z",
        )
        set_clock(client, "2026-10-01T00:00:00Z")
        invoice = issue_invoice_now(client, company["id"], subscription["id"])

        # Provisional (flat) would be 2 * 600 = 1200; final (day-by-day) is 900.
        assert invoice["payroll_per_employee_cents"] != 1200, (
            "final invoice line must not equal the naive provisional estimate"
        )
        assert invoice["payroll_per_employee_cents"] == 900
