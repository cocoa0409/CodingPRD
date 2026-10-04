"""Domain types: entity shapes, status enumerations, and the role enumeration.

Two families of resource shapes exist: mutable resources carry the full common
field set (``id``, ``created_at``, ``updated_at``, ``version``), while the four
immutable-leaf records (screen assignments, shifts, trivia entries, fantasy
entries) carry only ``id`` and ``created_at``.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ─── Enumerations ────────────────────────────────────────────────────────────


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    VENUE_MANAGER = "VenueManager"
    HOST = "Host"
    SERVER = "Server"
    SCHEDULER = "Scheduler"


class EventKind(str, Enum):
    BASE = "BASE"
    OVERLAY = "OVERLAY"
    PPV = "PPV"


class League(str, Enum):
    FF_NFL = "FF_NFL"
    FF_NBA = "FF_NBA"
    MLB = "MLB"
    NHL = "NHL"
    NCAA = "NCAA"
    MMA = "MMA"
    BOXING = "BOXING"
    ENTERTAINMENT = "ENTERTAINMENT"


class EventStatus(str, Enum):
    INGESTED = "INGESTED"
    CANCELLED = "CANCELLED"


class LicenseStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ZonePosture(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    BLACKOUT_LOCKED = "BLACKOUT_LOCKED"


class WaitlistStatus(str, Enum):
    WAITING = "WAITING"
    CALLED = "CALLED"
    SEATED = "SEATED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class CheckKind(str, Enum):
    REGULAR = "REGULAR"
    PPV = "PPV"


class CheckStatus(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class OrderLineKind(str, Enum):
    TRADITIONAL = "TRADITIONAL"
    BONELESS = "BONELESS"


class OrderLineStatus(str, Enum):
    OPEN = "OPEN"
    VOID = "VOID"


class StaffingPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    LOCKED = "LOCKED"


class ShiftRole(str, Enum):
    FOH = "FOH"
    BOH = "BOH"


class TriviaSessionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"


class FantasyContestStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


# ─── Entity shapes (mutable resources: full common field set) ────────────────


class Venue(TypedDict, total=False):
    id: str
    name: str
    market_zip: str
    capacity_seats: int
    wing_cost_cents_per_lb: int
    volatility_score: float
    created_at: str
    updated_at: str
    version: int


class Event(TypedDict, total=False):
    id: str
    kind: str
    league: str
    title: str
    home_market_zip: str
    expected_attendance: int
    lift_pct: Optional[float]
    status: str
    scheduled_start: str
    scheduled_end: str
    created_at: str
    updated_at: str
    version: int


class BroadcastLicense(TypedDict, total=False):
    id: str
    venue_id: str
    league: str
    blackout_radius_miles: Optional[int]
    fee_per_head_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Zone(TypedDict, total=False):
    id: str
    venue_id: str
    name: str
    screen_ids: List[str]
    primary_event_id: Optional[str]
    posture: str
    created_at: str
    updated_at: str
    version: int


class Guest(TypedDict, total=False):
    id: str
    venue_id: str
    name: str
    phone: str
    no_show_count: int
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict, total=False):
    id: str
    venue_id: str
    guest_id: str
    party_size: int
    status: str
    called_at: Optional[str]
    kickoff_override: bool
    created_at: str
    updated_at: str
    version: int


class Check(TypedDict, total=False):
    id: str
    venue_id: str
    guest_id: str
    party_size: int
    guest_count: int
    event_id: Optional[str]
    kind: str
    status: str
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    check_id: str
    kind: str
    portion_count: int
    unit_price_cents: int
    line_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PromoRule(TypedDict, total=False):
    id: str
    day_of_week: int
    wing_kind: str
    promo_price_cents_per_10: int
    portion_size: int
    start_date: str
    end_date: str
    created_at: str
    updated_at: str
    version: int


class StaffingPlan(TypedDict, total=False):
    id: str
    venue_id: str
    name: str
    status: str
    foh_required: int
    boh_required: int
    created_at: str
    updated_at: str
    version: int


class TriviaSession(TypedDict, total=False):
    id: str
    venue_id: str
    title: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FantasyContest(TypedDict, total=False):
    id: str
    venue_id: str
    entry_fee_cents: int
    rake_pct: float
    prize_structure: List[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class PpvEvent(TypedDict, total=False):
    id: str
    venue_id: str
    event_id: str
    commercial_fee_cents: int
    cover_charge_cents: int
    capacity_posture_cents: int
    created_at: str
    updated_at: str
    version: int


# ─── Immutable-leaf records (only id + created_at are system-managed) ────────


class ScreenAssignment(TypedDict, total=False):
    id: str
    zone_id: str
    event_id: str
    screen_id: str
    audio_enabled: bool
    created_at: str


class Shift(TypedDict, total=False):
    id: str
    plan_id: str
    role: str
    start_time: str
    end_time: str
    headcount: int
    expected_covers: int
    created_at: str


class TriviaEntry(TypedDict, total=False):
    id: str
    session_id: str
    guest_id: str
    points: int
    correct_count: int
    consecutive_correct: int
    created_at: str


class FantasyEntry(TypedDict, total=False):
    id: str
    contest_id: str
    guest_id: str
    lineup: Dict[str, Any]
    prize_cents: int
    created_at: str
