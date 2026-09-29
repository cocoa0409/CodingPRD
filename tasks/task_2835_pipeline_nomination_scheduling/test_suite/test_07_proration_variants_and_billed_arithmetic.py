"""Proration methodology variants and the arithmetic that bills a settled cycle.

The two proration methodologies award the same nominations differently, and the
two settlement bases bill the same delivered barrels differently. Both pairs are
exercised here against literal expected figures, because the PRD fixes every
threshold, every truncation and every rounding step.
"""

from test_helpers import (
    assert_capacity_conservation,
    assert_money_precision,
    assert_ratio_precision,
    change_proration_policy,
    close_cycle,
    deliver_ticket,
    inject_ticket,
    nomination_key,
    nominate,
    open_cycle,
    prorate_cycle,
    refresh_cycle,
    refresh_nomination,
    settle_cycle,
    setup_multi_shipper_cycle,
    ticket_at,
)

CANONICAL_ALPHA_HISTORY = [
    ("ALPHA", 30000, "2026-06-30T00:00:00Z"),
    ("ALPHA", 42000, "2026-07-31T00:00:00Z"),
]
CANONICAL_BRAVO_HISTORY = [
    ("BRAVO", 20000, "2026-06-30T00:00:00Z"),
    ("BRAVO", 16000, "2026-07-31T00:00:00Z"),
]


def _barrels(value) -> int:
    """Allocations and capacities are whole barrels."""
    return int(round(float(value)))


def _volume(value) -> float:
    """Measured and historical volumes are carried to two decimal places."""
    return round(float(value), 2)


def _money(value) -> float:
    """Monetary amounts are carried to two decimal places."""
    return round(float(value), 2)


def _ratio(value) -> float:
    """A cycle's proration factor is carried to six decimal places."""
    return round(float(value), 6)


def _two_shipper_history_weighted_cycle():
    """ALPHA 70000 bbl of ULSD against BRAVO 50000 bbl of CBOB, both HISTORICAL,
    on a HISTORY_WEIGHTED segment whose effective capacity is exactly 100000 bbl."""
    return setup_multi_shipper_cycle(
        [("ALPHA", "ULSD", 70000), ("BRAVO", "CBOB", 50000)],
        grades=("ULSD", "CBOB"),
        history=CANONICAL_ALPHA_HISTORY + CANONICAL_BRAVO_HISTORY,
        close=True,
    )


def _second_cycle_with_the_same_nominations(ctx):
    """Open an October cycle on the same segment carrying identical nominations,
    so the only thing that differs between the two runs is the filed methodology."""
    open_cycle(
        ctx,
        cycle_code="2026-10",
        ship_start_at="2026-10-01T00:00:00Z",
        ship_end_at="2026-10-31T00:00:00Z",
    )
    nominate(ctx, "ALPHA", "ULSD", nominated_bbl=70000, key="ALPHA:ULSD:october")
    nominate(ctx, "BRAVO", "CBOB", nominated_bbl=50000, key="BRAVO:CBOB:october")
    close_cycle(ctx)
    prorate_cycle(ctx)
    refresh_nomination(ctx, "ALPHA:ULSD:october")
    refresh_nomination(ctx, "BRAVO:CBOB:october")
    return ctx


def _two_grade_delivered_cycle(basis_mode="DELIVERED"):
    """ALPHA moves 30000 bbl of ULSD and 26100 bbl of CBOB in one cycle, both
    batches injected in full and both delivered 99 bbl short, then settled."""
    ctx = setup_multi_shipper_cycle(
        [("ALPHA", "ULSD", 30000), ("ALPHA", "CBOB", 26100)],
        grades=("ULSD", "CBOB"),
        history=CANONICAL_ALPHA_HISTORY,
        origin_stock_bbl=100000,
        publish=True,
    )
    diesel_batch = ticket_at(ctx, 1)
    gasoline_batch = ticket_at(ctx, 2)
    inject_ticket(ctx, diesel_batch["id"], 30000, measured_sulfur_ppm=9, measured_rvp_psi=10)
    deliver_ticket(ctx, diesel_batch["id"], 29901)
    inject_ticket(
        ctx, gasoline_batch["id"], 26100, measured_sulfur_ppm=60, measured_rvp_psi=13
    )
    deliver_ticket(ctx, gasoline_batch["id"], 26001)
    settle_cycle(ctx, basis_mode)
    return ctx


