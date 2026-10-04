"""Domain types: entity shapes, status enums, role enum.

Entity field inventories follow the PRD's resource descriptions.  Certification
and Match rows carry only id + created_at (no updated_at, no version); every
other resource carries the four system-managed fields.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CANDIDATE = "Candidate"
    EMPLOYER = "Employer"
    PLATFORM_ADMIN = "PlatformAdmin"


class NurseStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    HIRED = "HIRED"
    WITHDRAWN = "WITHDRAWN"


class Specialty(str, Enum):
    ICU = "ICU"
    ER = "ER"
    MED_SURG = "MED_SURG"
    TELEMETRY = "TELEMETRY"
    OR = "OR"
    PEDIATRICS = "PEDIATRICS"
    LABOR_DELIVERY = "LABOR_DELIVERY"
    ONCOLOGY = "ONCOLOGY"


class Shift(str, Enum):
    DAY = "DAY"
    NIGHT = "NIGHT"
    ROTATING = "ROTATING"


class LicenseVerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class CertCode(str, Enum):
    BLS = "BLS"
    ACLS = "ACLS"
    PALS = "PALS"
    CCRN = "CCRN"
    CEN = "CEN"
    RNC = "RNC"
    ONC = "ONC"


class FeeModel(str, Enum):
    SUBSCRIPTION = "SUBSCRIPTION"
    PER_PLACEMENT = "PER_PLACEMENT"


class SubscriptionTier(str, Enum):
    BASIC = "BASIC"
    PRO = "PRO"
    ENTERPRISE = "ENTERPRISE"


class EmployerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RequisitionStatus(str, Enum):
    OPEN = "OPEN"
    PAUSED = "PAUSED"
    FILLED = "FILLED"
    CLOSED = "CLOSED"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INTERVIEWING = "INTERVIEWING"
    OFFER_EXTENDED = "OFFER_EXTENDED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class InterviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class OfferStatus(str, Enum):
    ISSUED = "ISSUED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    RESCINDED = "RESCINDED"
    EXPIRED = "EXPIRED"


class CredentialStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class BackgroundStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"


class ScreeningOverallStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"


class DocType(str, Enum):
    I9 = "I9"
    W4 = "W4"
    DIRECT_DEPOSIT = "DIRECT_DEPOSIT"
    HEALTH_RECORD = "HEALTH_RECORD"
    SIGNED_CONTRACT = "SIGNED_CONTRACT"


class DocumentStatus(str, Enum):
    RECEIVED = "RECEIVED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PlacementStatus(str, Enum):
    PENDING_START = "PENDING_START"
    GUARANTEE_ACTIVE = "GUARANTEE_ACTIVE"
    COMPLETED = "COMPLETED"
    TERMINATED_IN_GUARANTEE = "TERMINATED_IN_GUARANTEE"


class InvoiceKind(str, Enum):
    PLACEMENT_FEE = "PLACEMENT_FEE"
    SUBSCRIPTION_RENEWAL = "SUBSCRIPTION_RENEWAL"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_CREDITED = "PARTIALLY_CREDITED"
    SETTLED = "SETTLED"
    VOID = "VOID"


class Nurse(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    home_state: str
    primary_specialty: str
    years_experience: int
    desired_shift: str
    desired_hourly_rate_cents: int
    max_commute_miles: int
    current_employer_name: str
    confidentiality_exclusions: List[str]
    status: str
    license_verified: bool
    active_application_count: int
    created_at: str
    updated_at: str
    version: int


class LicenseVerification(TypedDict, total=False):
    id: str
    nurse_id: str
    license_number: str
    license_state: str
    expiry_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict, total=False):
    # Append-only row: id + created_at only; no updated_at, no version.
    id: str
    nurse_id: str
    cert_code: str
    expires_on: str
    created_at: str


class Employer(TypedDict, total=False):
    id: str
    legal_name: str
    facility_state: str
    fee_model: str
    subscription_tier: str
    sla_response_hours: int
    guarantee_days: int
    placement_fee_bps: int
    credit_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Requisition(TypedDict, total=False):
    id: str
    employer_id: str
    specialty: str
    unit_name: str
    required_certs: List[str]
    facility_state: str
    distance_from_facility_miles: int
    shift: str
    offered_hourly_rate_cents: int
    openings_total: int
    openings_filled: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Match(TypedDict, total=False):
    # Regenerated artifact: id + created_at only; no updated_at, no version.
    id: str
    nurse_id: str
    requisition_id: str
    match_score: int
    suppressed: bool
    generated_at: str
    created_at: str


class Application(TypedDict, total=False):
    id: str
    requisition_id: str
    nurse_id: str
    employer_id: str
    proposed_hourly_rate_cents: int
    proposed_shift: str
    status: str
    response_deadline_at: str
    revision_count: int
    deadline_extended: bool
    created_at: str
    updated_at: str
    version: int


class Interview(TypedDict, total=False):
    id: str
    application_id: str
    starts_at: str
    ends_at: str
    status: str
    scheduled_by_employer_at: str
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict, total=False):
    id: str
    application_id: str
    offered_hourly_rate_cents: int
    start_date: str
    status: str
    offer_expires_at: str
    issued_at: str
    created_at: str
    updated_at: str
    version: int


class Screening(TypedDict, total=False):
    id: str
    application_id: str
    credential_status: str
    background_status: str
    overall_status: str
    created_at: str
    updated_at: str
    version: int


class OnboardingDocument(TypedDict, total=False):
    id: str
    application_id: str
    doc_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Placement(TypedDict, total=False):
    id: str
    application_id: str
    requisition_id: str
    nurse_id: str
    employer_id: str
    hourly_rate_cents: int
    annualized_salary_cents: int
    start_date: str
    guarantee_ends_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    employer_id: str
    placement_id: Optional[str]
    invoice_kind: str
    amount_due_cents: int
    amount_credited_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
