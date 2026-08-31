"""Record -> JSON serialisers. Internal keys prefixed with '_' are never emitted."""
from core import dec_to_float, fmt_instant


def _common(rec):
    out = {
        "id": rec["id"],
        "created_at": fmt_instant(rec["created_at"]),
    }
    if "updated_at" in rec:
        out["updated_at"] = fmt_instant(rec["updated_at"])
    if "version" in rec:
        out["version"] = rec["version"]
    return out


def member_out(rec):
    out = _common(rec)
    out.update({
        "external_member_id": rec["external_member_id"],
        "full_name": rec["full_name"],
        "birth_date": rec["birth_date"],
        "state_code": rec["state_code"],
        "chronic_condition_count": rec["chronic_condition_count"],
        "social_data_consent_status": rec["social_data_consent_status"],
        "latest_concurrent_score": rec["latest_concurrent_score"],
        "latest_concurrent_tier": rec["latest_concurrent_tier"],
        "latest_prospective_score": rec["latest_prospective_score"],
        "latest_prospective_tier": rec["latest_prospective_tier"],
    })
    return out


def stratification_out(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_instant(rec["created_at"]),
        "member_id": rec["member_id"],
        "variant": rec["variant"],
        "as_of_date": rec["as_of_date"],
        "utilization_points": dec_to_float(rec["utilization_points"]),
        "chronic_points": dec_to_float(rec["chronic_points"]),
        "social_need_points": dec_to_float(rec["social_need_points"]),
        "raw_score": dec_to_float(rec["raw_score"]),
        "score": rec["score"],
        "tier": rec["tier"],
        "included_event_count": rec["included_event_count"],
    }


def program_out(rec):
    out = _common(rec)
    out.update({
        "name": rec["name"],
        "min_risk_tier": rec["min_risk_tier"],
        "stratification_variant": rec["stratification_variant"],
        "required_credential_levels": list(rec["required_credential_levels"]),
        "care_plan_review_interval_days": rec["care_plan_review_interval_days"],
        "toc_outreach_hours": rec["toc_outreach_hours"],
        "referral_loop_days": rec["referral_loop_days"],
        "staff_minute_budget": rec["staff_minute_budget"],
        "hourly_cost_cents": rec["hourly_cost_cents"],
        "cohort_benchmark_pmpm_cents": rec["cohort_benchmark_pmpm_cents"],
        "committed_staff_minutes": rec["committed_staff_minutes"],
        "delivered_staff_minutes": rec["delivered_staff_minutes"],
    })
    return out


def care_manager_out(rec):
    out = _common(rec)
    out.update({
        "full_name": rec["full_name"],
        "credential_level": rec["credential_level"],
        "licensed_state_codes": list(rec["licensed_state_codes"]),
        "capacity_points": dec_to_float(rec["capacity_points"]),
        "assigned_caseload_points": dec_to_float(rec["assigned_caseload_points"]),
        "capacity_status": rec["capacity_status"],
        "active_enrollment_count": rec["active_enrollment_count"],
    })
    return out


def enrollment_out(rec):
    out = _common(rec)
    out.update({
        "member_id": rec["member_id"],
        "program_id": rec["program_id"],
        "care_manager_id": rec["care_manager_id"],
        "enrollment_status": rec["enrollment_status"],
        "engagement_status": rec["engagement_status"],
        "risk_tier_at_enrollment": rec["risk_tier_at_enrollment"],
        "risk_score_at_enrollment": rec["risk_score_at_enrollment"],
        "cadence_tier": rec["cadence_tier"],
        "cadence_tier_snapshot": rec["cadence_tier_snapshot"],
        "pre_toc_cadence_tier": rec["pre_toc_cadence_tier"],
        "acuity_weight_points": dec_to_float(rec["acuity_weight_points"]),
        "activated_at": fmt_instant(rec["activated_at"]),
        "disenrolled_at": fmt_instant(rec["disenrolled_at"]),
        "disenrollment_reason": rec["disenrollment_reason"],
        "next_touch_due_at": fmt_instant(rec["next_touch_due_at"]),
        "toc_due_at": fmt_instant(rec["toc_due_at"]),
        "last_reached_touch_at": fmt_instant(rec["last_reached_touch_at"]),
        "consecutive_failed_outreach_count": rec["consecutive_failed_outreach_count"],
        "reached_touch_count": rec["reached_touch_count"],
        "engagement_score": rec["engagement_score"],
        "assignment_reason": rec["assignment_reason"],
    })
    return out


def care_plan_out(rec):
    out = _common(rec)
    out.update({
        "enrollment_id": rec["enrollment_id"],
        "authored_by_care_manager_id": rec["authored_by_care_manager_id"],
        "reviewed_by_care_manager_id": rec["reviewed_by_care_manager_id"],
        "title": rec["title"],
        "status": rec["status"],
        "plan_version_no": rec["plan_version_no"],
        "revision_count": rec["revision_count"],
        "review_decision": rec["review_decision"],
        "revision_note": rec["revision_note"],
        "submitted_at": fmt_instant(rec["submitted_at"]),
        "approved_at": fmt_instant(rec["approved_at"]),
        "closed_at": fmt_instant(rec["closed_at"]),
        "next_review_due_at": fmt_instant(rec["next_review_due_at"]),
        "at_risk_goal_count": rec["at_risk_goal_count"],
        "compliance_posture": rec["compliance_posture"],
    })
    return out


