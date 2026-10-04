"""Combinatorial formulas whose branches nest on more than one input."""
from test_helpers import (
    advance_clock,
    assert_device_plan_invariants,
    assert_migration_request,
    create_account,
    create_activated_line,
    create_device_plan,
    create_line_addition,
    check_migration_eligibility,
    get_account,
    get_migration_request,
    review_line_addition,
    setup_account_with_active_lines,
    setup_migration_with_anchor_lines,
)


class TestCreditClassNestedScoreAndLineCount:
    """The score ladder is read first, then demoted by the post-addition line count."""

    def test_fifth_line_on_the_account_demotes_class_b_to_class_c(self, api):
        """PRD §3.6: "if the line count the account would hold after this addition — the
        current active line count plus the request's `line_count` — is 5 or more, and the
        class read off the score was `CLASS_A` or `CLASS_B`, the determined class is
        downgraded to `CLASS_C`."

        Design: Difficulty/combinatorial_formula/credit_class_nested_score_and_family_tier
        """
        account, _anchor = setup_account_with_active_lines(1, mdn_offset=0)
        assert account["payment_history_score"] == 720

        request = create_line_addition(account["id"], 4)
        assert request["line_count"] == 4

        decided = review_line_addition(request["id"], decision="APPROVE")

        assert decided["determined_credit_class"] == "CLASS_C"
        assert decided["required_deposit_cents"] == 25000
        assert decided["request_state"] == "APPROVED"

    def test_same_score_without_the_fifth_line_stays_class_b(self, api):
        """PRD §3.6: "The deposit that follows from the class is fixed per class:
        `CLASS_A` requires 0 cents, `CLASS_B` requires 10 000 cents, `CLASS_C` requires
        25 000 cents, `CLASS_D` requires 50 000 cents, and `BLOCKED` requires 0 cents,
        since a blocked request never gets far enough to owe a deposit."

        Design: Difficulty/combinatorial_formula/credit_class_nested_score_and_family_tier
        """
        account = create_account(payment_history_score=720, existing_deposit_cents=50000)

        request = create_line_addition(account["id"], 4)
        decided = review_line_addition(request["id"], decision="APPROVE")

        assert decided["determined_credit_class"] == "CLASS_B"
        assert decided["required_deposit_cents"] == 10000
        assert decided["request_state"] == "APPROVED"

    def test_deposit_follows_the_determined_class_on_both_accounts(self, api):
        """PRD §3.6: "The deposit that follows from the class is fixed per class:
        `CLASS_A` requires 0 cents, `CLASS_B` requires 10 000 cents, `CLASS_C` requires
        25 000 cents, `CLASS_D` requires 50 000 cents, and `BLOCKED` requires 0 cents,
        since a blocked request never gets far enough to owe a deposit."

        Design: Difficulty/combinatorial_formula/credit_class_nested_score_and_family_tier
        """
        busy, _busy_line = setup_account_with_active_lines(1, mdn_offset=10)
        idle, _ = setup_account_with_active_lines(0, mdn_offset=20)

        busy_request = review_line_addition(
            create_line_addition(busy["id"], 4)["id"], decision="APPROVE"
        )
        idle_request = review_line_addition(
            create_line_addition(idle["id"], 4)["id"], decision="APPROVE"
        )

        assert busy_request["required_deposit_cents"] == 25000
        assert idle_request["required_deposit_cents"] == 10000
        assert busy_request["determined_credit_class"] == "CLASS_C"
        assert idle_request["determined_credit_class"] == "CLASS_B"


