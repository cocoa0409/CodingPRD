"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    ADMIN = "Admin"
    LICENSEE = "Licensee"
    ROYALTY_OPS = "RoyaltyOps"
    PAYEE_ADMIN = "PayeeAdmin"
    STATUTORY_BOARD = "StatutoryBoard"
    ROYALTY_AUDITOR = "RoyaltyAuditor"
    MATCHING_AGENT = "MatchingAgent"


class LicenseStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ServiceCategory(str, Enum):
    PREEXISTING_SUBSCRIPTION = "PREEXISTING_SUBSCRIPTION"
    NONSUBSCRIPTION_AD_SUPPORTED = "NONSUBSCRIPTION_AD_SUPPORTED"
    BUSINESS_ESTABLISHMENT = "BUSINESS_ESTABLISHMENT"


class ScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"


class ProceedingStatus(str, Enum):
    OPEN = "OPEN"
    DECIDED = "DECIDED"
    PUBLISHED = "PUBLISHED"
    CLOSED = "CLOSED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    AMENDED = "AMENDED"


class IdentificationStatus(str, Enum):
    MATCHED = "MATCHED"
    UNMATCHED = "UNMATCHED"


class LiabilityStatus(str, Enum):
    COMPUTED = "COMPUTED"
    BILLED = "BILLED"
    PAID = "PAID"
    SETTLED = "SETTLED"
    WRITTEN_OFF = "WRITTEN_OFF"


class BatchStatus(str, Enum):
    PLANNED = "PLANNED"
    EXECUTED = "EXECUTED"
    REVERSED = "REVERSED"


class PayeeType(str, Enum):
    RIGHTS_OWNER = "RIGHTS_OWNER"
    FEATURED_ARTIST = "FEATURED_ARTIST"
    NONFEATURED_FUND = "NONFEATURED_FUND"


class FundType(str, Enum):
    AFM = "AFM"
    SAG_AFTRA = "SAG_AFTRA"


class RegistrationStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class CatalogStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class ClaimStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ClaimantType(str, Enum):
    RIGHTS_OWNER = "RIGHTS_OWNER"
    FEATURED_ARTIST = "FEATURED_ARTIST"


class PoolStatus(str, Enum):
    ACCRUING = "ACCRUING"
    MATCHING_CAMPAIGN = "MATCHING_CAMPAIGN"
    DISTRIBUTION_ELIGIBLE = "DISTRIBUTION_ELIGIBLE"
    DISTRIBUTED = "DISTRIBUTED"
    EXPIRED = "EXPIRED"


class AuditStatus(str, Enum):
    OPENED = "OPENED"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    SETTLED = "SETTLED"
    CLOSED = "CLOSED"
    WAIVED = "WAIVED"

# All entities carry the full common field set (id, created_at, updated_at, version).

class Licensee(TypedDict, total=False):
    id: str
    legal_name: str
    service_category: str
    license_status: str
    notice_date: str
    annual_minimum_fee_cents: int
    suspended_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RateSchedule(TypedDict, total=False):
    id: str
    proceeding_ref: str
    effective_start: str
    effective_end: str
    rate_per_performance_microcents: int
    min_fee_cents: int
    category: str
    schedule_status: str
    created_at: str
    updated_at: str
    version: int


class RateProceeding(TypedDict, total=False):
    id: str
    docket_no: str
    proceeding_status: str
    decided_schedule_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UsageReport(TypedDict, total=False):
    id: str
    licensee_id: str
    period_start: str
    period_end: str
    report_status: str
    total_performances: int
    matched_performances: int
    unmatched_performances: int
    created_at: str
    updated_at: str
    version: int


class PlayLine(TypedDict, total=False):
    id: str
    usage_report_id: str
    isrc: str
    track_title: str
    artist_name: str
    performance_count: int
    identification_status: str
    matched_recording_id: Optional[str]
    match_attempt_count: int
    created_at: str
    updated_at: str
    version: int


class Recording(TypedDict, total=False):
    id: str
    isrc: str
    track_title: str
    rights_owner_id: str
    featured_artist_id: str
    catalog_status: str
    created_at: str
    updated_at: str
    version: int


class RoyaltyLiability(TypedDict, total=False):
    id: str
    usage_report_id: str
    period_start: str
    gross_performance_royalty_cents: int
    minimum_fee_cents: int
    amount_due_cents: int
    liability_status: str
    admin_fee_cents: int
    distributable_pool_cents: int
    created_at: str
    updated_at: str
    version: int


class DistributionBatch(TypedDict, total=False):
    id: str
    usage_report_id: str
    batch_status: str
    scheduled_for: str
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DistributionLine(TypedDict, total=False):
    id: str
    distribution_batch_id: str
    payee_type: str
    payee_artist_id: Optional[str]
    payee_rights_owner_id: Optional[str]
    fund_type: Optional[str]
    amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Artist(TypedDict, total=False):
    id: str
    stage_name: str
    contact_email: str
    registration_status: str
    payee_verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RightsOwner(TypedDict, total=False):
    id: str
    legal_name: str
    contact_email: str
    registration_status: str
    payee_verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OwnershipClaim(TypedDict, total=False):
    id: str
    recording_id: str
    claimant_type: str
    claimant_id: str
    claimed_share_pct: float
    claim_status: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UnclaimedPool(TypedDict, total=False):
    id: str
    period_start: str
    period_end: str
    accrued_unmatched_cents: int
    pool_status: str
    distributed_cents: int
    campaign_count: int
    created_at: str
    updated_at: str
    version: int


class AuditCase(TypedDict, total=False):
    id: str
    licensee_id: str
    auditor_ref: str
    period_start: str
    period_end: str
    audit_status: str
    assessed_underpayment_cents: int
    recovered_cents: int
    created_at: str
    updated_at: str
    version: int
