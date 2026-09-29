"""Serializers: one per entity, emitting exactly the fields PRD declares.

Fields whose source is a live aggregate (PRD 2.9, 2.10, 2.12, 3.7, 3.9) are
computed at read time so that every response reflects the current logical clock.
"""

from core import fmt_ts, get_row, rows
import calc


def ts(value):
    return fmt_ts(value) if value is not None else None


def _common(row, out):
    out["id"] = row["id"]
    out["created_at"] = ts(row["created_at"])
    if "updated_at" in row:
        out["updated_at"] = ts(row["updated_at"])
    if "version" in row:
        out["version"] = row["version"]
    return out


def plant_out(row):
    out = {
        "name": row["name"],
        "region_code": row["region_code"],
        "permit_nox_kg_per_tonne_clinker_cap": row["permit_nox_kg_per_tonne_clinker_cap"],
        "permit_annual_nox_budget_kg": row["permit_annual_nox_budget_kg"],
        "permit_nox_budget_remaining_kg": calc.nox_budget_remaining(row),
        "permit_max_tsr_pct": row["permit_max_tsr_pct"],
        "permit_max_chlorine_kg_per_run": row["permit_max_chlorine_kg_per_run"],
        "peak_season_months": row["peak_season_months"],
        "clinker_free_lime_max_pct": row["clinker_free_lime_max_pct"],
        "rolling_nox_intensity_kg_per_tonne": calc.rolling_nox_intensity(row),
        "cement_tonne_balance_tonnes": calc.cement_tonne_balance(row["id"]),
        "production_posture": calc.production_posture(row["id"]),
    }
    return _common(row, out)


def raw_material_out(row):
    out = {
        "code": row["code"],
        "category": row["category"],
        "cao_pct": row["cao_pct"],
        "sio2_pct": row["sio2_pct"],
        "al2o3_pct": row["al2o3_pct"],
        "fe2o3_pct": row["fe2o3_pct"],
        "so3_pct": row["so3_pct"],
        "moisture_pct": row["moisture_pct"],
        "cost_per_tonne": row["cost_per_tonne"],
        "is_alternative": row["is_alternative"],
        "max_substitution_pct": row["max_substitution_pct"],
    }
    return _common(row, out)


def fuel_out(row):
    out = {
        "code": row["code"],
        "category": row["category"],
        "lhv_gj_per_tonne": row["lhv_gj_per_tonne"],
        "nox_kg_per_gj": row["nox_kg_per_gj"],
        "co2_kg_per_gj": row["co2_kg_per_gj"],
        "chlorine_pct": row["chlorine_pct"],
        "is_alternative": row["is_alternative"],
    }
    return _common(row, out)


def customer_out(row):
    out = {
        "name": row["name"],
        "region_code": row["region_code"],
        "contract_state": row["contract_state"],
        "contract_priority": row["contract_priority"],
        "contract_monthly_tonnes": row["contract_monthly_tonnes"],
        "required_cement_type": row["required_cement_type"],
        "max_so3_pct": row["max_so3_pct"],
        "credit_hold": row["credit_hold"],
        "open_reserved_tonnes": calc.customer_open_reserved(row["id"]),
        "lifetime_loaded_tonnes": calc.customer_lifetime_loaded(row["id"]),
    }
    return _common(row, out)


def design_out(row):
    out = {
        "plant_id": row["plant_id"],
        "code": row["code"],
        "target_lsf": row["target_lsf"],
        "target_sm": row["target_sm"],
        "target_am": row["target_am"],
        "module_tolerance_lsf": row["module_tolerance_lsf"],
        "pile_lsf_tolerance": row["pile_lsf_tolerance"],
        "components": [
            {"raw_material_id": c["raw_material_id"],
             "mass_fraction_pct": c["mass_fraction_pct"]}
            for c in row["components"]
        ],
        "as_designed_cao_pct": row["as_designed_cao_pct"],
        "as_designed_sio2_pct": row["as_designed_sio2_pct"],
        "as_designed_al2o3_pct": row["as_designed_al2o3_pct"],
        "as_designed_fe2o3_pct": row["as_designed_fe2o3_pct"],
        "as_designed_lsf": row["as_designed_lsf"],
        "as_designed_sm": row["as_designed_sm"],
        "as_designed_am": row["as_designed_am"],
        "status": row["status"],
        "revision_count": row["revision_count"],
        "revision_reason": row["revision_reason"],
        "created_by_user_id": row["created_by_user_id"],
        "approved_by_user_id": row["approved_by_user_id"],
        "approved_at": ts(row["approved_at"]),
        "active_pile_count": calc.active_pile_count(row["id"]),
        "superseded_by_design_id": row["superseded_by_design_id"],
    }
    return _common(row, out)