class TestDeviceInstallmentRoundingOrder:
    """Floor the recurring installment first, then hand the remainder to the first one."""

    def test_recurring_installment_is_the_floored_quotient(self, api):
        """PRD §3.5: "The regular monthly installment is that financed balance divided
        by `installment_months` with the remainder discarded — the per-installment amount
        is floored, never rounded — and the entire remainder is then assigned to the first
        installment, which is therefore as large as or larger than every subsequent one."

        Design: Difficulty/combinatorial_formula/device_installment_rounding_order_pinned
        """
        account = create_account(payment_history_score=720, existing_deposit_cents=50000)
        line = create_activated_line(account["id"], "4155550301", billing_mode="POSTPAID")
        advance_clock("2026-09-02T00:00:00Z")

        plan = create_device_plan(
            line,
            device_price_cents=60000,
            down_payment_cents=10000,
            installment_months=24,
            activation_at="2026-09-02T00:00:00Z",
        )

        assert plan["monthly_installment_cents"] == 2083
        assert plan["remaining_balance_cents"] == 50000
        assert plan["plan_state"] == "ACTIVE"
        assert_device_plan_invariants(plan)

    def test_the_whole_remainder_lands_on_the_first_installment(self, api):
        """PRD §3.5: "the entire remainder is then assigned to the first installment,
        which is therefore as large as or larger than every subsequent one."

        Design: Difficulty/combinatorial_formula/device_installment_rounding_order_pinned
        """
        account = create_account(payment_history_score=720, existing_deposit_cents=50000)
        line = create_activated_line(account["id"], "4155550301", billing_mode="POSTPAID")
        advance_clock("2026-09-02T00:00:00Z")

        plan = create_device_plan(
            line,
            device_price_cents=60000,
            down_payment_cents=10000,
            installment_months=24,
            activation_at="2026-09-02T00:00:00Z",
        )

        financed = plan["device_price_cents"] - plan["down_payment_cents"]
        recurring = plan["monthly_installment_cents"]
        first_installment = financed - recurring * (plan["installment_months"] - 1)
        assert first_installment == 2091
        assert first_installment >= recurring

    def test_down_payment_covering_the_price_yields_a_zero_installment(self, api):
        """PRD §3.5: "A quoted plan whose down payment covers the whole price has a
        financed balance of zero and therefore a zero installment."

        Design: Difficulty/combinatorial_formula/device_installment_rounding_order_pinned
        """
        account = create_account(payment_history_score=720, existing_deposit_cents=50000)
        line = create_activated_line(account["id"], "4155550301", billing_mode="POSTPAID")
        advance_clock("2026-09-02T00:00:00Z")

        plan = create_device_plan(
            line,
            device_price_cents=60000,
            down_payment_cents=60000,
            installment_months=24,
            activation_at="2026-09-02T00:00:00Z",
        )

        assert plan["remaining_balance_cents"] == 0
        assert plan["monthly_installment_cents"] == 0


class TestMigrationProrationEvaluationOrder:
    """The carry term reads the device balance the same transition just wrote."""

    def test_proration_credit_includes_the_carry_component(self, api):
        """PRD §3.3: "Third, the tier carries a plan rate in cents: tier 1 is 5 000
        cents, tier 2 is 4 000 cents, tier 3 is 3 000 cents and tier 4 is 2 500 cents."
        PRD §3.3: "Sixth, the carry component is one half of the sum of the migration's
        `prepaid_balance_cents` and its `device_balance_cents`, rounded half-up to whole
        cents."
        PRD §3.3: "Seventh, `proration_credit_cents` is the proration component plus the
        carry component."

        Design: Difficulty/combinatorial_formula/migration_proration_evaluation_order_carry
        """
        account, _anchors, migrating, migration = setup_migration_with_anchor_lines(
            anchor_line_count=1,
            mdn_offset=100,
            prepaid_balance_cents=10000,
            requested_cutover_at="2026-10-01T00:00:00Z",
        )
        assert get_account(account["id"])["active_line_count"] == 1

        check_migration_eligibility(migration["id"])
        advance_clock("2026-10-01T00:00:00Z")
        completed = get_migration_request(migration["id"])

        assert completed["migration_state"] == "CUTOVER_COMPLETE"
        assert completed["carried_mdn"] == migrating["mdn"]
        assert completed["device_balance_cents"] == 0
        assert completed["proration_credit_cents"] == 8867

    def test_carry_component_is_half_of_the_carried_balances(self, api):
        """PRD §3.3: "Sixth, the carry component is one half of the sum of the migration's
        `prepaid_balance_cents` and its `device_balance_cents`, rounded half-up to whole
        cents."

        Design: Difficulty/combinatorial_formula/migration_proration_evaluation_order_carry
        """
        _account, _anchors, _migrating, migration = setup_migration_with_anchor_lines(
            anchor_line_count=1,
            mdn_offset=200,
            prepaid_balance_cents=10000,
            requested_cutover_at="2026-10-01T00:00:00Z",
        )

        check_migration_eligibility(migration["id"])
        advance_clock("2026-10-01T00:00:00Z")
        completed = get_migration_request(migration["id"])

        carry = round(
            0.50 * (completed["prepaid_balance_cents"] + completed["device_balance_cents"])
        )
        assert carry == 5000
        assert completed["proration_credit_cents"] > carry
        assert_migration_request(completed)

    def test_remaining_days_zeroes_the_proration_component_late_in_the_month(self, api):
        """PRD §3.3: "Fourth, the remaining days in the current billing cycle are 30 minus
        the day-of-month of the current logical clock instant, so a cutover landing on
        the first of the month leaves 29 remaining days, and a cutover landing on the
        thirtieth or thirty-first leaves a number that is zero or negative."

        Design: Difficulty/combinatorial_formula/migration_proration_evaluation_order_carry
        """
        _account, _anchors, _migrating, migration = setup_migration_with_anchor_lines(
            anchor_line_count=1,
            mdn_offset=300,
            prepaid_balance_cents=10000,
            requested_cutover_at="2026-10-30T00:00:00Z",
        )

        check_migration_eligibility(migration["id"])
        advance_clock("2026-10-30T00:00:00Z")
        completed = get_migration_request(migration["id"])

        # day-of-month 30 leaves zero remaining days, so only the carry term contributes.
        assert completed["proration_credit_cents"] == 5000