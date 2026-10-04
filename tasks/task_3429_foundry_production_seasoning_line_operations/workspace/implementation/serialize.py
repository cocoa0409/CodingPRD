"""Entity -> JSON-safe dict serializers. Computed fields are derived on read."""
from datetime import datetime, date
from decimal import Decimal

import calc
import domain
import store


def _num(v):
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    return v


def _dt(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return store.format_dt(v)
    if isinstance(v, date):
        return v.isoformat()
    return v


def _common(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def product(p):
    d = _common(p)
    d.update(
        {
            "sku_code": p["sku_code"],
            "name": p["name"],
            "category": p["category"],
            "target_weight_oz": _num(p["target_weight_oz"]),
            "weight_tolerance_oz": _num(p["weight_tolerance_oz"]),
            "target_diameter_in": _num(p["target_diameter_in"]),
            "diameter_tolerance_in": _num(p["diameter_tolerance_in"]),
            "min_wall_thickness_in": _num(p["min_wall_thickness_in"]),
            "wholesale_price_cents": p["wholesale_price_cents"],
            "msrp_cents": p["msrp_cents"],
            "import_landed_cost_cents": p["import_landed_cost_cents"],
            "peak_season_start_week": p["peak_season_start_week"],
            "peak_season_end_week": p["peak_season_end_week"],
            "status": p["status"],
        }
    )
    return d


def order(o):
    idx, tier, posture = domain.order_derived(o)
    material = domain.order_material_to_date_cents(o)
    d = _common(o)
    d.update(
        {
            "product_id": o["product_id"],
            "planned_quantity": o["planned_quantity"],
            "scheduled_week": o["scheduled_week"],
            "state": o["state"],
            "posture": posture,
            "scrap_tier": tier,
            "poured_units": o["poured_units"],
            "good_units": o["good_units"],
            "scrapped_units": o["scrapped_units"],
            "defect_scrapped_units": o["defect_scrapped_units"],
            "scrap_weighted_units": _num(calc.D(o["scrap_weighted_units"])),
            "scrap_index": _num(idx),
            "labor_hours_actual": _num(o["labor_hours_actual"]),
            "energy_kwh_actual": _num(o["energy_kwh_actual"]),
            "unit_cost_provisional_cents": calc.unit_cost_provisional(
                material, o["planned_quantity"]
            ),
            "unit_cost_final_cents": o["unit_cost_final_cents"],
            "margin_flag": o["margin_flag"],
        }
    )
    return d


def melt_batch(m):
    d = _common(m)
    d.update(
        {
            "production_order_id": m["production_order_id"],
            "furnace_id": m["furnace_id"],
            "planned_tap_start": _dt(m["planned_tap_start"]),
            "planned_tap_end": _dt(m["planned_tap_end"]),
            "planned_iron_lbs": _num(m["planned_iron_lbs"]),
            "planned_pig_iron_pct": _num(m["planned_pig_iron_pct"]),
            "planned_scrap_steel_pct": _num(m["planned_scrap_steel_pct"]),
            "planned_returns_pct": _num(m["planned_returns_pct"]),
            "planned_alloy_pct": _num(m["planned_alloy_pct"]),
            "state": m["state"],
            "state_before_hold": m["state_before_hold"],
            "adjustment_count": m["adjustment_count"],
            "pig_iron_lbs": _num(m["pig_iron_lbs"]),
            "scrap_steel_lbs": _num(m["scrap_steel_lbs"]),
            "returns_lbs": _num(m["returns_lbs"]),
            "alloy_lbs": _num(m["alloy_lbs"]),
            "planned_charge_cost_cents": m["planned_charge_cost_cents"],
            "actual_charge_cost_cents": m["actual_charge_cost_cents"],
            "carbon_pct": _num(m["carbon_pct"]),
            "silicon_pct": _num(m["silicon_pct"]),
            "manganese_pct": _num(m["manganese_pct"]),
            "sulfur_pct": _num(m["sulfur_pct"]),
            "phosphorus_pct": _num(m["phosphorus_pct"]),
            "bath_temp_f": _num(m["bath_temp_f"]),
            "carbon_equivalent": _num(m["carbon_equivalent"]),
            "chemistry_recorded_by": m["chemistry_recorded_by"],
            "certified_by": m["certified_by"],
            "tapped_temp_f": _num(m["tapped_temp_f"]),
            "tapped_lbs": _num(m["tapped_lbs"]),
            "slag_loss_lbs": _num(m["slag_loss_lbs"]),
            "poured_lbs": _num(m["poured_lbs"]),
            "remaining_iron_lbs": _num(m["remaining_iron_lbs"]),
            "returns_credit_lbs": _num(m["returns_credit_lbs"]),
        }
    )
    return d


def mold(m):
    d = _common(m)
    d.update(
        {
            "production_order_id": m["production_order_id"],
            "new_sand_pct": _num(m["new_sand_pct"]),
            "reclaimed_sand_pct": _num(m["reclaimed_sand_pct"]),
            "moisture_pct": _num(m["moisture_pct"]),
            "clay_pct": _num(m["clay_pct"]),
            "sand_weight_lbs": _num(m["sand_weight_lbs"]),
            "state": m["state"],
            "reclaimed_sand_lbs": _num(m["reclaimed_sand_lbs"]),
            "dust_collected_lbs": _num(m["dust_collected_lbs"]),
            "reclaim_loss_lbs": _num(m["reclaim_loss_lbs"]),
        }
    )
    return d


def casting_unit(u):
    d = _common(u)
    d.update(
        {
            "production_order_id": u["production_order_id"],
            "melt_batch_id": u["melt_batch_id"],
            "mold_id": u["mold_id"],
            "seasoning_batch_id": u["seasoning_batch_id"],
            "pour_weight_oz": _num(u["pour_weight_oz"]),
            "measured_weight_oz": _num(u["measured_weight_oz"]),
            "measured_diameter_in": _num(u["measured_diameter_in"]),
            "measured_wall_thickness_in": _num(u["measured_wall_thickness_in"]),
            "state": u["state"],
            "rework_count": u["rework_count"],
            "scrap_reason": u["scrap_reason"],
            "scrapped_after_rework": u["scrapped_after_rework"],
        }
    )
    return d


def defect_report(r):
    d = _common(r)
    d.update(
        {
            "casting_unit_id": r["casting_unit_id"],
            "defect_type": r["defect_type"],
            "severity": r["severity"],
            "status": r["status"],
            "disposition": r["disposition"],
            "dispositioned_by": r["dispositioned_by"],
            "notes": r["notes"],
        }
    )
    return d


def seasoning_batch(sb):
    d = _common(sb)
    d.update(
        {
            "production_order_id": sb["production_order_id"],
            "oil_type": sb["oil_type"],
            "coating_count": sb["coating_count"],
            "unit_ids": list(sb["unit_ids"]),
            "unit_count": sb["unit_count"],
            "planned_bake_start": _dt(sb["planned_bake_start"]),
            "planned_bake_end": _dt(sb["planned_bake_end"]),
            "oven_id": sb["oven_id"],
            "state": sb["state"],
            "actual_bake_temp_f": _num(sb["actual_bake_temp_f"]),
            "oil_lot_number": sb["oil_lot_number"],
            "coa_reference": sb["coa_reference"],
            "bake_recorded_by": sb["bake_recorded_by"],
            "bake_duration_min": sb["bake_duration_min"],
            "cure_score": sb["cure_score"],
            "food_safety_verified": sb["food_safety_verified"],
            "released_by": sb["released_by"],
        }
    )
    return d


def permit(p):
    d = _common(p)
    rate = domain.current_sand_rate() if p["permit_type"] == "SAND_RECLAMATION" else None
    d.update(
        {
            "permit_type": p["permit_type"],
            "limit_value": _num(p["limit_value"]),
            "measurement_unit": p["measurement_unit"],
            "compliance_period": p["compliance_period"],
            "status": p["status"],
            "over_limit_reading_count_current_period": p[
                "over_limit_reading_count_current_period"
            ],
            "current_sand_rate": _num(rate),
            "last_breach_reading_recorded_by": p["last_breach_reading_recorded_by"],
        }
    )
    return d


def emissions_reading(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "permit_id": r["permit_id"],
        "reading_value": _num(r["reading_value"]),
        "source": r["source"],
        "recorded_by": r["recorded_by"],
    }


def inventory_record(rec):
    d = _common(rec)
    d.update(
        {
            "product_id": rec["product_id"],
            "on_hand_units": rec["on_hand_units"],
            "reserved_units": rec["reserved_units"],
            "shipped_units": rec["shipped_units"],
            "outlet_sold_units": rec["outlet_sold_units"],
            "available_units": rec["on_hand_units"] - rec["reserved_units"],
        }
    )
    return d


def retail_allocation(a):
    d = _common(a)
    d.update(
        {
            "inventory_record_id": a["inventory_record_id"],
            "channel": a["channel"],
            "allocated_qty": a["allocated_qty"],
            "ship_week": _dt(a["ship_week"]),
            "status": a["status"],
            "confirmed_at": a["confirmed_at"],
        }
    )
    return d


def outlet_sale(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "product_id": s["product_id"],
        "channel": s["channel"],
        "qty": s["qty"],
        "unit_price_cents": s["unit_price_cents"],
        "floor_price_cents": s["floor_price_cents"],
        "recorded_by": s["recorded_by"],
    }
