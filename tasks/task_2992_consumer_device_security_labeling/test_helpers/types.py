"""Domain types for the Consumer Device Security Labeling API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Dict, Any


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
    CONFORMITY_REVIEWER = "ConformityReviewer"
    MANUFACTURER = "Manufacturer"
    TEST_LAB_OPERATOR = "TestLabOperator"
    RETAILER = "Retailer"
    CONSUMER = "Consumer"


ALL_ROLES = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class RequiredRoute(str, Enum):
    SELF_ATTESTATION = "SELF_ATTESTATION"
    THIRD_PARTY_TEST = "THIRD_PARTY_TEST"


class EligibilityStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    EXCLUDED = "EXCLUDED"


class PracticeArea(str, Enum):
    AUTHENTICATION = "AUTHENTICATION"
    SOFTWARE_UPDATE = "SOFTWARE_UPDATE"
    DATA_PROTECTION = "DATA_PROTECTION"
    VULN_DISCLOSURE = "VULN_DISCLOSURE"


PRACTICE_AREAS = [a.value for a in PracticeArea]


class EnterpriseClass(str, Enum):
    SMALL = "SMALL"
    LARGE = "LARGE"


class Standing(str, Enum):
    GOOD = "GOOD"
    DELINQUENT = "DELINQUENT"
    BARRED = "BARRED"


class ConformanceCurrency(str, Enum):
    CURRENT = "CURRENT"
    STALE = "STALE"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    DEFICIENT = "DEFICIENT"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class AssessmentDecision(str, Enum):
    APPROVED = "APPROVED"
    DEFICIENT = "DEFICIENT"
    REJECTED = "REJECTED"


class Grade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    FAIL = "FAIL"


class LabResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_TESTED = "NOT_TESTED"


class AccreditationStatus(str, Enum):
    ACCREDITED = "ACCREDITED"
    PROBATION = "PROBATION"
    REVOKED = "REVOKED"


class EngagementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class GrantStatus(str, Enum):
    PENDING_REGISTRY = "PENDING_REGISTRY"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class RegistryPublicationStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    WITHHELD = "WITHHELD"


class PublicationDecision(str, Enum):
    PUBLISHED = "PUBLISHED"
    WITHHELD = "WITHHELD"


class SuspensionReason(str, Enum):
    PRODUCT_SPEC_CHANGED = "PRODUCT_SPEC_CHANGED"
    SPONSOR_DELINQUENT = "SPONSOR_DELINQUENT"
    SUPPORT_PERIOD_ENDED = "SUPPORT_PERIOD_ENDED"


class UpdateCadence(str, Enum):
    AUTOMATIC = "AUTOMATIC"
    USER_INITIATED = "USER_INITIATED"
    NONE = "NONE"


class DisclosureCompleteness(str, Enum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


class ParticipationTier(str, Enum):
    BASELINE = "BASELINE"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class DisplayChannel(str, Enum):
    IN_STORE = "IN_STORE"
    ONLINE = "ONLINE"


class AuthorizationStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class WithdrawalReason(str, Enum):
    RETAILER_REQUEST = "RETAILER_REQUEST"
    GRANT_SUSPENDED = "GRANT_SUSPENDED"
    GRANT_EXPIRED = "GRANT_EXPIRED"


class ViolationType(str, Enum):
    UNAUTHORIZED_DISPLAY = "UNAUTHORIZED_DISPLAY"
    EXPIRED_LABEL_DISPLAY = "EXPIRED_LABEL_DISPLAY"
    FALSE_CLAIM = "FALSE_CLAIM"


class CaseStatus(str, Enum):
    OPENED = "OPENED"
    NOTICE_ISSUED = "NOTICE_ISSUED"
    LAB_REFERRAL = "LAB_REFERRAL"
    ADJUDICATED_UPHELD = "ADJUDICATED_UPHELD"
    ADJUDICATED_DISMISSED = "ADJUDICATED_DISMISSED"
    VACATED = "VACATED"


class PenaltyStatus(str, Enum):
    NONE = "NONE"
    ASSESSED = "ASSESSED"
    PAID = "PAID"
    VACATED = "VACATED"


class PenaltyVariant(str, Enum):
    STATUTORY_SCHEDULE = "STATUTORY_SCHEDULE"
    REVENUE_LINKED = "REVENUE_LINKED"


class AdjudicationOutcome(str, Enum):
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class EvaluationGrade(str, Enum):
    MEETING_TARGET = "MEETING_TARGET"
    PARTIAL = "PARTIAL"
    BELOW_TARGET = "BELOW_TARGET"


# --------------------------------------------------------------------------
# Entity shapes.  Resources listed in PRD §2.5 carry id / created_at /
# updated_at / version; SecurityCriterion and RecognitionSurvey carry only
# id and created_at.
# --------------------------------------------------------------------------
class ProgramTier(TypedDict):
    id: str
    tier_code: str
    required_route: str
    label_validity_days: int
    min_overall_score: float
    unverified_weight_factor: float
    issuance_base_fee_cents: int
    max_deficiency_rounds: int
    created_at: str
    updated_at: str
    version: int


class DeviceCategory(TypedDict):
    id: str
    category_code: str
    display_name: str
    eligibility_status: str
    exclusion_reason: Optional[str]
    program_tier_id: str
    min_support_period_days: int
    created_at: str
    updated_at: str
    version: int


class SecurityCriterion(TypedDict):
    """Immutable catalogue record: id and created_at only (PRD §2.5)."""
    id: str
    criterion_code: str
    practice_area: str
    weight: int
    requires_lab_verification: bool
    criterion_text: str
    created_at: str


class Manufacturer(TypedDict):
    id: str
    legal_name: str
    contact_email: str
    enterprise_class: str
    annual_us_revenue_cents: int
    standing: str
    outstanding_penalty_cents: int
    paid_penalty_cents: int
    vacated_penalty_cents: int
    total_assessed_penalty_cents: int
    upheld_case_count: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    manufacturer_id: str
    device_category_id: str
    model_name: str
    sku: str
    firmware_version: str
    declared_support_period_end: str
    update_policy_disclosed: bool
    retail_units_shipped: int
    spec_revision: int
    conformance_currency: str
    eligibility_status: str
    last_change_summary: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConformanceAssessment(TypedDict):
    id: str
    product_id: str
    route: str
    assessed_spec_revision: int
    status: str
    deficiency_round: int
    provisional_area_scores: Optional[Dict[str, float]]
    provisional_overall_score: Optional[float]
    verified_area_scores: Optional[Dict[str, float]]
    verified_overall_score: Optional[float]
    decided_overall_score: Optional[float]
    decided_min_area_score: Optional[float]
    gate_applied: bool
    grade: Optional[str]
    submitted_at: Optional[str]
    decided_at: Optional[str]
    decided_by_user_id: Optional[str]
    last_deficiency_by_user_id: Optional[str]
    reviewer_note: Optional[str]
    superseded_by_assessment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CriterionResponse(TypedDict):
    id: str
    assessment_id: str
    criterion_id: str
    self_declared_conformant: bool
    evidence_ref: Optional[str]
    lab_result: str
    lab_verified: bool
    created_at: str
    updated_at: str
    version: int


class TestLab(TypedDict):
    id: str
    lab_name: str
    accreditation_status: str
    total_bench_hours: int
    concurrent_bench_capacity: int
    reserved_bench_hours: int
    available_bench_hours: int
    created_at: str
    updated_at: str
    version: int


class TestEngagement(TypedDict):
    id: str
    assessment_id: str
    test_lab_id: str
    window_start: str
    window_end: str
    bench_hours: int
    status: str
    failed_criterion_codes: Optional[List[str]]
    report_reference: Optional[str]
    cancellation_reason: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LabelGrant(TypedDict):
    id: str
    product_id: str
    assessment_id: str
    scannable_code: str
    grant_status: str
    registry_publication_status: str
    suspension_reason: Optional[str]
    renewal_required: bool
    valid_from: Optional[str]
    valid_until: Optional[str]
    renewal_generation: int
    issuance_fee_cents: int
    superseded_by_grant_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RegistryEntry(TypedDict):
    id: str
    label_grant_id: str
    support_period_end: str
    update_policy_url: str
    update_cadence: str
    vuln_disclosure_contact: str
    disclosure_completeness: str
    published_at: Optional[str]
    published_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Retailer(TypedDict):
    id: str
    retailer_name: str
    education_materials_ack: bool
    education_program_version: Optional[str]
    active_display_count: int
    participation_tier: str
    created_at: str
    updated_at: str
    version: int


class RetailerDisplayAuthorization(TypedDict):
    id: str
    retailer_id: str
    label_grant_id: str
    channel: str
    display_from: str
    display_until: str
    status: str
    withdrawal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EnforcementCase(TypedDict):
    id: str
    subject_manufacturer_id: str
    reported_retailer_id: Optional[str]
    reported_scannable_code: str
    code_matches_registry: bool
    violation_type: str
    violation_line_items: List[Dict[str, Any]]
    violation_unit_count: int
    case_status: str
    penalty_status: str
    penalty_variant: Optional[str]
    penalty_cents: int
    aggravation_multiplier: Optional[float]
    notice_reference: Optional[str]
    notice_issued_by_user_id: Optional[str]
    adjudicated_by_user_id: Optional[str]
    referred_test_lab_id: Optional[str]
    adjudicated_at: Optional[str]
    vacate_reason: Optional[str]
    payment_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecognitionSurvey(TypedDict):
    """Immutable historical observation: id and created_at only (PRD §2.5)."""
    id: str
    survey_period_label: str
    survey_period_end: str
    respondents_count: int
    recognized_count: int
    created_at: str
