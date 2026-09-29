"""Domain types for the Ballot Measure Petition Signature Verification API.

Status enums, role enum and entity TypedDicts. Resources that carry the full
set of system-managed properties list ``id``, ``created_at``, ``updated_at``
and ``version``; the three configuration resources carry only ``id`` and
``created_at`` because neither ``updated_at`` nor ``version`` exists on them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    SOS_ADMIN = "SosAdmin"
    ELECTIONS_EXAMINER = "ElectionsExaminer"
    TITLE_EXAMINER = "TitleExaminer"
    PROPONENT = "Proponent"
    COUNTY_CLERK = "CountyClerk"
    CIRCULATOR_AGENT = "CirculatorAgent"
    CHALLENGER = "Challenger"


ALL_ROLES = [r.value for r in UserRole]


class StratificationMode(str, Enum):
    POOLED = "POOLED"
    STRATIFIED = "STRATIFIED"


class RegistrationStatus(str, Enum):
    """VoterRecord.registration_status."""
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    CANCELLED = "CANCELLED"
    PENDING = "PENDING"


class MeasureSubjectCode(str, Enum):
    TAX = "TAX"
    ELECTIONS = "ELECTIONS"
    EDUCATION = "EDUCATION"
    HEALTH = "HEALTH"
    ENVIRONMENT = "ENVIRONMENT"
    PUBLIC_SAFETY = "PUBLIC_SAFETY"


class PetitionStatus(str, Enum):
    DRAFT = "DRAFT"
    FORMAT_REVIEW = "FORMAT_REVIEW"
    FORMAT_REJECTED = "FORMAT_REJECTED"
    TITLE_PENDING = "TITLE_PENDING"
    CLEARED = "CLEARED"
    SIGNATURES_FILED = "SIGNATURES_FILED"
    SAMPLE_VERIFICATION = "SAMPLE_VERIFICATION"
    FULL_CHECK = "FULL_CHECK"
    CURE_PERIOD = "CURE_PERIOD"
    PENDING_CERTIFICATION = "PENDING_CERTIFICATION"
    PENDING_FAILURE = "PENDING_FAILURE"
    CERTIFIED = "CERTIFIED"
    FAILED = "FAILED"


class ChallengeDimension(str, Enum):
    """Petition.challenge_status."""
    NONE = "NONE"
    CHALLENGE_FILED = "CHALLENGE_FILED"
    COURT_REVIEW = "COURT_REVIEW"
    COURT_AFFIRMED = "COURT_AFFIRMED"
    COURT_REVERSED = "COURT_REVERSED"


class CirculatorRegistrationStatus(str, Enum):
    PENDING_TRAINING = "PENDING_TRAINING"
    TRAINED = "TRAINED"
    REGISTERED = "REGISTERED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class BatchStatus(str, Enum):
    RECEIVED = "RECEIVED"
    AFFIDAVIT_VERIFIED = "AFFIDAVIT_VERIFIED"
    SAMPLED = "SAMPLED"
    FULLY_CHECKED = "FULLY_CHECKED"
    REJECTED_FORMAT = "REJECTED_FORMAT"
    INVALIDATED = "INVALIDATED"


class SignatureValidationStatus(str, Enum):
    PENDING = "PENDING"
    VALID = "VALID"
    INVALID_NOT_REGISTERED = "INVALID_NOT_REGISTERED"
    INVALID_DUPLICATE = "INVALID_DUPLICATE"
    INVALID_SIGNATURE_MISMATCH = "INVALID_SIGNATURE_MISMATCH"
    INVALID_WRONG_COUNTY = "INVALID_WRONG_COUNTY"
    INVALID_FORMAT_DEFECT = "INVALID_FORMAT_DEFECT"
    VOIDED = "VOIDED"


class VoidReason(str, Enum):
    BATCH_INVALIDATED = "BATCH_INVALIDATED"
    CIRCULATOR_REVOKED = "CIRCULATOR_REVOKED"
    FRAUD_SUBSTANTIATED = "FRAUD_SUBSTANTIATED"


class RoundType(str, Enum):
    RANDOM_SAMPLE = "RANDOM_SAMPLE"
    FULL_CHECK = "FULL_CHECK"
    CURE_RECHECK = "CURE_RECHECK"


class RoundStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class RoundDetermination(str, Enum):
    PENDING = "PENDING"
    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"
    FULL_CHECK_REQUIRED = "FULL_CHECK_REQUIRED"


class CurePeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED_SUFFICIENT = "CLOSED_SUFFICIENT"
    CLOSED_INSUFFICIENT = "CLOSED_INSUFFICIENT"
    EXPIRED = "EXPIRED"


class ChallengeStatus(str, Enum):
    FILED = "FILED"
    COURT_REVIEW = "COURT_REVIEW"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class ChallengeGrounds(str, Enum):
    COUNT_ERROR = "COUNT_ERROR"
    FORGERY = "FORGERY"
    CIRCULATOR_INELIGIBLE = "CIRCULATOR_INELIGIBLE"
    FORMAT_DEFECT = "FORMAT_DEFECT"


class CourtRuling(str, Enum):
    AFFIRM = "AFFIRM"
    REVERSE = "REVERSE"


class FormatDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class DeterminationInput(str, Enum):
    CERTIFY = "CERTIFY"
    FAIL = "FAIL"


class ReferralType(str, Enum):
    FORGED_SIGNATURES = "FORGED_SIGNATURES"
    CIRCULATOR_MISCONDUCT = "CIRCULATOR_MISCONDUCT"
    FALSE_AFFIDAVIT = "FALSE_AFFIDAVIT"


class ReferralStatus(str, Enum):
    OPENED = "OPENED"
    REFERRED_TO_AG = "REFERRED_TO_AG"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"


class ReferralFinding(str, Enum):
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"


class InvoiceTier(str, Enum):
    TIER_NONE = "TIER_NONE"
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"


# --- Configuration resources: only id + created_at ------------------------

class VerificationStandard(TypedDict):
    id: str
    created_at: str
    jurisdiction_code: str
    gubernatorial_vote_total: int
    signature_pct_bps: int
    sample_pct_bps: int
    sample_min_count: int
    sufficiency_upper_bps: int
    sufficiency_lower_bps: int
    stratification_mode: str
    county_distribution_pct_bps: int
    required_qualifying_counties: int
    cure_allowed: bool
    cure_window_days: int
    cure_eligibility_floor_bps: int
    circulation_window_days: int
    verification_rate_millicents_per_signature: int
    county_surcharge_bps: int


class County(TypedDict):
    id: str
    created_at: str
    county_code: str
    name: str
    registered_voter_count: int


class VoterRecord(TypedDict):
    id: str
    created_at: str
    county_id: str
    voter_id_number: str
    full_name: str
    registration_status: str
    signature_on_file_hash: str
    registration_date: str


# --- Resources with the full system-managed property set ------------------

class Petition(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    standard_id: str
    proponent_user_id: str
    proponent_name: str
    submitted_title: str
    measure_subject_codes: List[str]
    official_title: Optional[str]
    official_summary: Optional[str]
    status: str
    challenge_status: str
    format_review_round: int
    cleared_at: Optional[str]
    circulation_deadline: Optional[str]
    required_valid_signatures: int
    raw_signature_count: int
    accepted_raw_total: int
    projected_valid_count: int
    verified_valid_count: int
    qualifying_county_count: int
    verification_cost_accrued_cents: int
    voided_signature_count: int
    cure_period_count: int


class Circulator(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    full_name: str
    residency_state_code: str
    is_paid: bool
    employer_name: Optional[str]
    disclosure_document_id: Optional[str]
    paid_disclosure_on_file: bool
    registration_status: str
    training_course_code: Optional[str]
    training_completed_at: Optional[str]
    affidavit_filed_at: Optional[str]
    misconduct_strike_count: int
    credibility_score_bps: int


class CirculationAssignment(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    petition_id: str
    circulator_id: str
    effective_from: str
    effective_to: str
    assigned_county_codes: List[str]
    paid_disclosure_ack: bool
    status: str


class SignatureBatch(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    petition_id: str
    circulator_id: str
    county_id: str
    cure_period_id: Optional[str]
    is_supplemental: bool
    affidavit_signed: bool
    affidavit_notary_id: Optional[str]
    filed_at: str
    raw_count: int
    accepted_raw_count: int
    format_defect_count: int
    checked_signature_count: int
    verification_cost_cents: int
    status: str
    status_before_invalidation: Optional[str]
    invalidation_reason: Optional[str]


class SignatureRecord(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    batch_id: str
    line_number: int
    signer_name: str
    claimed_voter_id_number: str
    signed_on: str
    signature_hash: str
    matched_voter_record_id: Optional[str]
    duplicate_of_signature_id: Optional[str]
    validated_in_round_id: Optional[str]
    in_sample: bool
    validation_status: str
    status_before_void: Optional[str]
    void_reason: Optional[str]
    manual_match_override_applied: bool


class VerificationRound(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    petition_id: str
    cure_period_id: Optional[str]
    round_type: str
    round_index: int
    status: str
    eligible_pool_size: int
    sample_size: int
    sampled_valid_count: int
    validity_rate_bps: int
    projected_valid_count: int
    determination: str
    tallied_by_examiner_id: Optional[str]
    accrued_cost_cents: int
    voided_reason: Optional[str]


class CurePeriod(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    petition_id: str
    opened_at: str
    deadline_at: str
    shortfall_at_open: int
    assumed_validity_rate_bps: int
    cure_target_raw_signatures: int
    supplemental_raw_count: int
    status: str


class Challenge(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    petition_id: str
    challenger_user_id: str
    challenger_name: str
    grounds: str
    statement: str
    filed_at: str
    review_deadline_at: str
    court_docket_number: Optional[str]
    ruling: Optional[str]
    status: str


class FraudReferral(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    petition_id: str
    circulator_id: str
    batch_id: Optional[str]
    referral_type: str
    narrative: str
    opened_by_examiner_id: str
    adjudicated_by_examiner_id: Optional[str]
    referred_to_ag: bool
    finding: Optional[str]
    voided_signature_count: int
    status: str
