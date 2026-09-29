"""Entity views.  Derived fields are computed live at read time (PRD 2.11)."""

import calc
import domain
from store import db


def _common(record):
    return {
        "id": record["id"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "version": record["version"],
    }


def _immutable(record):
    return {"id": record["id"], "created_at": record["created_at"]}


# --------------------------------------------------------------------------

def shipper_account(record):
    out = _common(record)
    out.update({
        "account_number": record["account_number"],
        "name": record["name"],
        "billing_email": record["billing_email"],
        "status": record["status"],
    })
    out.update(domain.ledger_aggregates(record["id"]))
    return out


def rate_contract(record):
    out = _common(record)
    out.update({
        "shipper_id": record["shipper_id"],
        "supersedes_contract_id": record["supersedes_contract_id"],
        "effective_from": record["effective_from"],
        "effective_to": record["effective_to"],
        "dim_divisor": record["dim_divisor"],
        "min_charge_cents": record["min_charge_cents"],
        "rate_table": record["rate_table"],
        "tier_discount_table": record["tier_discount_table"],
        "accessorial_rate_overrides": record["accessorial_rate_overrides"],
        "residential_waived": record["residential_waived"],
        "status": record["status"],
        "activated_at": record["activated_at"],
    })
    return out


def service_level(record):
    out = _immutable(record)
    out.update({
        "code": record["code"],
        "name": record["name"],
        "guarantee_hours": record["guarantee_hours"],
        "guaranteed": record["guaranteed"],
    })
    return out


def surcharge_window(record):
    out = _common(record)
    out.update({
        "code": record["code"],
        "kind": record["kind"],
        "service_level_id": record["service_level_id"],
        "start_date": record["start_date"],
        "end_date": record["end_date"],
        "per_package_cents": record["per_package_cents"],
        "oversize_add_cents": record["oversize_add_cents"],
        "status": record["status"],
    })
    return out


def shipment(record):
    out = _common(record)
    out.update({
        "shipper_id": record["shipper_id"],
        "service_level_id": record["service_level_id"],
        "contract_id": record["contract_id"],
        "tracking_number": record["tracking_number"],
        "zone": record["zone"],
        "delivery_area_class": record["delivery_area_class"],
        "residential_declared": record["residential_declared"],
        "non_conveyable_declared": record["non_conveyable_declared"],
        "declared_length_in": record["declared_length_in"],
        "declared_width_in": record["declared_width_in"],
        "declared_height_in": record["declared_height_in"],
        "declared_weight_lbs": record["declared_weight_lbs"],
        "picked_up_at": record["picked_up_at"],
        "pickup_date": record["pickup_date"],
        "divisor_used": record["divisor_used"],
        "declared_cube_in3": record["declared_cube_in3"],
        "preliminary_dim_weight_lbs": record["preliminary_dim_weight_lbs"],
        "preliminary_billable_weight_lbs": record["preliminary_billable_weight_lbs"],
        "preliminary_basis": record["preliminary_basis"],
        "scanned_cube_in3": record["scanned_cube_in3"],
        "final_dim_weight_lbs": record["final_dim_weight_lbs"],
        "final_billable_weight_lbs": record["final_billable_weight_lbs"],
        "final_basis": record["final_basis"],
        "billable_weight_lbs": record["billable_weight_lbs"],
        "dim_variance_pct": calc.as_number(record["dim_variance_pct"]),
        "weight_variance_lbs": calc.as_number(record["weight_variance_lbs"]),
        "oversize_flag": record["oversize_flag"],
        "additional_handling_flag": record["additional_handling_flag"],
        "measurement_status": record["measurement_status"],
        "movement_status": record["movement_status"],
        "billing_status": record["billing_status"],
        "delivered_at": record["delivered_at"],
        "guarantee_deadline_utc": record["guarantee_deadline_utc"],
        "accessorial_total_cents": domain.shipment_accessorial_total(record["id"]),
    })
    return out


def dimension_scan(record):
    out = _immutable(record)
    out.update({
        "shipment_id": record["shipment_id"],
        "scan_source": record["scan_source"],
        "scanned_length_in": record["scanned_length_in"],
        "scanned_width_in": record["scanned_width_in"],
        "scanned_height_in": record["scanned_height_in"],
        "scanned_weight_lbs": record["scanned_weight_lbs"],
        "non_conveyable_observed": record["non_conveyable_observed"],
        "scanned_cube_in3": record["scanned_cube_in3"],
        "dim_variance_pct": calc.as_number(record["dim_variance_pct"]),
        "weight_variance_lbs": calc.as_number(record["weight_variance_lbs"]),
        "tolerance_status": record["tolerance_status"],
        "captured_at": record["captured_at"],
    })
    return out


def accessorial_charge(record):
    out = _common(record)
    out.update({
        "shipment_id": record["shipment_id"],
        "code": record["code"],
        "amount_cents": record["amount_cents"],
        "source": record["source"],
        "status": record["status"],
        "reason": record["reason"],
        "assessed_basis": record["assessed_basis"],
    })
    return out


def invoice(record):
    pending = domain.invoice_pending_count(record["id"])
    out = _common(record)
    out.update({
        "shipper_id": record["shipper_id"],
        "period_start": record["period_start"],
        "period_end": record["period_end"],
        "status": record["status"],
        "line_count": len(domain.lines_of_invoice(record["id"])),
        "transportation_subtotal_cents": record["transportation_subtotal_cents"],
        "accessorial_subtotal_cents": record["accessorial_subtotal_cents"],
        "gross_charges_cents": record["gross_charges_cents"],
        "tier_discount_bps": record["tier_discount_bps"],
        "tier_discount_cents": record["tier_discount_cents"],
        "adjustment_total_cents": domain.invoice_adjustment_total(record["id"]),
        "net_amount_cents": domain.invoice_net_amount(record),
        "pending_adjustment_count": pending,
        "has_pending_adjustments": pending > 0,
        "issued_at": record["issued_at"],
        "dispute_deadline_utc": record["dispute_deadline_utc"],
        "payment_reference": record["payment_reference"],
    })
    return out


def invoice_line(record):
    adjustment_total = domain.line_adjustment_total(record["id"])
    out = _common(record)
    out.update({
        "invoice_id": record["invoice_id"],
        "shipment_id": record["shipment_id"],
        "billable_weight_lbs": record["billable_weight_lbs"],
        "billable_weight_basis": record["billable_weight_basis"],
        "rate_cents_per_lb": record["rate_cents_per_lb"],
        "transportation_base_cents": record["transportation_base_cents"],
        "surcharge_cents": record["surcharge_cents"],
        "accessorial_total_cents": record["accessorial_total_cents"],
        "base_line_total_cents": record["base_line_total_cents"],
        "adjustment_total_cents": adjustment_total,
        "line_total_cents": record["base_line_total_cents"] + adjustment_total,
        "voided": record["voided"],
    })
    return out


def billing_adjustment(record):
    out = _common(record)
    out.update({
        "invoice_line_id": record["invoice_line_id"],
        "dispute_id": record["dispute_id"],
        "guarantee_claim_id": record["guarantee_claim_id"],
        "reason": record["reason"],
        "delta_cents": record["delta_cents"],
        "status": record["status"],
        "created_by_user_id": record["created_by_user_id"],
        "applied_by_user_id": record["applied_by_user_id"],
        "note": record["note"],
        "applied_at": record["applied_at"],
    })
    return out


def dispute(record):
    out = _common(record)
    out.update({
        "invoice_line_id": record["invoice_line_id"],
        "shipper_user_id": record["shipper_user_id"],
        "claim_type": record["claim_type"],
        "disputed_codes": record["disputed_codes"],
        "claimed_reason": record["claimed_reason"],
        "status": record["status"],
        "round_count": record["round_count"],
        "required_item_type": record["required_item_type"],
        "accepted_evidence_count": domain.accepted_evidence_count(record["id"]),
        "granted_credit_cents": record["granted_credit_cents"],
        "resolved_at": record["resolved_at"],
    })
    return out


def evidence_item(record):
    out = _immutable(record)
    out.update({
        "dispute_id": record["dispute_id"],
        "item_type": record["item_type"],
        "reference": record["reference"],
        "submitted_by_user_id": record["submitted_by_user_id"],
        "accepted": record["accepted"],
    })
    return out


def guarantee_claim(record):
    out = _common(record)
    out.update({
        "shipment_id": record["shipment_id"],
        "invoice_line_id": record["invoice_line_id"],
        "claimed_reason": record["claimed_reason"],
        "guarantee_deadline_utc": record["guarantee_deadline_utc"],
        "delivered_at": record["delivered_at"],
        "late_by_seconds": record["late_by_seconds"],
        "candidate_refund_cents": record["candidate_refund_cents"],
        "refund_cents": record["refund_cents"],
        "status": record["status"],
        "filed_by_user_id": record["filed_by_user_id"],
        "adjudicated_at": record["adjudicated_at"],
    })
    return out


SERIALIZERS = {
    "shipper_accounts": shipper_account,
    "rate_contracts": rate_contract,
    "service_levels": service_level,
    "surcharge_windows": surcharge_window,
    "shipments": shipment,
    "dimension_scans": dimension_scan,
    "accessorial_charges": accessorial_charge,
    "invoices": invoice,
    "invoice_lines": invoice_line,
    "billing_adjustments": billing_adjustment,
    "disputes": dispute,
    "evidence_items": evidence_item,
    "guarantee_claims": guarantee_claim,
}
