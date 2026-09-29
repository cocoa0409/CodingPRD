"""Response payloads for the thirteen entities.

Derived fields are computed here on every read, so a payload can never carry a
stale figure. Only the versioned quartet, raw inputs and state fields are
stored.
"""

import derive
from store import db, iso, iso_date


def _stamps(row, versioned=True):
    out = {"id": row["id"], "created_at": iso(row["created_at"])}
    if versioned:
        out["updated_at"] = iso(row["updated_at"])
        out["version"] = row["version"]
    return out


# --------------------------------------------------------------------------
# AcademicProgram
# --------------------------------------------------------------------------

def program(row):
    rolling, latest = derive.cost_figures(row["id"])
    score, band = derive.composite_score(row)
    water = derive.waterfall(row)
    out = {
        "code": row["code"],
        "name": row["name"],
        "degree_level": row["degree_level"],
        "department_code": row["department_code"],
        "host_capacity_per_day": row["host_capacity_per_day"],
        "lifecycle_state": row["lifecycle_state"],
        "catalog_status": row["catalog_status"],
        "catalog_status_pre_decision": row["catalog_status_pre_decision"],
        "consolidated_into_program_id": row["consolidated_into_program_id"],
        "discontinuation_override": row["discontinuation_override"],
        "snapshot_count": len(derive.snapshots_of(row["id"])),
        "cost_per_credit_hour_rolling_cents": rolling,
        "cost_per_credit_hour_latest_cents": latest,
        "composite_score": derive.f2(score) if score is not None else None,
        "viability_band": band,
        "faculty_fte_baseline": derive.f2(water["faculty_fte_baseline"]),
        "active_fte_total": derive.f2(water["active_fte_total"]),
        "reassigned_fte_total": derive.f2(water["reassigned_fte_total"]),
        "separated_fte_total": derive.f2(water["separated_fte_total"]),
        "assigned_pool_fte": derive.f2(water["assigned_pool_fte"]),
        "retained_teach_out_fte": derive.f2(water["retained_teach_out_fte"]),
        "reducible_fte": derive.f2(water["reducible_fte"]),
        "severance_budget_cap_cents": water["severance_budget_cap_cents"],
        "staffing_liability_cents": water["staffing_liability_cents"],
        "deferred_fte": derive.f2(water["deferred_fte"]),
    }
    out.update(_stamps(row))
    return out


def snapshot(row):
    out = {
        "program_id": row["program_id"],
        "term_code": row["term_code"],
        "term_index": row["term_index"],
        "enrollment_headcount": row["enrollment_headcount"],
        "credit_hours": row["credit_hours"],
        "direct_cost_cents": row["direct_cost_cents"],
        "completions_count": row["completions_count"],
        "market_demand_index": row["market_demand_index"],
        "cost_per_credit_hour_cents": derive.snapshot_cost_per_credit_hour(row),
    }
    out.update(_stamps(row, versioned=False))
    return out


# --------------------------------------------------------------------------
# ReviewCycle / SelfStudy
# --------------------------------------------------------------------------

def cycle(row):
    out = {
        "program_id": row["program_id"],
        "cycle_year": row["cycle_year"],
        "state": row["state"],
        "self_study_due_at": iso(row["self_study_due_at"]),
        "required_section_codes": list(row["required_section_codes"]),
        "addendum_round": row["addendum_round"],
        "response_concurrence": row["response_concurrence"],
        "response_text": row["response_text"],
        "disputed_finding_codes": list(row["disputed_finding_codes"]),
        "response_submitted_at": iso(row["response_submitted_at"]),
        "decided_at": iso(row["decided_at"]),
        "compliance_posture": derive.compliance_posture(row),
    }
    out.update(_stamps(row))
    return out


def missing_section_codes(self_study):
    parent = db.cycles.get(self_study["cycle_id"])
    if parent is None:
        return []
    have = set(self_study["section_codes"])
    return [code for code in parent["required_section_codes"] if code not in have]


def self_study(row):
    out = {
        "cycle_id": row["cycle_id"],
        "narrative": row["narrative"],
        "section_codes": list(row["section_codes"]),
        "state": row["state"],
        "revision_round": row["revision_round"],
        "submitted_at": iso(row["submitted_at"]),
        "accepted_at": iso(row["accepted_at"]),
        "revision_notes": row["revision_notes"],
        "attestation_note": row["attestation_note"],
        "missing_section_codes": missing_section_codes(row),
    }
    out.update(_stamps(row))
    return out


# --------------------------------------------------------------------------
# ExternalReviewer / ReviewerVisit / ReviewerReport
# --------------------------------------------------------------------------

def reviewer(row):
    visit_count = len([v for v in db.visits.values()
                       if v["reviewer_id"] == row["id"]])
    out = {
        "full_name": row["full_name"],
        "institution": row["institution"],
        "specialty_code": row["specialty_code"],
        "conflict_program_codes": list(row["conflict_program_codes"]),
        "travel_buffer_hours": row["travel_buffer_hours"],
        "visit_count": visit_count,
    }
    out.update(_stamps(row))
    return out


def visit(row):
    out = {
        "cycle_id": row["cycle_id"],
        "reviewer_id": row["reviewer_id"],
        "window_start_at": iso(row["window_start_at"]),
        "window_end_at": iso(row["window_end_at"]),
        "state": row["state"],
        "span_start_date": iso_date(row["window_start_at"]),
        "span_end_date": iso_date(row["window_end_at"]),
        "completed_at": iso(row["completed_at"]),
        "report_count": len(derive.reports_of(row["id"])),
    }
    out.update(_stamps(row))
    return out