def pile_out(row):
    out = {
        "plant_id": row["plant_id"],
        "raw_mix_design_id": row["raw_mix_design_id"],
        "pile_code": row["pile_code"],
        "additions": [
            {"raw_material_id": a["raw_material_id"],
             "tonnes_as_received": a["tonnes_as_received"],
             "moisture_pct": a["moisture_pct"],
             "added_at": ts(a["added_at"])}
            for a in row["additions"]
        ],
        "as_received_tonnes": row["as_received_tonnes"],
        "dry_tonnes": row["dry_tonnes"],
        "alt_raw_share_pct": row["alt_raw_share_pct"],
        "as_blended_cao_pct": row["as_blended_cao_pct"],
        "as_blended_sio2_pct": row["as_blended_sio2_pct"],
        "as_blended_al2o3_pct": row["as_blended_al2o3_pct"],
        "as_blended_fe2o3_pct": row["as_blended_fe2o3_pct"],
        "as_blended_lsf": row["as_blended_lsf"],
        "as_blended_sm": row["as_blended_sm"],
        "as_blended_am": row["as_blended_am"],
        "lsf_deviation": row["lsf_deviation"],
        "status": row["status"],
        "sealed_at": ts(row["sealed_at"]),
        "consumed_dry_tonnes": row["consumed_dry_tonnes"],
    }
    return _common(row, out)


def burn_test_out(row):
    out = {
        "plant_id": row["plant_id"],
        "fuel_id": row["fuel_id"],
        "requested_max_tsr_pct": row["requested_max_tsr_pct"],
        "valid_days": row["valid_days"],
        "status": row["status"],
        "measured_chlorine_pct": row["measured_chlorine_pct"],
        "measured_nox_kg_per_gj": row["measured_nox_kg_per_gj"],
        "stack_compliant": row["stack_compliant"],
        "result_recorded_by_user_id": row["result_recorded_by_user_id"],
        "adjudicated_by_user_id": row["adjudicated_by_user_id"],
        "authorized_max_tsr_pct": row["authorized_max_tsr_pct"],
        "valid_from": ts(row["valid_from"]),
        "valid_until": ts(row["valid_until"]),
        "decision_reason": row["decision_reason"],
    }
    return _common(row, out)


def kiln_out(row):
    out = {
        "plant_id": row["plant_id"],
        "code": row["code"],
        "nominal_shc_gj_per_tonne": row["nominal_shc_gj_per_tonne"],
        "cooldown_buffer_hours": row["cooldown_buffer_hours"],
        "reline_due_hours": row["reline_due_hours"],
        "refractory_hours_since_reline": row["refractory_hours_since_reline"],
        "availability_state": calc.kiln_availability_state(row),
    }
    return _common(row, out)


def run_out(row):
    plant = None
    kiln = get_row("kilns", row["kiln_id"])
    if kiln is not None:
        plant = get_row("plants", kiln["plant_id"])
    intensity, breach = calc.run_nox_intensity(row, plant)
    out = {
        "kiln_id": row["kiln_id"],
        "blended_pile_id": row["blended_pile_id"],
        "clinker_silo_id": row["clinker_silo_id"],
        "window_start": ts(row["window_start"]),
        "window_end": ts(row["window_end"]),
        "scheduled_hours": row["scheduled_hours"],
        "process_state": row["process_state"],
        "quality_state": row["quality_state"],
        "fuel_charges": [
            {"fuel_id": c["fuel_id"], "tonnes": c["tonnes"],
             "energy_gj": c["energy_gj"], "charged_at": ts(c["charged_at"])}
            for c in row["fuel_charges"]
        ],
        "gross_energy_gj": row["gross_energy_gj"],
        "provisional_clinker_tonnes": row["provisional_clinker_tonnes"],
        "effective_shc_gj_per_tonne": row["effective_shc_gj_per_tonne"],
        "clinker_tonnes": row["clinker_tonnes"],
        "tsr_pct": row["tsr_pct"],
        "nox_emitted_kg": row["nox_emitted_kg"],
        "chlorine_input_kg": row["chlorine_input_kg"],
        "nox_intensity_kg_per_tonne": intensity,
        "nox_intensity_breach": breach,
        "free_lime_pct": calc.run_free_lime_pct(row["id"]),
        "lit_at": ts(row["lit_at"]),
        "completed_at": ts(row["completed_at"]),
        "abort_reason": row["abort_reason"],
    }
    return _common(row, out)


def outage_out(row):
    out = {
        "kiln_id": row["kiln_id"],
        "window_start": ts(row["window_start"]),
        "window_end": ts(row["window_end"]),
        "scope": row["scope"],
        "peak_season_override": row["peak_season_override"],
        "demand_season_class": row["demand_season_class"],
        "status": row["status"],
        "refractory_replaced": row["refractory_replaced"],
        "approved_by_user_id": row["approved_by_user_id"],
        "started_at": ts(row["started_at"]),
        "completed_at": ts(row["completed_at"]),
    }
    return _common(row, out)


