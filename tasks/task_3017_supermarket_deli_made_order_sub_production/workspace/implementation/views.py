"""Serialisers: stored row -> JSON resource.

Field names and shapes follow the scaffold's entity table and the PRD exactly;
nothing structural is invented here.
"""
from util import out_number


def _base(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def store(row):
    out = _base(row)
    out.update({
        "store_number": row["store_number"],
        "name": row["name"],
        "deli_case_capacity_lbs": out_number(row["deli_case_capacity_lbs"]),
        "hot_bar_capacity_lbs": out_number(row["hot_bar_capacity_lbs"]),
        "sub_station_count": row["sub_station_count"],
        "haccp_safety_flag": row["haccp_safety_flag"],
        "case_on_hand_lbs": out_number(row["case_on_hand_lbs"]),
        "posture": row["posture"],
        "posture_gate_flag": row["posture_gate_flag"],
        "posture_reason": row["posture_reason"],
        "certified_slicer_operator_count": row["certified_slicer_operator_count"],
        "active_price_file_id": row["active_price_file_id"],
        "targeted_promo_id": row["targeted_promo_id"],
        "covered_allergen_set": list(row["covered_allergen_set"]),
        "available_bread_units": row["available_bread_units"],
        "verified_waste_liability_cents": row["verified_waste_liability_cents"],
        "pending_waste_verification_count": row["pending_waste_verification_count"],
        "ops_run_index": row["ops_run_index"],
        "logical_clock_at_last_run": row["logical_clock_at_last_run"],
    })
    return out


def deli_item(row):
    out = _base(row)
    out.update({
        "sku": row["sku"],
        "name": row["name"],
        "category": row["category"],
        "unit_cost_cents": row["unit_cost_cents"],
        "retail_price_per_lb_cents": row["retail_price_per_lb_cents"],
        "case_life_minutes": row["case_life_minutes"],
        "markdown_window_minutes": row["markdown_window_minutes"],
        "allergen_flags": list(row["allergen_flags"]),
        "slicer_required": row["slicer_required"],
        "servings_per_platter": row["servings_per_platter"],
        "bread_deli_item_id": row["bread_deli_item_id"],
        "status": row["status"],
    })
    return out


def associate(row):
    out = _base(row)
    out.update({
        "store_id": row["store_id"],
        "employee_number": row["employee_number"],
        "full_name": row["full_name"],
        "primary_role": row["primary_role"],
        "status": row["status"],
        "allergy_set": list(row["allergy_set"]),
        "active_certification_count": row["active_certification_count"],
        "assigned_slicer_id": row["assigned_slicer_id"],
    })
    return out


def certification(row):
    out = _base(row)
    out.update({
        "store_id": row["store_id"],
        "associate_id": row["associate_id"],
        "deli_item_id": row["deli_item_id"],
        "revoked_by_manager_id": row["revoked_by_manager_id"],
        "cert_type": row["cert_type"],
        "issued_at": row["issued_at"],
        "expires_at": row["expires_at"],
        "status": row["status"],
        "grace_reminder": row["grace_reminder"],
    })
    return out


def batch(row):
    out = _base(row)
    out.update({
        "store_id": row["store_id"],
        "deli_item_id": row["deli_item_id"],
        "slicer_id": row["slicer_id"],
        "produced_by_associate_id": row["produced_by_associate_id"],
        "rework_of_batch_id": row["rework_of_batch_id"],
        "batch_code": row["batch_code"],
        "planned_lbs": out_number(row["planned_lbs"]),
        "produced_lbs": out_number(row["produced_lbs"]),
        "produced_at": row["produced_at"],
        "hold_expires_at": row["hold_expires_at"],
        "production_status": row["production_status"],
        "hold_status": row["hold_status"],
        "markdown_sold_lbs": out_number(row["markdown_sold_lbs"]),
        "markdown_cents": row["markdown_cents"],
        "discard_lbs": out_number(row["discard_lbs"]),
        "temperature_breach": row["temperature_breach"],
        "case_yield_cost_provisional_cents": row["case_yield_cost_provisional_cents"],
        "case_yield_cost_final_cents": row["case_yield_cost_final_cents"],
    })
    return out


def slicer(row):
    out = _base(row)
    out.update({
        "store_id": row["store_id"],
        "assigned_deli_item_id": row["assigned_deli_item_id"],
        "last_sliced_deli_item_id": row["last_sliced_deli_item_id"],
        "assigned_operator_id": row["assigned_operator_id"],
        "asset_tag": row["asset_tag"],
        "sanitation_cycle_limit": row["sanitation_cycle_limit"],
        "sanitation_status": row["sanitation_status"],
        "cuts_since_sanitation": row["cuts_since_sanitation"],
        "in_use_minutes": row["in_use_minutes"],
        "last_sanitized_at": row["last_sanitized_at"],
        "open_sanitation_cycle_id": row["open_sanitation_cycle_id"],
    })
    return out


def cycle(row):
    out = _base(row)
    out.update({
        "store_id": row["store_id"],
        "slicer_id": row["slicer_id"],
        "production_batch_id": row["production_batch_id"],
        "allergen_cleared_from_item_id": row["allergen_cleared_from_item_id"],
        "verified_by_associate_id": row["verified_by_associate_id"],
        "cycle_type": row["cycle_type"],
        "cycle_minutes": row["cycle_minutes"],
        "buffer_minutes": row["buffer_minutes"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "status": row["status"],
    })
    return out


def ticket(row):
    out = _base(row)
    out.update({
        "store_id": row["store_id"],
        "deli_item_id": row["deli_item_id"],
        "bread_deli_item_id": row["bread_deli_item_id"],
        "order_channel": row["order_channel"],
        "placed_by_customer_ref": row["placed_by_customer_ref"],
        "lines": [dict(line) for line in row["lines"]],
        "creation_sequence": row["creation_sequence"],
        "ticket_number": row["ticket_number"],
        "queue_position": row["queue_position"],
        "weight_lbs": out_number(row["weight_lbs"]),
        "status": row["status"],
        "promised_at": row["promised_at"],
        "completed_at": row["completed_at"],
        "line_total_cents": row["line_total_cents"],
        "lateness_minutes": row["lateness_minutes"],
        "remake_count": row["remake_count"],
        "label_id": row["label_id"],
        "bread_status": row["bread_status"],
    })
    return out


def promotion(row):
    out = _base(row)
    out.update({
        "promo_code": row["promo_code"],
        "deli_item_id": row["deli_item_id"],
        "week_start_date": row["week_start_date"],
        "week_end_date": row["week_end_date"],
        "forecast_uplift_pct": out_number(row["forecast_uplift_pct"]),
        "trailing_baseline_units": row["trailing_baseline_units"],
        "required_bread_units": row["required_bread_units"],
        "settled_bread_units": row["settled_bread_units"],
        "status": row["status"],
    })
    return out


def bread_order(row):
    out = _base(row)
    out.update({
        "store_id": row["store_id"],
        "bread_deli_item_id": row["bread_deli_item_id"],
        "promotion_id": row["promotion_id"],
        "committed_units": row["committed_units"],
        "required_units": row["required_units"],
        "delivered_units": row["delivered_units"],
        "shortfall_units": row["shortfall_units"],
        "reserved_units": row["reserved_units"],
        "unreserved_required_units": row["unreserved_required_units"],
        "submit_by_at": row["submit_by_at"],
        "status": row["status"],
    })
    return out


def price_file(row):
    out = _base(row)
    out.update({
        "store_id": row["store_id"],
        "file_label": row["file_label"],
        "effective_from": row["effective_from"],
        "effective_to": row["effective_to"],
        "item_price_count": row["item_price_count"],
        "status": row["status"],
        "activated_at": row["activated_at"],
        "synced_scale_count": row["synced_scale_count"],
    })
    return out


def label(row):
    out = _base(row)
    out.update({
        "store_id": row["store_id"],
        "sub_ticket_id": row["sub_ticket_id"],
        "price_file_id": row["price_file_id"],
        "subject_type": row["subject_type"],
        "subject_ref_id": row["subject_ref_id"],
        "net_weight_lbs": out_number(row["net_weight_lbs"]),
        "unit_price_cents": row["unit_price_cents"],
        "total_price_cents": row["total_price_cents"],
        "printed_at": row["printed_at"],
        "status": row["status"],
    })
    return out


def catering(row):
    out = _base(row)
    out.update({
        "store_id": row["store_id"],
        "platter_deli_item_id": row["platter_deli_item_id"],
        "parent_order_id": row["parent_order_id"],
        "certified_planner_associate_id": row["certified_planner_associate_id"],
        "customer_name": row["customer_name"],
        "platter_count": row["platter_count"],
        "headcount": row["headcount"],
        "lead_time_hours": row["lead_time_hours"],
        "pickup_window_start": row["pickup_window_start"],
        "pickup_window_end": row["pickup_window_end"],
        "deposit_cents": row["deposit_cents"],
        "quote_total_cents": row["quote_total_cents"],
        "pickup_bucket_key": row["pickup_bucket_key"],
        "status": row["status"],
    })
    return out


def waste(row):
    out = _base(row)
    out.update({
        "store_id": row["store_id"],
        "production_batch_id": row["production_batch_id"],
        "markdown_by_associate_id": row["markdown_by_associate_id"],
        "verifier_associate_id": row["verifier_associate_id"],
        "verified_by_certification_id": row["verified_by_certification_id"],
        "discard_lbs": out_number(row["discard_lbs"]),
        "reason": row["reason"],
        "markdown_sold_lbs": out_number(row["markdown_sold_lbs"]),
        "markdown_cents": row["markdown_cents"],
        "markdown_recorded_at": row["markdown_recorded_at"],
        "discarded_at": row["discarded_at"],
        "discard_value_cents": row["discard_value_cents"],
        "handling_fee_cents": row["handling_fee_cents"],
        "total_liability_cents": row["total_liability_cents"],
        "status": row["status"],
    })
    return out


SERIALIZERS = {
    "stores": store,
    "items": deli_item,
    "associates": associate,
    "certifications": certification,
    "batches": batch,
    "slicers": slicer,
    "sanitation_cycles": cycle,
    "sub_tickets": ticket,
    "promotions": promotion,
    "bread_orders": bread_order,
    "price_files": price_file,
    "labels": label,
    "catering_orders": catering,
    "waste_records": waste,
}


def render(table_name, row):
    return SERIALIZERS[table_name](row)