def test_history_weighted_proration_caps_each_weight_at_the_shipping_history_base(api):
    """ALPHA nominates 70000 bbl with a 36000 bbl history base and BRAVO nominates
    50000 bbl with an 18000 bbl base; because the weights are capped at the base,
    the 90000 bbl historical pool splits 60000 / 30000 and the unused new-shipper
    reserve then lifts BRAVO to 40000 bbl.

    PRD 3.5: "For each nomination classed `HISTORICAL`, its weight is the smaller
    of its `nominated_bbl` and its `history_base_bbl`, and the total weight is the
    sum of those weights across the historical nominations."

    PRD 3.5: "When there are no new-shipper nominations at all, the entire reserve
    becomes new-shipper leftover and spills over into redistribution rather than
    being wasted."

    Design: Difficulty/dual_variant_calc/proration_policy_history_vs_volume_divergence
    """
    ctx = _two_shipper_history_weighted_cycle()
    assert _barrels(ctx["cycle"]["effective_capacity_bbl"]) == 100000

    prorate_cycle(ctx)
    alpha = refresh_nomination(ctx, nomination_key("ALPHA", "ULSD"))
    bravo = refresh_nomination(ctx, nomination_key("BRAVO", "CBOB"))
    cycle = refresh_cycle(ctx)

    assert _volume(alpha["history_base_bbl"]) == 36000.00
    assert alpha["allocation_class"] == "HISTORICAL"
    assert _volume(bravo["history_base_bbl"]) == 18000.00
    assert bravo["allocation_class"] == "HISTORICAL"

    assert _barrels(alpha["allocated_bbl"]) == 60000
    assert _barrels(bravo["allocated_bbl"]) == 40000
    assert _barrels(cycle["allocated_total_bbl"]) == 100000
    assert _barrels(cycle["unallocated_capacity_bbl"]) == 0
    assert_capacity_conservation(cycle)
    assert _ratio(cycle["proration_factor"]) == 0.833333
    assert_ratio_precision(cycle["proration_factor"], "proration_factor")


def test_volume_weighted_proration_shares_the_line_by_nominated_volume_alone(api):
    """Refiling the methodology as VOLUME_WEIGHTED and running the identical pair
    of nominations again awards ALPHA 58334 bbl rather than 60000 bbl — a 1666 bbl
    divergence on the same data — while both runs report a proration factor of
    0.833333, and the already-prorated September cycle is left untouched.

    PRD 3.5: "The total nominated volume is the sum of `nominated_bbl` across the
    input set, each nomination's allocation is the smaller of its `nominated_bbl`
    and `effective_capacity_bbl` multiplied by that nomination's `nominated_bbl`
    divided by the total nominated volume and truncated downward to a whole barrel,
    and the leftover carried into redistribution is `effective_capacity_bbl` less
    the sum of those allocations."

    PRD 3.1: "A `TariffAdministrator` may replace a segment's `proration_policy` at
    any time; the new value governs every subsequent proration run and never
    rewrites the allocations of a cycle that has already been prorated."

    Design: Difficulty/dual_variant_calc/proration_policy_history_vs_volume_divergence
    """
    ctx = _two_shipper_history_weighted_cycle()
    prorate_cycle(ctx)
    september = refresh_cycle(ctx)
    september_alpha = refresh_nomination(ctx, nomination_key("ALPHA", "ULSD"))
    assert _barrels(september_alpha["allocated_bbl"]) == 60000

    change_proration_policy(ctx, "VOLUME_WEIGHTED")
    _second_cycle_with_the_same_nominations(ctx)

    october_alpha = ctx["nominations"]["ALPHA:ULSD:october"]
    october_bravo = ctx["nominations"]["BRAVO:CBOB:october"]
    october = refresh_cycle(ctx)

    assert _barrels(october["effective_capacity_bbl"]) == 100000
    assert _barrels(october_alpha["allocated_bbl"]) == 58334
    assert _barrels(october_bravo["allocated_bbl"]) == 41666
    assert _barrels(october["allocated_total_bbl"]) == 100000
    assert _barrels(october["unallocated_capacity_bbl"]) == 0
    assert_capacity_conservation(october)
    assert _ratio(october["proration_factor"]) == 0.833333

    assert (
        _barrels(september_alpha["allocated_bbl"])
        - _barrels(october_alpha["allocated_bbl"])
        == 1666
    )

    frozen_september_alpha = refresh_nomination(ctx, nomination_key("ALPHA", "ULSD"))
    assert _barrels(frozen_september_alpha["allocated_bbl"]) == 60000
    assert _barrels(
        refresh_nomination(ctx, nomination_key("BRAVO", "CBOB"))["allocated_bbl"]
    ) == 40000
    assert _barrels(september["allocated_total_bbl"]) == 100000


