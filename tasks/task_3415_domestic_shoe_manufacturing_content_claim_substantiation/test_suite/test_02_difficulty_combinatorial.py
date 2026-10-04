"""Depth probes: combinatorial formulas (run unit-cost surcharge tiers; custom
order price evaluation order)."""
import pytest

from test_helpers import (
    WEEK_36, accept_order, bom_line, certify_pair, complete_run, create_report,
    get_order, lock_allocation, make_allocation, make_component, make_factory,
    make_lot, make_model, make_order, make_run, reserve_run, set_clock,
    start_run, validate_success,
)
from test_helpers import TEST_USERS

PLANNER = TEST_USERS["planner"]
SOURCING = TEST_USERS["sourcing"]


def _three_run_tier_kit():
    """Cleared DOMESTIC factory (3 lines, rate 50, overhead 600); M550 with one
    IMPORT_ALLOWED 1.0 outsole line (lot @3000); CUSTOM_BATCH / STOCK /
    GOVERNMENT runs of 8 units, all COMPLETED at 20/0/0 actual minutes.
    Per-pair base for each run: 3000 + 20*50 + 600 = 4600."""
    set_clock()
    factory = make_factory(factory_name="Norridgewock ME Plant",
                           government_cleared=True, line_count=3)
    c_out = make_component("Rubber outsole", "OUTSOLE")
    make_lot(c_out["id"], supplier_name="Akron Rubber", quantity_received=1000,
             unit_cost_cents=3000, is_domestic=True)
    model = make_model(bom_lines=[
        bom_line(c_out["id"], planned_unit_cost_cents=3000, planned_is_domestic=False),
    ], style_code="M550", base_price_cents=9900, import_cost_basis_cents=3000)
    allocation = make_allocation(factory["id"], WEEK_36, 100)
    runs = {}
    for run_type, line in (("CUSTOM_BATCH", 1), ("STOCK", 2), ("GOVERNMENT", 3)):
        runs[run_type] = make_run(model["id"], factory["id"], run_type=run_type,
                                  planned_units=8, line_index=line)
    lock_allocation(allocation["id"])
    for run in runs.values():
        reserve_run(run["id"])
    certify_pair(factory["id"])
    for run_type, run in runs.items():
        start_run(run["id"])
        runs[run_type] = complete_run(run["id"], (20, 0, 0))
    return {"factory": factory, "model": model, "runs": runs}


def test_run_unit_cost_custom_batch_pays_tier_plus_five_points(api):
    """PRD §3.5: "A small-batch surcharge percentage is then selected:
    `GOVERNMENT` runs are exempt and pay zero percent, while every other run
    pays 25 percent when `planned_units` is below 10, 15 percent when it is at
    least 10 but below 25, 8 percent when it is at least 25 but below 50, and
    zero percent at 50 or more; a `CUSTOM_BATCH` run pays an additional 5
    percent on top of its tier."

    Design: Difficulty/combinatorial_formula/run_unit_cost_surcharge_tiers_and_type_conditionals
    """
    runs = _three_run_tier_kit()["runs"]
    # CUSTOM_BATCH, 8 units: 4600 * (1 + 0.25 + 0.05) = 5980.
    assert runs["CUSTOM_BATCH"]["certified_unit_cost_cents"] == 5980
    # STOCK, 8 units: 4600 * 1.25 = 5750.
    assert runs["STOCK"]["certified_unit_cost_cents"] == 5750


def test_run_unit_cost_government_is_surcharge_exempt(api):
    """PRD §3.5: "A small-batch surcharge percentage is then selected:
    `GOVERNMENT` runs are exempt and pay zero percent, while every other run
    pays 25 percent when `planned_units` is below 10, 15 percent when it is at
    least 10 but below 25, 8 percent when it is at least 25 but below 50, and
    zero percent at 50 or more; a `CUSTOM_BATCH` run pays an additional 5
    percent on top of its tier. The certified unit cost is the base multiplied
    by one plus the surcharge, rounded half up to integer cents — the single
    rounding happening after the surcharge is applied."

    Design: Difficulty/combinatorial_formula/run_unit_cost_surcharge_tiers_and_type_conditionals
    """
    runs = _three_run_tier_kit()["runs"]
    # GOVERNMENT, 8 units: exempt despite 8 < 10 -> 4600 * 1.00.
    assert runs["GOVERNMENT"]["certified_unit_cost_cents"] == 4600
    # Same 4600 base on all three runs; only tier + run_type conditionals split them.
    assert runs["CUSTOM_BATCH"]["certified_unit_cost_cents"] - 4600 == 1380


