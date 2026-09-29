"""Resource serializers. Every derived figure is recomputed at read time."""
from db import db, iso
from services import derive, lookup
from services.nums import ZERO, rhu


def _common(row, out):
    out["id"] = row["id"]
    out["created_at"] = iso(row["created_at"])
    out["updated_at"] = iso(row["updated_at"])
    out["version"] = row["version"]
    return out


def program(row):
    out = {
        "code": row["code"],
        "title": row["title"],
        "status": row["status"],
        "mastery_threshold_pct": rhu(row["mastery_threshold_pct"], 2),
        "units_per_credit_hour": rhu(row["units_per_credit_hour"], 1),
        "sap_min_units_per_term": row["sap_min_units_per_term"],
        "required_unit_total": row["required_unit_total"],
        "irr_tolerance_pct": rhu(row["irr_tolerance_pct"], 2),
        "irr_min_paired_reviews": row["irr_min_paired_reviews"],
        "irr_suspend_rate_pct": rhu(row["irr_suspend_rate_pct"], 2),
        "attempt_cooloff_hours": row["attempt_cooloff_hours"],
        "attempts_before_endorsement": row["attempts_before_endorsement"],
        "critical_dimension_min_ratio": rhu(row["critical_dimension_min_ratio"], 2),
        "cadence_gate_overdue_days": row["cadence_gate_overdue_days"],
        "blueprint_notice_days": row["blueprint_notice_days"],
        "aid_earned_pct_full_threshold": rhu(row["aid_earned_pct_full_threshold"], 4),
        "aid_min_credit_equivalency": row["aid_min_credit_equivalency"],
        "competency_count": derive.program_competency_count(row),
        "published_at_utc": iso(row["published_at_utc"]),
    }
    return _common(row, out)


def competency(row):
    effective = derive.effective_blueprint(row)
    out = {
        "program_id": row["program_id"],
        "code": row["code"],
        "title": row["title"],
        "unit_value": rhu(row["unit_value"], 2),
        "level": row["level"],
        "mastery_threshold_pct": (rhu(row["mastery_threshold_pct"], 2)
                                  if row["mastery_threshold_pct"] is not None
                                  else None),
        "effective_mastery_threshold_pct": derive.effective_mastery_threshold(row),
        "prerequisite_competency_id": row["prerequisite_competency_id"],
        "prerequisite_depth": derive.prerequisite_depth(row),
        "status": row["status"],
        "effective_blueprint_id": effective["id"] if effective else None,
        "mastered_by_student_count": derive.mastered_by_student_count(row),
    }
    return _common(row, out)


def dimension(dim):
    return {
        "code": dim["code"],
        "weight": rhu(dim["weight"], 4),
        "max_score": dim["max_score"],
        "critical": dim["critical"],
    }


def blueprint(row):
    out = {
        "competency_id": row["competency_id"],
        "version_label": "BP-%d" % derive.blueprint_ordinal(row),
        "dimensions": [dimension(d) for d in row["dimensions"]],
        "dimension_count": len(row["dimensions"]),
        "passing_rule": row["passing_rule"],
        "required_evaluator_count": row["required_evaluator_count"],
        "effective_from_utc": iso(row["effective_from_utc"]),
        "effective_to_utc": iso(row["effective_to_utc"]),
        "status": row["status"],
        "attempts_bound_count": derive.blueprint_attempts_bound_count(row),
    }
    return _common(row, out)


def student(row):
    sid = row["id"]
    out = {
        "program_id": row["program_id"],
        "full_name": row["full_name"],
        "email": row["email"],
        "enrollment_status": row["enrollment_status"],
        "sap_status": row["sap_status"],
        "mastered_unit_total": rhu(derive.mastered_unit_total(sid), 2),
        "mastered_competency_count": derive.mastered_competency_count(sid),
        "cumulative_credit_equivalency": derive.cumulative_credit_equivalency(row),
        "integrity_strike_count": derive.integrity_strike_count(sid),
        "aid_scheduled_total_cents": derive.aid_scheduled_total_cents(sid),
        "aid_retained_total_cents": derive.aid_retained_total_cents(sid),
        "aid_returned_total_cents": derive.aid_returned_total_cents(sid),
        "activated_at_utc": iso(row["activated_at_utc"]),
        "suspended_at_utc": iso(row["suspended_at_utc"]),
        "withdrawn_at_utc": iso(row["withdrawn_at_utc"]),
        "graduated_at_utc": iso(row["graduated_at_utc"]),
    }
    return _common(row, out)


