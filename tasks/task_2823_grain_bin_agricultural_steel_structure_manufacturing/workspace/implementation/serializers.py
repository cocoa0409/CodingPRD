"""Per-entity JSON projections. Every field traces to the PRD entity tables."""
from common import fmt_dt, num


def _audit(row, out):
    out["created_at"] = fmt_dt(row["created_at"])
    out["updated_at"] = fmt_dt(row["updated_at"])
    out["version"] = row["version"]
    return out


def jurisdiction(row):
    return {
        "id": row["id"],
        "code": row["code"],
        "name": row["name"],
        "seal_required": row["seal_required"],
        "min_design_wind_speed_mph": row["min_design_wind_speed_mph"],
        "seismic_design_category": row["seismic_design_category"],
        "permit_review_days": row["permit_review_days"],
        "created_at": fmt_dt(row["created_at"]),
    }


def grain_profile(row):
    return {
        "id": row["id"],
        "grain_code": row["grain_code"],
        "bulk_density_kg_per_m3": num(row["bulk_density_kg_per_m3"]),
        "janssen_k_ratio": num(row["janssen_k_ratio"]),
        "max_safe_moisture_pct": num(row["max_safe_moisture_pct"]),
        "aeration_cfm_per_m3_base": num(row["aeration_cfm_per_m3_base"]),
        "drying_multiplier": num(row["drying_multiplier"]),
        "created_at": fmt_dt(row["created_at"]),
    }


def coating_spec(row):
    return {
        "id": row["id"],
        "coating_code": row["coating_code"],
        "zinc_mass_g_per_m2": num(row["zinc_mass_g_per_m2"]),
        "corrosion_class": row["corrosion_class"],
        "coating_cost_per_kg_cents": row["coating_cost_per_kg_cents"],
        "changeover_minutes": row["changeover_minutes"],
        "max_ambient_moisture_pct": num(row["max_ambient_moisture_pct"]),
        "created_at": fmt_dt(row["created_at"]),
    }


def roll_forming_line(row):
    return {
        "id": row["id"],
        "line_code": row["line_code"],
        "max_gauge_mm": num(row["max_gauge_mm"]),
        "created_at": fmt_dt(row["created_at"]),
    }


def engineer(row):
    return _audit(
        row,
        {
            "id": row["id"],
            "name": row["name"],
            "license_number": row["license_number"],
            "licensed_jurisdiction_codes": list(row["licensed_jurisdiction_codes"]),
            "status": row["status"],
        },
    )


def dealer(row):
    return _audit(
        row,
        {
            "id": row["id"],
            "name": row["name"],
            "region_code": row["region_code"],
            "jurisdiction_id": row["jurisdiction_id"],
            "credit_limit_cents": row["credit_limit_cents"],
            "program_tier": row["program_tier"],
            "staging_slots": row["staging_slots"],
            "high_cube_access": row["high_cube_access"],
            "credit_committed_cents": row["credit_committed_cents"],
            "credit_available_cents": row["credit_available_cents"],
            "staged_kit_count": row["staged_kit_count"],
            "status": row["status"],
        },
    )


def bin_design(row):
    return _audit(
        row,
        {
            "id": row["id"],
            "dealer_id": row["dealer_id"],
            "jurisdiction_id": row["jurisdiction_id"],
            "grain_profile_id": row["grain_profile_id"],
            "coating_spec_id": row["coating_spec_id"],
            "author_engineer_id": row["author_engineer_id"],
            "sealed_by_engineer_id": row["sealed_by_engineer_id"],
            "diameter_m": num(row["diameter_m"]),
            "eave_height_m": num(row["eave_height_m"]),
            "roof_pitch_deg": row["roof_pitch_deg"],
            "design_wind_speed_mph": row["design_wind_speed_mph"],
            "moisture_pct": num(row["moisture_pct"]),
            "design_method": row["design_method"],
            "circumference_m": num(row["circumference_m"]),
            "sheets_per_course": row["sheets_per_course"],
            "sheet_courses": row["sheet_courses"],
            "sidewall_sheet_count": row["sidewall_sheet_count"],
            "roof_panel_count": row["roof_panel_count"],
            "capacity_m3": num(row["capacity_m3"]),
            "grain_lateral_kpa": num(row["grain_lateral_kpa"]),
            "moisture_factor": num(row["moisture_factor"]),
            "grain_demand_kpa": num(row["grain_demand_kpa"]),
            "wind_demand_kpa": num(row["wind_demand_kpa"]),
            "seismic_demand_kpa": num(row["seismic_demand_kpa"]),
            "governing_load_case": row["governing_load_case"],
            "governing_demand_kpa": num(row["governing_demand_kpa"]),
            "required_stiffener_count": row["required_stiffener_count"],
            "utilization_ratio": num(row["utilization_ratio"]),
            "sheet_gauge_mm": num(row["sheet_gauge_mm"]),
            "roof_ring_required": row["roof_ring_required"],
            "seal_required": row["seal_required"],
            "revision_round": row["revision_round"],
            "sealed_at": fmt_dt(row["sealed_at"]),
            "permit_ready_at": fmt_dt(row["permit_ready_at"]),
            "status": row["status"],
        },
    )


