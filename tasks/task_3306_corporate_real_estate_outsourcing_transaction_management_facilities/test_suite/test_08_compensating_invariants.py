"""Compensating invariants: forward actions conserve a named quantity."""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    validate_success,
    setup_executed_lease_with_accrual,
    setup_approved_request,
    create_broker_engagement,
    assign_broker_engagement,
    TEST_USERS,
    ApiErrorId,
    ae_headers,
)

TM = TEST_USERS["transaction_manager_headers"]


class TestFeeLedgerConservation:

    def test_credit_ledger_is_unchanged_by_the_application(self, api):
        """PRD §2.9: "fee_ledger_credit_cents is the sum of credit_amount_cents
        over every commission record on the account: posting a record raises it,
        and applying the credit against a fee accrual transfers value within the
        ledger without ever changing the total."

        Design: Difficulty/compensating_invariant/commission_credit_ledger_conserves_under_apply
        """
        account, lease, request, assignment, engagement, accrual = (
            setup_executed_lease_with_accrual(
                accrual_period="2026-Q3", base_fee_cents=3_000_000,
                extra_record={
                    "base_rent_cents": 30_000_000,
                    "commission_pct": 0.15,
                    "accrual_date": "2026-07-01T00:00:00Z",
                },
            )
        )
        before = get_success_data(api.get_account(account["id"], ae_headers(account)))
        applied = validate_success(api.apply_lease_execution(accrual["id"], TM), 200)
        after = get_success_data(api.get_account(account["id"], ae_headers(account)))
        # 4,500,000.00 (posted) + 1,850,000.00 (lease execution) = 6,350,000.00
        assert before["fee_ledger_credit_cents"] == pytest.approx(6_350_000.00, abs=0.01)
        assert after["fee_ledger_credit_cents"] == pytest.approx(6_350_000.00, abs=0.01)
        assert after["fee_ledger_credit_cents"] == pytest.approx(
            before["fee_ledger_credit_cents"], abs=0.01
        )
        assert applied["credit_application_state"] == "CREDITED"
        assert applied["applied_credit_cents"] == pytest.approx(6_350_000.00, abs=0.01)

    def test_second_application_on_a_credited_accrual_is_locked(self, api):
        """PRD §3.4: "It requires the target accrual to be OPEN — an accrual that
        is not open is rejected with ERR_FEE_ACCRUAL_LOCKED (HTTP 409)."

        Design: Difficulty/compensating_invariant/commission_credit_ledger_conserves_under_apply
        """
        account, lease, request, assignment, engagement, accrual = (
            setup_executed_lease_with_accrual(
                accrual_period="2026-Q3", base_fee_cents=3_000_000,
            )
        )
        validate_success(api.apply_lease_execution(accrual["id"], TM), 200)
        res = api.apply_lease_execution(accrual["id"], TM)
        validate_error(res, ApiErrorId.ERR_FEE_ACCRUAL_LOCKED)


class TestBrokerPoolConservation:

    def test_engagement_execution_splits_the_deal_commission(self, api):
        """PRD §3.4: "A SENIOR broker's raw share is the deal commission
        multiplied by 6,000 and divided by 10,000".
        PRD §3.4: "The conservation invariant is exact: broker_share_cents plus
        account_share_cents equals deal_commission_cents, with no cent created or
        destroyed."

        Design: Difficulty/compensating_invariant/broker_pool_conserves_under_engagement_termination
        """
        account, lease, request, assignment = setup_approved_request()
        engagement = create_broker_engagement(account, request)
        engagement = assign_broker_engagement(engagement)
        executed = validate_success(api.execute_broker_engagement(engagement["id"], TM), 200)
        assert executed["deal_commission_cents"] == 1_850_000
        assert executed["broker_share_cents"] == 1_110_000
        assert executed["account_share_cents"] == 740_000
        assert (
            executed["broker_share_cents"] + executed["account_share_cents"]
            == executed["deal_commission_cents"]
        )

    def test_terminating_the_engagement_restores_the_pool(self, api):
        """PRD §3.4: "Terminating an already-executed engagement is not neutral:
        it sets broker_share_cents and account_share_cents back to zero, which
        restores the account's broker_pool_allocated_cents to exactly the value it
        held before the execution."

        Design: Difficulty/compensating_invariant/broker_pool_conserves_under_engagement_termination
        """
        account, lease, request, assignment = setup_approved_request()
        engagement = create_broker_engagement(account, request)
        engagement = assign_broker_engagement(engagement)
        validate_success(api.execute_broker_engagement(engagement["id"], TM), 200)
        terminated = validate_success(
            api.terminate_broker_engagement(engagement["id"], TM), 200
        )
        assert terminated["broker_share_cents"] == 0
        assert terminated["account_share_cents"] == 0
        current = get_success_data(api.get_account(account["id"], ae_headers(account)))
        assert current["broker_pool_allocated_cents"] == pytest.approx(0.00, abs=0.01)