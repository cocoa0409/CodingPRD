"""Blend lot selection + specification + cost rollup
(calculations.blend_lot_selection and calculations.blend_cost_rollup).

Pinned rules:
- needed_i = round_half_up(target_batch_kg * target_proportion_pct_i / 100, 3)
- cap_i = floor(needed_i * 40.0 / 100 to 3 decimals)   (ROUND_FLOOR exception)
- candidates: ACCEPTED lots only, matching spice_code, flavor >= min,
  organic requirement honored, quantity_remaining_kg > 0
- COST_MIN: cost_per_kg_cents ASC, created_at ASC; FIFO_AGE: crop_year ASC, created_at ASC
- alloc = min(remaining_need, lot.quantity_remaining_kg, cap_i)
- cost rollup: round_half_up per allocation (0 decimals) FIRST, then sum,
  then overhead = round_half_up(subtotal * 3.5/100), total = subtotal + overhead.
"""
from decimal import Decimal

from state import DB
from errors import ApiError
from helpers import D, q3, floor3, round_cents

MAX_SINGLE_LOT_SHARE_PCT = Decimal("40.0")
PRODUCTION_OVERHEAD_PCT = Decimal("3.5")
HUNDRED = Decimal("100")


def formula_lines(formula_id):
    lines = [l for l in DB.formula_lines.values() if l["formula_id"] == formula_id]
    lines.sort(key=lambda l: (l["created_at"], l["_seq"]))
    return lines


def select_allocations(run, formula):
    """Walk the formula's lines in creation order and allocate lots.

    Returns (allocations, residual_flavor_pct, blended_moisture_pct,
             cost_total_cents, spec_status).
    Raises ERR_NO_QUALIFYING_LOTS / ERR_INSUFFICIENT_LOT_QUANTITY before any
    computed field exists (caller persists nothing in that case).
    """
    allocations = []
    for line in formula_lines(formula["id"]):
        needed = q3(run["target_batch_kg"] * line["target_proportion_pct"] / HUNDRED)
        cap = floor3(needed * MAX_SINGLE_LOT_SHARE_PCT / HUNDRED)
        cands = [
            lot for lot in DB.lots.values()
            if lot["status"] == "ACCEPTED"
            and lot["spice_code"] == line["spice_code"]
            and lot["flavor_intensity_units"] >= line["min_lot_flavor_units"]
            and (not line["organic_required"] or lot["organic_certified"])
            and lot["quantity_remaining_kg"] > 0
        ]
        if not cands:
            raise ApiError("ERR_NO_QUALIFYING_LOTS", 422,
                           "No qualifying lots for component %s" % line["masked_component_code"])
        if run["selection_policy"] == "COST_MIN":
            cands.sort(key=lambda l: (l["cost_per_kg_cents"], l["created_at"], l["_seq"]))
        else:  # FIFO_AGE
            cands.sort(key=lambda l: (l["crop_year"], l["created_at"], l["_seq"]))
        remaining = needed
        for lot in cands:
            if remaining <= 0:
                break
            alloc = min(remaining, lot["quantity_remaining_kg"], cap)
            if alloc > 0:
                allocations.append({
                    "lot_id": lot["id"],
                    "spice_code": line["spice_code"],
                    "allocated_kg": alloc,
                })
                remaining -= alloc
        if remaining > 0:
            raise ApiError("ERR_INSUFFICIENT_LOT_QUANTITY", 409,
                           "Insufficient qualifying quantity for component %s"
                           % line["masked_component_code"])

    total_kg = sum((a["allocated_kg"] for a in allocations), D(0))
    if total_kg > 0:
        blended_flavor = sum(
            (a["allocated_kg"] * DB.lots[a["lot_id"]]["flavor_intensity_units"]
             for a in allocations), D(0)) / total_kg
        blended_moisture = sum(
            (a["allocated_kg"] * DB.lots[a["lot_id"]]["moisture_pct"]
             for a in allocations), D(0)) / total_kg
    else:
        blended_flavor = D(0)
        blended_moisture = D(0)
    residual = q3((blended_flavor - formula["target_flavor_units"])
                  / formula["target_flavor_units"] * HUNDRED)
    moisture3 = q3(blended_moisture)
    within = (abs(residual) <= formula["flavor_tolerance_pct"]
              and moisture3 <= formula["max_moisture_pct"])
    spec_status = "WITHIN_SPEC" if within else "OUT_OF_SPEC"

    # Cost rollup: per-allocation rounding FIRST, then sum, then overhead.
    subtotal = 0
    for a in allocations:
        line_cost = round_cents(a["allocated_kg"] * DB.lots[a["lot_id"]]["cost_per_kg_cents"])
        a["line_cost_cents"] = line_cost
        subtotal += line_cost
    overhead = round_cents(D(subtotal) * PRODUCTION_OVERHEAD_PCT / HUNDRED)
    cost_total = subtotal + overhead

    return allocations, residual, moisture3, cost_total, spec_status
