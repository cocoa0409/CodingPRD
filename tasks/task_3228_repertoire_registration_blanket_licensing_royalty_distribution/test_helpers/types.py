"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class PartyType(str, Enum):
    SONGWRITER = "SONGWRITER"
    PUBLISHER = "PUBLISHER"


class AffiliateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class WorkStatus(str, Enum):
    REGISTERED = "REGISTERED"
    IN_CONFLICT = "IN_CONFLICT"
    CONFIRMED = "CONFIRMED"
    WITHDRAWN = "WITHDRAWN"


class ShareClaimRole(str, Enum):
    WRITER = "WRITER"
    PUBLISHER = "PUBLISHER"


class ShareClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DISPUTED = "DISPUTED"
    REVOKED = "REVOKED"


class LicenseeCategory(str, Enum):
    BROADCASTER = "BROADCASTER"
    DIGITAL_SERVICE = "DIGITAL_SERVICE"
    VENUE = "VENUE"


class CreditStanding(str, Enum):
    GOOD = "GOOD"
    DELINQUENT = "DELINQUENT"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISPUTED = "DISPUTED"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class DisputeOpenedBy(str, Enum):
    LICENSEE = "LICENSEE"
    PRO = "PRO"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    NEGOTIATION = "NEGOTIATION"
    RATE_COURT = "RATE_COURT"
    SETTLED = "SETTLED"
    WITHDRAWN = "WITHDRAWN"


class RateCourtCaseStatus(str, Enum):
    FILED = "FILED"
    HEARING = "HEARING"
    DECIDED = "DECIDED"
    DISMISSED = "DISMISSED"


class PerformanceMedium(str, Enum):
    TERRESTRIAL_RADIO = "TERRESTRIAL_RADIO"
    NETWORK_TV = "NETWORK_TV"
    CABLE_TV = "CABLE_TV"
    DIGITAL_STREAMING = "DIGITAL_STREAMING"
    LIVE_VENUE = "LIVE_VENUE"


class PerformanceDaypart(str, Enum):
    PRIME = "PRIME"
    DAY = "DAY"
    LATE_NIGHT = "LATE_NIGHT"
    OVERNIGHT = "OVERNIGHT"


class PerformanceSource(str, Enum):
    MONITORING = "MONITORING"
    CUE_SHEET = "CUE_SHEET"
    DIGITAL_REPORT = "DIGITAL_REPORT"
    SAMPLE = "SAMPLE"


class PerformanceEventStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class CycleStatus(str, Enum):
    DRAFT = "DRAFT"
    COLLECTING = "COLLECTING"
    CALCULATING = "CALCULATING"
    DISTRIBUTED = "DISTRIBUTED"
    ADJUSTED = "ADJUSTED"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    PAID = "PAID"
    ADJUSTED = "ADJUSTED"


class AdjustmentReason(str, Enum):
    LATE_CLAIM = "LATE_CLAIM"
    AUDIT_FINDING = "AUDIT_FINDING"
    RATE_COURT_RETRO = "RATE_COURT_RETRO"
    DATA_CORRECTION = "DATA_CORRECTION"


class AdjustmentStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"


class AuditStatus(str, Enum):
    OPEN = "OPEN"
    FINDINGS_FILED = "FINDINGS_FILED"
    CLOSED = "CLOSED"


class PoolStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_ESCHEATED = "PARTIALLY_ESCHEATED"
    ESCHEATED = "ESCHEATED"


class UserRole(str, Enum):
    PRO_REGISTRAR = "ProRegistrar"
    PRO_LICENSING_ADMIN = "ProLicensingAdmin"
    RATE_COURT_OFFICER = "RateCourtOfficer"
    ROYALTY_DISTRIBUTOR = "RoyaltyDistributor"
    FINANCE_OFFICER = "FinanceOfficer"
    PUBLISHER = "Publisher"
    SONGWRITER = "Songwriter"
    LICENSEE = "Licensee"
    PRO_SYSTEM_ADMIN = "ProSystemAdmin"


# All entities carry common fields: id, created_at, updated_at, version.

class Affiliate(TypedDict, total=False):
    id: str
    legal_name: str
    party_type: str
    affiliation_code: str
    status: str
    royalty_balance_cents: int
    total_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class Work(TypedDict, total=False):
    id: str
    title: str
    alternate_titles: List[str]
    registered_by_affiliate_id: str
    status: str
    confirmed_at: Optional[str]
    aggregate_interest_bps: int
    created_at: str
    updated_at: str
    version: int


class ShareClaim(TypedDict, total=False):
    id: str
    work_id: str
    affiliate_id: str
    role: str
    collection_share_bps: int
    interest_share_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Licensee(TypedDict, total=False):
    id: str
    legal_name: str
    category: str
    reported_revenue_cents: int
    usage_units: int
    blanket_fee_cents: int
    credit_standing: str
    created_at: str
    updated_at: str
    version: int


class License(TypedDict, total=False):
    id: str
    licensee_id: str
    category: str
    effective_date: str
    expiry_date: str
    status: str
    fee_basis_cents: int
    created_at: str
    updated_at: str
    version: int


class RateDispute(TypedDict, total=False):
    id: str
    license_id: str
    opened_by_role: str
    disputed_fee_cents: int
    status: str
    settled_fee_cents: Optional[int]
    negotiation_rounds: int
    created_at: str
    updated_at: str
    version: int


class RateCourtCase(TypedDict, total=False):
    id: str
    dispute_id: str
    status: str
    adjudicated_fee_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PerformanceEvent(TypedDict, total=False):
    id: str
    work_id: str
    license_id: str
    performance_date: str
    medium: str
    daypart: str
    source: str
    play_count: int
    universe_estimated_plays: int
    credit_units: float
    cycle_id: Optional[str]
    rejection_error_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DistributionCycle(TypedDict, total=False):
    id: str
    label: str
    period_start: str
    period_end: str
    status: str
    pool_amount_cents: Optional[int]
    claims_open_until: Optional[str]
    version_epoch: int
    created_at: str
    updated_at: str
    version: int


class RoyaltyStatement(TypedDict, total=False):
    id: str
    cycle_id: str
    affiliate_id: str
    epoch: int
    gross_amount_cents: int
    admin_fee_cents: int
    net_amount_cents: int
    unclaimed_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RoyaltyAdjustment(TypedDict, total=False):
    id: str
    statement_id: str
    affiliate_id: str
    delta_cents: int
    reason: str
    audit_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditRequest(TypedDict, total=False):
    id: str
    licensee_id: str
    scope_period_start: str
    scope_period_end: str
    status: str
    findings_delta_cents: int
    created_at: str
    updated_at: str
    version: int


class UnclaimedRoyaltyPool(TypedDict, total=False):
    id: str
    cycle_id: str
    balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
