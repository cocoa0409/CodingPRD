"""Difficulty queue A: combinatorial formulas — per-line rounding, nested labor min/cap."""
from test_helpers import (
    adjudicate,
    file_claim_with_photos,
    get_remedy,
    setup_active_registration,
)


def test_material_proration_rounds_per_line_before_sum(api, program_admin_headers, claimant_headers):
    """PRD §3.6 step 3: "Each registration component line's `material_cost_cents` is
    multiplied by the schedule percentage and rounded half up to a whole cent per line;
    the pool `prorated_material_pool_cents` is the sum of those per-line rounded
    amounts. The per-line rounding before summation is pinned — rounding the sum
    instead is a different, incorrect algorithm." PRD §3.6 step 5:
    "`homeowner_material_share_cents` is the determination share applied to the
    remainder — the total installed material cost across all component lines minus the
    prorated pool — rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/material_proration_rounds_per_line_before_sum
    """
    ctx = setup_active_registration(tier="BRONZE", line_cents=1001)
    reg = ctx["registration"]
    info = file_claim_with_photos(reg["id"], claim_labor_cost_cents=0,
                                  file_at="2032-09-10", description="granule loss")
    claim, cv = info["claim"], info["version"]
    adjudicate(claim["id"], "MANUFACTURER_DEFECT", cv)
    rem = get_remedy(claim["id"])[0]
    assert rem["prorated_material_pool_cents"] == 2004
    assert rem["material_covered_cents"] == 2004
    assert rem["homeowner_material_share_cents"] == 2000
    assert rem["labor_covered_cents"] == 0


def test_material_proration_per_line_rounding_order_matters(api, program_admin_headers, claimant_headers):
    """PRD §3.6 step 3: "The per-line rounding before summation is pinned — rounding
    the sum instead is a different, incorrect algorithm."
    (4 lines of 1001 at 50 percent: per-line round gives 501 each, summing to 2004;
    sum-then-round would give 2002.)

    Design: Difficulty/combinatorial_formula/material_proration_rounds_per_line_before_sum
    """
    ctx = setup_active_registration(tier="BRONZE", line_cents=1001)
    reg = ctx["registration"]
    info = file_claim_with_photos(reg["id"], claim_labor_cost_cents=0,
                                  file_at="2032-09-10", description="rounding")
    claim, cv = info["claim"], info["version"]
    adjudicate(claim["id"], "MANUFACTURER_DEFECT", cv)
    rem = get_remedy(claim["id"])[0]
    assert rem["prorated_material_pool_cents"] != 2002
    assert rem["prorated_material_pool_cents"] == 2004


def test_labor_coverage_nested_min_cap_binds_at_gold(api, program_admin_headers, claimant_headers):
    """PRD §3.6 step 6: "Inside the window, `labor_covered_cents` is the determination
    share applied to the lesser of the claim's `claim_labor_cost_cents` and the tier's
    labor cap — 200000 cents for `BRONZE`, 500000 cents for `SILVER`, 1000000 cents
    for `GOLD` — rounded half up to a whole cent." PRD §3.6 step 2: "Under
    `ENHANCED_PLUS`, coverage holds at 100 percent through the tenth year..."

    Design: Difficulty/combinatorial_formula/labor_coverage_nested_min_and_strict_year_gate
    """
    ctx = setup_active_registration(tier="GOLD", line_cents=25000,
                                    license_expiry="2040-01-01", insurance_expiry="2040-01-01")
    reg = ctx["registration"]
    info = file_claim_with_photos(reg["id"], claim_labor_cost_cents=1200000,
                                  file_at="2032-09-10", description="claim A")
    claim, cv = info["claim"], info["version"]
    adjudicate(claim["id"], "MANUFACTURER_DEFECT", cv)
    rem = get_remedy(claim["id"])[0]
    assert rem["labor_covered_cents"] == 1000000
    assert rem["material_covered_cents"] == 100000
    assert rem["completed_years"] == 6


def test_labor_coverage_strict_year_gate_closes_at_boundary(api, program_admin_headers, claimant_headers):
    """PRD §3.6 step 6: "For `QUALIFYING_SYSTEM` registrations, labor coverage also
    expires with age: each tier covers labor for a fixed number of years — 2 years
    for `BRONZE`, 5 for `SILVER`, 10 for `GOLD` — and the gate is strict, so at the
    boundary year the coverage is already gone; a claim filed in or after the tier's
    labor year count receives zero labor coverage."

    Design: Difficulty/combinatorial_formula/labor_coverage_nested_min_and_strict_year_gate
    """
    ctx = setup_active_registration(tier="GOLD", line_cents=25000,
                                    license_expiry="2040-01-01", insurance_expiry="2040-01-01")
    reg = ctx["registration"]
    info = file_claim_with_photos(reg["id"], claim_labor_cost_cents=1200000,
                                  file_at="2036-09-10", description="claim B")
    claim, cv = info["claim"], info["version"]
    adjudicate(claim["id"], "MANUFACTURER_DEFECT", cv)
    rem = get_remedy(claim["id"])[0]
    assert rem["completed_years"] == 10
    assert rem["labor_covered_cents"] == 0
