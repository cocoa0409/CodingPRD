"""Difficulty rule: combinatorial_formula — per-line rounding order changes
the total, and the tier evaluation keys off the PRE-discount basis (PRD
§2.6, §3.5)."""

from test_helpers import (
    acknowledge_chair_order,
    acknowledge_order,
    create_and_lock_configuration,
    create_order,
    make_module_entry,
    setup_dealer_world,
    submit_order,
)


def _two_line_trap_submitted(api):
    """Locked configuration with two WORKSTATION_6X6 grade B entries (qty 3
    and qty 1) on a base-42 SYSTEMS family; one order, submitted."""
    ctx = setup_dealer_world(
        api, family_specs=(("SYS-7500", "SYSTEMS", 42),)
    )
    spec = create_and_lock_configuration(
        api,
        ctx["dealer"]["id"],
        modules=[
            make_module_entry("WORKSTATION_6X6", "B", 3),
            make_module_entry("WORKSTATION_6X6", "B", 1),
        ],
    )
    order = create_order(
        api, ctx["agreement"]["id"], spec["id"], ctx["dealer"]["id"]
    )
    return submit_order(api, order, ctx["dealer"]["id"])


def test_per_line_rounding_then_sum_beats_sum_then_round(api):
    """PRD §2.6: "The pre-discount order total is the sum of already-rounded
    line totals; an implementation must never sum unrounded line amounts and
    round once at the end." WORKSTATION_6X6 grade B unit exact price is
    85837 x 1.05 = 90128.85: per-entry rounding gives round(270386.55) +
    round(90128.85) = 270387 + 90129 = 360516 — one cent more than the
    merged-quantity 360515.

    Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_beats_sum_then_round
    """
    submitted = _two_line_trap_submitted(api)
    assert submitted["pre_discount_total_cents"] == 360516
    assert submitted["pre_discount_total_cents"] != 360515, (
        "sum-then-round arithmetic would give 360515; per-line rounding "
        "must give 360516"
    )


def test_provisional_total_uses_rounded_lines(api):
    """PRD §2.6: "Order pricing applies rounding exactly twice: once per
    module line, where each line's exact extended amount is rounded to whole
    cents before any summation, and once on the discounted order total." The
    tier-1 provisional total of the two-line configuration is
    round_half_up(360516 x 0.90) = round_half_up(324464.4) = 324464.

    Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_beats_sum_then_round
    """
    submitted = _two_line_trap_submitted(api)
    assert submitted["provisional_tier"] == 1
    assert submitted["provisional_total_cents"] == 324464


def _second_chair_order(api):
    """Agreement preloaded to cumulative 12500000 by an acknowledged
    100-chair order; a second, still-DRAFT 100-chair order against it."""
    ctx = setup_dealer_world(api)
    acknowledge_chair_order(api, ctx, 100)
    spec = create_and_lock_configuration(
        api, ctx["dealer"]["id"],
        modules=[make_module_entry("TASK_CHAIR_SET", "A", 100)],
    )
    order = create_order(
        api, ctx["agreement"]["id"], spec["id"], ctx["dealer"]["id"]
    )
    return ctx, order


def test_provisional_tier_uses_prior_cumulative_only(api):
    """PRD §3.5: "the provisional tier basis is the agreement's
    `cumulative_volume_cents` as it stands before this order — excluding this
    order entirely". With cumulative 12500000 the second 100-chair order
    (pre-discount 12500000) provisions at tier 1: 12500000 x 0.90 = 11250000.

    Design: Difficulty/combinatorial_formula/tier_evaluation_order_pinned_off_prediscount_total
    """
    ctx, order = _second_chair_order(api)
    submitted = submit_order(api, order, ctx["dealer"]["id"])
    assert submitted["pre_discount_total_cents"] == 12500000
    assert submitted["provisional_tier"] == 1
    assert submitted["provisional_total_cents"] == 11250000


def test_final_tier_keys_off_prediscount_total(api):
    """PRD §3.5: "the final tier basis is the agreement's
    `cumulative_volume_cents` plus this order's `pre_discount_total_cents`"
    and the discount is "applied as a flat average-rate discount over the
    whole pre-discount total — not as a marginal per-tier rate." The basis
    lands exactly on the 25000000 boundary (inclusive lower edge), so tier 2
    applies to the whole order: 12500000 x 0.85 = 10625000.

    Design: Difficulty/combinatorial_formula/tier_evaluation_order_pinned_off_prediscount_total
    """
    ctx, order = _second_chair_order(api)
    submit_order(api, order, ctx["dealer"]["id"])
    acknowledged = acknowledge_order(api, order["id"])
    assert acknowledged["final_tier"] == 2
    assert acknowledged["final_total_cents"] == 10625000
