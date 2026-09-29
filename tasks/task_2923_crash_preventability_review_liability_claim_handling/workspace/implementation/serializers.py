"""Per-entity response shapes. Field order follows the entity declarations."""

from decimal import Decimal

import calc
from envelope import fmt_dt, num
from store import db


def _fmt_date(value):
    return None if value is None else value.isoformat()


def _common(row, out, versioned=True):
    out["created_at"] = fmt_dt(row["created_at"])
    if versioned:
        out["updated_at"] = fmt_dt(row["updated_at"])
        out["version"] = row["version"]
    return out


def terminal(row):
    active = calc.active_driver_count(row["id"])
    suspended = calc.suspended_driver_count(row["id"])
    preventable = calc.terminal_preventable_count(row["id"])
    rate = calc.crash_rate(preventable, row["_miles"])
    out = {
        "id": row["id"],
        "name": row["name"],
        "terminal_code": row["terminal_code"],
        "region_code": row["region_code"],
        "annual_miles_millions": row["annual_miles_millions"],
        "active_driver_count": active,
        "suspended_driver_count": suspended,
        "preventable_crash_count": preventable,
        "crash_rate_per_million_miles": num(rate),
        "risk_tier": calc.risk_tier(rate),
        "staffing_posture": calc.staffing_posture(row["id"]),
        "late_filing_count": calc.late_filing_count(row["id"]),
    }
    return _common(row, out)


def driver(row):
    points = calc.preventable_points(row)
    out = {
        "id": row["id"],
        "terminal_id": row["terminal_id"],
        "employee_code": row["employee_code"],
        "full_name": row["full_name"],
        "cdl_number": row["cdl_number"],
        "hire_date": _fmt_date(row["hire_date"]),
        "status": row["status"],
        "tenure_band": calc.tenure_band(row),
        "preventable_points": num(points),
        "required_action_tier": calc.action_tier(points),
        "continued_employment_decision": row["continued_employment_decision"],
        "decision_note": row["decision_note"],
    }
    return _common(row, out)


def crash(row):
    out = {
        "id": row["id"],
        "driver_id": row["driver_id"],
        "terminal_id": row["terminal_id"],
        "occurred_at": fmt_dt(row["occurred_at"]),
        "notified_at": fmt_dt(row["notified_at"]),
        "location_text": row["location_text"],
        "severity": row["severity"],
        "route_class": row["route_class"],
        "tow_away": row["tow_away"],
        "tow_reason": row["tow_reason"],
        "injury_transported_count": row["injury_transported_count"],
        "fatality_count": row["fatality_count"],
        "hazmat_release": row["hazmat_release"],
        "mechanical_factor": row["mechanical_factor"],
        "third_party_at_fault": row["third_party_at_fault"],
        "dot_recordable": row["dot_recordable"],
        "recordability_codes": list(row["recordability_codes"]),
        "report_due_at": fmt_dt(row["report_due_at"]),
        "reporting_status": row["reporting_status"],
        "filing_reference": row["filing_reference"],
        "filed_at": fmt_dt(row["filed_at"]),
        "preventability_status": row["preventability_status"],
        "appeals_exhausted": row["appeals_exhausted"],
        "evidence_posture": calc.evidence_posture(row),
    }
    return _common(row, out)


def driver_statement(row):
    out = {
        "id": row["id"],
        "crash_id": row["crash_id"],
        "narrative": row["narrative"],
        "conditions_note": row["conditions_note"],
        "attested": row["attested"],
        "submitted_by_driver_id": row["submitted_by_driver_id"],
        "submitted_at": fmt_dt(row["submitted_at"]),
    }
    return _common(row, out, versioned=False)


def evidence_item(row):
    out = {
        "id": row["id"],
        "crash_id": row["crash_id"],
        "kind": row["kind"],
        "source_device_id": row["source_device_id"],
        "window_start_at": fmt_dt(row["window_start_at"]),
        "window_end_at": fmt_dt(row["window_end_at"]),
        "retention_deadline_at": fmt_dt(row["retention_deadline_at"]),
        "preservation_state": row["preservation_state"],
        "evidence_hash": row["evidence_hash"],
        "preserved_copy_uri": row["preserved_copy_uri"],
        "preserved_at": fmt_dt(row["preserved_at"]),
        "purge_reason": row["purge_reason"],
    }
    return _common(row, out)


def review_case(row):
    active, abstain = calc.vote_counts(row["id"])
    out = {
        "id": row["id"],
        "crash_id": row["crash_id"],
        "committee_name": row["committee_name"],
        "statement_waiver_reason": row["statement_waiver_reason"],
        "status": row["status"],
        "determination": row["determination"],
        "decision_basis": row["decision_basis"],
        "committee_score": num(row["committee_score"]),
        "active_vote_count": active,
        "abstain_count": abstain,
        "next_vote_sequence": row["next_vote_sequence"],
        "appeal_round": row["appeal_round"],
        "appeal_grounds": row["appeal_grounds"],
        "appeal_grounds_code": row["appeal_grounds_code"],
        "appeal_evidence_item_id": row["appeal_evidence_item_id"],
        "decided_by_user_id": row["decided_by_user_id"],
        "decided_at": fmt_dt(row["decided_at"]),
    }
    return _common(row, out)


