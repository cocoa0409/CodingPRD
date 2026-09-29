"""Entity serializers.  Field sets follow SCAFFOLD s1.1 exactly."""

from decimal import Decimal

import calc
from store import db


def _f(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(row, out):
    out["id"] = row["id"]
    out["created_at"] = row["created_at"]
    out["updated_at"] = row["updated_at"]
    out["version"] = row["version"]
    return out


def property_out(row):
    return _common(row, {
        "name": row["name"],
        "unit_count": row["unit_count"],
        "market_code": row["market_code"],
        "compactor_capacity_lbs": row["compactor_capacity_lbs"],
        "status": row["status"],
        "active_contract_id": row["active_contract_id"],
        "escalation_level": row["escalation_level"],
        "pending_fine_revenue_cents": row["pending_fine_revenue_cents"],
        "delinquent_resident_count": row["delinquent_resident_count"],
    })


def contract_out(row):
    return _common(row, {
        "property_id": row["property_id"],
        "per_unit_monthly_fee_cents": row["per_unit_monthly_fee_cents"],
        "property_revenue_share_bps": row["property_revenue_share_bps"],
        "service_night_days": list(row["service_night_days"]),
        "effective_from": row["effective_from"],
        "effective_to": row["effective_to"],
        "sla_missed_threshold_bps": row["sla_missed_threshold_bps"],
        "status": row["status"],
        "last_invoiced_period": row["last_invoiced_period"],
    })


def resident_out(row):
    return _common(row, {
        "property_id": row["property_id"],
        "unit_number": row["unit_number"],
        "full_name": row["full_name"],
        "move_in_date": row["move_in_date"],
        "move_out_date": row["move_out_date"],
        "fee_passthrough_enabled": row["fee_passthrough_enabled"],
        "status": row["status"],
        "collections_status": row["collections_status"],
        "fines_outstanding_cents": row["fines_outstanding_cents"],
        "fines_assessed_this_period_cents": calc.fines_assessed_this_period_cents(row["id"]),
    })


def contractor_out(row):
    return _common(row, {
        "legal_name": row["legal_name"],
        "equipment_provided_by_company": row["equipment_provided_by_company"],
        "sets_own_schedule": row["sets_own_schedule"],
        "works_exclusively": row["works_exclusively"],
        "weekly_committed_hours": row["weekly_committed_hours"],
        "tax_form_type": row["tax_form_type"],
        "direct_deposit_on_file": row["direct_deposit_on_file"],
        "onboarding_status": row["onboarding_status"],
        "classification": row["classification"],
        "classification_basis": row["classification_basis"],
        "control_score": row["control_score"],
        "observed_weekly_hours": _f(row["observed_weekly_hours"]),
        "background_checked_by_user_id": row["background_checked_by_user_id"],
        "created_by_user_id": row["created_by_user_id"],
        "deactivation_reason": row["deactivation_reason"],
    })


def night_out(row):
    return _common(row, {
        "contract_id": row["contract_id"],
        "rescheduled_from_night_id": row["rescheduled_from_night_id"],
        "service_date": row["service_date"],
        "service_window_start": row["service_window_start"],
        "service_window_end": row["service_window_end"],
        "seasonal_volume_index": row["seasonal_volume_index"],
        "holiday_flag": row["holiday_flag"],
        "verification_status": row["verification_status"],
        "billing_status": row["billing_status"],
        "expected_door_count": row["expected_door_count"],
        "scanned_door_count": row["scanned_door_count"],
        "coverage_bps": row["coverage_bps"],
        "assigned_unit_coverage_count": row["assigned_unit_coverage_count"],
        "reschedule_action": row["reschedule_action"],
    })


def route_out(row):
    return _common(row, {
        "service_night_id": row["service_night_id"],
        "contractor_id": row["contractor_id"],
        "unit_from": row["unit_from"],
        "unit_to": row["unit_to"],
        "unit_coverage_count": row["unit_coverage_count"],
        "status": row["status"],
        "accepted_at": row["accepted_at"],
        "completed_at": row["completed_at"],
        "scan_count": row["scan_count"],
        "abandon_reason": row["abandon_reason"],
    })


def scan_out(row):
    return _common(row, {
        "route_assignment_id": row["route_assignment_id"],
        "service_night_id": row["service_night_id"],
        "resident_id": row["resident_id"],
        "scan_result": row["scan_result"],
        "container_type": row["container_type"],
        "non_compliance_type": row["non_compliance_type"],
        "tag_status": row["tag_status"],
        "offense_ordinal": row["offense_ordinal"],
        "scanned_at": row["scanned_at"],
        "void_reason": row["void_reason"],
    })


def fine_out(row):
    return _common(row, {
        "scan_id": row["scan_id"],
        "resident_id": row["resident_id"],
        "tag_type": row["tag_type"],
        "offense_ordinal": row["offense_ordinal"],
        "base_cents": row["base_cents"],
        "escalation_multiplier": _f(row["escalation_multiplier"]),
        "seasonal_uplift_applied": row["seasonal_uplift_applied"],
        "amount_cents": row["amount_cents"],
        "uncapped_amount_cents": row["uncapped_amount_cents"],
        "origin": row["origin"],
        "status": row["status"],
        "dispute_round": row["dispute_round"],
        "assessed_by_user_id": row["assessed_by_user_id"],
        "adjudicated_by_user_id": row["adjudicated_by_user_id"],
        "dispute_reason": row["dispute_reason"],
    })


def incident_out(row):
    return _common(row, {
        "property_id": row["property_id"],
        "incident_type": row["incident_type"],
        "description": row["description"],
        "reported_by_role": row["reported_by_role"],
        "reported_by_user_id": row["reported_by_user_id"],
        "reported_at": row["reported_at"],
        "ack_deadline_at": row["ack_deadline_at"],
        "status": row["status"],
        "acknowledged_at": row["acknowledged_at"],
        "escalated_at": row["escalated_at"],
        "resolved_at": row["resolved_at"],
        "resolution_note": row["resolution_note"],
    })


def statement_out(row):
    """A DRAFT statement is re-read as PROVISIONAL on every GET (PRD s3.8)."""
    money = {
        "gross_passthrough_cents": row["gross_passthrough_cents"],
        "scheduled_night_count": row["scheduled_night_count"],
        "missed_equivalent_nights": row["missed_equivalent_nights"],
        "missed_service_bps": row["missed_service_bps"],
        "sla_credit_rate_bps": row["sla_credit_rate_bps"],
        "missed_service_credit_cents": row["missed_service_credit_cents"],
        "property_revenue_share_cents": row["property_revenue_share_cents"],
        "net_due_from_property_cents": row["net_due_from_property_cents"],
    }
    if row["status"] == "DRAFT":
        contract = db.contracts.get(row["contract_id"])
        prop = db.properties.get(contract["property_id"]) if contract else None
        if contract is not None and prop is not None:
            money = calc.statement_settlement(contract, prop, row["billing_period"], "PROVISIONAL")
    out = {
        "contract_id": row["contract_id"],
        "superseded_statement_id": row["superseded_statement_id"],
        "billing_period": row["billing_period"],
        "variant": row["variant"],
        "gross_passthrough_cents": money["gross_passthrough_cents"],
        "scheduled_night_count": money["scheduled_night_count"],
        "missed_equivalent_nights": _f(money["missed_equivalent_nights"]),
        "missed_service_bps": money["missed_service_bps"],
        "sla_credit_rate_bps": money["sla_credit_rate_bps"],
        "missed_service_credit_cents": money["missed_service_credit_cents"],
        "property_revenue_share_cents": money["property_revenue_share_cents"],
        "net_due_from_property_cents": money["net_due_from_property_cents"],
        "status": row["status"],
        "created_by_user_id": row["created_by_user_id"],
        "issued_by_user_id": row["issued_by_user_id"],
        "void_reason": row["void_reason"],
    }
    return _common(row, out)
