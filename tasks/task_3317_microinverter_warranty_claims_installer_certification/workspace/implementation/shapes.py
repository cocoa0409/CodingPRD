"""Response shapes.

Each function renders one entity exactly as the entity table declares it:
ProductionLot, WarrantyTransfer and ReplacementOrder expose only `id` and
`created_at` (no updated_at, no version), while the other seven carry the full
audit convention (PRD 2.4).
"""


def installer(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "installer_code": row.get("installer_code"),
        "company_name": row.get("company_name"),
        "contact_email": row.get("contact_email"),
        "certification_level": row.get("certification_level"),
        "certification_status": row.get("certification_status"),
        "certified_until": row.get("certified_until"),
        "design_tool_enabled": row.get("design_tool_enabled"),
        "commissioning_enabled": row.get("commissioning_enabled"),
        "active_system_count": row.get("active_system_count"),
        "claim_approval_rate_pct": row.get("claim_approval_rate_pct"),
        "labor_approved_cents_total": row.get("labor_approved_cents_total"),
        "labor_reversed_cents_total": row.get("labor_reversed_cents_total"),
        "labor_paid_cents_total": row.get("labor_paid_cents_total"),
    }


def design_project(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "installer_id": row.get("installer_id"),
        "site_address": row.get("site_address"),
        "site_postal_code": row.get("site_postal_code"),
        "module_count": row.get("module_count"),
        "dc_capacity_watts": row.get("dc_capacity_watts"),
        "dc_ac_ratio": row.get("dc_ac_ratio"),
        "status": row.get("status"),
        "rejection_reason": row.get("rejection_reason"),
    }


def production_lot(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "lot_code": row.get("lot_code"),
        "manufacture_month": row.get("manufacture_month"),
        "defect_threshold_pct": row.get("defect_threshold_pct"),
        "embed_model_code": row.get("embed_model_code"),
        "units_registered_count": row.get("units_registered_count"),
        "failed_unit_count": row.get("failed_unit_count"),
        "window_failed_unit_count": row.get("window_failed_unit_count"),
        "defect_rate_cumulative_pct": row.get("defect_rate_cumulative_pct"),
        "defect_rate_window_pct": row.get("defect_rate_window_pct"),
        "lot_status": row.get("lot_status"),
        "corrective_action_required": row.get("corrective_action_required"),
        "replacement_model_code": row.get("replacement_model_code"),
        "watch_started_at": row.get("watch_started_at"),
    }


def system_registration(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "installer_id": row.get("installer_id"),
        "design_project_id": row.get("design_project_id"),
        "site_address": row.get("site_address"),
        "site_postal_code": row.get("site_postal_code"),
        "homeowner_name": row.get("homeowner_name"),
        "homeowner_email": row.get("homeowner_email"),
        "commissioned_at": row.get("commissioned_at"),
        "warranty_start_at": row.get("warranty_start_at"),
        "base_warranty_end_at": row.get("base_warranty_end_at"),
        "extended_warranty_end_at": row.get("extended_warranty_end_at"),
        "warranty_status": row.get("warranty_status"),
        "unit_count": row.get("unit_count"),
        "replacement_ratio": row.get("replacement_ratio"),
        "coverage_window": row.get("coverage_window"),
        "owner_change_count": row.get("owner_change_count"),
    }


def unit(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "system_id": row.get("system_id"),
        "serial_number": row.get("serial_number"),
        "model_code": row.get("model_code"),
        "production_lot_id": row.get("production_lot_id"),
        "installed_at": row.get("installed_at"),
        "commissioning_state": row.get("commissioning_state"),
        "monitored_status": row.get("monitored_status"),
        "last_performance_ratio": row.get("last_performance_ratio"),
        "underperformance_streak_hours": row.get("underperformance_streak_hours"),
        "failed_at": row.get("failed_at"),
        "replacement_count": row.get("replacement_count"),
        "replacement_window_position": row.get("replacement_window_position"),
        "rma_eligible": row.get("rma_eligible"),
        "campaign_eligible": row.get("campaign_eligible"),
        "retired_generation": row.get("retired_generation"),
        "direct_replacement_unsupported": row.get("direct_replacement_unsupported"),
    }


def warranty_claim(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "unit_id": row.get("unit_id"),
        "installer_id": row.get("installer_id"),
        "claim_kind": row.get("claim_kind"),
        "remote_diagnostic_ref": row.get("remote_diagnostic_ref"),
        "status": row.get("status"),
        "installer_level_at_claim": row.get("installer_level_at_claim"),
        "system_age_months_at_claim": row.get("system_age_months_at_claim"),
        "diagnostic_source": row.get("diagnostic_source"),
        "labor_eligible": row.get("labor_eligible"),
        "approved_labor_hours": row.get("approved_labor_hours"),
        "denial_reason": row.get("denial_reason"),
        "reopen_count": row.get("reopen_count"),
    }


