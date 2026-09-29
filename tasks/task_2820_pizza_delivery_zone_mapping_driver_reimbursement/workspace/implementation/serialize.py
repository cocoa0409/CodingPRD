"""JSON representations of the fourteen resources."""
import calc
import clock
import derive


def _common(record, versioned=True):
    payload = {"id": record["id"], "created_at": clock.iso(record["created_at"])}
    if versioned:
        payload["updated_at"] = clock.iso(record["updated_at"])
        payload["version"] = record["version"]
    return payload


def store(record):
    payload = {
        "store_number": record["store_number"],
        "name": record["name"],
        "latitude_micro": record["latitude_micro"],
        "longitude_micro": record["longitude_micro"],
        "promise_minutes": record["promise_minutes"],
        "delivery_fee_cents": record["delivery_fee_cents"],
        "cash_limit_cents": record["cash_limit_cents"],
        "hot_bag_count": record["hot_bag_count"],
        "max_stacked_stops": record["max_stacked_stops"],
        "handoff_minutes_per_stop": record["handoff_minutes_per_stop"],
        "dispatch_reset_buffer_minutes": record["dispatch_reset_buffer_minutes"],
        "service_posture": record["service_posture"],
        "cash_collected_total_cents": derive.store_cash_collected(record["id"]),
        "safe_deposit_total_cents": derive.store_safe_deposit(record["id"]),
        "unassigned_order_count": derive.unassigned_order_count(record["id"]),
        "active_zone_version_number": derive.active_zone_version_number(record["id"]),
    }
    payload.update(_common(record))
    return payload


def zone_version(record):
    payload = {
        "store_id": record["store_id"],
        "version_number": record["version_number"],
        "polygon": [dict(vertex) for vertex in record["polygon"]],
        "effective_from": clock.iso(record["effective_from"]),
        "effective_to": clock.iso(record["effective_to"]),
        "max_drive_time_minutes": record["max_drive_time_minutes"],
        "base_drive_minutes": record["base_drive_minutes"],
        "minutes_per_mile": record["minutes_per_mile"],
        "peak_surcharge_minutes": record["peak_surcharge_minutes"],
        "barrier_surcharge_minutes": record["barrier_surcharge_minutes"],
        "status": record["status"],
        "supersedes_zone_version_id": record["supersedes_zone_version_id"],
        "activated_at": clock.iso(record["activated_at"]),
    }
    payload.update(_common(record))
    return payload


def service_address(record):
    payload = {
        "store_id": record["store_id"],
        "line1": record["line1"],
        "latitude_micro": record["latitude_micro"],
        "longitude_micro": record["longitude_micro"],
        "crosses_barrier": record["crosses_barrier"],
        "grid_miles": calc.miles_out(record["grid_miles"]),
        "drive_time_estimate_minutes": record["drive_time_estimate_minutes"],
        "zone_state": record["zone_state"],
        "evaluated_zone_version_number": record["evaluated_zone_version_number"],
        "evaluated_at": clock.iso(record["evaluated_at"]),
        "override_state": record["override_state"],
        "override_until": clock.iso(record["override_until"]),
        "effective_zone_state": derive.effective_zone_state(record),
    }
    payload.update(_common(record))
    return payload


def address_dispute(record):
    payload = {
        "service_address_id": record["service_address_id"],
        "claimed_state": record["claimed_state"],
        "evidence_note": record["evidence_note"],
        "status": record["status"],
        "review_round_count": record["review_round_count"],
        "resolution": record["resolution"],
        "granted_until": clock.iso(record["granted_until"]),
        "decided_at": clock.iso(record["decided_at"]),
        "reviewer_user_id": record["reviewer_user_id"],
    }
    payload.update(_common(record))
    return payload