def report(row):
    out = {
        "visit_id": row["visit_id"],
        "recommendation": row["recommendation"],
        "finding_codes": list(row["finding_codes"]),
        "narrative": row["narrative"],
        "sequence_number": row["sequence_number"],
        "filed_at": iso(row["filed_at"]),
    }
    out.update(_stamps(row, versioned=False))
    return out


# --------------------------------------------------------------------------
# DecisionRecord / AgencyNotification
# --------------------------------------------------------------------------

def decision(row):
    total, unacknowledged = derive.notification_counters(row)
    out = {
        "cycle_id": row["cycle_id"],
        "outcome": row["outcome"],
        "rationale": row["rationale"],
        "effective_term_index": row["effective_term_index"],
        "receiving_program_id": row["receiving_program_id"],
        "improvement_target_score": (
            derive.f2(row["improvement_target_score"])
            if row["improvement_target_score"] is not None else None),
        "improvement_review_term_index": row["improvement_review_term_index"],
        "improvement_milestones": list(row["improvement_milestones"]),
        "state": row["state"],
        "improvement_state": row["improvement_state"],
        "proposed_by_user_id": row["proposed_by_user_id"],
        "ratified_by_user_id": row["ratified_by_user_id"],
        "ratification_note": row["ratification_note"],
        "ratified_at": iso(row["ratified_at"]),
        "effectuated_at": iso(row["effectuated_at"]),
        "rescission_reason": row["rescission_reason"],
        "composite_score_at_proposal": (
            derive.f2(row["composite_score_at_proposal"])
            if row["composite_score_at_proposal"] is not None else None),
        "viability_band_at_proposal": row["viability_band_at_proposal"],
        "notification_count": total,
        "unacknowledged_notification_count": unacknowledged,
    }
    out.update(_stamps(row))
    return out


def notification(row):
    out = {
        "decision_id": row["decision_id"],
        "agency_type": row["agency_type"],
        "agency_code": row["agency_code"],
        "status": row["status"],
        "due_at": iso(row["due_at"]),
        "sent_at": iso(row["sent_at"]),
        "acknowledged_at": iso(row["acknowledged_at"]),
        "transmitted_reference": row["transmitted_reference"],
        "origin": row["origin"],
        "overdue_marked_at": iso(row["overdue_marked_at"]),
    }
    out.update(_stamps(row))
    return out


# --------------------------------------------------------------------------
# TeachOutPlan / CourseGuarantee / DisplacedStudent
# --------------------------------------------------------------------------

def plan(row):
    ledger = derive.plan_ledger(row)
    out = {
        "program_id": row["program_id"],
        "decision_id": row["decision_id"],
        "last_admit_term_index": row["last_admit_term_index"],
        "first_teach_out_term_index": row["first_teach_out_term_index"],
        "final_award_term_index": row["final_award_term_index"],
        "state": row["state"],
        "plan_revision_round": row["plan_revision_round"],
        "revision_notes": row["revision_notes"],
        "approved_at": iso(row["approved_at"]),
        "activated_at": iso(row["activated_at"]),
        "completed_at": iso(row["completed_at"]),
    }
    out.update(ledger)
    out.update(_stamps(row))
    return out


def guarantee(row):
    committed = derive.guarantee_committed(row["id"])
    out = {
        "teach_out_plan_id": row["teach_out_plan_id"],
        "course_code": row["course_code"],
        "term_index": row["term_index"],
        "seats_guaranteed": row["seats_guaranteed"],
        "seats_committed": committed,
        "seats_available": row["seats_guaranteed"] - committed,
        "status": row["status"],
        "substitute_course_code": row["substitute_course_code"],
        "substitution_justification": row["substitution_justification"],
        "waived_reason_code": row["waived_reason_code"],
    }
    out.update(_stamps(row))
    return out


def student(row):
    projection = derive.student_projection(row)
    out = {
        "teach_out_plan_id": row["teach_out_plan_id"],
        "student_number": row["student_number"],
        "credits_remaining": row["credits_remaining"],
        "max_credits_per_term": row["max_credits_per_term"],
        "advised_credits_per_term": row["advised_credits_per_term"],
        "advising_status": row["advising_status"],
        "committed_seat_count": derive.student_committed(row["id"]),
        "completion_term_index": row["completion_term_index"],
        "withdrawal_reason_code": row["withdrawal_reason_code"],
        "advised_at": iso(row["advised_at"]),
    }
    out.update(projection)
    out.update(_stamps(row))
    return out


# --------------------------------------------------------------------------
# FacultyAppointment
# --------------------------------------------------------------------------

def appointment(row):
    parent = db.programs.get(row["program_id"])
    position = None
    notice_pay = derive.notice_pay_for(row)
    if parent is not None:
        water = derive.waterfall(parent)
        position = water["positions"].get(row["id"])
        notice_pay = water["notice_pay"].get(row["id"], notice_pay)
    out = {
        "program_id": row["program_id"],
        "faculty_number": row["faculty_number"],
        "tenure_status": row["tenure_status"],
        "fte": derive.f2(row["fte"]),
        "annual_salary_cents": row["annual_salary_cents"],
        "state": row["state"],
        "reassigned_to_department_code": row["reassigned_to_department_code"],
        "notice_days": row["notice_days"],
        "notice_issued_at": iso(row["notice_issued_at"]),
        "separated_at": iso(row["separated_at"]),
        "reassignment_withdraw_count": row["reassignment_withdraw_count"],
        "notice_pay_cents": notice_pay,
        "reduction_sequence_position": position,
    }
    out.update(_stamps(row))
    return out
