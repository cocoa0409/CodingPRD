"""Resource serialisation.  Derived fields are refreshed at read time so a
rollup never disagrees with the rows it was computed from (PRD 2.10)."""

import domain
from store import fmt_dt


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_dt(rec["created_at"]),
        "updated_at": fmt_dt(rec["updated_at"]),
        "version": rec["version"],
    }


def producer_out(rec):
    domain.evaluate_compliance(rec)
    rec["voting_shares"] = domain.voting_shares(rec)
    out = _common(rec)
    out.update({
        "legal_name": rec["legal_name"],
        "region_code": rec["region_code"],
        "contact_email": rec["contact_email"],
        "onboarding_status": rec["onboarding_status"],
        "food_safety_tier": rec["food_safety_tier"],
        "compliance_ok": rec["compliance_ok"],
        "review_cycles": rec["review_cycles"],
        "suspension_count": rec["suspension_count"],
        "paid_in_capital_cents": rec["paid_in_capital_cents"],
        "voting_shares": rec["voting_shares"],
        "patronage_volume_cents": rec["patronage_volume_cents"],
        "shrink_charge_cents": rec["shrink_charge_cents"],
        "retained_patronage_cents": rec["retained_patronage_cents"],
    })
    return out


def document_out(rec):
    out = _common(rec)
    out.update({
        "producer_id": rec["producer_id"],
        "doc_type": rec["doc_type"],
        "issued_on": fmt_dt(rec["issued_on"]),
        "expires_on": fmt_dt(rec["expires_on"]),
        "status": rec["status"],
        "adjudicated_by_user_id": rec["adjudicated_by_user_id"],
        "rejection_reason": rec["rejection_reason"],
    })
    return out


def product_out(rec):
    rec["quantity_available"] = domain.product_available(rec)
    out = _common(rec)
    out.update({
        "producer_id": rec["producer_id"],
        "commodity_code": rec["commodity_code"],
        "unit_of_measure": rec["unit_of_measure"],
        "storage_class": rec["storage_class"],
        "pack_weight_lb": rec["pack_weight_lb"],
        "units_per_pallet": rec["units_per_pallet"],
        "producer_unit_price_cents": rec["producer_unit_price_cents"],
        "status": rec["status"],
        "quantity_offered": rec["quantity_offered"],
        "quantity_committed": rec["quantity_committed"],
        "quantity_available": rec["quantity_available"],
        "offer_window_start": fmt_dt(rec["offer_window_start"]),
        "offer_window_end": fmt_dt(rec["offer_window_end"]),
    })
    return out


def buyer_out(rec):
    out = _common(rec)
    out.update({
        "legal_name": rec["legal_name"],
        "buyer_type": rec["buyer_type"],
        "dock_zone_code": rec["dock_zone_code"],
        "payment_terms_days": rec["payment_terms_days"],
        "credit_limit_cents": rec["credit_limit_cents"],
        "outstanding_balance_cents": rec["outstanding_balance_cents"],
    })
    return out


def order_out(rec):
    out = _common(rec)
    out.update({
        "buyer_id": rec["buyer_id"],
        "requested_delivery_date": fmt_dt(rec["requested_delivery_date"]),
        "fulfillment_status": rec["fulfillment_status"],
        "settlement_status": rec["settlement_status"],
        "producer_subtotal_cents": rec["producer_subtotal_cents"],
        "hub_margin_cents": rec["hub_margin_cents"],
        "order_total_cents": rec["order_total_cents"],
        "margin_tier_bp": rec["margin_tier_bp"],
        "invoiced_total_cents": rec["invoiced_total_cents"],
        "paid_total_cents": rec["paid_total_cents"],
        "credit_memo_cents": rec["credit_memo_cents"],
        "invoice_due_date": fmt_dt(rec["invoice_due_date"]),
        "route_id": rec["route_id"],
        "route_sequence_no": rec["route_sequence_no"],
        "planned_arrival_at": fmt_dt(rec["planned_arrival_at"]),
        "service_minutes": rec["service_minutes"],
        "order_pallets": rec["order_pallets"],
    })
    return out