def driver(record):
    payload = {
        "store_id": record["store_id"],
        "full_name": record["full_name"],
        "license_number": record["license_number"],
        "vehicle_class": record["vehicle_class"],
        "qualification_status": record["qualification_status"],
        "insurance_status": derive.driver_insurance_status(record["id"]),
        "mvr_points_latest": derive.driver_mvr_points(record["id"]),
        "cash_on_hand_cents": derive.driver_cash_on_hand(record["id"]),
        "cash_posture": derive.driver_cash_posture(record),
        "reimbursement_accrued_cents": derive.driver_accrued_cents(record["id"]),
        "qualified_by_user_id": record["qualified_by_user_id"],
        "disqualified_reason": record["disqualified_reason"],
    }
    payload.update(_common(record))
    return payload


def qualification_decision(record):
    """PRD 3.6: "Qualification itself is a signed decision, carrying a `decision`
    of `QUALIFY`, `SUSPEND`, `REINSTATE` or `DISQUALIFY` plus an optional
    `reason`." PRD 4 returns that new record in the 201 data field."""
    payload = {
        "driver_id": record["driver_id"],
        "decision": record["decision"],
        "reason": record["reason"],
    }
    payload.update(_common(record))
    return payload


def vehicle_cost_model(record):
    payload = {
        "store_id": record["store_id"],
        "vehicle_class": record["vehicle_class"],
        "per_delivery_cents": record["per_delivery_cents"],
        "tier1_cap_miles": calc.miles_out(record["tier1_cap_miles"]),
        "tier1_per_mile_cents": record["tier1_per_mile_cents"],
        "tier2_per_mile_cents": record["tier2_per_mile_cents"],
        "min_reimbursement_per_stop_cents": record["min_reimbursement_per_stop_cents"],
        "effective_from": clock.iso(record["effective_from"]),
        "status": record["status"],
        "retired_at": clock.iso(record["retired_at"]),
    }
    payload.update(_common(record))
    return payload


def mvr_check(record):
    payload = {
        "driver_id": record["driver_id"],
        "result": record["result"],
        "violation_points": record["violation_points"],
        "checked_on": clock.iso(record["checked_on"]),
        "recorded_by_user_id": record["recorded_by_user_id"],
    }
    payload.update(_common(record, versioned=False))
    return payload


def insurance_verification(record):
    payload = {
        "driver_id": record["driver_id"],
        "policy_number": record["policy_number"],
        "coverage_from": clock.iso(record["coverage_from"]),
        "coverage_to": clock.iso(record["coverage_to"]),
        "liability_limit_cents": record["liability_limit_cents"],
        "status": record["status"],
        "rejected_reason": record["rejected_reason"],
    }
    payload.update(_common(record))
    return payload


def order(record):
    payload = {
        "store_id": record["store_id"],
        "service_address_id": record["service_address_id"],
        "customer_name": record["customer_name"],
        "customer_phone": record["customer_phone"],
        "food_subtotal_cents": record["food_subtotal_cents"],
        "tip_cents": record["tip_cents"],
        "payment_method": record["payment_method"],
        "fulfillment_status": record["fulfillment_status"],
        "settlement_status": record["settlement_status"],
        "promise_minutes_snapshot": record["promise_minutes_snapshot"],
        "fee_tier": record["fee_tier"],
        "base_delivery_fee_cents": record["base_delivery_fee_cents"],
        "fee_waiver_pct": record["fee_waiver_pct"],
        "delivery_fee_cents": record["delivery_fee_cents"],
        "total_charge_cents": record["total_charge_cents"],
        "disclosed_fee_cents": record["disclosed_fee_cents"],
        "disclosed_tip_cents": record["disclosed_tip_cents"],
        "driver_tip_notice_given": record["driver_tip_notice_given"],
        "fee_disclosure_accurate": record["fee_disclosure_accurate"],
        "fee_disclosed_at": clock.iso(record["fee_disclosed_at"]),
        "placed_at": clock.iso(record["placed_at"]),
        "ready_at": clock.iso(record["ready_at"]),
        "door_arrival_at": clock.iso(record["door_arrival_at"]),
        "zone_held_at": clock.iso(record["zone_held_at"]),
        "zone_hold_minutes": record["zone_hold_minutes"],
        "remake_hold_minutes": record["remake_hold_minutes"],
        "remake_count": record["remake_count"],
        "order_to_door_gross_minutes": record["order_to_door_gross_minutes"],
        "order_to_door_net_minutes": record["order_to_door_net_minutes"],
        "cash_collected_cents": record["cash_collected_cents"],
        "remedy_issued_cents": record["remedy_issued_cents"],
        "remake_credit_cents": record["remake_credit_cents"],
        "declined_reason": record["declined_reason"],
    }
    payload.update(_common(record))
    return payload


