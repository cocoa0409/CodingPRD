"""Entity representations. Computed fields are derived here so that a read never
returns a stale aggregate (PRD sec 2.13)."""
import calc
from auth import member_status
from store import clock_date, num, parse_date


def _common(record, out):
    out["created_at"] = record["created_at"]
    out["updated_at"] = record["updated_at"]
    out["version"] = record["version"]
    return out


def program(record):
    out = {
        "id": record["id"],
        "cip_code": record["cip_code"],
        "title": record["title"],
        "cluster": record["cluster"],
        "approval_status": record["approval_status"],
        "clna_phase": record["clna_phase"],
        "approval_round": record["approval_round"],
        "authored_by_user_id": record["authored_by_user_id"],
        "clna_certified_by_user_id": record["clna_certified_by_user_id"],
        "labor_market_data_asof": record["labor_market_data_asof"],
        "clna_certified_on": record["clna_certified_on"],
        "clna_expires_on": record["clna_expires_on"],
        "alignment_index": num(record["alignment_index"], 4),
        "alignment_index_variant": record["alignment_index_variant"],
        "secondary_credit_total": num(record["secondary_credit_total"], 2),
        "postsecondary_credit_total": num(record["postsecondary_credit_total"], 2),
        "articulated_credit_total": num(record["articulated_credit_total"], 2),
        "federal_reporting_eligible": record["approval_status"] == "STATE_APPROVED",
        "open_finding_codes": list(record["open_finding_codes"]),
        "narrative_url": record["narrative_url"],
    }
    return _common(record, out)


def course(record):
    out = {
        "id": record["id"],
        "pos_id": record["pos_id"],
        "code": record["code"],
        "title": record["title"],
        "segment": record["segment"],
        "position": record["position"],
        "credit_hours": num(record["credit_hours"], 2),
        "articulated_credit_hours": num(record["articulated_credit_hours"], 2),
        "articulation_verified": record["articulation_verified"],
        "prerequisite_course_id": record["prerequisite_course_id"],
        "status": record["status"],
        "depth_from_root": calc.depth_from_root(record),
    }
    return _common(record, out)


def credential(record):
    out = {
        "id": record["id"],
        "pos_id": record["pos_id"],
        "code": record["code"],
        "title": record["title"],
        "tier": record["tier"],
        "exam_required": record["exam_required"],
        "counts_toward_indicator": record["counts_toward_indicator"],
        "verified_attainment_count": calc.verified_attainment_count(record["id"]),
    }
    return _common(record, out)


def student(record):
    out = {
        "id": record["id"],
        "pos_id": record["pos_id"],
        "state_student_id": record["state_student_id"],
        "cohort_year": record["cohort_year"],
        "special_population_codes": list(record["special_population_codes"]),
        "cte_credits_earned": num(record["cte_credits_earned"], 2),
        "concentrator_status": record["concentrator_status"],
        "verified_qualifying_attainment_count":
            record["verified_qualifying_attainment_count"],
        "exited_on": record["exited_on"],
        "exit_reason": record["exit_reason"],
    }
    return _common(record, out)


def attainment(record):
    """Immutable: id and created_at only -- no updated_at, no version."""
    return {
        "id": record["id"],
        "student_id": record["student_id"],
        "credential_id": record["credential_id"],
        "attained_on": record["attained_on"],
        "exam_score": num(record["exam_score"], 2),
        "verification_status": record["verification_status"],
        "counted_for_indicator": record["counted_for_indicator"],
        "created_at": record["created_at"],
    }


def committee(record):
    active, employers, chair_id = calc.committee_counts(record["id"])
    out = {
        "id": record["id"],
        "pos_id": record["pos_id"],
        "name": record["name"],
        "quorum_min_members": record["quorum_min_members"],
        "employer_seat_min": record["employer_seat_min"],
        "status": record["status"],
        "active_member_count": active,
        "employer_member_count": employers,
        "chair_member_id": chair_id,
    }
    return _common(record, out)


def member(record):
    out = {
        "id": record["id"],
        "committee_id": record["committee_id"],
        "full_name": record["full_name"],
        "sector": record["sector"],
        "seat_code": record["seat_code"],
        "term_start_on": record["term_start_on"],
        "term_end_on": record["term_end_on"],
        "is_chair": record["is_chair"],
        "status": member_status(record),
    }
    return _common(record, out)


