"""Interest accrual, monthly fee assessment, and GL variance."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_project, create_product, create_gl, create_account, map_account,
    advance_to_mock_conversion, start_mock_run, finalize_run, set_clock,
    setup_mock_conversion_project, setup_plan_scheduled,
    plan_cutover, add_task, create_ancillary_system, verify_ancillary_system,
)

PM = TEST_USERS["pm_headers"]
CE = TEST_USERS["ce_headers"]


class TestAccrualRoundingOrder:
    def test_daily_rounded_half_up_then_multiplied(self, api):
        """PRD §2.6: "Interest computation rounds the **daily** interest amount
        half-up to a whole cent before multiplying by the number of accrual
        days; all subsequent aggregation is exact integer arithmetic."

        Design: Difficulty/combinatorial_formula/accrual_rounding_order_daily_then_multiply
        """
        project = create_project()
        pt = create_product(project["id"], product_code="DDA-ODD", rate=0.03)
        gl = create_gl(project["id"])
        acct = create_account(
            project["id"], pt["id"], legacy_account_number="L-4001",
            opening_principal_cents=10000001, accrual_start_date="2026-09-01",
        )
        map_account(acct["id"], gl["id"], project["id"])
        advance_to_mock_conversion(project["id"])
        run = start_mock_run(project["id"])
        finalize_run(run["id"], clock="2026-09-10T00:00:00Z")
        data = get_success_data(api.get_account(acct["id"], CE))
        # round_half_up(10000001 * 0.03 / 365) = round_half_up(821.9179) = 822;
        # accrued = 822 * 10 days (2026-09-01..2026-09-10 inclusive).
        assert data["daily_interest_cents"] == 822
        assert data["cutoff_accrued_interest_cents"] == 8220
        assert data["conversion_balance_cents"] == 10008221

    def test_multiply_then_round_would_differ_so_daily_first_is_observable(self, api):
        """PRD §2.6: "Interest computation rounds the **daily** interest amount
        half-up to a whole cent before multiplying by the number of accrual
        days; all subsequent aggregation is exact integer arithmetic."
        PRD §3.4: "For a `DEPOSIT` account the `conversion_balance_cents` is
        the principal plus the accrued interest"

        Design: Difficulty/combinatorial_formula/accrual_rounding_order_daily_then_multiply
        """
        project = create_project()
        pt = create_product(project["id"], product_code="DDA-ODD2", rate=0.03)
        gl = create_gl(project["id"])
        acct = create_account(
            project["id"], pt["id"], legacy_account_number="L-4002",
            opening_principal_cents=10000001, accrual_start_date="2026-09-01",
        )
        map_account(acct["id"], gl["id"], project["id"])
        advance_to_mock_conversion(project["id"])
        run = start_mock_run(project["id"])
        finalize_run(run["id"], clock="2026-09-10T00:00:00Z")
        data = get_success_data(api.get_account(acct["id"], CE))
        # Multiply-then-round would give 8219; daily-first gives 8220.
        assert data["cutoff_accrued_interest_cents"] == 8220
        assert data["cutoff_accrued_interest_cents"] != 8219


class TestAccrualDualVariant:
    def test_mock_finalize_then_cutover_recompute_at_cutoff_date(self, api):
        """PRD §3.7: "transitions every `CLEARED` account to `CONVERTED` and
        recomputes each such account's accrual authoritatively with the
        computation date set to `cutoff_business_date`"

        Design: Difficulty/dual_variant_calc/accrual_interest_mock_run_vs_cutover_variant
        """
        project = create_project()
        pt = create_product(project["id"], product_code="DDA-STD", rate=0.03,
                            monthly_fee_cents=0)
        gl = create_gl(project["id"])
        acct = create_account(
            project["id"], pt["id"], legacy_account_number="L-1001",
            opening_principal_cents=10000000, accrual_start_date="2026-09-01",
        )
        map_account(acct["id"], gl["id"], project["id"])
        advance_to_mock_conversion(project["id"])
        run = start_mock_run(project["id"])
        finalized = finalize_run(run["id"], clock="2026-09-10T00:00:00Z")
        assert finalized["outcome"] == "PASSED"
        # Mock (advisory) variant at the 2026-09-10 finalize clock date:
        # 822 daily * 10 days.
        mid = get_success_data(api.get_account(acct["id"], CE))
        assert mid["cutoff_accrued_interest_cents"] == 8220
        # Certify the account (MAPPED -> EXCEPTION -> CLEARED) so go-live
        # converts it.
        get_success_data(api.flag_exception(acct["id"], {"note": "x"}, CE))
        get_success_data(api.clear_exception(acct["id"], {"resolution_note": "y"}, CE))
        # Plan the cutover, schedule and execute the single task, then go live.
        sys_row = create_ancillary_system(project["id"])
        verify_ancillary_system(sys_row["id"])
        plan = plan_cutover(project["id"])
        task = add_task(plan["id"])
        get_success_data(api.schedule_plan(plan["id"], PM))
        set_clock("2026-09-19T20:30:00Z")
        get_success_data(api.declare_go(plan["id"], PM))
        get_success_data(api.start_task(task["id"], CE))
        get_success_data(api.complete_task(task["id"], CE))
        set_clock("2026-09-20T00:00:00Z")
        get_success_data(api.go_live(project["id"], PM))
        final = get_success_data(api.get_account(acct["id"], PM))
        # Cutover variant recomputes at cutoff_business_date (2026-09-20, the
        # current clock date per PRD §3.7): 822 * 20 days = 16440.
        assert final["status"] == "CONVERTED"
        assert final["daily_interest_cents"] == 822
        assert final["cutoff_accrued_interest_cents"] == 16440
        assert final["conversion_balance_cents"] == 10016440

    def test_same_account_yields_different_accrual_per_variant(self, api):
        """PRD §3.5: "The mock-run accrual variant is **advisory**: it refreshes
        `conversion_balance_cents`, `cutoff_accrued_interest_cents`, and
        `daily_interest_cents` per account but never flags exceptions on
        accounts as a side effect of the computation itself."
        PRD §3.7: "transitions every `CLEARED` account to `CONVERTED` and
        recomputes each such account's accrual authoritatively with the
        computation date set to `cutoff_business_date`"

        Design: Difficulty/dual_variant_calc/accrual_interest_mock_run_vs_cutover_variant
        """
        project = create_project()
        pt = create_product(project["id"], product_code="DDA-STD", rate=0.03,
                            monthly_fee_cents=0)
        gl = create_gl(project["id"])
        acct = create_account(
            project["id"], pt["id"], legacy_account_number="L-1101",
            opening_principal_cents=10000000, accrual_start_date="2026-09-01",
        )
        map_account(acct["id"], gl["id"], project["id"])
        advance_to_mock_conversion(project["id"])
        run = start_mock_run(project["id"])
        finalize_run(run["id"], clock="2026-09-10T00:00:00Z")
        mock_accrued = get_success_data(api.get_account(acct["id"], CE))[
            "cutoff_accrued_interest_cents"]
        get_success_data(api.flag_exception(acct["id"], {"note": "x"}, CE))
        get_success_data(api.clear_exception(acct["id"], {"resolution_note": "y"}, CE))
        sys_row = create_ancillary_system(project["id"])
        verify_ancillary_system(sys_row["id"])
        plan = plan_cutover(project["id"])
        task = add_task(plan["id"])
        get_success_data(api.schedule_plan(plan["id"], PM))
        set_clock("2026-09-19T20:30:00Z")
        get_success_data(api.declare_go(plan["id"], PM))
        get_success_data(api.start_task(task["id"], CE))
        get_success_data(api.complete_task(task["id"], CE))
        set_clock("2026-09-20T00:00:00Z")
        get_success_data(api.go_live(project["id"], PM))
        final = get_success_data(api.get_account(acct["id"], PM))
        assert mock_accrued == 8220
        assert final["cutoff_accrued_interest_cents"] == 16440
        assert final["cutoff_accrued_interest_cents"] != mock_accrued


class TestThirty360:
    def test_thirty_360_counts_30_day_months(self, api):
        """PRD §3.4: "under `THIRTY_360` every month counts as exactly thirty
        days — the count is 360 times the year difference, plus 30 times the
        month difference, plus the smaller of the computation date's
        day-of-month and 30, minus the smaller of the start date's day-of-month
        and 30, plus one."
        PRD §3.4: "for a `LOAN` account the `conversion_balance_cents` always
        equals the principal exactly — loan interest is tracked separately and
        never folds into the converted balance."

        Design: Corner/calculations/thirty_360_day_count_uses_30_day_months
        """
        set_clock("2026-01-01T00:00:00Z")
        project = create_project()
        pt = create_product(project["id"], product_code="LN-360", kind="LOAN",
                            accrual_method="THIRTY_360", rate=0.06)
        gl = create_gl(project["id"], gl_code="GL-L", description="loans")
        acct = create_account(
            project["id"], pt["id"], legacy_account_number="LN-1",
            account_type="LOAN", opening_principal_cents=36000000,
            accrual_start_date="2026-01-31",
        )
        map_account(acct["id"], gl["id"], project["id"])
        advance_to_mock_conversion(project["id"])
        run = start_mock_run(project["id"])
        finalize_run(run["id"], clock="2026-03-01T00:00:00Z")
        data = get_success_data(api.get_account(acct["id"], CE))
        # 360*(0) + 30*(3-1) + min(1,30) - min(31,30) + 1 = 32 days.
        assert data["daily_interest_cents"] == 6000
        assert data["cutoff_accrued_interest_cents"] == 192000
        assert data["conversion_balance_cents"] == 36000000


class TestMonthlyFee:
    def test_fee_waiver_threshold_equality_waives(self, api):
        """PRD §3.4: "otherwise, when the balance is at least the threshold the
        fee is waived to zero — equality waives — and below the threshold the
        full fee is assessed."

        Design: Difficulty/boundary_precision_check/fee_waiver_threshold_equality_waives
        """
        project = create_project()
        pt = create_product(
            project["id"], product_code="DDA-FEE", rate=0.0,
            monthly_fee_cents=1500, fee_waiver_threshold_cents=500000,
        )
        gl = create_gl(project["id"])
        a_eq = create_account(
            project["id"], pt["id"], legacy_account_number="A-EQ",
            opening_principal_cents=500000,
        )
        a_below = create_account(
            project["id"], pt["id"], legacy_account_number="A-BELOW",
            opening_principal_cents=499999,
        )
        map_account(a_eq["id"], gl["id"], project["id"])
        map_account(a_below["id"], gl["id"], project["id"])
        advance_to_mock_conversion(project["id"])
        run = start_mock_run(project["id"])
        finalize_run(run["id"])
        eq = get_success_data(api.get_account(a_eq["id"], CE))
        below = get_success_data(api.get_account(a_below["id"], CE))
        assert eq["conversion_balance_cents"] == 500000
        assert eq["monthly_fee_assessed_cents"] == 0
        assert below["conversion_balance_cents"] == 499999
        assert below["monthly_fee_assessed_cents"] == 1500

    def test_fee_below_threshold_pays_full_and_equality_waives(self, api):
        """PRD §3.4: "otherwise, when the balance is at least the threshold the
        fee is waived to zero — equality waives — and below the threshold the
        full fee is assessed."

        Design: Difficulty/boundary_precision_check/fee_waiver_threshold_equality_waives
        """
        project = create_project()
        pt = create_product(
            project["id"], product_code="DDA-FEE2", rate=0.0,
            monthly_fee_cents=700, fee_waiver_threshold_cents=100000,
        )
        gl = create_gl(project["id"])
        a_at = create_account(
            project["id"], pt["id"], legacy_account_number="B-AT",
            opening_principal_cents=100000,
        )
        a_low = create_account(
            project["id"], pt["id"], legacy_account_number="B-LOW",
            opening_principal_cents=99999,
        )
        map_account(a_at["id"], gl["id"], project["id"])
        map_account(a_low["id"], gl["id"], project["id"])
        advance_to_mock_conversion(project["id"])
        run = start_mock_run(project["id"])
        finalize_run(run["id"])
        at = get_success_data(api.get_account(a_at["id"], CE))
        low = get_success_data(api.get_account(a_low["id"], CE))
        assert at["monthly_fee_assessed_cents"] == 0
        assert low["monthly_fee_assessed_cents"] == 700

    def test_loan_accounts_never_assess_monthly_fee(self, api):
        """PRD §3.4: "For a `LOAN` account the assessed fee is always zero."

        Design: Corner/calculations/loan_accounts_never_assess_monthly_fee
        """
        project = create_project()
        pt = create_product(project["id"], product_code="LN", kind="LOAN",
                            accrual_method="ACT_360", rate=0.05,
                            monthly_fee_cents=900)
        gl = create_gl(project["id"], gl_code="GL-L", description="loans")
        acct = create_account(
            project["id"], pt["id"], legacy_account_number="LN-9",
            account_type="LOAN", opening_principal_cents=500000,
        )
        map_account(acct["id"], gl["id"], project["id"])
        advance_to_mock_conversion(project["id"])
        run = start_mock_run(project["id"])
        finalize_run(run["id"])
        data = get_success_data(api.get_account(acct["id"], CE))
        assert data["monthly_fee_assessed_cents"] == 0


class TestGLVarianceInputSet:
    def test_blocked_account_drops_out_of_expected_after_rollback(self, api):
        """PRD §3.3: "`expected_balance_cents`, the sum of
        `opening_principal_cents` across its accounts in `MAPPED`, `EXCEPTION`,
        `CLEARED`, or `CONVERTED` status"
        PRD §3.6: "every account in `MAPPED`, `CLEARED`, or `EXCEPTION` becomes
        `BLOCKED` with `frozen_flag` left true; the project returns to
        `MOCK_CONVERSION` with `cutover_scheduled_date` cleared to null"

        Design: Corner/calculations/gl_variance_excludes_staged_and_blocked_accounts
        """
        ctx = setup_plan_scheduled()
        pid = ctx["project"]["id"]
        gl_id = ctx["gl"]["id"]
        acct_id = ctx["account"]["id"]
        pre = get_success_data(api.get_gl_account(gl_id, TEST_USERS["fc_headers"]))
        assert pre["expected_balance_cents"] == 100000
        plan = get_success_data(api.rollback_plan(ctx["plan"]["id"], PM))
        assert plan["status"] == "ROLLED_BACK"
        acct = get_success_data(api.get_account(acct_id, TEST_USERS["fc_headers"]))
        assert acct["status"] == "BLOCKED"
        post = get_success_data(api.get_gl_account(gl_id, TEST_USERS["fc_headers"]))
        assert post["expected_balance_cents"] == 0
        proj = get_success_data(api.get_project(pid, PM))
        assert proj["status"] == "MOCK_CONVERSION"
        assert proj["cutover_scheduled_date"] is None


class TestDerivedFieldRecomputation:
    def test_conversion_balance_recomputed_per_finalize_clock(self, api):
        """PRD §3.5: "The system stamps `finished_at` from the clock, computes
        `duration_seconds` as the whole seconds between start and finish,
        recomputes the accrual and monthly fee for every in-scope account at
        the finalize clock date, recomputes every GL's variance, and then
        snapshots three run-level figures"

        Design: Corner/cross_cutting_layers/derived_field_recomputation_on_mock_finalize
        """
        project = create_project()
        pt = create_product(project["id"], product_code="DDA", rate=0.03)
        gl = create_gl(project["id"])
        acct = create_account(
            project["id"], pt["id"], legacy_account_number="L-1",
            opening_principal_cents=36500000, accrual_start_date="2026-09-01",
        )
        map_account(acct["id"], gl["id"], project["id"])
        advance_to_mock_conversion(project["id"])
        r1 = start_mock_run(project["id"], run_label="MOCK-1")
        finalize_run(r1["id"], clock="2026-09-05T00:00:00Z")
        bal1 = get_success_data(api.get_account(acct["id"], CE))[
            "conversion_balance_cents"]
        r2 = start_mock_run(project["id"], run_label="MOCK-2")
        finalize_run(r2["id"], clock="2026-09-15T00:00:00Z")
        row = get_success_data(api.get_account(acct["id"], CE))
        assert row["daily_interest_cents"] == 3000
        assert bal1 == 36515000  # 5 days accrued
        assert row["conversion_balance_cents"] == 36545000  # 15 days, recomputed
