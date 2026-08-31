"""Public JSON representations of every entity."""

from decimal import Decimal

import domain
import store


def num(value):
    """Render a decimal quantity as a JSON number."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(row):
    return {
        "id": row["id"],
        "created_at": store.iso(row["created_at"]),
        "updated_at": store.iso(row["updated_at"]),
        "version": row["version"],
    }


def ward(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "code": row["code"],
        "tray_line_capacity_per_window": row["tray_line_capacity_per_window"],
        "delivery_lead_minutes": row["delivery_lead_minutes"],
        "temperature_probe_required": row["temperature_probe_required"],
        "status": row["status"],
        "active_patient_census": store.ward_census(row["id"]),
    })
    return out


def patient(row):
    active_order = store.active_diet_order_of(row["id"])
    active_hold = store.active_hold_of(row["id"])
    out = _common(row)
    out.update({
        "ward_id": row["ward_id"],
        "mrn": row["mrn"],
        "full_name": row["full_name"],
        "age_years": row["age_years"],
        "allergen_codes": list(row["allergen_codes"]),
        "texture_level": row["texture_level"],
        "liquid_level": row["liquid_level"],
        "status": row["status"],
        "npo_status": row["npo_status"],
        "active_procedure_hold_id": active_hold["id"] if active_hold else None,
        "active_diet_order_id": active_order["id"] if active_order else None,
        "missed_meal_count": row["missed_meal_count"],
        "protein_deficit_g": num(row["protein_deficit_g"]),
        "daily_supplement_cost_cents": row["daily_supplement_cost_cents"],
        "survey_count": row["survey_count"],
        "satisfaction_score_avg": num(row["satisfaction_score_avg"]),
    })
    return out


def diet_rule(row):
    out = _common(row)
    out.update({
        "diet_code": row["diet_code"],
        "display_name": row["display_name"],
        "max_sodium_mg_per_meal": row["max_sodium_mg_per_meal"],
        "max_potassium_mg_per_meal": row["max_potassium_mg_per_meal"],
        "max_carb_g_per_meal": num(row["max_carb_g_per_meal"]),
        "min_texture_level": row["min_texture_level"],
        "min_liquid_level": row["min_liquid_level"],
        "forbidden_tag_codes": list(row["forbidden_tag_codes"]),
        "requires_dietitian_cosign": row["requires_dietitian_cosign"],
        "precedence_rank": row["precedence_rank"],
        "status": row["status"],
    })
    return out


def diet_order(row):
    envelope = domain.envelope_of(row)
    successor = None
    for candidate in store.diet_orders.values():
        if candidate.get("supersedes_diet_order_id") == row["id"]:
            successor = candidate["id"]
            break
    out = _common(row)
    out.update({
        "patient_id": row["patient_id"],
        "primary_diet_rule_id": row["primary_diet_rule_id"],
        "secondary_diet_rule_id": row["secondary_diet_rule_id"],
        "supersedes_diet_order_id": row["supersedes_diet_order_id"],
        "superseded_by_diet_order_id": successor,
        "ordering_physician_user_id": row["ordering_physician_user_id"],
        "cosigned_by_user_id": row["cosigned_by_user_id"],
        "texture_level": row["texture_level"],
        "liquid_level": row["liquid_level"],
        "status": row["status"],
        "revision_round": row["revision_round"],
        "revision_note": row["revision_note"],
        "effective_from": store.iso(row["effective_from"]),
        "effective_sodium_cap_mg": envelope["effective_sodium_cap_mg"],
        "effective_potassium_cap_mg": envelope["effective_potassium_cap_mg"],
        "effective_carb_cap_g": num(envelope["effective_carb_cap_g"]),
        "effective_texture_level": envelope["effective_texture_level"],
        "effective_liquid_level": envelope["effective_liquid_level"],
        "forbidden_tag_codes_effective": list(
            envelope["forbidden_tag_codes_effective"] or []),
        "linked_meal_order_count": row["linked_meal_order_count"],
    })
    return out


def meal_period(row):
    out = _common(row)
    out.update({
        "ward_id": row["ward_id"],
        "period_code": row["period_code"],
        "service_date": row["service_date"],
        "order_cutoff_at": store.iso(row["order_cutoff_at"]),
        "window_start_at": store.iso(row["window_start_at"]),
        "window_end_at": store.iso(row["window_end_at"]),
        "production_capacity_trays": row["production_capacity_trays"],
        "cost_ceiling_cents": row["cost_ceiling_cents"],
        "status": row["status"],
        "forecast_variant": row["forecast_variant"],
        "forecast_tray_count": row["forecast_tray_count"],
        "forecast_cost_cents": row["forecast_cost_cents"],
        "forecast_variance_pct": num(row["forecast_variance_pct"]),
        "locked_at": store.iso(row["locked_at"]),
        "committed_tray_count": row["committed_tray_count"],
        "committed_food_cost_cents": row["committed_food_cost_cents"],
        "delivered_tray_count": row["delivered_tray_count"],
        "period_overhead_cents": row["period_overhead_cents"],
        "period_bulk_discount_cents": row["period_bulk_discount_cents"],
        "period_total_cost_cents": row["period_total_cost_cents"],
    })
    return out


def menu_item(row):
    out = _common(row)
    out.update({
        "item_code": row["item_code"],
        "display_name": row["display_name"],
        "sodium_mg": row["sodium_mg"],
        "potassium_mg": row["potassium_mg"],
        "carb_g": num(row["carb_g"]),
        "protein_g": num(row["protein_g"]),
        "unit_cost_cents": row["unit_cost_cents"],
        "texture_level": row["texture_level"],
        "liquid_level": row["liquid_level"],
        "service_temp_class": row["service_temp_class"],
        "allergen_codes": list(row["allergen_codes"]),
        "tag_codes": list(row["tag_codes"]),
        "status": row["status"],
    })
    return out


def meal_order(row):
    out = _common(row)
    out.update({
        "patient_id": row["patient_id"],
        "meal_period_id": row["meal_period_id"],
        "diet_order_id": row["diet_order_id"],
        "pinned_diet_order_version": row["pinned_diet_order_version"],
        "placed_by_user_id": row["placed_by_user_id"],
        "fulfillment_status": row["fulfillment_status"],
        "qa_status": row["qa_status"],
        "revalidation_required": row["revalidation_required"],
        "effective_texture_level": row["effective_texture_level"],
        "effective_liquid_level": row["effective_liquid_level"],
        "total_sodium_mg": row["total_sodium_mg"],
        "total_potassium_mg": row["total_potassium_mg"],
        "total_carb_g": num(row["total_carb_g"]),
        "total_protein_g": num(row["total_protein_g"]),
        "food_cost_cents": row["food_cost_cents"],
        "requires_hot_probe": row["requires_hot_probe"],
        "requires_cold_probe": row["requires_cold_probe"],
        "hot_probe_celsius": num(row["hot_probe_celsius"]),
        "cold_probe_celsius": num(row["cold_probe_celsius"]),
        "accuracy_retry_count": row["accuracy_retry_count"],
        "temperature_retry_count": row["temperature_retry_count"],
        "accuracy_checked_by_user_id": row["accuracy_checked_by_user_id"],
        "temperature_checked_by_user_id": row["temperature_checked_by_user_id"],
        "delivered_at": store.iso(row["delivered_at"]),
        "delivery_window_compliance": row["delivery_window_compliance"],
        "service_compliance_score": row["service_compliance_score"],
        "missed_reason": row["missed_reason"],
    })
    return out


def meal_order_line(row):
    out = _common(row)
    out.update({
        "meal_order_id": row["meal_order_id"],
        "menu_item_id": row["menu_item_id"],
        "substituted_from_menu_item_id": row["substituted_from_menu_item_id"],
        "quantity": row["quantity"],
        "line_status": row["line_status"],
        "substitution_reason": row["substitution_reason"],
        "line_cost_cents": row["line_cost_cents"],
    })
    return out


def procedure_hold(row):
    out = _common(row)
    out.update({
        "patient_id": row["patient_id"],
        "procedure_code": row["procedure_code"],
        "npo_kind": row["npo_kind"],
        "hold_start_at": store.iso(row["hold_start_at"]),
        "hold_end_at": store.iso(row["hold_end_at"]),
        "buffer_before_minutes": row["buffer_before_minutes"],
        "buffer_after_minutes": row["buffer_after_minutes"],
        "buffered_start_at": store.iso(row["buffered_start_at"]),
        "buffered_end_at": store.iso(row["buffered_end_at"]),
        "status": row["status"],
        "requested_by_user_id": row["requested_by_user_id"],
        "released_at": store.iso(row["released_at"]),
        "missed_meal_order_count": row["missed_meal_order_count"],
    })
    return out


def consult(row):
    out = _common(row)
    out.update({
        "patient_id": row["patient_id"],
        "acuity": row["acuity"],
        "reason_code": row["reason_code"],
        "requested_by_user_id": row["requested_by_user_id"],
        "assigned_dietitian_user_id": row["assigned_dietitian_user_id"],
        "auto_generated": row["auto_generated"],
        "status": row["status"],
        "assessment_variant": row["assessment_variant"],
        "weight_loss_pct": num(row["weight_loss_pct"]),
        "intake_pct": num(row["intake_pct"]),
        "bmi": num(row["bmi"]),
        "albumin_g_dl": num(row["albumin_g_dl"]),
        "malnutrition_risk_score": num(row["malnutrition_risk_score"]),
        "risk_tier": row["risk_tier"],
        "recommended_supplement_item_id": row["recommended_supplement_item_id"],
        "signed_by_user_id": row["signed_by_user_id"],
        "due_at": store.iso(row["due_at"]),
        "is_overdue": domain.consult_is_overdue(row),
        "linked_supplement_order_count": row["linked_supplement_order_count"],
    })
    return out


def supplement_order(row):
    out = _common(row)
    out.update({
        "consult_id": row["consult_id"],
        "patient_id": row["patient_id"],
        "menu_item_id": row["menu_item_id"],
        "doses_per_day": row["doses_per_day"],
        "status": row["status"],
        "daily_cost_cents": row["daily_cost_cents"],
        "ordered_by_user_id": row["ordered_by_user_id"],
        "activated_at": store.iso(row["activated_at"]),
        "cancelled_at": store.iso(row["cancelled_at"]),
    })
    return out


def survey(row):
    """Immutable append-only event: id and created_at only, no updated_at, no version."""
    return {
        "id": row["id"],
        "created_at": store.iso(row["created_at"]),
        "meal_order_id": row["meal_order_id"],
        "patient_id": row["patient_id"],
        "taste_score": row["taste_score"],
        "temperature_score": row["temperature_score"],
        "accuracy_score": row["accuracy_score"],
        "comment": row["comment"],
        "composite_score": num(row["composite_score"]),
    }
