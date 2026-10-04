"""Public serialization of stored records.

Applies lazy status evaluation on read (PRD SS2.5). OrderLine, Lot and
TrainingCertification are light resources: only id + created_at, no
updated_at and no version (PRD SS2.4).
"""
from domain import (incident_scope, late_pulls_30d, lazy_cert, lazy_lot,
                    lazy_territory, performance_scores, training_compliant)
from util import fmt_ts


def _common(r):
    return {
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def ser_distributor(d):
    prov, fin = performance_scores(d["id"])
    out = {
        "id": d["id"],
        "code": d["code"],
        "name": d["name"],
        "status": d["status"],
        "service_level_tier": d["service_level_tier"],
        "performance_score_provisional": prov,
        "performance_score_final": fin,
    }
    out.update(_common(d))
    return out


def ser_territory(t):
    lazy_territory(t)
    out = {
        "id": t["id"],
        "code": t["code"],
        "name": t["name"],
        "region": t["region"],
        "status": t["status"],
        "granted_distributor_id": t["granted_distributor_id"],
        "granted_at": fmt_ts(t["granted_at"]),
        "revoked_at": fmt_ts(t["revoked_at"]),
        "min_weekly_visits_per_account": t["min_weekly_visits_per_account"],
    }
    out.update(_common(t))
    return out


def ser_account(a):
    out = {
        "id": a["id"],
        "name": a["name"],
        "channel": a["channel"],
        "approval_status": a["approval_status"],
        "territory_id": a["territory_id"],
        "distributor_id": a["distributor_id"],
        "approved_at": fmt_ts(a["approved_at"]),
        "late_pulls_30d": late_pulls_30d(a["id"]),
        "training_compliant": training_compliant(a["id"]),
    }
    out.update(_common(a))
    return out


def ser_product(p):
    out = {
        "id": p["id"],
        "code": p["code"],
        "name": p["name"],
        "base_price_cents": p["base_price_cents"],
        "shelf_life_opened_hours": p["shelf_life_opened_hours"],
        "shelf_life_unopened_days": p["shelf_life_unopened_days"],
        "allergen_tags": list(p["allergen_tags"]),
        "requires_dedicated_slicer": p["requires_dedicated_slicer"],
        "channel_restricted": p["channel_restricted"],
        "status": p["status"],
    }
    out.update(_common(p))
    return out


def ser_authorization(a):
    out = {
        "id": a["id"],
        "account_id": a["account_id"],
        "product_id": a["product_id"],
        "status": a["status"],
        "suspension_source": a["suspension_source"],
    }
    out.update(_common(a))
    return out


def ser_order(o):
    out = {
        "id": o["id"],
        "distributor_id": o["distributor_id"],
        "delivery_week": o["delivery_week"],
        "allocation_status": o["allocation_status"],
        "fulfillment_status": o["fulfillment_status"],
        "merchandise_total_cents": o["merchandise_total_cents"],
        "discount_cents": o["discount_cents"],
        "delivery_fee_cents": o["delivery_fee_cents"],
        "total_cents": o["total_cents"],
    }
    out.update(_common(o))
    return out


def ser_order_line(l):
    # light resource: id + created_at only
    return {
        "id": l["id"],
        "order_id": l["order_id"],
        "product_id": l["product_id"],
        "qty_requested": l["qty_requested"],
        "qty_allocated": l["qty_allocated"],
        "unit_price_cents": l["unit_price_cents"],
        "line_total_cents": l["line_total_cents"],
        "created_at": fmt_ts(l["created_at"]),
    }


def ser_plant(p):
    out = {
        "id": p["id"],
        "code": p["code"],
        "name": p["name"],
        "status": p["status"],
    }
    out.update(_common(p))
    return out


def ser_run(r):
    out = {
        "id": r["id"],
        "plant_id": r["plant_id"],
        "line_code": r["line_code"],
        "product_id": r["product_id"],
        "window_start": fmt_ts(r["window_start"]),
        "window_end": fmt_ts(r["window_end"]),
        "capacity_units": r["capacity_units"],
        "planned_units": r["planned_units"],
        "actual_units": r["actual_units"],
        "waste_units": r["waste_units"],
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def ser_lot(lot):
    lazy_lot(lot)
    # light resource: id + created_at only
    return {
        "id": lot["id"],
        "production_run_id": lot["production_run_id"],
        "product_id": lot["product_id"],
        "available_units": lot["available_units"],
        "allocated_units": lot["allocated_units"],
        "delivered_units": lot["delivered_units"],
        "expires_at": fmt_ts(lot["expires_at"]),
        "status": lot["status"],
        "created_at": fmt_ts(lot["created_at"]),
    }


def ser_delivery(d):
    out = {
        "id": d["id"],
        "order_id": d["order_id"],
        "account_id": d["account_id"],
        "distributor_id": d["distributor_id"],
        "lines": [{"lot_id": line["lot_id"], "qty": line["qty"]} for line in d["lines"]],
        "status": d["status"],
        "confirmed_at": fmt_ts(d["confirmed_at"]),
    }
    out.update(_common(d))
    return out


def ser_visit(v):
    out = {
        "id": v["id"],
        "account_id": v["account_id"],
        "distributor_id": v["distributor_id"],
        "window_start": fmt_ts(v["window_start"]),
        "window_end": fmt_ts(v["window_end"]),
        "status": v["status"],
        "score": v["score"],
        "rotation_compliant": v["rotation_compliant"],
        "slicer_presentation_ok": v["slicer_presentation_ok"],
        "submitted_at": fmt_ts(v["submitted_at"]),
    }
    out.update(_common(v))
    return out


def ser_slicer(s):
    out = {
        "id": s["id"],
        "account_id": s["account_id"],
        "label": s["label"],
        "dedicated_allergen": s["dedicated_allergen"],
        "cleaning_verified_at": fmt_ts(s["cleaning_verified_at"]),
        "status": s["status"],
    }
    out.update(_common(s))
    return out


def ser_log(l):
    out = {
        "id": l["id"],
        "account_id": l["account_id"],
        "product_id": l["product_id"],
        "slicer_id": l["slicer_id"],
        "opened_at": fmt_ts(l["opened_at"]),
        "pull_deadline": fmt_ts(l["pull_deadline"]),
        "pulled_at": fmt_ts(l["pulled_at"]),
        "status": l["status"],
    }
    out.update(_common(l))
    return out


def ser_cert(c):
    lazy_cert(c)
    # light resource: id + created_at only
    return {
        "id": c["id"],
        "account_id": c["account_id"],
        "associate_name": c["associate_name"],
        "slicing_module_passed": c["slicing_module_passed"],
        "allergen_module_passed": c["allergen_module_passed"],
        "certified_at": fmt_ts(c["certified_at"]),
        "expires_at": fmt_ts(c["expires_at"]),
        "status": c["status"],
        "created_at": fmt_ts(c["created_at"]),
    }


def ser_promo(p):
    out = {
        "id": p["id"],
        "account_id": p["account_id"],
        "product_id": p["product_id"],
        "promo_price_cents": p["promo_price_cents"],
        "start_date": p["start_date"],
        "end_date": p["end_date"],
        "budget_cents": p["budget_cents"],
        "estimated_units": p["estimated_units"],
        "status": p["status"],
        "unit_allowance_cents": p["unit_allowance_cents"],
        "reserved_cents": p["reserved_cents"],
        "spent_cents": p["spent_cents"],
        "released_cents": p["released_cents"],
    }
    out.update(_common(p))
    return out


def ser_incident(i):
    out = {
        "id": i["id"],
        "plant_id": i["plant_id"],
        "title": i["title"],
        "severity": i["severity"],
        "affected_run_ids": list(i["affected_run_ids"]),
        "status": i["status"],
        "resolution_outcome": i["resolution_outcome"],
        "affected_account_count": incident_scope(i),
    }
    out.update(_common(i))
    return out
