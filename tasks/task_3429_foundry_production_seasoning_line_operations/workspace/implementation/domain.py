"""Shared domain helpers: lookups, derived order state, and cross-entity cascades."""
from decimal import Decimal

import calc
import store
from errors import err

UNIT_NONTERMINAL = (
    "POURED",
    "SHAKEOUT_DONE",
    "DEFECT_REVIEW",
    "REWORK",
    "FINISHED",
    "SEASONING_QUEUED",
)
MELT_CANCELLABLE = ("CHARGING", "MELTING", "CHEMISTRY_CHECK", "ADJUSTMENT", "CERTIFIED", "HELD")
MELT_HOLDABLE = ("CHARGING", "MELTING", "CHEMISTRY_CHECK", "ADJUSTMENT", "CERTIFIED")


def try_get(kind, rid):
    return store.db[kind].get(rid)


def get_or_404(kind, rid):
    ent = store.db[kind].get(rid)
    if ent is None:
        raise err("ERR_RESOURCE_NOT_FOUND", f"{kind[:-1]} not found: {rid}")
    return ent


def order_derived(order):
    """Recompute (scrap_index, scrap_tier, posture) from current stored counters."""
    idx = calc.scrap_index(order["scrap_weighted_units"], order["poured_units"])
    tier = calc.scrap_tier(idx)
    held = any(
        m["state"] == "HELD" and m["production_order_id"] == order["id"]
        for m in store.db["melts"].values()
    )
    if held:
        posture = "FROZEN"
    elif tier == "RED":
        posture = "RESTRICTED"
    else:
        posture = "OPEN"
    return idx, tier, posture


def order_material_to_date_cents(order):
    return sum(
        m["actual_charge_cost_cents"]
        for m in store.db["melts"].values()
        if m["production_order_id"] == order["id"] and m["state"] != "CANCELLED"
    )


def permits_of_type(permit_type):
    return [p for p in store.db["permits"].values() if p["permit_type"] == permit_type]


def permit_type_in_breach(permit_type):
    return any(p["status"] == "BREACH" for p in permits_of_type(permit_type))


def inventory_for_product(product_id):
    for rec in store.db["inventory"].values():
        if rec["product_id"] == product_id:
            return rec
    return None


def available_units(rec):
    return rec["on_hand_units"] - rec["reserved_units"]


def current_sand_rate():
    """Month-to-date reclamation rate over molds reclaimed this calendar month."""
    now = store.now()
    key = (now.year, now.month)
    relevant = [
        m
        for m in store.db["molds"].values()
        if m["state"] == "SAND_RECLAIMED"
        and m.get("_reclaimed_at") is not None
        and (m["_reclaimed_at"].year, m["_reclaimed_at"].month) == key
    ]
    if not relevant:
        return None
    total_reclaimed = sum(calc.D(m["reclaimed_sand_lbs"]) for m in relevant)
    total_sand = sum(calc.D(m["sand_weight_lbs"]) for m in relevant)
    if total_sand == 0:
        return None
    return calc.rhu(total_reclaimed / total_sand, 4)


def order_closure_cascade(order):
    """Shared cancel/complete cascade (PRD 3.2). Seasoning batches fail first so
    their SEASONING_QUEUED units are then scrapped by the unit cascade."""
    oid = order["id"]
    for sb in sorted(store.db["seasoning"].values(), key=store.sort_key):
        if sb["production_order_id"] == oid and sb["state"] in ("COATING", "BAKING"):
            sb["state"] = "FAILED"
            store.touch(sb)
    for u in sorted(store.db["units"].values(), key=store.sort_key):
        if u["production_order_id"] == oid and u["state"] in UNIT_NONTERMINAL:
            if u["state"] == "DEFECT_REVIEW":
                for r in store.db["reports"].values():
                    if r["casting_unit_id"] == u["id"] and r["status"] == "OPEN":
                        r["status"] = "DISPOSITIONED"
                        r["disposition"] = "SCRAP"
                        r["dispositioned_by"] = "system"
                        store.touch(r)
            if u["state"] == "SEASONING_QUEUED":
                u["seasoning_batch_id"] = None
            u["state"] = "SCRAPPED"
            u["scrap_reason"] = "ORDER_CANCEL"
            order["scrapped_units"] += 1
            store.touch(u)
    for m in sorted(store.db["melts"].values(), key=store.sort_key):
        if m["production_order_id"] == oid and m["state"] in MELT_CANCELLABLE:
            m["state"] = "CANCELLED"
            m["state_before_hold"] = None
            store.touch(m)
    for mold in sorted(store.db["molds"].values(), key=store.sort_key):
        if mold["production_order_id"] == oid and mold["state"] == "PREPARED":
            mold["state"] = "CANCELLED"
            store.touch(mold)


def hold_cascade():
    """Permit enters BREACH: in-flight melts move to HELD (PRD 3.7)."""
    for m in sorted(store.db["melts"].values(), key=store.sort_key):
        if m["state"] in MELT_HOLDABLE:
            m["state_before_hold"] = m["state"]
            m["state"] = "HELD"
            store.touch(m)


def resume_cascade():
    """Permit returns to ACTIVE: HELD melts resume their state_before_hold."""
    for m in sorted(store.db["melts"].values(), key=store.sort_key):
        if m["state"] == "HELD":
            m["state"] = m["state_before_hold"]
            m["state_before_hold"] = None
            store.touch(m)


def breach_permit(permit, recorded_by, hold_melts):
    """Drive a permit into BREACH (idempotent when already BREACH)."""
    if permit["status"] == "BREACH":
        return
    permit["status"] = "BREACH"
    permit["last_breach_reading_recorded_by"] = recorded_by
    if hold_melts:
        hold_cascade()
    store.touch(permit)


def mark_unit_finished(unit):
    """Unit reaches FINISHED; first FINISHED unit moves order POURING -> FINISHING."""
    unit["state"] = "FINISHED"
    store.touch(unit)
    order = store.db["orders"].get(unit["production_order_id"])
    if order is not None and order["state"] == "POURING":
        order["state"] = "FINISHING"
        store.touch(order)


def defect_scrap(unit, report, dispositioned_by):
    """Disposition SCRAP accounting (PRD 3.5)."""
    report["status"] = "DISPOSITIONED"
    report["disposition"] = "SCRAP"
    report["dispositioned_by"] = dispositioned_by
    store.touch(report)

    unit["state"] = "SCRAPPED"
    unit["scrap_reason"] = "DEFECT"
    unit["scrapped_after_rework"] = unit["rework_count"] >= 1
    store.touch(unit)

    order = store.db["orders"][unit["production_order_id"]]
    order["scrapped_units"] += 1
    order["defect_scrapped_units"] += 1
    weight = calc.REWORK_SCRAP_WEIGHT if unit["scrapped_after_rework"] else Decimal("1.0")
    order["scrap_weighted_units"] = calc.D(order["scrap_weighted_units"]) + weight
    store.touch(order)

    melt = store.db["melts"].get(unit["melt_batch_id"])
    if melt is not None:
        melt["returns_credit_lbs"] = calc.D(melt["returns_credit_lbs"]) + calc.returns_credit_for_unit(
            unit["pour_weight_oz"]
        )
