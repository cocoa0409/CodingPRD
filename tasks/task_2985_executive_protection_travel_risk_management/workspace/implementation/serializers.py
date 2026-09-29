"""Entity representations.

PRD 2.4: eleven types carry id, created_at, updated_at and version; the two
append-only event records (PublicExposureSignal, CheckIn) carry only id and
created_at -- updated_at and version are absent from their representation, not
present-and-null.
"""

from util import fmt_instant


def _audit(row):
    return {
        "id": row["id"],
        "created_at": fmt_instant(row["created_at"]),
        "updated_at": fmt_instant(row["updated_at"]),
        "version": row["version"],
    }


def _event(row):
    return {
        "id": row["id"],
        "created_at": fmt_instant(row["created_at"]),
    }


def executive(row):
    out = {
        "full_name": row["full_name"],
        "tier": row["tier"],
        "role_title": row["role_title"],
        "base_country_code": row["base_country_code"],
        "annual_security_budget_cents": row["annual_security_budget_cents"],
        "consent_scope": row["consent_scope"],
        "consent_expires_at": fmt_instant(row["consent_expires_at"]),
        "residential_survey_status": row["residential_survey_status"],
        "residential_component": row["residential_component"],
        "public_exposure_score": row["public_exposure_score"],
        "threat_level": row["threat_level"],
        "committed_budget_cents": row["committed_budget_cents"],
        "spent_budget_cents": row["spent_budget_cents"],
        "remaining_budget_cents": remaining_budget_cents(row),
        "annual_disclosed_perquisite_cents": row["annual_disclosed_perquisite_cents"],
        "business_borne_security_cents": row["business_borne_security_cents"],
        "open_degraded_trip_count": row["open_degraded_trip_count"],
    }
    out.update(_audit(row))
    return out


def remaining_budget_cents(row):
    """PRD 2.10: annual less committed less spent."""
    return (row["annual_security_budget_cents"]
            - row["committed_budget_cents"]
            - row["spent_budget_cents"])


def staff(row):
    out = {
        "full_name": row["full_name"],
        "staff_role": row["staff_role"],
        "certification_expires_at": fmt_instant(row["certification_expires_at"]),
        "hourly_rate_cents": row["hourly_rate_cents"],
        "committed_detail_hours": row["committed_detail_hours"],
        "released_detail_hours": row["released_detail_hours"],
    }
    out.update(_audit(row))
    return out


def exposure_signal(row):
    out = {
        "executive_id": row["executive_id"],
        "signal_type": row["signal_type"],
        "severity": row["severity"],
        "observed_at": fmt_instant(row["observed_at"]),
        "source_note": row["source_note"],
    }
    out.update(_event(row))
    return out


def risk_assessment(row):
    out = {
        "executive_id": row["executive_id"],
        "authored_by_staff_id": row["authored_by_staff_id"],
        "approved_by_staff_id": row["approved_by_staff_id"],
        "supersedes_assessment_id": row["supersedes_assessment_id"],
        "status": row["status"],
        "threat_monitoring_score": row["threat_monitoring_score"],
        "public_exposure_component": row["public_exposure_component"],
        "residential_component_snapshot": row["residential_component_snapshot"],
        "composite_risk_score": row["composite_risk_score"],
        "revision_round": row["revision_round"],
        "review_notes": row["review_notes"],
        "submitted_at": fmt_instant(row["submitted_at"]),
        "approved_at": fmt_instant(row["approved_at"]),
    }
    out.update(_audit(row))
    return out


def destination_rating(row):
    out = {
        "country_code": row["country_code"],
        "crime_index": row["crime_index"],
        "political_instability_index": row["political_instability_index"],
        "medical_infrastructure_index": row["medical_infrastructure_index"],
        "natural_hazard_index": row["natural_hazard_index"],
        "composite_destination_score": row["composite_destination_score"],
        "rating_band": row["rating_band"],
        "insurance_required_coverage_cents": row["insurance_required_coverage_cents"],
        "advisory_effective_at": fmt_instant(row["advisory_effective_at"]),
        "advisory_note": row["advisory_note"],
    }
    out.update(_audit(row))
    return out


def insurance_policy(row):
    out = {
        "executive_id": row["executive_id"],
        "policy_type": row["policy_type"],
        "coverage_cents": row["coverage_cents"],
        "effective_from": fmt_instant(row["effective_from"]),
        "effective_to": fmt_instant(row["effective_to"]),
        "excluded_country_codes": list(row["excluded_country_codes"]),
        "status": row["status"],
        "verified_at": fmt_instant(row["verified_at"]),
        "verification_note": row["verification_note"],
    }
    out.update(_audit(row))
    return out


