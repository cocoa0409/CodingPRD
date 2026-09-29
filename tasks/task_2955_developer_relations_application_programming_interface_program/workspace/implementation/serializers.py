"""Wire representations for every entity."""
from decimal import Decimal

from db import format_instant


def _num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def developer_out(d):
    return {
        "id": d["id"],
        "org_name": d["org_name"],
        "contact_email": d["contact_email"],
        "region_code": d["region_code"],
        "onboarding_state": d["onboarding_state"],
        "standing": d["standing"],
        "directory_state": d["directory_state"],
        "directory_summary": d["directory_summary"],
        "docs_version_acknowledged": d["docs_version_acknowledged"],
        "tos_version_accepted": d["tos_version_accepted"],
        "certification_level": d["certification_level"],
        "certification_expires_at": format_instant(d["certification_expires_at"]),
        "hackathon_award_count": d["hackathon_award_count"],
        "clean_window_count": d["clean_window_count"],
        "throttled_window_count": d["throttled_window_count"],
        "violation_points": d["violation_points"],
        "trust_score": d["trust_score"],
        "audited_trust_score": d["audited_trust_score"],
        "revoked_at": format_instant(d["revoked_at"]),
        "created_at": format_instant(d["created_at"]),
        "updated_at": format_instant(d["updated_at"]),
        "version": d["version"],
    }


def api_product_out(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "data_sensitivity": p["data_sensitivity"],
        "scope_catalog": [
            {"scope": entry["scope"], "sensitivity": entry["sensitivity"]}
            for entry in p["scope_catalog"]
        ],
        "sample_app_slugs": list(p["sample_app_slugs"]),
        "sustained_rpm_pool": p["sustained_rpm_pool"],
        "monthly_call_pool": p["monthly_call_pool"],
        "allocated_sustained_rpm": p["allocated_sustained_rpm"],
        "allocated_monthly_calls": p["allocated_monthly_calls"],
        "available_sustained_rpm": p["sustained_rpm_pool"] - p["allocated_sustained_rpm"],
        "available_monthly_calls": p["monthly_call_pool"] - p["allocated_monthly_calls"],
        "required_tos_version": p["required_tos_version"],
        "demand_index": _num(p["demand_index"]),
        "created_at": format_instant(p["created_at"]),
        "updated_at": format_instant(p["updated_at"]),
        "version": p["version"],
    }


def api_version_out(v):
    return {
        "id": v["id"],
        "api_product_id": v["api_product_id"],
        "semver": v["semver"],
        "lifecycle_state": v["lifecycle_state"],
        "breaking_change": v["breaking_change"],
        "migration_guide_url": v["migration_guide_url"],
        "migration_guide_published_at": format_instant(v["migration_guide_published_at"]),
        "deprecation_announced_at": format_instant(v["deprecation_announced_at"]),
        "sunset_at": format_instant(v["sunset_at"]),
        "required_notice_days": v["required_notice_days"],
        "notice_days_at_announcement": v["notice_days_at_announcement"],
        "sunset_completed_at": format_instant(v["sunset_completed_at"]),
        "created_at": format_instant(v["created_at"]),
        "updated_at": format_instant(v["updated_at"]),
        "version": v["version"],
    }


def access_application_out(a):
    return {
        "id": a["id"],
        "developer_id": a["developer_id"],
        "target_api_version_id": a["target_api_version_id"],
        "requested_tier": a["requested_tier"],
        "requested_scopes": list(a["requested_scopes"]),
        "requested_monthly_calls": a["requested_monthly_calls"],
        "justification_text": a["justification_text"],
        "state": a["state"],
        "revision_round": a["revision_round"],
        "reviewer_user_id": a["reviewer_user_id"],
        "approver_user_id": a["approver_user_id"],
        "approved_tier": a["approved_tier"],
        "granted_scopes": list(a["granted_scopes"]) if a["granted_scopes"] is not None else None,
        "data_access_limit": a["data_access_limit"],
        "changes_requested_note": a["changes_requested_note"],
        "decision_reason": a["decision_reason"],
        "decided_at": format_instant(a["decided_at"]),
        "created_at": format_instant(a["created_at"]),
        "updated_at": format_instant(a["updated_at"]),
        "version": a["version"],
    }


def quota_assignment_out(q):
    return {
        "id": q["id"],
        "developer_id": q["developer_id"],
        "access_application_id": q["access_application_id"],
        "pinned_api_version_id": q["pinned_api_version_id"],
        "tier": q["tier"],
        "granted_scopes": list(q["granted_scopes"]),
        "sustained_rpm": q["sustained_rpm"],
        "burst_rpm": q["burst_rpm"],
        "burst_credit_balance": q["burst_credit_balance"],
        "monthly_call_allowance": q["monthly_call_allowance"],
        "bonus_call_credit": q["bonus_call_credit"],
        "monthly_calls_consumed": q["monthly_calls_consumed"],
        "entitlement_state": q["entitlement_state"],
        "throttle_state": q["throttle_state"],
        "trust_multiplier_applied": _num(q["trust_multiplier_applied"]),
        "activated_at": format_instant(q["activated_at"]),
        "suspended_at": format_instant(q["suspended_at"]),
        "suspension_reason": q["suspension_reason"],
        "retired_at": format_instant(q["retired_at"]),
        "last_reset_at": format_instant(q["last_reset_at"]),
        "created_at": format_instant(q["created_at"]),
        "updated_at": format_instant(q["updated_at"]),
        "version": q["version"],
    }


