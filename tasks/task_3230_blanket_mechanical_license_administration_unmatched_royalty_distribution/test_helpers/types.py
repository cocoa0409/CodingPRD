"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, List, TypedDict


class UserRole(str, Enum):
    MLC_ADMINISTRATOR = "MLCAdministrator"
    SERVICE_PROVIDER_USER = "ServiceProviderUser"
    MEMBER_USER = "MemberUser"
    PUBLIC_SEARCHER = "PublicSearcher"


class ParticipationStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class MemberType(str, Enum):
    PUBLISHER = "PUBLISHER"
    SELF_PUBLISHED_SONGWRITER = "SELF_PUBLISHED_SONGWRITER"
    ADMINISTRATOR = "ADMINISTRATOR"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class PaymentMethod(str, Enum):
    ACH = "ACH"
    WIRE = "WIRE"
    CHECK = "CHECK"


class PayeeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class WorkStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNDER_DISPUTE = "UNDER_DISPUTE"
    WITHDRAWN = "WITHDRAWN"


class WorkShareStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISPUTED = "DISPUTED"
    WITHDRAWN = "WITHDRAWN"


class RateScheduleStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class UsageReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    AMENDED = "AMENDED"
    UNDER_AUDIT = "UNDER_AUDIT"
    AUDIT_CONFIRMED = "AUDIT_CONFIRMED"


class UsageLineStatus(str, Enum):
    PENDING_MATCH = "PENDING_MATCH"
    MATCHED = "MATCHED"
    UNMATCHED = "UNMATCHED"
    CLAIMED_MATCHED = "CLAIMED_MATCHED"
    DISPUTE_HELD = "DISPUTE_HELD"
    DISTRIBUTED = "DISTRIBUTED"


class AccrualStatus(str, Enum):
    HELD = "HELD"
    CLAIMED = "CLAIMED"
    RELEASED = "RELEASED"
    DISTRIBUTED = "DISTRIBUTED"
    FORFEITED = "FORFEITED"


class MatchRunStatus(str, Enum):
    COMPLETED = "COMPLETED"


class ClaimStatus(str, Enum):
    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    DISPUTED = "DISPUTED"
    RESOLVED = "RESOLVED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    DELIVERED = "DELIVERED"


class StatementLineType(str, Enum):
    MATCHED_EARNINGS = "MATCHED_EARNINGS"
    CLAIM_EARNINGS = "CLAIM_EARNINGS"
    DISTRIBUTION = "DISTRIBUTION"
    ADJUSTMENT = "ADJUSTMENT"


class AuditStatus(str, Enum):
    OPEN = "OPEN"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class CycleRunStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class CycleMethodology(str, Enum):
    MARKET_SHARE_USAGE = "MARKET_SHARE_USAGE"
    MARKET_SHARE_PRIOR = "MARKET_SHARE_PRIOR"


class ServiceProvider(TypedDict, total=False):
    id: str
    legal_name: str
    participation_status: str
    accepted_rate_schedule_version: int
    audit_credits: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    legal_name: str
    member_type: str
    ipi_number: Optional[str]
    is_signatory: bool
    status: str
    prior_market_share_numerator: int
    prior_market_share_denominator: int
    created_at: str
    updated_at: str
    version: int


class Payee(TypedDict, total=False):
    id: str
    member_id: str
    payee_legal_name: str
    payment_method: str
    routing_number: Optional[str]
    account_number: Optional[str]
    tax_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MusicalWork(TypedDict, total=False):
    id: str
    title: str
    iswc: Optional[str]
    status: str
    withdrawn_at: Optional[str]
    total_share_percent: float
    match_run_count: int
    created_at: str
    updated_at: str
    version: int


class WorkShare(TypedDict, total=False):
    id: str
    work_id: str
    claimant_member_id: str
    administered_by_member_id: Optional[str]
    share_percent: float
    effective_from: str
    effective_to: Optional[str]
    status: str
    supersedes_share_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RateSchedule(TypedDict, total=False):
    id: str
    effective_from: str
    effective_to: Optional[str]
    rate_cents_under_5min: int
    rate_cents_per_minute_over_5min: int
    status: str
    created_at: str
    updated_at: str
    version: int


class UsageReport(TypedDict, total=False):
    id: str
    service_provider_id: str
    reporting_month: str
    status: str
    accepted_rate_schedule_version: int
    total_usage_cents: int
    matched_usage_cents: int
    unmatched_usage_cents: int
    payment_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UsageLine(TypedDict, total=False):
    id: str
    report_id: str
    isrc: str
    track_title: str
    plays_count: int
    duration_seconds: int
    royalties_cents: int
    status: str
    matched_work_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RoyaltyAccrual(TypedDict, total=False):
    id: str
    usage_line_id: str
    service_provider_id: str
    amount_cents: int
    hold_expires_at: str
    reporting_month: str
    status: str
    matched_work_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MatchRun(TypedDict, total=False):
    id: str
    initiated_by: str
    total_lines_evaluated: int
    lines_matched: int
    lines_promoted_unmatched: int
    match_rate_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    accrual_id: str
    claimant_member_id: str
    claimed_work_id: str
    share_percent_claimed: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict, total=False):
    id: str
    work_id: str
    share_context: str
    claim_ids: List[str]
    status: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Statement(TypedDict, total=False):
    # Append-only family: carries only id + created_at (no updated_at/version)
    id: str
    member_id: str
    period_month: str
    gross_cents: int
    adjustments_cents: int
    net_cents: int
    status: str
    created_at: str


class StatementLine(TypedDict, total=False):
    # Append-only family: carries only id + created_at (no updated_at/version)
    id: str
    statement_id: str
    usage_line_id: Optional[str]
    member_id: str
    allocated_cents: int
    line_type: str
    payee_id: Optional[str]
    created_at: str


class AuditEngagement(TypedDict, total=False):
    id: str
    service_provider_id: str
    auditor_member_id: str
    scope_months: List[str]
    status: str
    findings_note: Optional[str]
    adjustment_cents: int
    created_at: str
    updated_at: str
    version: int


class CycleRun(TypedDict, total=False):
    id: str
    cycle_month: str
    pool_from_month: str
    pool_to_month: str
    status: str
    pool_cents: int
    residual_cents: int
    methodology: str
    created_at: str
    updated_at: str
    version: int


class DistributionLine(TypedDict, total=False):
    # Append-only family: carries only id + created_at (no updated_at/version)
    id: str
    cycle_run_id: str
    member_id: str
    allocated_cents: int
    weight_numerator: int
    weight_denominator: int
    residual_cents: int
    created_at: str
