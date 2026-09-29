"""Entity serializers. Field lists follow SCAFFOLD section 1.1 exactly; every
instant is ISO 8601 UTC with three fractional digits (PRD section 2.4)."""

import calc
import clock
import derive


def _common(row):
    return {
        "id": row["id"],
        "created_at": clock.iso(row["created_at"]),
        "updated_at": clock.iso(row["updated_at"]),
        "version": row["version"],
    }


def club(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "state_code": row["state_code"],
        "minor_athlete_program": row["minor_athlete_program"],
        "roster_size_attested": row["roster_size_attested"],
        "escrow_balance_cents": row["escrow_balance_cents"],
        "total_funded_cents": row["total_funded_cents"],
        "sanction_status": row["sanction_status"],
        "compliance_posture": row["compliance_posture"],
        "compliance_score": calc.score_out(row["compliance_score"]),
        "open_finding_count": row["open_finding_count"],
        "critical_open_finding_count": row["critical_open_finding_count"],
        "restricted_member_count": row["restricted_member_count"],
        "active_assignment_count": row["active_assignment_count"],
    })
    return out


def member(row):
    out = _common(row)
    out.update({
        "club_id": row["club_id"],
        "full_name": row["full_name"],
        "email": row["email"],
        "role_type": row["role_type"],
        "has_minor_athlete_contact": row["has_minor_athlete_contact"],
        "date_of_birth": row["date_of_birth"],
        "jurisdiction_codes": list(row["jurisdiction_codes"]),
        "risk_points": row["risk_points"],
        "required_tier": row["required_tier"],
        "screening_status": row["screening_status"],
        "screening_expires_at": clock.iso(row["screening_expires_at"]),
        "membership_status": row["membership_status"],
        "training_status": row["training_status"],
        "contact_eligibility": row["contact_eligibility"],
        "eligible_through": clock.iso(row["eligible_through"]),
        "records_retained_through": clock.iso(row["records_retained_through"]),
        "last_renewed_at": clock.iso(row["last_renewed_at"]),
        "active_assignment_count": row["active_assignment_count"],
    })
    return out


def screening_order(row):
    out = _common(row)
    out.update({
        "member_id": row["member_id"],
        "tier": row["tier"],
        "jurisdiction_count": row["jurisdiction_count"],
        "expedited": row["expedited"],
        "gross_subtotal_cents": row["gross_subtotal_cents"],
        "discount_cents": row["discount_cents"],
        "expedite_cents": row["expedite_cents"],
        "charged_cents": row["charged_cents"],
        "status": row["status"],
        "vendor_disposition": row["vendor_disposition"],
        "disposition": row["disposition"],
        "returned_at": clock.iso(row["returned_at"]),
        "adjudicated_at": clock.iso(row["adjudicated_at"]),
        "expires_at": clock.iso(row["expires_at"]),
        "void_reason": row["void_reason"],
    })
    return out


def training_course(row):
    out = _common(row)
    out.update({
        "code": row["code"],
        "title": row["title"],
        "validity_days": row["validity_days"],
        "delivery_mode": row["delivery_mode"],
        "required_for_tiers": list(row["required_for_tiers"]),
        "pass_score": row["pass_score"],
    })
    return out


def training_assignment(row):
    out = _common(row)
    out.update({
        "member_id": row["member_id"],
        "course_code": row["course_code"],
        "status": row["status"],
        "assigned_at": clock.iso(row["assigned_at"]),
        "due_at": clock.iso(row["due_at"]),
        "started_at": clock.iso(row["started_at"]),
        "completed_at": clock.iso(row["completed_at"]),
        "score": row["score"],
        "expires_at": clock.iso(row["expires_at"]),
    })
    return out


def coach_assignment(row):
    out = _common(row)
    out.update({
        "member_id": row["member_id"],
        "club_id": row["club_id"],
        "team_name": row["team_name"],
        "season_start": clock.iso(row["season_start"]),
        "season_end": clock.iso(row["season_end"]),
        "status": row["status"],
        "activated_at": clock.iso(row["activated_at"]),
        "eligibility_snapshot_version": row["eligibility_snapshot_version"],
        "electronic_comm_authorized": row["electronic_comm_authorized"],
        "electronic_comm_channel_kind": row["electronic_comm_channel_kind"],
        "parent_copy_required": row["parent_copy_required"],
        "suspended_reason": row["suspended_reason"],
    })
    return out