def term(row):
    out = {
        "student_id": row["student_id"],
        "term_start_utc": iso(row["term_start_utc"]),
        "term_end_utc": iso(row["term_end_utc"]),
        "tuition_cents": row["tuition_cents"],
        "status": row["status"],
        "term_days": derive.term_days(row),
        "attempts_used": derive.term_attempts_used(row),
        "units_mastered_in_term": rhu(derive.units_mastered_in_term(row), 2),
        "credit_equivalency_earned": derive.credit_equivalency_earned(row),
        "activated_at_utc": iso(row["activated_at_utc"]),
        "closed_effective_utc": iso(row["closed_effective_utc"]),
        "attended_days": row["attended_days"],
        "earned_pct": (rhu(row["earned_pct"], 4)
                       if row["earned_pct"] is not None else None),
        "institutional_refund_cents": row["institutional_refund_cents"],
        "net_institutional_charge_cents": row["net_institutional_charge_cents"],
    }
    return _common(row, out)


def mentor(row):
    out = {
        "full_name": row["full_name"],
        "email": row["email"],
        "max_caseload": row["max_caseload"],
        "cadence_days": row["cadence_days"],
        "current_caseload": derive.mentor_caseload(row),
        "status": row["status"],
    }
    return _common(row, out)


def assignment(row):
    status, overdue, due = derive.cadence_state(row)
    out = {
        "mentor_id": row["mentor_id"],
        "student_id": row["student_id"],
        "cadence_days": row["cadence_days"],
        "selection_mode": row["selection_mode"],
        "assigned_at_utc": iso(row["assigned_at_utc"]),
        "last_contact_utc": iso(row["last_contact_utc"]),
        "contact_count": row["contact_count"],
        "next_contact_due_utc": iso(due),
        "cadence_status": status,
        "overdue_days": overdue,
        "endorsed_competency_ids": [e["competency_id"]
                                    for e in derive.unconsumed_endorsements(row)],
        "endorsement_count": derive.endorsement_count(row),
        "status": row["status"],
        "ended_at_utc": iso(row["ended_at_utc"]),
    }
    return _common(row, out)


def evaluator(row):
    paired, agreeing, rate = derive.evaluator_reliability(row)
    out = {
        "full_name": row["full_name"],
        "email": row["email"],
        "certification_level": row["certification_level"],
        "mentor_id": row["mentor_id"],
        "status": row["status"],
        "submitted_score_count": derive.submitted_score_count(row),
        "paired_review_count": paired,
        "agreeing_review_count": agreeing,
        "irr_agreement_rate_pct": rate,
        "demoted_at_utc": iso(row["demoted_at_utc"]),
    }
    return _common(row, out)


def attempt(row):
    out = {
        "student_id": row["student_id"],
        "competency_id": row["competency_id"],
        "blueprint_id": row["blueprint_id"],
        "term_id": row["term_id"],
        "attempt_number": derive.attempt_number(row),
        "status": row["status"],
        "held_from_status": row["held_from_status"],
        "integrity_hold": derive.attempt_integrity_hold(row),
        "artifact_hash": row["artifact_hash"],
        "client_fingerprint": row["client_fingerprint"],
        "integrity_attestation_accepted": row["integrity_attestation_accepted"],
        "submitted_at_utc": iso(row["submitted_at_utc"]),
        "scores_received_count": derive.attempt_scores_received_count(row),
        "final_score_pct": (rhu(row["final_score_pct"], 2)
                            if row["final_score_pct"] is not None else None),
        "is_provisional_score": row["is_provisional_score"],
        "score_variant": row["score_variant"],
        "critical_fail": row["critical_fail"],
        "scored_at_utc": iso(row["scored_at_utc"]),
        "mastered_at_utc": iso(row["mastered_at_utc"]),
        "cooloff_until_utc": iso(derive.attempt_cooloff_until(row)),
        "revision_count": row["revision_count"],
        "endorsement_consumed": row["endorsement_consumed"],
    }
    return _common(row, out)


def score(row):
    out = {
        "attempt_id": row["attempt_id"],
        "evaluator_id": row["evaluator_id"],
        "dimension_scores": [{"code": d["code"], "score": rhu(d["score"], 2)}
                              for d in row["dimension_scores"]],
        "narrative": row["narrative"],
        "weighted_score_pct": rhu(row["weighted_score_pct"], 2),
        "critical_fail": row["critical_fail"],
        "reader_ordinal": row["reader_ordinal"],
        "is_adjudication": row["is_adjudication"],
        "submitted_at_utc": iso(row["submitted_at_utc"]),
        "status": row["status"],
        "voided_reason": row["voided_reason"],
    }
    return _common(row, out)


