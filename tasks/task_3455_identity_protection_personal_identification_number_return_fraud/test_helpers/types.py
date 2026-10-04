"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD entity narratives (section 3) and the role model (section 2.1).
Every entity carries the standard common fields (id, created_at, updated_at,
version) per PRD section 2.5, except VerificationDocument — the immutable
submission record that carries only id and created_at (both updated_at and
version are absent from it).
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ─── Roles (PRD section 2.1) ─────────────────────────

class UserRole(str, Enum):
    TAXPAYER = "Taxpayer"
    TAX_PREPARER = "TaxPreparer"
    VERIFICATION_AGENT = "VerificationAgent"
    FRAUD_ANALYST = "FraudAnalyst"
    TAXPAYER_ADVOCATE = "TaxpayerAdvocate"
    SYSTEM_ADMIN = "SystemAdmin"


# ─── Enumerations ────────────────────────────────────

class TaxpayerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VICTIM_FLAGGED = "VICTIM_FLAGGED"


class IpPinEnrollment(str, Enum):
    NOT_ENROLLED = "NOT_ENROLLED"
    ENROLLED = "ENROLLED"
    OPTED_OUT = "OPTED_OUT"


class PinDeliveryChannel(str, Enum):
    POSTAL_MAIL = "POSTAL_MAIL"
    ONLINE_ACCOUNT = "ONLINE_ACCOUNT"


class ReportSource(str, Enum):
    TAXPAYER_REPORT = "TAXPAYER_REPORT"
    DUPLICATE_DETECTION = "DUPLICATE_DETECTION"


class ReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class PinStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class PreparerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class FilingStatus(str, Enum):
    SINGLE = "SINGLE"
    MARRIED_JOINT = "MARRIED_JOINT"
    HEAD_OF_HOUSEHOLD = "HEAD_OF_HOUSEHOLD"


class BankProduct(str, Enum):
    NONE = "NONE"
    REFUND_TRANSFER = "REFUND_TRANSFER"


class TaxReturnStatus(str, Enum):
    RECEIVED = "RECEIVED"
    FILTER_PASSED = "FILTER_PASSED"
    FILTER_HELD = "FILTER_HELD"
    REFUND_SCHEDULED = "REFUND_SCHEDULED"
    REFUND_RELEASED = "REFUND_RELEASED"
    FRAUD_CONFIRMED = "FRAUD_CONFIRMED"


class HoldZone(str, Enum):
    GRAY = "GRAY"
    FULL = "FULL"


class FilterHoldStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED_VERIFIED = "RESOLVED_VERIFIED"
    RESOLVED_FALSE_POSITIVE = "RESOLVED_FALSE_POSITIVE"
    RESOLVED_FRAUD = "RESOLVED_FRAUD"


class VerificationChannel(str, Enum):
    ONLINE = "ONLINE"
    PHONE = "PHONE"
    IN_PERSON = "IN_PERSON"


class DocType(str, Enum):
    PHOTO_ID = "PHOTO_ID"
    PRIOR_YEAR_RETURN = "PRIOR_YEAR_RETURN"
    W2 = "W2"
    SSA_CARD = "SSA_CARD"
    UTILITY_BILL = "UTILITY_BILL"


class VerificationCaseStatus(str, Enum):
    OPENED = "OPENED"
    DOCS_REQUESTED = "DOCS_REQUESTED"
    DOCS_SUBMITTED = "DOCS_SUBMITTED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"


class Relationship(str, Enum):
    CHILD = "CHILD"
    STEPCHILD = "STEPCHILD"
    SIBLING = "SIBLING"
    PARENT = "PARENT"
    OTHER = "OTHER"


class ClaimStatus(str, Enum):
    CLAIMED = "CLAIMED"
    CONTESTED = "CONTESTED"
    SUSTAINED = "SUSTAINED"
    DISALLOWED = "DISALLOWED"


class ConflictResolution(str, Enum):
    FIRST_FILER = "FIRST_FILER"
    SECOND_FILER = "SECOND_FILER"


class ConflictResolvedReason(str, Enum):
    ANALYST_DECISION = "ANALYST_DECISION"
    DEFAULT_NO_EVIDENCE = "DEFAULT_NO_EVIDENCE"
    FRAUD_FORFEIT = "FRAUD_FORFEIT"


class ConflictStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class PatternType(str, Enum):
    PREPARER_NETWORK_VELOCITY = "PREPARER_NETWORK_VELOCITY"
    BANK_PRODUCT_CLUSTER = "BANK_PRODUCT_CLUSTER"


