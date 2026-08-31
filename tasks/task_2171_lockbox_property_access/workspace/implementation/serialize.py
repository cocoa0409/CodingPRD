"""Resource serialisers — computed fields are derived live at read time."""
from core import db, num2
import calc


def _common(rec):
    return {
        "created_at": rec.get("created_at"),
        "updated_at": rec.get("updated_at"),
        "version": rec.get("version"),
    }


def association(rec):
    out = {
        "id": rec["id"],
        "name": rec["name"],
        "jurisdiction_code": rec["jurisdiction_code"],
        "temp_code_daily_limit": rec["temp_code_daily_limit"],
        "temp_code_overage_fee_cents": rec["temp_code_overage_fee_cents"],
        "removal_grace_days": rec["removal_grace_days"],
        "late_removal_daily_fee_cents": rec["late_removal_daily_fee_cents"],
        "late_removal_cap_cents": rec["late_removal_cap_cents"],
        "credential_cap_per_member": rec["credential_cap_per_member"],
        "grant_buffer_minutes": rec["grant_buffer_minutes"],
        "recovery_target_pct": rec["recovery_target_pct"],
        "recovery_rate_pct": rec["recovery_rate_pct"],
        "posture": calc.association_posture(rec["id"]),
    }
    out.update(calc.association_counters(rec["id"]))
    out.update(_common(rec))
    return out


def member(rec):
    out = {
        "id": rec["id"],
        "association_id": rec["association_id"],
        "full_name": rec["full_name"],
        "email": rec["email"],
        "dues_paid_through": rec["dues_paid_through"],
        "membership_status": rec["membership_status"],
        "active_credential_count": calc.active_credential_count(rec["id"]),
        "outstanding_balance_cents": calc.member_statement_balance(rec["id"]),
        "loss_report_count": calc.loss_report_count(rec["id"]),
        "temp_codes_issued_today": calc.temp_codes_issued_today(rec["id"]),
    }
    out.update(_common(rec))
    return out


def contractor(rec):
    out = {
        "id": rec["id"],
        "association_id": rec["association_id"],
        "company_name": rec["company_name"],
        "insurance_expires_on": rec["insurance_expires_on"],
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def lockbox(rec):
    out = {
        "id": rec["id"],
        "association_id": rec["association_id"],
        "serial_number": rec["serial_number"],
        "model": rec["model"],
        "replacement_cost_cents": rec["replacement_cost_cents"],
        "in_service_since": rec["in_service_since"],
        "status": rec["status"],
        "assigned_member_id": rec.get("assigned_member_id"),
        "current_listing_id": rec.get("current_listing_id"),
        "loss_type": rec.get("loss_type"),
        "police_report_number": rec.get("police_report_number"),
    }
    out.update(_common(rec))
    return out


def listing(rec):
    out = {
        "id": rec["id"],
        "association_id": rec["association_id"],
        "listing_agent_id": rec["listing_agent_id"],
        "address_line": rec["address_line"],
        "mls_number": rec["mls_number"],
        "concurrent_showing_limit": rec["concurrent_showing_limit"],
        "status": rec["status"],
        "close_date": rec.get("close_date"),
    }
    out.update(_common(rec))
    return out


def placement(rec):
    out = {
        "id": rec["id"],
        "lockbox_id": rec["lockbox_id"],
        "listing_id": rec["listing_id"],
        "placed_by_member_id": rec.get("placed_by_member_id"),
        "placement_status": rec["placement_status"],
        "billing_status": rec["billing_status"],
        "placed_at": rec.get("placed_at"),
        "removal_deadline": rec.get("removal_deadline"),
        "removed_at": rec.get("removed_at"),
        "late_days": rec.get("late_days", 0),
        "on_time": calc.placement_on_time(rec),
    }
    out.update(_common(rec))
    return out


def credential(rec):
    out = {
        "id": rec["id"],
        "member_id": rec["member_id"],
        "credential_type": rec["credential_type"],
        "expires_at": rec["expires_at"],
        "status": rec["status"],
        "suspended_by_cascade": rec.get("suspended_by_cascade", False),
        "supersede_reason": rec.get("supersede_reason"),
    }
    out.update(_common(rec))
    return out


def grant_uses_count(grant_id):
    return sum(
        1 for e in db.events.values()
        if e.get("grant_id") == grant_id and e["outcome"] == "GRANTED"
    )


def grant(rec):
    out = {
        "id": rec["id"],
        "listing_id": rec["listing_id"],
        "lockbox_id": rec["lockbox_id"],
        "issued_by_member_id": rec.get("issued_by_member_id"),
        "contractor_id": rec.get("contractor_id"),
        "supersedes_grant_id": rec.get("supersedes_grant_id"),
        "grant_type": rec["grant_type"],
        "window_start": rec["window_start"],
        "window_end": rec["window_end"],
        "max_uses": rec["max_uses"],
        "uses_count": grant_uses_count(rec["id"]),
        "access_code": rec.get("access_code"),
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def appointment_event_count(appointment_id):
    return sum(
        1 for e in db.events.values()
        if e.get("matched_appointment_id") == appointment_id
    )


def appointment(rec):
    out = {
        "id": rec["id"],
        "listing_id": rec["listing_id"],
        "showing_member_id": rec["showing_member_id"],
        "window_start": rec["window_start"],
        "window_end": rec["window_end"],
        "status": rec["status"],
        "access_event_count": appointment_event_count(rec["id"]),
        "cancel_reason": rec.get("cancel_reason"),
    }
    out.update(_common(rec))
    return out


def event(rec):
    return {
        "id": rec["id"],
        "lockbox_id": rec["lockbox_id"],
        "credential_id": rec.get("credential_id"),
        "grant_id": rec.get("grant_id"),
        "listing_id": rec.get("listing_id"),
        "matched_appointment_id": rec.get("matched_appointment_id"),
        "incident_review_id": rec.get("incident_review_id"),
        "actor_type": rec["actor_type"],
        "occurred_at": rec["occurred_at"],
        "outcome": rec["outcome"],
        "after_hours": rec["after_hours"],
        "risk_weight": rec["risk_weight"],
        "created_at": rec["created_at"],
    }


def review(rec):
    out = {
        "id": rec["id"],
        "association_id": rec["association_id"],
        "listing_id": rec.get("listing_id"),
        "lockbox_id": rec.get("lockbox_id"),
        "window_start": rec["window_start"],
        "window_end": rec["window_end"],
        "opened_by_user_id": rec.get("opened_by_user_id"),
        "closed_by_user_id": rec.get("closed_by_user_id"),
        "status": rec["status"],
        "event_count": rec.get("event_count", 0),
        "risk_score": rec.get("risk_score", 0.00),
        "severity": rec.get("severity", "LOW"),
        "findings": rec.get("findings"),
    }
    out.update(_common(rec))
    return out


def charge(rec):
    out = {
        "id": rec["id"],
        "member_id": rec.get("member_id"),
        "lockbox_id": rec.get("lockbox_id"),
        "placement_id": rec.get("placement_id"),
        "charge_type": rec["charge_type"],
        "amount_cents": rec["amount_cents"],
        "variant_applied": rec["variant_applied"],
        "basis": rec.get("basis"),
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out
