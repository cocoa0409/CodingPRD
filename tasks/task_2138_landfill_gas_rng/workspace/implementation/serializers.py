"""Entity -> JSON serialization."""

from decimal import Decimal

import store
from common import fmt_iso, month_in_quarter


def raw(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def site_out(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "state_code": row["state_code"],
        "host_royalty_pct": raw(row["host_royalty_pct"]),
        "royalty_variant": row["royalty_variant"],
        "royalty_floor_usd_per_mmbtu": raw(row["royalty_floor_usd_per_mmbtu"]),
        "permit_nmoc_limit_lb_per_hr": raw(row["permit_nmoc_limit_lb_per_hr"]),
        "design_collection_efficiency_pct": raw(row["design_collection_efficiency_pct"]),
        "collected_flow_scfm": raw(row["collected_flow_scfm"]),
        "collection_efficiency_pct": raw(row["collection_efficiency_pct"]),
        "energy_produced_mmbtu": raw(row["energy_produced_mmbtu"]),
        "energy_injected_mmbtu": raw(row["energy_injected_mmbtu"]),
        "energy_flared_mmbtu": raw(row["energy_flared_mmbtu"]),
        "energy_vented_mmbtu": raw(row["energy_vented_mmbtu"]),
        "rin_generated_total": row["rin_generated_total"],
        "rin_available_count": row["rin_available_count"],
        "rin_retired_count": row["rin_retired_count"],
        "rin_reversed_count": row["rin_reversed_count"],
        "royalty_payable_usd": raw(row["royalty_payable_usd"]),
        "compliance_posture": row["compliance_posture"],
        "created_at": fmt_iso(row["created_at"]),
        "updated_at": fmt_iso(row["updated_at"]),
        "version": row["version"],
    }


def well_out(row):
    return {
        "id": row["id"],
        "site_id": row["site_id"],
        "well_code": row["well_code"],
        "target_flow_scfm": raw(row["target_flow_scfm"]),
        "operating_state": row["operating_state"],
        "current_flow_scfm": raw(row["current_flow_scfm"]),
        "last_reading_flow_scfm": raw(row["last_reading_flow_scfm"]),
        "wellhead_vacuum_inhg": raw(row["wellhead_vacuum_inhg"]),
        "last_quality_class": row["last_quality_class"],
        "last_reading_at": fmt_iso(row["last_reading_at"]),
        "consecutive_good_readings": row["consecutive_good_readings"],
        "lockout_work_order_id": row["lockout_work_order_id"],
        "created_at": fmt_iso(row["created_at"]),
        "updated_at": fmt_iso(row["updated_at"]),
        "version": row["version"],
    }


def reading_out(row):
    return {
        "id": row["id"],
        "well_id": row["well_id"],
        "taken_at": fmt_iso(row["taken_at"]),
        "methane_pct": raw(row["methane_pct"]),
        "oxygen_pct": raw(row["oxygen_pct"]),
        "nitrogen_pct": raw(row["nitrogen_pct"]),
        "temperature_f": raw(row["temperature_f"]),
        "flow_scfm": raw(row["flow_scfm"]),
        "vacuum_inhg": raw(row["vacuum_inhg"]),
        "air_intrusion_index": raw(row["air_intrusion_index"]),
        "quality_class": row["quality_class"],
        "resulting_well_state": row["resulting_well_state"],
        "recorded_by_user_id": row["recorded_by_user_id"],
        "created_at": fmt_iso(row["created_at"]),
    }


def work_order_out(row):
    return {
        "id": row["id"],
        "well_id": row["well_id"],
        "work_type": row["work_type"],
        "window_start": fmt_iso(row["window_start"]),
        "window_end": fmt_iso(row["window_end"]),
        "lockout_buffer_minutes": row["lockout_buffer_minutes"],
        "status": row["status"],
        "actual_start_at": fmt_iso(row["actual_start_at"]),
        "actual_end_at": fmt_iso(row["actual_end_at"]),
        "condensate_gallons_removed": raw(row["condensate_gallons_removed"]),
        "created_at": fmt_iso(row["created_at"]),
        "updated_at": fmt_iso(row["updated_at"]),
        "version": row["version"],
    }


def haul_out(row):
    return {
        "id": row["id"],
        "work_order_id": row["work_order_id"],
        "gallons": raw(row["gallons"]),
        "disposal_manifest_no": row["disposal_manifest_no"],
        "hauled_at": fmt_iso(row["hauled_at"]),
        "is_hazardous": row["is_hazardous"],
        "created_at": fmt_iso(row["created_at"]),
    }


def plant_out(row):
    return {
        "id": row["id"],
        "site_id": row["site_id"],
        "plant_code": row["plant_code"],
        "receipt_point_code": row["receipt_point_code"],
        "receipt_point_mdq_dth_per_day": raw(row["receipt_point_mdq_dth_per_day"]),
        "min_feed_scfm": raw(row["min_feed_scfm"]),
        "spec_min_methane_pct": raw(row["spec_min_methane_pct"]),
        "spec_max_oxygen_pct": raw(row["spec_max_oxygen_pct"]),
        "spec_max_co2_pct": raw(row["spec_max_co2_pct"]),
        "process_mode": row["process_mode"],
        "spec_status": row["spec_status"],
        "availability_factor_pct": raw(row["availability_factor_pct"]),
        "downtime_minutes_mtd": raw(row["downtime_minutes_mtd"]),
        "flare_minutes_mtd": raw(row["flare_minutes_mtd"]),
        "created_at": fmt_iso(row["created_at"]),
        "updated_at": fmt_iso(row["updated_at"]),
        "version": row["version"],
    }


def downtime_out(row):
    return {
        "id": row["id"],
        "plant_id": row["plant_id"],
        "start_at": fmt_iso(row["start_at"]),
        "end_at": fmt_iso(row["end_at"]),
        "cause": row["cause"],
        "disposition": row["disposition"],
        "status": row["status"],
        "flared_mmbtu": raw(row["flared_mmbtu"]),
        "vented_mmbtu": raw(row["vented_mmbtu"]),
        "duration_minutes": raw(row["duration_minutes"]),
        "auto_generated": row["auto_generated"],
        "created_at": fmt_iso(row["created_at"]),
        "updated_at": fmt_iso(row["updated_at"]),
        "version": row["version"],
    }


def contract_out(row):
    return {
        "id": row["id"],
        "site_id": row["site_id"],
        "counterparty_name": row["counterparty_name"],
        "contract_mdq_dth_per_day": raw(row["contract_mdq_dth_per_day"]),
        "price_usd_per_dth": raw(row["price_usd_per_dth"]),
        "attribute_share_pct": raw(row["attribute_share_pct"]),
        "term_start": fmt_iso(row["term_start"]),
        "term_end": fmt_iso(row["term_end"]),
        "status": row["status"],
        "delivered_dth_mtd": raw(row["delivered_dth_mtd"]),
        "created_at": fmt_iso(row["created_at"]),
        "updated_at": fmt_iso(row["updated_at"]),
        "version": row["version"],
    }


def nomination_out(row):
    return {
        "id": row["id"],
        "contract_id": row["contract_id"],
        "plant_id": row["plant_id"],
        "gas_day_start": fmt_iso(row["gas_day_start"]),
        "gas_day_end": fmt_iso(row["gas_day_end"]),
        "nominated_dth": raw(row["nominated_dth"]),
        "hourly_rate_dth": raw(row["hourly_rate_dth"]),
        "status": row["status"],
        "committed_dth": raw(row["committed_dth"]),
        "delivered_dth": raw(row["delivered_dth"]),
        "curtail_reason": row["curtail_reason"],
        "created_at": fmt_iso(row["created_at"]),
        "updated_at": fmt_iso(row["updated_at"]),
        "version": row["version"],
    }


def batch_out(row):
    return {
        "id": row["id"],
        "plant_id": row["plant_id"],
        "nomination_id": row["nomination_id"],
        "interval_start": fmt_iso(row["interval_start"]),
        "interval_end": fmt_iso(row["interval_end"]),
        "hourly_volumes_mscf": [raw(v) for v in row["hourly_volumes_mscf"]],
        "methane_pct": raw(row["methane_pct"]),
        "oxygen_pct": raw(row["oxygen_pct"]),
        "co2_pct": raw(row["co2_pct"]),
        "gross_mmbtu": raw(row["gross_mmbtu"]),
        "metered_mmbtu": raw(row["metered_mmbtu"]),
        "status": row["status"],
        "spec_failure_reason": row["spec_failure_reason"],
        "void_reason": row["void_reason"],
        "created_at": fmt_iso(row["created_at"]),
        "updated_at": fmt_iso(row["updated_at"]),
        "version": row["version"],
    }


def attribute_out(row):
    return {
        "id": row["id"],
        "injection_batch_id": row["injection_batch_id"],
        "program": row["program"],
        "basis": row["basis"],
        "generation_period": row["generation_period"],
        "energy_basis_mmbtu": raw(row["energy_basis_mmbtu"]),
        "eligibility_factor": raw(row["eligibility_factor"]),
        "rin_count": row["rin_count"],
        "ci_project_gco2e_per_mj": raw(row["ci_project_gco2e_per_mj"]),
        "lcfs_credits": raw(row["lcfs_credits"]),
        "status": row["status"],
        "reversal_reason": row["reversal_reason"],
        "created_at": fmt_iso(row["created_at"]),
        "updated_at": fmt_iso(row["updated_at"]),
        "version": row["version"],
    }


def attached_attribute_batch_count(report):
    """AttributeBatch rows in this report's period, on this report's site,
    whose status is anything other than REVERSED."""
    count = 0
    for attribute in store.attribute_batches.values():
        if attribute["status"] == "REVERSED":
            continue
        if not month_in_quarter(attribute["generation_period"], report["period"]):
            continue
        batch = store.injection_batches.get(attribute["injection_batch_id"])
        if batch is None:
            continue
        plant = store.plants.get(batch["plant_id"])
        if plant is None or plant["site_id"] != report["site_id"]:
            continue
        count += 1
    return count


def report_out(row):
    return {
        "id": row["id"],
        "site_id": row["site_id"],
        "report_type": row["report_type"],
        "period": row["period"],
        "nmoc_lb_per_hr_reported": raw(row["nmoc_lb_per_hr_reported"]),
        "exceedance_flag": row["exceedance_flag"],
        "status": row["status"],
        "prepared_by_user_id": row["prepared_by_user_id"],
        "reviewed_by_user_id": row["reviewed_by_user_id"],
        "revision_count": row["revision_count"],
        "return_reason": row["return_reason"],
        "corrective_action_note": row["corrective_action_note"],
        "attached_attribute_batch_count": attached_attribute_batch_count(row),
        "created_at": fmt_iso(row["created_at"]),
        "updated_at": fmt_iso(row["updated_at"]),
        "version": row["version"],
    }


def statement_out(row):
    return {
        "id": row["id"],
        "site_id": row["site_id"],
        "period": row["period"],
        "allowed_deductions_usd": raw(row["allowed_deductions_usd"]),
        "variant_override": row["variant_override"],
        "variant_applied": row["variant_applied"],
        "billable_mmbtu": raw(row["billable_mmbtu"]),
        "gas_revenue_usd": raw(row["gas_revenue_usd"]),
        "attribute_revenue_usd": raw(row["attribute_revenue_usd"]),
        "gross_revenue_usd": raw(row["gross_revenue_usd"]),
        "calculated_amount_usd": raw(row["calculated_amount_usd"]),
        "floor_amount_usd": raw(row["floor_amount_usd"]),
        "royalty_amount_usd": raw(row["royalty_amount_usd"]),
        "status": row["status"],
        "dispute_reason": row["dispute_reason"],
        "created_at": fmt_iso(row["created_at"]),
        "updated_at": fmt_iso(row["updated_at"]),
        "version": row["version"],
    }
