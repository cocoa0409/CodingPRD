"""Dual-variant calculations: the same entity carrying two divergent totals."""
from test_helpers import (
    activate_promo_schedule,
    advance_clock,
    assert_account_ledger_invariant,
    assert_device_plan,
    assert_promo_schedule,
    assert_trade_in_assessment,
    create_account,
    create_activated_line,
    create_device_plan,
    create_promo_schedule,
    create_trade_in_assessment,
    get_account,
    get_device_plan,
    get_promo_schedule,
    grade_trade_in_assessment,
)


class TestPromoCreditProjectionVariantDivergence:
    """The projection counts billable months; the vested total counts elapsed cycles."""

    def test_provisional_total_projects_32000_while_vested_total_is_zero(self, api):
        """PRD §3.4: "The provisional total, written to `provisional_total_cents`, is a
        flat base credit of 20 000 cents plus 1 000 cents for each billable month, so it
        treats every billable month as if it had already been completed and already
        includes the retention bonus."
        PRD §3.4: "The vested total, written to `vested_total_cents`, is different in
        kind: it credits only the cycles the line has actually completed inside the
        window, so it is 1 000 cents multiplied by `cycles_elapsed`."

        Design: Difficulty/dual_variant_calc/promo_projection_forward_vs_vested_chronological
        """
        account = create_account(payment_history_score=720, existing_deposit_cents=50000)
        line = create_activated_line(account["id"], "4155550101", billing_mode="PREPAID")
        advance_clock("2026-09-02T00:00:00Z")

        schedule = create_promo_schedule(
            line,
            monthly_credit_cents=1000,
            installment_months=12,
            retention_requirement_cycles=12,
            window_start="2026-09-02T00:00:00Z",
        )

        assert schedule["provisional_total_cents"] == 32000
        assert schedule["vested_total_cents"] == 0
        assert schedule["cycles_elapsed"] == 0
        assert (
            schedule["provisional_total_cents"] != schedule["vested_total_cents"]
        ), "the forward-looking variant and the chronological variant must not coincide"
        assert_promo_schedule(schedule)

    def test_account_ledger_reflects_the_projected_total_on_creation(self, api):
        """PRD §3.4: "the account's `promo_credited_cents` is incremented by the
        `provisional_total_cents` of the new schedule, after which the account's
        `net_promo_credit_cents` is recomputed as `promo_credited_cents` minus
        `promo_clawed_back_cents`."

        Design: Difficulty/dual_variant_calc/promo_projection_forward_vs_vested_chronological
        """
        account = create_account(payment_history_score=720, existing_deposit_cents=50000)
        line = create_activated_line(account["id"], "4155550101", billing_mode="PREPAID")
        advance_clock("2026-09-02T00:00:00Z")

        create_promo_schedule(
            line,
            monthly_credit_cents=1000,
            installment_months=12,
            retention_requirement_cycles=12,
            window_start="2026-09-02T00:00:00Z",
        )

        refreshed = get_account(account["id"])
        assert refreshed["promo_credited_cents"] == 32000
        assert refreshed["net_promo_credit_cents"] == 32000
        assert_account_ledger_invariant(refreshed)

    def test_vested_total_stays_strictly_below_the_projection_while_the_window_runs(
        self, api
    ):
        """PRD §3.4: "For any schedule whose `cycles_elapsed` is below
        `billable_months` — the ordinary case while the window is still running — the
        vested total is strictly smaller than the provisional total, and the difference
        is exactly the retention bonus that has not yet been earned."

        Design: Difficulty/dual_variant_calc/promo_projection_forward_vs_vested_chronological
        """
        account = create_account(payment_history_score=720, existing_deposit_cents=50000)
        line = create_activated_line(account["id"], "4155550101", billing_mode="PREPAID")
        advance_clock("2026-09-02T00:00:00Z")

        schedule = create_promo_schedule(
            line,
            monthly_credit_cents=1000,
            installment_months=12,
            retention_requirement_cycles=12,
            window_start="2026-09-02T00:00:00Z",
        )
        activate_promo_schedule(schedule["id"])
        advance_clock("2026-10-17T00:00:00Z")

        refreshed = get_promo_schedule(schedule["id"])
        assert refreshed["provisional_total_cents"] == 32000
        assert refreshed["vested_total_cents"] == 1000 * refreshed["cycles_elapsed"]
        assert refreshed["vested_total_cents"] < refreshed["provisional_total_cents"]


