"""Row -> JSON. Derived fields are recomputed here, so every read is fresh."""
from decimal import Decimal

import calc
from store import db
from util import fmt_dt


def num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(row):
    return {
        "id": row["id"],
        "created_at": fmt_dt(row["created_at"]),
        "updated_at": fmt_dt(row["updated_at"]),
        "version": row["version"],
    }


def plant_json(plant):
    out = _common(plant)
    exceeded = calc.exceeded_pollutants(plant)
    out.update({
        "name": plant["name"],
        "site_code": plant["site_code"],
        "permit_limit_tons_30d": num(plant["permit_limit_tons_30d"]),
        "spot_gas_index_usd_per_mmbtu": num(plant["spot_gas_index_usd_per_mmbtu"]),
        "gas_index_updated_at": fmt_dt(plant["gas_index_updated_at"]),
        "hedged_blend_usd_per_mmbtu": num(calc.hedged_blend(plant)),
        "permit_status": plant["permit_status"],
        "psm_program_status": plant["psm_program_status"],
        "operating_posture": calc.operating_posture(plant, exceeded),
        "exceeded_pollutants": exceeded,
        "last_vessel_inspection_at": fmt_dt(plant["last_vessel_inspection_at"]),
    })
    return out


def train_json(train):
    out = _common(train)
    charge = calc.active_charge(train["id"])
    out.update({
        "plant_id": train["plant_id"],
        "train_code": train["train_code"],
        "rated_ammonia_tpd": num(train["rated_ammonia_tpd"]),
        "status": train["status"],
        "active_charge_id": charge["id"] if charge else None,
    })
    return out


def charge_json(charge):
    out = _common(charge)
    cumulative, calendar, activity = calc.activity_figures(charge)
    out.update({
        "train_id": charge["train_id"],
        "charge_code": charge["charge_code"],
        "design_life_hours": num(charge["design_life_hours"]),
        "baseline_operating_hours": num(charge["baseline_operating_hours"]),
        "poisoning_index": num(charge["poisoning_index"]),
        "regeneration_count": charge["regeneration_count"],
        "installed_at": fmt_dt(charge["installed_at"]),
        "cumulative_operating_hours": num(cumulative),
        "calendar_activity_pct": num(calendar),
        "activity_pct": num(activity),
        "status": charge["status"],
    })
    return out


def lot_json(lot):
    out = _common(lot)
    out.update({
        "plant_id": lot["plant_id"],
        "lot_code": lot["lot_code"],
        "mmbtu_volume": num(lot["mmbtu_volume"]),
        "strike_price_usd_per_mmbtu": num(lot["strike_price_usd_per_mmbtu"]),
        "delivery_month": lot["delivery_month"],
        "consumed_mmbtu": num(lot["consumed_mmbtu"]),
        "remaining_mmbtu": num(calc.remaining_mmbtu(lot)),
        "status": lot["status"],
    })
    return out


def line_json(line):
    return {
        "id": line["id"],
        "created_at": fmt_dt(line["created_at"]),
        "plant_id": line["plant_id"],
        "product_code": line["product_code"],
        "ammonia_tons_per_product_ton": num(line["ammonia_tons_per_product_ton"]),
        "conversion_cost_usd_per_ton": num(line["conversion_cost_usd_per_ton"]),
        "regulated": line["regulated"],
        "priority_rank": line["priority_rank"],
    }


def run_json(run):
    out = _common(run)
    out.update({
        "train_id": run["train_id"],
        "catalyst_charge_id": run["catalyst_charge_id"],
        "run_code": run["run_code"],
        "window_start": fmt_dt(run["window_start"]),
        "window_end": fmt_dt(run["window_end"]),
        "target_ammonia_tons": num(run["target_ammonia_tons"]),
        "actual_ammonia_tons": num(run["actual_ammonia_tons"]),
        "actual_operating_hours": num(run["actual_operating_hours"]),
        "consumed_gas_mmbtu": num(run["consumed_gas_mmbtu"]),
        "provisional_unit_cost_usd_per_ton": num(run["provisional_unit_cost_usd_per_ton"]),
        "final_unit_cost_usd_per_ton": num(run["final_unit_cost_usd_per_ton"]),
        "unallocated_ammonia_tons": num(calc.unallocated_ammonia_tons(run)),
        "status": run["status"],
        "abort_reason": run["abort_reason"],
        "reopen_reason": run["reopen_reason"],
        "created_by_user_id": run["created_by_user_id"],
    })
    return out


def order_json(order):
    out = _common(order)
    out.update({
        "run_id": order["run_id"],
        "product_line_id": order["product_line_id"],
        "destination_asset_id": order["destination_asset_id"],
        "order_code": order["order_code"],
        "requested_tons": num(order["requested_tons"]),
        "reserved_tons": num(order["reserved_tons"]),
        "allocated_ammonia_tons": num(order["allocated_ammonia_tons"]),
        "produced_tons": num(order["produced_tons"]),
        "landed_cost_usd": num(order["landed_cost_usd"]),
        "allocation_status": order["allocation_status"],
        "security_status": order["security_status"],
        "release_reason": order["release_reason"],
        "created_by_user_id": order["created_by_user_id"],
        "security_checked_by_user_id": order["security_checked_by_user_id"],
    })
    return out


