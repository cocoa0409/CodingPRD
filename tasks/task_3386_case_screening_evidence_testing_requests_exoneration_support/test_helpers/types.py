"""Domain types: entity TypedDicts, status enums, role enum.

Every entity carries the common fields id / created_at / updated_at / version
(PRD "Common Resource Properties"); TypedDicts below list the entity-specific
fields on top of those. Nullable system-stamped fields are typed Optional -
per the PRD convention, a field described as stamped or recorded by a
particular event carries null until that event has occurred.
"""
from enum import Enum
from typing import Dict, List, Optional, TypedDict


# =============================================================================
# Roles (PRD "User and Role-Based Access Control")
# =============================================================================

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    INTAKE_SPECIALIST = "IntakeSpecialist"
    MANAGING_ATTORNEY = "ManagingAttorney"
    STAFF_ATTORNEY = "StaffAttorney"
    EVIDENCE_ANALYST = "EvidenceAnalyst"
    CLIENT_SERVICES_ADVOCATE = "ClientServicesAdvocate"
    POLICY_DIRECTOR = "PolicyDirector"
    CLIENT = "Client"


# =============================================================================
# Intake / screening vocabularies
# =============================================================================

class ClaimStrength(str, Enum):
    WEAK = "WEAK"
    MODERATE = "MODERATE"
    STRONG = "STRONG"
    COMPELLING = "COMPELLING"


class EvidencePotential(str, Enum):
    NONE_KNOWN = "NONE_KNOWN"
    UNCERTAIN = "UNCERTAIN"
    LIKELY_STORED = "LIKELY_STORED"
    CONFIRMED_STORED = "CONFIRMED_STORED"


class HealthUrgency(str, Enum):
    NONE = "NONE"
    MODERATE = "MODERATE"
    CRITICAL = "CRITICAL"


class IntakeStatus(str, Enum):
    RECEIVED = "RECEIVED"
    SCREENING = "SCREENING"
    MORE_INFO_REQUESTED = "MORE_INFO_REQUESTED"
    DECISION_PENDING = "DECISION_PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WAITLISTED = "WAITLISTED"


