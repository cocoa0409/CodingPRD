"""Response shapes for the resources declared in the PRD.

These are documentation-grade TypedDicts: they name the fields each resource
publishes so tests read clearly.  Three resource kinds are write-once event
records and deliberately carry only ``id`` and ``created_at`` — they have no
``updated_at`` and no ``version``.
"""

from typing import Any, Dict, List, Optional, TypedDict


class Envelope(TypedDict):
    data: Any
    meta: Dict[str, Any]


class RegistrationSite(TypedDict, total=False):
    id: str
    site_code: str
    name: str
    region_code: str
    registrar_headcount: int
    status: str
    active_record_count: int
    flagged_record_count: int
    created_at: str
    updated_at: str
    version: int


class MatchRuleSet(TypedDict, total=False):
    id: str
    name: str
    version_label: str
    attribute_weights: Dict[str, float]
    auto_link_threshold: float
    review_threshold: float
    conflict_penalty_points: float
    status: str
    created_at: str
    updated_at: str
    version: int


class RegistrationSearchAttempt(TypedDict, total=False):
    """Write-once event record: only ``id`` and ``created_at`` besides payload."""

    id: str
    site_id: str
    searched_last_name: str
    searched_first_name: Optional[str]
    searched_dob: Optional[str]
    searched_sex: Optional[str]
    searched_ssn_last4: Optional[str]
    searched_postal_code: Optional[str]
    searched_phone: Optional[str]
    result_count: int
    top_score: float
    top_match_record_mrn: Optional[str]
    blocked_creation: bool
    rule_set_version_label: Optional[str]
    created_at: str


class PatientRecord(TypedDict, total=False):
    id: str
    site_id: str
    mrn: str
    enterprise_id: str
    last_name: str
    first_name: str
    dob: str
    sex: str
    ssn_last4: Optional[str]
    address_line: Optional[str]
    postal_code: Optional[str]
    phone: Optional[str]
    biometric_template_hash: Optional[str]
    insurance_member_id: Optional[str]
    clinical_element_count: int
    identity_state: str
    integrity_state: str
    survivor_record_id: Optional[str]
    subsumed_member_count: int
    origin_search_attempt_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CandidatePair(TypedDict, total=False):
    id: str
    record_a_id: str
    record_b_id: str
    rule_set_id: str
    score_variant: str
    raw_score: float
    match_score: float
    attribute_score_breakdown: Dict[str, float]
    conflict_flags: List[str]
    classification: str
    queue_state: str
    base_band: str
    priority_band: str
    evidence_points: float
    evidence_adjustment: float
    effective_score: float
    subject_record_mrn: str
    detected_at_site_id: str
    triage_note: Optional[str]
    recommendation: Optional[str]
    recommended_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReviewEvidence(TypedDict, total=False):
    """Write-once event record: only ``id`` and ``created_at``."""

    id: str
    pair_id: str
    evidence_type: str
    outcome: str
    weight_points: float
    note: Optional[str]
    submitted_by_user_id: str
    created_at: str


class MergeOperation(TypedDict, total=False):
    id: str
    pair_id: str
    survivor_record_id: str
    subsumed_record_id: str
    rationale: str
    state: str
    moved_clinical_element_count: int
    subsumed_prior_enterprise_id: str
    recompressed_record_mrns: List[str]
    propagation_task_count: int
    approved_by_user_id: str
    completed_at: Optional[str]
    reversal_deadline_at: Optional[str]
    unmerge_reason: Optional[str]
    unmerged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DownstreamSystem(TypedDict, total=False):
    id: str
    system_code: str
    name: str
    propagation_mode: str
    ack_required: bool
    max_concurrent_dispatch: int
    status: str
    unacked_task_count: int
    created_at: str
    updated_at: str
    version: int


class PropagationTask(TypedDict, total=False):
    id: str
    downstream_system_id: str
    operation_kind: str
    merge_operation_id: Optional[str]
    overlay_correction_id: Optional[str]
    state: str
    attempt_count: int
    dispatch_window_start_at: Optional[str]
    dispatch_window_end_at: Optional[str]
    propagation_deadline_at: str
    last_error_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OverlayCorrection(TypedDict, total=False):
    id: str
    record_id: str
    overlay_type: str
    state: str
    corrected_field_snapshot: Dict[str, Any]
    prior_field_snapshot: Dict[str, Any]
    affected_clinical_element_count: int
    encounter_from_date: str
    encounter_to_date: str
    closure_note: Optional[str]
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class ContaminationRemediation(TypedDict, total=False):
    id: str
    record_id: str
    source_type: str
    merge_operation_id: Optional[str]
    overlay_correction_id: Optional[str]
    state: str
    element_count_subject: int
    element_count_quarantined: int
    element_count_reassigned: int
    reassigned_to_record_mrn: Optional[str]
    closure_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FraudInvestigation(TypedDict, total=False):
    id: str
    record_id: str
    pair_id: Optional[str]
    trigger_kind: str
    opened_by: str
    opened_by_user_id: Optional[str]
    risk_score: float
    state: str
    note: Optional[str]
    finding_note: Optional[str]
    referral_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExternalMatchRequest(TypedDict, total=False):
    id: str
    record_id: str
    exchange_partner_code: str
    consent_on_file: bool
    external_demographics: Dict[str, Any]
    external_score: float
    state: str
    rule_set_id: str
    created_at: str
    updated_at: str
    version: int


class SiteDuplicateMetric(TypedDict, total=False):
    """Write-once event record: only ``id`` and ``created_at``."""

    id: str
    site_id: str
    window_start_date: str
    window_end_date: str
    attribution_variant: str
    records_created: int
    confirmed_duplicates: int
    duplicate_rate_bps: int
    sample_size_sufficient: bool
    rule_set_version_label: Optional[str]
    created_at: str
