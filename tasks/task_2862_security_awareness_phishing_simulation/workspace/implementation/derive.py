"""Derived-field computation and JSON serialization for every entity."""
import calc
from store import fmt, store


def _common(row):
    out = {"id": row["id"], "created_at": fmt(row["created_at"])}
    if "version" in row:
        out["updated_at"] = fmt(row["updated_at"])
        out["version"] = row["version"]
    return out


# ---------------------------------------------------------------- Employee
def employee_json(emp):
    out = _common(emp)
    out.update({
        "email": emp["email"],
        "full_name": emp["full_name"],
        "department": emp["department"],
        "role_code": emp["role_code"],
        "manager_id": emp["manager_id"],
        "hire_date": emp["hire_date"],
        "employment_status": emp["employment_status"],
        "tenure_band": calc.tenure_band(emp),
        "compliance_state": calc.compliance_state(emp["id"]),
        "access_posture": calc.access_posture(emp["id"]),
        "active_suspension_count": calc.active_suspension_count(emp["id"]),
        "repeat_clicker_tier": calc.repeat_clicker_tier(emp),
        "consecutive_clean_simulations": calc.consecutive_clean_simulations(emp["id"]),
        "reserved_simulation_slots": calc.reserved_simulation_slots(emp["id"]),
        "risk_score_provisional": calc.risk_score_provisional(emp),
        "risk_score_settled": calc.risk_score_settled(emp),
    })
    return out


# ----------------------------------------------------------- TrainingModule
def module_json(mod):
    out = _common(mod)
    out.update({
        "code": mod["code"],
        "title": mod["title"],
        "module_type": mod["module_type"],
        "applies_to_role_codes": list(mod["applies_to_role_codes"]),
        "criticality": mod["criticality"],
        "passing_score_pct": mod["passing_score_pct"],
        "reminder_offsets_days": list(mod["reminder_offsets_days"]),
        "escalate_after_reminders": mod["escalate_after_reminders"],
        "max_extension_days": mod["max_extension_days"],
        "status": mod["status"],
        "published_at": fmt(mod["published_at"]),
        "retired_at": fmt(mod["retired_at"]),
    })
    return out


# ------------------------------------------------------ CurriculumAssignment
def assignment_json(asg):
    module = store.modules.get(asg["module_id"])
    out = _common(asg)
    out.update({
        "employee_id": asg["employee_id"],
        "module_id": asg["module_id"],
        "assignment_reason": asg["assignment_reason"],
        "assigned_at": fmt(asg["assigned_at"]),
        "due_at": fmt(asg["due_at"]),
        "granted_extension_days": asg["granted_extension_days"],
        "effective_due_at": fmt(calc.effective_due_at(asg)),
        "state": asg["state"],
        "attempt_count": asg["attempt_count"],
        "last_score_pct": asg["last_score_pct"],
        "completed_at": fmt(asg["completed_at"]),
        "reminders_sent": asg["reminders_sent"],
        "last_reminder_at": fmt(asg["last_reminder_at"]),
        "next_reminder_due_at": fmt(calc.next_reminder_due_at(asg, module)) if module else None,
        "escalation_level": asg["escalation_level"],
        "days_overdue": calc.days_overdue(asg),
        "superseded_by_assignment_id": asg["superseded_by_assignment_id"],
        "void_reason_code": asg["void_reason_code"],
    })
    return out


# --------------------------------------------------------- EscalationNotice
def notice_json(row):
    out = _common(row)
    out.update({
        "assignment_id": row["assignment_id"],
        "manager_id": row["manager_id"],
        "level": row["level"],
        "sent_at": fmt(row["sent_at"]),
        "state": row["state"],
        "acknowledged_at": fmt(row["acknowledged_at"]),
        "action_plan_note": row["action_plan_note"],
    })
    return out


# --------------------------------------------------------- AccessConsequence
def consequence_json(row):
    out = _common(row)
    out.update({
        "employee_id": row["employee_id"],
        "source_assignment_id": row["source_assignment_id"],
        "consequence_type": row["consequence_type"],
        "severity_rank": row["severity_rank"],
        "state": row["state"],
        "reason_code": row["reason_code"],
        "applied_at": fmt(row["applied_at"]),
        "lifted_at": fmt(row["lifted_at"]),
        "lift_reason_code": row["lift_reason_code"],
    })
    return out


# ---------------------------------------------------------- PhishingTemplate
def template_json(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "pretext_category": row["pretext_category"],
        "difficulty_tier": row["difficulty_tier"],
        "theme_tags": list(row["theme_tags"]),
        "credential_capture_enabled": row["credential_capture_enabled"],
        "review_state": row["review_state"],
        "harmful_flag_hits": list(row["harmful_flag_hits"]),
        "blocked_reason": row["blocked_reason"],
    })
    return out


