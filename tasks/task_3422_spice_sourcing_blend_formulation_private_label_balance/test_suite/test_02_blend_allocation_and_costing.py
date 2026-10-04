"""Blend allocation under interacting constraints and pinned cost rounding."""
import pytest
from test_helpers import (
    create_supplier, create_accepted_lot, create_active_formula,
    create_committed_blend_run,
)

TAG_A = "Design: Difficulty/combinatorial_formula/blend_allocation_multi_constraint_mode_a"
TAG_B = "Design: Difficulty/combinatorial_formula/blend_cost_rollup_rounding_order_mode_b"


def _setup_grill42_commit():
    """Six ACCEPTED lots (3 pepper, 3 paprika) and a committed 200 kg run of
    two-line formula GRILL-42 (pepper 60% min 80, paprika 40% min 50)."""
    supplier = create_supplier(name="Global Spice Ltd", origin_country="VN")
    p1 = create_accepted_lot(supplier["id"], crop_year=2024,
                             flavor_intensity_units=90.0, cost_per_kg_cents=300)
    p2 = create_accepted_lot(supplier["id"], crop_year=2025,
                             flavor_intensity_units=85.0, cost_per_kg_cents=280)
    p3 = create_accepted_lot(supplier["id"], crop_year=2025,
                             flavor_intensity_units=88.0, cost_per_kg_cents=320)
    k1 = create_accepted_lot(supplier["id"], spice_code="PAPRIKA",
                             origin_region="Szeged", quantity_kg=50,
                             flavor_intensity_units=60.0, cost_per_kg_cents=200)
    k2 = create_accepted_lot(supplier["id"], spice_code="PAPRIKA",
                             origin_region="Szeged", quantity_kg=60,
                             flavor_intensity_units=55.0, cost_per_kg_cents=180)
    k3 = create_accepted_lot(supplier["id"], spice_code="PAPRIKA",
                             origin_region="Szeged", crop_year=2026,
                             quantity_kg=40, flavor_intensity_units=58.0,
                             cost_per_kg_cents=220)
    formula = create_active_formula(
        "GRILL-42", target_flavor_units=75.0,
        lines=[dict(spice_code="BLACK_PEPPER", target_proportion_pct=60.0,
                    min_lot_flavor_units=80.0),
               dict(spice_code="PAPRIKA", target_proportion_pct=40.0,
                    min_lot_flavor_units=50.0)])
    br = create_committed_blend_run(formula["id"], "COST_MIN", 200)
    return {"p1": p1, "p2": p2, "p3": p3, "k1": k1, "k2": k2, "k3": k3,
            "br": br}


def _setup_cumin_commit():
    """Three identical-cost ACCEPTED cumin lots and a committed 2.513 kg run —
    the per-lot cap floor(2.513*0.40) = 1.005 binds twice."""
    supplier = create_supplier(name="Cumin Coop", origin_country="TR")
    m1 = create_accepted_lot(supplier["id"], spice_code="CUMIN",
                             origin_region="Konya", moisture_pct=5.0)
    m2 = create_accepted_lot(supplier["id"], spice_code="CUMIN",
                             origin_region="Konya", moisture_pct=5.0)
    m3 = create_accepted_lot(supplier["id"], spice_code="CUMIN",
                             origin_region="Konya", moisture_pct=5.0)
    formula = create_active_formula(
        "CUMIN-PURE",
        lines=[dict(spice_code="CUMIN", target_proportion_pct=100.0,
                    min_lot_flavor_units=0.0)])
    br = create_committed_blend_run(formula["id"], "COST_MIN", 2.513)
    return {"m1": m1, "m2": m2, "m3": m3, "br": br}


