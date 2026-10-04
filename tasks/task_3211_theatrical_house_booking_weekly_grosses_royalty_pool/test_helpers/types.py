"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    HOUSE_MANAGER = "HouseManager"
    COMPANY_REP = "CompanyRep"
    BOX_OFFICE_AGENT = "BoxOfficeAgent"


class SizeClass(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class BookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    EVICTED = "EVICTED"
    MAINTENANCE_HOLD = "MAINTENANCE_HOLD"
    DONE = "DONE"


class LicenseAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class WeeklyGrossReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class StopNoticeStatus(str, Enum):
    OPEN = "OPEN"
    DISCHARGED = "DISCHARGED"
    EXECUTED = "EXECUTED"


class CapitalProjectStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TicketOrderStatus(str, Enum):
    SOLD = "SOLD"
    REFUNDED = "REFUNDED"


class ProductionCompany(TypedDict, total=False):
    id: str
    name: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class Theatre(TypedDict, total=False):
    id: str
    name: str
    capacity: int
    size_class: str
    is_landmark: bool
    base_weekly_rent_cents: int
    created_at: str
    updated_at: str
    version: int


class Production(TypedDict, total=False):
    id: str
    company_id: str
    title: str
    required_size_class: str
    required_loadin_hours: int
    required_loadout_hours: int
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict, total=False):
    id: str
    production_id: str
    theatre_id: str
    loadin_start: str
    run_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LicenseAgreement(TypedDict, total=False):
    id: str
    booking_id: str
    weekly_rent_cents: int
    stop_clause_weekly_floor_cents: int
    stop_clause_consecutive_weeks: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RoyaltyParticipant(TypedDict, total=False):
    id: str
    production_id: str
    participant_name: str
    royalty_points: int
    pool_eligible: bool
    fixed_royalty_cents: int
    created_at: str
    updated_at: str
    version: int


class DiscountCode(TypedDict, total=False):
    id: str
    production_id: str
    code: str
    percent_off: float
    active: bool
    created_at: str
    updated_at: str
    version: int


class TicketOrder(TypedDict, total=False):
    id: str
    booking_id: str
    performance_date: str
    ticket_count: int
    is_group_sale: bool
    discount_code_id: Optional[str]
    dynamic_pricing_factor: float
    face_value_cents: int
    status: str
    computed_gross_cents: int
    refunded: bool
    created_at: str
    updated_at: str
    version: int


class WeeklyGrossReport(TypedDict, total=False):
    id: str
    booking_id: str
    week_start: str
    week_end: str
    status: str
    gross_cents: int
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict, total=False):
    id: str
    report_id: str
    booking_id: str
    house_expenses_cents: int
    crew_cost_cents: int
    theatre_share_cents: int
    weekly_operating_profit_cents: int
    royalty_pool_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StopNotice(TypedDict, total=False):
    id: str
    booking_id: str
    consecutive_under_floor_weeks: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CapitalProject(TypedDict, total=False):
    id: str
    theatre_id: str
    description: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict, total=False):
    id: str
    booking_id: str
    crew_size: int
    engaged_at: str
    created_at: str
    updated_at: str
    version: int