class TestTradeInCreditVariantDivergence:
    """The estimate is keyed on the self-report; the settled credit on the grade."""

    def test_estimated_and_final_credits_diverge_and_settle_on_the_plan(self, api):
        """PRD §3.5: "the estimated credit, written to `estimated_credit_cents`, is
        looked up from the condition the customer declared."
        PRD §3.5: "The final credit, written to `final_credit_cents`, is looked up from
        the inspector's `graded_condition` using the same five-value table, and
        `grade_delta_cents` is computed as `final_credit_cents` minus
        `estimated_credit_cents` — a negative delta means the device graded worse than
        the customer declared, and a zero delta means the self-report was accurate."

        Design: Difficulty/dual_variant_calc/trade_in_estimated_vs_final_condition_keyed
        """
        account = create_account(payment_history_score=720, existing_deposit_cents=50000)
        line = create_activated_line(account["id"], "4155550102", billing_mode="PREPAID")
        advance_clock("2026-09-02T00:00:00Z")
        plan = create_device_plan(
            line,
            device_price_cents=60000,
            down_payment_cents=10000,
            installment_months=24,
            activation_at="2026-09-02T00:00:00Z",
        )
        assessment = create_trade_in_assessment(
            plan["id"], declared_condition="GOOD"
        )
        assert assessment["estimated_credit_cents"] == 42000

        graded = grade_trade_in_assessment(assessment["id"], "FAIR")

        assert graded["estimated_credit_cents"] == 42000
        assert graded["final_credit_cents"] == 24000
        assert graded["grade_delta_cents"] == -18000
        assert_trade_in_assessment(graded)

    def test_graded_credit_settles_against_the_plan_balance(self, api):
        """PRD §3.5: "The plan's `trade_in_credit_cents` is set to `final_credit_cents`,
        and the plan's `remaining_balance_cents` is recomputed as the greatest of the
        device price less the down payment less the final credit, and zero — the balance
        floors at zero rather than turning negative when a generous trade-in exceeds
        what is owed."

        Design: Difficulty/dual_variant_calc/trade_in_estimated_vs_final_condition_keyed
        """
        account = create_account(payment_history_score=720, existing_deposit_cents=50000)
        line = create_activated_line(account["id"], "4155550102", billing_mode="PREPAID")
        advance_clock("2026-09-02T00:00:00Z")
        plan = create_device_plan(
            line,
            device_price_cents=60000,
            down_payment_cents=10000,
            installment_months=24,
            activation_at="2026-09-02T00:00:00Z",
        )
        assessment = create_trade_in_assessment(plan["id"], declared_condition="GOOD")

        grade_trade_in_assessment(assessment["id"], "FAIR")

        settled = get_device_plan(plan["id"])
        assert settled["trade_in_credit_cents"] == 24000
        assert settled["remaining_balance_cents"] == 26000
        assert_device_plan(settled)

    def test_accurate_self_report_yields_a_zero_delta(self, api):
        """PRD §3.5: "a zero delta means the self-report was accurate."

        Design: Difficulty/dual_variant_calc/trade_in_estimated_vs_final_condition_keyed
        """
        account = create_account(payment_history_score=720, existing_deposit_cents=50000)
        line = create_activated_line(account["id"], "4155550102", billing_mode="PREPAID")
        advance_clock("2026-09-02T00:00:00Z")
        plan = create_device_plan(
            line,
            device_price_cents=60000,
            down_payment_cents=10000,
            installment_months=24,
            activation_at="2026-09-02T00:00:00Z",
        )
        assessment = create_trade_in_assessment(plan["id"], declared_condition="POOR")

        graded = grade_trade_in_assessment(assessment["id"], "POOR")

        assert graded["estimated_credit_cents"] == 8000
        assert graded["final_credit_cents"] == 8000
        assert graded["grade_delta_cents"] == 0

    def test_generous_trade_in_floors_the_plan_balance_at_zero(self, api):
        """PRD §3.5: "the balance floors at zero rather than turning negative when a
        generous trade-in exceeds what is owed."

        Design: Difficulty/dual_variant_calc/trade_in_estimated_vs_final_condition_keyed
        """
        account = create_account(payment_history_score=720, existing_deposit_cents=50000)
        line = create_activated_line(account["id"], "4155550102", billing_mode="PREPAID")
        advance_clock("2026-09-02T00:00:00Z")
        plan = create_device_plan(
            line,
            device_price_cents=60000,
            down_payment_cents=10000,
            installment_months=24,
            activation_at="2026-09-02T00:00:00Z",
        )
        assessment = create_trade_in_assessment(plan["id"], declared_condition="POOR")

        graded = grade_trade_in_assessment(assessment["id"], "FLAWLESS")

        assert graded["final_credit_cents"] == 60000
        assert graded["grade_delta_cents"] == 52000
        settled = get_device_plan(plan["id"])
        assert settled["remaining_balance_cents"] == 0