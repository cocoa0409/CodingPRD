"""Ingredient-order costing and the automatic reorder draft (PRD 3.8)."""

from store import db, new_entity
from response import mark_new
from services.calc import auto_reorder_topup, cost_order_line


def build_lines(department, entries):
    """Cost each (ingredient, required_units) pair in supplied order.

    Returns (lines, order_total_cents); every line is rounded to whole cents
    before the total sums the already-rounded lines.
    """
    freight = department["freight_surcharge_pct"]
    lines = []
    total = 0
    for ingredient, required_units in entries:
        cases, ordered_units, line_cost = cost_order_line(ingredient, required_units, freight)
        lines.append(
            {
                "ingredient_id": ingredient["id"],
                "required_units": int(required_units),
                "cases": cases,
                "ordered_units": ordered_units,
                "line_cost_cents": line_cost,
            }
        )
        total += line_cost
    return lines, total


def create_order(department, target_bake_day_id, origin, lines, total):
    row = new_entity(
        department_id=department["id"],
        target_bake_day_id=target_bake_day_id,
        origin=origin,
        lines=lines,
        order_total_cents=total,
        order_status="DRAFT",
        submitted_at_utc=None,
        received_lines=[],
        shortfall_units_total=0,
        cancel_reason=None,
    )
    db.ingredient_orders[row["id"]] = row
    mark_new(row)
    return row


def create_auto_reorder(department, ingredients):
    """One AUTO_REORDER draft per run completion, holding one top-up line per
    eligible ingredient.  No order is minted when nothing is eligible."""
    entries = [(ingredient, auto_reorder_topup(ingredient)) for ingredient in ingredients]
    if not entries:
        return None
    lines, total = build_lines(department, entries)
    order = create_order(department, None, "AUTO_REORDER", lines, total)
    from services.rollups import recompute_commitment

    recompute_commitment(department, force=True)
    return order