def investigating_body(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "scope_categories": list(row["scope_categories"]),
        "intake_status": row["intake_status"],
        "max_open_cases": row["max_open_cases"],
        "open_case_count": row["open_case_count"],
    })
    return out


def case(row):
    out = _common(row)
    out.update({
        "club_id": row["club_id"],
        "reported_member_id": row["reported_member_id"],
        "investigating_body_id": row["investigating_body_id"],
        "allegation_category": row["allegation_category"],
        "reporter_kind": row["reporter_kind"],
        "reporter_user_id": row["reporter_user_id"],
        "narrative": row["narrative"],
        "occurred_at": clock.iso(row["occurred_at"]),
        "intake_received_at": clock.iso(row["intake_received_at"]),
        "report_timeliness": row["report_timeliness"],
        "status": row["status"],
        "routed_at": clock.iso(row["routed_at"]),
        "closure_reason": row["closure_reason"],
        "outcome": row["outcome"],
        "closed_at": clock.iso(row["closed_at"]),
    })
    return out


def interim_measure(row):
    out = _common(row)
    out.update({
        "case_id": row["case_id"],
        "member_id": row["member_id"],
        "measure_kind": row["measure_kind"],
        "permanence": row["permanence"],
        "effective_from": clock.iso(row["effective_from"]),
        "effective_to": clock.iso(row["effective_to"]),
        "status": row["status"],
        "imposed_by_user_id": row["imposed_by_user_id"],
        "converted_by_user_id": row["converted_by_user_id"],
        "lifted_at": clock.iso(row["lifted_at"]),
        "lift_reason": row["lift_reason"],
        "rationale": row["rationale"],
    })
    return out


def club_audit(row):
    out = _common(row)
    out.update({
        "club_id": row["club_id"],
        "audit_period_start": clock.iso(row["audit_period_start"]),
        "audit_period_end": clock.iso(row["audit_period_end"]),
        "score_variant": row["score_variant"],
        "sampled_member_ids": list(row["sampled_member_ids"]),
        "sampled_member_count": row["sampled_member_count"],
        "compliant_member_count": row["compliant_member_count"],
        "denominator_count": row["denominator_count"],
        "compliance_score": calc.score_out(row["compliance_score"]),
        "finding_total_count": row["finding_total_count"],
        "open_finding_count": row["open_finding_count"],
        "remediated_finding_count": row["remediated_finding_count"],
        "waived_finding_count": row["waived_finding_count"],
        "sanction_fine_cents": row["sanction_fine_cents"],
        "status": row["status"],
        "finalized_at": clock.iso(row["finalized_at"]),
        "closed_at": clock.iso(row["closed_at"]),
        "resolution": row["resolution"],
    })
    return out


def audit_finding(row):
    out = _common(row)
    out.update({
        "audit_id": row["audit_id"],
        "member_id": row["member_id"],
        "finding_code": row["finding_code"],
        "severity": row["severity"],
        "is_repeat": row["is_repeat"],
        "status": row["status"],
        "fine_cents": row["fine_cents"],
        "evidence_note": row["evidence_note"],
        "decision_note": row["decision_note"],
    })
    return out


def room_stay(row):
    out = _common(row)
    out.update({
        "club_id": row["club_id"],
        "member_id": row["member_id"],
        "occupant_kind": row["occupant_kind"],
        "minor_athlete_age": row["minor_athlete_age"],
        "trip_label": row["trip_label"],
        "room_number": row["room_number"],
        "check_in": clock.iso(row["check_in"]),
        "check_out": clock.iso(row["check_out"]),
        "status": row["status"],
        "cancel_reason": row["cancel_reason"],
    })
    return out


def projection(row, variant):
    horizons = derive.projection(row, variant)
    return {
        "variant": variant,
        "projected_eligible_through": clock.iso(horizons["projected"]),
        "screening_expiry": clock.iso(horizons["screening_expiry"]),
        "training_expiry": clock.iso(horizons["training_expiry"]),
        "screening_status": row["screening_status"],
        "training_status": row["training_status"],
        "membership_status": row["membership_status"],
        "contact_eligibility": row["contact_eligibility"],
        "required_tier": row["required_tier"],
        "risk_points": row["risk_points"],
        "records_retained_through": clock.iso(row["records_retained_through"]),
        "blocking_reasons": derive.blocking_reasons(row),
    }
