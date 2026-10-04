"""Combinatorial pricing — three-input wholesale ceiling and pinned invoice
evaluation order.

Mode (a) instance proves the min(discount, tier_ceiling) switch by driving
three firms at, above, and below their respective ceilings.  Mode (c)
instance proves subtotal -> tax -> total by computing a literal cent-by-cent
expected invoice.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers.fixtures import (
    add_employee,
    add_payroll,
    create_advanced_plan,
    create_firm,
    create_firm_user,
    create_plus_plan,
    get_subscription,
    issue_invoice_now,
    reset_clock,
    set_clock,
    setup_company_with_active_subscription,
    transfer_billing_to_firm,
)


class TestMonthlyPriceModeA:
    """Three firms on the same plan; the tier ceiling pins the effective
    discount independently per tier."""

    def _setup_firm_owned_subscription(self, client, firm_kwargs, legal_name):
        plan = self._plan
        scenario = setup_company_with_active_subscription(
            client, plan_id=plan["id"], legal_name=legal_name
        )
        firm = create_firm(client, **firm_kwargs)
        firm_admin = create_firm_user(
            client, firm["id"], is_firm_admin=True,
            email="admin@{0}.example".format(firm["id"][:8]),
        )
        transfer_billing_to_firm(client, scenario, firm, firm_admin)
        return scenario, firm

    def test_silver_firm_discount_capped_at_twenty_percent(self, client):
        """PRD 3.5: "the effective discount percentage is the firm's
        `wholesale_discount_pct` capped at the ceiling of its
        `proadvisor_tier` — 0.20 for `SILVER`, 0.35 for `GOLD`, 0.50 for
        `PLATINUM` — and the price is the list price times one minus that
        capped percentage, rounded half-up to whole cents."

        Design: Difficulty/combinatorial_formula/monthly_subscription_price_mode_a_3input_conditional
        """
        reset_clock(client)
        self._plan = create_advanced_plan(client)
        scenario, _firm = self._setup_firm_owned_subscription(
            client,
            {
                "firm_name": "Silver Co",
                "wholesale_discount_pct": 0.50,  # above SILVER ceiling
                "proadvisor_tier": "SILVER",
            },
            "Delta Corp",
        )
        subscription = get_subscription(client, scenario["company"]["id"])
        # 10000 * (1 - 0.20) = 8000 — the raw 0.50 was rejected by the ceiling.
        assert subscription["monthly_price_cents"] == 8000

    def test_gold_at_ceiling_and_platinum_below_ceiling(self, client):
        """PRD 3.5: "the effective discount percentage is the firm's
        `wholesale_discount_pct` capped at the ceiling of its
        `proadvisor_tier` — 0.20 for `SILVER`, 0.35 for `GOLD`, 0.50 for
        `PLATINUM` — and the price is the list price times one minus that
        capped percentage, rounded half-up to whole cents."

        Design: Difficulty/combinatorial_formula/monthly_subscription_price_mode_a_3input_conditional
        """
        reset_clock(client)
        self._plan = create_advanced_plan(client)

        # GOLD at ceiling (0.35 == 0.35).
        scenario_gold, _f1 = self._setup_firm_owned_subscription(
            client,
            {
                "firm_name": "Gold Co",
                "wholesale_discount_pct": 0.35,
                "proadvisor_tier": "GOLD",
            },
            "Epsilon Corp",
        )
        subscription_gold = get_subscription(client, scenario_gold["company"]["id"])
        # 10000 * (1 - 0.35) = 6500
        assert subscription_gold["monthly_price_cents"] == 6500

        # PLATINUM below ceiling (0.10 < 0.50).
        scenario_plat, _f2 = self._setup_firm_owned_subscription(
            client,
            {
                "firm_name": "Plat Co",
                "wholesale_discount_pct": 0.10,
                "proadvisor_tier": "PLATINUM",
            },
            "Zeta Corp",
        )
        subscription_plat = get_subscription(client, scenario_plat["company"]["id"])
        # 10000 * (1 - 0.10) = 9000
        assert subscription_plat["monthly_price_cents"] == 9000


class TestInvoiceTotalModeC:
    """Invoice line math is pinned: subtotal -> tax -> total."""

    def test_invoice_lines_pinned_order_uk_tax(self, client):
        """PRD 3.5: "The subtotal is the list subscription price minus the
        wholesale discount plus the payroll base plus the payroll per-employee
        charge; tax is the subtotal times the company's regional rate (zero
        percent US, twenty percent UK, twenty-one percent EU), rounded
        half-up to whole cents; `total_cents` is the subtotal plus that tax."

        Design: Difficulty/combinatorial_formula/invoice_total_mode_c_evaluation_order_pinned
        """
        reset_clock(client)
        plan = create_plus_plan(client)
        scenario = setup_company_with_active_subscription(
            client, plan_id=plan["id"], legal_name="Gamma UK Ltd",
        )
        # Switch the company's region to UK by re-creating — the fixture used
        # the default US.  Instead, create a fresh company with home_country
        # GB / data_region UK.
        from test_helpers.fixtures import (
            accept_user,
            create_company,
            create_primary_admin,
            activate_subscription,
        )

        company = create_company(
            client, plan["id"], legal_name="Gamma UK Ltd",
            admin_email="g@guk.example", home_country="GB", data_region="UK",
        )
        admin = create_primary_admin(client, company["id"], email="admin@guk.example")
        accept_user(client, company["id"], admin["id"])
        subscription = activate_subscription(client, company["id"], admin["id"])

        payroll = add_payroll(client, company["id"], admin["id"], "SELF_SERVICE")
        add_employee(
            client, company["id"], admin["id"], payroll["id"],
            legal_name="Emp One", hire_date="2026-09-01T00:00:00Z",
        )

        firm = create_firm(
            client, firm_name="Gold Tier CPA", wholesale_discount_pct=0.30,
            proadvisor_tier="GOLD",
        )
        firm_admin = create_firm_user(
            client, firm["id"], is_firm_admin=True, email="admin@guk-firm.example"
        )
        # Initiate + accept the billing transfer so the invoice is FIRM-billed.
        from test_helpers.fixtures import (
            client_accept_transfer,
            initiate_transfer_to_firm,
        )
        transfer = initiate_transfer_to_firm(
            client, company["id"], subscription["id"], firm["id"], firm_admin["id"]
        )
        current = get_subscription(client, company["id"])
        client_accept_transfer(
            client, company["id"], transfer["id"], admin["id"], current["version"]
        )

        set_clock(client, "2026-10-01T00:00:00Z")
        invoice = issue_invoice_now(client, company["id"], subscription["id"])

        assert invoice["list_subscription_cents"] == 8000
        assert invoice["wholesale_discount_cents"] == 2400  # 8000 * 0.30
        assert invoice["payroll_base_cents"] == 4500
        assert invoice["payroll_per_employee_cents"] == 600  # 1 emp * 30 days * 600/30
        # subtotal == 8000 - 2400 + 4500 + 600 == 10700
        # tax == round_half_up(10700 * 0.20) == 2140
        # total == 10700 + 2140 == 12840
        assert invoice["tax_cents"] == 2140
        assert invoice["total_cents"] == 12840

    def test_invoice_lines_pinned_order_payroll_before_tax(self, client):
        """PRD 3.5: "Payroll enters the base before tax, never after."

        Design: Difficulty/combinatorial_formula/invoice_total_mode_c_evaluation_order_pinned
        """
        reset_clock(client)
        plan = create_plus_plan(client)
        from test_helpers.fixtures import (
            accept_user,
            activate_subscription,
            create_company,
            create_primary_admin,
        )

        company = create_company(
            client, plan["id"], legal_name="UK No Discount",
            admin_email="n@guk.example", home_country="GB", data_region="UK",
        )
        admin = create_primary_admin(client, company["id"], email="admin@uknodisc.example")
        accept_user(client, company["id"], admin["id"])
        subscription = activate_subscription(client, company["id"], admin["id"])

        payroll = add_payroll(client, company["id"], admin["id"], "SELF_SERVICE")
        add_employee(
            client, company["id"], admin["id"], payroll["id"],
            legal_name="Solo", hire_date="2026-09-01T00:00:00Z",
        )
        set_clock(client, "2026-10-01T00:00:00Z")
        invoice = issue_invoice_now(client, company["id"], subscription["id"])

        # CLIENT-billed: list=8000, discount=0, payroll_base=4500, per_employee=600
        # subtotal == 8000 + 4500 + 600 == 13100; tax == round(13100 * 0.20) == 2620
        # total == 13100 + 2620 == 15720
        assert invoice["list_subscription_cents"] == 8000
        assert invoice["wholesale_discount_cents"] == 0
        assert invoice["payroll_base_cents"] == 4500
        assert invoice["payroll_per_employee_cents"] == 600
        assert invoice["tax_cents"] == 2620
        assert invoice["total_cents"] == 15720
