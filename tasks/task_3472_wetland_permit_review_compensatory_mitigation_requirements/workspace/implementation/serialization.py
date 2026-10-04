"""Entity serializers: internal dicts -> JSON-safe API representations.

Datetimes render as ISO 8601 UTC with three fractional digits; Decimals
render as JSON numbers (int when integral, else float). Computed-on-read
fields (prior_violation_count, bank inventory maps, revenue, penalty
accrual) are derived here without mutating the stored entity.
"""

from decimal import Decimal

from calculations import bank_inventory, penalty_accrued
from db import STORE, iso


def num(value):
    """Decimal -> JSON number (int when integral, else float)."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    return value


def _common(entity):
    return {
        "id": entity["id"],
        "created_at": iso(entity["created_at"]),
        "updated_at": iso(entity["updated_at"]),
        "version": entity["version"],
    }


def applicant_out(a):
    out = _common(a)
    out.update({
        "legal_name": a["legal_name"],
        "organization_type": a["organization_type"],
        "contact_email": a["contact_email"],
        # Computed: enforcement cases naming this applicant that have
        # matured past OPENED (case_status != OPENED).
        "prior_violation_count": sum(
            1 for c in STORE["cases"].values()
            if c["responsible_applicant_id"] == a["id"]
            and c["case_status"] != "OPENED"),
    })
    return out


def site_out(s):
    out = _common(s)
    out.update({
        "applicant_id": s["applicant_id"],
        "site_name": s["site_name"],
        "state_code": s["state_code"],
        "watershed_code": s["watershed_code"],
        "total_acres": num(s["total_acres"]),
        "resource_types_present": list(s["resource_types_present"]),
    })
    return out


def jd_out(j):
    out = _common(j)
    out.update({
        "site_id": j["site_id"],
        "jd_type": j["jd_type"],
        "determination": j["determination"],
        "rationale": j["rationale"],
        "issued_date": iso(j["issued_date"]),
        "expiration_date": iso(j["expiration_date"]),
        "status": j["status"],
    })
    return out


def appeal_out(a):
    out = _common(a)
    out.update({
        "jd_id": a["jd_id"],
        "appellant_applicant_id": a["appellant_applicant_id"],
        "grounds_text": a["grounds_text"],
        "filed_date": iso(a["filed_date"]),
        "decided_date": iso(a["decided_date"]),
        "decision_rationale": a["decision_rationale"],
        "status": a["status"],
    })
    return out


def application_out(app):
    out = _common(app)
    out.update({
        "applicant_id": app["applicant_id"],
        "site_id": app["site_id"],
        "jd_id": app["jd_id"],
        "pathway": app["pathway"],
        "general_permit_code": app["general_permit_code"],
        "impacts": [
            {"resource_type": line["resource_type"],
             "impact_acres": num(line["impact_acres"])}
            for line in app["impacts"]
        ],
        "total_impact_acres": num(app["total_impact_acres"]),
        "is_after_the_fact": app["is_after_the_fact"],
        "enforcement_case_id": app["enforcement_case_id"],
        "project_purpose": app["project_purpose"],
        "estimated_cost_dollars": num(app["estimated_cost_dollars"]),
        "submitted_date": iso(app["submitted_date"]),
        "screening_reviewer_id": app["screening_reviewer_id"],
        "pir_score": num(app["pir_score"]),
        "pir_outcome": app["pir_outcome"],
        "compensatory_mitigation_required": app["compensatory_mitigation_required"],
        "notice_status": app["notice_status"],
        "notice_published_date": iso(app["notice_published_date"]),
        "comment_period_days": app["comment_period_days"],
        "status": app["status"],
    })
    return out


def aa_out(aa):
    out = _common(aa)
    out.update({
        "application_id": aa["application_id"],
        "avoidance_demonstrated": aa["avoidance_demonstrated"],
        "avoidance_narrative": aa["avoidance_narrative"],
        "minimization_steps": list(aa["minimization_steps"]),
        "ledpa_conclusion": aa["ledpa_conclusion"],
        "offsite_alternatives_considered": aa["offsite_alternatives_considered"],
        "revision_count": aa["revision_count"],
        "status": aa["status"],
    })
    return out


def comment_out(c):
    out = _common(c)
    out.update({
        "application_id": c["application_id"],
        "agency": c["agency"],
        "comment_type": c["comment_type"],
        "comment_text": c["comment_text"],
        "filed_date": iso(c["filed_date"]),
        "resolution_text": c["resolution_text"],
        "status": c["status"],
    })
    return out


def plan_out(p):
    out = _common(p)
    out.update({
        "application_id": p["application_id"],
        "mechanism": p["mechanism"],
        "financial_assurance_dollars": num(p["financial_assurance_dollars"]),
        "stewardship_entity_name": p["stewardship_entity_name"],
        "long_term_stewardship_secured": p["long_term_stewardship_secured"],
        "required_credits_by_type": {k: num(v) for k, v in
                                     p["required_credits_by_type"].items()},
        "final_credits_required_by_type": (
            {k: num(v) for k, v in p["final_credits_required_by_type"].items()}
            if p["final_credits_required_by_type"] is not None else None),
        "ilf_fee_due_dollars": num(p["ilf_fee_due_dollars"]),
        "ilf_fee_paid_dollars": num(p["ilf_fee_paid_dollars"]),
        "assurance_required_dollars": num(p["assurance_required_dollars"]),
        "secured_date": iso(p["secured_date"]),
        "status": p["status"],
    })
    return out


def bank_out(b):
    reserved, purchased, available, revenue = bank_inventory(b)
    out = _common(b)
    out.update({
        "bank_name": b["bank_name"],
        "sponsor_name": b["sponsor_name"],
        "state_code": b["state_code"],
        "service_area_watersheds": list(b["service_area_watersheds"]),
        "credit_capacity": {k: num(v) for k, v in b["credit_capacity"].items()},
        "base_price_per_credit": {k: num(v) for k, v in
                                  b["base_price_per_credit"].items()},
        "credits_reserved_by_type": {k: num(v) for k, v in reserved.items()},
        "credits_purchased_by_type": {k: num(v) for k, v in purchased.items()},
        "available_credits_by_type": {k: num(v) for k, v in available.items()},
        "revenue_dollars": num(revenue),
        "status": b["status"],
    })
    return out


def credit_txn_out(t):
    out = _common(t)
    out.update({
        "bank_id": t["bank_id"],
        "plan_id": t["plan_id"],
        "resource_type": t["resource_type"],
        "credits": num(t["credits"]),
        "price_per_credit_dollars": num(t["price_per_credit_dollars"]),
        "total_price_dollars": num(t["total_price_dollars"]),
        "status": t["status"],
    })
    return out


def permit_out(p):
    out = _common(p)
    out.update({
        "application_id": p["application_id"],
        "permit_number": p["permit_number"],
        "issue_date": iso(p["issue_date"]),
        "expiration_date": iso(p["expiration_date"]),
        "special_conditions": list(p["special_conditions"]),
        "status": p["status"],
    })
    return out


def report_out(r):
    out = _common(r)
    out.update({
        "permit_id": r["permit_id"],
        "plan_id": r["plan_id"],
        "period_index": r["period_index"],
        "due_date": iso(r["due_date"]),
        "coverage_start": iso(r["coverage_start"]),
        "coverage_end": iso(r["coverage_end"]),
        "findings_text": r["findings_text"],
        "submitted_date": iso(r["submitted_date"]),
        "outcome": r["outcome"],
        "deficiency_notes": r["deficiency_notes"],
        "status": r["status"],
    })
    return out


def case_out(c):
    out = _common(c)
    out.update({
        "site_id": c["site_id"],
        "responsible_applicant_id": c["responsible_applicant_id"],
        "unauthorized_fill_acres": num(c["unauthorized_fill_acres"]),
        "description": c["description"],
        "case_source": c["case_source"],
        "opened_by_officer_id": c["opened_by_officer_id"],
        "opened_date": iso(c["opened_date"]),
        "confirmed_date": iso(c["confirmed_date"]),
        "penalty_accrued_dollars": num(penalty_accrued(c)),
        "penalty_final_dollars": num(c["penalty_final_dollars"]),
        "resolution_track": c["resolution_track"],
        "atf_application_id": c["atf_application_id"],
        "restoration_deadline": iso(c["restoration_deadline"]),
        "extension_used": c["extension_used"],
        "case_status": c["case_status"],
    })
    return out
