"""Domain types for the Sponsorship Inventory & Activation API.

Entity shapes, status enums and the operator role enum, as described in the PRD.
Entities that are written once (a rate-card line and a sponsor survey) carry only
``id`` and ``created_at`` -- they have neither ``updated_at`` nor ``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Operator roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PROPERTY_ADMIN = "PropertyAdmin"
    SPONSORSHIP_SELLER = "SponsorshipSeller"
    CONTRACT_APPROVER = "ContractApprover"
    ACTIVATION_MANAGER = "ActivationManager"
    PERFORMANCE_AUDITOR = "PerformanceAuditor"
    SPONSOR_CONTACT = "SponsorContact"


# --------------------------------------------------------------------------
# Enumerated vocabularies
# --------------------------------------------------------------------------
class SportCode(str, Enum):
    FOOTBALL = "FOOTBALL"
    BASKETBALL = "BASKETBALL"
    SOCCER = "SOCCER"
    HOCKEY = "HOCKEY"
    BASEBALL = "BASEBALL"


class PropertyStatus(str, Enum):
    PLANNING = "PLANNING"
    SELLING = "SELLING"
    IN_SEASON = "IN_SEASON"
    CLOSED = "CLOSED"


class RateCardStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class AssetClass(str, Enum):
    SIGNAGE = "SIGNAGE"
    DIGITAL_BOARD = "DIGITAL_BOARD"
    MEDIA_SPOT = "MEDIA_SPOT"
    HOSPITALITY = "HOSPITALITY"
    IP_RIGHTS = "IP_RIGHTS"
    ACTIVATION_SPACE = "ACTIVATION_SPACE"


class InventoryAssetStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class SponsorCategory(str, Enum):
    BEVERAGE = "BEVERAGE"
    AUTOMOTIVE = "AUTOMOTIVE"
    FINANCIAL = "FINANCIAL"
    TELECOM = "TELECOM"
    APPAREL = "APPAREL"
    TECH = "TECH"


class SponsorStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    CHURNED = "CHURNED"


class RenewalBand(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    COUNTERSIGNED = "COUNTERSIGNED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    TERMINATED = "TERMINATED"


class FulfillmentStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    FULFILLED = "FULFILLED"
    SHORTFALL = "SHORTFALL"


class ExclusivityScope(str, Enum):
    NONE = "NONE"
    CATEGORY = "CATEGORY"


class InKindCategory(str, Enum):
    MEDIA_TRADE = "MEDIA_TRADE"
    PRODUCT = "PRODUCT"
    SERVICES = "SERVICES"
    TICKETS = "TICKETS"


class EntitlementStatus(str, Enum):
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    FULFILLED = "FULFILLED"
    SHORTFALL = "SHORTFALL"
    WAIVED = "WAIVED"


class BookingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    PREEMPTED = "PREEMPTED"


class ProofState(str, Enum):
    NONE = "NONE"
    PENDING_REVIEW = "PENDING_REVIEW"
    VERIFIED = "VERIFIED"
    DEFICIENT = "DEFICIENT"


class EvidenceType(str, Enum):
    PHOTO = "PHOTO"
    IMPRESSIONS = "IMPRESSIONS"
    SOCIAL = "SOCIAL"


class ProofStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class StaffMemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class StaffAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    CHECKED_IN = "CHECKED_IN"
    NO_SHOW = "NO_SHOW"
    RELEASED = "RELEASED"


class RenewalIntent(str, Enum):
    NO = "NO"
    MAYBE = "MAYBE"
    YES = "YES"


class ReportBasis(str, Enum):
    VERIFIED = "VERIFIED"
    GROSS = "GROSS"


ASSET_CLASSES = [c.value for c in AssetClass]
PROPERTY_STATUSES = [s.value for s in PropertyStatus]
CONTRACT_STATUSES = [s.value for s in ContractStatus]
FULFILLMENT_STATUSES = [s.value for s in FulfillmentStatus]
ENTITLEMENT_STATUSES = [s.value for s in EntitlementStatus]
BOOKING_STATUSES = [s.value for s in BookingStatus]
PROOF_STATES = [s.value for s in ProofState]


# --------------------------------------------------------------------------
# Entity shapes -- resources carrying id/created_at/updated_at/version
# --------------------------------------------------------------------------
class Property(TypedDict):
    id: str
    name: str
    sport_code: str
    season_year: int
    season_start: str
    season_end: str
    status: str
    seasonality_index: float
    inventory_target_value_cents: int
    committed_gross_value_cents: int
    delivered_media_value_cents: int
    sellout_pct: float
    created_at: str
    updated_at: str
    version: int


class RateCard(TypedDict):
    id: str
    property_id: str
    label: str
    effective_year: int
    status: str
    published_at: Optional[str]
    superseded_by_rate_card_id: Optional[str]
    line_count: int
    created_at: str
    updated_at: str
    version: int


class InventoryAsset(TypedDict):
    id: str
    property_id: str
    name: str
    asset_class: str
    capacity_units: int
    changeover_buffer_minutes: int
    requires_staffing: bool
    min_staff_count: int
    status: str
    reserved_units_total: int
    created_at: str
    updated_at: str
    version: int


class Sponsor(TypedDict):
    id: str
    name: str
    category: str
    contact_email: str
    status: str
    renewal_likelihood_score: float
    renewal_band: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    sponsor_id: str
    property_id: str
    rate_card_id: Optional[str]
    status: str
    fulfillment_status: str
    term_start: str
    term_end: str
    exclusivity_scope: str
    in_kind_declared_value_cents: int
    in_kind_category: str
    gross_entitlement_value_cents: int
    volume_discount_pct: float
    cash_value_cents: int
    in_kind_recognized_value_cents: int
    total_recognized_value_cents: int
    delivered_media_value_cents: int
    makegood_credit_cents: int
    revision_round: int
    submitted_by_user_id: Optional[str]
    countersigned_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Entitlement(TypedDict):
    id: str
    contract_id: str
    inventory_asset_id: str
    clause_ref: str
    asset_class: str
    promised_units: int
    unit_value_cents: int
    gross_value_cents: int
    delivered_units: int
    delivery_pct: float
    status: str
    makegood_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class AssetBooking(TypedDict):
    id: str
    entitlement_id: str
    inventory_asset_id: str
    window_start: str
    window_end: str
    units_booked: int
    status: str
    proof_state: str
    verified_impressions: int
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProofOfPerformance(TypedDict):
    id: str
    asset_booking_id: str
    evidence_type: str
    measured_value: int
    media_uri: Optional[str]
    status: str
    captured_by_user_id: str
    adjudicated_by_user_id: Optional[str]
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict):
    id: str
    full_name: str
    hourly_rate_cents: int
    status: str
    scheduled_minutes: int
    created_at: str
    updated_at: str
    version: int


class StaffAssignment(TypedDict):
    id: str
    asset_booking_id: str
    staff_member_id: str
    shift_start: str
    shift_end: str
    role_label: str
    status: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Write-once resources -- id and created_at only, never updated_at or version
# --------------------------------------------------------------------------
class RateCardLine(TypedDict):
    id: str
    rate_card_id: str
    asset_class: str
    base_unit_price_cents: int
    tier_breaks: List[dict]
    exclusivity_multiplier: float
    created_at: str


class SponsorSurvey(TypedDict):
    id: str
    contract_id: str
    satisfaction_score: int
    activation_quality_score: int
    reporting_quality_score: int
    renewal_intent: str
    submitted_by_user_id: str
    composite_score: float
    created_at: str


class RoiReport(TypedDict):
    contract_id: str
    basis: str
    media_value_cents: int
    impressions_total: int
    roi_ratio: float
    roo_attainment_pct: float
    cost_per_thousand_impressions_cents: Optional[float]
    makegood_credit_cents: int