class Recommendation(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    WAITLIST = "WAITLIST"


class IntakeDecision(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WAITLISTED = "WAITLISTED"


class IntakeAdvanceEvent(str, Enum):
    BEGIN_SCREENING = "BEGIN_SCREENING"
    REQUEST_MORE_INFO = "REQUEST_MORE_INFO"
    RECOMMEND = "RECOMMEND"


# =============================================================================
# Case vocabularies
# =============================================================================

class CaseStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATION = "INVESTIGATION"
    TESTING = "TESTING"
    LITIGATION = "LITIGATION"
    EXONERATED = "EXONERATED"
    CLOSED = "CLOSED"


class CaseResolution(str, Enum):
    UNSUBSTANTIATED = "UNSUBSTANTIATED"
    EVIDENCE_LOST = "EVIDENCE_LOST"
    CLIENT_WITHDREW = "CLIENT_WITHDREW"
    OTHER = "OTHER"


class EvidencePosture(str, Enum):
    NO_EVIDENCE = "NO_EVIDENCE"
    SEEKING = "SEEKING"
    SECURED = "SECURED"
    PARTIALLY_COMPROMISED = "PARTIALLY_COMPROMISED"
    FULLY_COMPROMISED = "FULLY_COMPROMISED"
    EXCULPATORY = "EXCULPATORY"


class ReleaseReadiness(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PLANNING = "PLANNING"
    READY = "READY"
    RELEASED = "RELEASED"


class ExpectationSetting(str, Enum):
    CAUTIOUS = "CAUTIOUS"
    NEUTRAL = "NEUTRAL"
    OPTIMISTIC = "OPTIMISTIC"


class CaseAdvanceEvent(str, Enum):
    BEGIN_INVESTIGATION = "BEGIN_INVESTIGATION"
    BEGIN_TESTING = "BEGIN_TESTING"
    BEGIN_LITIGATION = "BEGIN_LITIGATION"
    UPDATE_RELEASE_CHECKLIST = "UPDATE_RELEASE_CHECKLIST"
    EXECUTE_RELEASE = "EXECUTE_RELEASE"
    CLOSE = "CLOSE"


# =============================================================================
# Evidence / records vocabularies
# =============================================================================

class EvidenceType(str, Enum):
    BIOLOGICAL_SWAB = "BIOLOGICAL_SWAB"
    CLOTHING = "CLOTHING"
    WEAPON = "WEAPON"
    FINGERPRINT_CARD = "FINGERPRINT_CARD"
    OTHER = "OTHER"


class CustodianType(str, Enum):
    COURT_CLERK = "COURT_CLERK"
    POLICE_PROPERTY = "POLICE_PROPERTY"
    CRIME_LAB = "CRIME_LAB"
    MEDICAL_EXAMINER = "MEDICAL_EXAMINER"


class LocationStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    SEARCHING = "SEARCHING"
    LOCATED = "LOCATED"
    REPORTED_MISSING = "REPORTED_MISSING"
    REPORTED_DESTROYED = "REPORTED_DESTROYED"
    CUSTODY_CONFIRMED = "CUSTODY_CONFIRMED"
    DESTRUCTION_VERIFIED = "DESTRUCTION_VERIFIED"


class TestingStatus(str, Enum):
    UNTESTED = "UNTESTED"
    TESTING_AUTHORIZED = "TESTING_AUTHORIZED"
    SAMPLE_RESERVED = "SAMPLE_RESERVED"
    TESTED = "TESTED"
    SAMPLE_EXHAUSTED = "SAMPLE_EXHAUSTED"


class EvidenceAdvanceEvent(str, Enum):
    START_SEARCH = "START_SEARCH"
    MARK_LOCATED = "MARK_LOCATED"
    MARK_MISSING = "MARK_MISSING"
    CONFIRM_CUSTODY = "CONFIRM_CUSTODY"
    VERIFY_DESTRUCTION = "VERIFY_DESTRUCTION"


class AgencyType(str, Enum):
    COURT = "COURT"
    POLICE = "POLICE"
    LABORATORY = "LABORATORY"
    MEDICAL_EXAMINER = "MEDICAL_EXAMINER"


class RecordsRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    FULFILLED = "FULFILLED"
    PARTIALLY_FULFILLED = "PARTIALLY_FULFILLED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"


class ResponseDisposition(str, Enum):
    FULFILLED = "FULFILLED"
    PARTIALLY_FULFILLED = "PARTIALLY_FULFILLED"
    DENIED = "DENIED"


class RevealDisposition(str, Enum):
    LOCATED = "LOCATED"
    DESTROYED = "DESTROYED"
    MISSING = "MISSING"


class RecordsAdvanceEvent(str, Enum):
    SUBMIT = "SUBMIT"
    RECORD_RESPONSE = "RECORD_RESPONSE"
    APPEAL = "APPEAL"


# =============================================================================
# Testing authorization / laboratory vocabularies
# =============================================================================

class AuthorizationKind(str, Enum):
    AGREEMENT = "AGREEMENT"
    MOTION = "MOTION"


class TestingAuthorizationStatus(str, Enum):
    DRAFTED = "DRAFTED"
    PROPOSED = "PROPOSED"
    NEGOTIATING = "NEGOTIATING"
    SIGNED = "SIGNED"
    REJECTED_BY_PROSECUTION = "REJECTED_BY_PROSECUTION"
    FILED = "FILED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"


class Ruling(str, Enum):
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class AgreementEvent(str, Enum):
    PROPOSE = "PROPOSE"
    COUNTER = "COUNTER"
    SIGN = "SIGN"
    REJECT = "REJECT"


class MotionEvent(str, Enum):
    FILE = "FILE"
    RECORD_RULING = "RECORD_RULING"
    APPEAL = "APPEAL"


class LabTestType(str, Enum):
    DNA_STR = "DNA_STR"
    DNA_TOUCH = "DNA_TOUCH"
    DNA_YSTR = "DNA_YSTR"
    MITOCHONDRIAL_DNA = "MITOCHONDRIAL_DNA"
    SEROLOGY = "SEROLOGY"


class LabAnalysisStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SAMPLE_SHIPPED = "SAMPLE_SHIPPED"
    RESULT_RECORDED = "RESULT_RECORDED"
    INTERPRETED = "INTERPRETED"
    CANCELLED = "CANCELLED"


class LabOutcome(str, Enum):
    EXCLUSIONARY = "EXCLUSIONARY"
    INCLUSIONARY = "INCLUSIONARY"
    INCONCLUSIVE = "INCONCLUSIVE"
    NO_PROFILE = "NO_PROFILE"


class ExpertInterpretation(str, Enum):
    SUPPORTS_INNOCENCE = "SUPPORTS_INNOCENCE"
    NEUTRAL = "NEUTRAL"
    SUPPORTS_CONVICTION = "SUPPORTS_CONVICTION"


class DbComparisonStatus(str, Enum):
    NOT_RUN = "NOT_RUN"
    COMPLETED_HIT = "COMPLETED_HIT"
    COMPLETED_NO_HIT = "COMPLETED_NO_HIT"
    COMPLETED_PARTIAL = "COMPLETED_PARTIAL"


class ComparisonResult(str, Enum):
    HIT = "HIT"
    NO_HIT = "NO_HIT"
    PARTIAL = "PARTIAL"


class LabAdvanceEvent(str, Enum):
    SHIP_SAMPLE = "SHIP_SAMPLE"
    RECORD_RESULT = "RECORD_RESULT"
    RECORD_EXPERT_INTERPRETATION = "RECORD_EXPERT_INTERPRETATION"
    RUN_DATABASE_COMPARISON = "RUN_DATABASE_COMPARISON"
    CANCEL = "CANCEL"


# =============================================================================
# Litigation / compensation vocabularies
# =============================================================================

class PetitionType(str, Enum):
    POST_CONVICTION = "POST_CONVICTION"
    DIRECT_APPEAL = "DIRECT_APPEAL"
    CLEMENCY = "CLEMENCY"
    HABEAS_CORPUS = "HABEAS_CORPUS"


class ClaimBasis(str, Enum):
    ACTUAL_INNOCENCE = "ACTUAL_INNOCENCE"
    PROCEDURAL = "PROCEDURAL"
    BOTH = "BOTH"


class PetitionStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    DECIDED_GRANTED = "DECIDED_GRANTED"
    DECIDED_DENIED = "DECIDED_DENIED"
    APPEAL_FILED = "APPEAL_FILED"


class PetitionDecision(str, Enum):
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class PetitionAdvanceEvent(str, Enum):
    FILE = "FILE"
    RECORD_DECISION = "RECORD_DECISION"
    APPEAL = "APPEAL"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    PAID = "PAID"


class ClaimDecision(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ClaimAdvanceEvent(str, Enum):
    FILE = "FILE"
    RECORD_DECISION = "RECORD_DECISION"
    APPEAL = "APPEAL"
    RECORD_PAYMENT = "RECORD_PAYMENT"


# =============================================================================
# Reentry / policy vocabularies
# =============================================================================

class ServiceType(str, Enum):
    HOUSING = "HOUSING"
    EMPLOYMENT = "EMPLOYMENT"
    MEDICAL = "MEDICAL"
    COUNSELING = "COUNSELING"


class ReferralStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReferralAdvanceEvent(str, Enum):
    ACTIVATE = "ACTIVATE"
    COMPLETE = "COMPLETE"
    CANCEL = "CANCEL"


class PolicyTopic(str, Enum):
    EVIDENCE_PRESERVATION = "EVIDENCE_PRESERVATION"
    COMPENSATION_REFORM = "COMPENSATION_REFORM"
    DATABASE_ACCESS = "DATABASE_ACCESS"
    RECORDS_TRANSPARENCY = "RECORDS_TRANSPARENCY"


class PolicyStatus(str, Enum):
    PROPOSED = "PROPOSED"
    RESEARCHING = "RESEARCHING"
    DRAFTED = "DRAFTED"
    ADOPTED = "ADOPTED"
    STALLED = "STALLED"


class PolicyAdvanceEvent(str, Enum):
    BEGIN_RESEARCH = "BEGIN_RESEARCH"
    SUBMIT_DRAFT = "SUBMIT_DRAFT"
    ADOPT = "ADOPT"
    STALL = "STALL"
    RESUME = "RESUME"


# =============================================================================
# Entity TypedDicts (all entities carry id/created_at/updated_at/version)
# =============================================================================

class Jurisdiction(TypedDict):
    id: str
    state_code: str
    name: str
    has_post_conviction_dna_statute: bool
    post_conviction_deadline_years: Optional[int]
    clemency_available: bool
    compensation_statute_exists: bool
    compensation_cap_cents: Optional[int]
    actual_innocence_enhancement_pct: int
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    full_name: str
    inmate_number: str
    facility_name: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IntakeRequest(TypedDict):
    id: str
    client_id: str
    jurisdiction_id: str
    conviction_date: str
    conviction_summary: str
    claim_of_actual_innocence: bool
    claim_strength: str
    evidence_potential: str
    years_served: int
    health_urgency: str
    expedited_review: bool
    status: str
    screening_score_standard: Optional[float]
    screening_score_expedited: Optional[float]
    waitlist_priority_score: Optional[float]
    recommendation: Optional[str]
    recommended_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    decision: Optional[str]
    decision_reason: Optional[str]
    accepted_case_id: Optional[str]
    supplement_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict):
    id: str
    intake_request_id: str
    assigned_attorney_id: Optional[str]
    status: str
    resolution: Optional[str]
    evidence_posture: str
    destroyed_evidence_count: int
    exculpatory_evidence_flag: bool
    strategy_notes: Optional[str]
    theory_of_case: Optional[str]
    last_contact_at: str
    contact_count: int
    contact_overdue: bool
    contact_interval_days: Optional[int]
    last_expectation_setting: Optional[str]
    exoneration_date: Optional[str]
    release_housing_ready: bool
    release_id_documents_ready: bool
    release_transportation_ready: bool
    scheduled_release_date: Optional[str]
    release_readiness: str
    created_at: str
    updated_at: str
    version: int


class EvidenceItem(TypedDict):
    id: str
    case_id: str
    description: str
    evidence_type: str
    custodian_type: str
    location_status: str
    testing_status: str
    initial_sample_ng: int
    remaining_sample_ng: int
    created_at: str
    updated_at: str
    version: int


class RevealedItem(TypedDict):
    evidence_item_id: str
    disposition: str


class RecordsRequest(TypedDict):
    id: str
    case_id: str
    agency_type: str
    agency_name: str
    request_summary: str
    status: str
    response_disposition: Optional[str]
    items_revealed: List[Dict[str, str]]
    created_at: str
    updated_at: str
    version: int


class TestingAuthorization(TypedDict):
    id: str
    case_id: str
    evidence_item_id: str
    kind: str
    status: str
    terms: Optional[str]
    proposed_test_types: Optional[List[str]]
    created_by_user_id: str
    last_ruling: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LabAnalysis(TypedDict):
    id: str
    evidence_item_id: str
    authorization_id: str
    lab_name: str
    test_type: str
    required_sample_ng: int
    reserved_sample_ng: int
    actual_consumed_ng: Optional[int]
    scheduled_start: str
    scheduled_end: str
    status: str
    outcome: Optional[str]
    profile_obtained: Optional[bool]
    expert_name: Optional[str]
    expert_interpretation: Optional[str]
    db_comparison_status: str
    db_matched_subject_name: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LegalPetition(TypedDict):
    id: str
    case_id: str
    petition_type: str
    court_name: str
    claim_basis: str
    status: str
    decision_vacates_conviction: Optional[bool]
    filed_at: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CompensationClaim(TypedDict):
    id: str
    case_id: str
    years_incarcerated_claimed: int
    documented_legal_fees_cents: int
    provisional_estimate_cents: int
    final_award_cents: Optional[int]
    status: str
    paid_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ReentryProvider(TypedDict):
    id: str
    name: str
    service_type: str
    total_capacity: int
    slots_in_use: int
    created_at: str
    updated_at: str
    version: int


class ReentryReferral(TypedDict):
    id: str
    case_id: str
    provider_id: str
    service_start: str
    service_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PolicyInitiative(TypedDict):
    id: str
    jurisdiction_id: str
    topic: str
    title: str
    status: str
    pattern_case_count: int
    created_at: str
    updated_at: str
    version: int
