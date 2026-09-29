"""Output shapes for every entity."""

import aggregates
import db


def num(value):
    """Render a stored Decimal percentage as a JSON number."""
    return None if value is None else float(value)


def common(row, out):
    out["created_at"] = row["created_at"]
    out["updated_at"] = row["updated_at"]
    out["version"] = row["version"]
    return out


def client(row):
    buckets = aggregates.unit_buckets(row["id"])
    out = {
        "id": row["id"],
        "name": row["name"],
        "client_code": row["client_code"],
        "service_level": row["service_level"],
        "inventory_ownership": row["inventory_ownership"],
        "restock_grade_floor": row["restock_grade_floor"],
        "refund_hold_hours": row["refund_hold_hours"],
        "liquidation_floor_pct": num(row["liquidation_floor_pct"]),
        "fraud_tolerance_cents": row["fraud_tolerance_cents"],
        "donation_allowed": row["donation_allowed"],
        "destroy_requires_dual_signoff": row["destroy_requires_dual_signoff"],
        "max_refund_exposure_cents": row["max_refund_exposure_cents"],
        "status": row["status"],
        "units_received": buckets["units_received"],
        "units_in_process": buckets["units_in_process"],
        "units_reserved_for_disposition": buckets["units_reserved_for_disposition"],
        "units_dispositioned": buckets["units_dispositioned"],
        "shrink_ledger_cents": aggregates.shrink_ledger(row["id"]),
        "settlement_balance_cents": aggregates.settlement_balance(row["id"]),
        "projected_settlement_balance_cents": aggregates.projected_settlement_balance(row["id"]),
        "open_rma_count": aggregates.open_rma_count(row["id"]),
    }
    return common(row, out)


def catalog_item(row):
    out = {
        "id": row["id"],
        "client_id": row["client_id"],
        "sku": row["sku"],
        "description": row["description"],
        "declared_value_cents": row["declared_value_cents"],
        "unit_weight_grams": row["unit_weight_grams"],
        "serialized": row["serialized"],
        "hazard_class": row["hazard_class"],
        "regulated_flag": row["regulated_flag"],
        "recall_status": row["recall_status"],
        "refurb_eligible": row["refurb_eligible"],
        "secondary_market_floor_cents": row["secondary_market_floor_cents"],
    }
    return common(row, out)


def processing_bay(row):
    out = {
        "id": row["id"],
        "bay_code": row["bay_code"],
        "bay_type": row["bay_type"],
        "buffer_minutes": row["buffer_minutes"],
        "status": row["status"],
    }
    return common(row, out)


def channel(row):
    out = {
        "id": row["id"],
        "name": row["name"],
        "channel_code": row["channel_code"],
        "channel_type": row["channel_type"],
        "accepted_grades": list(row["accepted_grades"]),
        "fee_pct": num(row["fee_pct"]),
        "hazard_certified": row["hazard_certified"],
        "recall_certified": row["recall_certified"],
        "min_lot_value_cents": row["min_lot_value_cents"],
        "concurrent_lot_capacity": row["concurrent_lot_capacity"],
        "price_index_pct": num(row["price_index_pct"]),
        "status": row["status"],
    }
    return common(row, out)


def rma(row):
    rollups = aggregates.rma_rollups(row)
    out = {
        "id": row["id"],
        "client_id": row["client_id"],
        "order_reference": row["order_reference"],
        "customer_reference": row["customer_reference"],
        "order_placed_at": row["order_placed_at"],
        "expires_at": row["expires_at"],
        "supersedes_rma_id": row["supersedes_rma_id"],
        "status": row["status"],
        "declared_line_count": rollups["declared_line_count"],
        "authorized_unit_total": rollups["authorized_unit_total"],
        "received_unit_total": rollups["received_unit_total"],
        "fraud_flag_count": rollups["fraud_flag_count"],
        "issued_at": row["issued_at"],
    }
    return common(row, out)


def rma_line(row):
    return {
        "id": row["id"],
        "rma_id": row["rma_id"],
        "catalog_item_id": row["catalog_item_id"],
        "authorized_quantity": row["authorized_quantity"],
        "reason_code": row["reason_code"],
        "declared_serial": row["declared_serial"],
        "received_quantity": aggregates.rma_line_received_quantity(row["id"]),
        "created_at": row["created_at"],
    }


def receipt(row):
    out = {
        "id": row["id"],
        "rma_id": row["rma_id"],
        "tracking_reference": row["tracking_reference"],
        "gross_weight_grams": row["gross_weight_grams"],
        "expected_weight_grams": row["expected_weight_grams"],
        "empty_box_suspected": row["empty_box_suspected"],
        "received_at": row["received_at"],
        "scanned_by_user_id": row["scanned_by_user_id"],
    }
    return common(row, out)


