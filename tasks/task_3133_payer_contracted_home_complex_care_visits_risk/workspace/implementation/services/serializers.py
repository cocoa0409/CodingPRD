"""Serializers — shape each stored entity into its API response form.

All entities carry the common system fields id/created_at/updated_at/version
per PRD §2.4. None values serialize as JSON null.
"""


def care_program(p):
    return {
        "id": p["id"],
        "program_code": p["program_code"],
        "display_name": p["display_name"],
        "service_geography_zips": p["service_geography_zips"],
        "urgent_response_sla_hours": p["urgent_response_sla_hours"],
        "current_period_index": p["current_period_index"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def payer_contract(c):
    return {
        "id": c["id"],
        "care_program_id": c["care_program_id"],
        "payer_name": c["payer_name"],
        "contract_effective_date": c["contract_effective_date"],
        "contract_expiration_date": c["contract_expiration_date"],
        "payment_model": c["payment_model"],
        "pmpm_rate_cents": c.get("pmpm_rate_cents"),
        "shared_savings_baseline_pmpm_cents": c.get("shared_savings_baseline_pmpm_cents"),
        "shared_savings_split_pct": c.get("shared_savings_split_pct"),
        "quality_withhold_pct": c.get("quality_withhold_pct"),
        "min_performance_threshold": c.get("min_performance_threshold"),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def pcp_provider(p):
    return {
        "id": p["id"],
        "care_program_id": p["care_program_id"],
        "npi": p["npi"],
        "full_name": p["full_name"],
        "practice_name": p["practice_name"],
        "notification_opt_in": p["notification_opt_in"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def clinician(c):
    return {
        "id": c["id"],
        "care_program_id": c["care_program_id"],
        "full_name": c["full_name"],
        "discipline": c["discipline"],
        "home_zip": c["home_zip"],
        "max_daily_visits": c["max_daily_visits"],
        "active_daily_visit_count": c["active_daily_visit_count"],
        "urgent_response_qualified": c["urgent_response_qualified"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def member(m):
    return {
        "id": m["id"],
        "care_program_id": m["care_program_id"],
        "payer_contract_id": m["payer_contract_id"],
        "member_external_id": m["member_external_id"],
        "full_name": m["full_name"],
        "date_of_birth": m["date_of_birth"],
        "address_zip": m["address_zip"],
        "pcp_provider_id": m["pcp_provider_id"],
        "chronic_condition_codes": m["chronic_condition_codes"],
        "prior_ed_visits_12mo": m["prior_ed_visits_12mo"],
        "prior_inpatient_admits_12mo": m["prior_inpatient_admits_12mo"],
        "burden_score_provisional": m["burden_score_provisional"],
        "burden_score_final": m.get("burden_score_final"),
        "risk_tier": m.get("risk_tier"),
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def enrollment(e):
    return {
        "id": e["id"],
        "member_id": e["member_id"],
        "outreach_channel": e["outreach_channel"],
        "outreach_attempts": e["outreach_attempts"],
        "consent_recorded_at": e.get("consent_recorded_at"),
        "consent_document_id": e.get("consent_document_id"),
        "disenrollment_reason": e.get("disenrollment_reason"),
        "status": e["status"],
        "is_current": e["is_current"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def care_team(t):
    return {
        "id": t["id"],
        "enrollment_id": t["enrollment_id"],
        "member_id": t["member_id"],
        "primary_np_id": t.get("primary_np_id"),
        "social_worker_id": t.get("social_worker_id"),
        "behavioral_clinician_id": t.get("behavioral_clinician_id"),
        "status": t["status"],
        "composition_complete": t["composition_complete"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def visit(v):
    return {
        "id": v["id"],
        "enrollment_id": v["enrollment_id"],
        "member_id": v["member_id"],
        "clinician_id": v.get("clinician_id"),
        "visit_type": v["visit_type"],
        "scheduled_start": v["scheduled_start"],
        "scheduled_end": v["scheduled_end"],
        "actual_start": v.get("actual_start"),
        "actual_end": v.get("actual_end"),
        "cancellation_reason": v.get("cancellation_reason"),
        "reschedule_count": v["reschedule_count"],
        "status": v["status"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def assessment(a):
    return {
        "id": a["id"],
        "visit_id": a["visit_id"],
        "member_id": a["member_id"],
        "medication_reconciliation": a.get("medication_reconciliation"),
        "safety_evaluation": a.get("safety_evaluation"),
        "social_needs_screening": a.get("social_needs_screening"),
        "pcp_coordination_note": a.get("pcp_coordination_note"),
        "pcp_notified": a["pcp_notified"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def episode(e):
    return {
        "id": e["id"],
        "enrollment_id": e["enrollment_id"],
        "member_id": e["member_id"],
        "trigger_source": e["trigger_source"],
        "triggered_at": e["triggered_at"],
        "sla_deadline": e["sla_deadline"],
        "dispatched_clinician_id": e.get("dispatched_clinician_id"),
        "on_scene_at": e.get("on_scene_at"),
        "resolved_outcome": e.get("resolved_outcome"),
        "sla_met": e.get("sla_met"),
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def settlement(s):
    return {
        "id": s["id"],
        "payer_contract_id": s["payer_contract_id"],
        "period_index": s["period_index"],
        "enrolled_member_count": s["enrolled_member_count"],
        "gross_capitation_cents": s.get("gross_capitation_cents"),
        "gross_savings_share_cents": s.get("gross_savings_share_cents"),
        "quality_withhold_cents": s["quality_withhold_cents"],
        "withhold_released_cents": s.get("withhold_released_cents"),
        "net_payment_cents": s.get("net_payment_cents"),
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def medical_cost(c):
    return {
        "id": c["id"],
        "payer_contract_id": c["payer_contract_id"],
        "member_id": c["member_id"],
        "period_index": c["period_index"],
        "amount_cents": c["amount_cents"],
        "incurred_date": c["incurred_date"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }
