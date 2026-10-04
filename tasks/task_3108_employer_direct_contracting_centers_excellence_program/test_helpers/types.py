"""Domain types: entity TypedDicts, status enums, role enum (PRD §2-§4)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    EMPLOYER_REP = "EmployerRep"
    CARE_COORDINATOR = "CareCoordinator"
    PHYSICIAN_REVIEWER = "PhysicianReviewer"
    CLAIMS_ADMIN = "ClaimsAdmin"


class EmployerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class BundleTemplateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class EpisodeStatus(str, Enum):
    INTAKE_PENDING = "INTAKE_PENDING"
    SCREENING = "SCREENING"
    SOR_PENDING = "SOR_PENDING"
    SOR_REVIEW = "SOR_REVIEW"
    APPROVED = "APPROVED"
    SCHEDULING = "SCHEDULING"
    PRE_OP = "PRE_OP"
    SURGERY_DONE = "SURGERY_DONE"
    POST_OP_TRACKING = "POST_OP_TRACKING"
    CLOSED = "CLOSED"
    AVOIDED = "AVOIDED"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"
    ABSORBED = "ABSORBED"


class TravelBenefitStatus(str, Enum):
    ADMINISTERED = "ADMINISTERED"
    RELEASED = "RELEASED"


class CarePlanItemStatus(str, Enum):
    OPEN = "OPEN"
    DONE = "DONE"
    WAIVED = "WAIVED"


class ProcedureFamily(str, Enum):
    CARDIAC = "CARDIAC"
    ORTHO_JOINT = "ORTHO_JOINT"
    BARIATRIC = "BARIATRIC"
    SPINE = "SPINE"


class ReadmitPolicy(str, Enum):
    RELATED_ONLY = "RELATED_ONLY"
    ALL_CAUSE = "ALL_CAUSE"


class ClaimType(str, Enum):
    BUNDLE_CASE = "BUNDLE_CASE"
    RELATED_CARE = "RELATED_CARE"
    TRAVEL = "TRAVEL"
    LODGING = "LODGING"
    READMISSION = "READMISSION"


class SubmittingEntity(str, Enum):
    HOSPITAL = "HOSPITAL"
    SURGERY_CENTER = "SURGERY_CENTER"
    ANESTHESIA_GROUP = "ANESTHESIA_GROUP"
    TRAVEL_VENDOR = "TRAVEL_VENDOR"


class ReviewConclusion(str, Enum):
    SURGERY_INDICATED = "SURGERY_INDICATED"
    SURGERY_UNNECESSARY = "SURGERY_UNNECESSARY"
    MORE_INFO_NEEDED = "MORE_INFO_NEEDED"


class ScreeningDocType(str, Enum):
    IMAGING = "IMAGING"
    LAB = "LAB"
    NOTE = "NOTE"
    CONSENT = "CONSENT"


class ScreeningResult(str, Enum):
    CANDIDATE = "CANDIDATE"
    NOT_A_CANDIDATE = "NOT_A_CANDIDATE"


class BenefitKind(str, Enum):
    TRAVEL = "TRAVEL"
    LODGING = "LODGING"


class Traveler(str, Enum):
    PATIENT = "PATIENT"
    COMPANION = "COMPANION"


class CarePhase(str, Enum):
    PRE_OP = "PRE_OP"
    POST_OP = "POST_OP"


class PriceRule(str, Enum):
    LOCKED = "LOCKED"
    REPRICED = "REPRICED"


class ClosedOutcome(str, Enum):
    CLEAN = "CLEAN"
    READMITTED = "READMITTED"


# --- Entity TypedDicts (common_fields: true unless noted) ---


class Employer(TypedDict, total=False):
    id: str
    legal_name: str
    ein: str
    baseline_rate_book: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BundleTemplate(TypedDict, total=False):
    id: str
    procedure_family: str
    label: str
    warranty_days: int
    implant_component_cap_cents: int
    readmit_policy: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RateBook(TypedDict, total=False):
    id: str
    book_code: str
    rates: dict
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    employer_id: str
    template_id: str
    template_version: int
    effective_from: str
    effective_to: str
    bundle_price_cents: int
    rate_components: dict
    outlier_threshold_cents: int
    outlier_share_pct: int
    episode_cap_per_month: int
    concurrent_capacity: int
    travel_benefit_cents: int
    lodging_benefit_cents: int
    companion_allowed: bool
    change_history: list
    reprice_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict, total=False):
    id: str
    employer_id: str
    full_name: str
    dob: str
    member_id: str
    created_at: str
    updated_at: str
    version: int


class Episode(TypedDict, total=False):
    id: str
    patient_id: str
    contract_id: str
    family: str
    intake_request_id: str
    status: str
    screen_seq: int
    scheduled_start_seq: int
    warranty_end_seq: int
    warranty_close_seq: int
    surgery_done_seq: int
    discharge_seq: int
    price_rule: Optional[str]
    applied_bundle_price_cents: int
    applied_rate_components: dict
    estimated_total_billed_cents: int
    closed_outcome: Optional[str]
    triage_rank: int
    created_at: str
    updated_at: str
    version: int


# Append-only: only id + created_at from the common set (PRD §2.4).
class Screening(TypedDict, total=False):
    id: str
    episode_id: str
    doc_type: str
    result: str
    screen_seq: int
    created_at: str


# Append-only: only id + created_at from the common set (PRD §2.4).
class SecondOpinionReview(TypedDict, total=False):
    id: str
    episode_id: str
    reviewer_id: str
    conclusion: str
    screen_seq: int
    prev_status: str
    created_at: str


class Claim(TypedDict, total=False):
    id: str
    episode_id: str
    claim_type: str
    submitting_entity: str
    service_date_seq: int
    billed_cents: int
    status: str
    adjudicated_payable_cents: Optional[int]
    adjudication_reason: Optional[str]
    is_readmit_related: bool
    created_at: str
    updated_at: str
    version: int


class Readmission(TypedDict, total=False):
    id: str
    episode_id: str
    related: bool
    provider_billed_cents: int
    recorded_seq: int
    out_of_window: bool
    absorbed_cents: int
    created_at: str
    updated_at: str
    version: int


class TravelBenefit(TypedDict, total=False):
    id: str
    episode_id: str
    kind: str
    traveler: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CarePlanItem(TypedDict, total=False):
    id: str
    episode_id: str
    phase: str
    local_provider_name: str
    required: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class EmployerReport(TypedDict, total=False):
    id: str
    employer_id: str
    period_month: str
    status: str
    computed_seq: int
    avoided_procedures_count: int
    avoided_cost_estimate_cents: int
    readmission_rate_pct: float
    warranty_absorbed_total_cents: int
    avg_days_to_schedule: float
    created_at: str
    updated_at: str
    version: int
