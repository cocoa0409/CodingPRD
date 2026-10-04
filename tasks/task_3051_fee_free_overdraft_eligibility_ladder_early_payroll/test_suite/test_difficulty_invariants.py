"""Depth tests for conserved quantities and ledger double-entry parity."""

import test_helpers as th
from test_helpers import fixtures


def _setup_borrowed_2000(api):
    """ELIGIBLE member (limit 2000) with one open 2000 advance and a registered
    qualifying deposit of 5000 awaiting settlement."""
    w = fixtures.setup_eligible_member(
        api,
        external_ref="m18",
        num_deposits=2,
        settlement_dates=["2026-08-14T00:00:00Z", "2026-08-21T00:00:00Z"],
    )
    account_id = w["account"]["id"]
    member_id = w["member"]["id"]
    account = fixtures.get_account(api, account_id)
    assert account["outstanding_cushion_cents"] == 0
    adv = fixtures.draw_advance(api, account_id, member_id, 2000, idempotency_key="m18-a1")
    dep = fixtures.register_deposit(
        api,
        account_id,
        originator_id="EMP18",
        originator_type="PAYROLL",
        amount_cents=5000,
        settlement_date="2026-09-01T00:00:00Z",
        trace_id="m18-t3",
    )
    return w, adv, dep


def test_cushion_outstanding_conserved_across_borrow_repay(api):
    """PRD §3.6: "The `outstanding_cushion_cents` is the sum of
    `outstanding_cents` over the account's advances in `OPEN` or
    `PARTIALLY_REPAID` status."
    PRD §3.6: "An allocation that exactly covers the outstanding moves the
    advance to `REPAID`, zeroes `outstanding_cents`, and stamps `repaid_at`."

    Design: Difficulty/compensating_invariant/cushion_outstanding_conserved_across_borrow_repay
    """
    w, adv, dep = _setup_borrowed_2000(api)
    fixtures.settle_deposit(api, dep["id"])

    account = fixtures.get_account(api, w["account"]["id"])
    assert account["outstanding_cushion_cents"] == 0

    current = th.get_success_data(api.get_advance(adv["id"], th.TEST_USERS["program_ops"]))
    assert current["status"] == "REPAID"
    assert current["on_time"] is True
    allocs = fixtures.list_allocations_for_advance(api, adv["id"])
    assert sum(a["amount_cents"] for a in allocs) == 2000 == current["principal_cents"]


def test_cushion_outstanding_rises_on_borrow_and_falls_on_repay(api):
    """PRD §3.6: "A successful draw creates an `OverdraftAdvance` with `origin`
    `MEMBER_INITIATED`, `principal_cents` equal to the amount, and status
    `OPEN`; the account's `outstanding_cushion_cents` rises by the amount, the
    `posted_balance_cents` is credited with the amount (cushion funds land as
    spendable money), and an `ADVANCE_CREDIT` ledger entry records the
    movement."
    PRD §3.6: "Each allocation reduces both the advance's `outstanding_cents`
    and the account's `outstanding_cushion_cents`."

    Design: Difficulty/compensating_invariant/cushion_outstanding_conserved_across_borrow_repay
    """
    w, adv, dep = _setup_borrowed_2000(api)
    mid = fixtures.get_account(api, w["account"]["id"])
    assert mid["outstanding_cushion_cents"] == 2000

    fixtures.settle_deposit(api, dep["id"])
    after = fixtures.get_account(api, w["account"]["id"])
    assert after["outstanding_cushion_cents"] == 0

    current = th.get_success_data(api.get_advance(adv["id"], th.TEST_USERS["program_ops"]))
    assert current["outstanding_cents"] == 0
    assert current["status"] == "REPAID"