def meeting(record):
    out = {
        "id": record["id"],
        "committee_id": record["committee_id"],
        "agenda_kind": record["agenda_kind"],
        "scheduled_for": record["scheduled_for"],
        "held_at": record["held_at"],
        "attendee_member_ids": list(record["attendee_member_ids"]),
        "vote_yes": record["vote_yes"],
        "vote_no": record["vote_no"],
        "minutes_url": record["minutes_url"],
        "amendment_reason": record["amendment_reason"],
        "minutes_status": record["minutes_status"],
        "eligible_attendee_count": record["eligible_attendee_count"],
        "employer_attendee_count": record["employer_attendee_count"],
        "quorum_met": record["quorum_met"],
        "endorsement_passed": record["endorsement_passed"],
    }
    return _common(record, out)


def award_status(record):
    """OPEN inside the inclusive window, CLOSED once the clock passes its end."""
    end = parse_date(record["obligation_window_end"])
    if end is not None and clock_date() > end:
        return "CLOSED"
    return "OPEN"


def award(record):
    out = {
        "id": record["id"],
        "fiscal_year": record["fiscal_year"],
        "allocation_cents": record["allocation_cents"],
        "obligation_window_start": record["obligation_window_start"],
        "obligation_window_end": record["obligation_window_end"],
        "status": award_status(record),
        "direct_obligated_cents": record["direct_obligated_cents"],
        "indirect_rate": num(record["indirect_rate"], 4),
        "indirect_pool_cents": record["indirect_pool_cents"],
        "obligated_cents": record["obligated_cents"],
        "remaining_cents": record["remaining_cents"],
        "admin_cap_cents": record["admin_cap_cents"],
        "admin_obligated_cents": record["admin_obligated_cents"],
    }
    return _common(record, out)


def expenditure(record):
    out = {
        "id": record["id"],
        "grant_award_id": record["grant_award_id"],
        "pos_id": record["pos_id"],
        "category": record["category"],
        "description": record["description"],
        "unit_cost_cents": record["unit_cost_cents"],
        "quantity": record["quantity"],
        "gross_cents": record["gross_cents"],
        "federal_share_pct": num(record["federal_share_pct"], 4),
        "approved_cents": record["approved_cents"],
        "asset_tag": record["asset_tag"],
        "service_period_start": record["service_period_start"],
        "service_period_end": record["service_period_end"],
        "status": record["status"],
        "requested_by_user_id": record["requested_by_user_id"],
        "certified_by_user_id": record["certified_by_user_id"],
        "finding_code": record["finding_code"],
        "obligation_reference": record["obligation_reference"],
        "void_reason": record["void_reason"],
    }
    return _common(record, out)


def indicator(record):
    live = calc.preliminary(record)
    out = {
        "id": record["id"],
        "pos_id": record["pos_id"],
        "indicator_code": record["indicator_code"],
        "reporting_year": record["reporting_year"],
        "cohort_year": record["cohort_year"],
        "baseline_pct": num(record["baseline_pct"], 2),
        "negotiated_level_pct": num(record["negotiated_level_pct"], 2),
        "last_offer_pct": num(record["last_offer_pct"], 2),
        "last_offer_by_user_id": record["last_offer_by_user_id"],
        "last_offer_by_role": record["last_offer_by_role"],
        "negotiation_round": record["negotiation_round"],
        "denominator_count": live["denominator_count"],
        "numerator_count": live["numerator_count"],
        "small_cohort_flag": live["small_cohort_flag"],
        "preliminary_actual_pct": num(live["preliminary_actual_pct"], 2),
        "preliminary_status_projection": live["preliminary_status_projection"],
        "actual_pct": num(record["actual_pct"], 2),
        "met_threshold_pct": num(record["met_threshold_pct"], 2),
        "consecutive_miss_count": record["consecutive_miss_count"],
        "status": record["status"],
        "closed_on": record["closed_on"],
    }
    return _common(record, out)


def plan(record):
    out = {
        "id": record["id"],
        "performance_indicator_id": record["performance_indicator_id"],
        "funding_expenditure_id": record["funding_expenditure_id"],
        "milestones": [dict(m) for m in record["milestones"]],
        "milestone_count": len(record["milestones"]),
        "revision_round": record["revision_round"],
        "status": record["status"],
        "return_reasons": list(record["return_reasons"]),
        "submitted_at": record["submitted_at"],
        "accepted_at": record["accepted_at"],
    }
    return _common(record, out)


def educator(record):
    out = {
        "id": record["id"],
        "pos_id": record["pos_id"],
        "full_name": record["full_name"],
        "certification_route": record["certification_route"],
        "claimed_industry_hours": record["claimed_industry_hours"],
        "verified_industry_hours": record["verified_industry_hours"],
        "credential_expires_on": record["credential_expires_on"],
        "status": record["status"],
    }
    return _common(record, out)
