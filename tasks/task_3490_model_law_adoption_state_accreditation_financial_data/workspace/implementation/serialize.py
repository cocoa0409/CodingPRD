"""Entity serializers — exact field names from the scaffold entity table.

created_at / updated_at render with 3 fractional digits; every other datetime
renders as the clock reads (iso_domain). Decimals render as JSON numbers.
"""

from util import iso3, iso_domain, num


def _base(rec):
    return {
        "id": rec["id"],
        "created_at": iso3(rec["created_at"]),
        "updated_at": iso3(rec["updated_at"]),
        "version": rec["version"],
    }


def serialize_model_act(r):
    out = _base(r)
    out.update({
        "model_code": r["model_code"],
        "version_label": r["version_label"],
        "title": r["title"],
        "act_type": r["act_type"],
        "committee_name": r["committee_name"],
        "is_core": r["is_core"],
        "status": r["status"],
        "published_at": iso_domain(r["published_at"]),
        "votes_cast": r["votes_cast"],
        "favorable_votes": r["favorable_votes"],
    })
    return out


def serialize_exposure_draft(r):
    out = _base(r)
    out.update({
        "model_act_id": r["model_act_id"],
        "exposure_number": r["exposure_number"],
        "comment_window_start": iso_domain(r["comment_window_start"]),
        "comment_window_end": iso_domain(r["comment_window_end"]),
        "status": r["status"],
    })
    return out


def serialize_ballot(r):
    out = _base(r)
    out.update({
        "model_act_id": r["model_act_id"],
        "state_code": r["state_code"],
        "vote": r["vote"],
        "status": r["status"],
        "cast_at": iso_domain(r["cast_at"]),
    })
    return out


def serialize_state(r):
    out = _base(r)
    out.update({
        "code": r["code"],
        "name": r["name"],
        "accreditation_status": r["accreditation_status"],
        "consecutive_fail_count": r["consecutive_fail_count"],
        "core_act_coverage_pct": num(r["core_act_coverage_pct"]),
    })
    return out


def serialize_adoption(r):
    out = _base(r)
    out.update({
        "model_act_id": r["model_act_id"],
        "state_code": r["state_code"],
        "adopted_citation": r["adopted_citation"],
        "enacted_on": iso_domain(r["enacted_on"]),
        "status": r["status"],
    })
    return out


def serialize_review(r):
    out = _base(r)
    out.update({
        "state_id": r["state_id"],
        "period_start": iso_domain(r["period_start"]),
        "period_end": iso_domain(r["period_end"]),
        "team_lead_id": r["team_lead_id"],
        "self_assessment_compliant": r["self_assessment_compliant"],
        "self_assessment_total": r["self_assessment_total"],
        "desk_score": num(r["desk_score"]),
        "findings_compliant": r["findings_compliant"],
        "findings_total": r["findings_total"],
        "onsite_score": num(r["onsite_score"]),
        "proposed_outcome": r["proposed_outcome"],
        "origin": r["origin"],
        "status": r["status"],
    })
    return out


def serialize_insurer(r):
    out = _base(r)
    out.update({
        "naic_code": r["naic_code"],
        "name": r["name"],
        "domicile_state_code": r["domicile_state_code"],
        "status": r["status"],
        "latest_rbc_ratio": num(r["latest_rbc_ratio"]),
        "latest_action_level": r["latest_action_level"],
    })
    return out


def serialize_filing(r):
    out = _base(r)
    out.update({
        "insurer_id": r["insurer_id"],
        "period_year": r["period_year"],
        "period_quarter": r["period_quarter"],
        "valuation_standard_code": r["valuation_standard_code"],
        "valuation_standard_version_label": r["valuation_standard_version_label"],
        "reported_surplus_cents": r["reported_surplus_cents"],
        "asset_risk_cents": r["asset_risk_cents"],
        "underwriting_risk_cents": r["underwriting_risk_cents"],
        "other_risk_cents": r["other_risk_cents"],
        "status": r["status"],
        "edit_failures": list(r["edit_failures"]),
    })
    return out


def serialize_rbc_report(r):
    out = _base(r)
    out.update({
        "filing_id": r["filing_id"],
        "insurer_naic_code": r["insurer_naic_code"],
        "tac_cents": num(r["tac_cents"]),
        "acl_covariance_cents": num(r["acl_covariance_cents"]),
        "acl_additive_cents": num(r["acl_additive_cents"]),
        "ratio_covariance": num(r["ratio_covariance"]),
        "ratio_additive": num(r["ratio_additive"]),
        "action_level": r["action_level"],
    })
    return out


def serialize_producer(r):
    out = _base(r)
    out.update({
        "npn": r["npn"],
        "full_name": r["full_name"],
        "home_state_code": r["home_state_code"],
        "active_license_count": r["active_license_count"],
    })
    return out


def serialize_license(r):
    out = _base(r)
    out.update({
        "producer_id": r["producer_id"],
        "state_code": r["state_code"],
        "license_class": r["license_class"],
        "effective_from": iso_domain(r["effective_from"]),
        "valid_until": iso_domain(r["valid_until"]),
        "status": r["status"],
    })
    return out


def serialize_call(r):
    out = _base(r)
    out.update({
        "call_code": r["call_code"],
        "topic": r["topic"],
        "lead_state_code": r["lead_state_code"],
        "total_cost_cents": r["total_cost_cents"],
        "status": r["status"],
    })
    return out


def serialize_response(r):
    out = _base(r)
    out.update({
        "call_id": r["call_id"],
        "insurer_naic_code": r["insurer_naic_code"],
        "direct_premium_cents": r["direct_premium_cents"],
        "complaint_count": r["complaint_count"],
        "exam_priority_score": num(r["exam_priority_score"]),
        "escalation_flag": r["escalation_flag"],
        "allocated_cost_cents": r["allocated_cost_cents"],
        "cost_share_excluded": r["cost_share_excluded"],
    })
    return out


def serialize_standard(r):
    out = _base(r)
    out.update({
        "code": r["code"],
        "version_label": r["version_label"],
        "guidance_text": r["guidance_text"],
        "author_user_id": r["author_user_id"],
        "status": r["status"],
    })
    return out
