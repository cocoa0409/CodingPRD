"""Domain types: entity TypedDicts, status enums, role enum.

Entity shapes follow the PRD resource model. Ledger-style append-only
resources (PerformanceAssessment, SettlementEntry) carry only id and
created_at — no updated_at, no version.
"""
from enum import Enum
from typing import Optional, TypedDict


class DeliveryYearStatus(str, Enum):
    DRAFT = "DRAFT"
    FORECAST_LOCKED = "FORECAST_LOCKED"
    AUCTION_OPEN = "AUCTION_OPEN"
    CLEARED = "CLEARED"
    SETTLED = "SETTLED"
    CLOSED = "CLOSED"


class LoadForecastStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"


class OwnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ResourceStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ACCREDITED = "ACCREDITED"
    RETIRED = "RETIRED"


class ResourceType(str, Enum):
    GEN = "GEN"
    DR = "DR"
    EE = "EE"


class AccreditationMethod(str, Enum):
    CLASS_AVG = "CLASS_AVG"
    UNIT_SPECIFIC = "UNIT_SPECIFIC"


class AccreditationStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    EFFECTIVE = "EFFECTIVE"
    REJECTED = "REJECTED"


class OfferStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SEALED = "SEALED"
    CLEARED = "CLEARED"
    PARTIALLY_CLEARED = "PARTIALLY_CLEARED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class MitigationStatus(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    PASSED = "PASSED"
    MITIGATED = "MITIGATED"
    EXEMPT = "EXEMPT"


class ReviewOutcome(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    MITIGATE = "MITIGATE"
    EXEMPT = "EXEMPT"


class AuctionRunStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    SEALED = "SEALED"
    CLEARED = "CLEARED"
    SETTLED = "SETTLED"


class CommitmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REPLACEMENT_PENDING = "REPLACEMENT_PENDING"
    SETTLED = "SETTLED"
    DEFAULTED = "DEFAULTED"


class ReplacementStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class EmergencyEventStatus(str, Enum):
    DECLARED = "DECLARED"
    ASSESSING = "ASSESSING"
    ASSESSED = "ASSESSED"
    SETTLED = "SETTLED"


class EventType(str, Enum):
    EMERGENCY_ACTION = "EMERGENCY_ACTION"
    DR_TEST = "DR_TEST"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class MeasurementReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class SettlementEntryType(str, Enum):
    CHARGE = "CHARGE"
    BONUS = "BONUS"
    REDISTRIBUTION = "REDISTRIBUTION"


class UserRole(str, Enum):
    MARKET_ADMIN = "MarketAdmin"
    RESOURCE_OWNER = "ResourceOwner"
    SETTLEMENT_OPS = "SettlementOps"


class DeliveryYear(TypedDict, total=False):
    id: str
    delivery_year_label: str
    planning_period_start: str
    planning_period_end: str
    status: str
    reliability_requirement_mw: float
    forecast_version: int
    created_at: str
    updated_at: str
    version: int


class Zone(TypedDict, total=False):
    id: str
    delivery_year_id: str
    zone_code: str
    parent_zone_id: Optional[str]
    import_limit_mw: Optional[float]
    zonal_requirement_mw: float
    clearing_price_per_mw_day: Optional[float]
    cleared_mw: float
    created_at: str
    updated_at: str
    version: int


class LoadForecast(TypedDict, total=False):
    id: str
    delivery_year_id: str
    revision: int
    rto_peak_load_mw: float
    reserve_margin_pct: float
    pool_wide_avg_eford: float
    zonal_peak_shares: dict
    status: str
    created_at: str
    updated_at: str
    version: int


class ResourceOwnerEntity(TypedDict, total=False):
    id: str
    legal_name: str
    contact_email: str
    credit_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CapacityResource(TypedDict, total=False):
    id: str
    owner_id: str
    zone_id: str
    resource_type: str
    nameplate_mw: float
    status: str
    accredited_ucap_mw: float
    must_offer: bool
    created_at: str
    updated_at: str
    version: int


class Accreditation(TypedDict, total=False):
    id: str
    resource_id: str
    delivery_year_id: str
    method: str
    class_avg_factor: Optional[float]
    unit_elcc_factor: Optional[float]
    forced_outage_rate: float
    scarcity_hours_sampled: int
    accreditation_factor: float
    ucap_mw: float
    status: str
    created_at: str
    updated_at: str
    version: int


class AuctionOffer(TypedDict, total=False):
    id: str
    resource_id: str
    auction_run_id: str
    offer_mw: float
    offer_price_per_mw_day: float
    mitigated_cap_per_mw_day: float
    mitigation_status: str
    effective_price_per_mw_day: float
    cleared_mw: float
    status: str
    created_at: str
    updated_at: str
    version: int


class MitigationReview(TypedDict, total=False):
    id: str
    offer_id: str
    reviewer_note: Optional[str]
    pivotal_supplier_flag: bool
    outcome: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuctionRun(TypedDict, total=False):
    id: str
    delivery_year_id: str
    run_label: str
    status: str
    sealed_at: Optional[str]
    cleared_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CapacityCommitment(TypedDict, total=False):
    id: str
    resource_id: str
    offer_id: str
    delivery_year_id: str
    committed_mw: float
    clearing_price_per_mw_day: float
    daily_revenue_dollars: float
    status: str
    cumulative_performance_score: float
    created_at: str
    updated_at: str
    version: int


class ReplacementTransaction(TypedDict, total=False):
    id: str
    commitment_id: str
    replacement_resource_id: str
    replacement_mw: float
    price_per_mw_day: float
    expected_commitment_version: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EmergencyEvent(TypedDict, total=False):
    id: str
    delivery_year_id: str
    event_start: str
    event_end: str
    event_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PerformanceAssessment(TypedDict, total=False):
    # Append-only: id + created_at only; NO updated_at, NO version.
    id: str
    emergency_event_id: str
    commitment_id: str
    expected_mw: float
    actual_mw: float
    performance_ratio: float
    charge_or_credit_dollars: float
    assessed_mwh: float
    status: str
    created_at: str


class MeasurementReport(TypedDict, total=False):
    id: str
    resource_id: str
    delivery_year_id: str
    reporting_period_start: str
    reporting_period_end: str
    metered_mwh: float
    baseline_mwh: float
    verified_ucap_mw: float
    revision_of_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SettlementEntry(TypedDict, total=False):
    # Append-only: id + created_at only; NO updated_at, NO version.
    id: str
    delivery_year_id: str
    commitment_id: str
    emergency_event_id: Optional[str]
    entry_type: str
    amount_dollars: float
    created_at: str
