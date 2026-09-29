"""Resource -> JSON projections.  Numbers are emitted as JSON numbers, money as
integer cents, timestamps canonicalised to three fractional digits."""

from util import fmt_dt, num


def _common(row, payload):
    payload["id"] = row["id"]
    payload["created_at"] = fmt_dt(row["created_at"])
    payload["updated_at"] = fmt_dt(row["updated_at"])
    payload["version"] = row["version"]
    return payload


def department(row):
    return _common(row, {
        "name": row["name"],
        "store_number": row["store_number"],
        "shrink_budget_pct": num(row["shrink_budget_pct"]),
        "labor_rate_cents_per_minute": num(row["labor_rate_cents_per_minute"]),
        "freight_surcharge_pct": num(row["freight_surcharge_pct"]),
        "donation_partner_enabled": row["donation_partner_enabled"],
        "open_purchase_commitment_cents": row["open_purchase_commitment_cents"],
    })


def bake_day(row):
    return _common(row, {
        "department_id": row["department_id"],
        "business_date": row["business_date"],
        "day_of_week": row["day_of_week"],
        "labor_budget_minutes": row["labor_budget_minutes"],
        "oven_shift_start_utc": fmt_dt(row["oven_shift_start_utc"]),
        "oven_shift_end_utc": fmt_dt(row["oven_shift_end_utc"]),
        "plan_posture": row["plan_posture"],
        "markdown_authorization": row["markdown_authorization"],
        "forecast_lines": [
            {
                "product_id": line["product_id"],
                "daypart": line["daypart"],
                "forecasted_units": line["forecasted_units"],
            }
            for line in row["forecast_lines"]
        ],
        "planned_labor_minutes": num(row["planned_labor_minutes"]),
        "actual_labor_minutes": num(row["actual_labor_minutes"]),
        "planned_units_total": row["planned_units_total"],
        "produced_units_total": row["produced_units_total"],
        "production_cost_cents": row["production_cost_cents"],
        "waste_units_total": row["waste_units_total"],
        "shrink_cost_cents": row["shrink_cost_cents"],
        "shrink_cost_basis_pct": num(row["shrink_cost_basis_pct"]),
        "shrink_unit_basis_pct": num(row["shrink_unit_basis_pct"]),
        "plan_unmet_unit_count": row["plan_unmet_unit_count"],
    })


def oven(row):
    return _common(row, {
        "department_id": row["department_id"],
        "name": row["name"],
        "deck_count": row["deck_count"],
        "rack_capacity_per_deck": row["rack_capacity_per_deck"],
        "changeover_buffer_minutes": row["changeover_buffer_minutes"],
        "allergen_mode": row["allergen_mode"],
        "oven_status": row["oven_status"],
        "status_reason": row["status_reason"],
    })


def product(row):
    return _common(row, {
        "department_id": row["department_id"],
        "sku": row["sku"],
        "name": row["name"],
        "production_method": row["production_method"],
        "units_per_rack": row["units_per_rack"],
        "proof_minutes": row["proof_minutes"],
        "bake_minutes": row["bake_minutes"],
        "cool_minutes": row["cool_minutes"],
        "base_labor_minutes_per_rack": num(row["base_labor_minutes_per_rack"]),
        "setup_labor_minutes": num(row["setup_labor_minutes"]),
        "unit_retail_cents": row["unit_retail_cents"],
        "shelf_life_hours": row["shelf_life_hours"],
        "markdown_pct": num(row["markdown_pct"]),
        "allergen_tags": list(row["allergen_tags"]),
        "allergen_free_claim": row["allergen_free_claim"],
        "recipe_lines": [
            {"ingredient_id": line["ingredient_id"], "units_per_rack": line["units_per_rack"]}
            for line in row["recipe_lines"]
        ],
        "is_custom_cake_base": row["is_custom_cake_base"],
    })


def ingredient(row):
    return _common(row, {
        "department_id": row["department_id"],
        "name": row["name"],
        "case_pack_units": row["case_pack_units"],
        "unit_cost_cents": num(row["unit_cost_cents"]),
        "shelf_life_days": row["shelf_life_days"],
        "daily_usage_units": row["daily_usage_units"],
        "reorder_point_units": row["reorder_point_units"],
        "on_hand_units": row["on_hand_units"],
        "replenishment_state": row["replenishment_state"],
        "allergen_tags": list(row["allergen_tags"]),
    })


def production_run(row):
    return _common(row, {
        "bake_day_id": row["bake_day_id"],
        "product_id": row["product_id"],
        "oven_id": row["oven_id"],
        "deck_index": row["deck_index"],
        "origin": row["origin"],
        "rack_count": row["rack_count"],
        "planned_units": row["planned_units"],
        "proof_start_utc": fmt_dt(row["proof_start_utc"]),
        "bake_start_utc": fmt_dt(row["bake_start_utc"]),
        "bake_end_utc": fmt_dt(row["bake_end_utc"]),
        "ready_utc": fmt_dt(row["ready_utc"]),
        "expires_utc": fmt_dt(row["expires_utc"]),
        "execution_status": row["execution_status"],
        "disposition_status": row["disposition_status"],
        "cancelled_reason": row["cancelled_reason"],
        "actual_units": row["actual_units"],
        "actual_labor_minutes": num(row["actual_labor_minutes"]),
        "planned_labor_minutes": num(row["planned_labor_minutes"]),
        "final_labor_minutes": num(row["final_labor_minutes"]),
        "ingredient_cost_cents": row["ingredient_cost_cents"],
        "unit_cost_basis_cents": row["unit_cost_basis_cents"],
        "on_shelf_units": row["on_shelf_units"],
        "wasted_units_total": row["wasted_units_total"],
        "markdown_unit_price_cents": row["markdown_unit_price_cents"],
        "executed_by_user_id": row["executed_by_user_id"],
        "shared_equipment_label_tags": list(row["shared_equipment_label_tags"]),
    })


def pickup_slot(row):
    return _common(row, {
        "bake_day_id": row["bake_day_id"],
        "slot_start_utc": fmt_dt(row["slot_start_utc"]),
        "slot_end_utc": fmt_dt(row["slot_end_utc"]),
        "decorator_capacity_units": row["decorator_capacity_units"],
        "reserved_decoration_units": row["reserved_decoration_units"],
        "slot_status": row["slot_status"],
    })


def cake_order(row):
    return _common(row, {
        "bake_day_id": row["bake_day_id"],
        "pickup_slot_id": row["pickup_slot_id"],
        "product_id": row["product_id"],
        "customer_name": row["customer_name"],
        "decoration_complexity": row["decoration_complexity"],
        "tier_count": row["tier_count"],
        "allergen_free_required": row["allergen_free_required"],
        "rush_requested": row["rush_requested"],
        "order_status": row["order_status"],
        "revision_count": row["revision_count"],
        "decoration_units": row["decoration_units"],
        "required_decoration_lead_minutes": row["required_decoration_lead_minutes"],
        "decoration_deadline_utc": fmt_dt(row["decoration_deadline_utc"]),
        "quote_subtotal_cents": row["quote_subtotal_cents"],
        "rush_fee_cents": row["rush_fee_cents"],
        "volume_discount_cents": row["volume_discount_cents"],
        "quote_total_cents": row["quote_total_cents"],
        "decoration_started_utc": fmt_dt(row["decoration_started_utc"]),
        "ready_at_utc": fmt_dt(row["ready_at_utc"]),
        "picked_up_at_utc": fmt_dt(row["picked_up_at_utc"]),
    })


def ingredient_order(row):
    return _common(row, {
        "department_id": row["department_id"],
        "target_bake_day_id": row["target_bake_day_id"],
        "origin": row["origin"],
        "lines": [
            {
                "ingredient_id": line["ingredient_id"],
                "required_units": line["required_units"],
                "cases": line["cases"],
                "ordered_units": line["ordered_units"],
                "line_cost_cents": line["line_cost_cents"],
            }
            for line in row["lines"]
        ],
        "order_total_cents": row["order_total_cents"],
        "order_status": row["order_status"],
        "submitted_at_utc": fmt_dt(row["submitted_at_utc"]),
        "received_lines": [
            {"ingredient_id": line["ingredient_id"], "received_units": line["received_units"]}
            for line in row["received_lines"]
        ],
        "shortfall_units_total": row["shortfall_units_total"],
        "cancel_reason": row["cancel_reason"],
    })


def waste_record(row):
    return _common(row, {
        "production_run_id": row["production_run_id"],
        "bake_day_id": row["bake_day_id"],
        "disposition_reason": row["disposition_reason"],
        "units": row["units"],
        "unit_cost_basis_cents": row["unit_cost_basis_cents"],
        "waste_cost_cents": row["waste_cost_cents"],
        "record_status": row["record_status"],
        "attested_by_user_id": row["attested_by_user_id"],
        "voided_by_user_id": row["voided_by_user_id"],
        "void_reason": row["void_reason"],
    })