def integrity_case(row):
    out = {
        "attempt_id": row["attempt_id"],
        "student_id": row["student_id"],
        "signal_type": row["signal_type"],
        "severity": row["severity"],
        "note": row["note"],
        "status": row["status"],
        "sanction": row["sanction"],
        "attempt_status_at_open": row["attempt_status_at_open"],
        "opened_by_user_id": row["opened_by_user_id"],
        "resolved_by_user_id": row["resolved_by_user_id"],
        "resolved_at_utc": iso(row["resolved_at_utc"]),
        "auto_raised": row["auto_raised"],
    }
    return _common(row, out)


def sap_review(row):
    return {
        "id": row["id"],
        "student_id": row["student_id"],
        "term_id": row["term_id"],
        "evaluated_at_utc": iso(row["evaluated_at_utc"]),
        "terms_counted": row["terms_counted"],
        "expected_units": row["expected_units"],
        "cumulative_mastered_units": row["cumulative_mastered_units"],
        "pace_pct": rhu(row["pace_pct"], 2),
        "pace_band": row["pace_band"],
        "previous_sap_status": row["previous_sap_status"],
        "new_sap_status": row["new_sap_status"],
        "reviewed_by_user_id": row["reviewed_by_user_id"],
        "created_at": iso(row["created_at"]),
    }


def disbursement(row):
    out = {
        "student_id": row["student_id"],
        "term_id": row["term_id"],
        "scheduled_amount_cents": row["scheduled_amount_cents"],
        "status": row["status"],
        "hold_reason": row["hold_reason"],
        "credit_equivalency_at_disbursement": row["credit_equivalency_at_disbursement"],
        "outstanding_amount_cents": row["outstanding_amount_cents"],
        "disbursed_amount_cents": row["disbursed_amount_cents"],
        "cancelled_amount_cents": row["cancelled_amount_cents"],
        "returned_amount_cents": row["returned_amount_cents"],
        "retained_amount_cents": row["retained_amount_cents"],
        "unearned_aid_cents": row["unearned_aid_cents"],
        "school_return_share_cents": row["school_return_share_cents"],
        "student_return_share_cents": row["student_return_share_cents"],
        "aid_review_required": row["aid_review_required"],
        "disbursed_at_utc": iso(row["disbursed_at_utc"]),
        "returned_at_utc": iso(row["returned_at_utc"]),
    }
    return _common(row, out)


def transcript(row):
    out = {
        "student_id": row["student_id"],
        "purpose": row["purpose"],
        "status": row["status"],
        "competency_line_count": row["competency_line_count"],
        "total_mastered_units": row["total_mastered_units"],
        "translated_credit_hours": rhu(row["translated_credit_hours"], 1),
        "line_credit_hour_sum": rhu(row["line_credit_hour_sum"], 2),
        "rounding_residual_credit_hours": rhu(row["rounding_residual_credit_hours"], 2),
        "lines": [
            {
                "competency_code": line["competency_code"],
                "unit_value": rhu(line["unit_value"], 2),
                "line_credit_hours": rhu(line["line_credit_hours"], 2),
                "mastered_at_utc": iso(line["mastered_at_utc"]),
            }
            for line in row["lines"]
        ],
        "issued_at_utc": iso(row["issued_at_utc"]),
        "voided_reason": row["voided_reason"],
    }
    return _common(row, out)


def progress_summary(row):
    sid = row["id"]
    program_row = lookup.program_of_student(row)
    cumulative = derive.cumulative_credit_equivalency(row)
    aid_sum = 0
    for term_row in lookup.terms_of(sid):
        if term_row["status"] == "CANCELLED":
            continue
        aid_sum += derive.credit_equivalency_earned(term_row)
    asg = derive.active_assignment(sid)
    if asg is None:
        cadence_status = None
        overdue = 0
        asg_id = None
    else:
        cadence_status, overdue, _due = derive.cadence_state(asg)
        asg_id = asg["id"]
    return {
        "student_id": sid,
        "enrollment_status": row["enrollment_status"],
        "sap_status": row["sap_status"],
        "mastered_unit_total": rhu(derive.mastered_unit_total(sid), 2),
        "mastered_competency_count": derive.mastered_competency_count(sid),
        "required_unit_total": (program_row["required_unit_total"]
                               if program_row else None),
        "cumulative_credit_equivalency": cumulative,
        "aid_credit_equivalency_sum": aid_sum,
        "credit_equivalency_variance": rhu(cumulative - aid_sum, 1),
        "aid_scheduled_total_cents": derive.aid_scheduled_total_cents(sid),
        "aid_retained_total_cents": derive.aid_retained_total_cents(sid),
        "aid_returned_total_cents": derive.aid_returned_total_cents(sid),
        "active_mentor_assignment_id": asg_id,
        "cadence_status": cadence_status,
        "overdue_days": overdue,
        "open_integrity_case_count": derive.open_case_count(sid),
    }
