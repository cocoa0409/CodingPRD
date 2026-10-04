"""Domain types: entity TypedDicts, status enums, role enum.

All string values below are spelled exactly as the PRD spells them.
Every resource carries the common system-managed fields
``id``, ``created_at``, ``updated_at`` and ``version`` (PRD §2.5).
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1) — header values, spelled exactly.
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    SYSTEM_ADMINISTRATOR = "SystemAdministrator"
    REGISTRANT_REPRESENTATIVE = "RegistrantRepresentative"
    REGISTRATION_REVIEWER = "RegistrationReviewer"
    RISK_ASSESSOR = "RiskAssessor"
    STATE_LEAD_AGENCY = "StateLeadAgency"
    CERTIFICATION_AUTHORITY = "CertificationAuthority"


# ---------------------------------------------------------------------------
# Field enums
# ---------------------------------------------------------------------------
class ToxCategory(str, Enum):
    I = "I"
    II = "II"
    III = "III"
    IV = "IV"


class FormulationType(str, Enum):
    EMULSIFIABLE_CONCENTRATE = "EMULSIFIABLE_CONCENTRATE"
    GRANULAR = "GRANULAR"
    WETTABLE_POWDER = "WETTABLE_POWDER"
    READY_TO_USE = "READY_TO_USE"
    SEED_TREATMENT = "SEED_TREATMENT"


class ProductClassification(str, Enum):
    GENERAL_USE = "GENERAL_USE"
    RESTRICTED_USE = "RESTRICTED_USE"


class SignalWord(str, Enum):
    DANGER_POISON = "DANGER_POISON"
    WARNING = "WARNING"
    CAUTION = "CAUTION"


class UsePattern(str, Enum):
    FOOD_USE = "FOOD_USE"
    NON_FOOD_USE = "NON_FOOD_USE"
    MIXED_USE = "MIXED_USE"


class ApplicationMethod(str, Enum):
    GROUND = "GROUND"
    AERIAL = "AERIAL"
    CHEMIGATION = "CHEMIGATION"
    SEED_TREATMENT = "SEED_TREATMENT"


class StudyType(str, Enum):
    EFFICACY = "EFFICACY"
    TOXICOLOGY = "TOXICOLOGY"
    ENVIRONMENTAL_FATE = "ENVIRONMENTAL_FATE"
    RESIDUE_CHEMISTRY = "RESIDUE_CHEMISTRY"
    OCCUPATIONAL_EXPOSURE = "OCCUPATIONAL_EXPOSURE"
    ECOLOGICAL_EFFECTS = "ECOLOGICAL_EFFECTS"


class AssessmentTier(str, Enum):
    SCREENING = "SCREENING"
    REFINED = "REFINED"


class RowOrigin(str, Enum):
    INITIAL_APPLICATION = "INITIAL_APPLICATION"
    AMENDMENT = "AMENDMENT"


class AmendmentType(str, Enum):
    NEW_USE = "NEW_USE"
    RATE_CHANGE = "RATE_CHANGE"
    METHOD_CHANGE = "METHOD_CHANGE"


class CertificationCategory(str, Enum):
    AGRICULTURAL_PEST_CONTROL = "AGRICULTURAL_PEST_CONTROL"
    AERIAL_APPLICATION = "AERIAL_APPLICATION"
    STRUCTURAL = "STRUCTURAL"
    AQUATIC = "AQUATIC"


class RestrictionCode(str, Enum):
    PROHIBITED = "PROHIBITED"
    RATE_CAP = "RATE_CAP"
    SEASONAL_WINDOW = "SEASONAL_WINDOW"


class ProceedingType(str, Enum):
    CANCELLATION = "CANCELLATION"
    SUSPENSION = "SUSPENSION"


class ProceedingReason(str, Enum):
    RISK_FINDING = "RISK_FINDING"
    IMMINENT_HAZARD = "IMMINENT_HAZARD"
    DCI_DELINQUENCY = "DCI_DELINQUENCY"
    REGISTRANT_REQUEST = "REGISTRANT_REQUEST"


class StocksMethod(str, Enum):
    FIXED = "FIXED"
    DEPLETION = "DEPLETION"


class DisposalMethod(str, Enum):
    SALE = "SALE"
    RETURN = "RETURN"
    DESTRUCTION = "DESTRUCTION"


# ---------------------------------------------------------------------------
# Status enums (one per state machine)
# ---------------------------------------------------------------------------
class ProductStatus(str, Enum):
    UNREGISTERED = "UNREGISTERED"
    REGISTERED = "REGISTERED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    DATA_DEFICIENCY = "DATA_DEFICIENCY"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class StudyStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class UseSiteStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class ToleranceStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ESTABLISHED = "ESTABLISHED"
    REVOKED = "REVOKED"


class AmendmentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class CertificationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class BulletinStatus(str, Enum):
    IN_EFFECT = "IN_EFFECT"
    LIFTED = "LIFTED"


class ReviewCaseStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    DCI_PENDING = "DCI_PENDING"
    UNDER_REVIEW = "UNDER_REVIEW"
    COMPLETED = "COMPLETED"
    REFERRED = "REFERRED"


class DataCallInStatus(str, Enum):
    ISSUED = "ISSUED"
    RESPONDED = "RESPONDED"
    DEFICIENT = "DEFICIENT"
    SATISFIED = "SATISFIED"
    DELINQUENT = "DELINQUENT"


class ProceedingStatus(str, Enum):
    INITIATED = "INITIATED"
    HEARING_HELD = "HEARING_HELD"
    EFFECTIVE = "EFFECTIVE"
    VACATED = "VACATED"


class StateRegistrationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"
    LAPSED = "LAPSED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — all entities carry the common system-managed fields
# id / created_at / updated_at / version (PRD §2.5).
# ---------------------------------------------------------------------------
class ActiveIngredient(TypedDict):
    id: str
    common_name: str
    cas_number: str
    tox_category: str
    reference_dose_mg_kg_day: float
    aquatic_lc50_ppm: float
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    product_name: str
    active_ingredient_id: str
    registrant_ref: str
    formulation_type: str
    classification: str
    status: str
    signal_word: Optional[str]
    epa_registration_number: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UseSiteInput(TypedDict, total=False):
    """The seven-field use-site object accepted at application creation and
    inside a NEW_USE amendment payload (PRD §3.2 / §3.5)."""
    site_code: str
    pest_code: str
    max_application_rate_lbs_acre: float
    max_applications_per_season: int
    preharvest_interval_days: int
    application_method: str
    restricted_entry_interval_hours: int


class RegistrationApplication(TypedDict):
    id: str
    product_id: str
    registrant_ref: str
    use_pattern: str
    requested_classification: str
    status: str
    submitted_at: Optional[str]
    review_due_at: Optional[str]
    deficiency_count: int
    payment_cents: Optional[int]
    decided_at: Optional[str]
    final_classification: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StudySubmission(TypedDict):
    id: str
    application_id: Optional[str]
    data_call_in_id: Optional[str]
    study_type: str
    guideline_reference: str
    commodity_code: Optional[str]
    field_trial_residue_ppm: Optional[float]
    status: str
    submitted_by_ref: str
    decided_by_ref: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UseSite(TypedDict):
    id: str
    product_id: str
    origin: str
    site_code: str
    pest_code: str
    max_application_rate_lbs_acre: float
    max_applications_per_season: int
    preharvest_interval_days: int
    application_method: str
    restricted_entry_interval_hours: int
    status: str
    pre_removal_status: Optional[str]
    removed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RiskAssessment(TypedDict):
    id: str
    application_id: str
    assessor_ref: str
    tier: str
    pct_crop_treated: Optional[float]
    assessment_seq: int
    dietary_exposure_mg_day: float
    dietary_rq: float
    occupational_rq: float
    ecological_rq: float
    level_of_concern_exceeded: bool
    assessed_at: str
    created_at: str
    updated_at: str
    version: int


class Tolerance(TypedDict):
    id: str
    product_id: str
    origin: str
    commodity_code: str
    tolerance_ppm: float
    status: str
    established_at: Optional[str]
    revoked_at: Optional[str]
    pre_revocation_status: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LabelAmendment(TypedDict):
    id: str
    product_id: str
    registrant_ref: str
    amendment_type: str
    payload: Dict[str, Any]
    status: str
    priia_category: str
    submitted_at: str
    review_due_at: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ApplicatorCertification(TypedDict):
    id: str
    applicator_name: str
    state_code: str
    category: str
    certified_until: str
    status: str
    renewed_count: int
    created_at: str
    updated_at: str
    version: int


class EndangeredSpeciesBulletin(TypedDict):
    id: str
    product_id: str
    county_fips: str
    restriction_code: str
    rate_cap_lbs_acre: Optional[float]
    window_start_month: int
    window_end_month: int
    consultation_reference: str
    status: str
    effective_at: str
    lifted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RegistrationReviewCase(TypedDict):
    id: str
    product_id: str
    cycle_number: int
    opened_at: str
    due_at: str
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DataCallIn(TypedDict):
    id: str
    review_case_id: str
    required_study_types: List[str]
    response_deadline: str
    status: str
    issued_at: str
    responded_at: Optional[str]
    satisfied_study_types: List[str]
    pending_study_types: List[str]
    outstanding_study_types: List[str]
    created_at: str
    updated_at: str
    version: int


class CancellationProceeding(TypedDict):
    id: str
    product_id: str
    proceeding_type: str
    reason: str
    status: str
    auto_created: bool
    initiated_by_ref: str
    initiated_at: str
    hearing_held_at: Optional[str]
    effective_at: Optional[str]
    vacated_at: Optional[str]
    pre_effective_product_status: Optional[str]
    existing_stocks_authorized_units: Optional[int]
    stocks_method: Optional[str]
    depletion_rate_units_per_month: Optional[int]
    allow_sale_until: Optional[str]
    allow_use_until: Optional[str]
    existing_stocks_disposals: List[Dict[str, Any]]
    existing_stocks_disposed_units: int
    created_at: str
    updated_at: str
    version: int


class StateRegistration(TypedDict):
    id: str
    product_id: str
    registrant_ref: str
    state_code: str
    status: str
    additional_restrictions: List[str]
    annual_fee_cents: Optional[int]
    submitted_at: str
    granted_at: Optional[str]
    renewal_due_at: Optional[str]
    last_renewal_at: Optional[str]
    renewal_count: int
    created_at: str
    updated_at: str
    version: int
