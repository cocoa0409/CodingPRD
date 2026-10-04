"""Depth tests for repayment allocation modes and boundary conditions."""

import test_helpers as th
from test_helpers import fixtures


def _allocations_by_advance(api, advance_ids, deposit_id):
    result = {}
    for aid in advance_ids:
        allocs = fixtures.list_allocations_for_advance(api, aid)
        funded = [a for a in allocs if a["deposit_id"] == deposit_id]
        assert len(funded) == 1, f"expected exactly one allocation for {aid}: {funded}"
        result[aid] = funded[0]
    return result


def _setup_pro_rata_scenario(api):
    """Member with three open advances of 1666/1667/1667 (total 5000) under a
    5000-cent limit, followed by a 2500 OTHER deposit registration."""
    w = fixtures.setup_eligible_member(api, external_ref="m4", num_deposits=4)
    account_id = w["account"]["id"]
    member_id = w["member"]["id"]
    assert w["profile"]["computed_limit_cents"] == 2000

    # Seed cycle: borrow 2000, repay on time -> streak 1.
    seed_adv = fixtures.draw_advance(api, account_id, member_id, 2000, idempotency_key="m4-seed")
    fixtures.repay_with_qualifying_deposit(
        api, account_id, "EMP4", settlement_date="2026-09-01T00:00:00Z", trace_suffix="t5"
    )
    member = fixtures.get_member(api, member_id)
    assert member["consecutive_on_time_repayments"] == 1

    profile2 = fixtures.evaluate(api, member_id, mode="BATCH")
    assert profile2["computed_limit_cents"] == 5000, f"second limit: {profile2}"

    adv1 = fixtures.draw_advance(api, account_id, member_id, 1666, idempotency_key="m4-a1")
    adv2 = fixtures.draw_advance(api, account_id, member_id, 1667, idempotency_key="m4-a2")
    adv3 = fixtures.draw_advance(api, account_id, member_id, 1667, idempotency_key="m4-a3")

    other = fixtures.register_deposit(
        api,
        account_id,
        originator_id="VENMO",
        originator_type="OTHER",
        amount_cents=2500,
        settlement_date="2026-09-01T00:00:00Z",
        trace_id="m4-other1",
    )
    return w, [adv1, adv2, adv3], seed_adv, other


def test_pro_rata_per_line_rounding_amounts(api):
    """PRD §3.6: "When the deposit is not qualifying, repayment is proportional:
    the pool is the lesser of the deposit amount and the total outstanding across
    open advances; each advance's share is the pool multiplied by its fraction of
    the total outstanding, rounded half-up per line; the rounding remainder — the
    pool minus the sum of the rounded shares — is added onto the oldest advance;
    and shares of zero produce no allocation row, recorded with `allocation_mode`
    `PRO_RATA`."

    Design: Difficulty/combinatorial_formula/pro_rata_rounding_remainder_to_oldest
    """
    _w, advances, _seed, other = _setup_pro_rata_scenario(api)
    fixtures.settle_deposit(api, other["id"])

    by_advance = _allocations_by_advance(api, [a["id"] for a in advances], other["id"])
    amounts = [by_advance[a["id"]]["amount_cents"] for a in advances]
    # round_half_up(2500*1666/5000)=833, round_half_up(2500*1667/5000)=834 twice;
    # the -1 cent remainder reconciles onto the oldest advance.
    assert amounts == [832, 834, 834], f"allocations: {amounts}"
    for alloc in by_advance.values():
        th.assert_repayment_allocation(alloc)
        assert alloc["allocation_mode"] == "PRO_RATA"


