"""Resource serialisation.  Derived fields are recomputed on every read."""
import clock
import derive
from store import db

COMMON = ("id", "created_at", "updated_at", "version")


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": clock.iso(rec["created_at"]),
        "updated_at": clock.iso(rec["updated_at"]),
        "version": rec["version"],
    }


def client(rec):
    client_id = rec["id"]
    deposits = derive.retainer_deposits_total(client_id)
    drawn = derive.retainer_drawn(client_id)
    out = _common(rec)
    out.update({
        "full_name": rec["full_name"],
        "residence_setting": rec["residence_setting"],
        "status": rec["status"],
        "capacity_status": rec["capacity_status"],
        "capacity_basis": rec["capacity_basis"],
        "risk_posture": derive.risk_posture(rec),
        "acuity_score": derive.acuity_score(client_id),
        "billing_increment_min": rec["billing_increment_min"],
        "travel_billing_pct": rec["travel_billing_pct"],
        "retainer_floor_cents": rec["retainer_floor_cents"],
        "authorized_concurrent_caregivers": rec["authorized_concurrent_caregivers"],
        "retainer_deposits_total_cents": deposits,
        "retainer_balance_cents": deposits - drawn,
        "unbilled_accrual_cents": derive.unbilled_accrual(client_id),
        "authorized_coverage_hours": derive.authorized_coverage_hours(client_id),
        "protective_escalation_status":
            derive.protective_escalation_status(client_id),
    })
    return out


def care_manager(rec):
    out = _common(rec)
    out.update({
        "full_name": rec["full_name"],
        "credential": rec["credential"],
        "hourly_rate_cents": rec["hourly_rate_cents"],
        "is_supervisor": rec["is_supervisor"],
        "active": rec["active"],
    })
    return out


def vendor(rec):
    out = _common(rec)
    out.update({
        "name": rec["name"],
        "vendor_type": rec["vendor_type"],
        "has_referral_relationship": rec["has_referral_relationship"],
        "referral_fee_pct": rec["referral_fee_pct"],
        "standing": rec["standing"],
    })
    return out


def contact(rec):
    status, days_overdue = derive.report_cadence(rec)
    out = _common(rec)
    out.update({
        "client_id": rec["client_id"],
        "full_name": rec["full_name"],
        "contact_role": rec["contact_role"],
        "is_surrogate_decision_maker": rec["is_surrogate_decision_maker"],
        "is_long_distance": rec["is_long_distance"],
        "reporting_cadence_days": rec["reporting_cadence_days"],
        "last_report_sent_at": clock.iso(rec["last_report_sent_at"]),
        "reports_sent_count": rec["reports_sent_count"],
        "report_status": status,
        "days_overdue": days_overdue,
    })
    return out


def assessment(rec):
    out = _common(rec)
    out.update({
        "client_id": rec["client_id"],
        "care_manager_id": rec["care_manager_id"],
        "reviewed_by_care_manager_id": rec["reviewed_by_care_manager_id"],
        "domain_scores": dict(rec["domain_scores"]),
        "narrative": rec["narrative"],
        "status": rec["status"],
        "revision_round": rec["revision_round"],
        "screening_acuity": rec["screening_acuity"],
        "comprehensive_acuity": rec["comprehensive_acuity"],
        "accepted_at": clock.iso(rec["accepted_at"]),
    })
    return out


def care_plan(rec):
    out = _common(rec)
    out.update({
        "client_id": rec["client_id"],
        "source_assessment_id": rec["source_assessment_id"],
        "supersedes_care_plan_id": rec["supersedes_care_plan_id"],
        "approved_by_contact_id": rec["approved_by_contact_id"],
        "goals": list(rec["goals"]),
        "review_interval_days": rec["review_interval_days"],
        "pinned_assessment_version": rec["pinned_assessment_version"],
        "status": rec["status"],
        "rejection_rounds": rec["rejection_rounds"],
        "coverage_gap_flag": derive.coverage_gap_flag(rec),
        "activated_at": clock.iso(rec["activated_at"]),
    })
    return out


