"""Capacity-side calculations (PRD 3.2, 3.3; SCAFFOLD 1.3).

allocated_hours (per-component round-up, then sum), train_window_conflict
(half-open intervals, exact gap allowed), firm_capacity_waterfall (with
CLINICAL preemption selector), material_coverage (10% overage, single-source
check before generic shortage, created_at-ascending consumption).
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
import store
from constants import (
    CHANGEOVER_BLOCK_HOURS,
    FIRM_CONSUMING_STATUSES,
    OVERAGE_FACTOR,
    PRODUCTION_BLOCK_HOURS,
    SEED_SHIFT_HOURS,
    WINDOW_STATUSES,
)
from errors import err


def _ceil_block(hours, block):
    return -(-int(hours) // block) * block


def _predecessor(train_id, start_utc, exclude_id=None):
    """Latest-ending earlier campaign on the train in a window-occupying status."""
    cands = [
        c for c in store.all_recs("campaigns")
        if c["train_id"] == train_id
        and c["id"] != exclude_id
        and c["status"] in WINDOW_STATUSES
        and c["planned_end_utc"] <= start_utc
    ]
    if not cands:
        return None
    return max(cands, key=lambda c: (c["planned_end_utc"], c["created_at"], c["_seq"]))


def gap_hours(prod_a, prod_b):
    """Required gap between campaigns of prod_a (earlier) and prod_b (later)."""
    if prod_a["id"] == prod_b["id"]:
        return prod_b["same_product_turnaround_hours"]
    return max(prod_a["changeover_hours"], prod_b["changeover_hours"])


def allocated_hours(train_id, product, upstream_hours, downstream_hours, start_utc):
    up = _ceil_block(upstream_hours, SEED_SHIFT_HOURS)
    down = _ceil_block(downstream_hours, PRODUCTION_BLOCK_HOURS)
    pred = _predecessor(train_id, start_utc)
    changeover = 0
    if pred is not None:
        pred_product = store.get("products", pred["product_id"])
        g = gap_hours(pred_product, product)
        changeover = _ceil_block(g, CHANGEOVER_BLOCK_HOURS)
    return up + down + changeover


def check_window_conflict(train_id, product, start_utc, end_utc, exclude_id=None):
    """ERR_TRAIN_WINDOW_CONFLICT on overlap or sub-gap shortfall (>= semantics)."""
    for other in store.all_recs("campaigns"):
        if other["train_id"] != train_id or other["id"] == exclude_id:
            continue
        if other["status"] not in WINDOW_STATUSES:
            continue
        other_product = store.get("products", other["product_id"])
        g = gap_hours(other_product, product)
        gap = timedelta(hours=g)
        if start_utc >= other["planned_end_utc"] + gap:
            continue
        if end_utc + gap <= other["planned_start_utc"]:
            continue
        err("ERR_TRAIN_WINDOW_CONFLICT",
            "Planned window collides with another campaign on the train")


def _same_month(dt, month_start):
    return dt.year == month_start.year and dt.month == month_start.month


def firm_consumed(site_id, month_start, exclude_id=None):
    total = 0
    for c in store.all_recs("campaigns"):
        if c["id"] == exclude_id or c["status"] not in FIRM_CONSUMING_STATUSES:
            continue
        train = store.get("trains", c["train_id"])
        if train["site_id"] == site_id and _same_month(c["planned_start_utc"], month_start):
            total += c["allocated_hours"]
    return total


def capacity_waterfall(site, candidate):
    """Firm monthly capacity waterfall with CLINICAL preemption (PRD 3.2)."""
    month = candidate["planned_start_utc"]
    available = site["monthly_capacity_hours"] - firm_consumed(site["id"], month)
    if candidate["allocated_hours"] <= available:
        return  # <= semantics: exact fit is sufficient
    if candidate["demand_type"] != "CLINICAL":
        err("ERR_CAPACITY_EXCEEDED", "Firm monthly capacity insufficient")
    cands = []
    for c in store.all_recs("campaigns"):
        if c["demand_type"] == "COMMERCIAL" and c["status"] == "ALLOCATED" \
                and _same_month(c["planned_start_utc"], month):
            train = store.get("trains", c["train_id"])
            if train["site_id"] == site["id"]:
                cands.append(c)
    # latest planned_start_utc first; ties by earliest created_at (seq tie-break)
    cands.sort(key=lambda c: (-c["planned_start_utc"].timestamp(), c["created_at"], c["_seq"]))
    for c in cands:
        c["status"] = "PREEMPTED"  # ALLOCATED -> PREEMPTED releases firm hours
        store.touch(c)
        available += c["allocated_hours"]
        if candidate["allocated_hours"] <= available:
            return
    err("ERR_CAPACITY_EXCEEDED", "Firm monthly capacity insufficient after preemption")


def required_quantity(base_quantity):
    return (Decimal(str(base_quantity)) * (1 + OVERAGE_FACTOR)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)


def available_quantity(site_id, material_name):
    total = Decimal("0")
    for lot in store.all_recs("materials"):
        if lot["site_id"] == site_id and lot["material_name"] == material_name \
                and lot["status"] == "AVAILABLE":
            total += lot["quantity_available"]
    return total


def check_material_coverage(site_id, product):
    """Single-source shortfall check globally precedes the generic shortage."""
    entries = product["required_materials"]
    for entry in entries:
        if entry["is_single_source"]:
            req = required_quantity(entry["base_quantity"])
            if available_quantity(site_id, entry["material_name"]) < req:
                err("ERR_SINGLE_SOURCE_MATERIAL_BLOCKED",
                    f"Single-source material {entry['material_name']} short")
    for entry in entries:
        req = required_quantity(entry["base_quantity"])
        if available_quantity(site_id, entry["material_name"]) < req:
            err("ERR_MATERIAL_SHORTAGE", f"Material {entry['material_name']} short")


def consume_materials(site_id, product):
    """Decrement AVAILABLE lots in created_at ASC order until each entry covered."""
    for entry in product["required_materials"]:
        remaining = required_quantity(entry["base_quantity"])
        lots = [lot for lot in store.all_recs("materials")
                if lot["site_id"] == site_id
                and lot["material_name"] == entry["material_name"]
                and lot["status"] == "AVAILABLE"]
        lots.sort(key=lambda lot: (lot["created_at"], lot["_seq"]))
        for lot in lots:
            if remaining <= 0:
                break
            take = min(lot["quantity_available"], remaining)
            lot["quantity_available"] -= take
            store.touch(lot)
            remaining -= take
