"""Shared domain helpers: lookups, serializers, cascades."""

import db
import services.calculations as calc
from errors import not_found
from util import iso_out, touch


# ---------------- lookups ----------------

def get_supplier(sid):
    s = db.suppliers.get(sid)
    if s is None:
        raise not_found("Supplier not found: %s" % sid)
    return s


def get_audit(aid):
    a = db.audits.get(aid)
    if a is None:
        raise not_found("Audit not found: %s" % aid)
    return a


def get_commissary(cid):
    c = db.commissaries.get(cid)
    if c is None:
        raise not_found("Commissary not found: %s" % cid)
    return c


def get_truck(tid):
    t = db.trucks.get(tid)
    if t is None:
        raise not_found("Truck not found: %s" % tid)
    return t


def get_route(rid):
    r = db.routes.get(rid)
    if r is None:
        raise not_found("Route not found: %s" % rid)
    return r


def get_menu_item(mid):
    m = db.menu_items.get(mid)
    if m is None:
        raise not_found("Menu item not found: %s" % mid)
    return m


def get_store(sid):
    s = db.stores.get(sid)
    if s is None:
        raise not_found("Store not found: %s" % sid)
    return s


def get_batch(bid):
    b = db.batches.get(bid)
    if b is None:
        raise not_found("Batch not found: %s" % bid)
    return b


def get_order(oid):
    o = db.orders.get(oid)
    if o is None:
        raise not_found("Order not found: %s" % oid)
    return o


def get_associate(aid):
    a = db.associates.get(aid)
    if a is None:
        raise not_found("Associate not found: %s" % aid)
    return a


def get_posting(pid):
    p = db.postings.get(pid)
    if p is None:
        raise not_found("Manager posting not found: %s" % pid)
    return p


def get_application(aid):
    a = db.applications.get(aid)
    if a is None:
        raise not_found("Manager application not found: %s" % aid)
    return a


def get_shift(sid):
    s = db.shifts.get(sid)
    if s is None:
        raise not_found("Shift not found: %s" % sid)
    return s


def get_beef_delivery(did):
    d = db.beef_deliveries.get(did)
    if d is None:
        raise not_found("Beef delivery not found: %s" % did)
    return d


def get_production_run(rid):
    r = db.production_runs.get(rid)
    if r is None:
        raise not_found("Production run not found: %s" % rid)
    return r


# ---------------- serializers ----------------