def authorization(rec):
    out = _common(rec)
    out.update({
        "care_plan_id": rec["care_plan_id"],
        "vendor_id": rec["vendor_id"],
        "client_id": rec["client_id"],
        "authorizing_decision_id": rec["authorizing_decision_id"],
        "coi_acknowledged_by_contact_id": rec["coi_acknowledged_by_contact_id"],
        "coverage_start": clock.iso(rec["coverage_start"]),
        "coverage_end": clock.iso(rec["coverage_end"]),
        "concurrent_caregivers": rec["concurrent_caregivers"],
        "hourly_cost_cents": rec["hourly_cost_cents"],
        "coverage_hours": rec["coverage_hours"],
        "base_cost_cents": rec["base_cost_cents"],
        "coordination_fee_cents": rec["coordination_fee_cents"],
        "total_projected_cost_cents": rec["total_projected_cost_cents"],
        "auth_status": rec["auth_status"],
        "coi_status": rec["coi_status"],
        "disclosure_text": rec["disclosure_text"],
        "suspension_reason": rec["suspension_reason"],
        "termination_reason": rec["termination_reason"],
    })
    return out


def conference(rec):
    out = _common(rec)
    out.update({
        "client_id": rec["client_id"],
        "scheduled_start": clock.iso(rec["scheduled_start"]),
        "scheduled_end": clock.iso(rec["scheduled_end"]),
        "invited_contact_ids": list(rec["invited_contact_ids"]),
        "attended_contact_ids": list(rec["attended_contact_ids"]),
        "agenda": rec["agenda"],
        "status": rec["status"],
        "reschedule_count": rec["reschedule_count"],
        "quorum_met": rec["quorum_met"],
        "surrogate_present": derive.surrogate_present_of(rec),
        "convened_at": clock.iso(rec["convened_at"]),
    })
    return out


def decision(rec):
    out = _common(rec)
    out.update({
        "family_conference_id": rec["family_conference_id"],
        "decided_by_contact_id": rec["decided_by_contact_id"],
        "decision_type": rec["decision_type"],
        "decision_text": rec["decision_text"],
        "capacity_basis": rec["capacity_basis"],
        "status": rec["status"],
        "ratified_at": clock.iso(rec["ratified_at"]),
        "escalated_at": clock.iso(rec["escalated_at"]),
        "rescinded_reason": rec["rescinded_reason"],
    })
    return out


def episode(rec):
    out = _common(rec)
    out.update({
        "client_id": rec["client_id"],
        "assigned_care_manager_id": rec["assigned_care_manager_id"],
        "trigger_type": rec["trigger_type"],
        "hospital_name": rec["hospital_name"],
        "opened_at": clock.iso(rec["opened_at"]),
        "stabilized_at": clock.iso(rec["stabilized_at"]),
        "discharge_at": clock.iso(rec["discharge_at"]),
        "closed_at": clock.iso(rec["closed_at"]),
        "status": rec["status"],
        "readmission_count": rec["readmission_count"],
    })
    return out


def time_entry(rec):
    out = _common(rec)
    out.update({
        "client_id": rec["client_id"],
        "care_manager_id": rec["care_manager_id"],
        "approved_by_care_manager_id": rec["approved_by_care_manager_id"],
        "invoice_id": rec["invoice_id"],
        "crisis_episode_id": rec["crisis_episode_id"],
        "service_type": rec["service_type"],
        "start_at": clock.iso(rec["start_at"]),
        "end_at": clock.iso(rec["end_at"]),
        "service_location_id": rec["service_location_id"],
        "service_date": rec["service_date"],
        "raw_minutes": rec["raw_minutes"],
        "rounded_minutes": rec["rounded_minutes"],
        "rate_multiplier": float(rec["rate_multiplier"]),
        "after_hours_factor": float(rec["after_hours_factor"]),
        "billable_amount_cents": rec["billable_amount_cents"],
        "status": rec["status"],
        "note": rec["note"],
    })
    return out


def invoice(rec):
    out = _common(rec)
    out.update({
        "client_id": rec["client_id"],
        "period_start": rec["period_start"],
        "period_end": rec["period_end"],
        "amount_paid_cents": rec["amount_paid_cents"],
        "status": rec["status"],
        "issued_at": clock.iso(rec["issued_at"]),
        "voided_reason": rec["voided_reason"],
    })
    if rec["status"] == "DRAFT":
        computed = derive.invoice_totals(rec, "PROVISIONAL")
    else:
        computed = {
            "variant": rec["variant"],
            "line_entry_ids": list(rec["line_entry_ids"]),
            "line_subtotal_cents": rec["line_subtotal_cents"],
            "admin_fee_cents": rec["admin_fee_cents"],
            "total_due_cents": rec["total_due_cents"],
            "retainer_applied_cents": rec["retainer_applied_cents"],
            "balance_due_cents": rec["balance_due_cents"],
        }
    out.update(computed)
    return out
