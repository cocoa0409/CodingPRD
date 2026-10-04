"""Domain types: entity row TypedDicts, status enums, and the role enum.

Every persisted resource carries ``id`` and ``created_at`` plus ``updated_at``
and an integer ``version`` that increments on every mutation.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    """The five declared roles."""

    CLUB_ADMIN = "ClubAdmin"
    SCHOOL_ADMIN = "SchoolAdmin"
    TEACHER = "Teacher"
    PARENT = "Parent"
    DONOR = "Donor"


class GradeBand(str, Enum):
    K_2 = "K_2"
    G3_5 = "G3_5"
    G6_8 = "G6_8"


class TitleFormat(str, Enum):
    HARDCOVER = "HARDCOVER"
    PAPERBACK = "PAPERBACK"
    CLUB_PAPERBACK = "CLUB_PAPERBACK"


class SchoolPosture(str, Enum):
    NORMAL = "NORMAL"
    RESTRICTED = "RESTRICTED"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PromotionKind(str, Enum):
    BONUS_POINTS = "BONUS_POINTS"
    TITLE_INCENTIVE = "TITLE_INCENTIVE"


class PromotionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class FlyerCycleStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CLOSED = "CLOSED"


class ClassOrderStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    CANCELLED = "CANCELLED"


class ShipStatus(str, Enum):
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    SHIPPED = "SHIPPED"


class PointsStatus(str, Enum):
    UNAWARDED = "UNAWARDED"
    AWARDED = "AWARDED"
    CLAWED_BACK = "CLAWED_BACK"


class OrderLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BACKORDERED = "BACKORDERED"
    CANCELLED = "CANCELLED"


class SubmittedBy(str, Enum):
    PARENT_ONLINE = "PARENT_ONLINE"
    TEACHER = "TEACHER"


class BookFairStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DonationRequestStatus(str, Enum):
    OPEN = "OPEN"
    MATCHED = "MATCHED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class RedemptionKind(str, Enum):
    BOOK = "BOOK"
    SUPPLY = "SUPPLY"


class RedemptionStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class EnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LedgerEntryType(str, Enum):
    EARN = "EARN"
    REDEEM = "REDEEM"
    EXPIRE = "EXPIRE"
    CLAWBACK = "CLAWBACK"
    ADJUST = "ADJUST"


class LedgerRefType(str, Enum):
    CLASS_ORDER = "CLASS_ORDER"
    REDEMPTION = "REDEMPTION"
    OPS_RUN = "OPS_RUN"
    MANUAL = "MANUAL"


class School(TypedDict, total=False):
    id: str
    name: str
    address: str
    low_income_program: bool
    posture: str
    active_fair_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Teacher(TypedDict, total=False):
    id: str
    school_id: str
    full_name: str
    email: str
    grade_band: str
    points_balance: int
    points_earned_total: int
    points_redeemed_total: int
    points_expired_total: int
    donated_books_received: int
    created_at: str
    updated_at: str
    version: int


class Title(TypedDict, total=False):
    id: str
    isbn: str
    name: str
    format: str
    grade_band: str
    base_price_cents: int
    points_cost: int
    rights_holder: str
    royalty_cap_cents: int
    license_status: str
    royalty_accrued_cents: int
    fair_count_used: int
    created_at: str
    updated_at: str
    version: int


class Promotion(TypedDict, total=False):
    id: str
    name: str
    kind: str
    grade_band: Optional[str]
    title_id: Optional[str]
    multiplier_bp: Optional[int]
    bonus_points_per_unit: Optional[int]
    starts_on: str
    ends_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FlyerCycle(TypedDict, total=False):
    id: str
    school_id: str
    month: str
    grade_band: str
    status: str
    offering_count: int
    created_at: str
    updated_at: str
    version: int


class FlyerOffering(TypedDict, total=False):
    id: str
    cycle_id: str
    title_id: str
    flyer_price_cents: int
    fair_overlap: bool
    created_at: str
    updated_at: str
    version: int


class ClassOrder(TypedDict, total=False):
    id: str
    cycle_id: str
    teacher_id: str
    status: str
    ship_status: str
    points_status: str
    subtotal_cents: int
    rewardable_subtotal_cents: int
    discount_cents: int
    net_total_cents: int
    shipping_fee_cents: int
    awarded_base_points: int
    awarded_bonus_points: int
    awarded_total_points: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    class_order_id: str
    offering_id: str
    student_name: str
    submitted_by: str
    qty: int
    unit_price_cents: int
    fair_overlap: bool
    donation_funded: bool
    status: str
    points_earned: int
    created_at: str
    updated_at: str
    version: int


class BookFair(TypedDict, total=False):
    id: str
    school_id: str
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FairTitle(TypedDict, total=False):
    id: str
    fair_id: str
    title_id: str
    created_at: str
    updated_at: str
    version: int


class DonationRequest(TypedDict, total=False):
    id: str
    school_id: str
    teacher_id: str
    title_id: str
    qty_requested: int
    qty_matched: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Redemption(TypedDict, total=False):
    id: str
    teacher_id: str
    kind: str
    title_id: Optional[str]
    qty: int
    points_cost: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProgramEnrollment(TypedDict, total=False):
    id: str
    school_id: str
    status: str
    enrolled_on: str
    created_at: str
    updated_at: str
    version: int


class PointsLedger(TypedDict, total=False):
    id: str
    teacher_id: str
    entry_type: str
    points: int
    ref_type: str
    ref_id: str
    note: str
    created_at: str
    updated_at: str
    version: int