def test_a_delivered_basis_settlement_records_the_ship_or_pay_counterfactual(api):
    """ALPHA moves 30000 bbl of ULSD and 26100 bbl of CBOB and delivers 99 bbl short
    on each; the DELIVERED basis bills the 55902 bbl that arrived for 95312.92 USD
    while the ship-or-pay counterfactual on the 56100 bbl scheduled is 95650.50 USD,
    a divergence of 337.58 USD recorded on the settlement itself.

    PRD 3.9: "For a given ticket, the billable volume under the `DELIVERED` basis is
    the larger of the ticket's `delivered_bbl` — treated as zero when it is null —
    and the pinned tariff's `tender_minimum_bbl`; under the `SCHEDULED` basis it is
    the larger of the ticket's `volume_bbl` and that same `tender_minimum_bbl`."

    PRD 3.9: "The charge on the `basis_mode` the scheduler chose is written to
    `tariff_charge_usd`; the charge on the other basis is written to
    `alt_basis_charge_usd` as an explicit counterfactual; and `basis_delta_usd` is
    `alt_basis_charge_usd` less `tariff_charge_usd`, rounded half up to two decimal
    places."

    Design: Difficulty/dual_variant_calc/settlement_basis_scheduled_vs_delivered_divergence
    """
    ctx = _two_grade_delivered_cycle("DELIVERED")
    settlements = ctx["settlements"]
    assert len(settlements) == 1, "one settlement row per billed shipper"
    settlement = settlements[0]

    assert settlement["basis_mode"] == "DELIVERED"
    assert _volume(settlement["scheduled_bbl"]) == 56100.00
    assert _volume(settlement["delivered_bbl"]) == 55902.00
    assert _money(settlement["tariff_charge_usd"]) == 95312.92
    assert _money(settlement["alt_basis_charge_usd"]) == 95650.50
    assert _money(settlement["basis_delta_usd"]) == 337.58
    for field in ("tariff_charge_usd", "alt_basis_charge_usd", "basis_delta_usd"):
        assert_money_precision(settlement[field], field)


def test_a_settled_cycle_allocates_the_system_loss_and_zeroes_a_tolerance_penalty(api):
    """The 198 bbl of system loss lands wholly on the only billed shipper, which
    drives its imbalance to exactly 0.00 bbl, places it in the TOLERANCE tier whose
    multiplier is zero, and leaves the total billed equal to transportation alone.

    PRD 3.9: "Step four: `imbalance_bbl` is the `delivered_bbl` less the
    `scheduled_bbl` plus the `loss_allocation_bbl`, rounded half up to two decimal
    places — note that it may legitimately be negative."

    PRD 3.9: "A shipper inside tolerance therefore pays transportation only, because
    its multiplier zeroes the penalty term outright."

    Design: Difficulty/dual_variant_calc/settlement_basis_scheduled_vs_delivered_divergence
    """
    ctx = _two_grade_delivered_cycle("DELIVERED")
    settlement = ctx["settlements"][0]

    assert _volume(settlement["loss_allocation_bbl"]) == 198.00
    assert _volume(settlement["imbalance_bbl"]) == 0.00
    assert settlement["imbalance_tier"] == "TOLERANCE"
    assert _money(settlement["imbalance_charge_usd"]) == 0.00
    assert _money(settlement["total_billed_usd"]) == 95312.92
    assert settlement["status"] == "DRAFT"
    assert refresh_cycle(ctx)["status"] == "SETTLED"


