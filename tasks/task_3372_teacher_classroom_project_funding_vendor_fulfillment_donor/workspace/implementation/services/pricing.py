"""Pricing and scoring calculations (SCAFFOLD calculations table).

- po_shipping_quote: tiered weight base + ceil pounds * max zone rate +
  fragile flat, clamped to [199, 4999] cents.
- project_cost_quote: provisional (live catalog prices, DRAFT/RETURNED) and
  pinned (frozen at submit).
- school_equity_scores: banded step function vs weighted blend.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

import store

ZONE_RATES = {"A": 120, "B": 180, "C": 260}

GOAL_MIN_CENTS = 10000
GOAL_MAX_CENTS = 200000

TIER1_MAX_OZ = 32
TIER1_BASE_CENTS = 299
TIER2_MAX_OZ = 128
TIER2_BASE_CENTS = 599
TIER3_BASE_CENTS = 899
FRAGILE_FLAT_CENTS = 350
FEE_MIN_CENTS = 199
FEE_CAP_CENTS = 4999


def shipping_quote(lines):
    """lines: [{quantity, weight_oz, shipping_zone, fragile}] for ONE vendor."""
    total_oz = sum(line["quantity"] * line["weight_oz"] for line in lines)
    if total_oz <= TIER1_MAX_OZ:
        tier_base = TIER1_BASE_CENTS
    elif total_oz <= TIER2_MAX_OZ:
        tier_base = TIER2_BASE_CENTS
    else:
        tier_base = TIER3_BASE_CENTS
    zone_rate = max(ZONE_RATES[line["shipping_zone"]] for line in lines)
    pounds = math.ceil(total_oz / 16)
    raw = tier_base + pounds * zone_rate
    if any(line["fragile"] for line in lines):
        raw += FRAGILE_FLAT_CENTS
    return min(FEE_CAP_CENTS, max(FEE_MIN_CENTS, raw))


def items_of(project_id):
    """A project's ProjectItems, catalog-creation ordered."""
    rows = [it for it in store.project_items.values() if it["project_id"] == project_id]
    rows.sort(key=lambda it: (it["created_at"], it["_seq"]))
    return rows


def vendor_groups(project_id):
    """Group the project's items by the catalog item's vendor.

    Returns {vendor_id: [(project_item, catalog_item), ...]} with each group
    sorted by the catalog item's created_at ASC (never by id).
    """
    groups = {}
    for item in items_of(project_id):
        ci = store.catalog_items.get(item["catalog_item_id"])
        if ci is None:
            continue
        groups.setdefault(ci["vendor_id"], []).append((item, ci))
    for pairs in groups.values():
        pairs.sort(key=lambda pair: (pair[1]["created_at"], pair[1]["_seq"]))
    return groups


def shipping_lines(pairs):
    return [
        {
            "quantity": item["quantity"],
            "weight_oz": ci["weight_oz"],
            "shipping_zone": ci["shipping_zone"],
            "fragile": ci["fragile"],
        }
        for item, ci in pairs
    ]


def provisional_total(project):
    """Draft-face quote at CURRENT catalog prices; None while no items exist."""
    items = items_of(project["id"])
    if not items:
        return None
    total = 0
    for item in items:
        ci = store.catalog_items[item["catalog_item_id"]]
        total += item["quantity"] * ci["unit_price_cents"]
    for pairs in vendor_groups(project["id"]).values():
        total += shipping_quote(shipping_lines(pairs))
    return total


def equity_banded(poverty_pct):
    p = float(poverty_pct)
    if p >= 90.0:
        return 100
    if p >= 75.0:
        return 80
    if p >= 50.0:
        return 50
    return 10


def equity_weighted(poverty_pct, ell_pct):
    """round_half_up(0.7 * poverty_pct + 0.3 * ell_pct, 1)."""
    value = Decimal(str(poverty_pct)) * Decimal("0.7") + Decimal(str(ell_pct)) * Decimal("0.3")
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
