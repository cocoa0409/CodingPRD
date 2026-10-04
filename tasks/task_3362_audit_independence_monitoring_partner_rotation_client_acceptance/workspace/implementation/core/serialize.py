"""Entity rendering: internal rows to the declared response shapes."""

from datetime import datetime
from decimal import Decimal

from .utils import format_instant

CLIENT_FIELDS = (
    "id", "created_at", "updated_at", "version",
    "legal_name", "industry_code", "jurisdiction_country",
    "is_public_interest_entity", "parent_client_id", "status",
    "naf_annual_cap_cents", "naf_approved_fee_cents",
    "aggregate_independence_status", "open_finding_count",
)

ENGAGEMENT_FIELDS = (
    "id", "created_at", "updated_at", "version",
    "client_id", "engagement_type", "fiscal_year_end", "is_multinational",
    "status", "independence_status", "risk_tier", "combined_risk_score",
    "assigned_workload_points", "lead_partner_id", "concurring_partner_id",
    "quality_review_required",
)

ACCEPTANCE_FIELDS = (
    "id", "created_at", "updated_at", "version",
    "client_id", "engagement_id", "proposed_by", "industry_expertise_required",
    "industry_expertise_confirmed", "integrity_score", "risk_score",
    "combined_risk_score", "status", "decision_notes", "decided_at",
)

ASSESSMENT_FIELDS = (
    "id", "created_at", "updated_at", "version",
    "acceptance_id", "source_type", "severity", "score_impact",
    "assessed_on", "resolved",
)

PROFESSIONAL_FIELDS = (
    "id", "created_at", "updated_at", "version",
    "full_name", "grade", "home_affiliate_id", "rotation_role_class",
    "availability", "max_workload_points", "active_workload_points",
    "rotation_exposure_months",
)

ASSIGNMENT_FIELDS = (
    "id", "created_at", "updated_at", "version",
    "engagement_id", "professional_id", "role", "started_on",
    "scheduled_end_on", "ended_on", "status", "consecutive_service_months",
    "time_off_months_required", "eligible_return_on", "rotation_status",
    "workload_points",
)

FINDING_FIELDS = (
    "id", "created_at", "updated_at", "version",
    "professional_id", "engagement_id", "origin", "origin_ref_id",
    "finding_type", "severity", "status", "discovered_on",
    "remediation_due_on", "closed_on", "remediation_attempts",
)

THREAT_FIELDS = (
    "id", "created_at", "updated_at", "version",
    "professional_id", "client_id", "threat_type", "instrument_type",
    "relationship_type", "value_cents", "effective_on", "is_material",
    "cooling_off_end_on", "status", "cleared_on",
)

SERVICE_FIELDS = (
    "id", "created_at", "updated_at", "version",
    "client_id", "engagement_id", "service_category", "fee_cents",
    "is_prohibited_for_pie", "committee_resolution_ref", "approval_expires_on",
    "approved_fee_cents", "approved_on", "status",
)

AFFILIATE_FIELDS = (
    "id", "created_at", "updated_at", "version",
    "firm_name", "country_code", "network_tier", "independence_framework",
    "status", "open_breach_count",
)

ATTESTATION_FIELDS = (
    "id", "created_at", "updated_at", "version",
    "affiliate_id", "engagement_id", "attestation_status", "attested_on",
    "breach_count",
)

REVIEW_FIELDS = (
    "id", "created_at", "updated_at", "version",
    "engagement_id", "reviewer_id", "review_type", "inspection_body",
    "received_on", "due_on", "response_due_on", "deficiency_count",
    "remediation_plan_ref", "status",
)

FIELDS_BY_ENTITY = {
    "client": CLIENT_FIELDS,
    "engagement": ENGAGEMENT_FIELDS,
    "acceptance": ACCEPTANCE_FIELDS,
    "assessment": ASSESSMENT_FIELDS,
    "professional": PROFESSIONAL_FIELDS,
    "assignment": ASSIGNMENT_FIELDS,
    "finding": FINDING_FIELDS,
    "threat": THREAT_FIELDS,
    "service": SERVICE_FIELDS,
    "affiliate": AFFILIATE_FIELDS,
    "attestation": ATTESTATION_FIELDS,
    "review": REVIEW_FIELDS,
}


def _render(value):
    if isinstance(value, datetime):
        return format_instant(value)
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    return value


def serialize(entity, row):
    return {name: _render(row.get(name)) for name in FIELDS_BY_ENTITY[entity]}


def serialize_many(entity, rows):
    return [serialize(entity, row) for row in rows]
