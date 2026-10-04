"""Entity serializers honoring the two timestamp families of PRD section 2.4.

System family (created_at / updated_at): three fractional digits, always.
Domain family (event timestamps read from the logical clock): rendered as the
clock reads. Calendar-date fields render as plain YYYY-MM-DD.
"""
import clock


def _sys(value):
    return clock.render_system(value) if value is not None else None


def _dom(value):
    return clock.render_domain(value) if value is not None else None


def _date(value):
    return clock.render_date(value) if value is not None else None


def _system_fields(entity):
    return {
        "created_at": _sys(entity["created_at"]),
        "updated_at": _sys(entity["updated_at"]),
        "version": entity["version"],
    }


def operator(entity):
    out = {
        "id": entity["id"],
        "legal_name": entity["legal_name"],
        "annual_tonnage_tons": entity["annual_tonnage_tons"],
        "home_district": entity["home_district"],
    }
    out.update(_system_fields(entity))
    return out


def mine(entity):
    out = {
        "id": entity["id"],
        "operator_id": entity["operator_id"],
        "mine_name": entity["mine_name"],
        "mine_type": entity["mine_type"],
        "activation_date": _date(entity["activation_date"]),
        "status": entity["status"],
        "production_status": entity["production_status"],
        "pov_status": entity["pov_status"],
    }
    out.update(_system_fields(entity))
    return out


def inspector(entity):
    out = {
        "id": entity["id"],
        "full_name": entity["full_name"],
        "badge_number": entity["badge_number"],
        "district_code": entity["district_code"],
        "certification": entity["certification"],
        "conflicted_operator_ids": list(entity["conflicted_operator_ids"]),
    }
    out.update(_system_fields(entity))
    return out


def inspection_cycle(entity):
    out = {
        "id": entity["id"],
        "mine_id": entity["mine_id"],
        "cycle_index": entity["cycle_index"],
        "period_start": _date(entity["period_start"]),
        "period_end": _date(entity["period_end"]),
        "required_inspections": entity["required_inspections"],
        "completed_inspections": entity["completed_inspections"],
        "status": entity["status"],
    }
    out.update(_system_fields(entity))
    return out


def inspection(entity):
    out = {
        "id": entity["id"],
        "mine_id": entity["mine_id"],
        "cycle_id": entity["cycle_id"],
        "inspector_id": entity["inspector_id"],
        "kind": entity["kind"],
        "accident_id": entity["accident_id"],
        "planned_start_at": _dom(entity["planned_start_at"]),
        "planned_end_at": _dom(entity["planned_end_at"]),
        "file_reviewed_at": _dom(entity["file_reviewed_at"]),
        "actual_entry_at": _dom(entity["actual_entry_at"]),
        "completed_at": _dom(entity["completed_at"]),
        "status": entity["status"],
    }
    out.update(_system_fields(entity))
    return out


def citation(entity):
    out = {
        "id": entity["id"],
        "inspection_id": entity["inspection_id"],
        "mine_id": entity["mine_id"],
        "issued_by_inspector_id": entity["issued_by_inspector_id"],
        "standard_code": entity["standard_code"],
        "kind": entity["kind"],
        "negligence": entity["negligence"],
        "gravity_likelihood": entity["gravity_likelihood"],
        "gravity_severity": entity["gravity_severity"],
        "persons_affected": entity["persons_affected"],
        "significant_and_substantial": entity["significant_and_substantial"],
        "repeat_violation": entity["repeat_violation"],
        "issued_at": _dom(entity["issued_at"]),
        "abatement_base_days": entity["abatement_base_days"],
        "abatement_deadline": _dom(entity["abatement_deadline"]),
        "abatement_extended": entity["abatement_extended"],
        "abated_at": _dom(entity["abated_at"]),
        "verified_at": _dom(entity["verified_at"]),
        "verified_by_inspector_id": entity["verified_by_inspector_id"],
        "abatement_status": entity["abatement_status"],
        "contest_status": entity["contest_status"],
        "system_issued": entity["system_issued"],
    }
    out.update(_system_fields(entity))
    return out


def penalty_assessment(entity):
    out = {
        "id": entity["id"],
        "citation_id": entity["citation_id"],
        "points_total": entity["points_total"],
        "proposed_penalty_cents": entity["proposed_penalty_cents"],
        "final_penalty_cents": entity["final_penalty_cents"],
        "good_faith_applied": entity["good_faith_applied"],
        "statutory_floor_applied": entity["statutory_floor_applied"],
        "status": entity["status"],
    }
    out.update(_system_fields(entity))
    return out


def imminent_danger_order(entity):
    out = {
        "id": entity["id"],
        "mine_id": entity["mine_id"],
        "inspection_id": entity["inspection_id"],
        "issued_by_inspector_id": entity["issued_by_inspector_id"],
        "hazard_description": entity["hazard_description"],
        "issued_at": _dom(entity["issued_at"]),
        "miners_withdrawn_count": entity["miners_withdrawn_count"],
        "withdrawal_confirmed_at": _dom(entity["withdrawal_confirmed_at"]),
        "abatement_verified_at": _dom(entity["abatement_verified_at"]),
        "verified_by_inspector_id": entity["verified_by_inspector_id"],
        "terminated_at": _dom(entity["terminated_at"]),
        "status": entity["status"],
    }
    out.update(_system_fields(entity))
    return out


def contest(entity):
    out = {
        "id": entity["id"],
        "citation_id": entity["citation_id"],
        "filed_by_operator_id": entity["filed_by_operator_id"],
        "grounds": entity["grounds"],
        "filed_at": _dom(entity["filed_at"]),
        "status": entity["status"],
        "outcome": entity["outcome"],
        "modified_penalty_cents": entity["modified_penalty_cents"],
        "decided_at": _dom(entity["decided_at"]),
    }
    out.update(_system_fields(entity))
    return out


def mine_plan(entity):
    out = {
        "id": entity["id"],
        "mine_id": entity["mine_id"],
        "plan_type": entity["plan_type"],
        "revision_no": entity["revision_no"],
        "document_ref": entity["document_ref"],
        "submitted_at": _dom(entity["submitted_at"]),
        "supersedes_plan_id": entity["supersedes_plan_id"],
        "next_revision_due_at": _dom(entity["next_revision_due_at"]),
        "approved_at": _dom(entity["approved_at"]),
        "rejection_reason": entity["rejection_reason"],
        "status": entity["status"],
    }
    out.update(_system_fields(entity))
    return out


def accident(entity):
    out = {
        "id": entity["id"],
        "mine_id": entity["mine_id"],
        "occurred_at": _dom(entity["occurred_at"]),
        "reported_at": _dom(entity["reported_at"]),
        "severity": entity["severity"],
        "description": entity["description"],
        "late_report": entity["late_report"],
        "root_cause": entity["root_cause"],
        "report_text": entity["report_text"],
        "published_at": _dom(entity["published_at"]),
        "status": entity["status"],
    }
    out.update(_system_fields(entity))
    return out


def pov_screening(entity):
    out = {
        "id": entity["id"],
        "mine_id": entity["mine_id"],
        "variant": entity["variant"],
        "screened_at": _dom(entity["screened_at"]),
        "window_start": _dom(entity["window_start"]),
        "ss_citation_count": entity["ss_citation_count"],
        "weighted_score": entity["weighted_score"],
        "result": entity["result"],
    }
    out.update(_system_fields(entity))
    return out