def labor_reimbursement(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "claim_id": row.get("claim_id"),
        "installer_id": row.get("installer_id"),
        "claimed_hours": row.get("claimed_hours"),
        "allowed_hours": row.get("allowed_hours"),
        "cap_applied": row.get("cap_applied"),
        "hourly_rate_cents": row.get("hourly_rate_cents"),
        "age_factor": row.get("age_factor"),
        "level_factor": row.get("level_factor"),
        "labor_component_cents": row.get("labor_component_cents"),
        "diagnostic_component_cents": row.get("diagnostic_component_cents"),
        "net_amount_cents": row.get("net_amount_cents"),
        "status": row.get("status"),
        "rejection_reason": row.get("rejection_reason"),
        "paid_at": row.get("paid_at"),
    }


def warranty_transfer(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "system_id": row.get("system_id"),
        "transfer_kind": row.get("transfer_kind"),
        "new_owner_name": row.get("new_owner_name"),
        "new_owner_email": row.get("new_owner_email"),
        "effective_date": row.get("effective_date"),
        "preserved_months": row.get("preserved_months"),
        "approval_source": row.get("approval_source"),
        "status": row.get("status"),
        "rejection_reason": row.get("rejection_reason"),
    }


def proactive_campaign(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "lot_id": row.get("lot_id"),
        "origin": row.get("origin"),
        "replacement_model_code": row.get("replacement_model_code"),
        "max_units": row.get("max_units"),
        "guaranteed_units": row.get("guaranteed_units"),
        "status": row.get("status"),
        "target_unit_count": row.get("target_unit_count"),
        "dispatched_count": row.get("dispatched_count"),
        "canceled_count": row.get("canceled_count"),
        "window_start_at": row.get("window_start_at"),
        "window_end_at": row.get("window_end_at"),
    }


def replacement_order(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "claim_id": row.get("claim_id"),
        "campaign_id": row.get("campaign_id"),
        "unit_id": row.get("unit_id"),
        "replacement_model_code": row.get("replacement_model_code"),
        "compatibility_class": row.get("compatibility_class"),
        "status": row.get("status"),
        "dispatched_at": row.get("dispatched_at"),
        "installed_at": row.get("installed_at"),
    }


def coverage(system, figures):
    return {
        "system_id": system["id"],
        "warranty_status": system.get("warranty_status"),
        "base_warranty_end_at": figures["base_warranty_end_at"],
        "extended_warranty_end_at": figures["extended_warranty_end_at"],
        "extension_months": figures["extension_months"],
        "replacement_ratio": figures["replacement_ratio"],
        "coverage_start_at": figures["coverage_window"]["start_at"],
        "coverage_end_at": figures["coverage_window"]["end_at"],
    }


def monitoring_summary(system, age_months, active_units, failed_units,
                       per_unit_rate_cents, metering_fee_cents):
    return {
        "system_id": system["id"],
        "warranty_status": system.get("warranty_status"),
        "system_age_months": age_months,
        "active_units": active_units,
        "failed_units": failed_units,
        "per_unit_rate_cents": per_unit_rate_cents,
        "metering_fee_cents": metering_fee_cents,
    }


def labor_quote(reimbursement_row, figures):
    return {
        "reimbursement_id": reimbursement_row["id"],
        "level_used": figures["level_used"],
        "age_factor": figures["age_factor"],
        "allowed_hours": figures["allowed_hours"],
        "cap_applied": figures["cap_applied"],
        "labor_component_cents": figures["labor_component_cents"],
        "diagnostic_component_cents": figures["diagnostic_component_cents"],
        "net_amount_cents": figures["net_amount_cents"],
        "blended_total_cents": figures["blended_total_cents"],
    }


def campaign_preview(campaign, lot_only_model_code, pure_rank_ids, guaranteed_ids,
                     target_unit_count):
    return {
        "campaign_id": campaign["id"],
        "status": campaign.get("status"),
        "lot_only_model_code": lot_only_model_code,
        "pure_rank_unit_ids": pure_rank_ids,
        "guaranteed_first_unit_ids": guaranteed_ids,
        "target_unit_count": target_unit_count,
        "max_units": campaign.get("max_units"),
        "guaranteed_units": campaign.get("guaranteed_units"),
    }


def billing_entitlement(row):
    return {
        "entitlement_id": row["id"],
        "unit_id": row.get("unit_id"),
        "entitlement_kind": row.get("entitlement_kind"),
        "effective_from": row.get("effective_from"),
        "status": row.get("status"),
    }


def share_link(row):
    return {
        "share_link_id": row["id"],
        "system_id": row.get("system_id"),
        "expires_at": row.get("expires_at"),
        "scope": row.get("scope"),
    }


def billing_correction(row):
    return {
        "period_month_id": row["id"],
        "system_id": row.get("system_id"),
        "period_month": row.get("period_month"),
        "original_metering_fee_cents": row.get("original_metering_fee_cents"),
        "corrected_metering_fee_cents": row.get("corrected_metering_fee_cents"),
        "current_month_charge_cents": row.get("current_month_charge_cents"),
        "variance_bps": row.get("variance_bps"),
        "watermarked_total_cents": row.get("watermarked_total_cents"),
    }