def ser_supplier(s):
    return {
        "id": s["id"],
        "supplier_code": s["supplier_code"],
        "spec_profile": s["spec_profile"],
        "audit_frequency_days": s["audit_frequency_days"],
        # Lazily recomputed on read (PRD §2.4).
        "days_since_last_passed_audit": calc.days_since_last_passed_audit(s),
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_audit(a):
    return {
        "id": a["id"],
        "supplier_id": a["supplier_id"],
        "scheduled_date": iso_out(a["scheduled_date"]),
        "completed_at": iso_out(a["completed_at"]),
        "result": a["result"],
        "findings": a["findings"],
        "recorded_by_id": a["recorded_by_id"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_commissary(c):
    return {
        "id": c["id"],
        "name": c["name"],
        "lat": c["lat"],
        "lng": c["lng"],
        "radius_limit_km": c["radius_limit_km"],
        "daily_patty_capacity": c["daily_patty_capacity"],
        "daily_bun_capacity": c["daily_bun_capacity"],
        "daily_produce_capacity": c["daily_produce_capacity"],
        "raw_beef_lbs_on_hand": c["raw_beef_lbs_on_hand"],
        "delivery_days_mask": c["delivery_days_mask"],
        "regional_entry_open": c["regional_entry_open"],
        "supplier_id": c["supplier_id"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_truck(t):
    return {
        "id": t["id"],
        "commissary_id": t["commissary_id"],
        "plate": t["plate"],
        "route_type": t["route_type"],
        "cooler_capacity_cases": t["cooler_capacity_cases"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def ser_route(r):
    return {
        "id": r["id"],
        "commissary_id": r["commissary_id"],
        "truck_id": r["truck_id"],
        "service_date": iso_out(r["service_date"]),
        "store_ids": r["store_ids"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_menu_item(m):
    return {
        "id": m["id"],
        "sku": m["sku"],
        "name": m["name"],
        "base_price_cents": m["base_price_cents"],
        "patty_count": m["patty_count"],
        "produce_units": m["produce_units"],
        "active": m["active"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def ser_store(s):
    return {
        "id": s["id"],
        "commissary_id": s["commissary_id"],
        "name": s["name"],
        "lat": s["lat"],
        "lng": s["lng"],
        "distance_km": s["distance_km"],
        "opening_mode": s["opening_mode"],
        # Lazily recomputed on read (PRD §2.4).
        "surge_day_index": calc.surge_day_index(s),
        "surge_start_date": iso_out(s["surge_start_date"]),
        "surge_end_date": iso_out(s["surge_end_date"]),
        "manager_associate_id": s["manager_associate_id"],
        "staffing_posture": calc.staffing_posture(s["id"]),
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_batch(b):
    return {
        "id": b["id"],
        "store_id": b["store_id"],
        "commissary_id": b["commissary_id"],
        "production_run_id": b["production_run_id"],
        "route_id": b["route_id"],
        "delivery_date": iso_out(b["delivery_date"]),
        "patty_count": b["patty_count"],
        "bun_count": b["bun_count"],
        "produce_units": b["produce_units"],
        "cooler_cases_required": b["cooler_cases_required"],
        "gap_hours_at_load": b["gap_hours_at_load"],
        "delivered_at": iso_out(b.get("delivered_at")),
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def ser_order(o):
    return {
        "id": o["id"],
        "store_id": o["store_id"],
        "placed_by_associate_id": o["placed_by_associate_id"],
        "lines": o["lines"],
        "base_total_cents": o["base_total_cents"],
        "modifier_charge_cents": o["modifier_charge_cents"],
        "total_price_cents": o["total_price_cents"],
        "patties_reserved": o["patties_reserved"],
        "queue_position": o["queue_position"],
        "surge_pacing_minutes": o["surge_pacing_minutes"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def ser_associate(a):
    return {
        "id": a["id"],
        "full_name": a["full_name"],
        "hired_date": iso_out(a["hired_date"]),
        "home_store_id": a["home_store_id"],
        "current_level": a["current_level"],
        "hourly_wage_cents": a["hourly_wage_cents"],
        "promotion_count": a["promotion_count"],
        "active": a["active"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_posting(p):
    return {
        "id": p["id"],
        "store_id": p["store_id"],
        "posted_by_id": p["posted_by_id"],
        "status": p["status"],
        "filled_by_associate_id": p["filled_by_associate_id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_application(a):
    return {
        "id": a["id"],
        "posting_id": a["posting_id"],
        "candidate_associate_id": a["candidate_associate_id"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_shift(s):
    return {
        "id": s["id"],
        "store_id": s["store_id"],
        "associate_id": s["associate_id"],
        "shift_start": iso_out(s["shift_start"]),
        "shift_end": iso_out(s["shift_end"]),
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_beef_delivery(d):
    return {
        "id": d["id"],
        "commissary_id": d["commissary_id"],
        "supplier_id": d["supplier_id"],
        "shipped_at": iso_out(d["shipped_at"]),
        "raw_beef_lbs": d["raw_beef_lbs"],
        "transit_temp_celsius": d["transit_temp_celsius"],
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def ser_production_run(r):
    return {
        "id": r["id"],
        "commissary_id": r["commissary_id"],
        "run_date": iso_out(r["run_date"]),
        "patties_planned": r["patties_planned"],
        "buns_planned": r["buns_planned"],
        "produce_units_planned": r["produce_units_planned"],
        "beef_lbs_required": r["beef_lbs_required"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


# ---------------- cascades ----------------

def supplier_fail_suspension(supplier):
    """Pinned single-pass propagation: deliveries first (created_at ASC), then
    commissaries. In-flight deliveries are rejected for the supplier's
    OPERATIONAL commissaries (the ones being demoted); deliveries bound for
    non-operational commissaries are left for the receipt decision."""
    supplier["status"] = "SUSPENDED"
    touch(supplier)
    operational_ids = {
        c["id"] for c in db.commissaries.values()
        if c["supplier_id"] == supplier["id"] and c["status"] == "OPERATIONAL"
    }
    deliveries = [
        d for d in db.beef_deliveries.values()
        if d["supplier_id"] == supplier["id"]
        and d["status"] in ("SCHEDULED", "IN_TRANSIT")
        and d["commissary_id"] in operational_ids
    ]
    deliveries.sort(key=lambda d: d["created_at"])
    for d in deliveries:
        d["status"] = "REJECTED"
        touch(d)
    for c in db.commissaries.values():
        if c["id"] in operational_ids:
            c["status"] = "BUILDING"
            c["regional_entry_open"] = False
            touch(c)


def supplier_retire_cascade(supplier):
    """SCHEDULED deliveries -> CANCELLED; IN_TRANSIT left for receipt decision."""
    for d in db.beef_deliveries.values():
        if d["supplier_id"] == supplier["id"] and d["status"] == "SCHEDULED":
            d["status"] = "CANCELLED"
            touch(d)


def store_close_cascade(store):
    """PLANNED batches -> CANCELLED; DRAFT/FINALIZED routes listing the store ->
    CANCELLED; SCHEDULED shifts -> CANCELLED."""
    for b in db.batches.values():
        if b["store_id"] == store["id"] and b["status"] == "PLANNED":
            b["status"] = "CANCELLED"
            touch(b)
    for r in db.routes.values():
        if store["id"] in r["store_ids"] and r["status"] in ("DRAFT", "FINALIZED"):
            r["status"] = "CANCELLED"
            touch(r)
    for s in db.shifts.values():
        if s["store_id"] == store["id"] and s["status"] == "SCHEDULED":
            s["status"] = "CANCELLED"
            touch(s)


def commissary_decommission_cascade(commissary):
    """ACTIVE trucks -> INACTIVE; DRAFT routes -> CANCELLED (FINALIZED/COMPLETED
    untouched)."""
    for t in db.trucks.values():
        if t["commissary_id"] == commissary["id"] and t["status"] == "ACTIVE":
            t["status"] = "INACTIVE"
            touch(t)
    for r in db.routes.values():
        if r["commissary_id"] == commissary["id"] and r["status"] == "DRAFT":
            r["status"] = "CANCELLED"
            touch(r)


def has_surging_store(commissary_id):
    return any(
        s["commissary_id"] == commissary_id and s.get("opening_mode") == "OPENING_SURGE"
        for s in db.stores.values()
    )


def any_store_surging_in(store_ids):
    return any(
        db.stores.get(sid) is not None and db.stores[sid].get("opening_mode") == "OPENING_SURGE"
        for sid in store_ids
    )
