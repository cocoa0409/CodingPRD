"""Domain types: entity TypedDicts, status enums, role enum.

Every value mirrors the PRD exactly: enum members are the wire strings, and
TypedDicts list exactly the fields a response carries. Most resources carry
the common fields ``id``, ``created_at``, ``updated_at`` and ``version``;
``Conviction`` is the deliberate exception (immutable once posted), so its
TypedDict carries only ``id`` and ``created_at`` plus its payload fields.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ── Roles (PRD §2.1) ─────────────────────────────────────────────────────────

class UserRole(str, Enum):
    ASSOCIATION_ADMIN = "AssociationAdmin"
    JURISDICTION_REGISTRAR = "JurisdictionRegistrar"
    CERTIFICATION_ENGINEER = "CertificationEngineer"
    FEDERAL_VERIFIER = "FederalVerifier"
    AUDIT_AUTHORITY = "AuditAuthority"


# ── Enum-typed fields ────────────────────────────────────────────────────────

class FeeTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class MembershipStatus(str, Enum):
    APPLIED = "APPLIED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class SystemName(str, Enum):
    POINTER_NETWORK = "POINTER_NETWORK"
    COMMERCIAL_DRIVER_NETWORK = "COMMERCIAL_DRIVER_NETWORK"
    TITLE_NETWORK = "TITLE_NETWORK"


class ParticipationStatus(str, Enum):
    ENROLLING = "ENROLLING"
    TESTING = "TESTING"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"


class CertificationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class LawfulStatusBasis(str, Enum):
    US_CITIZEN = "US_CITIZEN"
    PERMANENT_RESIDENT = "PERMANENT_RESIDENT"
    TEMPORARY_STATUS = "TEMPORARY_STATUS"


class RecordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TRANSFERRED_OUT = "TRANSFERRED_OUT"


class LicenseClass(str, Enum):
    STANDARD = "STANDARD"
    COMMERCIAL = "COMMERCIAL"


class LicenseStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    SURRENDERED = "SURRENDERED"
    DENIED = "DENIED"


class CheckStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class CheckType(str, Enum):
    SSN = "SSN"
    LAWFUL_STATUS = "LAWFUL_STATUS"


class TransferStatus(str, Enum):
    INITIATED = "INITIATED"
    SURRENDER_RECORDED = "SURRENDER_RECORDED"
    CONTESTED = "CONTESTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ConvictionSeverity(str, Enum):
    NON_CMV = "NON_CMV"
    CMV_SERIOUS = "CMV_SERIOUS"
    CMV_MAJOR = "CMV_MAJOR"


class DisqualificationBasis(str, Enum):
    MANUAL_JUDICIAL = "MANUAL_JUDICIAL"
    AUTO_MAJOR = "AUTO_MAJOR"
    AUTO_POINTS = "AUTO_POINTS"


class DisqualificationStatus(str, Enum):
    # Derived at read time from the logical clock; never stored.
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    OVERTURNED = "OVERTURNED"


class TitleBrand(str, Enum):
    SALVAGE = "SALVAGE"
    FLOOD = "FLOOD"
    REBUILT = "REBUILT"
    JUNK = "JUNK"


class TitleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPORTED = "EXPORTED"


class TitleTransferStatus(str, Enum):
    VERIFIED = "VERIFIED"
    COMPLETED = "COMPLETED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    AUDITED = "AUDITED"


# ── Entity bodies ────────────────────────────────────────────────────────────

class Jurisdiction(TypedDict):
    id: str
    code: str
    name: str
    fee_tier: str
    membership_status: str
    certified_systems_count: int
    timeliness_score_bp: int
    created_at: str
    updated_at: str
    version: int


class SystemParticipation(TypedDict):
    id: str
    jurisdiction_id: str
    system: str
    status: str
    granted_at: Optional[str]
    suspended_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConnectionCertification(TypedDict):
    id: str
    participation_id: str
    window_start: str
    window_end: str
    status: str
    score: Optional[int]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DriverIdentity(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    ssn_last4_hash: str
    lawful_status_basis: str
    created_at: str
    updated_at: str
    version: int


class DriverRecord(TypedDict):
    id: str
    driver_id: str
    holding_jurisdiction_id: str
    status: str
    points_total: int
    abstract_points_total: int
    created_at: str
    updated_at: str
    version: int


class License(TypedDict):
    id: str
    driver_id: str
    issuing_jurisdiction_id: str
    record_id: str
    license_class: str
    status: str
    ssn_check_status: str
    lawful_status_check_status: str
    created_at: str
    updated_at: str
    version: int


class LicenseTransfer(TypedDict):
    id: str
    driver_id: str
    from_jurisdiction_id: str
    to_jurisdiction_id: str
    prior_license_id: str
    new_license_id: Optional[str]
    status: str
    contest_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Conviction(TypedDict):
    # Immutable event: carries id + created_at only — NO updated_at, NO version.
    id: str
    record_id: str
    offense_date: str
    conviction_date: str
    severity: str
    points: int
    posted_at: str
    is_late: bool
    created_at: str


class Disqualification(TypedDict):
    id: str
    record_id: str
    basis: str
    start_date: str
    end_date: str
    status: str  # derived at read time from the logical clock
    overturned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VehicleTitle(TypedDict):
    id: str
    vin: str
    holding_jurisdiction_id: str
    brands: List[str]
    status: str
    washing_alert: bool
    created_at: str
    updated_at: str
    version: int


class TitleTransfer(TypedDict):
    id: str
    vehicle_title_id: str
    to_jurisdiction_id: str
    disclosed_brands: List[str]
    carried_brands: List[str]
    new_title_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeInvoice(TypedDict):
    id: str
    jurisdiction_id: str
    fiscal_year: int
    projected_volume: int
    certified_count_at_issue: int
    provisional_amount_cents: int
    status: str
    dispute_reason: Optional[str]
    settled_amount_cents: Optional[int]
    actual_volume_quarters: Optional[List[int]]
    final_amount_cents: Optional[int]
    adjustment_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int