def upgrade_request_out(u):
    return {
        "id": u["id"],
        "quota_assignment_id": u["quota_assignment_id"],
        "requested_sustained_rpm": u["requested_sustained_rpm"],
        "justification_text": u["justification_text"],
        "requested_delta_rpm": u["requested_delta_rpm"],
        "granted_delta_rpm": u["granted_delta_rpm"],
        "state": u["state"],
        "denial_reason": u["denial_reason"],
        "run_sequence": u["run_sequence"],
        "decided_at": format_instant(u["decided_at"]),
        "created_at": format_instant(u["created_at"]),
        "updated_at": format_instant(u["updated_at"]),
        "version": u["version"],
    }


def usage_window_out(w):
    return {
        "id": w["id"],
        "quota_assignment_id": w["quota_assignment_id"],
        "window_start": format_instant(w["window_start"]),
        "window_end": format_instant(w["window_end"]),
        "total_calls": w["total_calls"],
        "burst_calls": w["burst_calls"],
        "attribution_variant": w["attribution_variant"],
        "calls_charged_to_allowance": w["calls_charged_to_allowance"],
        "burst_credit_consumed": w["burst_credit_consumed"],
        "monthly_calls_consumed_after": w["monthly_calls_consumed_after"],
        "overage_calls": w["overage_calls"],
        "rate_limit_breach": w["rate_limit_breach"],
        "resulting_throttle_state": w["resulting_throttle_state"],
        "created_at": format_instant(w["created_at"]),
    }


def sandbox_lease_out(l):
    return {
        "id": l["id"],
        "developer_id": l["developer_id"],
        "api_product_id": l["api_product_id"],
        "starts_at": format_instant(l["starts_at"]),
        "lease_days": l["lease_days"],
        "expires_at": format_instant(l["expires_at"]),
        "sample_app_slug": l["sample_app_slug"],
        "state": l["state"],
        "released_at": format_instant(l["released_at"]),
        "closed_reason": l["closed_reason"],
        "created_at": format_instant(l["created_at"]),
        "updated_at": format_instant(l["updated_at"]),
        "version": l["version"],
    }


def violation_case_out(c):
    return {
        "id": c["id"],
        "developer_id": c["developer_id"],
        "quota_assignment_id": c["quota_assignment_id"],
        "category": c["category"],
        "severity": c["severity"],
        "summary": c["summary"],
        "evidence_window_ids": list(c["evidence_window_ids"])
        if c["evidence_window_ids"] is not None
        else None,
        "state": c["state"],
        "penalty_points": c["penalty_points"],
        "points_applied": c["points_applied"],
        "opened_by_user_id": c["opened_by_user_id"],
        "investigator_user_id": c["investigator_user_id"],
        "adjudicator_user_id": c["adjudicator_user_id"],
        "remediation_deadline": format_instant(c["remediation_deadline"]),
        "appeal_deadline": format_instant(c["appeal_deadline"]),
        "outcome": c["outcome"],
        "appeal_reason": c["appeal_reason"],
        "appeal_count": c["appeal_count"],
        "decision_note": c["decision_note"],
        "created_at": format_instant(c["created_at"]),
        "updated_at": format_instant(c["updated_at"]),
        "version": c["version"],
    }


def support_case_out(s):
    return {
        "id": s["id"],
        "kind": s["kind"],
        "developer_id": s["developer_id"],
        "api_product_id": s["api_product_id"],
        "severity": s["severity"],
        "title": s["title"],
        "started_at": format_instant(s["started_at"]),
        "state": s["state"],
        "escalation_tier": s["escalation_tier"],
        "first_response_due_minutes": s["first_response_due_minutes"],
        "first_response_at": format_instant(s["first_response_at"]),
        "first_response_breached": s["first_response_breached"],
        "communication_count": s["communication_count"],
        "last_communication_at": format_instant(s["last_communication_at"]),
        "max_communication_gap_minutes": s["max_communication_gap_minutes"],
        "comms_gap_breached": s["comms_gap_breached"],
        "resolved_at": format_instant(s["resolved_at"]),
        "downtime_minutes": s["downtime_minutes"],
        "credit_uplift_applied": _num(s["credit_uplift_applied"]),
        "affected_assignment_count": s["affected_assignment_count"],
        "total_credit_calls": s["total_credit_calls"],
        "resolution_note": s["resolution_note"],
        "created_at": format_instant(s["created_at"]),
        "updated_at": format_instant(s["updated_at"]),
        "version": s["version"],
    }


def feedback_item_out(f):
    return {
        "id": f["id"],
        "developer_id": f["developer_id"],
        "api_product_id": f["api_product_id"],
        "category": f["category"],
        "body": f["body"],
        "state": f["state"],
        "author_top_tier": f["author_top_tier"],
        "raw_impact": _num(f["raw_impact"]),
        "priority_score": _num(f["priority_score"]),
        "triaged_by_user_id": f["triaged_by_user_id"],
        "decision_note": f["decision_note"],
        "triaged_at": format_instant(f["triaged_at"]),
        "created_at": format_instant(f["created_at"]),
        "updated_at": format_instant(f["updated_at"]),
        "version": f["version"],
    }
