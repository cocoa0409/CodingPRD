"""Entity -> JSON projection. Internal bookkeeping keys never leak."""
from decimal import Decimal

FIELDS = {
    "policy_cycle": [
        "id", "cycle_label", "effective_from", "effective_to", "posture",
        "days_in_office_floor", "badge_weight", "network_weight",
        "collaboration_target_score", "equity_variance_threshold_pct",
        "enrolled_team_count", "aggregate_compliance_rate", "formal_action_total",
        "created_at", "updated_at", "version",
    ],
    "team": [
        "id", "policy_cycle_id", "team_code", "expected_days_in_office_per_week",
        "core_collaboration_days", "headcount_planned", "signal_corroboration_required",
        "expected_daily_attendance", "base_entitlement", "buffer_seats_entitled",
        "entitled_seats", "escalated_headcount", "formal_action_count",
        "created_at", "updated_at", "version",
    ],
    "employee": [
        "id", "team_id", "employee_number", "work_email", "home_timezone",
        "tenure_start_date", "demographic_band", "manager_user_id", "hr_partner_user_id",
        "disability_accommodation_on_file", "status", "current_eligibility_class",
        "cumulative_shortfall_days", "consecutive_breach_weeks",
        "approved_relief_days_total", "non_compliance_pressure", "compliance_state",
        "escalation_stage", "created_at", "updated_at", "version",
    ],
    "eligibility_classification": [
        "id", "employee_id", "supersedes_classification_id", "requested_class",
        "justification_code", "effective_from", "state", "created_by_user_id",
        "decided_by_user_id", "decision_note", "created_at", "updated_at", "version",
    ],
    "attendance_week": [
        "id", "employee_id", "iso_week", "week_start_date", "status", "required_days",
        "variant_applied", "credited_days", "relief_days_credited", "shortfall_days",
        "amendment_reason", "finalized_at", "created_at", "updated_at", "version",
    ],
    "compliance_signal": [
        "id", "attendance_week_id", "signal_source", "site_code", "observed_date",
        "minutes_present", "dedupe_key", "created_at",
    ],
    "exception_request": [
        "id", "employee_id", "category", "requested_relief_days", "start_date",
        "end_date", "rationale", "status", "interactive_process_required",
        "granted_relief_days", "info_needed", "response_note", "info_round_count",
        "adjudicated_by_user_id", "closure_reason", "created_at", "updated_at", "version",
    ],
    "remote_location_request": [
        "id", "employee_id", "jurisdiction_code", "data_classification_tier",
        "proposed_start_date", "status", "tax_review_status", "security_review_status",
        "licensing_gap_count", "tax_nexus_registration_cost_cents", "control_gap_count",
        "preliminary_risk_score", "final_risk_score", "decision_reason",
        "created_at", "updated_at", "version",
    ],
    "neighborhood": [
        "id", "policy_cycle_id", "anchor_team_id", "neighborhood_code", "site_code",
        "seat_count", "buffer_seats", "desk_index_from", "desk_index_to",
        "committed_seats", "peak_committed_seats", "utilization_pct", "allocation_state",
        "created_at", "updated_at", "version",
    ],
    "seat_allocation": [
        "id", "neighborhood_id", "team_id", "allocated_seats", "window_start_week",
        "window_end_week", "status", "weeks_in_window", "line_chargeback_cents",
        "release_reason", "created_at", "updated_at", "version",
    ],
    "desk_assignment": [
        "id", "seat_allocation_id", "employee_id", "desk_index", "start_date",
        "end_date", "status", "assignment_mode", "vacated_at",
        "created_at", "updated_at", "version",
    ],
    "escalation_case": [
        "id", "employee_id", "prior_case_id", "stage", "opened_pressure",
        "discretionary_hold", "last_action_by_user_id", "action_note",
        "created_at", "updated_at", "version",
    ],
    "recalibration_review": [
        "id", "policy_cycle_id", "review_label", "proposed_days_in_office_delta",
        "state", "submitted_by_user_id", "decided_by_user_id", "collaboration_index",
        "meets_collaboration_target", "total_space_chargeback_cents",
        "equity_variance_pct", "equity_flag", "qualifying_band_count",
        "decision_reason", "created_at", "updated_at", "version",
    ],
}


def _plain(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def dump(kind, row):
    return {key: _plain(row.get(key)) for key in FIELDS[kind]}


def dump_all(kind, rows):
    return [dump(kind, row) for row in rows]
