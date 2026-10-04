"""Endpoint side effects: observable consequences of a transition or clock move."""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_paginated,
    validate_success,
    begin_offboarding,
    create_activated_account,
    create_transition_task,
    set_clock,
    setup_negotiating_lease,
    TEST_USERS,
    ae_headers,
)

TM = TEST_USERS["transaction_manager_headers"]
TRANS = TEST_USERS["transition_manager_headers"]


class TestLeaseExecutionSideEffects:

    def test_execute_recomputes_annual_net_fee(self, api):
        """PRD §3.4: "That posting recomputes the account's annual_net_fee_cents
        through the fee rule, and the account's version is incremented."

        Design: Corner/endpoints/lease_execute_recomputes_open_accrual_credit
        """
        account, lease, request, assignment, engagement = setup_negotiating_lease()
        executed = validate_success(api.execute_lease(lease["id"], TM), 200)
        assert executed["pipeline_state"] == "EXECUTED"
        current = get_success_data(api.get_account(account["id"], ae_headers(account)))
        # gross fee 47,200,000 less the 1,850,000 third-party credit.
        assert current["annual_net_fee_cents"] == pytest.approx(45_350_000.00, abs=0.01)


class TestClockAdvanceSideEffects:

    def test_clock_past_due_date_fails_the_task(self, api):
        """PRD §3.9: "Every TransitionTask whose due_at is at or before the new
        instant and whose state is PENDING or IN_PROGRESS becomes FAILED".
        PRD §3.8: "completion reaches exactly 10,000 only when every task is
        terminal."

        Design: Corner/endpoints/clock_advance_expires_overdue_transition_task
        """
        account = create_activated_account_with_offboarding()
        task = create_transition_task(
            account, task_name="Records handover",
            task_type="RECORDS_TRANSFER", due_at="2026-12-01T00:00:00Z",
        )
        set_clock("2026-12-15T00:00:00Z")
        task_after = validate_success(api.get_transition_task(task["id"], TRANS), 200)
        assert task_after["task_state"] == "FAILED"
        current = get_success_data(api.get_account(account["id"], ae_headers(account)))
        assert current["completion_pct_bps"] == 10_000


class TestAccountScopedListing:

    def test_transition_task_audit_trail_is_account_scoped(self, api):
        """PRD §2.3: "limit caps how many items are returned and defaults to 10
        when omitted".
        PRD §3.8: "the sequence number orders tasks within the plan".

        Design: Corner/endpoints/transition_task_audit_trail_reachable_from_account
        """
        account = create_activated_account_with_offboarding()
        create_transition_task(
            account, task_name="Vendor wind-down",
            task_type="VENDOR_TERMINATION", sequence_no=4, blocking=False,
            due_at="2026-12-31T00:00:00Z",
        )
        data, meta = validate_paginated(
            api.list_account_transition_tasks(account["id"], TRANS)
        )
        assert meta["total_count"] == 1
        assert data[0]["sequence_no"] == 4


def create_activated_account_with_offboarding():
    """Active account driven into OFFBOARDING (module-local helper)."""
    account = create_activated_account()
    return begin_offboarding(account)