class TestMultiLineAllocation:
    def test_per_lot_cap_binds_and_forces_third_lot(self, api):
        """PRD §3.4: "From the needed quantity it derives the per-line
        single-lot cap: 40.0 percent of the needed kilograms, rounded down to
        three decimal places — no single lot may supply more than that cap for
        the line." PRD §3.4: "The commit then walks the ordered pool,
        allocating from each lot the minimum of three quantities — the line's
        remaining need, the lot's `quantity_remaining_kg`, and the per-line cap".

        Pepper line needs 120.000 kg (cap 48.000): p2=48, p1=48, p3=24.
        Paprika line needs 80.000 kg (cap 32.000): k2=32, k1=32, k3=16.

        Design: Difficulty/combinatorial_formula/blend_allocation_multi_constraint_mode_a
        """
        s = _setup_grill42_commit()
        br = s["br"]
        assert br["status"] == "COMMITTED"
        alloc = {a["lot_id"]: a["allocated_kg"]
                 for a in br["selected_allocations"]}
        assert alloc[s["p2"]["id"]] == pytest.approx(48.0, abs=1e-6)
        assert alloc[s["p1"]["id"]] == pytest.approx(48.0, abs=1e-6)
        assert alloc[s["p3"]["id"]] == pytest.approx(24.0, abs=1e-6)
        assert alloc[s["k2"]["id"]] == pytest.approx(32.0, abs=1e-6)
        assert alloc[s["k1"]["id"]] == pytest.approx(32.0, abs=1e-6)
        assert alloc[s["k3"]["id"]] == pytest.approx(16.0, abs=1e-6)

    def test_allocation_order_cost_rollup_and_residual(self, api):
        """PRD §3.4: "`selected_allocations` (ordered by formula-line creation
        order, then by policy order within each line)". PRD §3.4: "The
        production overhead is the subtotal multiplied by 3.5 percent, rounded
        half-up to a whole cent. The `cost_total_cents` is the subtotal plus
        the overhead."

        Subtotal 35520 (pepper) + 15680 (paprika) = 51200; overhead
        round_half_up(51200 * 0.035) = 1792; total 52992. Blended flavor 75.6
        vs target 75.0 -> residual +0.8, WITHIN_SPEC.

        Design: Difficulty/combinatorial_formula/blend_allocation_multi_constraint_mode_a
        """
        s = _setup_grill42_commit()
        br = s["br"]
        entries = br["selected_allocations"]
        # Formula-line creation order: all BLACK_PEPPER entries precede PAPRIKA.
        assert [e["spice_code"] for e in entries[:3]] == ["BLACK_PEPPER"] * 3
        assert [e["spice_code"] for e in entries[3:]] == ["PAPRIKA"] * 3
        assert [e["line_cost_cents"] for e in entries] == [
            13440, 14400, 7680, 5760, 6400, 3520]
        assert br["cost_total_cents"] == 52992
        assert br["residual_flavor_pct"] == pytest.approx(0.8, abs=1e-6)
        assert br["spec_status"] == "WITHIN_SPEC"


class TestCostRollupRoundingOrder:
    def test_per_allocation_rounding_uses_exact_decimal(self, api):
        """PRD §2.6: "multiplying 1.005 by 100 must yield exactly 100.5, which
        then rounds to exactly 101". PRD §3.4: "the allocation's
        `line_cost_cents` is `allocated_kg` multiplied by the lot's
        `cost_per_kg_cents`, rounded half-up to a whole cent — the rounding
        happens per allocation first."

        Allocations 1.005 / 1.005 / 0.503 kg @100 cents -> line costs
        101 / 101 / 50 (ties on cost broken by created_at).

        Design: Difficulty/combinatorial_formula/blend_cost_rollup_rounding_order_mode_b
        """
        s = _setup_cumin_commit()
        br = s["br"]
        assert br["status"] == "COMMITTED"
        entries = br["selected_allocations"]
        assert [e["lot_id"] for e in entries] == [
            s["m1"]["id"], s["m2"]["id"], s["m3"]["id"]]
        for entry, expected_kg in zip(entries, [1.005, 1.005, 0.503]):
            assert entry["allocated_kg"] == pytest.approx(expected_kg, abs=1e-6)
        assert [e["line_cost_cents"] for e in entries] == [101, 101, 50]

    def test_total_is_261_not_the_sum_then_round_260(self, api):
        """PRD §3.4: "Rounding per allocation, then summing, then applying
        overhead is the only correct order; summing raw per-allocation products
        and rounding once at the end yields different cents and is wrong."

        Subtotal 101+101+50 = 252; overhead round_half_up(252 * 0.035) = 9;
        total 261. The unpinned order would give 260.

        Design: Difficulty/combinatorial_formula/blend_cost_rollup_rounding_order_mode_b
        """
        s = _setup_cumin_commit()
        br = s["br"]
        assert br["cost_total_cents"] == 261
        assert br["cost_total_cents"] != 260
        assert br["residual_flavor_pct"] == pytest.approx(0.0, abs=1e-6)
        assert br["spec_status"] == "WITHIN_SPEC"
