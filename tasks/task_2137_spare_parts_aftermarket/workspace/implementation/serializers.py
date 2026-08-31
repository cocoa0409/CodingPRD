"""Resource serializers. available_units and replenishment_status are derived live."""
import store
import domain


def _common(rec, out):
    out["id"] = rec["id"]
    out["created_at"] = store.iso(rec["created_at"])
    if "updated_at" in rec:
        out["updated_at"] = store.iso(rec["updated_at"])
    if "version" in rec:
        out["version"] = rec["version"]
    return out


def part(rec):
    out = {
        "part_number": rec["part_number"],
        "description": rec["description"],
        "lifecycle_state": rec["lifecycle_state"],
        "superseded_by_part_id": rec["superseded_by_part_id"],
        "unit_cost_cents": rec["unit_cost_cents"],
        "lead_time_days": rec["lead_time_days"],
        "weight_kg": rec["weight_kg"],
        "hazmat": rec["hazmat"],
        "max_stock_units": rec["max_stock_units"],
        "criticality_score": rec["criticality_score"],
        "criticality_class": rec["criticality_class"],
        "stocking_policy": rec["stocking_policy"],
        "safety_stock_units": rec["safety_stock_units"],
        "reorder_point_units": rec["reorder_point_units"],
        "on_hand_units": rec["on_hand_units"],
        "allocated_units": rec["allocated_units"],
        "quarantine_units": rec["quarantine_units"],
        "in_transit_units": rec["in_transit_units"],
        "available_units": domain.available_units(rec),
        "replenishment_status": domain.replenishment_status(rec),
        "current_list_unit_price_cents": rec["current_list_unit_price_cents"],
        "current_effective_uplift_pct": rec["current_effective_uplift_pct"],
    }
    return _common(rec, out)


def equipment_model(rec):
    out = {
        "model_code": rec["model_code"],
        "name": rec["name"],
        "production_end_date": store.iso(rec["production_end_date"]),
        "support_end_date": store.iso(rec["support_end_date"]),
    }
    return _common(rec, out)


def installed_unit(rec):
    out = {
        "model_id": rec["model_id"],
        "dealer_id": rec["dealer_id"],
        "serial_number": rec["serial_number"],
        "build_revision": rec["build_revision"],
        "commission_date": store.iso(rec["commission_date"]),
        "region": rec["region"],
        "status": rec["status"],
    }
    return _common(rec, out)


def part_applicability(rec):
    out = {
        "part_id": rec["part_id"],
        "model_id": rec["model_id"],
        "effective_from_build_revision": rec["effective_from_build_revision"],
        "effective_to_build_revision": rec["effective_to_build_revision"],
        "qty_per_unit": rec["qty_per_unit"],
        "applicability_status": rec["applicability_status"],
    }
    return _common(rec, out)


def dealer(rec):
    out = {
        "dealer_code": rec["dealer_code"],
        "tier": rec["tier"],
        "region": rec["region"],
        "credit_limit_cents": rec["credit_limit_cents"],
        "outstanding_balance_cents": rec["outstanding_balance_cents"],
        "lifetime_restocking_fee_cents": rec["lifetime_restocking_fee_cents"],
        "lifetime_rebate_cents": rec["lifetime_rebate_cents"],
        "credit_hold": rec["credit_hold"],
        "status": rec["status"],
    }
    return _common(rec, out)


def work_order(rec):
    out = {
        "installed_unit_id": rec["installed_unit_id"],
        "dealer_id": rec["dealer_id"],
        "work_type": rec["work_type"],
        "downtime_priority": rec["downtime_priority"],
        "status": rec["status"],
        "opened_at": store.iso(rec["opened_at"]),
        "closed_at": store.iso(rec["closed_at"]),
    }
    return _common(rec, out)


def part_line(rec):
    out = {
        "work_order_id": rec["work_order_id"],
        "part_id": rec["part_id"],
        "qty_requested": rec["qty_requested"],
        "qty_consumed": rec["qty_consumed"],
        "line_status": rec["line_status"],
        "fulfillment_mode": rec["fulfillment_mode"],
        "decision_net_benefit_cents": rec["decision_net_benefit_cents"],
        "freight_cost_cents": rec["freight_cost_cents"],
        "effective_uplift_pct": rec["effective_uplift_pct"],
        "list_unit_price_cents": rec["list_unit_price_cents"],
        "list_line_total_cents": rec["list_line_total_cents"],
        "quoted_line_total_cents": rec["quoted_line_total_cents"],
        "variant_delta_cents": rec["variant_delta_cents"],
        "margin_pct": rec["margin_pct"],
        "charged_amount_cents": rec["charged_amount_cents"],
        "consumed_at": store.iso(rec["consumed_at"]),
    }
    return _common(rec, out)