def _three_shipper_waterfall_cycle():
    """ALPHA 50000 ULSD, BRAVO 40000 CBOB and CHARLIE 20000 ULSD against 100000 bbl,
    created in that order so the waterfall's tie is broken by creation order.

    ALPHA carries two FINAL rows plus one PROVISIONAL row that must not qualify;
    BRAVO carries two FINAL rows; CHARLIE carries exactly one.
    """
    return setup_multi_shipper_cycle(
        [("ALPHA", "ULSD", 50000), ("BRAVO", "CBOB", 40000), ("CHARLIE", "ULSD", 20000)],
        grades=("ULSD", "CBOB"),
        history=[
            ("ALPHA", 30000, "2026-06-30T00:00:00Z"),
            ("ALPHA", 42000, "2026-07-31T00:00:00Z"),
            ("ALPHA", 90000, "2026-07-15T00:00:00Z", "PROVISIONAL"),
            ("BRAVO", 20000, "2026-06-30T00:00:00Z"),
            ("BRAVO", 16000, "2026-07-31T00:00:00Z"),
            ("CHARLIE", 12000, "2026-07-31T00:00:00Z"),
        ],
        prorate=True,
    )


def test_a_provisional_history_row_never_qualifies_and_one_row_is_not_a_history(api):
    """ALPHA's 90000 bbl PROVISIONAL row is ignored, so its base is the mean of the
    two FINAL rows and it is HISTORICAL; CHARLIE's single FINAL row still yields a
    12000 bbl base but leaves it NEW_SHIPPER, which caps it at the reserve pool.

    PRD 3.5: "A historical movement record qualifies for a nomination when its
    `shipper_id` matches the nomination's shipper, its `segment_id` matches the
    cycle's segment, its `record_status` is `FINAL`, and its `cycle_end_at` falls at
    or after the instant exactly 365 days — one full year — before the cycle's
    `window_open_at` and strictly before `window_open_at` itself."

    PRD 3.5: "The count of qualifying records also fixes `allocation_class`: a
    shipper with at least two qualifying records on the segment is `HISTORICAL`, and
    a shipper with fewer than two is `NEW_SHIPPER`."

    Design: Difficulty/combinatorial_formula/history_weighted_proration_nested_caps_pools_and_waterfall_tiebreak
    """
    ctx = _three_shipper_waterfall_cycle()
    alpha = ctx["nominations"][nomination_key("ALPHA", "ULSD")]
    charlie = ctx["nominations"][nomination_key("CHARLIE", "ULSD")]

    assert _volume(alpha["history_base_bbl"]) == 36000.00
    assert alpha["allocation_class"] == "HISTORICAL"
    assert _volume(charlie["history_base_bbl"]) == 12000.00
    assert charlie["allocation_class"] == "NEW_SHIPPER"

    assert _barrels(alpha["allocated_bbl"]) == 50000
    assert _barrels(charlie["allocated_bbl"]) == 10000


