"""Resource serialization.  Derived fields are computed at read time."""
import derive
from store import db, sort_created


def _common(row, out):
    out["id"] = row["id"]
    out["created_at"] = row["created_at"]
    if "version" in row:
        out["updated_at"] = row["updated_at"]
        out["version"] = row["version"]
    return out


def language_out(row):
    return _common(
        row,
        {
            "code": row["code"],
            "name": row["name"],
            "tier_class": row["tier_class"],
            "oral_exam_available": row["oral_exam_available"],
            "telephonic_vendor_available": row["telephonic_vendor_available"],
            "active_credentialed_count": derive.language_active_count(row["id"]),
        },
    )


def courthouse_out(row):
    encumbered, obligated, available = derive.ledger(row)
    return _common(
        row,
        {
            "name": row["name"],
            "county_code": row["county_code"],
            "courtroom_count": row["courtroom_count"],
            "remote_equipment_tier": row["remote_equipment_tier"],
            "vri_concurrent_capacity": row["vri_concurrent_capacity"],
            "status": row["status"],
            "pay_budget_cents": row["pay_budget_cents"],
            "encumbered_pay_cents": encumbered,
            "obligated_pay_cents": obligated,
            "available_pay_cents": available,
        },
    )


def rate_schedule_out(row):
    return _common(
        row,
        {
            "effective_from": row["effective_from"],
            "effective_through": row["effective_through"],
            "master_hourly_cents": row["master_hourly_cents"],
            "certified_hourly_cents": row["certified_hourly_cents"],
            "registered_hourly_cents": row["registered_hourly_cents"],
            "provisional_hourly_cents": row["provisional_hourly_cents"],
            "minimum_call_hours": row["minimum_call_hours"],
            "travel_mileage_rate_cents": row["travel_mileage_rate_cents"],
            "travel_free_radius_miles": row["travel_free_radius_miles"],
            "remote_rate_multiplier": row["remote_rate_multiplier"],
            "late_cancellation_hours": row["late_cancellation_hours"],
            "late_cancellation_pay_hours": row["late_cancellation_pay_hours"],
            "rare_premium_low_pct": row["rare_premium_low_pct"],
            "rare_premium_high_pct": row["rare_premium_high_pct"],
            "rare_premium_bracket_cents": row["rare_premium_bracket_cents"],
        },
    )


def interpreter_out(row):
    rolling, lifetime = derive.quality_scores(row["id"])
    pending, paid = derive.interpreter_pay(row["id"])
    return _common(
        row,
        {
            "full_name": row["full_name"],
            "email": row["email"],
            "phone": row["phone"],
            "home_county_code": row["home_county_code"],
            "accepts_in_person": row["accepts_in_person"],
            "accepts_remote": row["accepts_remote"],
            "roster_status": row["roster_status"],
            "ethics_training_status": row["ethics_training_status"],
            "ethics_completed_on": row["ethics_completed_on"],
            "credential_tier": derive.credential_tier(row["id"]),
            "credentialed_language_ids": derive.credentialed_language_ids(row["id"]),
            "complaint_points": derive.complaint_points(row["id"]),
            "rolling_12_month_score": rolling,
            "lifetime_score": lifetime,
            "pending_pay_cents": pending,
            "paid_pay_cents": paid,
            "suspension_through": row["suspension_through"],
        },
    )


def attempts_of(credential_id, exam_type=None):
    rows = [
        a
        for a in db.exam_attempts.values()
        if a["credential_id"] == credential_id
        and (exam_type is None or a["exam_type"] == exam_type)
    ]
    return sorted(rows, key=lambda a: (a["taken_on"], a["created_at"], a["_seq"]))


def credential_out(row):
    written = attempts_of(row["id"], "WRITTEN")
    oral = attempts_of(row["id"], "ORAL")
    return _common(
        row,
        {
            "interpreter_id": row["interpreter_id"],
            "language_id": row["language_id"],
            "target_tier": row["target_tier"],
            "tier": row["tier"],
            "status": row["status"],
            "written_best_score": max([a["score"] for a in written]) if written else None,
            "oral_best_score": max([a["score"] for a in oral]) if oral else None,
            "written_attempt_count": len(written),
            "oral_attempt_count": len(oral),
            "issued_on": row["issued_on"],
            "expires_on": row["expires_on"],
            "grace_through": row["grace_through"],
            "cycle_credit_hours": row["cycle_credit_hours"],
            "renewal_count": row["renewal_count"],
        },
    )