def line_out(rec):
    out = _common(rec)
    out.update({
        "order_id": rec["order_id"],
        "commodity_code": rec["commodity_code"],
        "storage_class": rec["storage_class"],
        "unit_of_measure": rec["unit_of_measure"],
        "quantity_requested": rec["quantity_requested"],
        "max_unit_price_cents": rec["max_unit_price_cents"],
        "quantity_allocated": rec["quantity_allocated"],
        "quantity_delivered": rec["quantity_delivered"],
        "quantity_rejected": rec["quantity_rejected"],
        "line_producer_cents": rec["line_producer_cents"],
        "line_margin_cents": rec["line_margin_cents"],
        "line_total_cents": rec["line_total_cents"],
        "status": rec["status"],
    })
    return out


def allocation_out(rec):
    out = _common(rec)
    out.update({
        "order_line_id": rec["order_line_id"],
        "product_id": rec["product_id"],
        "quantity": rec["quantity"],
        "producer_unit_price_cents": rec["producer_unit_price_cents"],
        "margin_bp": rec["margin_bp"],
        "producer_amount_cents": rec["producer_amount_cents"],
        "hub_margin_cents": rec["hub_margin_cents"],
        "buyer_amount_cents": rec["buyer_amount_cents"],
        "delivered_quantity": rec["delivered_quantity"],
        "rejected_quantity": rec["rejected_quantity"],
        "producer_charge_cents": rec["producer_charge_cents"],
        "hub_absorbed_cents": rec["hub_absorbed_cents"],
        "staged_temp_c": rec["staged_temp_c"],
        "temp_excursion": rec["temp_excursion"],
        "status": rec["status"],
    })
    return out


def dock_slot_out(rec):
    domain.refresh_slot(rec)
    out = _common(rec)
    out.update({
        "door_code": rec["door_code"],
        "storage_class": rec["storage_class"],
        "window_start": fmt_dt(rec["window_start"]),
        "window_end": fmt_dt(rec["window_end"]),
        "pallet_capacity": rec["pallet_capacity"],
        "temp_setpoint_c": rec["temp_setpoint_c"],
        "sanitation_buffer_minutes": rec["sanitation_buffer_minutes"],
        "pallets_booked": rec["pallets_booked"],
        "status": rec["status"],
    })
    return out


def appointment_out(rec):
    out = _common(rec)
    out.update({
        "dock_slot_id": rec["dock_slot_id"],
        "producer_id": rec["producer_id"],
        "arrival_start": fmt_dt(rec["arrival_start"]),
        "arrival_end": fmt_dt(rec["arrival_end"]),
        "pallets": rec["pallets"],
        "risk_class": rec["risk_class"],
        "received_pallets": rec["received_pallets"],
        "recorded_temp_c": rec["recorded_temp_c"],
        "status": rec["status"],
    })
    return out


def route_out(rec):
    domain.refresh_route_counts(rec)
    out = _common(rec)
    out.update({
        "route_date": fmt_dt(rec["route_date"]),
        "vehicle_code": rec["vehicle_code"],
        "storage_class": rec["storage_class"],
        "pallet_capacity": rec["pallet_capacity"],
        "depot_departure_at": fmt_dt(rec["depot_departure_at"]),
        "pallets_loaded": rec["pallets_loaded"],
        "stop_count": rec["stop_count"],
        "status": rec["status"],
    })
    return out


def claim_out(rec):
    out = _common(rec)
    out.update({
        "allocation_id": rec["allocation_id"],
        "quantity_rejected": rec["quantity_rejected"],
        "reason_code": rec["reason_code"],
        "note": rec["note"],
        "filed_by_user_id": rec["filed_by_user_id"],
        "adjudicated_by_user_id": rec["adjudicated_by_user_id"],
        "status": rec["status"],
        "producer_fault_bp": rec["producer_fault_bp"],
        "buyer_credit_cents": rec["buyer_credit_cents"],
        "producer_charge_cents": rec["producer_charge_cents"],
        "hub_absorbed_cents": rec["hub_absorbed_cents"],
    })
    return out


def cycle_out(rec):
    out = _common(rec)
    out.update({
        "fiscal_year": rec["fiscal_year"],
        "distributable_pool_cents": rec["distributable_pool_cents"],
        "status": rec["status"],
        "proposed_by_user_id": rec["proposed_by_user_id"],
        "ratified_by_user_id": rec["ratified_by_user_id"],
        "basis_snapshot_total_cents": rec["basis_snapshot_total_cents"],
        "eligible_producer_count": rec["eligible_producer_count"],
        "distributed_total_cents": rec["distributed_total_cents"],
        "remainder_cents": rec["remainder_cents"],
    })
    return out