def dispatch(record):
    payload = {
        "driver_id": record["driver_id"],
        "planned_depart_at": clock.iso(record["planned_depart_at"]),
        "status": record["status"],
        "stop_count": record["stop_count"],
        "committed_hot_bag_slots": derive.committed_hot_bag_slots(record),
        "route_minutes": record["route_minutes"],
        "expected_return_at": clock.iso(record["expected_return_at"]),
        "resolved_cost_model_id": record["resolved_cost_model_id"],
        "estimated_reimbursement_cents": record["estimated_reimbursement_cents"],
        "actual_reimbursement_cents": record["actual_reimbursement_cents"],
        "reimbursement_variance_cents": record["reimbursement_variance_cents"],
        "departed_at": clock.iso(record["departed_at"]),
        "returned_at": clock.iso(record["returned_at"]),
        "recalled_reason": record["recalled_reason"],
    }
    payload.update(_common(record))
    return payload


def dispatch_stop(record):
    payload = {
        "dispatch_id": record["dispatch_id"],
        "order_id": record["order_id"],
        "sequence": record["sequence"],
        "hot_bag_slots": record["hot_bag_slots"],
        "planned_miles": calc.miles_out(record["planned_miles"]),
        "planned_drive_minutes": record["planned_drive_minutes"],
        "actual_miles": calc.miles_out(record["actual_miles"]),
        "status": record["status"],
        "arrived_at": clock.iso(record["arrived_at"]),
        "cash_collected_cents": record["cash_collected_cents"],
    }
    payload.update(_common(record))
    return payload


def reimbursement_line(record):
    payload = {
        "dispatch_id": record["dispatch_id"],
        "driver_id": record["driver_id"],
        "order_id": record["order_id"],
        "line_type": record["line_type"],
        "basis": record["basis"],
        "amount_cents": record["amount_cents"],
        "sequence_snapshot": record["sequence_snapshot"],
        "status": record["status"],
    }
    payload.update(_common(record))
    return payload


def safe_drop(record):
    payload = {
        "driver_id": record["driver_id"],
        "amount_cents": record["amount_cents"],
        "envelope_number": record["envelope_number"],
        "status": record["status"],
        "voided_reason": record["voided_reason"],
        "voided_at": clock.iso(record["voided_at"]),
    }
    payload.update(_common(record))
    return payload


def complaint(record):
    payload = {
        "order_id": record["order_id"],
        "category": record["category"],
        "description": record["description"],
        "status": record["status"],
        "proposed_remedy_cents": record["proposed_remedy_cents"],
        "remedy_basis": record["remedy_basis"],
        "driver_chargeable": record["driver_chargeable"],
        "clawback_cents": record["clawback_cents"],
        "logged_by_user_id": record["logged_by_user_id"],
        "resolved_by_user_id": record["resolved_by_user_id"],
        "resolved_at": clock.iso(record["resolved_at"]),
    }
    payload.update(_common(record))
    return payload


SERIALIZERS = {
    "store": store,
    "zone_version": zone_version,
    "service_address": service_address,
    "address_dispute": address_dispute,
    "driver": driver,
    "vehicle_cost_model": vehicle_cost_model,
    "mvr_check": mvr_check,
    "insurance_verification": insurance_verification,
    "order": order,
    "dispatch": dispatch,
    "dispatch_stop": dispatch_stop,
    "reimbursement_line": reimbursement_line,
    "safe_drop": safe_drop,
    "complaint": complaint,
}
