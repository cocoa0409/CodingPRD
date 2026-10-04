"""Difficulty queue: combinatorial formulas — tiered scrap weighting and the
pinned-order channel-split waterfall."""
import pytest

from test_helpers import (
    TEST_USERS,
    create_product,
    disposition_report,
    expected_channel_split,
    get_inventory_record_for_product,
    get_order,
    get_unit,
    inspect_unit_defect,
    rework_unit_via_defect,
    scrap_unit_via_defect,
    setup_shaken_units,
    validate_success,
)


def _ctx_with_plain_and_reworked_scrap():
    """25 poured units; u1 scrapped plain (1.0), u2 scrapped after one rework (1.5).

    Returns (ctx, u2_id). Mirrors the design recipe exactly.
    """
    ctx = setup_shaken_units(num_units=25, order_overrides={"planned_quantity": 30})
    u1, u2 = ctx["unit_ids"][0], ctx["unit_ids"][1]
    scrap_unit_via_defect(u1, defect_type="POROSITY", severity="MINOR")
    rework_unit_via_defect(u2, defect_type="SAND_INCLUSION", severity="MAJOR")
    _, report_id = inspect_unit_defect(u2, defect_type="CRACK", severity="MAJOR")
    disposition_report(report_id, "SCRAP")
    return ctx, u2


def test_scrap_weights_plain_vs_after_rework(api):
    """PRD §3.5: "The order's `scrapped_units` and `defect_scrapped_units` each
    increment by 1, and the order's `scrap_weighted_units` accumulates 1.5 for a
    unit scrapped after rework but 1.0 for a unit never reworked."
    PRD §3.5: "its `scrapped_after_rework` flag records whether `rework_count` was
    at least 1 at scrap time."

    Design: Difficulty/combinatorial_formula/scrap_index_tiered_weighting_restricts_order
    """
    ctx, u2 = _ctx_with_plain_and_reworked_scrap()
    unit = get_unit(u2)
    assert unit["state"] == "SCRAPPED"
    assert unit["scrapped_after_rework"] is True
    assert unit["scrap_reason"] == "DEFECT"
    order = get_order(ctx["order"]["id"])
    assert order["poured_units"] == 25
    assert order["defect_scrapped_units"] == 2
    assert order["scrap_weighted_units"] == pytest.approx(2.5, abs=1e-9)


def test_tiered_scrap_index_flips_posture_to_restricted(api):
    """PRD §2.8: "The `scrap_tier` summarizes defect-driven scrap: it is `GREEN`
    while the order's `scrap_index` is below 0.04, `WATCH` once `scrap_index` is at
    least 0.04 and still below 0.08, and `RED` once `scrap_index` reaches 0.08."
    PRD §2.8: "otherwise it is `RESTRICTED` when the order's `scrap_tier` is `RED`
    (equivalently, when `scrap_index` is at least 0.08); otherwise it is `OPEN`."
    2.5 weighted over 25 poured -> scrap_index 0.1000 -> RED -> RESTRICTED; treating
    the reworked unit as 1.0 would give 0.0800 — the conditional weight decides the
    tier.

    Design: Difficulty/combinatorial_formula/scrap_index_tiered_weighting_restricts_order
    """
    ctx, _ = _ctx_with_plain_and_reworked_scrap()
    order = get_order(ctx["order"]["id"])
    assert order["scrap_index"] == pytest.approx(0.10, abs=1e-9), (
        f"scrap_index {order['scrap_index']} != 0.1000 (2.5 / 25)")
    assert order["scrap_tier"] == "RED"
    assert order["posture"] == "RESTRICTED"


def test_channel_split_pinned_per_line_rounding(api):
    """PRD §3.8: "The split is a waterfall evaluated in exactly this pinned order,
    each line rounded half-up to integer units and clamped by what remains: first
    the museum store receives the smaller of `build_qty` times 0.02 rounded half-up
    and the remaining pool; then the factory outlet receives the smaller of
    `build_qty` times 0.08 rounded half-up and what remains; then ecommerce receives
    the smaller of `build_qty` times 0.15 rounded half-up and what remains; and the
    retail chain absorbs whatever is left."
    build_qty 37 -> museum 1, outlet 3, ecommerce 6, retail chain 27 (round-half-up
    of 5.55 is 6; a truncating rule would give 5).

    Design: Difficulty/combinatorial_formula/channel_split_per_line_rounding_remainder
    """
    product = create_product()
    record = get_inventory_record_for_product(product["id"])
    resp = api.get_allocation_plan(record["id"], 37,
                                   TEST_USERS["retail_planner_headers"])
    plan = validate_success(resp)
    assert plan["museum_store_units"] == 1
    assert plan["factory_outlet_units"] == 3
    assert plan["ecommerce_units"] == 6
    assert plan["retail_chain_units"] == 27


def test_channel_split_conserves_build_qty(api):
    """PRD §3.8: "Computing a single rounding over the total, or reordering the
    channels, is forbidden."
    The four pinned lines partition the build exactly: 1 + 3 + 6 + 27 == 37, with
    the retail chain absorbing the remainder after the three rounded lines.

    Design: Difficulty/combinatorial_formula/channel_split_per_line_rounding_remainder
    """
    product = create_product()
    record = get_inventory_record_for_product(product["id"])
    resp = api.get_allocation_plan(record["id"], 37,
                                   TEST_USERS["retail_planner_headers"])
    plan = validate_success(resp)
    total = (plan["museum_store_units"] + plan["factory_outlet_units"]
             + plan["ecommerce_units"] + plan["retail_chain_units"])
    assert total == 37
    assert plan == expected_channel_split(37)
    assert plan["retail_chain_units"] == 37 - 1 - 3 - 6