def _custom_pricing_kit():
    """CUSTOM1 (no certified report -> null domestic price) and CUSTOM2
    (CERTIFIED report total 5600 -> domestic price 21000); orders O_FB
    (CUSTOM1, RED, qty 2) and O_KP (CUSTOM2, RED, monogram AB, qty 1)."""
    set_clock()
    factory = make_factory(factory_name="Norridgewock ME Plant",
                           government_cleared=True, line_count=3)
    c_k = make_component("Kevlar lace set", "LACES")
    make_lot(c_k["id"], supplier_name="Rhode Island Cordage", quantity_received=100,
             unit_cost_cents=4000, is_domestic=True)
    m_fb = make_model(bom_lines=[bom_line(c_k["id"], planned_unit_cost_cents=100)],
                      style_code="CUSTOM1", base_price_cents=15000,
                      import_cost_basis_cents=4000, standard_stitching_minutes=1,
                      standard_lasting_minutes=1, standard_assembly_minutes=1)
    m_kp = make_model(bom_lines=[
        bom_line(c_k["id"], sourcing_requirement="DOMESTIC_REQUIRED",
                 planned_unit_cost_cents=3900, planned_is_domestic=True),
    ], style_code="CUSTOM2", base_price_cents=15000, import_cost_basis_cents=4000,
        standard_stitching_minutes=20)
    allocation = make_allocation(factory["id"], WEEK_36, 100)
    run = make_run(m_kp["id"], factory["id"], planned_units=10)
    lock_allocation(allocation["id"])
    reserve_run(run["id"])
    certify_pair(factory["id"])
    start_run(run["id"])
    complete_run(run["id"], (20, 0, 0))
    create_report(run["id"], "CERTIFIED")  # total 5600 -> domestic_price 21000
    o_fb = make_order(m_fb["id"], buyer="cust-1", colorway="RED", size="10",
                      quantity_units=2)
    o_kp = make_order(m_kp["id"], buyer="cust-1", colorway="RED", size="9",
                      monogram="AB", quantity_units=1)
    return {"m_fb": m_fb, "m_kp": m_kp, "o_fb": o_fb, "o_kp": o_kp}


def test_custom_price_tier_keyed_on_pre_discount_subtotal(api):
    """PRD §3.7: "The pre-discount subtotal is the base plus the fees, and the
    discount tier is keyed on that pre-discount figure, never on the discounted
    total: a subtotal of at least 20000 cents earns a 10 percent discount, a
    subtotal of at least 12000 cents but under 20000 earns 5 percent, and
    anything below 12000 cents earns none."

    Design: Difficulty/combinatorial_formula/custom_order_price_pinned_evaluation_order
    """
    kit = _custom_pricing_kit()
    accepted = accept_order(kit["o_kp"]["id"])
    # base 21000 + colorway 250 + monogram 500 = 21750 >= 20000 -> 10% tier.
    # 21750 * 0.90 = 19575 per pair, x 1 unit. Keying the tier on the
    # post-discount 19575 (< 20000) would wrongly yield 20663.
    assert accepted["quoted_price_cents"] == 19575
    model = validate_success(api.get_model(kit["m_kp"]["id"], SOURCING))
    assert model["domestic_price_cents"] == 21000


def test_custom_price_fallback_markup_and_per_pair_rounding(api):
    """PRD §3.7: "The per-pair base is the model's `domestic_price_cents` when
    that field has been populated by a certified domestic report, and otherwise
    the model's `base_price_cents` marked up by 15 percent and rounded half up
    to integer cents."
    PRD §3.7: "The order's `quoted_price_cents` is the discounted per-pair price
    rounded half up to integer cents and only then multiplied by
    `quantity_units` — the per-pair rounding happens before the quantity
    multiplication."

    Design: Difficulty/combinatorial_formula/custom_order_price_pinned_evaluation_order
    """
    kit = _custom_pricing_kit()
    accepted = accept_order(kit["o_fb"]["id"])
    # fallback base round_half_up(15000 * 1.15) = 17250; +250 colorway = 17500
    # -> 5% tier -> round_half_up(17500 * 0.95) = 16625 per pair; x 2 = 33250.
    assert accepted["quoted_price_cents"] == 33250
    model = validate_success(api.get_model(kit["m_fb"]["id"], SOURCING))
    assert model["domestic_price_cents"] is None
