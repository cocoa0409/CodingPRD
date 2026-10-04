"""Domain types: entity TypedDicts, status enums, role enum for the
collector-vehicle agreed-value coverage API."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    MEMBER = "Member"
    UNDERWRITER = "Underwriter"
    APPRAISER = "Appraiser"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    CLUB_COORDINATOR = "ClubCoordinator"
    PLATFORM_ADMIN = "PlatformAdmin"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class DrivingRecordStatus(str, Enum):
    CLEAN = "CLEAN"
    MINOR_VIOLATIONS = "MINOR_VIOLATIONS"
    MAJOR_VIOLATIONS = "MAJOR_VIOLATIONS"


class VehicleStatus(str, Enum):
    REGISTERED = "REGISTERED"
    INSURED = "INSURED"
    UNDER_RESTORATION = "UNDER_RESTORATION"
    RETIRED = "RETIRED"


class EligibilityStatus(str, Enum):
    PENDING = "PENDING"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class DocumentationStatus(str, Enum):
    INCOMPLETE = "INCOMPLETE"
    COMPLETE = "COMPLETE"


class VehicleClass(str, Enum):
    ANTIQUE = "ANTIQUE"
    CLASSIC = "CLASSIC"
    MODERN_COLLECTIBLE = "MODERN_COLLECTIBLE"
    EXOTIC = "EXOTIC"


class ConditionGrade(str, Enum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    FAIR = "FAIR"
    PROJECT = "PROJECT"


class StorageType(str, Enum):
    ENCLOSED_GARAGE = "ENCLOSED_GARAGE"
    CARPORT = "CARPORT"
    OUTDOOR = "OUTDOOR"


class PrimaryUse(str, Enum):
    SHOW = "SHOW"
    PLEASURE = "PLEASURE"
    RESTORATION = "RESTORATION"


class PhotoType(str, Enum):
    FRONT = "FRONT"
    REAR = "REAR"
    DRIVER_SIDE = "DRIVER_SIDE"
    PASSENGER_SIDE = "PASSENGER_SIDE"
    INTERIOR = "INTERIOR"
    ENGINE = "ENGINE"
    ODOMETER = "ODOMETER"
    VIN_PLATE = "VIN_PLATE"


class PhotoStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class GuideStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class AppraisalStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"


class ValuationMethod(str, Enum):
    GUIDE_TOOL = "GUIDE_TOOL"
    CERTIFIED_APPRAISAL = "CERTIFIED_APPRAISAL"
    AUCTION_COMPOSITE = "AUCTION_COMPOSITE"


class ValuationStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    STALE = "STALE"


class UsageTier(str, Enum):
    LIMITED = "LIMITED"
    REGULAR = "REGULAR"
    EXTENDED = "EXTENDED"


class PolicyStatus(str, Enum):
    QUOTED = "QUOTED"
    PENDING_DOCUMENTS = "PENDING_DOCUMENTS"
    ACTIVE = "ACTIVE"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUSPENDED = "SUSPENDED"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"


class DriverStatus(str, Enum):
    LISTED = "LISTED"
    REMOVED = "REMOVED"


class EventKind(str, Enum):
    ORDINARY = "ORDINARY"
    CLUB_EVENT = "CLUB_EVENT"
    PARADE = "PARADE"
    EXHIBITION = "EXHIBITION"


class UsageEventStatus(str, Enum):
    RECORDED = "RECORDED"
    REVERSED = "REVERSED"


class RepairShopStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"


class LossType(str, Enum):
    COLLISION = "COLLISION"
    THEFT = "THEFT"
    FIRE = "FIRE"
    VANDALISM = "VANDALISM"
    WEATHER = "WEATHER"


class ClaimStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    REPAIR_AUTHORIZED = "REPAIR_AUTHORIZED"
    TOTAL_LOSS_DECLARED = "TOTAL_LOSS_DECLARED"
    PAID = "PAID"
    CLOSED = "CLOSED"


class SettlementVariant(str, Enum):
    NONE = "NONE"
    REPAIR = "REPAIR"
    TOTAL_LOSS = "TOTAL_LOSS"


class RestorationStage(str, Enum):
    DISASSEMBLY = "DISASSEMBLY"
    BODYWORK = "BODYWORK"
    MECHANICAL = "MECHANICAL"
    FINISH = "FINISH"
    COMPLETE = "COMPLETE"


class RestorationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"


class ClubTier(str, Enum):
    BASIC = "BASIC"
    ENTHUSIAST = "ENTHUSIAST"
    CONCOURS = "CONCOURS"


class ClubMembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"


class ClubEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class RegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CANCELLED = "CANCELLED"


class ServiceType(str, Enum):
    FLATBED_TOW = "FLATBED_TOW"
    BATTERY = "BATTERY"
    FUEL = "FUEL"
    LOCKOUT = "LOCKOUT"


class RoadsideEventStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Member(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    has_daily_driver: bool
    daily_driver_vehicle_desc: Optional[str]
    driving_record_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    member_id: str
    vin: str
    year: int
    make: str
    model: str
    vehicle_class: str
    condition_grade: str
    storage_type: str
    primary_use: str
    eligibility_status: str
    eligibility_reasons: list
    documentation_status: str
    accepted_photo_count: int
    current_valuation_id: Optional[str]
    current_agreed_value_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class VehiclePhoto(TypedDict, total=False):
    id: str
    vehicle_id: str
    photo_type: str
    image_ref: str
    captured_at: str
    status: str
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ValuationGuide(TypedDict, total=False):
    id: str
    edition: str
    effective_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ValuationGuideEntry(TypedDict, total=False):
    id: str
    guide_id: str
    vehicle_class: str
    make: str
    year_min: int
    year_max: int
    base_value_cents: int
    created_at: str
    updated_at: str
    version: int


class Appraisal(TypedDict, total=False):
    id: str
    vehicle_id: str
    appraiser_user_id: str
    appraised_value_cents: int
    appraised_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AuctionResult(TypedDict, total=False):
    id: str
    vehicle_class: str
    make: str
    model: str
    year: int
    sale_price_cents: int
    sale_date: str
    source_name: str
    created_at: str
    updated_at: str
    version: int


class Valuation(TypedDict, total=False):
    id: str
    vehicle_id: str
    method: str
    appraisal_id: Optional[str]
    guide_id: Optional[str]
    computed_value_cents: int
    proposed_agreed_value_cents: int
    final_agreed_value_cents: Optional[int]
    band_override: bool
    status: str
    approved_by_user_id: Optional[str]
    approved_at: Optional[str]
    is_stale: bool
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict, total=False):
    id: str
    member_id: str
    vehicle_id: str
    valuation_id: str
    usage_tier: str
    annual_mileage_allowance: int
    period_start: str
    period_end: str
    agreed_value_cents: int
    endorsement_limit_cents: int
    coverage_limit_cents: int
    premium_cents: int
    billable_miles_used: int
    overage_charge_cents: int
    remaining_allowance_miles: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict, total=False):
    id: str
    policy_id: str
    full_name: str
    license_number: str
    years_licensed: int
    violations_last_3y: int
    is_primary: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class UsageEvent(TypedDict, total=False):
    id: str
    policy_id: str
    reported_miles: int
    event_date: str
    event_kind: str
    billable_miles: int
    overage_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RepairShop(TypedDict, total=False):
    id: str
    name: str
    specialty: str
    hourly_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    policy_id: str
    incident_date: str
    loss_type: str
    description: str
    repair_shop_id: Optional[str]
    estimate_cents: Optional[int]
    salvage_retained: bool
    salvage_value_cents: int
    settlement_variant: str
    payout_cents: Optional[int]
    declared_by_user_id: Optional[str]
    settled_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RestorationProject(TypedDict, total=False):
    id: str
    vehicle_id: str
    policy_id: str
    stage: str
    receipts_total_cents: int
    endorsement_limit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClubMembership(TypedDict, total=False):
    id: str
    member_id: str
    tier: str
    roadside_calls_limit: int
    roadside_calls_used: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClubEvent(TypedDict, total=False):
    id: str
    name: str
    venue: str
    start_date: str
    end_date: str
    capacity: int
    registered_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EventRegistration(TypedDict, total=False):
    id: str
    event_id: str
    member_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RoadsideEvent(TypedDict, total=False):
    id: str
    membership_id: str
    vehicle_id: str
    service_type: str
    event_date: str
    status: str
    created_at: str
    updated_at: str
    version: int
