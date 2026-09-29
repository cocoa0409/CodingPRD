"""Entity representations (SCAFFOLD entities + PRD 2.4 common fields)."""
from util import iso
from services import calc


def _common(row):
    return {
        "id": row["id"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def season(row):
    out = _common(row)
    out.update({
        "season_label": row["season_label"],
        "base_depth_policy": row["base_depth_policy"],
        "water_right_seasonal_af": row["water_right_seasonal_af"],
        "plant_max_gpm": row["plant_max_gpm"],
        "snowmaking_kwh_per_af": row["snowmaking_kwh_per_af"],
        "min_patrollers_per_open_area": row["min_patrollers_per_open_area"],
        "groom_freshness_hours": row["groom_freshness_hours"],
        "energy_windows": [dict(w) for w in row["energy_windows"]],
        "season_state": row["season_state"],
        "water_reserved_af": row["water_reserved_af"],
        "water_used_af": row["water_used_af"],
        "snow_produced_swe_af": row["snow_produced_swe_af"],
        "open_area_count": row["open_area_count"],
    })
    return out


def lift(row):
    out = _common(row)
    out.update({
        "season_id": row["season_id"],
        "lift_code": row["lift_code"],
        "name": row["name"],
        "lift_type": row["lift_type"],
        "wind_hold_threshold_mph": row["wind_hold_threshold_mph"],
        "hourly_capacity_pph": row["hourly_capacity_pph"],
        "required_operator_count": row["required_operator_count"],
        "service_status": row["service_status"],
        "mechanical_status": row["mechanical_status"],
        "last_inspection_at": iso(row["last_inspection_at"]),
        "last_inspection_result": row["last_inspection_result"],
        "inspection_valid_until": iso(row["inspection_valid_until"]),
        "staffed_operator_count": calc.staffed_operator_count(row),
        "wind_hold_since": iso(row["wind_hold_since"]),
    })
    return out


def staff_assignment(row):
    out = _common(row)
    out.update({
        "lift_id": row["lift_id"],
        "operator_code": row["operator_code"],
        "role_on_lift": row["role_on_lift"],
        "shift_start": iso(row["shift_start"]),
        "shift_end": iso(row["shift_end"]),
        "state": row["state"],
        "released_at": iso(row["released_at"]),
    })
    return out


def terrain_area(row):
    depth, stake_count = calc.terrain_base_depth(row)
    out = _common(row)
    out.update({
        "season_id": row["season_id"],
        "serving_lift_id": row["serving_lift_id"],
        "trail_code": row["trail_code"],
        "name": row["name"],
        "terrain_class": row["terrain_class"],
        "acres": row["acres"],
        "min_open_base_depth_in": row["min_open_base_depth_in"],
        "avalanche_terrain": row["avalanche_terrain"],
        "opening_state": row["opening_state"],
        "park_state": row["park_state"],
        "park_feature_count": row["park_feature_count"],
        "park_risk_score": row["park_risk_score"],
        "park_built_by_user_id": row["park_built_by_user_id"],
        "park_inspected_by_user_id": row["park_inspected_by_user_id"],
        "base_depth_in": depth,
        "base_depth_stake_count": stake_count,
        "last_groomed_at": iso(row["last_groomed_at"]),
        "groom_coverage_pct": row["groom_coverage_pct"],
        "groom_ready": calc.groom_is_current(row),
        "mitigation_clearance_expires_at": iso(row["mitigation_clearance_expires_at"]),
        "assigned_patroller_count": calc.assigned_patroller_count(row),
        "machine_swe_af": row["machine_swe_af"],
    })
    return out


def snow_depth_reading(row):
    return {
        "id": row["id"],
        "terrain_area_id": row["terrain_area_id"],
        "stake_code": row["stake_code"],
        "depth_in": row["depth_in"],
        "density_pct": row["density_pct"],
        "measured_at": iso(row["measured_at"]),
        "source": row["source"],
        "created_at": iso(row["created_at"]),
    }


def pump_house(row):
    out = _common(row)
    out.update({
        "season_id": row["season_id"],
        "pump_house_code": row["pump_house_code"],
        "name": row["name"],
        "max_gpm": row["max_gpm"],
        "gun_count": row["gun_count"],
        "status": row["status"],
        "peak_committed_gpm": row["peak_committed_gpm"],
        "active_session_count": row["active_session_count"],
    })
    return out


def session(row):
    out = _common(row)
    out.update({
        "terrain_area_id": row["terrain_area_id"],
        "pump_house_id": row["pump_house_id"],
        "window_start": iso(row["window_start"]),
        "window_end": iso(row["window_end"]),
        "planned_minutes": row["planned_minutes"],
        "gun_count": row["gun_count"],
        "gpm": row["gpm"],
        "state": row["state"],
        "wet_bulb_f": row["wet_bulb_f"],
        "started_at": iso(row["started_at"]),
        "last_running_since": iso(row["last_running_since"]),
        "ended_at": iso(row["ended_at"]),
        "accumulated_run_minutes": row["accumulated_run_minutes"],
        "water_af_reserved": row["water_af_reserved"],
        "water_af_actual": row["water_af_actual"],
        "snow_yield_factor": row["snow_yield_factor"],
        "snow_swe_af": row["snow_swe_af"],
        "energy_kwh": row["energy_kwh"],
        "energy_cost_usd": row["energy_cost_usd"],
        "demand_surcharge_applied": row["demand_surcharge_applied"],
        "abort_reason": row["abort_reason"],
    })
    return out


def grooming_task(row):
    out = _common(row)
    out.update({
        "terrain_area_id": row["terrain_area_id"],
        "cat_route_code": row["cat_route_code"],
        "sequence_index": row["sequence_index"],
        "snowcat_unit_code": row["snowcat_unit_code"],
        "winch_required": row["winch_required"],
        "winch_anchor_code": row["winch_anchor_code"],
        "window_start": iso(row["window_start"]),
        "window_end": iso(row["window_end"]),
        "state": row["state"],
        "passes_completed": row["passes_completed"],
        "coverage_pct": row["coverage_pct"],
        "dispatched_at": iso(row["dispatched_at"]),
        "completed_at": iso(row["completed_at"]),
    })
    return out


def patroller(row):
    out = _common(row)
    out.update({
        "season_id": row["season_id"],
        "assigned_terrain_area_id": row["assigned_terrain_area_id"],
        "patroller_code": row["patroller_code"],
        "full_name": row["full_name"],
        "cert_level": row["cert_level"],
        "blaster_certified": row["blaster_certified"],
        "on_duty": row["on_duty"],
        "status": row["status"],
    })
    return out


def mission(row):
    out = _common(row)
    out.update({
        "terrain_area_id": row["terrain_area_id"],
        "executed_by_patroller_id": row["executed_by_patroller_id"],
        "cleared_by_patroller_id": row["cleared_by_patroller_id"],
        "route_code": row["route_code"],
        "method": row["method"],
        "planned_charges": row["planned_charges"],
        "hazard_rating_pre": row["hazard_rating_pre"],
        "hazard_rating_post": row["hazard_rating_post"],
        "state": row["state"],
        "charges_used": row["charges_used"],
        "clearance_valid_hours": row["clearance_valid_hours"],
        "road_closure_minutes": row["road_closure_minutes"],
        "executed_at": iso(row["executed_at"]),
        "cleared_at": iso(row["cleared_at"]),
    })
    return out


def incident(row):
    out = _common(row)
    out.update({
        "terrain_area_id": row["terrain_area_id"],
        "responder_patroller_id": row["responder_patroller_id"],
        "reporter_code": row["reporter_code"],
        "severity": row["severity"],
        "location_note": row["location_note"],
        "state": row["state"],
        "transport_mode": row["transport_mode"],
        "disposition": row["disposition"],
        "reported_at": iso(row["reported_at"]),
        "dispatched_at": iso(row["dispatched_at"]),
        "transport_ordered_at": iso(row["transport_ordered_at"]),
        "closed_at": iso(row["closed_at"]),
        "response_minutes": row["response_minutes"],
    })
    return out


def day_plan(row):
    out = _common(row)
    out.update({
        "season_id": row["season_id"],
        "operating_date": row["operating_date"],
        "parking_stalls_total": row["parking_stalls_total"],
        "posture": row["posture"],
        "wind_speed_mph": row["wind_speed_mph"],
        "wet_bulb_f": row["wet_bulb_f"],
        "new_snow_in": row["new_snow_in"],
        "open_terrain_count": row["open_terrain_count"],
        "terrain_open_acres": row["terrain_open_acres"],
        "open_lift_capacity_pph": row["open_lift_capacity_pph"],
        "raw_ccc": row["raw_ccc"],
        "guest_capacity": row["guest_capacity"],
        "non_season_pool": row["non_season_pool"],
        "admitted_guest_count": row["admitted_guest_count"],
        "non_season_admitted_count": row["non_season_admitted_count"],
        "waitlisted_guest_count": row["waitlisted_guest_count"],
        "parking_stalls_used": row["parking_stalls_used"],
        "weather_updated_at": iso(row["weather_updated_at"]),
        "published_at": iso(row["published_at"]),
        "closed_at": iso(row["closed_at"]),
    })
    return out


def reservation(row):
    out = _common(row)
    out.update({
        "day_plan_id": row["day_plan_id"],
        "party_code": row["party_code"],
        "pass_type": row["pass_type"],
        "party_size": row["party_size"],
        "vehicle_count": row["vehicle_count"],
        "state": row["state"],
        "allocated_stalls": row["allocated_stalls"],
        "waitlist_reason": row["waitlist_reason"],
        "confirmed_at": iso(row["confirmed_at"]),
        "checked_in_at": iso(row["checked_in_at"]),
        "released_at": iso(row["released_at"]),
    })
    return out
