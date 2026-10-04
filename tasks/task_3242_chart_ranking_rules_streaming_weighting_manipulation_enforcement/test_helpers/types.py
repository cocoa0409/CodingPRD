"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CHART_MANAGER = "ChartManager"
    CHART_OPS = "ChartOps"
    DATA_PROVIDER = "DataProvider"
    LABEL_REP = "LabelRep"
    INVESTIGATOR = "Investigator"


class ChartKind(str, Enum):
    SINGLES = "SINGLES"
    ALBUMS = "ALBUMS"


class ChartScope(str, Enum):
    MAIN = "MAIN"
    GENRE = "GENRE"


class MethodologyVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    FROZEN = "FROZEN"


class ChartWeekStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    COMPUTED = "COMPUTED"
    PUBLISHED = "PUBLISHED"


class ProviderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class FeedKind(str, Enum):
    SALES = "SALES"
    STREAM_ON_DEMAND = "STREAM_ON_DEMAND"
    STREAM_PROGRAMMED = "STREAM_PROGRAMMED"
    AIRPLAY = "AIRPLAY"


class Territory(str, Enum):
    DOMESTIC = "DOMESTIC"
    INTERNATIONAL = "INTERNATIONAL"


class ProductKind(str, Enum):
    TRACK = "TRACK"
    ALBUM = "ALBUM"


class EligibilityPosture(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    DISQUALIFIED = "DISQUALIFIED"


class LabelAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ComponentKind(str, Enum):
    SALES = "SALES"
    STREAM_ON_DEMAND_PAID = "STREAM_ON_DEMAND_PAID"
    STREAM_ON_DEMAND_AD = "STREAM_ON_DEMAND_AD"
    STREAM_PROGRAMMED = "STREAM_PROGRAMMED"
    AIRPLAY = "AIRPLAY"


class ConsumptionReportStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"
    EXCLUDED = "EXCLUDED"


class SaleChannel(str, Enum):
    D2C = "D2C"
    RETAIL = "RETAIL"
    TICKET_BUNDLE = "TICKET_BUNDLE"
    MERCH_BUNDLE = "MERCH_BUNDLE"


class SaleBatchReviewStatus(str, Enum):
    CLEARED = "CLEARED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REJECTED = "REJECTED"


class SignalKind(str, Enum):
    ARTIFICIAL_STREAMING = "ARTIFICIAL_STREAMING"
    BULK_PURCHASE = "BULK_PURCHASE"
    TICKET_BUNDLE_ABUSE = "TICKET_BUNDLE_ABUSE"


class ManipulationSignalStatus(str, Enum):
    OPEN = "OPEN"
    DISMISSED = "DISMISSED"
    ESCALATED = "ESCALATED"


class InvestigationStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class InvestigationFinding(str, Enum):
    DISMISSED = "DISMISSED"
    QUARANTINE_REPORTS = "QUARANTINE_REPORTS"
    DISQUALIFY = "DISQUALIFY"


class ChartEntryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RECURRENT_REMOVED = "RECURRENT_REMOVED"
    RE_ENTERED = "RE_ENTERED"


class GenreDisputeStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_RECLASSIFIED = "RESOLVED_RECLASSIFIED"


class DisputeResolution(str, Enum):
    UPHOLD = "UPHOLD"
    RECLASSIFY = "RECLASSIFY"


class ChartFreezeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"


class Chart(TypedDict, total=False):
    id: str
    chart_code: str
    title: str
    chart_kind: str
    chart_scope: str
    genre_tag: Optional[str]
    current_methodology_version_id: Optional[str]
    recurrent_rule_id: str
    created_at: str
    updated_at: str
    version: int


class MethodologyVersion(TypedDict, total=False):
    id: str
    chart_id: str
    version_label: str
    w_sales: float
    w_on_demand: float
    w_programmed: float
    w_airplay: float
    paid_stream_divisor: int
    ad_stream_divisor: int
    prog_stream_divisor: int
    tea_rate: int
    effective_from: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ChartWeek(TypedDict, total=False):
    id: str
    chart_id: str
    week_index: int
    opens_at: str
    closes_at: str
    reporting_cutoff: str
    status: str
    computed_methodology_version_id: Optional[str]
    holiday_adjusted: bool
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict, total=False):
    id: str
    provider_code: str
    display_name: str
    feed_kind: str
    territory: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AvailabilityPolicy(TypedDict, total=False):
    available_from: str
    available_until: Optional[str]


class TitleProduct(TypedDict, total=False):
    id: str
    upc: str
    title: str
    artist_name: str
    product_kind: str
    genre_tag: str
    release_date: str
    base_price_cents: int
    label_account_id: str
    availability_policy: dict
    eligibility_posture: str
    created_at: str
    updated_at: str
    version: int


class LabelAccount(TypedDict, total=False):
    id: str
    legal_name: str
    account_code: str
    strike_count: int
    account_status: str
    created_at: str
    updated_at: str
    version: int


class RecurrentRule(TypedDict, total=False):
    id: str
    rule_code: str
    max_weeks: int
    min_rank: int
    reentry_min_rank: int
    description: str
    created_at: str
    updated_at: str
    version: int


class ConsumptionReport(TypedDict, total=False):
    id: str
    provider_id: str
    title_product_id: str
    chart_week_id: str
    component_kind: str
    quantity: int
    event_time: str
    file_fingerprint: str
    status: str
    review_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SaleBatch(TypedDict, total=False):
    id: str
    title_product_id: str
    channel: str
    quantity: int
    buyer_key: str
    chart_week_id: str
    countable_units: int
    review_status: str
    created_at: str
    updated_at: str
    version: int


class ManipulationSignal(TypedDict, total=False):
    id: str
    title_product_id: str
    chart_week_id: str
    signal_kind: str
    evidence: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Investigation(TypedDict, total=False):
    id: str
    signal_id: str
    assigned_to: str
    finding: Optional[str]
    notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ChartEntry(TypedDict, total=False):
    id: str
    chart_week_id: str
    title_product_id: str
    points: float
    rank: Optional[int]
    weeks_on_chart: int
    peak_rank: Optional[int]
    entry_status: str
    created_at: str
    updated_at: str
    version: int


class GenreDispute(TypedDict, total=False):
    id: str
    title_product_id: str
    chart_id: str
    filed_by_label_id: str
    claimed_genre: str
    resolution: Optional[str]
    status: str
    reentries_processed: bool
    created_at: str
    updated_at: str
    version: int


class ChartFreeze(TypedDict, total=False):
    id: str
    chart_id: str
    reason: str
    expected_chart_version: int
    resolved_by_methodology_version_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
