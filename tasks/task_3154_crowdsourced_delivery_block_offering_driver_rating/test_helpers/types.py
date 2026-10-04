"""Domain types: entity TypedDicts, status enums and the role enum.

Derived from the PRD's resource definitions. Every resource carries the
standard common fields ``id``, ``created_at``, ``updated_at`` and ``version``.
"""

from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    """The five recognised operational capacities."""

    ANONYMOUS = "Anonymous"
    DRIVER = "Driver"
    STATION_OPS = "StationOps"
    PLATFORM_ADMIN = "PlatformAdmin"
    APPEALS_REVIEWER = "AppealsReviewer"


# ---------------------------------------------------------------------------
# Status / state enumerations
# ---------------------------------------------------------------------------

class DriverStatus(str, Enum):
    APPLIED = "APPLIED"
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


class RatingTier(str, Enum):
    STANDARD = "STANDARD"
    PLUS = "PLUS"
    PREMIER = "PREMIER"


class ScreeningStatus(str, Enum):
    INITIATED = "INITIATED"
    IN_REVIEW = "IN_REVIEW"
    CLEARED = "CLEARED"
    FAILED = "FAILED"


class VehicleClass(str, Enum):
    SEDAN = "SEDAN"
    SUV = "SUV"
    VAN = "VAN"


class InsuranceStatus(str, Enum):
    NONE = "NONE"
    ATTESTED = "ATTESTED"
    EXPIRED = "EXPIRED"


class VehicleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class BlockStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class OfferStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    CHECKED_IN = "CHECKED_IN"
    ROUTE_ASSIGNED = "ROUTE_ASSIGNED"
    IN_DELIVERY = "IN_DELIVERY"
    COMPLETED = "COMPLETED"
    FORFEITED = "FORFEITED"
    NO_SHOW = "NO_SHOW"


class ForfeitCause(str, Enum):
    DRIVER_INITIATED = "DRIVER_INITIATED"
    SYSTEM_DEACTIVATION = "SYSTEM_DEACTIVATION"


class PackageStatus(str, Enum):
    LOADED = "LOADED"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    DELIVERY_FAILED = "DELIVERY_FAILED"
    RETURNED_TO_STATION = "RETURNED_TO_STATION"


class RatingEventType(str, Enum):
    COMPLETION_SCORE = "COMPLETION_SCORE"


class PayStatementStatus(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class AppealStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    EVIDENCE_REQUESTED = "EVIDENCE_REQUESTED"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all resources carry the full common-field set)
# ---------------------------------------------------------------------------

class Station(TypedDict):
    id: str
    name: str
    zone_code: str
    surge_enabled: bool
    pay_liabilities_cents: int
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict):
    id: str
    legal_name: str
    email: str
    status: str
    rating_tier: str
    rating_score_x100: int
    lifetime_rating_x100: int
    reliability_score_bp: int
    created_at: str
    updated_at: str
    version: int


class BackgroundScreening(TypedDict):
    id: str
    driver_id: str
    status: str
    failure_reason: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    driver_id: str
    vin: str
    vehicle_class: str
    insurance_expires_on: Optional[str]
    insurance_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryBlock(TypedDict):
    id: str
    station_id: str
    starts_at: str
    ends_at: str
    required_vehicle_class: str
    base_pay_cents: int
    surge_multiplier_bp: int
    estimated_pay_cents: int
    status: str
    assigned_driver_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BlockOffer(TypedDict):
    id: str
    block_id: str
    driver_id: str
    tier_floor: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BlockAssignment(TypedDict):
    id: str
    block_id: str
    driver_id: str
    offer_id: Optional[str]
    vehicle_id: str
    status: str
    surge_multiplier_snapshot_bp: int
    tier_at_accept: str
    provisional_pay_cents: int
    check_in_at: Optional[str]
    forfeited_at: Optional[str]
    no_show_at: Optional[str]
    forfeit_cause: Optional[str]
    strike_reversed: bool
    created_at: str
    updated_at: str
    version: int


class Package(TypedDict):
    id: str
    assignment_id: str
    tracking_code: str
    billable_weight_kg: float
    promised_by: str
    status: str
    delivered_at: Optional[str]
    photo_url: Optional[str]
    photo_gps_tagged: Optional[bool]
    photo_compliant: Optional[bool]
    on_time_delivery: Optional[bool]
    failure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RatingEvent(TypedDict):
    id: str
    driver_id: str
    assignment_id: str
    event_type: str
    points: int
    event_at: str
    created_at: str
    updated_at: str
    version: int


class PayStatement(TypedDict):
    id: str
    assignment_id: str
    status: str
    gross_cents: int
    tier_bonus_cents: int
    surcharges_cents: int
    penalties_cents: int
    final_pay_cents: int
    tier_applied: str
    settled_at: Optional[str]
    voided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    driver_id: str
    reason: str
    status: str
    evidence_count: int
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
