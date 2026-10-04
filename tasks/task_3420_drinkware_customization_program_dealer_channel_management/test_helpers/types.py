"""Domain types: entity TypedDicts, status enums, role enum.

All entities carry the common system fields (id, created_at, updated_at,
version) per PRD section 2.5. Fields the PRD describes as "null until <event>"
are typed Optional.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD section 2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CHANNEL_MANAGER = "ChannelManager"
    FIELD_INSPECTOR = "FieldInspector"
    DEALER = "Dealer"
    BUYER = "Buyer"
    PREPRESS_TECH = "PrepressTech"
    PRODUCTION_LEAD = "ProductionLead"
    WARRANTY_AGENT = "WarrantyAgent"
    CUSTOMER_CARE = "CustomerCare"


# ---------------------------------------------------------------------------
# Dealer domain enums
# ---------------------------------------------------------------------------
class DealerStatus(str, Enum):
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class DealerTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIER = "PREMIER"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VETTING = "VETTING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class InspectionStatus(str, Enum):
    UNSCHEDULED = "UNSCHEDULED"
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class DocsStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Enforcement enums
# ---------------------------------------------------------------------------
class CaseStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    ESCALATED_LEGAL = "ESCALATED_LEGAL"
    CONFIRMED_VIOLATION = "CONFIRMED_VIOLATION"
    DISMISSED = "DISMISSED"
    OVERTURNED = "OVERTURNED"


class Marketplace(str, Enum):
    AMAZON = "AMAZON"
    EBAY = "EBAY"
    WALMART = "WALMART"
    OTHER = "OTHER"


class InfractionCategory(str, Enum):
    MAP_VIOLATION = "MAP_VIOLATION"
    UNAUTHORIZED_MARKETPLACE = "UNAUTHORIZED_MARKETPLACE"
    BRAND_STANDARD = "BRAND_STANDARD"
    CHANNEL_DIVERSION = "CHANNEL_DIVERSION"


class InfractionState(str, Enum):
    NONE = "NONE"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    OVERTURNED = "OVERTURNED"


# ---------------------------------------------------------------------------
# Catalog enums
# ---------------------------------------------------------------------------
class ProductCategory(str, Enum):
    HARD_COOLER = "HARD_COOLER"
    SOFT_GOOD = "SOFT_GOOD"
    DRINKWARE = "DRINKWARE"


class ProductLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class DropType(str, Enum):
    STANDARD = "STANDARD"
    LIMITED_EDITION = "LIMITED_EDITION"


class DropStatus(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    ALLOCATION_OPEN = "ALLOCATION_OPEN"
    ALLOCATION_LOCKED = "ALLOCATION_LOCKED"
    LIVE = "LIVE"
    CLOSED = "CLOSED"


class AllocationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ALLOCATED = "ALLOCATED"
    EXPIRED = "EXPIRED"
    FORFEITED = "FORFEITED"


class ForfeitReason(str, Enum):
    DEALER_CHOICE = "DEALER_CHOICE"
    DEALER_SUSPENDED = "DEALER_SUSPENDED"
    DEALER_TERMINATED = "DEALER_TERMINATED"


# ---------------------------------------------------------------------------
# Customization order enums
# ---------------------------------------------------------------------------
class BuyerType(str, Enum):
    CORPORATE = "CORPORATE"
    INDIVIDUAL = "INDIVIDUAL"


class PrintTechnology(str, Enum):
    LASER = "LASER"
    PAD = "PAD"


class OrderState(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class ArtworkStatus(str, Enum):
    NO_ART = "NO_ART"
    PROOF_SUBMITTED = "PROOF_SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    ART_APPROVED = "ART_APPROVED"
    PROOF_EXHAUSTED = "PROOF_EXHAUSTED"


class ScheduleStatus(str, Enum):
    UNSCHEDULED = "UNSCHEDULED"
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    IN_PRODUCTION = "IN_PRODUCTION"
    COMPLETE = "COMPLETE"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"


class ReturnStatus(str, Enum):
    NONE = "NONE"
    RETURN_REQUESTED = "RETURN_REQUESTED"
    RETURN_DENIED = "RETURN_DENIED"
    RETURN_SETTLED = "RETURN_SETTLED"


class ReturnReason(str, Enum):
    DEFECT = "DEFECT"
    ARTWORK_MISMATCH = "ARTWORK_MISMATCH"
    BUYERS_REMORSE = "BUYERS_REMORSE"


class ReturnResolution(str, Enum):
    REMAKE = "REMAKE"
    PARTIAL_CREDIT = "PARTIAL_CREDIT"
    FULL_REFUND = "FULL_REFUND"


class ReservationStatus(str, Enum):
    NONE = "NONE"
    HELD = "HELD"
    WAITLISTED = "WAITLISTED"
    CONFIRMED = "CONFIRMED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class QuoteVariant(str, Enum):
    NONE = "NONE"
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class ProofStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    SUPERSEDED = "SUPERSEDED"


class SlotStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# Warranty enums
# ---------------------------------------------------------------------------
class ClaimSource(str, Enum):
    DTC = "DTC"
    DEALER = "DEALER"


class WarrantyComponent(str, Enum):
    LID = "LID"
    INSULATION = "INSULATION"
    HARDWARE = "HARDWARE"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED_REPAIR = "APPROVED_REPAIR"
    APPROVED_REPLACEMENT = "APPROVED_REPLACEMENT"
    DENIED = "DENIED"


class ReplacementResolution(str, Enum):
    SAME_COLORWAY = "SAME_COLORWAY"
    NEAREST_AVAILABLE = "NEAREST_AVAILABLE"
    CREDIT_EQUIVALENT = "CREDIT_EQUIVALENT"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all carry id / created_at / updated_at / version)
# ---------------------------------------------------------------------------
class Dealer(TypedDict):
    id: str
    legal_name: str
    storefront_address: str
    region_code: str
    tier: str
    credit_limit_cents: int
    sell_through_pct: float
    tenure_years: int
    status: str
    storefront_verified: bool
    brand_presentation_score: int
    infraction_points: int
    outstanding_balance_cents: int
    allocation_score: float
    created_at: str
    updated_at: str
    version: int


class DealerApplication(TypedDict):
    id: str
    dealer_id: str
    has_physical_storefront: bool
    storefront_sqft: int
    document_refs: List[str]
    status: str
    inspection_status: str
    docs_status: str
    inspector_user_id: Optional[str]
    inspection_window_start: Optional[str]
    inspection_window_end: Optional[str]
    brand_presentation_score: Optional[int]
    inspection_recorded_by: Optional[str]
    docs_reviewed_by: Optional[str]
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EnforcementCase(TypedDict):
    id: str
    marketplace: str
    seller_handle: str
    listing_url: str
    matched_dealer_id: Optional[str]
    status: str
    infraction_category: Optional[str]
    infraction_points: int
    infraction_issued_at: Optional[str]
    infraction_expires_at: Optional[str]
    infraction_state: str
    resolution_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductLine(TypedDict):
    id: str
    name: str
    category: str
    base_sku: str
    base_custom_price_cents: int
    map_price_cents: int
    min_custom_quantity: int
    warranty_months_lid: int
    warranty_months_insulation: int
    warranty_months_hardware: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ColorwayDrop(TypedDict):
    id: str
    product_line_id: str
    color_name: str
    pantone_code: str
    drop_type: str
    total_units: int
    dtc_reserved_units: int
    dealer_unit_price_cents: int
    allocation_opens_at: str
    allocation_closes_at: str
    go_live_at: str
    sales_end_at: str
    status: str
    dealer_committed_units: int
    warranty_reserved_units: int
    unallocated_units: int
    created_at: str
    updated_at: str
    version: int


class LaunchAllocation(TypedDict):
    id: str
    dealer_id: str
    drop_id: str
    requested_units: int
    unit_price_cents: int
    allocated_units: int
    status: str
    forfeit_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CustomizationOrder(TypedDict):
    id: str
    buyer_type: str
    buyer_ref: str
    product_line_id: str
    colorway_drop_id: str
    quantity: int
    declared_color_count: int
    declared_placement_count: int
    print_technology: str
    requested_ship_date: str
    order_state: str
    artwork_status: str
    proof_round: int
    schedule_status: str
    payment_status: str
    return_status: str
    return_reason: Optional[str]
    return_resolution: Optional[str]
    affected_unit_count: Optional[int]
    slot_id: Optional[str]
    reservation_status: str
    reserved_minutes: Optional[int]
    quote_variant: str
    peak_applied: Optional[bool]
    provisional_quote_cents: Optional[int]
    final_quote_cents: Optional[int]
    cancellation_fee_cents: Optional[int]
    refund_cents: Optional[int]
    qc_fail_count: int
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ArtworkProof(TypedDict):
    id: str
    order_id: str
    artwork_file_ref: str
    color_count: int
    placement_count: int
    pantone_codes: List[str]
    round_number: int
    status: str
    review_notes: Optional[str]
    submitted_by: str
    created_at: str
    updated_at: str
    version: int


class PrintSlot(TypedDict):
    id: str
    station_code: str
    technology: str
    window_start: str
    window_end: str
    capacity_minutes: int
    peak_overlap: bool
    booked_minutes: int
    available_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    claim_source: str
    dealer_id: Optional[str]
    buyer_ref: Optional[str]
    order_id: Optional[str]
    product_line_id: Optional[str]
    serial_number: str
    component: str
    failure_description: str
    purchase_date: Optional[str]
    filed_at: str
    warranty_anchor_at: str
    warranty_expires_at: str
    fraud_flag: bool
    replacement_colorway_resolution: Optional[str]
    credit_equivalent_cents: Optional[int]
    status: str
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
