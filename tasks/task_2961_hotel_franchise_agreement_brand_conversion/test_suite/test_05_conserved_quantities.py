"""Quantities that must balance after a restatement or a rejection."""

from test_helpers import (
    BSD_HEADERS,
    assert_fee_ledger_consistent,
    assert_integer,
    assert_money,
    assert_plan_counter_partition,
    fixtures,
    get_success_data,
)


# ─── A revenue correction conserves the fee ledger (PRD §3.8) ─────────

def _corrected_ledger_world(api):
    """Two reported months, then November restated downward to 250,000.00."""
    world = fixtures.setup_agreement_with_two_revenue_periods(api)
    fixtures.set_clock(api, "2027-02-10T00:00:00Z")
    world["agreement"] = fixtures.report_revenue(
        api, world["agreement_id"], world["owner_id"], "2026-11", 250_000.00, correction=True
    )
    return world


def test_revenue_correction_appends_a_row_and_supersedes_the_one_it_replaces(api):
    """PRD §3.8: the ledger is append-only, so a correction never edits
    history - it appends a third entry for the same month and flips the
    previously surviving November entry's superseded flag, leaving the audit
    trail intact while reported_period_count stays at two because one entry was
    added and one was superseded.

    Design: Difficulty/compensating_invariant/revenue_correction_conserves_the_fee_ledger
    """
    world = _corrected_ledger_world(api)
    agreement = world["agreement"]
    periods = agreement["revenue_periods"]

    assert len(periods) == 3, f"a correction appends rather than replaces, got {len(periods)}"
    assert periods[0]["period_month"] == "2026-11"
    assert periods[0]["superseded"] is True
    assert_money(periods[0]["gross_room_revenue"], 320_000.16, "revenue_periods[0].gross_room_revenue")
    assert periods[1]["superseded"] is False
    assert periods[2]["period_month"] == "2026-11"
    assert periods[2]["superseded"] is False
    assert_integer(agreement["reported_period_count"], 2, "reported_period_count")

    assert_money(periods[2]["royalty_fee"], 13_375.00, "corrected royalty_fee")
    assert_money(periods[2]["marketing_fee"], 6_250.00, "corrected marketing_fee")
    assert_money(periods[2]["reservation_fee"], 4_375.00, "corrected reservation_fee")
    assert_money(periods[2]["period_total_fee"], 24_000.00, "corrected period_total_fee")

    assert_money(periods[1]["royalty_fee"], 26_600.01, "december royalty_fee")
    assert_money(periods[1]["marketing_fee"], 12_000.00, "december marketing_fee")
    assert_money(periods[1]["reservation_fee"], 8_400.00, "december reservation_fee")
    assert_money(periods[1]["period_total_fee"], 47_000.01, "december period_total_fee")


def test_every_ledger_total_equals_the_sum_of_the_surviving_periods_only(api):
    """PRD §3.8: all four running totals are recomputed from the surviving
    entries alone as exact sums of already-rounded per-period amounts, so the
    superseded November row is excluded from every one of them; the ledger
    balances at 24000.00 plus 47000.01, and total_fees_assessed equals the sum
    of the other three totals.

    Design: Difficulty/compensating_invariant/revenue_correction_conserves_the_fee_ledger
    """
    world = _corrected_ledger_world(api)
    agreement = world["agreement"]

    assert_money(agreement["royalty_fee_to_date"], 39_975.01, "royalty_fee_to_date")
    assert_money(
        agreement["marketing_fund_contributed_total"], 18_250.00, "marketing_fund_contributed_total"
    )
    assert_money(agreement["reservation_fee_to_date"], 12_775.00, "reservation_fee_to_date")
    assert_money(agreement["total_fees_assessed"], 71_000.01, "total_fees_assessed")
    assert_money(
        agreement["total_fees_assessed"], 24_000.00 + 47_000.01, "surviving period totals"
    )
    assert_fee_ledger_consistent(agreement)
    assert agreement["status"] == "OPEN"
    assert agreement["compliance_status"] == "COMPLIANT"


# ─── A rejection restores the plan's counter partition (PRD §3.7) ──────

def test_completing_a_scope_line_moves_it_between_two_buckets_of_the_partition(api):
    """PRD §3.7: a completion moves one line from PENDING to SUBMITTED, so the
    plan's four status buckets read 2 pending, 1 submitted, 0 verified and 0
    overdue - and they still partition the three scope lines exactly, summing
    to items_total_count.

    Design: Difficulty/compensating_invariant/pip_item_rejection_restores_the_plan_counter_partition
    """
    world = fixtures.setup_accepted_plan(api)
    fixtures.set_clock(api, "2026-10-20T00:00:00Z")
    fixtures.complete_item(
        api,
        world["items_by_category"]["GUESTROOM"]["id"],
        world["owner_id"],
        completion_evidence="Model room signed off, floors 3-14 installed",
    )

    plan = get_success_data(api.get_pip(world["plan_id"], BSD_HEADERS))
    assert_integer(plan["items_pending_count"], 2, "items_pending_count")
    assert_integer(plan["items_submitted_count"], 1, "items_submitted_count")
    assert_integer(plan["items_verified_count"], 0, "items_verified_count")
    assert_integer(plan["items_overdue_count"], 0, "items_overdue_count")
    assert_integer(plan["items_total_count"], 3, "items_total_count")
    assert_plan_counter_partition(plan)
    assert plan["status"] == "IN_PROGRESS"


def test_rejecting_the_completion_unwinds_both_counters_and_leaves_only_a_tally(api):
    """PRD §3.7: a REJECT is the exact inverse of the completion - the line
    returns to PENDING with verified_at still null and its deadline untouched,
    both plan counters unwind to the pre-completion partition of 3/0/0/0, and
    the only trace left is rejection_count.  The plan does not rewind to
    ACCEPTED and its estimated cost is unchanged.

    Design: Difficulty/compensating_invariant/pip_item_rejection_restores_the_plan_counter_partition
    """
    world = fixtures.setup_accepted_plan(api)
    fixtures.set_clock(api, "2026-10-20T00:00:00Z")
    item_id = world["items_by_category"]["GUESTROOM"]["id"]
    fixtures.complete_item(api, item_id, world["owner_id"])
    item = fixtures.verify_item(
        api, item_id, "REJECT",
        verification_notes="Case goods finish does not match the approved brand spec.",
    )

    assert item["status"] == "PENDING"
    assert_integer(item["rejection_count"], 1, "rejection_count")
    assert item["verified_at"] is None
    assert item["due_date"] == "2027-04-03T00:00:00.000Z", (
        f"a rejection must not move the deadline, got {item['due_date']}"
    )

    plan = get_success_data(api.get_pip(world["plan_id"], BSD_HEADERS))
    assert_integer(plan["items_pending_count"], 3, "items_pending_count")
    assert_integer(plan["items_submitted_count"], 0, "items_submitted_count")
    assert_integer(plan["items_verified_count"], 0, "items_verified_count")
    assert_integer(plan["items_overdue_count"], 0, "items_overdue_count")
    assert_integer(plan["items_total_count"], 3, "items_total_count")
    assert_plan_counter_partition(plan)
    assert plan["status"] == "IN_PROGRESS"
    assert_money(plan["total_estimated_cost"], 3_120_000.00, "total_estimated_cost")