def trip(row):
    out = {
        "executive_id": row["executive_id"],
        "created_by_staff_id": row["created_by_staff_id"],
        "risk_assessment_id": row["risk_assessment_id"],
        "insurance_policy_id": row["insurance_policy_id"],
        "trip_purpose": row["trip_purpose"],
        "primary_destination_country_code": row["primary_destination_country_code"],
        "depart_at": fmt_instant(row["depart_at"]),
        "return_at": fmt_instant(row["return_at"]),
        "cost_allocation_method": row["cost_allocation_method"],
        "approval_state": row["approval_state"],
        "readiness_state": row["readiness_state"],
        "required_approval_level": row["required_approval_level"],
        "max_leg_risk_band": row["max_leg_risk_band"],
        "provisional_security_cost_cents": row["provisional_security_cost_cents"],
        "total_security_cost_cents": row["total_security_cost_cents"],
        "perquisite_taxable_cents": row["perquisite_taxable_cents"],
        "business_borne_cents": row["business_borne_cents"],
        "perquisite_rate_applied": row["perquisite_rate_applied"],
        "check_in_interval_hours": row["check_in_interval_hours"],
        "next_check_in_due_at": fmt_instant(row["next_check_in_due_at"]),
        "missed_check_in_count": row["missed_check_in_count"],
        "duress_active": row["duress_active"],
        "briefing_ack_at": fmt_instant(row["briefing_ack_at"]),
        "denied_reason": row["denied_reason"],
        "closed_at": fmt_instant(row["closed_at"]),
    }
    out.update(_audit(row))
    return out


def trip_leg(row):
    out = {
        "trip_id": row["trip_id"],
        "sequence_no": row["sequence_no"],
        "destination_country_code": row["destination_country_code"],
        "arrive_at": fmt_instant(row["arrive_at"]),
        "depart_at": fmt_instant(row["depart_at"]),
        "leg_risk_band": row["leg_risk_band"],
        "required_advance_items": list(row["required_advance_items"]),
        "completed_advance_items": list(row["completed_advance_items"]),
        "waived_advance_items": list(row["waived_advance_items"]),
        "advance_complete": row["advance_complete"],
        "lead_agent_covered": row["lead_agent_covered"],
    }
    out.update(_audit(row))
    return out


def detail_assignment(row):
    out = {
        "trip_leg_id": row["trip_leg_id"],
        "staff_id": row["staff_id"],
        "role_on_detail": row["role_on_detail"],
        "starts_at": fmt_instant(row["starts_at"]),
        "ends_at": fmt_instant(row["ends_at"]),
        "status": row["status"],
        "planned_billable_hours": row["planned_billable_hours"],
        "actual_ends_at": fmt_instant(row["actual_ends_at"]),
        "final_billable_hours": row["final_billable_hours"],
        "cost_cents": row["cost_cents"],
        "cost_basis": row["cost_basis"],
        "cancelled_reason": row["cancelled_reason"],
    }
    out.update(_audit(row))
    return out


def vendor(row):
    out = {
        "vendor_name": row["vendor_name"],
        "vendor_type": row["vendor_type"],
        "country_code": row["country_code"],
        "max_concurrent_engagements": row["max_concurrent_engagements"],
        "sla_response_minutes": row["sla_response_minutes"],
        "hourly_rate_cents": row["hourly_rate_cents"],
        "retainer_cents": row["retainer_cents"],
        "activation_status": row["activation_status"],
        "committed_engagement_hours": row["committed_engagement_hours"],
        "suspension_reason": row["suspension_reason"],
    }
    out.update(_audit(row))
    return out


def vendor_engagement(row):
    out = {
        "vendor_id": row["vendor_id"],
        "trip_leg_id": row["trip_leg_id"],
        "incident_id": row["incident_id"],
        "engagement_purpose": row["engagement_purpose"],
        "starts_at": fmt_instant(row["starts_at"]),
        "ends_at": fmt_instant(row["ends_at"]),
        "status": row["status"],
        "engagement_hours": row["engagement_hours"],
        "engagement_cost_cents": row["engagement_cost_cents"],
        "cancelled_reason": row["cancelled_reason"],
    }
    out.update(_audit(row))
    return out


def incident(row):
    out = {
        "trip_id": row["trip_id"],
        "affected_leg_sequence_no": row["affected_leg_sequence_no"],
        "incident_type": row["incident_type"],
        "severity": row["severity"],
        "status": row["status"],
        "response_track": row["response_track"],
        "duress_flag": row["duress_flag"],
        "narrative": row["narrative"],
        "opened_at": fmt_instant(row["opened_at"]),
        "triaged_at": fmt_instant(row["triaged_at"]),
        "resolved_at": fmt_instant(row["resolved_at"]),
        "closed_at": fmt_instant(row["closed_at"]),
        "response_cost_cents": row["response_cost_cents"],
    }
    out.update(_audit(row))
    return out


def check_in(row):
    out = {
        "trip_id": row["trip_id"],
        "kind": row["kind"],
        "reported_at": fmt_instant(row["reported_at"]),
        "location_country_code": row["location_country_code"],
        "recorded_location_country_code": row["recorded_location_country_code"],
        "location_withheld": row["location_withheld"],
        "consent_scope_snapshot": row["consent_scope_snapshot"],
        "late": row["late"],
        "note": row["note"],
    }
    out.update(_event(row))
    return out