def committee_vote(row):
    scores = row["criterion_scores"]
    out = {
        "id": row["id"],
        "review_case_id": row["review_case_id"],
        "member_user_id": row["member_user_id"],
        "sequence_number": row["sequence_number"],
        "vote": row["vote"],
        "criterion_scores": dict(scores) if scores is not None else None,
        "weighted_member_score": num(row["weighted_member_score"]),
        "superseded": row["superseded"],
        "comment": row["comment"],
        "cast_at": fmt_dt(row["cast_at"]),
    }
    return _common(row, out, versioned=False)


def claim(row):
    score = calc.litigation_risk_score(row)
    out = {
        "id": row["id"],
        "crash_id": row["crash_id"],
        "claimant_notice_date": _fmt_date(row["claimant_notice_date"]),
        "adjuster_note": row["adjuster_note"],
        "handling_status": row["handling_status"],
        "reserve_status": row["reserve_status"],
        "litigation_risk_score": score,
        "litigation_risk_multiplier": num(calc.litigation_risk_multiplier(score)),
        "counsel_required": calc.counsel_required(score),
        "counsel_assigned": row["counsel_assigned"],
        "counsel_firm_name": row["counsel_firm_name"],
        "counsel_type": row["counsel_type"],
        "counsel_assigned_at": fmt_dt(row["counsel_assigned_at"]),
        "litigation_flag": row["litigation_flag"],
        "closed_at": fmt_dt(row["closed_at"]),
        "provisional_reserve_cents": row["provisional_reserve_cents"],
        "revised_reserve_cents": row["revised_reserve_cents"],
        "outstanding_reserve_cents": row["outstanding_reserve_cents"],
        "indemnity_paid_cents": row["indemnity_paid_cents"],
        "alae_paid_cents": row["alae_paid_cents"],
        "reserve_released_cents": row["reserve_released_cents"],
        "subrogation_recovered_cents": row["subrogation_recovered_cents"],
        "sir_eroded_cents": row["sir_eroded_cents"],
        "insured_paid_cents": row["insured_paid_cents"],
        "layer_allocations": [dict(entry) for entry in row["layer_allocations"]],
        "total_incurred_cents": calc.total_incurred(row),
        "claim_exposure_cents": calc.claim_exposure(row),
    }
    return _common(row, out)


def policy_layer(row):
    out = {
        "id": row["id"],
        "program_year": row["program_year"],
        "layer_index": row["layer_index"],
        "layer_type": row["layer_type"],
        "attachment_point_cents": row["attachment_point_cents"],
        "limit_cents": row["limit_cents"],
        "insurer_name": row["insurer_name"],
    }
    return _common(row, out, versioned=False)


def demand(row):
    out = {
        "id": row["id"],
        "claim_id": row["claim_id"],
        "claimant_name": row["claimant_name"],
        "claimant_type": row["claimant_type"],
        "demand_amount_cents": row["demand_amount_cents"],
        "represented_by_counsel": row["represented_by_counsel"],
        "demand_received_at": fmt_dt(row["demand_received_at"]),
        "status": row["status"],
        "next_round_index": row["next_round_index"],
        "round_count": calc.round_count(row["id"]),
        "settled_amount_cents": row["settled_amount_cents"],
        "alae_cents": row["alae_cents"],
        "settlement_total_cents": row["settlement_total_cents"],
        "settled_at": fmt_dt(row["settled_at"]),
        "settlement_reference": row["settlement_reference"],
        "rescission_count": row["rescission_count"],
    }
    return _common(row, out)


def negotiation_round(row):
    out = {
        "id": row["id"],
        "demand_id": row["demand_id"],
        "round_index": row["round_index"],
        "carrier_offer_cents": row["carrier_offer_cents"],
        "claimant_counter_cents": row["claimant_counter_cents"],
        "gap_cents": row["gap_cents"],
        "outcome": row["outcome"],
        "offered_by_user_id": row["offered_by_user_id"],
        "offered_at": fmt_dt(row["offered_at"]),
        "countered_at": fmt_dt(row["countered_at"]),
    }
    return _common(row, out, versioned=False)


def disciplinary_action(row):
    out = {
        "id": row["id"],
        "driver_id": row["driver_id"],
        "crash_id": row["crash_id"],
        "action_type": row["action_type"],
        "action_note": row["action_note"],
        "suspension_start_at": fmt_dt(row["suspension_start_at"]),
        "suspension_end_at": fmt_dt(row["suspension_end_at"]),
        "retraining_course_code": row["retraining_course_code"],
        "retraining_status": row["retraining_status"],
        "status": row["status"],
        "override_reason": row["override_reason"],
        "override_flag": row["override_flag"],
        "issued_by_user_id": row["issued_by_user_id"],
        "completed_at": fmt_dt(row["completed_at"]),
    }
    return _common(row, out)


def subrogation_demand(row):
    out = {
        "id": row["id"],
        "claim_id": row["claim_id"],
        "third_party_name": row["third_party_name"],
        "at_fault_percentage": row["at_fault_percentage"],
        "basis_note": row["basis_note"],
        "status": row["status"],
        "recoverable_base_cents": row["recoverable_base_cents"],
        "max_recoverable_cents": row["max_recoverable_cents"],
        "recovered_amount_cents": row["recovered_amount_cents"],
        "resolution_note": row["resolution_note"],
        "resolved_at": fmt_dt(row["resolved_at"]),
    }
    return _common(row, out)