def asset_json(asset):
    out = _common(asset)
    position = calc.storage_position(asset)
    out.update({
        "plant_id": asset["plant_id"],
        "asset_code": asset["asset_code"],
        "asset_kind": asset["asset_kind"],
        "product_code": asset["product_code"],
        "capacity_tons": num(asset["capacity_tons"]),
        "security_class": asset["security_class"],
        "seasonal_reserve_pct": num(asset["seasonal_reserve_pct"]),
        "opening_balance_tons": num(asset["opening_balance_tons"]),
        "on_hand_tons": num(position["on_hand_tons"]),
        "reserved_tons": num(position["reserved_tons"]),
        "seasonal_reserve_tons": num(position["seasonal_reserve_tons"]),
        "available_tons": num(position["available_tons"]),
    })
    return out


def shipment_json(ship):
    out = _common(ship)
    out.update({
        "origin_asset_id": ship["origin_asset_id"],
        "dest_asset_id": ship["dest_asset_id"],
        "production_order_id": ship["production_order_id"],
        "shipment_code": ship["shipment_code"],
        "mode": ship["mode"],
        "tons": num(ship["tons"]),
        "distance_miles": num(ship["distance_miles"]),
        "window_start": fmt_dt(ship["window_start"]),
        "window_end": fmt_dt(ship["window_end"]),
        "base_freight_usd": num(ship["base_freight_usd"]),
        "fuel_surcharge_usd": num(ship["fuel_surcharge_usd"]),
        "freight_total_usd": num(ship["freight_total_usd"]),
        "freight_per_ton_usd": num(ship["freight_per_ton_usd"]),
        "received_tons": num(ship["received_tons"]),
        "status": ship["status"],
        "cancel_reason": ship["cancel_reason"],
    })
    return out


def quote_json(quote):
    out = _common(quote)
    out.update({
        "plant_id": quote["plant_id"],
        "product_line_id": quote["product_line_id"],
        "quote_code": quote["quote_code"],
        "tons": num(quote["tons"]),
        "pass_through_basis": quote["pass_through_basis"],
        "expires_at": fmt_dt(quote["expires_at"]),
        "gas_basis_usd_per_mmbtu": num(quote["gas_basis_usd_per_mmbtu"]),
        "quoted_price_usd_per_ton": num(quote["quoted_price_usd_per_ton"]),
        "issued_at": fmt_dt(quote["issued_at"]),
        "status": quote["status"],
        "withdraw_reason": quote["withdraw_reason"],
    })
    return out


def turnaround_json(turnaround):
    out = _common(turnaround)
    _, critical = calc.task_schedule(turnaround["id"])
    total, done = calc.turnaround_counters(turnaround["id"])
    out.update({
        "plant_id": turnaround["plant_id"],
        "train_id": turnaround["train_id"],
        "turnaround_code": turnaround["turnaround_code"],
        "scope": turnaround["scope"],
        "window_start": fmt_dt(turnaround["window_start"]),
        "window_end": fmt_dt(turnaround["window_end"]),
        "window_days": turnaround["window_days"],
        "critical_path_days": critical,
        "tasks_total_count": total,
        "tasks_done_count": done,
        "authored_by_user_id": turnaround["authored_by_user_id"],
        "psm_review_decision": turnaround["psm_review_decision"],
        "psm_reviewed_by_user_id": turnaround["psm_reviewed_by_user_id"],
        "psm_findings_count": turnaround["psm_findings_count"],
        "approved_by_user_id": turnaround["approved_by_user_id"],
        "status": turnaround["status"],
        "rejection_reason": turnaround["rejection_reason"],
    })
    return out


def task_json(task):
    out = _common(task)
    esd, _ = calc.task_schedule(task["turnaround_id"])
    out.update({
        "turnaround_id": task["turnaround_id"],
        "predecessor_task_id": task["predecessor_task_id"],
        "task_code": task["task_code"],
        "duration_days": task["duration_days"],
        "earliest_start_day": esd.get(task["id"], 0),
        "status": task["status"],
    })
    return out


def reading_json(reading):
    return {
        "id": reading["id"],
        "created_at": fmt_dt(reading["created_at"]),
        "plant_id": reading["plant_id"],
        "pollutant": reading["pollutant"],
        "rate_lb_per_hour": num(reading["rate_lb_per_hour"]),
        "interval_hours": num(reading["interval_hours"]),
        "reading_at": fmt_dt(reading["reading_at"]),
        "tons": num(reading["tons"]),
        "rolling_30d_tons": num(reading["rolling_30d_tons"]),
        "exceedance": reading["exceedance"],
    }


SERIALIZERS = {
    "plants": plant_json,
    "trains": train_json,
    "charges": charge_json,
    "lots": lot_json,
    "lines": line_json,
    "runs": run_json,
    "orders": order_json,
    "assets": asset_json,
    "shipments": shipment_json,
    "quotes": quote_json,
    "turnarounds": turnaround_json,
    "tasks": task_json,
    "readings": reading_json,
}


def dump(family, rows):
    fn = SERIALIZERS[family]
    return [fn(row) for row in rows]


def one(family, row):
    return SERIALIZERS[family](row)


def clock_json():
    return {"current_utc": fmt_dt(db.clock)}
