"""Blend-run lot selection: COST_MIN vs FIFO_AGE over identical inventory."""
import pytest
from test_helpers import (
    create_supplier, create_accepted_lot, create_active_formula,
    create_committed_blend_run,
)

TAG = "Design: Difficulty/dual_variant_calc/blend_selection_cost_min_vs_fifo_age"


def _setup_policy_runs():
    """Three ACCEPTED pepper lots where cost order and crop-year order disagree:
    L1 crop 2024 cost 500, L2 crop 2025 cost 400, L3 crop 2026 cost 300.
    Two committed 100 kg runs over the same ACTIVE formula, one per policy."""
    supplier = create_supplier()
    l1 = create_accepted_lot(supplier["id"], crop_year=2024,
                             cost_per_kg_cents=500)
    l2 = create_accepted_lot(supplier["id"], crop_year=2025,
                             cost_per_kg_cents=400)
    l3 = create_accepted_lot(supplier["id"], crop_year=2026,
                             cost_per_kg_cents=300)
    formula = create_active_formula("PEP-100")
    br_cm = create_committed_blend_run(formula["id"], "COST_MIN", 100)
    br_fa = create_committed_blend_run(formula["id"], "FIFO_AGE", 100)
    return {"l1": l1, "l2": l2, "l3": l3, "cm": br_cm, "fa": br_fa}


def _alloc_map(blend_run):
    return {a["lot_id"]: a["allocated_kg"]
            for a in blend_run["selected_allocations"]}


def test_cost_min_consumes_cheapest_lots_first(api):
    """PRD §3.4: "under `COST_MIN`, ascending `cost_per_kg_cents` with ties
    broken by ascending `created_at`, so the cheapest lots are consumed first".
    PRD §3.4: "For each recorded allocation, in recording order, the
    allocation's `line_cost_cents` is `allocated_kg` multiplied by the lot's
    `cost_per_kg_cents`, rounded half-up to a whole cent — the rounding happens
    per allocation first. The subtotal is then the sum of those per-allocation
    cents. The production overhead is the subtotal multiplied by 3.5 percent,
    rounded half-up to a whole cent."

    COST_MIN over 100 kg (cap 40.000 per lot): L3 40.000 @300 + L2 40.000 @400
    + L1 20.000 @500 = subtotal 38000, overhead 1330 -> total 39330.

    Design: Difficulty/dual_variant_calc/blend_selection_cost_min_vs_fifo_age
    """
    s = _setup_policy_runs()
    cm = s["cm"]
    assert cm["status"] == "COMMITTED"
    alloc = _alloc_map(cm)
    assert alloc[s["l3"]["id"]] == pytest.approx(40.0, abs=1e-6)
    assert alloc[s["l2"]["id"]] == pytest.approx(40.0, abs=1e-6)
    assert alloc[s["l1"]["id"]] == pytest.approx(20.0, abs=1e-6)
    assert cm["cost_total_cents"] == 39330
    assert cm["residual_flavor_pct"] == pytest.approx(0.0, abs=1e-6)
    assert cm["spec_status"] == "WITHIN_SPEC"


def test_fifo_age_consumes_oldest_crop_first(api):
    """PRD §3.4: "under `FIFO_AGE`, ascending `crop_year` with the same
    `created_at` tie-break, so the oldest crop is consumed first."
    PRD §3.4: "Given identical inventory, the two policies select genuinely
    different lot sets — and therefore produce a different `cost_total_cents` —
    whenever cost order and age order disagree."

    FIFO_AGE over 100 kg: L1 (2024) 40.000 @500 + L2 (2025) 40.000 @400
    + L3 (2026) 20.000 @300 = subtotal 42000, overhead 1470 -> total 43470.
    Identical inputs, different selected set than COST_MIN.

    Design: Difficulty/dual_variant_calc/blend_selection_cost_min_vs_fifo_age
    """
    s = _setup_policy_runs()
    fa, cm = s["fa"], s["cm"]
    assert fa["status"] == "COMMITTED"
    alloc_fa, alloc_cm = _alloc_map(fa), _alloc_map(cm)
    assert alloc_fa[s["l1"]["id"]] == pytest.approx(40.0, abs=1e-6)
    assert alloc_fa[s["l2"]["id"]] == pytest.approx(40.0, abs=1e-6)
    assert alloc_fa[s["l3"]["id"]] == pytest.approx(20.0, abs=1e-6)
    assert fa["cost_total_cents"] == 43470
    # Same inventory, same batch size: only the policy differs, so the same lot
    # is allocated 20.000 kg under COST_MIN but 40.000 kg under FIFO_AGE.
    assert alloc_cm[s["l1"]["id"]] != alloc_fa[s["l1"]["id"]]
    assert fa["residual_flavor_pct"] == pytest.approx(0.0, abs=1e-6)
    assert fa["spec_status"] == "WITHIN_SPEC"