def goal_out(rec):
    out = _common(rec)
    out.update({
        "care_plan_id": rec["care_plan_id"],
        "domain": rec["domain"],
        "description": rec["description"],
        "target_date": rec["target_date"],
        "status": rec["status"],
        "barrier_flag": rec["barrier_flag"],
        "planned_intervention_count": rec["planned_intervention_count"],
        "completed_intervention_count": rec["completed_intervention_count"],
    })
    return out


def intervention_out(rec):
    out = _common(rec)
    out.update({
        "goal_id": rec["goal_id"],
        "modality": rec["modality"],
        "staff_minutes": rec["staff_minutes"],
        "status": rec["status"],
        "cost_cents": rec["cost_cents"],
        "delivered_at": fmt_instant(rec["delivered_at"]),
        "void_reason": rec["void_reason"],
    })
    return out


def touch_out(rec):
    out = _common(rec)
    out.update({
        "enrollment_id": rec["enrollment_id"],
        "care_manager_id": rec["care_manager_id"],
        "touch_type": rec["touch_type"],
        "modality": rec["modality"],
        "scheduled_start_at": fmt_instant(rec["scheduled_start_at"]),
        "scheduled_end_at": fmt_instant(rec["scheduled_end_at"]),
        "status": rec["status"],
        "outcome": rec["outcome"],
        "documentation_note": rec["documentation_note"],
        "completed_at": fmt_instant(rec["completed_at"]),
        "cancel_reason": rec["cancel_reason"],
        "satisfied_toc_obligation": rec["satisfied_toc_obligation"],
    })
    return out


def transition_event_out(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_instant(rec["created_at"]),
        "member_id": rec["member_id"],
        "index_admission_event_id": rec["index_admission_event_id"],
        "event_type": rec["event_type"],
        "occurred_at": fmt_instant(rec["occurred_at"]),
        "facility_name": rec["facility_name"],
        "episode_cost_cents": rec["episode_cost_cents"],
        "adjudication_status": rec["adjudication_status"],
        "discharge_disposition": rec["discharge_disposition"],
        "toc_triggered_enrollment_count": rec["toc_triggered_enrollment_count"],
    }


def social_need_out(rec):
    out = _common(rec)
    out.update({
        "enrollment_id": rec["enrollment_id"],
        "domain": rec["domain"],
        "severity": rec["severity"],
        "status": rec["status"],
        "escalation_count": rec["escalation_count"],
        "identified_at": fmt_instant(rec["identified_at"]),
        "resolved_at": fmt_instant(rec["resolved_at"]),
    })
    return out


def community_resource_out(rec):
    out = _common(rec)
    out.update({
        "name": rec["name"],
        "served_domains": list(rec["served_domains"]),
        "service_state_codes": list(rec["service_state_codes"]),
        "contract_status": rec["contract_status"],
        "concurrent_slot_capacity": rec["concurrent_slot_capacity"],
        "open_referral_count": rec["open_referral_count"],
        "closed_loop_count": rec["closed_loop_count"],
    })
    return out


def referral_out(rec):
    out = _common(rec)
    out.update({
        "social_need_id": rec["social_need_id"],
        "community_resource_id": rec["community_resource_id"],
        "sent_by_care_manager_id": rec["sent_by_care_manager_id"],
        "status": rec["status"],
        "service_start_at": fmt_instant(rec["service_start_at"]),
        "service_end_at": fmt_instant(rec["service_end_at"]),
        "sent_at": fmt_instant(rec["sent_at"]),
        "decision_at": fmt_instant(rec["decision_at"]),
        "decline_reason": rec["decline_reason"],
        "outcome_note": rec["outcome_note"],
        "closed_at": fmt_instant(rec["closed_at"]),
        "loop_closure_hours": rec["loop_closure_hours"],
    })
    return out


def roi_measurement_out(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_instant(rec["created_at"]),
        "enrollment_id": rec["enrollment_id"],
        "method": rec["method"],
        "baseline_pmpm_cents": rec["baseline_pmpm_cents"],
        "monthly_projected_cost_cents": rec["monthly_projected_cost_cents"],
        "intervention_month_count": rec["intervention_month_count"],
        "projected_cost_cents": rec["projected_cost_cents"],
        "actual_cost_cents": rec["actual_cost_cents"],
        "gross_savings_cents": rec["gross_savings_cents"],
        "program_cost_cents": rec["program_cost_cents"],
        "net_savings_cents": rec["net_savings_cents"],
        "roi_ratio": dec_to_float(rec["roi_ratio"]),
        "measurement_end_at": fmt_instant(rec["measurement_end_at"]),
        "superseded": rec["superseded"],
    }
