"""Entity -> JSON projections. Computed fields are derived at read time."""
import calc
from core import DB


def _common(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def plan_out(row):
    out = _common(row)
    out.update({
        "code": row["code"],
        "name": row["name"],
        "item_slots": row["item_slots"],
        "monthly_fee_cents": row["monthly_fee_cents"],
        "monthly_swaps_allowed": row["monthly_swaps_allowed"],
        "shipping_cadence_days": row["shipping_cadence_days"],
        "waiver_monthly_fee_cents": row["waiver_monthly_fee_cents"],
        "waiver_coverage_cents": row["waiver_coverage_cents"],
    })
    return out


def technician_out(row):
    out = _common(row)
    out.update({
        "employee_code": row["employee_code"],
        "full_name": row["full_name"],
        "repair_certified": row["repair_certified"],
        "photography_certified": row["photography_certified"],
        "status": row["status"],
    })
    return out


def style_out(row):
    out = _common(row)
    out.update({
        "style_code": row["style_code"],
        "brand": row["brand"],
        "category": row["category"],
        "retail_price_cents": row["retail_price_cents"],
        "acquisition_cost_cents": row["acquisition_cost_cents"],
        "size_run": list(row["size_run"]),
        "expected_rental_turns_per_unit": row["expected_rental_turns_per_unit"],
        "planned_depth_units": row["planned_depth_units"],
        "planned_eol_value_cents": row["planned_eol_value_cents"],
        "forecast_monthly_requests": row["forecast_monthly_requests"],
        "avg_rental_days": row["avg_rental_days"],
        "demand_score": calc.style_demand_score(row),
    })
    out.update(calc.style_depth(row))
    return out


def unit_out(row):
    out = _common(row)
    out.update({
        "style_id": row["style_id"],
        "unit_code": row["unit_code"],
        "size": row["size"],
        "acquisition_cost_cents": row["acquisition_cost_cents"],
        "condition_grade": row["condition_grade"],
        "availability_state": row["availability_state"],
        "condition_state": row["condition_state"],
        "turns_completed": row["turns_completed"],
        "quarantine_hold": row["quarantine_hold"],
        "last_returned_at": row["last_returned_at"],
        "retired_at": row["retired_at"],
        "retirement_reason": row["retirement_reason"],
        "cumulative_servicing_cost_cents": calc.unit_cumulative_servicing(row["id"]),
        "realized_revenue_cents": calc.unit_realized_revenue(row["id"]),
        "occupied_until_date": calc.unit_occupied_until(row["id"]),
    })
    return out


def member_out(row):
    risk = calc.damage_risk(row, "LIFETIME")
    out = _common(row)
    out.update({
        "membership_plan_id": row["membership_plan_id"],
        "email": row["email"],
        "full_name": row["full_name"],
        "status": row["status"],
        "waiver_active": row["waiver_active"],
        "preferred_categories": list(row["preferred_categories"]),
        "size_profile": row["size_profile"],
        "waiver_coverage_used_cents": calc.member_waiver_used(row["id"]),
        "outstanding_fee_cents": calc.member_outstanding(row["id"]),
        "units_out_count": calc.member_units_out(row["id"]),
        "swaps_used_current_month": calc.swaps_used_current_month(row["id"]),
        "fit_confidence_score": calc.member_fit_confidence(row["id"]),
        "damage_risk_score": risk["damage_risk_score"],
        "damage_risk_band": risk["damage_risk_band"],
        "late_return_count": calc.member_late_return_count(row["id"]),
    })
    return out


def reservation_out(row):
    out = _common(row)
    out.update({
        "member_id": row["member_id"],
        "style_id": row["style_id"],
        "allocated_unit_id": row["allocated_unit_id"],
        "superseded_reservation_id": row["superseded_reservation_id"],
        "requested_size": row["requested_size"],
        "requested_start_date": row["requested_start_date"],
        "requested_end_date": row["requested_end_date"],
        "state": row["state"],
        "waitlist_position": calc.waitlist_position(row),
        "is_swap": row["is_swap"],
        "matched_at": row["matched_at"],
        "shipped_at": row["shipped_at"],
        "delivered_at": row["delivered_at"],
        "returned_at": row["returned_at"],
        "rental_days": row["rental_days"],
        "late_days": row["late_days"],
        "late_fee_cents": row["late_fee_cents"],
        "revenue_attributed_cents": row["revenue_attributed_cents"],
    })
    return out


def shipment_out(row):
    out = _common(row)
    out.update({
        "member_id": row["member_id"],
        "reservation_id": row["reservation_id"],
        "direction": row["direction"],
        "planned_ship_date": row["planned_ship_date"],
        "state": row["state"],
        "carrier_reference": row["carrier_reference"],
        "dispatched_at": row["dispatched_at"],
        "delivered_at": row["delivered_at"],
        "received_at": row["received_at"],
        "exception_count": row["exception_count"],
        "exception_reason": row["exception_reason"],
    })
    return out


def job_out(row):
    out = _common(row)
    out.update({
        "rental_unit_id": row["rental_unit_id"],
        "reservation_id": row["reservation_id"],
        "inspecting_technician_id": row["inspecting_technician_id"],
        "state": row["state"],
        "cleaning_required": row["cleaning_required"],
        "repair_required": row["repair_required"],
        "cleaning_completed_at": row["cleaning_completed_at"],
        "repair_completed_at": row["repair_completed_at"],
        "photographed_at": row["photographed_at"],
        "repair_attempts": row["repair_attempts"],
        "condemned": row["condemned"],
        "servicing_cost_cents": calc.servicing_cost(row),
    })
    return out


def inspection_out(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "job_id": row["job_id"],
        "technician_id": row["technician_id"],
        "soil_level": row["soil_level"],
        "damage_severity": row["damage_severity"],
        "condition_grade_after": row["condition_grade_after"],
        "biohazard_flag": row["biohazard_flag"],
        "notes": row["notes"],
        "attempt_index": row["attempt_index"],
    }


def claim_out(row):
    out = _common(row)
    out.update({
        "reservation_id": row["reservation_id"],
        "rental_unit_id": row["rental_unit_id"],
        "member_id": row["member_id"],
        "inspection_id": row["inspection_id"],
        "severity": row["severity"],
        "state": row["state"],
        "residual_value_cents": row["residual_value_cents"],
        "gross_fee_cents": row["gross_fee_cents"],
        "waiver_applied_cents": row["waiver_applied_cents"],
        "net_fee_cents": row["net_fee_cents"],
        "dispute_round": row["dispute_round"],
        "dispute_reason": row["dispute_reason"],
        "resolution": row["resolution"],
        "assessed_at": row["assessed_at"],
        "charged_at": row["charged_at"],
    })
    return out


def listing_out(row):
    out = _common(row)
    out.update({
        "rental_unit_id": row["rental_unit_id"],
        "supersedes_listing_id": row["supersedes_listing_id"],
        "channel": row["channel"],
        "state": row["state"],
        "markdown_step": row["markdown_step"],
        "base_price_cents": row["base_price_cents"],
        "list_price_cents": row["list_price_cents"],
        "channel_fee_cents": row["channel_fee_cents"],
        "net_recovery_cents": row["net_recovery_cents"],
        "floor_adjusted": row["floor_adjusted"],
        "sale_price_cents": row["sale_price_cents"],
        "listed_at": row["listed_at"],
        "sold_at": row["sold_at"],
    })
    return out


def feedback_out(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "reservation_id": row["reservation_id"],
        "member_id": row["member_id"],
        "style_id": row["style_id"],
        "fit_rating": row["fit_rating"],
        "occasion_match_score": row["occasion_match_score"],
        "keep_intent": row["keep_intent"],
        "comment": row["comment"],
    }


def ledger_out(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "member_id": row["member_id"],
        "damage_claim_id": row["damage_claim_id"],
        "reservation_id": row["reservation_id"],
        "kind": row["kind"],
        "direction": row["direction"],
        "amount_cents": row["amount_cents"],
        "balance_after_cents": row["balance_after_cents"],
        "memo": row["memo"],
    }
