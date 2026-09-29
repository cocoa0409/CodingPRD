"""Resource serializers: one explicit field list per entity (PRD 2.4)."""
import store

COMMON = ("id", "created_at", "updated_at", "version")
IMMUTABLE_COMMON = ("id", "created_at")

PROVIDER_FIELDS = (
    "legal_name", "provider_type", "rmd_filing_status", "auth_posture",
    "active_certificate_id", "penalty_points", "overdue_traceback_count",
    "open_notice_count", "active_assigned_number_count",
    "outstanding_forfeiture_cents", "blocking_false_positive_rate",
    "sweep_index",
) + COMMON

CERTIFICATE_FIELDS = (
    "provider_id", "spc_token", "public_key_fingerprint", "not_before",
    "not_after", "status", "issued_at", "activated_at", "revoked_at",
    "revocation_reason", "predecessor_certificate_id", "renewal_generation",
) + COMMON

PLAN_FIELDS = (
    "provider_id", "prevention_practices", "filing_state", "filed_by_user_id",
    "submitted_at", "decided_at", "deficiency_reasons", "deficiency_count",
    "revision_count",
) + COMMON

CUSTOMER_FIELDS = (
    "provider_id", "legal_name", "contact_email", "kyc_evidence_level",
    "kyc_state", "origination_state", "kyc_submitted_by_user_id",
    "kyc_decided_by_user_id", "kyc_decided_at", "traffic_risk_index",
    "risk_tier", "observation_count", "false_positive_count",
    "suspension_cause", "suspension_source_id",
) + COMMON

ASSIGNMENT_FIELDS = (
    "provider_id", "customer_id", "telephone_number", "ownership_evidence",
    "effective_from", "effective_to", "status", "revoked_at",
) + COMMON

ATTESTATION_FIELDS = (
    "provider_id", "customer_id", "certificate_id", "calling_number",
    "called_number", "origination_time", "attestation_level",
    "attestation_reason_code", "ownership_verified", "risk_tier_at_signing",
    "passport_identity_token",
) + IMMUTABLE_COMMON

OBSERVATION_FIELDS = (
    "provider_id", "customer_id", "window_start", "window_end",
    "total_call_count", "short_duration_call_count", "unanswered_call_count",
    "complaint_count", "window_subscore", "recorded_by_user_id",
    "resulting_risk_index", "triggered_suspension",
) + IMMUTABLE_COMMON

TRACEBACK_FIELDS = (
    "provider_id", "calling_number", "called_number", "origination_time",
    "received_at", "response_deadline_at", "hard_cutoff_at", "state",
    "responded_at", "identified_customer_id", "produced_attestation_id",
    "upstream_provider_note", "lateness_seconds", "call_detail_complete",
) + COMMON

NOTICE_FIELDS = (
    "provider_id", "calling_number", "description", "notified_at",
    "mitigation_deadline_at", "state", "customer_id", "mitigation_action",
    "resolved_at", "penalty_points_assessed",
) + COMMON

BLOCKING_EVENT_FIELDS = (
    "provider_id", "customer_id", "calling_number", "analytics_score",
    "reason", "status", "blocked_at", "blocked_by_user_id", "reversed_at",
    "triggered_suspension",
) + COMMON

DISPUTE_FIELDS = (
    "blocking_event_id", "customer_id", "claim_note", "filed_at",
    "resolution_deadline_at", "state", "resolution_note", "resolved_at",
    "resolved_by_user_id", "resolved_late",
) + COMMON

ENFORCEMENT_FIELDS = (
    "provider_id", "basis", "violation_count", "violation_days",
    "assessment_basis", "base_assessment_cents", "base_capped_cents",
    "assessment_tier", "score_band", "mitigation_credit_cents",
    "total_forfeiture_cents", "status", "contested_at", "adjudicated_at",
    "paid_at", "paid_amount_cents",
) + COMMON

REPORT_FIELDS = (
    "provider_id", "period_start", "period_end", "variant",
    "signed_call_count", "attestation_a_count", "traceback_total_count",
    "traceback_on_time_count", "traceback_pending_count",
    "notice_total_count", "notice_mitigated_count", "notice_open_count",
    "attestation_component", "traceback_component", "notice_component",
    "effectiveness_score", "score_band", "data_sufficiency", "state",
    "signed_off_by_user_id", "signed_off_at", "filed_at",
) + COMMON


def _make(fields):
    def serializer(row):
        return store.serialize(row, fields)
    return serializer


provider = _make(PROVIDER_FIELDS)
certificate = _make(CERTIFICATE_FIELDS)
plan = _make(PLAN_FIELDS)
customer = _make(CUSTOMER_FIELDS)
assignment = _make(ASSIGNMENT_FIELDS)
attestation = _make(ATTESTATION_FIELDS)
observation = _make(OBSERVATION_FIELDS)
traceback = _make(TRACEBACK_FIELDS)
notice = _make(NOTICE_FIELDS)
blocking_event = _make(BLOCKING_EVENT_FIELDS)
dispute = _make(DISPUTE_FIELDS)
enforcement = _make(ENFORCEMENT_FIELDS)
report = _make(REPORT_FIELDS)