def exam_attempt_out(row):
    return _common(
        row,
        {
            "credential_id": row["credential_id"],
            "exam_type": row["exam_type"],
            "score": row["score"],
            "taken_on": row["taken_on"],
            "attempt_ordinal": row["attempt_ordinal"],
            "result": row["result"],
        },
    )


def hearing_out(row):
    return _common(
        row,
        {
            "courthouse_id": row["courthouse_id"],
            "language_id": row["language_id"],
            "case_number": row["case_number"],
            "hearing_type": row["hearing_type"],
            "in_custody": row["in_custody"],
            "scheduled_start": row["scheduled_start"],
            "scheduled_end": row["scheduled_end"],
            "requested_delivery_mode": row["requested_delivery_mode"],
            "status": row["status"],
            "lead_time_days": row["lead_time_days"],
            "priority_score": row["priority_score"],
            "priority_class": row["priority_class"],
            "continuance_count": row["continuance_count"],
            "continuance_reason_code": row["continuance_reason_code"],
        },
    )


def assignment_out(row):
    return _common(
        row,
        {
            "hearing_id": row["hearing_id"],
            "interpreter_id": row["interpreter_id"],
            "credential_id": row["credential_id"],
            "credential_tier_snapshot": row["credential_tier_snapshot"],
            "delivery_mode": row["delivery_mode"],
            "vendor_served": row["vendor_served"],
            "estimated_one_way_miles": row["estimated_one_way_miles"],
            "actual_one_way_miles": row["actual_one_way_miles"],
            "service_status": row["service_status"],
            "compliance_status": row["compliance_status"],
            "check_in_utc": row["check_in_utc"],
            "actual_end_utc": row["actual_end_utc"],
            "cancel_reason_code": row["cancel_reason_code"],
        },
    )


def pay_claim_out(row):
    return _common(
        row,
        {
            "assignment_id": row["assignment_id"],
            "rate_schedule_id": row["rate_schedule_id"],
            "variant": row["variant"],
            "status": row["status"],
            "billable_hours": row["billable_hours"],
            "service_cents": row["service_cents"],
            "rare_premium_cents": row["rare_premium_cents"],
            "travel_cents": row["travel_cents"],
            "provisional_total_cents": row["provisional_total_cents"],
            "final_total_cents": row["final_total_cents"],
            "late_cancellation": row["late_cancellation"],
            "payment_reference": row["payment_reference"],
        },
    )


def complaint_out(row):
    return _common(
        row,
        {
            "interpreter_id": row["interpreter_id"],
            "assignment_id": row["assignment_id"],
            "category": row["category"],
            "severity": row["severity"],
            "narrative": row["narrative"],
            "filed_by_user_id": row["filed_by_user_id"],
            "reviewer_user_id": row["reviewer_user_id"],
            "reviewer_recommendation": row["reviewer_recommendation"],
            "adjudicator_user_id": row["adjudicator_user_id"],
            "disposition": row["disposition"],
            "status": row["status"],
            "adjudicated_at": row["adjudicated_at"],
            "appeal_filed_at": row["appeal_filed_at"],
            "remand_count": row["remand_count"],
        },
    )


def disciplinary_action_out(row):
    return _common(
        row,
        {
            "complaint_id": row["complaint_id"],
            "interpreter_id": row["interpreter_id"],
            "action_type": row["action_type"],
            "points": row["points"],
            "effective_from": row["effective_from"],
            "effective_through": row["effective_through"],
            "status": row["status"],
        },
    )


def unmet_need_report_out(row):
    return _common(
        row,
        {
            "courthouse_id": row["courthouse_id"],
            "period_start": row["period_start"],
            "period_end": row["period_end"],
            "resolved_hearing_count": row["resolved_hearing_count"],
            "served_hearing_count": row["served_hearing_count"],
            "unmet_hearing_count": row["unmet_hearing_count"],
            "rare_language_unmet_count": row["rare_language_unmet_count"],
            "coverage_rate_pct": row["coverage_rate_pct"],
            "compliance_status": row["compliance_status"],
            "by_language": row["by_language"],
        },
    )


def reports_of_courthouse(courthouse_id):
    rows = [
        r
        for r in db.unmet_need_reports.values()
        if r["courthouse_id"] == courthouse_id
    ]
    return sorted(rows, key=lambda r: (r["period_start"], r["created_at"], r["_seq"]))


def sorted_by(rows, *keys):
    return sorted(rows, key=lambda r: tuple(r[k] for k in keys) + (r["_seq"],))


def created_order(rows):
    return sort_created(rows)
