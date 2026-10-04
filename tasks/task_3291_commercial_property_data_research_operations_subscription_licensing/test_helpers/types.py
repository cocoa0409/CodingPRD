"""Domain types for the Commercial Property Data Licensing API.

Entity TypedDicts, status enumerations and the role enumeration, transcribed
from the resource model and state machines described in the PRD.

Resources declared with the standard common-field set carry ``id``,
``created_at``, ``updated_at`` and ``version``. ``UsageEvent`` is the one
exception: it is an immutable ledger entry and therefore carries only ``id``
and ``created_at``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Role enumeration (PRD §2.1) ──────────────────────────────

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    RESEARCH_ANALYST = "ResearchAnalyst"
    SEAT_USER = "SeatUser"
    LICENSING_ADMIN = "LicensingAdmin"
    ENFORCEMENT_OFFICER = "EnforcementOfficer"
    BROKER_PUBLISHER = "BrokerPublisher"


# ─── Status enumerations ──────────────────────────────────────

class OrganizationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class OrgType(str, Enum):
    DATA_PROVIDER = "DATA_PROVIDER"
    BROKERAGE = "BROKERAGE"
    SUBSCRIBER = "SUBSCRIBER"


class ServiceTier(str, Enum):
    ENTERPRISE = "ENTERPRISE"
    MID_MARKET = "MID_MARKET"
    SMB = "SMB"


class UserStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class PropertyType(str, Enum):
    OFFICE = "OFFICE"
    RETAIL = "RETAIL"
    INDUSTRIAL = "INDUSTRIAL"
    MULTIFAMILY = "MULTIFAMILY"
    HOSPITALITY = "HOSPITALITY"


class PropertyClass(str, Enum):
    CLASS_A = "CLASS_A"
    CLASS_B = "CLASS_B"
    CLASS_C = "CLASS_C"


class ResearchStatus(str, Enum):
    DRAFT = "DRAFT"
    RESEARCHING = "RESEARCHING"
    VERIFIED = "VERIFIED"


class LandPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class SourceType(str, Enum):
    DEED = "DEED"
    PUBLIC_RECORD = "PUBLIC_RECORD"
    DIRECT_CONTACT = "DIRECT_CONTACT"
    BROKER_LISTING = "BROKER_LISTING"
    THIRD_PARTY_FEED = "THIRD_PARTY_FEED"


class ContactMethod(str, Enum):
    PHONE = "PHONE"
    EMAIL = "EMAIL"
    SITE_VISIT = "SITE_VISIT"
    RECORDS_REQUEST = "RECORDS_REQUEST"
    FEED_IMPORT = "FEED_IMPORT"


class SourceClassification(str, Enum):
    FIRST_PARTY = "FIRST_PARTY"
    THIRD_PARTY_LICENSED = "THIRD_PARTY_LICENSED"


class ProposedStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ContractProduct(str, Enum):
    CORE_MARKET_DATA = "CORE_MARKET_DATA"
    ANALYTICS_INDEX = "ANALYTICS_INDEX"
    LISTING_SERVICE = "LISTING_SERVICE"
    GLOBAL_ALL = "GLOBAL_ALL"


class ContractStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    GRACE = "GRACE"
    RENEWED = "RENEWED"
    LAPSED = "LAPSED"
    TERMINATED = "TERMINATED"


class RenewalDecision(str, Enum):
    NONE = "NONE"
    FAILED = "FAILED"
    TERMINATED = "TERMINATED"


class AuditIntensity(str, Enum):
    STANDARD = "STANDARD"
    ENHANCED = "ENHANCED"


class IndexTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class SeatOccupancy(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    REVOKED = "REVOKED"


class UsageEventType(str, Enum):
    DATASET_DOWNLOAD = "DATASET_DOWNLOAD"
    REPORT_EXPORT = "REPORT_EXPORT"
    BULK_LOOKUP = "BULK_LOOKUP"
    API_QUERY = "API_QUERY"


class SaleSubordinationStatus(str, Enum):
    PENDING = "PENDING"
    SUBORDINATED = "SUBORDINATED"
    LAPSED = "LAPSED"


class ListingType(str, Enum):
    AVAILABLE = "AVAILABLE"
    LEASED = "LEASED"
    SOLD = "SOLD"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class CaseType(str, Enum):
    AUDIT = "AUDIT"
    LITIGATION = "LITIGATION"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    ESCALATED = "ESCALATED"
    SETTLED = "SETTLED"
    WITHDRAWN = "WITHDRAWN"


class RunType(str, Enum):
    INDEX = "INDEX"
    FORECAST = "FORECAST"


class AdjustmentMode(str, Enum):
    UNADJUSTED = "UNADJUSTED"
    HEDONIC = "HEDONIC"


class ForecastSelector(str, Enum):
    LATEST = "LATEST"
    EARLIEST = "EARLIEST"
    UPPER_BOUND = "UPPER_BOUND"


class AttributionStatus(str, Enum):
    ATTRIBUTED = "ATTRIBUTED"
    UNWOUND = "UNWOUND"


# ─── Entity shapes (common_fields: true unless noted) ─────────

class Organization(TypedDict):
    id: str
    legal_name: str
    org_type: str
    home_market: str
    service_tier: str
    authorized_market_count: int
    active_contract_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class User(TypedDict):
    id: str
    organization_id: str
    email: str
    full_name: str
    role: str
    assigned_market: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    parent_property_id: Optional[str]
    market: str
    address_line: str
    property_type: str
    rentable_sqft: int
    classification: str
    research_status: str
    land_posture: str
    attribute_verified_count: int
    attribute_total_count: int
    completeness_pct: float
    stale_source_count: int
    verified_sale_value_cents: int
    created_at: str
    updated_at: str
    version: int


class SourceDocument(TypedDict):
    id: str
    property_id: str
    source_type: str
    source_name: str
    contact_method: str
    distributed_markets: List[str]
    obtained_at: str
    source_classification: str
    created_at: str
    updated_at: str
    version: int


class PropertyAttribute(TypedDict):
    id: str
    property_id: str
    source_document_id: str
    field_name: str
    value: str
    proposed_value: Optional[str]
    proposed_status: str
    created_by_user_id: str
    verifier_user_id: Optional[str]
    last_verified_at: str
    attribute_market: str
    from_third_party: bool
    third_party_approved: bool
    revision_index: int
    created_at: str
    updated_at: str
    version: int


class LeaseComparable(TypedDict):
    id: str
    property_id: str
    tenant_name: str
    lease_start: str
    lease_end: str
    escalated_rent_psf: float
    effective_rent_psf: float
    renewal_option: bool
    recorded_at: str
    created_at: str
    updated_at: str
    version: int


class SaleTransaction(TypedDict):
    id: str
    property_id: str
    buyer_name: str
    close_date: str
    gross_sale_price_cents: int
    cap_rate_bps: int
    subordination_deadline: str
    subordination_status: str
    subordinated_at: Optional[str]
    subordinating_case_id: Optional[str]
    rolled_attributions: int
    created_at: str
    updated_at: str
    version: int


class LicensingContract(TypedDict):
    id: str
    subscriber_organization_id: str
    product: str
    licensed_markets: List[str]
    seat_count: int
    annual_fee_cents: int
    monthly_index_fee_cents: int
    auto_renew: bool
    renewal_notice_days: int
    term_start: str
    term_end: str
    renewal_decision: str
    renewal_due_at: str
    status: str
    audit_intensity: str
    created_at: str
    updated_at: str
    version: int


class LicenseSeat(TypedDict):
    id: str
    contract_id: str
    occupant_user_id: Optional[str]
    market: str
    index_tier: str
    monthly_active_days: int
    monthly_unauthorized_markets: List[str]
    distinctive_ip_count: int
    shared_flag: bool
    overage_fee_cents: int
    owner_user_id: Optional[str]
    owner_share_pct: float
    billed_owner_share_pct: float
    access_revoked: bool
    last_usage_cycle: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only ledger entry.
# Carries ONLY id and created_at; no updated_at, no version.
class UsageEvent(TypedDict):
    id: str
    seat_id: str
    user_id: str
    market: str
    event_type: str
    record_count: int
    distinguishing_ip: str
    occurred_at: str
    created_at: str


class EnforcementCase(TypedDict):
    id: str
    organization_id: str
    contract_id: str
    case_type: str
    finding_cents: int
    fee_rate_pct: float
    penalty_cents: int
    escalated_at: Optional[str]
    escalated_from_case_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AnalyticsRun(TypedDict):
    id: str
    market: str
    run_type: str
    adjustment_mode: str
    window_start: str
    window_end: str
    index_value: Optional[float]
    comp_count: int
    mean_effective_rent_psf: Optional[float]
    median_effective_rent_psf: Optional[float]
    selector: str
    forecast_value: Optional[float]
    forecast_due_at: str
    attributed_records_delta: int
    attribution_status: str
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict):
    id: str
    property_id: str
    organization_id: str
    listing_type: str
    monthly_rent_psf: float
    available_sqft: int
    published_at: str
    expires_at: str
    redistributed_markets: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int