def silo_out(row):
    out = {
        "plant_id": row["plant_id"],
        "code": row["code"],
        "material_kind": row["material_kind"],
        "capacity_tonnes": row["capacity_tonnes"],
        "tonnes_on_hand": row["tonnes_on_hand"],
        "reserved_tonnes": row["reserved_tonnes"],
        "unreleased_tonnes": row["unreleased_tonnes"],
        "available_tonnes": calc.silo_available(row),
        "loadout_spouts": row["loadout_spouts"],
        "draw_rate_tonnes_per_hour": row["draw_rate_tonnes_per_hour"],
        "status": row["status"],
        "block_reason": row["block_reason"],
    }
    return _common(row, out)


def batch_out(row):
    out = {
        "plant_id": row["plant_id"],
        "clinker_silo_id": row["clinker_silo_id"],
        "cement_silo_id": row["cement_silo_id"],
        "cement_type": row["cement_type"],
        "clinker_tonnes_drawn": row["clinker_tonnes_drawn"],
        "gypsum_pct": row["gypsum_pct"],
        "limestone_pct": row["limestone_pct"],
        "blaine_target_m2_per_kg": row["blaine_target_m2_per_kg"],
        "total_batch_tonnes": row["total_batch_tonnes"],
        "gypsum_tonnes": row["gypsum_tonnes"],
        "limestone_tonnes": row["limestone_tonnes"],
        "cement_tonnes": row["cement_tonnes"],
        "so3_pct": row["so3_pct"],
        "status": row["status"],
        "strength_branch_state": row["strength_branch_state"],
        "fineness_branch_state": row["fineness_branch_state"],
        "feed_state": row["feed_state"],
        "certified_tonnes_allocated": calc.batch_certified_allocated(row),
        "rejection_reason": row["rejection_reason"],
        "grinding_started_at": ts(row["grinding_started_at"]),
        "ground_at": ts(row["ground_at"]),
        "qualified_at": ts(row["qualified_at"]),
    }
    return _common(row, out)


def lab_test_out(row):
    """PRD 2.4: a LabTest is immutable — no updated_at and no version at all."""
    return {
        "id": row["id"],
        "test_type": row["test_type"],
        "kiln_run_id": row["kiln_run_id"],
        "cement_batch_id": row["cement_batch_id"],
        "value": row["value"],
        "unit": row["unit"],
        "spec_min": row["spec_min"],
        "spec_max": row["spec_max"],
        "in_spec": row["in_spec"],
        "recorded_by_user_id": row["recorded_by_user_id"],
        "created_at": ts(row["created_at"]),
    }


def certificate_out(row):
    out = {
        "cement_batch_id": row["cement_batch_id"],
        "customer_id": row["customer_id"],
        "certified_tonnes": row["certified_tonnes"],
        "status": row["status"],
        "certified_blaine_m2_per_kg": row["certified_blaine_m2_per_kg"],
        "certified_strength_mpa": row["certified_strength_mpa"],
        "certified_so3_pct": row["certified_so3_pct"],
        "allocated_tonnes": calc.certificate_allocated(row["id"]),
        "issued_by_user_id": row["issued_by_user_id"],
        "issued_at": ts(row["issued_at"]),
        "revoke_reason": row["revoke_reason"],
        "revoked_at": ts(row["revoked_at"]),
    }
    return _common(row, out)


def order_out(row):
    out = {
        "customer_id": row["customer_id"],
        "cement_silo_id": row["cement_silo_id"],
        "mill_certificate_id": row["mill_certificate_id"],
        "window_start": ts(row["window_start"]),
        "window_end": ts(row["window_end"]),
        "scheduled_hours": row["scheduled_hours"],
        "tonnes": row["tonnes"],
        "loaded_tonnes": row["loaded_tonnes"],
        "status": row["status"],
        "void_reason": row["void_reason"],
        "loading_started_at": ts(row["loading_started_at"]),
        "completed_at": ts(row["completed_at"]),
    }
    return _common(row, out)


SERIALIZERS = {
    "plants": plant_out,
    "raw_materials": raw_material_out,
    "fuels": fuel_out,
    "customers": customer_out,
    "designs": design_out,
    "piles": pile_out,
    "burn_tests": burn_test_out,
    "kilns": kiln_out,
    "kiln_runs": run_out,
    "outages": outage_out,
    "silos": silo_out,
    "batches": batch_out,
    "lab_tests": lab_test_out,
    "certificates": certificate_out,
    "orders": order_out,
}
