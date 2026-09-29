"""
TypedDict shapes for the fourteen resource families.

Thirteen families carry the full audit triple (created_at, updated_at,
version); the eligibility screen is append-only and therefore carries only
id and created_at, so its shape deliberately omits both other fields.
"""

from typing import Any, Dict, List, Optional, TypedDict


class VersionedEntity(TypedDict):
    """The audit fields carried by thirteen of the fourteen families."""

    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyEntity(TypedDict):
    """The audit fields carried by the append-only eligibility screen."""

    id: str
    created_at: str


class Representative(VersionedEntity):
    full_name: str
    accreditation_number: str
    accreditation_type: str
    accreditation_expires_on: str
    accreditation_status: str
    ce_credits_earned: int
    active_poa_count: int
    caseload_weight: float
    revocation_reason: Optional[str]


class CaseloadDecomposition(TypedDict):
    representative_id: str
    active_poa_count: int
    open_claim_count: int
    planned_outreach_count: int
    caseload_weight: float
    assignment_eligible: bool


class Veteran(VersionedEntity):
    full_name: str
    date_of_birth: str
    service_start_date: str
    service_end_date: str
    household_income_cents: int
    net_worth_cents: int
    dependent_count: int
    homeless_status: str
    referral_source: str
    county_case_number: str
    intake_status: str
    discharge_doc_status: str
    character_of_service: str
    wartime_service_days: int
    combined_rating_pct: int
    priority_group: str
    assigned_representative_id: Optional[str]
    date_of_death: Optional[str]


class DischargeDocument(VersionedEntity):
    veteran_id: str
    document_type: str
    source: str
    claimed_service_start: str
    claimed_service_end: str
    claimed_character_of_service: str
    verification_status: str
    resubmission_count: int
    discrepancy_reason: Optional[str]
    verified_at: Optional[str]
    verified_by_representative_id: Optional[str]


class CategoryResult(TypedDict):
    eligible: bool
    reason: str


class EligibilityScreen(AppendOnlyEntity):
    veteran_id: str
    screen_sequence: int
    basic_eligibility: bool
    income_limit_applied_cents: int
    wartime_service_days_at_screen: int
    priority_group_assigned: str
    category_results: Dict[str, CategoryResult]
    eligible_category_count: int


class PowerOfAttorney(VersionedEntity):
    veteran_id: str
    representative_id: str
    form_type: str
    scope: str
    executed_on: str
    status: str
    accepted_at: Optional[str]
    revoked_reason: Optional[str]


class ClaimedCondition(TypedDict):
    condition_code: str
    claimed_rating_pct: int


class Claim(VersionedEntity):
    veteran_id: str
    poa_id: Optional[str]
    claim_type: str
    claimed_conditions: List[ClaimedCondition]
    intent_to_file_date: Optional[str]
    status: str
    prepared_by_representative_id: str
    peer_reviewed_by_representative_id: Optional[str]
    rework_count: int
    reopen_count: int
    evidence_completeness_pct: float
    filed_on: Optional[str]
    effective_date_basis: Optional[str]
    effective_date: Optional[str]
    decision_outcome: Optional[str]
    awarded_rating_pct: Optional[int]
    decided_on: Optional[str]
    retro_award_cents: Optional[int]
    withdrawal_reason: Optional[str]


class EvidenceItem(VersionedEntity):
    claim_id: str
    evidence_type: str
    provider_name: str
    nexus_opinion_strength: Optional[str]
    status: str
    requested_on: str
    received_on: Optional[str]
    weight_points: float
    auto_generated: bool
    status_reason: Optional[str]


class ExamSite(VersionedEntity):
    name: str
    county_code: str
    concurrent_capacity: int
    buffer_minutes: int
    booked_slot_count: int


class ExamAppointment(VersionedEntity):
    claim_id: str
    exam_site_id: str
    starts_at: str
    ends_at: str
    status: str
    prep_session_completed: bool
    completed_on: Optional[str]
    cancellation_reason: Optional[str]


class DecisionReview(VersionedEntity):
    claim_id: str
    review_lane: str
    status: str
    counseled_by_representative_id: str
    decision_notice_date: str
    deadline_on: str
    days_remaining: int
    elected_on: Optional[str]
    filed_on: Optional[str]
    closure_reason: Optional[str]


class SweepResult(TypedDict):
    expired_count: int
    expired_review_ids: List[str]


class StateProgram(VersionedEntity):
    program_code: str
    program_name: str
    program_type: str
    fiscal_year: int
    annual_pool_cents: int
    min_rating_pct: int
    requires_wartime: bool
    max_award_cents: int
    allocated_cents: int


class StateBenefitApplication(VersionedEntity):
    veteran_id: str
    program_id: str
    fiscal_year: int
    assessed_property_value_cents: Optional[int]
    tuition_credits_requested: Optional[int]
    determination_status: str
    disbursement_status: str
    gross_award_cents: int
    admin_fee_cents: int
    benefit_amount_cents: int
    rating_at_approval_pct: Optional[int]
    determination_reason: Optional[str]
    issued_on: Optional[str]


class OutreachEvent(VersionedEntity):
    assigned_representative_id: str
    event_type: str
    location_name: str
    starts_at: str
    ends_at: str
    underserved_flag: bool
    status: str
    veterans_contacted: int
    veterans_enrolled: int
    cancellation_reason: Optional[str]


class OutcomeReport(VersionedEntity):
    fiscal_quarter: str
    status: str
    weighting_basis: Optional[str]
    filed_claim_count: int
    favorable_claim_count: int
    performance_score: float
    retro_dollars_cents: int
    veterans_contacted_total: int
    submitted_at: Optional[str]
    certified_by_representative_id: Optional[str]
    return_reason: Optional[str]


class ClockValue(TypedDict):
    current_utc: str


AnyEntity = Dict[str, Any]

__all__ = [
    "VersionedEntity",
    "AppendOnlyEntity",
    "Representative",
    "CaseloadDecomposition",
    "Veteran",
    "DischargeDocument",
    "CategoryResult",
    "EligibilityScreen",
    "PowerOfAttorney",
    "ClaimedCondition",
    "Claim",
    "EvidenceItem",
    "ExamSite",
    "ExamAppointment",
    "DecisionReview",
    "SweepResult",
    "StateProgram",
    "StateBenefitApplication",
    "OutreachEvent",
    "OutcomeReport",
    "ClockValue",
    "AnyEntity",
]