def design_analysis(row):
    return _audit(
        row,
        {
            "id": row["id"],
            "bin_design_id": row["bin_design_id"],
            "design_method": row["design_method"],
            "allowable_kpa_m": num(row["allowable_kpa_m"]),
            "governing_load_case": row["governing_load_case"],
            "governing_demand_kpa": num(row["governing_demand_kpa"]),
            "required_stiffener_count": row["required_stiffener_count"],
            "utilization_ratio": num(row["utilization_ratio"]),
            "verdict": row["verdict"],
            "analysis_index": row["analysis_index"],
            "superseded": row["superseded"],
        },
    )


def coil_lot(row):
    return _audit(
        row,
        {
            "id": row["id"],
            "coating_spec_id": row["coating_spec_id"],
            "heat_number": row["heat_number"],
            "gauge_mm": num(row["gauge_mm"]),
            "received_kg": num(row["received_kg"]),
            "reserved_kg": num(row["reserved_kg"]),
            "consumed_kg": num(row["consumed_kg"]),
            "scrap_kg": num(row["scrap_kg"]),
            "remaining_kg": num(row["remaining_kg"]),
            "status": row["status"],
        },
    )


def roll_forming_run(row):
    return _audit(
        row,
        {
            "id": row["id"],
            "roll_forming_line_id": row["roll_forming_line_id"],
            "coil_lot_id": row["coil_lot_id"],
            "dealer_order_id": row["dealer_order_id"],
            "window_start": fmt_dt(row["window_start"]),
            "window_end": fmt_dt(row["window_end"]),
            "planned_kg": num(row["planned_kg"]),
            "coating_code": row["coating_code"],
            "consumed_kg": num(row["consumed_kg"]),
            "scrap_kg": num(row["scrap_kg"]),
            "status": row["status"],
        },
    )


def dealer_order(row):
    return _audit(
        row,
        {
            "id": row["id"],
            "dealer_id": row["dealer_id"],
            "bin_design_id": row["bin_design_id"],
            "freight_load_id": row["freight_load_id"],
            "installation_crew_id": row["installation_crew_id"],
            "order_season": row["order_season"],
            "aeration_package": row["aeration_package"],
            "unload_system": row["unload_system"],
            "kit_subtotal_cents": row["kit_subtotal_cents"],
            "season_uplift_cents": row["season_uplift_cents"],
            "program_discount_cents": row["program_discount_cents"],
            "net_subtotal_cents": row["net_subtotal_cents"],
            "freight_surcharge_pct": num(row["freight_surcharge_pct"]),
            "freight_surcharge_cents": row["freight_surcharge_cents"],
            "total_cents": row["total_cents"],
            "required_deposit_cents": row["required_deposit_cents"],
            "credit_hold_cents": row["credit_hold_cents"],
            "deposit_paid_cents": row["deposit_paid_cents"],
            "kit_weight_kg": num(row["kit_weight_kg"]),
            "kit_cube_m3": num(row["kit_cube_m3"]),
            "grain_mass_kg": num(row["grain_mass_kg"]),
            "required_fan_cfm": row["required_fan_cfm"],
            "drying_hours_estimate": row["drying_hours_estimate"],
            "unload_rate_bph": row["unload_rate_bph"],
            "allocated_freight_cents": row["allocated_freight_cents"],
            "freight_sequence": row["freight_sequence"],
            "production_status": row["production_status"],
            "financial_status": row["financial_status"],
            "installation_readiness": row["installation_readiness"],
        },
    )


def kit_line(row):
    return {
        "id": row["id"],
        "dealer_order_id": row["dealer_order_id"],
        "component_code": row["component_code"],
        "quantity": row["quantity"],
        "unit_price_cents": row["unit_price_cents"],
        "extended_cents": row["extended_cents"],
        "weight_kg": num(row["weight_kg"]),
        "cube_m3": num(row["cube_m3"]),
        "created_at": fmt_dt(row["created_at"]),
    }


def freight_load(row):
    return _audit(
        row,
        {
            "id": row["id"],
            "dealer_id": row["dealer_id"],
            "trailer_type": row["trailer_type"],
            "allocation_basis": row["allocation_basis"],
            "yard_window_start": fmt_dt(row["yard_window_start"]),
            "yard_window_end": fmt_dt(row["yard_window_end"]),
            "max_cube_m3": num(row["max_cube_m3"]),
            "max_weight_kg": num(row["max_weight_kg"]),
            "assigned_cube_m3": num(row["assigned_cube_m3"]),
            "assigned_weight_kg": num(row["assigned_weight_kg"]),
            "cube_utilization_pct": num(row["cube_utilization_pct"]),
            "linehaul_cost_cents": row["linehaul_cost_cents"],
            "order_count": row["order_count"],
            "status": row["status"],
        },
    )


def installation_crew(row):
    return _audit(
        row,
        {
            "id": row["id"],
            "dealer_id": row["dealer_id"],
            "crew_name": row["crew_name"],
            "certification_tier": row["certification_tier"],
            "max_diameter_m": num(row["max_diameter_m"]),
            "certified_until": fmt_dt(row["certified_until"]),
            "status": row["status"],
        },
    )


def field_failure(row):
    return _audit(
        row,
        {
            "id": row["id"],
            "dealer_order_id": row["dealer_order_id"],
            "bin_design_id": row["bin_design_id"],
            "failure_mode": row["failure_mode"],
            "observed_load_kpa": num(row["observed_load_kpa"]),
            "measured_coating_loss_pct": num(row["measured_coating_loss_pct"]),
            "service_years": num(row["service_years"]),
            "structural_verdict": row["structural_verdict"],
            "corrosion_verdict": row["corrosion_verdict"],
            "determined_cause": row["determined_cause"],
            "status": row["status"],
        },
    )
