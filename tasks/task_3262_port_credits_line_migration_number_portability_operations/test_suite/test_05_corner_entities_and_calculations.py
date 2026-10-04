"""Corner coverage: entity defaults and the derivation boundaries behind them."""
from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
    advance_clock,
    api_client,
    assert_account,
    assert_account_ledger_invariant,
    assert_device_plan,
    create_account,
    create_activated_line,
    create_device_plan,
    create_line_addition,
    review_line_addition,
)


class TestAccountCreationDefaults:
    def test_credit_class_and_deposit_are_derived_not_accepted(self, api):
        """PRD §3.6: "An account is created in `account_status` `OPEN`, and opening it
        derives its `credit_class` and `deposit_required_cents` from its
        `payment_history_score`, its `existing_deposit_cents` and its `active_line_count`
        through the same credit-class rule that underwrites line additions, so a new
        account's class is never left unset."

        Design: Corner/entities/account_creation_defaults_credit_class_and_deposit
        """
        account = create_account(
            account_type="BUSINESS",
            tax_id_last4="3131",
            payment_history_score=900,
            existing_deposit_cents=0,
        )

        assert account["credit_class"] == "CLASS_A"
        assert account["deposit_required_cents"] == 0
        assert_account(account)

    def test_a_fresh_account_opens_with_empty_server_maintained_counters(self, api):
        """PRD §3.6: "Each of these begins at 0 on a freshly opened account, as does
        `deposit_required_cents` when the derived class calls for no deposit"

        Design: Corner/entities/account_creation_defaults_credit_class_and_deposit
        """
        account = create_account(
            account_type="BUSINESS",
            tax_id_last4="3131",
            payment_history_score=900,
            existing_deposit_cents=0,
        )

        assert account["active_line_count"] == 0
        assert account["net_promo_credit_cents"] == 0
        assert account["version"] == 1
        assert_account_ledger_invariant(account)

    def test_account_type_outside_the_enum_is_refused(self, api):
        """PRD §3.6: "an account is opened by a platform operator who declares its
        `account_type` — either `FAMILY` or `BUSINESS`"

        Design: Corner/entities/account_creation_rejects_unknown_account_type
        """
        response = api_client.create_account(
            {
                "account_type": "ENTERPRISE",
                "tax_id_last4": "3232",
                "payment_history_score": 700,
            },
            ADMIN,
        )

        assert response.status_code == 400
        assert response.json()["data"]["error_id"] == "ERR_INVALID_REQUEST"

    def test_reading_an_unknown_subscriber_line_reports_not_found(self, api):
        """PRD §3.11: "A read that names a resource that does not exist fails with the
        identifier for that resource type: a missing subscriber line yields
        `ERR_SUBSCRIBER_LINE_NOT_FOUND` (404)"

        Design: Corner/entities/subscriber_line_read_unknown_id_returns_not_found
        """
        response = api_client.get_subscriber_line(NON_EXISTENT_UUID, ADMIN)

        assert response.json()["data"]["error_id"] == "ERR_SUBSCRIBER_LINE_NOT_FOUND"


class TestCreditClassScoreBoundary:
    def test_exactly_800_lands_in_class_a_with_no_deposit(self, api):
        """PRD §3.6: "a score of 800 or above yields `CLASS_A`."
        PRD §3.6: "The deposit that follows from the class is fixed per class:
        `CLASS_A` requires 0 cents"

        Design: Corner/calculations/credit_class_boundary_score_800_is_class_a
        """
        account = create_account(
            payment_history_score=800, existing_deposit_cents=50000
        )
        request = create_line_addition(account["id"], 1)

        decided = review_line_addition(request["id"], decision="APPROVE")

        assert decided["determined_credit_class"] == "CLASS_A"
        assert decided["required_deposit_cents"] == 0

    def test_one_point_below_800_lands_in_class_b(self, api):
        """PRD §3.6: "from 650 up to but not including 800 yields `CLASS_B`"
        PRD §3.6: "`CLASS_B` requires 10 000 cents"

        Design: Corner/calculations/credit_class_boundary_score_800_is_class_a
        """
        account = create_account(
            payment_history_score=799, existing_deposit_cents=50000
        )
        request = create_line_addition(account["id"], 1)

        decided = review_line_addition(request["id"], decision="APPROVE")

        assert decided["determined_credit_class"] == "CLASS_B"
        assert decided["required_deposit_cents"] == 10000

    def test_the_class_ladder_demotes_to_class_c_at_five_lines(self, api):
        """PRD §3.6: "if the line count the account would hold after this addition — the
        current active line count plus the request's `line_count` — is 5 or more, and the
        class read off the score was `CLASS_A` or `CLASS_B`, the determined class is
        downgraded to `CLASS_C`."

        Design: Corner/calculations/credit_class_boundary_score_800_is_class_a
        """
        account = create_account(
            payment_history_score=800, existing_deposit_cents=50000
        )
        request = create_line_addition(account["id"], 5)

        decided = review_line_addition(request["id"], decision="APPROVE")

        assert decided["determined_credit_class"] == "CLASS_C"
        assert decided["required_deposit_cents"] == 25000


class TestDeviceInstallmentFloorAndRemainder:
    def test_floored_installment_and_the_first_installment_receipt(self, api):
        """PRD §3.5: "The regular monthly installment is that financed balance divided
        by `installment_months` with the remainder discarded — the per-installment amount
        is floored, never rounded — and the entire remainder is then assigned to the first
        installment, which is therefore as large as or larger than every subsequent one."

        Design: Corner/calculations/device_installment_floor_and_first_installment_remainder
        """
        account = create_account(payment_history_score=720, existing_deposit_cents=50000)
        line = create_activated_line(account["id"], "4155554401", billing_mode="POSTPAID")
        advance_clock("2026-09-02T00:00:00Z")

        plan = create_device_plan(
            line,
            device_model="Galaxy X2",
            device_price_cents=100000,
            down_payment_cents=0,
            installment_months=36,
            activation_at="2026-09-02T00:00:00Z",
        )

        assert plan["monthly_installment_cents"] == 2777
        assert plan["remaining_balance_cents"] == 100000

    def test_the_first_installment_absorbs_the_whole_remainder(self, api):
        """PRD §3.5: "the entire remainder is then assigned to the first installment,
        which is therefore as large as or larger than every subsequent one."

        Design: Corner/calculations/device_installment_floor_and_first_installment_remainder
        """
        account = create_account(payment_history_score=720, existing_deposit_cents=50000)
        line = create_activated_line(account["id"], "4155554401", billing_mode="POSTPAID")
        advance_clock("2026-09-02T00:00:00Z")

        plan = create_device_plan(
            line,
            device_model="Galaxy X2",
            device_price_cents=100000,
            down_payment_cents=0,
            installment_months=36,
            activation_at="2026-09-02T00:00:00Z",
        )

        financed = plan["device_price_cents"] - plan["down_payment_cents"]
        recurring = plan["monthly_installment_cents"]
        first_installment = financed - recurring * (plan["installment_months"] - 1)
        assert first_installment == 2805
        assert recurring * (plan["installment_months"] - 1) + first_installment == financed
        assert first_installment >= recurring
        assert_device_plan(plan)