def return_line(row):
    out = {
        "id": row["id"],
        "receipt_id": row["receipt_id"],
        "rma_line_id": row["rma_line_id"],
        "bay_id": row["bay_id"],
        "quantity": row["quantity"],
        "scanned_serial": row["scanned_serial"],
        "reason_code": row["reason_code"],
        "condition_grade": row["condition_grade"],
        "disposition": row["disposition"],
        "disposition_state": row["disposition_state"],
        "financial_state": row["financial_state"],
        "quarantine_start_at": row["quarantine_start_at"],
        "quarantine_end_at": row["quarantine_end_at"],
        "days_since_order": row["days_since_order"],
        "recovery_value_cents": row["recovery_value_cents"],
        "fraud_score_receipt": row["fraud_score_receipt"],
        "fraud_score_release": row["fraud_score_release"],
        "graded_by_user_id": row["graded_by_user_id"],
        "released_by_user_id": row["released_by_user_id"],
    }
    return common(row, out)


def fraud_check(row):
    return {
        "id": row["id"],
        "return_line_id": row["return_line_id"],
        "check_type": row["check_type"],
        "outcome": row["outcome"],
        "weight_points": row["weight_points"],
        "evidence": row["evidence"],
        "evaluated_stage": row["evaluated_stage"],
        "created_at": row["created_at"],
    }


def work_order(row):
    out = {
        "id": row["id"],
        "return_line_id": row["return_line_id"],
        "bay_id": row["bay_id"],
        "assigned_technician_user_id": row["assigned_technician_user_id"],
        "status": row["status"],
        "rework_cycles": row["rework_cycles"],
        "labor_minutes_total": row["labor_minutes_total"],
        "parts_cost_cents": row["parts_cost_cents"],
        "packaging_cost_cents": row["packaging_cost_cents"],
        "total_cost_cents": row["total_cost_cents"],
        "resulting_grade": row["resulting_grade"],
        "test_window_start_at": row["test_window_start_at"],
        "test_window_end_at": row["test_window_end_at"],
        "qa_user_id": row["qa_user_id"],
    }
    return common(row, out)


def disposition_order(row):
    out = {
        "id": row["id"],
        "return_line_id": row["return_line_id"],
        "channel_id": row["channel_id"],
        "disposition": row["disposition"],
        "quantity": row["quantity"],
        "unit_price_cents": row["unit_price_cents"],
        "channel_window_start_at": row["channel_window_start_at"],
        "channel_window_end_at": row["channel_window_end_at"],
        "gross_lot_value_cents": row["gross_lot_value_cents"],
        "effective_fee_pct": num(row["effective_fee_pct"]),
        "channel_fee_cents": row["channel_fee_cents"],
        "net_recovery_cents": row["net_recovery_cents"],
        "refurb_cost_cents": row["refurb_cost_cents"],
        "status": row["status"],
        "approved_by_user_id": row["approved_by_user_id"],
        "executed_by_user_id": row["executed_by_user_id"],
        "executed_at": row["executed_at"],
        "selected_by_policy": row["selected_by_policy"],
    }
    return common(row, out)


def pricing_feedback(row):
    return {
        "id": row["id"],
        "disposition_order_id": row["disposition_order_id"],
        "channel_id": row["channel_id"],
        "expected_price_cents": row["expected_price_cents"],
        "realized_price_cents": row["realized_price_cents"],
        "variance_pct": num(row["variance_pct"]),
        "sequence_no": row["sequence_no"],
        "created_at": row["created_at"],
    }


def refund_release(row):
    out = {
        "id": row["id"],
        "return_line_id": row["return_line_id"],
        "client_id": row["client_id"],
        "gross_refund_cents": row["gross_refund_cents"],
        "restocking_fee_pct": num(row["restocking_fee_pct"]),
        "restocking_fee_cents": row["restocking_fee_cents"],
        "net_refund_cents": row["net_refund_cents"],
        "release_eligible_at": row["release_eligible_at"],
        "released_at": row["released_at"],
        "released_by_user_id": row["released_by_user_id"],
        "reversed_at": row["reversed_at"],
        "denial_reason": row["denial_reason"],
    }
    return common(row, out)


def shrink_ledger_entry(row):
    return {
        "id": row["id"],
        "client_id": row["client_id"],
        "return_line_id": row["return_line_id"],
        "entry_type": row["entry_type"],
        "amount_cents": row["amount_cents"],
        "memo": row["memo"],
        "sequence_no": row["sequence_no"],
        "created_at": row["created_at"],
    }
