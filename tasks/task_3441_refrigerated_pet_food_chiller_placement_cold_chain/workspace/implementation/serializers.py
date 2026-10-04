"""Entity -> JSON serializers. Field sets follow scaffold entities exactly.
created_at/updated_at use 3-fractional-digit format (PRD 2.5); business
datetimes echo in plain-seconds-or-ms form. TemperatureReading has no
updated_at/version (append-only, PRD 2.5).
"""
import calc
from state import fmt_dt, fmt_dt_ms


def _common(e):
    return {
        "created_at": fmt_dt_ms(e["created_at"]),
        "updated_at": fmt_dt_ms(e["updated_at"]),
        "version": e["version"],
    }


def ser_store(s):
    out = {
        "id": s["id"], "name": s["name"], "region": s["region"],
        "demographic_index": s["demographic_index"],
        "weekly_category_velocity_index": s["weekly_category_velocity_index"],
        "competitor_density_index": s["competitor_density_index"],
        "available_sqft": s["available_sqft"],
        "distance_miles_from_plant": s["distance_miles_from_plant"],
    }
    out.update(_common(s))
    return out


def ser_evaluation(e):
    out = {
        "id": e["id"], "store_id": e["store_id"],
        "model_variant": e["model_variant"], "chiller_model": e["chiller_model"],
        "forecast_weekly_units": e["forecast_weekly_units"],
        "allocated_sqft": e["allocated_sqft"],
        "footprint_score": e["footprint_score"],
        "composite_score": e["composite_score"],
        "install_quote_cents": e["install_quote_cents"],
        "payback_months": e["payback_months"],
        "verdict": e["verdict"],
    }
    out.update(_common(e))
    return out


def ser_agreement(a):
    out = {
        "id": a["id"], "store_id": a["store_id"],
        "allocated_sqft": a["allocated_sqft"],
        "max_capex_cents": a["max_capex_cents"],
        "term_months": a["term_months"],
        "status": a["status"],
        "signed_at": fmt_dt(a["signed_at"]),
        "terminated_at": fmt_dt(a["terminated_at"]),
    }
    out.update(_common(a))
    return out


def ser_chiller(c):
    out = {
        "id": c["id"], "model": c["model"], "serial_no": c["serial_no"],
        "capacity_units": c["capacity_units"],
        "footprint_sqft": c["footprint_sqft"],
        "status": c["status"],
        "excursion_minutes_24h": calc.excursion_minutes_24h(c),
        "last_repair_at": fmt_dt(c["last_repair_at"]),
    }
    out.update(_common(c))
    return out


def ser_placement(p):
    out = {
        "id": p["id"], "store_id": p["store_id"], "chiller_id": p["chiller_id"],
        "agreement_id": p["agreement_id"],
        "status": p["status"],
        "performance_status": p["performance_status"],
        "operational_status": p["operational_status"],
        "underperforming_streak": p["underperforming_streak"],
        "standing_deliveries_per_week": p["standing_deliveries_per_week"],
        "safety_stock_units": p["safety_stock_units"],
        "installed_quote_cents": p["installed_quote_cents"],
        "last_reported_weekly_units": p["last_reported_weekly_units"],
        "payback_actuals_months": p["payback_actuals_months"],
        "retired_reason": p["retired_reason"],
        "relocated_to_placement_id": p["relocated_to_placement_id"],
    }
    out.update(_common(p))
    return out


def ser_reading(r):
    return {
        "id": r["id"], "chiller_id": r["chiller_id"],
        "recorded_at": fmt_dt(r["recorded_at"]),
        "temp_c": r["temp_c"], "duration_minutes": r["duration_minutes"],
        "is_excursion": r["is_excursion"],
        "created_at": fmt_dt_ms(r["created_at"]),
    }


def ser_ticket(t):
    out = {
        "id": t["id"], "chiller_id": t["chiller_id"], "origin": t["origin"],
        "issue_summary": t["issue_summary"], "status": t["status"],
        "window_start": fmt_dt(t["window_start"]),
        "window_end": fmt_dt(t["window_end"]),
        "resolution_note": t["resolution_note"],
    }
    out.update(_common(t))
    return out


def ser_shipment(s):
    out = {
        "id": s["id"], "store_id": s["store_id"], "lot_id": s["lot_id"],
        "quantity_units": s["quantity_units"],
        "departed_at": fmt_dt(s["departed_at"]),
        "status": s["status"],
        "delivered_at": fmt_dt(s["delivered_at"]),
        "accepted_units": s["accepted_units"],
        "rejected_units": s["rejected_units"],
    }
    out.update(_common(s))
    return out


def ser_lot(l):
    out = {
        "id": l["id"], "sku": l["sku"],
        "produced_at": fmt_dt(l["produced_at"]),
        "quantity_units": l["quantity_units"], "status": l["status"],
        "expires_at": fmt_dt(l["expires_at"]),
        "unshipped_qty": l["unshipped_qty"],
        "in_transit_qty": l["in_transit_qty"],
        "in_store_qty": l["in_store_qty"],
        "removed_qty": l["removed_qty"],
        "spoiled_qty": l["spoiled_qty"],
        "conservation_invariant": l["conservation_invariant"],
    }
    out.update(_common(l))
    return out


def ser_position(p):
    out = {
        "id": p["id"], "store_id": p["store_id"], "lot_id": p["lot_id"],
        "qty_on_hand": p["qty_on_hand"],
        "expiry_date": fmt_dt(p["expiry_date"]),
        "status": p["status"],
        "removal_reason": p["removal_reason"],
    }
    out.update(_common(p))
    return out


def ser_project(p):
    out = {
        "id": p["id"], "name": p["name"],
        "capacity_delta_units": p["capacity_delta_units"],
        "status": p["status"], "sequence_no": p["sequence_no"],
        "created_by_user_id": p["created_by_user_id"],
    }
    out.update(_common(p))
    return out


def ser_campaign(c):
    out = {
        "id": c["id"], "store_id": c["store_id"], "name": c["name"],
        "start_date": fmt_dt(c["start_date"]),
        "end_date": fmt_dt(c["end_date"]),
        "status": c["status"],
    }
    out.update(_common(c))
    return out
