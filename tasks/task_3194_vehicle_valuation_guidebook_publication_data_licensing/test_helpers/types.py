"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    VALUATION_ADMIN = "ValuationAdmin"
    DATA_OPS = "DataOps"
    DEALER_PARTNER = "DealerPartner"
    CONSUMER = "Consumer"
    LICENSEE = "Licensee"


class RegionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class SourceStatus(str, Enum):
    PROBATION = "PROBATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SourceType(str, Enum):
    DEALER = "DEALER"
    AUCTION = "AUCTION"
    LENDER = "LENDER"


class ConfigurationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class Segment(str, Enum):
    SEDAN = "SEDAN"
    SUV = "SUV"
    TRUCK = "TRUCK"
    VAN = "VAN"
    COUPE = "COUPE"


class BatchStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class SeriesStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    SUPERSEDED = "SUPERSEDED"


class EditionStatus(str, Enum):
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    WITHDRAWN = "WITHDRAWN"


class ShiftStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RESCINDED = "RESCINDED"


class OfferStatus(str, Enum):
    QUOTED = "QUOTED"
    INSPECTED = "INSPECTED"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"
    VOID = "VOID"


class ConditionTier(str, Enum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class PermittedUse(str, Enum):
    UNDERWRITING = "UNDERWRITING"
    SETTLEMENT = "SETTLEMENT"
    DISPLAY = "DISPLAY"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_ADJUSTED = "RESOLVED_ADJUSTED"
    WITHDRAWN = "WITHDRAWN"


class ReasonCode(str, Enum):
    WRONG_CONDITION = "WRONG_CONDITION"
    STALE_DATA = "STALE_DATA"
    MISSING_OPTIONS = "MISSING_OPTIONS"


class MethodologyStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class OptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class EventType(str, Enum):
    EDITION_READ = "EDITION_READ"
    OFFER_CREATED = "OFFER_CREATED"


# --- Entity TypedDicts ---
# Entities with common fields carry id, created_at, updated_at, version.


class Region(TypedDict, total=False):
    id: str
    region_code: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Source(TypedDict, total=False):
    id: str
    source_type: str
    region_id: str
    status: str
    consecutive_rejections: int
    external_key: str
    name: str
    created_at: str
    updated_at: str
    version: int


class Configuration(TypedDict, total=False):
    id: str
    make: str
    model: str
    year: int
    trim: str
    segment: str
    annual_expected_miles: int
    status: str
    external_key: str
    created_at: str
    updated_at: str
    version: int


class TransactionBatch(TypedDict, total=False):
    id: str
    source_id: str
    submission_ref: str
    items: List[dict]
    status: str
    accepted_count: int
    created_at: str
    updated_at: str
    version: int


class ValuationSeries(TypedDict, total=False):
    id: str
    configuration_id: str
    region_id: str
    effective_from: str
    cadence: str
    status: str
    confidence_score: float
    external_key: str
    created_at: str
    updated_at: str
    version: int


class ValuationEdition(TypedDict, total=False):
    id: str
    series_id: str
    effective_at: str
    reference_price_cents: int
    trade_in_cents: int
    private_party_cents: int
    retail_cents: int
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MarketShift(TypedDict, total=False):
    id: str
    region_id: Optional[str]
    segment: Optional[str]
    effective_at: str
    pct_adjustment: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CashOffer(TypedDict, total=False):
    id: str
    edition_id: str
    offer_amount_cents: int
    funding_dealer_id: str
    consumer_id: str
    mileage: int
    age_years: int
    declared_condition_tier: str
    option_ids: List[str]
    expires_at: str
    status: str
    final_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class LicenseAgreement(TypedDict, total=False):
    id: str
    licensee_ref: str
    permitted_uses: List[str]
    monthly_event_quota: int
    fee_per_event_cents: int
    status: str
    activation_version: int
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict, total=False):
    id: str
    offer_id: str
    reason_code: str
    status: str
    credit_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Methodology(TypedDict, total=False):
    id: str
    version_label: str
    formula_hash: str
    published_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ConditionStandard(TypedDict, total=False):
    id: str
    tier: str
    description: str
    multiplier: float
    created_at: str
    updated_at: str
    version: int


class OptionPackage(TypedDict, total=False):
    id: str
    configuration_id: str
    option_code: str
    credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsumerProfile(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only rows (common_fields: false): only id + created_at ---


class LicenseEvent(TypedDict, total=False):
    id: str
    created_at: str
    agreement_id: str
    event_type: str
    occurred_at: str


class DataCorrection(TypedDict, total=False):
    id: str
    created_at: str
    batch_id: str
    corrected_price_cents: int
    delta_applied: bool


class Snapshot(TypedDict, total=False):
    id: str
    created_at: str
    agreement_id: str
    methodology_version_label: str
    snapshot_version: int
