"""Response shaping. Field sets follow the entity declarations exactly."""

from decimal import Decimal

import derive


def _n(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(record, versioned=True):
    out = {"created_at": record["created_at"]}
    if versioned:
        out["updated_at"] = record["updated_at"]
        out["version"] = record["version"]
    return out


def _pick(record, names):
    return dict((name, _n(record.get(name))) for name in names)


PROVIDER_FIELDS = (
    "legal_name",
    "county_code",
    "site_address",
    "program_type",
    "requested_capacity",
    "capacity_ceiling",
    "licensed_capacity",
    "suspended_capacity",
    "application_status",
    "license_status",
    "license_number",
    "licensed_at",
    "provisional_started_at",
    "open_violation_points",
    "resolved_violation_points",
    "lifetime_violation_points",
    "critical_open_count",
    "critical_violation_count_24mo",
    "substantiated_complaint_count_24mo",
    "inconclusive_complaint_count_24mo",
    "risk_score",
    "risk_tier",
    "current_ladder_step",
    "probation_cycle_count",
    "decision_reason",
)


def provider(record):
    out = {"id": record["id"]}
    out.update(_pick(record, PROVIDER_FIELDS))
    out["clearance_complete"] = derive.provider_clearance_complete(record)
    out.update(_common(record))
    return out


INSPECTOR_FIELDS = (
    "full_name",
    "county_code",
    "certified_age_groups",
    "max_daily_visits",
    "status",
    "scheduled_visit_count",
)


def inspector(record):
    out = {"id": record["id"]}
    out.update(_pick(record, INSPECTOR_FIELDS))
    out.update(_common(record))
    return out


CHECKLIST_FIELDS = (
    "code",
    "title",
    "category",
    "default_severity",
    "age_groups_applicable",
    "infant_sensitive",
)


def checklist_item(record):
    out = {"id": record["id"]}
    out.update(_pick(record, CHECKLIST_FIELDS))
    out.update(_common(record, versioned=False))
    return out


STAFF_FIELDS = (
    "provider_id",
    "full_name",
    "member_type",
    "role_title",
    "date_of_birth",
    "qualified_age_groups",
)


def staff_member(record):
    status, eligible, tier = derive.staff_clearance(record)
    out = {"id": record["id"]}
    out.update(_pick(record, STAFF_FIELDS))
    out["clearance_status"] = status
    out["supervision_eligible"] = eligible
    out["barred_offense_tier"] = tier
    out.update(_common(record))
    return out


CHECK_FIELDS = (
    "staff_member_id",
    "check_type",
    "status",
    "disqualifying_offense_tier",
    "submitted_at",
    "decided_at",
    "expires_at",
    "waiver_requested_at",
    "waiver_rationale",
    "waiver_decided_at",
)


def background_check(record):
    out = {"id": record["id"]}
    out.update(_pick(record, CHECK_FIELDS))
    out.update(_common(record))
    return out


ROSTER_FIELDS = (
    "provider_id",
    "age_group",
    "requested_group_size",
    "approved_group_size",
    "enrolled_count",
    "staff_assigned_count",
    "lead_staff_member_id",
    "required_staff_count",
    "ratio_compliant",
    "group_size_compliant",
    "supervision_compliant",
    "last_verified_at",
)


def roster(record):
    out = {"id": record["id"]}
    out.update(_pick(record, ROSTER_FIELDS))
    out.update(_common(record))
    return out


INSPECTION_FIELDS = (
    "provider_id",
    "inspector_id",
    "complaint_id",
    "inspection_type",
    "status",
    "scheduled_for",
    "duration_minutes",
    "visit_window_end",
    "started_at",
    "submitted_at",
    "finalized_at",
    "target_age_groups",
    "age_groups_observed",
    "outcome",
    "preliminary_compliance_score",
    "final_compliance_score",
    "raw_deduction_points",
    "violation_count",
    "cap_required",
    "reopen_count",
)


def inspection(record):
    out = {"id": record["id"]}
    out.update(_pick(record, INSPECTION_FIELDS))
    out.update(_common(record))
    return out


VIOLATION_FIELDS = (
    "inspection_id",
    "checklist_item_id",
    "repeat_of_violation_id",
    "primary_age_group",
    "severity_override",
    "severity",
    "repeat_chain_depth",
    "infant_exposure",
    "assessed_points",
    "status",
    "correction_due_date",
    "narrative",
    "corrected_at",
    "vacated_reason",
    "auto_generated",
)


def violation(record):
    out = {"id": record["id"]}
    out.update(_pick(record, VIOLATION_FIELDS))
    out.update(_common(record))
    return out


COMPLAINT_FIELDS = (
    "provider_id",
    "assigned_investigator_id",
    "intake_channel",
    "allegation_category",
    "alleged_serious_harm",
    "affected_age_group",
    "complainant_name",
    "anonymous",
    "narrative",
    "priority",
    "status",
    "received_at",
    "screened_at",
    "investigation_due_at",
    "determination",
    "determined_at",
    "timeliness_flag",
    "closure_note",
)


def complaint(record):
    out = {"id": record["id"]}
    out.update(_pick(record, COMPLAINT_FIELDS))
    out.update(_common(record))
    return out


CAP_FIELDS = (
    "provider_id",
    "inspection_id",
    "violation_ids",
    "narrative",
    "proposed_completion_date",
    "status",
    "review_cycle_count",
    "submitted_at",
    "reviewed_at",
    "approved_at",
    "completed_at",
    "due_at",
    "reviewed_by_user_id",
    "review_note",
    "expected_inspection_version",
)


def cap(record):
    out = {"id": record["id"]}
    out.update(_pick(record, CAP_FIELDS))
    out.update(_common(record))
    return out


ACTION_FIELDS = (
    "provider_id",
    "source_inspection_id",
    "requested_action_type",
    "action_type",
    "ladder_step",
    "status",
    "basis_points",
    "fine_amount_cents",
    "proposed_at",
    "issued_at",
    "effective_at",
    "appeal_deadline_at",
    "appealed_at",
    "appeal_note",
    "resolved_at",
    "appeal_decision",
    "issued_by_user_id",
    "capacity_held_slots",
    "rationale",
)


def action(record):
    out = {"id": record["id"]}
    out.update(_pick(record, ACTION_FIELDS))
    out.update(_common(record))
    return out


AMENDMENT_FIELDS = (
    "provider_id",
    "pre_move_inspection_id",
    "new_director_staff_member_id",
    "amendment_type",
    "requested_capacity",
    "new_site_address",
    "new_age_group",
    "new_group_size",
    "requires_inspection",
    "status",
    "submitted_at",
    "decided_at",
    "decision_rationale",
    "effective_capacity_delta",
    "expected_provider_version",
)


def amendment(record):
    out = {"id": record["id"]}
    out.update(_pick(record, AMENDMENT_FIELDS))
    out.update(_common(record))
    return out


REPORT_FIELDS = (
    "provider_id",
    "generated_complaint_id",
    "incident_type",
    "occurred_at",
    "reported_at",
    "affected_child_age_group",
    "narrative",
    "reporting_deadline_at",
    "reporting_timeliness",
    "late_report_violation_created",
    "status",
    "reviewed_at",
    "closed_at",
    "agency_note",
)


def report(record):
    out = {"id": record["id"]}
    out.update(_pick(record, REPORT_FIELDS))
    out.update(_common(record))
    return out


POSTING_FIELDS = (
    "inspection_id",
    "provider_id",
    "posting_status",
    "redaction_complete",
    "consumer_summary",
    "display_score",
    "enforcement_banner",
    "posted_at",
    "expires_at",
    "corrected_at",
    "withdrawn_at",
    "revision_note",
    "correction_count",
)


def posting(record):
    out = {"id": record["id"]}
    out.update(_pick(record, POSTING_FIELDS))
    out.update(_common(record))
    return out