def test_the_single_redistribution_pass_breaks_a_tied_shortfall_by_creation_order(api):
    """BRAVO and CHARLIE both fall 10000 bbl short of their nominations after the
    pooled awards, and the one pass of redistribution separates them only on the
    nomination's creation order, so BRAVO reaches 40000 bbl and CHARLIE stops at
    10000 bbl with the whole 100000 bbl line consumed.

    PRD 3.5: "Every nomination whose allocation is still strictly below its
    `nominated_bbl` is eligible, and the eligible nominations are ordered by unmet
    demand — `nominated_bbl` less current allocation — descending, with ties broken
    by the nomination's `created_at` ascending."

    PRD 2.8: "A parallel identity governs allocation rather than volume: for every
    nomination cycle, `allocated_total_bbl` plus `unallocated_capacity_bbl` must
    equal `effective_capacity_bbl` exactly, in whole barrels, with zero drift."

    Design: Difficulty/combinatorial_formula/history_weighted_proration_nested_caps_pools_and_waterfall_tiebreak
    """
    ctx = _three_shipper_waterfall_cycle()
    bravo = ctx["nominations"][nomination_key("BRAVO", "CBOB")]
    charlie = ctx["nominations"][nomination_key("CHARLIE", "ULSD")]
    cycle = ctx["cycle"]

    assert _barrels(bravo["allocated_bbl"]) == 40000
    assert _barrels(charlie["allocated_bbl"]) == 10000

    assert _barrels(cycle["nominated_total_bbl"]) == 110000
    assert _barrels(cycle["allocated_total_bbl"]) == 100000
    assert _barrels(cycle["unallocated_capacity_bbl"]) == 0
    assert_capacity_conservation(cycle)
    assert _ratio(cycle["proration_factor"]) == 0.909091
    assert cycle["status"] == "PRORATED"


def test_rounding_each_ticket_line_before_summation_pins_the_transportation_charge(api):
    """Both billable volumes — 29901 bbl and 26001 bbl — sit above the 25000 bbl
    tier-one break and below the 45000 bbl tier-two break, so both price at
    1.705 USD; rounding 50981.205 and 44331.705 half up before adding them yields
    95312.92 USD, whereas summing the raw products and rounding once would yield
    95312.91 USD.

    PRD 2.9: "One rounding rule is load-bearing enough to state separately: where a
    charge is built from several batch lines, each line is rounded to two decimal
    places *first* and the rounded lines are then summed exactly."

    PRD 3.9: "The rate that applies to that billable volume is the pinned tariff's
    `tier2_rate_usd_per_bbl` when the billable volume is at or above `tier2_min_bbl`,
    otherwise its `tier1_rate_usd_per_bbl` when the billable volume is at or above
    `tier1_min_bbl`, and otherwise its `base_rate_usd_per_bbl`."

    Design: Difficulty/combinatorial_formula/per_ticket_rounding_before_summation_pins_tariff_charge
    """
    ctx = _two_grade_delivered_cycle("DELIVERED")
    settlement = ctx["settlements"][0]

    assert _money(settlement["tariff_charge_usd"]) == 95312.92
    assert _money(settlement["tariff_charge_usd"]) != 95312.91, (
        "summing the unrounded lines and rounding the total is the wrong order"
    )
    assert _money(settlement["total_billed_usd"]) == 95312.92
    assert_money_precision(settlement["total_billed_usd"], "total_billed_usd")


def test_the_first_batch_interfaces_against_the_linefill_and_the_second_downgrades(api):
    """The leading ULSD batch follows ULSD linefill, so its rank gap is zero and it
    cuts no slop; the CBOB batch behind it is one rank dirtier, so it cuts the
    segment's full 250 bbl at no flush — and those cuts do not disturb the billed
    volumes, which stay pinned at 95312.92 USD.

    PRD 3.6: "For the ticket at `sequence_position` 1 the upstream rank is the
    `sequence_rank` of the segment's linefill grade, named by the segment's
    `linefill_grade_id`; for every later ticket it is the `sequence_rank` of the
    grade on the predecessor ticket's nomination."

    PRD 3.6: "Where the ticket's own rank is *higher* than the upstream rank, meaning
    a dirtier product following a cleaner one, the cut is a **downgrade**:
    `transmix_bbl` is the segment's `transmix_cut_bbl` multiplied by the rank gap,
    and `requires_flush` stays false."

    Design: Difficulty/combinatorial_formula/per_ticket_rounding_before_summation_pins_tariff_charge
    """
    ctx = _two_grade_delivered_cycle("DELIVERED")
    diesel_batch = ticket_at(ctx, 1)
    gasoline_batch = ticket_at(ctx, 2)

    assert _barrels(diesel_batch["transmix_bbl"]) == 0
    assert diesel_batch["requires_flush"] is False
    assert _barrels(gasoline_batch["transmix_bbl"]) == 250
    assert gasoline_batch["requires_flush"] is False

    assert _money(ctx["settlements"][0]["tariff_charge_usd"]) == 95312.92