# ---------------------------------------------------------- PhishingCampaign
def campaign_json(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "template_id": row["template_id"],
        "difficulty_tier": row["difficulty_tier"],
        "target_departments": list(row["target_departments"]),
        "target_tenure_bands": list(row["target_tenure_bands"]),
        "target_min_repeat_tier": row["target_min_repeat_tier"],
        "communication_policy_ack": row["communication_policy_ack"],
        "author_user_id": row["author_user_id"],
        "reviewer_user_id": row["reviewer_user_id"],
        "state": row["state"],
        "rejection_reason": row["rejection_reason"],
        "scheduled_send_at": fmt(row["scheduled_send_at"]),
        "launched_at": fmt(row["launched_at"]),
        "closed_at": fmt(row["closed_at"]),
        "cancelled_at": fmt(row["cancelled_at"]),
        "debrief_note": row["debrief_note"],
        "target_count": row["target_count"],
        "evaluable_count": row["evaluable_count"],
    })
    if row["state"] == "CLOSED":
        # The close froze the four figures.
        out["click_rate"] = row["click_rate"]
        out["report_rate"] = row["report_rate"]
        out["credential_rate"] = row["credential_rate"]
        out["resilience_ratio"] = row["resilience_ratio"]
    else:
        bundle = calc.campaign_rates(row["id"])
        out["click_rate"] = bundle["click_rate"]
        out["report_rate"] = bundle["report_rate"]
        out["credential_rate"] = bundle["credential_rate"]
        out["resilience_ratio"] = bundle["resilience_ratio"]
    return out


# -------------------------------------------------------- SimulationDelivery
def delivery_json(row):
    out = _common(row)
    out.update({
        "campaign_id": row["campaign_id"],
        "employee_id": row["employee_id"],
        "base_difficulty_tier": row["base_difficulty_tier"],
        "effective_difficulty_tier": row["effective_difficulty_tier"],
        "state": row["state"],
        "queued_at": fmt(row["queued_at"]),
        "delivered_at": fmt(row["delivered_at"]),
        "first_click_at": fmt(row["first_click_at"]),
        "first_report_at": fmt(row["first_report_at"]),
        "credential_submitted_at": fmt(row["credential_submitted_at"]),
        "excluded_reason": row["excluded_reason"],
        "outcome_class": calc.outcome_class(row),
        "time_to_report_minutes": calc.time_to_report_minutes(row),
        "quiet_period_until": fmt(calc.quiet_period_until(row)),
    })
    return out


# ---------------------------------------------------------- InteractionEvent
def event_json(row):
    out = _common(row)
    out.update({
        "delivery_id": row["delivery_id"],
        "event_type": row["event_type"],
        "occurred_at": fmt(row["occurred_at"]),
        "source": row["source"],
        "sequence_index": row["sequence_index"],
        "superseding_effect": row["superseding_effect"],
    })
    return out


# -------------------------------------------------- RepeatClickerIntervention
def intervention_json(row):
    employee = store.employees.get(row["employee_id"])
    current_tier = calc.repeat_clicker_tier(employee) if employee else 0
    out = _common(row)
    out.update({
        "employee_id": row["employee_id"],
        "triggering_delivery_id": row["triggering_delivery_id"],
        "coaching_assignment_id": row["coaching_assignment_id"],
        "tier_at_open": row["tier_at_open"],
        "current_tier": current_tier,
        "simulation_frequency_days": calc.simulation_frequency_days(current_tier),
        "state": row["state"],
        "opened_at": fmt(row["opened_at"]),
        "closed_at": fmt(row["closed_at"]),
        "resolution_code": row["resolution_code"],
        "tier_decay_applied": row["tier_decay_applied"],
    })
    return out


# ------------------------------------------------------------- IncidentRecord
def incident_json(row):
    out = _common(row)
    out.update({
        "incident_type": row["incident_type"],
        "severity": row["severity"],
        "department": row["department"],
        "occurred_at": fmt(row["occurred_at"]),
        "root_cause_employee_id": row["root_cause_employee_id"],
        "summary": row["summary"],
        "phish_related": row["phish_related"],
    })
    return out


# --------------------------------------------------------- CommunicationWindow
def window_json(row):
    out = _common(row)
    out.update({
        "window_type": row["window_type"],
        "start_at": fmt(row["start_at"]),
        "end_at": fmt(row["end_at"]),
        "scope_department": row["scope_department"],
        "reason": row["reason"],
    })
    return out