class AlertStatus(str, Enum):
    FLAGGED = "FLAGGED"
    CONFIRMED_SCHEME = "CONFIRMED_SCHEME"
    CLEARED = "CLEARED"


class DisbursementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class HardshipType(str, Enum):
    LEVY_THREAT = "LEVY_THREAT"
    EVICTION = "EVICTION"
    MEDICAL = "MEDICAL"
    UTILITY_SHUTOFF = "UTILITY_SHUTOFF"
    OTHER = "OTHER"


class AdvocateCaseStatus(str, Enum):
    OPENED = "OPENED"
    EXPEDITED_REVIEW = "EXPEDITED_REVIEW"
    RESOLVED = "RESOLVED"


class ConfigStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


# ─── Entity TypedDicts ───────────────────────────────
# Common-fields entities carry id + created_at + updated_at + version
# (PRD section 2.5). VerificationDocument is the sole exception.

class Taxpayer(TypedDict, total=False):
    id: str
    tin: str
    full_name: str
    date_of_birth: str
    prior_year_refund_cents: int
    pin_delivery_channel: str
    status: str
    ip_pin_enrollment: str
    created_at: str
    updated_at: str
    version: int


class IdentityTheftReport(TypedDict, total=False):
    id: str
    taxpayer_id: str
    source: str
    description: str
    created_by_user_id: str
    confirmed_tax_year: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProtectionPin(TypedDict, total=False):
    id: str
    taxpayer_id: str
    tax_year: int
    pin_value: str
    delivery_channel: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Preparer(TypedDict, total=False):
    id: str
    ptin: str
    firm_name: str
    status: str
    filed_return_count: int
    created_at: str
    updated_at: str
    version: int


class TaxReturn(TypedDict, total=False):
    id: str
    taxpayer_id: str
    preparer_id: Optional[str]
    tax_year: int
    filing_status: str
    claimed_refund_cents: int
    ip_pin_submitted: Optional[str]
    bank_product: str
    bank_account_fingerprint: Optional[str]
    received_at: str
    risk_score: int
    scoring_model_version: str
    adjustment_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FilterHold(TypedDict, total=False):
    id: str
    return_id: str
    risk_score: int
    model_version: str
    zone: str
    reason_codes: List[str]
    priority_review: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class IdentityVerificationCase(TypedDict, total=False):
    id: str
    return_id: Optional[str]
    taxpayer_id: str
    channel: str
    attempts_count: int
    required_document_types: List[str]
    deadline_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class VerificationDocument(TypedDict, total=False):
    # Immutable submission record: carries ONLY id + created_at as common
    # fields; updated_at and version are absent (PRD section 2.5).
    id: str
    case_id: str
    doc_type: str
    received_at: str
    created_at: str


class ServiceOffice(TypedDict, total=False):
    id: str
    office_code: str
    name: str
    capacity: int
    created_at: str
    updated_at: str
    version: int


class VerificationAppointment(TypedDict, total=False):
    id: str
    office_id: str
    case_id: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DependentClaim(TypedDict, total=False):
    id: str
    return_id: str
    dependent_tin: str
    relationship: str
    credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DependentConflict(TypedDict, total=False):
    id: str
    dependent_tin: str
    tax_year: int
    return_a_id: str
    return_b_id: str
    evidence_window_ends_at: str
    evidence_a_submitted: bool
    evidence_b_submitted: bool
    resolution: Optional[str]
    resolved_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FraudSchemeAlert(TypedDict, total=False):
    id: str
    preparer_id: Optional[str]
    pattern_type: str
    evidence: Dict[str, Any]
    confirmed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RefundDisbursement(TypedDict, total=False):
    id: str
    return_id: str
    base_cents: int
    provisional_interest_cents: int
    final_interest_cents: Optional[int]
    amount_cents: int
    scheduled_at: str
    released_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AdvocateCase(TypedDict, total=False):
    id: str
    taxpayer_id: str
    return_id: Optional[str]
    hardship_type: str
    expedited: bool
    opened_by_user_id: str
    resolution_note: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FilterModelConfig(TypedDict, total=False):
    id: str
    model_version: str
    w_victim_flagged: int
    w_refund_delta: int
    w_bank_product: int
    w_preparer_flagged: int
    w_dependent_conflict: int
    interaction_bonus: int
    gray_zone_threshold: int
    hold_threshold: int
    status: str
    created_at: str
    updated_at: str
    version: int
