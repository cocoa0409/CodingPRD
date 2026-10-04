"""Domain types: entity TypedDicts, status enums, role enum.

Reflects the PRD's persisted-resource rules: every entity except
ProfitShareLedgerEntry carries id/created_at/updated_at/version; the ledger
entry is append-only and carries only id and created_at.
"""
from enum import Enum
from typing import Any, List, Optional, TypedDict


class MarketCenterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class MembershipStatus(str, Enum):
    ENROLLED_PENDING_DOCS = "ENROLLED_PENDING_DOCS"
    ACTIVE = "ACTIVE"
    DEPARTED = "DEPARTED"


class CapStatus(str, Enum):
    UNCAPPED = "UNCAPPED"
    CAPPED = "CAPPED"


class SponsorshipEdgeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class DocumentType(str, Enum):
    SPONSOR_ATTESTATION = "SPONSOR_ATTESTATION"
    ICA_SIGNED = "ICA_SIGNED"
    W9 = "W9"


class DisputeStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_OVERTURNED = "RESOLVED_OVERTURNED"
    DISMISSED = "DISMISSED"
    REOPENED = "REOPENED"


class DisputeResolution(str, Enum):
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"
    DISMISSED = "DISMISSED"


class CommissionEventStatus(str, Enum):
    POSTED = "POSTED"
    SETTLED = "SETTLED"
    VOID = "VOID"


class PeriodStatus(str, Enum):
    OPEN = "OPEN"
    PRELIMINARY_CLOSED = "PRELIMINARY_CLOSED"
    FINAL_CLOSE_PENDING = "FINAL_CLOSE_PENDING"
    FINAL_CLOSED = "FINAL_CLOSED"


class LedgerEntryType(str, Enum):
    EXPENSE = "EXPENSE"
    ADJUSTMENT = "ADJUSTMENT"


class DistributionBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class DistributionStatus(str, Enum):
    PROJECTION = "PROJECTION"
    PAYABLE = "PAYABLE"
    PAID = "PAID"
    CLAWED_BACK = "CLAWED_BACK"
    FORFEITED = "FORFEITED"


class TransferStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class VestingStatus(str, Enum):
    ACCRUING = "ACCRUING"
    VESTED = "VESTED"
    FORFEITED = "FORFEITED"


class ResolutionStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    RATIFIED = "RATIFIED"
    REJECTED = "REJECTED"


class ResolutionType(str, Enum):
    FINAL_CLOSE_RATIFICATION = "FINAL_CLOSE_RATIFICATION"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    MARKET_CENTER_ADMIN = "MarketCenterAdmin"
    REGIONAL_DIRECTOR = "RegionalDirector"
    ALC_CHAIR = "ALCChair"
    AGENT = "Agent"


class MarketCenter(TypedDict):
    id: str
    name: str
    region_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Agent(TypedDict):
    id: str
    market_center_id: str
    sponsor_agent_id: Optional[str]
    full_name: str
    email: str
    join_date: str
    membership_status: str
    cap_status: str
    cap_year_start: str
    cap_year_end: str
    accrued_company_dollar: float
    pending_payable_profit_share: float
    lifetime_profit_share: float
    departure_date: Optional[str]
    vested: bool
    created_at: str
    updated_at: str
    version: int


class SponsorshipEdge(TypedDict):
    id: str
    parent_agent_id: str
    child_agent_id: str
    depth_level: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OnboardingDocument(TypedDict):
    id: str
    agent_id: str
    document_type: str
    document_ref: str
    attested_sponsor_agent_id: Optional[str]
    received_at: str
    created_at: str
    updated_at: str
    version: int


class SponsorshipDispute(TypedDict):
    id: str
    filer_agent_id: str
    sponsored_agent_id: str
    current_sponsor_agent_id: Optional[str]
    evidence_document_id: str
    reason: str
    filed_at: str
    window_deadline: str
    status: str
    resolution: Optional[str]
    appeal_count: int
    created_at: str
    updated_at: str
    version: int


class CommissionEvent(TypedDict):
    id: str
    agent_id: str
    market_center_id: str
    gross_commission: float
    occurred_on: str
    external_ref: str
    status: str
    company_dollar: float
    agent_retained: float
    final_company_dollar: Optional[float]
    cap_applied: bool
    created_at: str
    updated_at: str
    version: int


class ProfitSharePeriod(TypedDict):
    id: str
    market_center_id: str
    period_month: str
    status: str
    provisional_profit: Optional[float]
    final_profit: Optional[float]
    provisional_pool: Optional[float]
    profit_share_pool: Optional[float]
    distributed_total: float
    center_retained_amount: float
    preliminary_closed_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProfitShareLedgerEntry(TypedDict):
    # Append-only resource: id + created_at only — NO updated_at, NO version.
    id: str
    period_id: str
    entry_type: str
    amount: float
    memo: Optional[str]
    created_at: str


class DistributionLine(TypedDict):
    source_agent_id: str
    depth_level: int
    entitlement: float
    scaled_amount: float


class ProfitShareDistribution(TypedDict):
    id: str
    period_id: str
    agent_id: str
    basis: str
    amount: float
    level_breakdown: List[DistributionLine]
    status: str
    created_at: str
    updated_at: str
    version: int


class TransferRequest(TypedDict):
    id: str
    agent_id: str
    from_market_center_id: str
    to_market_center_id: str
    effective_date: str
    status: str
    downline_preserved: bool
    created_at: str
    updated_at: str
    version: int


class VestingSchedule(TypedDict):
    id: str
    agent_id: str
    vesting_start_date: str
    service_months_provisional: int
    service_days_final: int
    vested_ratio_provisional: float
    vested_ratio_final: float
    status: str
    created_at: str
    updated_at: str
    version: int


class GovernanceResolution(TypedDict):
    id: str
    period_id: str
    resolution_type: str
    status: str
    notes: Optional[str]
    proposed_by: Optional[str]
    ratified_by: Optional[str]
    created_at: str
    updated_at: str
    version: int