def test_pro_rata_pool_conservation_and_partial_states(api):
    """PRD §3.6: "The rounding order is pinned: each line is rounded first, then
    the remainder reconciles against the oldest advance — never sum-then-round."
    PRD §3.6: "An allocation smaller than the outstanding moves the advance
    `OPEN → PARTIALLY_REPAID`; further partial allocations keep it
    `PARTIALLY_REPAID`."

    Design: Difficulty/combinatorial_formula/pro_rata_rounding_remainder_to_oldest
    """
    w, advances, _seed, other = _setup_pro_rata_scenario(api)
    fixtures.settle_deposit(api, other["id"])

    allocs = fixtures.list_allocations_for_deposit(api, other["id"])
    assert len(allocs) == 3
    assert sum(a["amount_cents"] for a in allocs) == 2500

    outstanding = []
    for adv in advances:
        current = th.get_success_data(api.get_advance(adv["id"], th.TEST_USERS["program_ops"]))
        assert current["status"] == "PARTIALLY_REPAID"
        outstanding.append(current["outstanding_cents"])
    assert outstanding == [834, 833, 833]

    account = fixtures.get_account(api, w["account"]["id"])
    assert account["outstanding_cushion_cents"] == 2500


def _setup_two_advances_exact_repay(api):
    """Member with a 2000 limit and two open advances of 1200 and 800, then a
    registered qualifying deposit of exactly 12000 (at the 10000 qualifying
    minimum, so the waterfall path runs and covers the 2000 outstanding with
    10000 left spendable)."""
    w = fixtures.setup_eligible_member(api, external_ref="m13", num_deposits=2)
    account_id = w["account"]["id"]
    member_id = w["member"]["id"]
    adv1 = fixtures.draw_advance(api, account_id, member_id, 1200, idempotency_key="m13-a1")
    adv2 = fixtures.draw_advance(api, account_id, member_id, 800, idempotency_key="m13-a2")
    dep = fixtures.register_deposit(
        api,
        account_id,
        originator_id="EMP13",
        originator_type="PAYROLL",
        amount_cents=12000,
        settlement_date="2026-09-01T00:00:00Z",
        trace_id="m13-t3",
    )
    return w, adv1, adv2, dep


def test_waterfall_exact_coverage_repays_both_advances(api):
    """PRD §3.6: "When the deposit is qualifying, the waterfall walks the
    account's `OPEN` and `PARTIALLY_REPAID` advances oldest first by
    `created_at`, allocating to each the lesser of its `outstanding_cents` and
    the remaining deposit funds, recording each allocation as a
    `RepaymentAllocation` with `allocation_mode` `WATERFALL` — every allocation
    row carries the `advance_id` it repays and the `deposit_id` that funded it —
    until the deposit is exhausted."
    PRD §3.6: "An allocation that exactly covers the outstanding moves the
    advance to `REPAID`, zeroes `outstanding_cents`, and stamps `repaid_at`."

    Design: Difficulty/boundary_precision_check/waterfall_exact_zero_outstanding_boundary
    """
    _w, adv1, adv2, dep = _setup_two_advances_exact_repay(api)
    fixtures.settle_deposit(api, dep["id"])

    for adv in (adv1, adv2):
        current = th.get_success_data(api.get_advance(adv["id"], th.TEST_USERS["program_ops"]))
        assert current["status"] == "REPAID"
        assert current["outstanding_cents"] == 0
        assert current["repaid_at"] is not None


def test_waterfall_exact_coverage_leaves_no_zero_allocation(api):
    """PRD §3.6: "The `outstanding_cushion_cents` is the sum of
    `outstanding_cents` over the account's advances in `OPEN` or
    `PARTIALLY_REPAID` status."
    PRD §3.6: "Repayment timeliness is judged at that instant: an advance repaid
    within 35 days of its creation is on time (`on_time` true), which increments
    the member's `consecutive_on_time_repayments`; a repayment later than 35
    days resets that counter to zero."

    Design: Difficulty/boundary_precision_check/waterfall_exact_zero_outstanding_boundary
    """
    w, _adv1, _adv2, dep = _setup_two_advances_exact_repay(api)
    fixtures.settle_deposit(api, dep["id"])

    allocs = fixtures.list_allocations_for_deposit(api, dep["id"])
    assert len(allocs) == 2
    assert sum(a["amount_cents"] for a in allocs) == 2000
    for alloc in allocs:
        assert alloc["allocation_mode"] == "WATERFALL"
        assert alloc["amount_cents"] > 0

    account = fixtures.get_account(api, w["account"]["id"])
    assert account["outstanding_cushion_cents"] == 0

    member = fixtures.get_member(api, w["member"]["id"])
    assert member["consecutive_on_time_repayments"] == 2