def forecast(rec):
    out = {
        "part_id": rec["part_id"],
        "horizon_months": rec["horizon_months"],
        "lookback_days": rec["lookback_days"],
        "method": rec["method"],
        "wo_history_units": rec["wo_history_units"],
        "annualized_wo_units": rec["annualized_wo_units"],
        "installed_base_units": rec["installed_base_units"],
        "ib_rate_units": rec["ib_rate_units"],
        "forecast_units": rec["forecast_units"],
        "forecast_status": rec["forecast_status"],
        "computed_at": store.iso(rec["computed_at"]),
    }
    return _common(rec, out)


def campaign(rec):
    out = {
        "part_id": rec["part_id"],
        "method": rec["method"],
        "coverage_years": rec["coverage_years"],
        "ltb_window_start": store.iso(rec["ltb_window_start"]),
        "ltb_window_end": store.iso(rec["ltb_window_end"]),
        "annual_demand_units": rec["annual_demand_units"],
        "proposed_qty": rec["proposed_qty"],
        "approved_qty": rec["approved_qty"],
        "remaining_qty": rec["remaining_qty"],
        "status": rec["status"],
        "revision_index": rec["revision_index"],
        "submitted_by_user_id": rec["submitted_by_user_id"],
        "approved_by_user_id": rec["approved_by_user_id"],
        "rejection_reason": rec["rejection_reason"],
    }
    return _common(rec, out)


def allocation_request(rec):
    out = {
        "campaign_id": rec["campaign_id"],
        "dealer_id": rec["dealer_id"],
        "requested_units": rec["requested_units"],
        "granted_units": rec["granted_units"],
        "priority_score": rec["priority_score"],
        "dealer_installed_units": rec["dealer_installed_units"],
        "status": rec["status"],
    }
    return _common(rec, out)


def replenishment_order(rec):
    out = {
        "part_id": rec["part_id"],
        "order_type": rec["order_type"],
        "qty": rec["qty"],
        "unit_cost_cents": rec["unit_cost_cents"],
        "freight_cost_cents": rec["freight_cost_cents"],
        "total_landed_cost_cents": rec["total_landed_cost_cents"],
        "approval_status": rec["approval_status"],
        "logistics_status": rec["logistics_status"],
        "auto_generated": rec["auto_generated"],
        "rejection_reason": rec.get("rejection_reason"),
    }
    return _common(rec, out)


def return_authorization(rec):
    out = {
        "work_order_part_line_id": rec["work_order_part_line_id"],
        "part_id": rec["part_id"],
        "dealer_id": rec["dealer_id"],
        "qty_returned": rec["qty_returned"],
        "return_reason": rec["return_reason"],
        "age_days": rec["age_days"],
        "gross_credit_cents": rec["gross_credit_cents"],
        "fee_pct": rec["fee_pct"],
        "restocking_fee_cents": rec["restocking_fee_cents"],
        "net_before_rebate_cents": rec["net_before_rebate_cents"],
        "rebate_pct": rec["rebate_pct"],
        "loyalty_rebate_cents": rec["loyalty_rebate_cents"],
        "final_credit_cents": rec["final_credit_cents"],
        "credit_posted_cents": rec["credit_posted_cents"],
        "disposition": rec["disposition"],
        "status": rec["status"],
        "rejection_reason": rec.get("rejection_reason"),
    }
    return _common(rec, out)


def price_rule(rec):
    out = {
        "criticality_class": rec["criticality_class"],
        "base_uplift_pct": rec["base_uplift_pct"],
        "max_uplift_pct": rec["max_uplift_pct"],
        "min_margin_pct": rec["min_margin_pct"],
        "rule_status": rec["rule_status"],
    }
    return _common(rec, out)


def ledger_entry(rec):
    out = {
        "id": rec["id"],
        "part_id": rec["part_id"],
        "entry_type": rec["entry_type"],
        "delta_units": rec["delta_units"],
        "balance_after_units": rec["balance_after_units"],
        "source_ref_type": rec["source_ref_type"],
        "source_ref_id": rec["source_ref_id"],
        "occurred_at": store.iso(rec["occurred_at"]),
        "created_at": store.iso(rec["created_at"]),
    }
    return out
