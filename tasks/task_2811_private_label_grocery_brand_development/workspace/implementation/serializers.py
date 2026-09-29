"""Wire representations of every entity."""
from decimal import Decimal

from db import iso


def num(value):
    """Decimals go out as JSON numbers; None stays null."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def program_out(row):
    return {
        "id": row["id"],
        "brand_name": row["brand_name"],
        "retailer_name": row["retailer_name"],
        "fiscal_year": row["fiscal_year"],
        "dev_budget_cents": row["dev_budget_cents"],
        "committed_budget_cents": row["committed_budget_cents"],
        "lifetime_committed_cents": row["lifetime_committed_cents"],
        "lifetime_released_cents": row["lifetime_released_cents"],
        "active_item_count": row["active_item_count"],
        "status": row["status"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def gap_out(row):
    return {
        "id": row["id"],
        "program_id": row["program_id"],
        "category_code": row["category_code"],
        "national_brand_name": row["national_brand_name"],
        "nb_retail_price_cents": row["nb_retail_price_cents"],
        "category_annual_sales_cents": row["category_annual_sales_cents"],
        "pl_share_pct": num(row["pl_share_pct"]),
        "unit_velocity_per_week": num(row["unit_velocity_per_week"]),
        "shelf_slots_quota": row["shelf_slots_quota"],
        "slots_consumed": row["slots_consumed"],
        "slots_open": row["slots_open"],
        "slots_consumed_lifetime": row["slots_consumed_lifetime"],
        "slots_released_lifetime": row["slots_released_lifetime"],
        "gap_score": num(row["gap_score"]),
        "recommended_tier": row["recommended_tier"],
        "approved_tier": row["approved_tier"],
        "override_justification": row["override_justification"],
        "status": row["status"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def supplier_out(row):
    return {
        "id": row["id"],
        "program_id": row["program_id"],
        "legal_name": row["legal_name"],
        "plant_country": row["plant_country"],
        "gfsi_certificate_expiry": iso(row["gfsi_certificate_expiry"]),
        "qualification_status": row["qualification_status"],
        "qualified_at": iso(row["qualified_at"]),
        "composite_score_cached": num(row["composite_score_cached"]),
        "probation_item_count": row["probation_item_count"],
        "weighted_complaint_points": row["weighted_complaint_points"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def plant_line_out(row):
    return {
        "id": row["id"],
        "supplier_id": row["supplier_id"],
        "line_code": row["line_code"],
        "daily_capacity_units": row["daily_capacity_units"],
        "changeover_buffer_minutes": num(row["changeover_buffer_minutes"]),
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def plant_audit_out(row):
    return {
        "id": row["id"],
        "supplier_id": row["supplier_id"],
        "audit_type": row["audit_type"],
        "window_start": iso(row["window_start"]),
        "window_end": iso(row["window_end"]),
        "food_safety_score": row["food_safety_score"],
        "sanitation_score": row["sanitation_score"],
        "capacity_score": row["capacity_score"],
        "traceability_score": row["traceability_score"],
        "audited_yield_pct": num(row["audited_yield_pct"]),
        "result": row["result"],
        "status": row["status"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def item_out(row):
    return {
        "id": row["id"],
        "gap_id": row["gap_id"],
        "supplier_id": row["supplier_id"],
        "replacement_item_id": row["replacement_item_id"],
        "item_name": row["item_name"],
        "tier": row["tier"],
        "pack_size_desc": row["pack_size_desc"],
        "development_status": row["development_status"],
        "quality_posture": row["quality_posture"],
        "trailing_90d_units": row["trailing_90d_units"],
        "complaint_ppm_90d": num(row["complaint_ppm_90d"]),
        "retail_price_cents": row["retail_price_cents"],
        "spec_revision_count": row["spec_revision_count"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def cost_model_out(row):
    return {
        "id": row["id"],
        "item_id": row["item_id"],
        "supplier_id": row["supplier_id"],
        "ingredient_cost_cents_per_unit": row["ingredient_cost_cents_per_unit"],
        "packaging_cost_cents_per_unit": row["packaging_cost_cents_per_unit"],
        "conversion_cost_cents_per_unit": row["conversion_cost_cents_per_unit"],
        "effective_base_cents": row["effective_base_cents"],
        "quoted_yield_pct": num(row["quoted_yield_pct"]),
        "freight_cents_per_pallet": row["freight_cents_per_pallet"],
        "units_per_pallet": row["units_per_pallet"],
        "moq_units": row["moq_units"],
        "tooling_cents": row["tooling_cents"],
        "landed_unit_cost_cents_as_quoted": row["landed_unit_cost_cents_as_quoted"],
        "landed_unit_cost_cents_audited": row["landed_unit_cost_cents_audited"],
        "open_change_request_count": row["open_change_request_count"],
        "status": row["status"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def study_out(row):
    return {
        "id": row["id"],
        "item_id": row["item_id"],
        "study_type": row["study_type"],
        "nb_control_lot_code": row["nb_control_lot_code"],
        "appearance_delta": num(row["appearance_delta"]),
        "aroma_delta": num(row["aroma_delta"]),
        "texture_delta": num(row["texture_delta"]),
        "flavor_delta": num(row["flavor_delta"]),
        "n_panelists": row["n_panelists"],
        "prefer_pl_count": row["prefer_pl_count"],
        "prefer_nb_count": row["prefer_nb_count"],
        "no_preference_count": row["no_preference_count"],
        "parity_index": num(row["parity_index"]),
        "preference_share_pct": num(row["preference_share_pct"]),
        "verdict": row["verdict"],
        "status": row["status"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def artwork_round_out(row):
    return {
        "id": row["id"],
        "item_id": row["item_id"],
        "round_number": row["round_number"],
        "designer_user_id": row["designer_user_id"],
        "reviewer_user_id": row["reviewer_user_id"],
        "serving_size_g": num(row["serving_size_g"]),
        "servings_per_container": num(row["servings_per_container"]),
        "fat_g_per_100g": num(row["fat_g_per_100g"]),
        "satfat_g_per_100g": num(row["satfat_g_per_100g"]),
        "carb_g_per_100g": num(row["carb_g_per_100g"]),
        "fiber_g_per_100g": num(row["fiber_g_per_100g"]),
        "sugars_g_per_100g": num(row["sugars_g_per_100g"]),
        "added_sugars_g_per_100g": num(row["added_sugars_g_per_100g"]),
        "protein_g_per_100g": num(row["protein_g_per_100g"]),
        "sodium_mg_per_100g": num(row["sodium_mg_per_100g"]),
        "declared_calories": row["declared_calories"],
        "declared_fat_g": num(row["declared_fat_g"]),
        "declared_satfat_g": num(row["declared_satfat_g"]),
        "declared_carb_g": num(row["declared_carb_g"]),
        "declared_fiber_g": num(row["declared_fiber_g"]),
        "declared_sugars_g": num(row["declared_sugars_g"]),
        "declared_added_sugars_g": num(row["declared_added_sugars_g"]),
        "declared_protein_g": num(row["declared_protein_g"]),
        "declared_sodium_mg": row["declared_sodium_mg"],
        "nutrition_status": row["nutrition_status"],
        "status": row["status"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def label_claim_out(row):
    return {
        "id": row["id"],
        "artwork_round_id": row["artwork_round_id"],
        "claim_text": row["claim_text"],
        "claim_type": row["claim_type"],
        "substantiation_ref": row["substantiation_ref"],
        "depends_on_nutrition": row["depends_on_nutrition"],
        "submitted_by_user_id": row["submitted_by_user_id"],
        "reviewed_by_user_id": row["reviewed_by_user_id"],
        "rationale": row["rationale"],
        "status": row["status"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def specification_out(row):
    return {
        "id": row["id"],
        "item_id": row["item_id"],
        "pinned_cost_model_id": row["pinned_cost_model_id"],
        "pinned_cost_model_version": row["pinned_cost_model_version"],
        "pinned_artwork_round_id": row["pinned_artwork_round_id"],
        "pinned_artwork_version": row["pinned_artwork_version"],
        "revision_no": row["revision_no"],
        "slotting_fee_cents": row["slotting_fee_cents"],
        "locked_at": iso(row["locked_at"]),
        "locked_by_user_id": row["locked_by_user_id"],
        "status": row["status"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def production_run_out(row):
    return {
        "id": row["id"],
        "item_id": row["item_id"],
        "specification_id": row["specification_id"],
        "plant_line_id": row["plant_line_id"],
        "run_type": row["run_type"],
        "window_start": iso(row["window_start"]),
        "window_end": iso(row["window_end"]),
        "planned_units": row["planned_units"],
        "produced_units": row["produced_units"],
        "completed_on_time": row["completed_on_time"],
        "completed_at": iso(row["completed_at"]),
        "committed_tooling_cents": row["committed_tooling_cents"],
        "approved_by_user_id": row["approved_by_user_id"],
        "hold_reason": row["hold_reason"],
        "status": row["status"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def complaint_out(row):
    return {
        "id": row["id"],
        "item_id": row["item_id"],
        "defect_category": row["defect_category"],
        "severity": row["severity"],
        "lot_code": row["lot_code"],
        "narrative": row["narrative"],
        "received_at": iso(row["received_at"]),
        "created_at": iso(row["created_at"]),
    }


def change_request_out(row):
    return {
        "id": row["id"],
        "item_id": row["item_id"],
        "cost_model_id": row["cost_model_id"],
        "requested_ingredient_cost_cents_per_unit": row["requested_ingredient_cost_cents_per_unit"],
        "requested_packaging_cost_cents_per_unit": row["requested_packaging_cost_cents_per_unit"],
        "requested_conversion_cost_cents_per_unit": row["requested_conversion_cost_cents_per_unit"],
        "substitution_scope": row["substitution_scope"],
        "substitution_material_desc": row["substitution_material_desc"],
        "counter_base_cents": row["counter_base_cents"],
        "round_number": row["round_number"],
        "raw_increase_cents": row["raw_increase_cents"],
        "increase_pct": num(row["increase_pct"]),
        "escalation_tier": row["escalation_tier"],
        "capped_increase_cents": row["capped_increase_cents"],
        "offset_fee_cents": row["offset_fee_cents"],
        "net_increase_cents": row["net_increase_cents"],
        "decided_by_user_id": row["decided_by_user_id"],
        "status": row["status"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }
