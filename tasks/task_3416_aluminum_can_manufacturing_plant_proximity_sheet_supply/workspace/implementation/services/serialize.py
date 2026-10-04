"""Entity serialization: public field projection plus read-time computed fields."""
from services import calc


def plant_public(p):
    scrap_ytd, metal_ytd = calc.plant_ytd(p)
    return {
        "id": p["id"],
        "name": p["name"],
        "region": p["region"],
        "warehouse_capacity_units": p["warehouse_capacity_units"],
        "warehouse_on_hand_units": p["warehouse_on_hand_units"],
        "projected_warehouse_units": calc.projected_warehouse_units(p),
        "posture": calc.plant_posture(p),
        "ops_run_index": p["ops_run_index"],
        "scrap_credit_lbs_ytd": float(scrap_ytd),
        "metal_consumed_lbs_ytd": float(metal_ytd),
        "recycled_content_pct": float(calc.recycled_content_pct(p)),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def customer_public(c):
    return {
        "id": c["id"],
        "name": c["name"],
        "home_region": c["home_region"],
        "filling_lines_count": c["filling_lines_count"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def agreement_public(a):
    rolling, lifetime = calc.agreement_accuracy(a["id"])
    return {
        "id": a["id"],
        "plant_id": a["plant_id"],
        "customer_id": a["customer_id"],
        "freight_zone": a["freight_zone"],
        "committed_annual_units": a["committed_annual_units"],
        "pass_through_pct": a["pass_through_pct"],
        "conversion_cost_cents_per_1000": a["conversion_cost_cents_per_1000"],
        "start_date": a["start_date"],
        "end_date": a["end_date"],
        "status": a["status"],
        "ytd_settled_units": a["ytd_settled_units"],
        "delivered_revenue_cents": a["delivered_revenue_cents"],
        "volume_tier": calc.volume_tier(a),
        "rolling_accuracy_pct": float(rolling),
        "lifetime_accuracy_pct": float(lifetime),
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def index_public(i):
    # Immutable after creation: no updated_at / version (PRD section 2.5).
    return {
        "id": i["id"],
        "period": i["period"],
        "index_cents_per_lb": i["index_cents_per_lb"],
        "created_at": i["created_at"],
    }


def line_public(l):
    return {
        "id": l["id"],
        "plant_id": l["plant_id"],
        "name": l["name"],
        "nominal_speed_cans_per_hour": l["nominal_speed_cans_per_hour"],
        "base_spoilage_pct": l["base_spoilage_pct"],
        "operational_status": l["operational_status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def format_public(f):
    return {
        "id": f["id"],
        "plant_id": f["plant_id"],
        "customer_id": f["customer_id"],
        "size_code": f["size_code"],
        "shape": f["shape"],
        "is_specialty": f["is_specialty"],
        "metal_lbs_per_1000_units": f["metal_lbs_per_1000_units"],
        "tooling_investment_cents": f["tooling_investment_cents"],
        "min_volume_commitment_units": f["min_volume_commitment_units"],
        "status": f["status"],
        "delivered_units": f["delivered_units"],
        "unamortized_exposure_cents": calc.format_unamortized_exposure(f),
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


_RUN_FIELDS = (
    "id", "agreement_id", "line_id", "format_id", "scheduled_qty", "graphics_code",
    "window_start", "window_end", "produced_qty", "spoiled_qty", "sheet_lbs_consumed",
    "effective_spoilage_pct", "spoilage_flag", "provisional_unit_price_cents_per_1000",
    "final_unit_price_cents_per_1000", "settled_amount_cents", "tier_delta_cents",
    "status", "created_at", "updated_at", "version",
)


def run_public(r):
    return {k: r[k] for k in _RUN_FIELDS}


def forecast_public(f):
    return {
        "id": f["id"],
        "agreement_id": f["agreement_id"],
        "period": f["period"],
        "forecast_qty": f["forecast_qty"],
        "actual_qty": f["actual_qty"],
        "accuracy_pct": f["accuracy_pct"],
        "status": f["status"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def scrap_public(s):
    return {
        "id": s["id"],
        "customer_id": s["customer_id"],
        "plant_id": s["plant_id"],
        "pickup_window_start": s["pickup_window_start"],
        "pickup_window_end": s["pickup_window_end"],
        "declared_weight_lbs": s["declared_weight_lbs"],
        "credited_weight_lbs": s["credited_weight_lbs"],
        "grade": s["grade"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def incident_public(i):
    return {
        "id": i["id"],
        "run_id": i["run_id"],
        "line_id": i["line_id"],
        "severity": i["severity"],
        "defect_class": i["defect_class"],
        "note": i["note"],
        "status": i["status"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }
