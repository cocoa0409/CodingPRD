"""TypedDict shapes for every persisted resource (PRD S2.4, S3).

These exist to document the field names and JSON types the tests read back, so
a test that misspells a field is caught by review rather than by a KeyError.
``Agency`` deliberately carries no ``updated_at`` and no ``version``: PRD S2.4
records it as "the single exception ... it carries only id and created_at".
"""

from typing import Any, Dict, List, Optional, TypedDict


class Desk(TypedDict):
    """PRD S3.1 -- the investigations desk and its four-column fee ledger."""

    id: str
    name: str
    fee_budget_total_cents: int
    fee_budget_available_cents: int
    fee_budget_committed_cents: int
    fee_budget_spent_cents: int
    retention_policy_days: int
    open_request_count: int
    open_appeal_count: int
    litigation_exposure_count: int
    source_exposure_incident_count: int
    security_posture: str
    created_at: str
    updated_at: str
    version: int


class Agency(TypedDict):
    """PRD S3.1 -- an immutable statutory reference row (no version)."""

    id: str
    name: str
    jurisdiction_code: str
    statute_name: str
    initial_response_days: int
    deadline_basis: str
    tolling_allowed: bool
    appeal_venue: str
    appeal_decision_days: int
    search_fee_cents_per_hour: int
    page_fee_cents: int
    max_waiver_cents: int
    holiday_dates: List[str]
    created_at: str


class RecordsRequest(TypedDict):
    """PRD S3.2, S3.3, S3.4 -- the request, both deadline variants, its fee."""

    id: str
    desk_id: str
    agency_id: str
    supersedes_request_id: Optional[str]
    subject_summary: str
    requested_format: str
    estimated_page_count: int
    waiver_requested: bool
    public_interest_score: int
    status: str
    requester_user_id: str
    submitted_at: Optional[str]
    due_at_strict: Optional[str]
    due_at_tolled: Optional[str]
    tolled_days_total: int
    clarification_round_count: int
    clarification_opened_at: Optional[str]
    search_hours: Optional[float]
    billed_page_count: Optional[int]
    search_fee_cents: Optional[int]
    duplication_fee_cents: Optional[int]
    gross_fee_cents: Optional[int]
    waiver_pct: Optional[float]
    waiver_amount_cents: Optional[int]
    net_fee_cents: Optional[int]
    fee_committed_cents: int
    fee_determined_at: Optional[str]
    denial_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    """PRD S3.5 -- an administrative appeal and its filing fee."""

    id: str
    request_id: str
    venue: str
    grounds: str
    filing_fee_cents: int
    status: str
    ripeness_basis: str
    filed_by_user_id: str
    filed_at: str
    decision_due_at: str
    decision_rationale: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dataset(TypedDict):
    """PRD S3.6 -- acquired data through delivery, cleaning and quarantine."""

    id: str
    request_id: str
    investigation_id: Optional[str]
    name: str
    negotiated_format: str
    delivered_format: Optional[str]
    expected_field_count: int
    sensitivity_tier: str
    status: str
    format_negotiation_status: str
    documentation_status: str
    record_count: int
    field_definition_count: int
    known_issue_count: int
    allocated_cost_cents: int
    retention_expires_at: Optional[str]
    quarantine_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FieldDefinition(TypedDict):
    """PRD S3.6 -- one documented column of a dataset."""

    id: str
    dataset_id: str
    field_name: str
    data_type: str
    null_rate_pct: float
    reidentification_risk: int
    is_source_identifying: bool
    known_issue_codes: List[str]
    suppression_applied: bool
    suppression_method: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Investigation(TypedDict):
    """PRD S3.7, S3.9 -- the editorial container and the publication gate."""

    id: str
    desk_id: str
    headline: str
    publication_mode: str
    status: str
    analysis_readiness: str
    finding_count: int
    unverified_finding_count: int
    doc_matched_finding_count: int
    sme_confirmed_finding_count: int
    sme_disputed_finding_count: int
    release_dataset_id: Optional[str]
    methodology_doc_ref: Optional[str]
    disclosure_risk_score: Optional[int]
    applicable_risk_variant: Optional[str]
    hold_reason_code: Optional[str]
    legal_clearance_at: Optional[str]
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AnalysisRun(TypedDict):
    """PRD S3.7 -- a reproducible run with two independent status dimensions."""

    id: str
    investigation_id: str
    code_repo_ref: str
    code_commit_sha: str
    container_digest: str
    compute_cost_cents: int
    labor_hours: float
    run_sequence: int
    code_review_status: str
    cost_allocation_status: str
    review_cycle_count: int
    labor_cost_cents: Optional[int]
    total_cost_cents: Optional[int]
    allocated_total_cents: int
    authored_by_user_id: str
    reviewed_by_user_id: Optional[str]
    peer_review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Finding(TypedDict):
    """PRD S3.8 -- a publishable claim and its verification status."""

    id: str
    investigation_id: str
    analysis_run_id: str
    claim_text: str
    verification_status: str
    source_document_ref: Optional[str]
    matched_page: Optional[int]
    sme_verdict_rationale: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExpertReviewer(TypedDict):
    """PRD S3.8 -- the outside expert whose id is their X-User-ID."""

    id: str
    name: str
    affiliation: str
    expertise_code: str
    max_concurrent_assignments: int
    conflict_of_interest_agency_ids: List[str]
    active_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class ReviewAssignment(TypedDict):
    """PRD S3.8 -- the reviewer/finding junction with its committed window."""

    id: str
    reviewer_id: str
    finding_id: str
    window_start: str
    window_end: str
    status: str
    verdict: Optional[str]
    rationale: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DocumentedAttempt(TypedDict):
    """PRD S3.9 -- one element of the append-only documented_attempts log."""

    channel: str
    contact_detail: Optional[str]
    deliverable: bool
    note: str
    attempted_at: str


class SubjectResponseRequest(TypedDict):
    """PRD S3.9 -- the right-of-reply record and its 72-hour notice clock."""

    id: str
    investigation_id: str
    subject_name: str
    contact_channel: str
    status: str
    attempt_count: int
    documented_attempts: List[DocumentedAttempt]
    notice_sent_at: Optional[str]
    response_deadline_at: Optional[str]
    response_text: Optional[str]
    on_the_record: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class SecureEnclave(TypedDict):
    """PRD S3.9 -- the controlled reading room and its sanitization buffer."""

    id: str
    name: str
    max_documents: int
    sanitization_buffer_minutes: int
    booked_session_count: int
    created_at: str
    updated_at: str
    version: int


class EnclaveSession(TypedDict):
    """PRD S3.9 -- a half-open supervised reading session."""

    id: str
    enclave_id: str
    dataset_id: str
    start_at: str
    end_at: str
    document_count: int
    purpose: str
    status: str
    opened_by_user_id: str
    documents_returned_count: Optional[int]
    cancellation_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisclosureRiskPreview(TypedDict):
    """PRD S3.9 -- the read-only rehearsal of the publication gate ladder."""

    aggregate_max_score: int
    composite_weighted_score: int
    applicable_variant: str
    applicable_score: int
    notice_window_hours: float
    blocking_reason_code: str


# A JSON request body: the tests build these as plain dicts.
Payload = Dict[str, Any]
