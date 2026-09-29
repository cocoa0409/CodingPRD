"""Declared field inventories for every entity and envelope in the contract.

The tuples below are used to assert that a response body carries exactly the
declared attributes, in addition to the common system fields.
"""

from typing import Any, Dict, List

Json = Dict[str, Any]
JsonList = List[Json]

# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

SUCCESS_ENVELOPE_KEYS = ("meta", "response_type", "data")
ERROR_ENVELOPE_KEYS = ("meta", "response_type", "data")

META_ALWAYS_KEYS = ("api_request_id", "api_request_timestamp")
META_PAGINATION_KEYS = ("limit", "offset", "total_count", "has_more")

ERROR_DATA_KEYS = ("error_id", "message")

RESPONSE_TYPE_OBJECT = "object"
RESPONSE_TYPE_ARRAY = "array"
RESPONSE_TYPE_ERROR = "error"

API_REQUEST_ID_PREFIX = "req_"

# ---------------------------------------------------------------------------
# Entities carrying id, created_at, updated_at and version
# ---------------------------------------------------------------------------

TERMINAL_FIELDS = (
    "name",
    "terminal_code",
    "region_code",
    "annual_miles_millions",
    "active_driver_count",
    "suspended_driver_count",
    "preventable_crash_count",
    "crash_rate_per_million_miles",
    "risk_tier",
    "staffing_posture",
    "late_filing_count",
)

DRIVER_FIELDS = (
    "terminal_id",
    "employee_code",
    "full_name",
    "cdl_number",
    "hire_date",
    "status",
    "tenure_band",
    "preventable_points",
    "required_action_tier",
    "continued_employment_decision",
    "decision_note",
)

CRASH_FIELDS = (
    "driver_id",
    "terminal_id",
    "occurred_at",
    "notified_at",
    "location_text",
    "severity",
    "route_class",
    "tow_away",
    "tow_reason",
    "injury_transported_count",
    "fatality_count",
    "hazmat_release",
    "mechanical_factor",
    "third_party_at_fault",
    "dot_recordable",
    "recordability_codes",
    "report_due_at",
    "reporting_status",
    "filing_reference",
    "filed_at",
    "preventability_status",
    "appeals_exhausted",
    "evidence_posture",
)

EVIDENCE_ITEM_FIELDS = (
    "crash_id",
    "kind",
    "source_device_id",
    "window_start_at",
    "window_end_at",
    "retention_deadline_at",
    "preservation_state",
    "evidence_hash",
    "preserved_copy_uri",
    "preserved_at",
    "purge_reason",
)

REVIEW_CASE_FIELDS = (
    "crash_id",
    "committee_name",
    "statement_waiver_reason",
    "status",
    "determination",
    "decision_basis",
    "committee_score",
    "active_vote_count",
    "abstain_count",
    "next_vote_sequence",
    "appeal_round",
    "appeal_grounds",
    "appeal_grounds_code",
    "appeal_evidence_item_id",
    "decided_by_user_id",
    "decided_at",
)

CLAIM_FIELDS = (
    "crash_id",
    "claimant_notice_date",
    "adjuster_note",
    "handling_status",
    "reserve_status",
    "litigation_risk_score",
    "litigation_risk_multiplier",
    "counsel_required",
    "counsel_assigned",
    "counsel_firm_name",
    "counsel_type",
    "counsel_assigned_at",
    "litigation_flag",
    "closed_at",
    "provisional_reserve_cents",
    "revised_reserve_cents",
    "outstanding_reserve_cents",
    "indemnity_paid_cents",
    "alae_paid_cents",
    "reserve_released_cents",
    "subrogation_recovered_cents",
    "sir_eroded_cents",
    "insured_paid_cents",
    "layer_allocations",
    "total_incurred_cents",
    "claim_exposure_cents",
)

DEMAND_FIELDS = (
    "claim_id",
    "claimant_name",
    "claimant_type",
    "demand_amount_cents",
    "represented_by_counsel",
    "demand_received_at",
    "status",
    "next_round_index",
    "round_count",
    "settled_amount_cents",
    "alae_cents",
    "settlement_total_cents",
    "settled_at",
    "settlement_reference",
    "rescission_count",
)

DISCIPLINARY_ACTION_FIELDS = (
    "driver_id",
    "crash_id",
    "action_type",
    "action_note",
    "suspension_start_at",
    "suspension_end_at",
    "retraining_course_code",
    "retraining_status",
    "status",
    "override_reason",
    "override_flag",
    "issued_by_user_id",
    "completed_at",
)

SUBROGATION_DEMAND_FIELDS = (
    "claim_id",
    "third_party_name",
    "at_fault_percentage",
    "basis_note",
    "status",
    "recoverable_base_cents",
    "max_recoverable_cents",
    "recovered_amount_cents",
    "resolution_note",
    "resolved_at",
)

# ---------------------------------------------------------------------------
# Append-only rows carrying only id and created_at
# ---------------------------------------------------------------------------

DRIVER_STATEMENT_FIELDS = (
    "crash_id",
    "narrative",
    "conditions_note",
    "attested",
    "submitted_by_driver_id",
    "submitted_at",
)

COMMITTEE_VOTE_FIELDS = (
    "review_case_id",
    "member_user_id",
    "sequence_number",
    "vote",
    "criterion_scores",
    "weighted_member_score",
    "superseded",
    "comment",
    "cast_at",
)

POLICY_LAYER_FIELDS = (
    "program_year",
    "layer_index",
    "layer_type",
    "attachment_point_cents",
    "limit_cents",
    "insurer_name",
)

NEGOTIATION_ROUND_FIELDS = (
    "demand_id",
    "round_index",
    "carrier_offer_cents",
    "claimant_counter_cents",
    "gap_cents",
    "outcome",
    "offered_by_user_id",
    "offered_at",
    "countered_at",
)

# ---------------------------------------------------------------------------
# Analytics projection
# ---------------------------------------------------------------------------

CRASH_ANALYTICS_FIELDS = (
    "terminal_id",
    "basis",
    "window_start_at",
    "window_end_at",
    "crash_count",
    "preventable_crash_count",
    "crash_rate_per_million_miles",
    "risk_tier",
)

BREAKDOWN_ENTRY_FIELDS = (
    "crash_count",
    "preventable_crash_count",
    "crash_rate_per_million_miles",
)

# Entities that carry an optimistic-concurrency version counter.
VERSIONED_ENTITY_FIELDS = {
    "Terminal": TERMINAL_FIELDS,
    "Driver": DRIVER_FIELDS,
    "Crash": CRASH_FIELDS,
    "EvidenceItem": EVIDENCE_ITEM_FIELDS,
    "ReviewCase": REVIEW_CASE_FIELDS,
    "Claim": CLAIM_FIELDS,
    "Demand": DEMAND_FIELDS,
    "DisciplinaryAction": DISCIPLINARY_ACTION_FIELDS,
    "SubrogationDemand": SUBROGATION_DEMAND_FIELDS,
}

# Append-only rows without a version counter.
APPEND_ONLY_ENTITY_FIELDS = {
    "DriverStatement": DRIVER_STATEMENT_FIELDS,
    "CommitteeVote": COMMITTEE_VOTE_FIELDS,
    "PolicyLayer": POLICY_LAYER_FIELDS,
    "NegotiationRound": NEGOTIATION_ROUND_FIELDS,
}
