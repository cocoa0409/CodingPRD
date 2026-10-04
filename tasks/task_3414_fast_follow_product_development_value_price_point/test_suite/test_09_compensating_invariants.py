"""Compensating invariants: launch-inventory conservation across sampling
COMMIT/DISTRIBUTE/RELEASE, and shelf-facing conservation across a
commit / shrink-evict / restore / re-commit cycle.
"""

from test_helpers import (
    TEST_USERS,
    advance_line_review_to_decided,
    assert_footprint_conservation,
    assert_launch_inventory_conserved,
    assert_sample_cap_respected,
    commit_slot,
    create_line_review,
    create_partner,
    create_slot,
    open_line_review,
    read_launch_plan,
    read_partner,
    read_planogram_slot,
    record_sample_event,
    set_clock,
    setup_executed_plan_with_sampling,
    setup_launch_ready_product,
    update_partner_capacities,
)

_PLANNER = TEST_USERS["retail_planner_headers"]


def test_commit_distribute_release_conserve_launch_inventory(api):
    """PRD §3.8: "Launch inventory is conserved at all times after the
    quantity lock: `qty_locked_units` always equals `retail_units_available`
    plus `samples_committed` plus `samples_distributed` plus
    `markdown_units`."
    Locked at 800 (landed 237): COMMIT 50 -> committed 50 / retail 750;
    DISTRIBUTE 20 -> committed 30 / distributed 20 / spend 4740 (20 * 237);
    RELEASE 30 -> committed 0 / retail 780. 750+50 == 750+30+20 ==
    780+0+20 == 800.

    Design: Difficulty/compensating_invariant/sample_commit_release_conserves_launch_inventory
    """
    ctx = setup_executed_plan_with_sampling()
    plan_id = ctx["plan"]["id"]

    after_commit = record_sample_event(plan_id, "COMMIT", 50, channel="CREATOR")
    assert after_commit["samples_committed"] == 50
    assert after_commit["retail_units_available"] == 750
    assert_launch_inventory_conserved(after_commit)

    after_distribute = record_sample_event(plan_id, "DISTRIBUTE", 20, channel="CREATOR")
    assert after_distribute["samples_committed"] == 30
    assert after_distribute["samples_distributed"] == 20
    assert after_distribute["sample_spend_cents"] == 4740
    assert after_distribute["retail_units_available"] == 750
    assert_launch_inventory_conserved(after_distribute)

    after_release = record_sample_event(plan_id, "RELEASE", 30)
    assert after_release["samples_committed"] == 0
    assert after_release["samples_distributed"] == 20
    assert after_release["retail_units_available"] == 780
    assert_launch_inventory_conserved(after_release)
    assert read_launch_plan(plan_id)["qty_locked_units"] == 800


def test_commit_then_release_of_same_size_leaves_every_bucket_unchanged(api):
    """PRD §3.8: "A `RELEASE` event is the compensating action: its count must
    not exceed `samples_committed`, and it returns the units to retail
    availability by decrementing `samples_committed`; a commit followed by a
    release of the same size leaves every bucket unchanged."
    COMMIT 50 then RELEASE 50: committed 0, distributed 0, spend 0, retail
    back to the locked 800 — the compensating pair leaves zero drift.

    Design: Difficulty/compensating_invariant/sample_commit_release_conserves_launch_inventory
    """
    ctx = setup_executed_plan_with_sampling()
    plan_id = ctx["plan"]["id"]

    record_sample_event(plan_id, "COMMIT", 50, channel="CREATOR")
    settled = record_sample_event(plan_id, "RELEASE", 50)

    assert settled["samples_committed"] == 0
    assert settled["samples_distributed"] == 0
    assert settled["sample_spend_cents"] == 0
    assert settled["retail_units_available"] == 800
    assert_launch_inventory_conserved(settled)
    assert_sample_cap_respected(settled)


def _setup_three_slots_decided():
    ctx = setup_launch_ready_product()
    ctx["partner"] = create_partner()
    ctx["line_review"] = create_line_review(ctx["partner"]["id"])
    ctx["line_review"] = open_line_review(ctx["line_review"]["id"])
    ctx["slot_a"] = create_slot(
        ctx["line_review"]["id"], ctx["product"]["id"],
        position_code="EYES-A1", facings=6,
    )
    ctx["slot_b"] = create_slot(
        ctx["line_review"]["id"], ctx["product"]["id"],
        position_code="EYES-A2", facings=4,
    )
    ctx["slot_d"] = create_slot(
        ctx["line_review"]["id"], ctx["product"]["id"],
        position_code="EYES-A3", facings=4,
    )
    ctx["line_review"] = advance_line_review_to_decided(ctx["line_review"]["id"])
    # A committed at the decision instant; B one day later (newer key).
    ctx["slot_a"] = commit_slot(ctx["slot_a"]["id"])
    set_clock("2026-10-22T00:00:00Z")
    ctx["slot_b"] = commit_slot(ctx["slot_b"]["id"])
    return ctx


def test_capacity_shrink_evicts_most_recently_committed_slot(api):
    """PRD §3.7: "when a revision reduces a category below its currently
    committed facings, the platform evicts to fit: it walks that category's
    `COMMITTED` slots — never `ACTIVE` ones — from most recently committed to
    least, ordered by `committed_at` descending with `created_at` descending
    as the tie-break, moving each evicted slot to `RELEASED` and reverting its
    quantity-locked or approved launch plan to `DRAFT`, until committed
    facings fit the new capacity."
    Committed 10 of 10 (A at 10-21, B at 10-22); shrinking EYES to 6 evicts
    the newest, B, and leaves A standing.

    Design: Difficulty/compensating_invariant/commit_vacate_cycle_conserves_shelf_facings
    """
    ctx = _setup_three_slots_decided()
    before = read_partner(ctx["partner"]["id"])
    assert before["committed_facings"]["EYES"] == 10
    assert before["available_facings"]["EYES"] == 0

    update_partner_capacities(ctx["partner"]["id"], {"EYES": 6})

    assert read_planogram_slot(ctx["slot_b"]["id"])["status"] == "RELEASED"
    assert read_planogram_slot(ctx["slot_a"]["id"])["status"] == "COMMITTED"
    after = read_partner(ctx["partner"]["id"])
    assert after["committed_facings"]["EYES"] == 6
    assert after["available_facings"]["EYES"] == 0
    assert_footprint_conservation(after)


def test_shrink_restore_recommit_cycle_conserves_facings(api):
    """PRD §2.9: "Footprint conservation is an invariant: for every category,
    committed plus available always equals the configured capacity, so
    committing a slot and vacating or releasing one are compensating actions
    that leave the sum unchanged."
    10/0 -> shrink to 6 (evict B) -> 6/0 -> restore to 10 -> 6/4 -> commit D
    -> 10/0: the evict/recommit pair compensates with no drift.

    Design: Difficulty/compensating_invariant/commit_vacate_cycle_conserves_shelf_facings
    """
    ctx = _setup_three_slots_decided()
    update_partner_capacities(ctx["partner"]["id"], {"EYES": 6})

    restored = update_partner_capacities(ctx["partner"]["id"], {"EYES": 10})
    assert restored["committed_facings"]["EYES"] == 6
    assert restored["available_facings"]["EYES"] == 4
    assert_footprint_conservation(restored)

    committed = commit_slot(ctx["slot_d"]["id"])
    assert committed["status"] == "COMMITTED"

    final = read_partner(ctx["partner"]["id"])
    assert final["committed_facings"]["EYES"] == 10
    assert final["available_facings"]["EYES"] == 0
    assert_footprint_conservation(final)
    assert read_planogram_slot(ctx["slot_b"]["id"])["status"] == "RELEASED"
