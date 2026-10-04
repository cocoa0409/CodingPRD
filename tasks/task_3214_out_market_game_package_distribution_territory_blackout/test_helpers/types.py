"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity definitions. Entities described as append-only
evidence (Payment, TerritoryCheck) carry only id + created_at — no
updated_at, no version. All other entities carry the standard quartet
id/created_at/updated_at/version.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    PLATFORM_ADMIN = "PlatformAdmin"
    LEAGUE_OPS = "LeagueOps"
    SUBSCRIBER = "Subscriber"
    VENUE_MANAGER = "VenueManager"
    SUPPORT_AGENT = "SupportAgent"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"


class RightsGrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class SeasonPhase(str, Enum):
    PRE_SALE = "PRE_SALE"
    REGULAR = "REGULAR"
    POST = "POST"


class SlateStatus(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    FINALIZED = "FINALIZED"
    LOCKED = "LOCKED"


class OfferStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class AccountKind(str, Enum):
    RESIDENTIAL = "RESIDENTIAL"
    COMMERCIAL = "COMMERCIAL"


class PlanTier(str, Enum):
    BASE = "BASE"
    PREMIUM = "PREMIUM"
    STUDENT = "STUDENT"


class SubscriptionStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class EntitlementState(str, Enum):
    ENABLED = "ENABLED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class VenueLicenseStatus(str, Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class OccupancyTier(str, Enum):
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


class StudentVerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class VerificationMethod(str, Enum):
    SHEERID = "SHEERID"
    DOCUMENT_REVIEW = "DOCUMENT_REVIEW"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED_REFUND = "APPROVED_REFUND"
    DENIED = "DENIED"
    ESCALATED = "ESCALATED"


class ComplaintCategory(str, Enum):
    BLACKOUT_DISPUTE = "BLACKOUT_DISPUTE"
    BILLING = "BILLING"
    QUALITY = "QUALITY"


class GameEntitlementStatus(str, Enum):
    GRANTED = "GRANTED"
    WITHDRAWN = "WITHDRAWN"
    BLACKED_OUT = "BLACKED_OUT"


class WithdrawnReason(str, Enum):
    NATIONAL_SELECTION = "NATIONAL_SELECTION"
    ENTITLEMENT_REVOKED = "ENTITLEMENT_REVOKED"
    SUBSCRIPTION_CANCELLED = "SUBSCRIPTION_CANCELLED"


class PaymentKind(str, Enum):
    CHARGE = "CHARGE"
    REFUND = "REFUND"


class Verdict(str, Enum):
    AVAILABLE = "AVAILABLE"
    BLACKED_OUT = "BLACKED_OUT"
    NOT_IN_PACKAGE = "NOT_IN_PACKAGE"
    NO_ENTITLEMENT = "NO_ENTITLEMENT"


class OverrideStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESCINDED = "RESCINDED"


class ReasonCode(str, Enum):
    GOODWILL = "GOODWILL"
    SERVICE_OUTAGE = "SERVICE_OUTAGE"
    REGULATORY = "REGULATORY"


class RightsGrant(TypedDict, total=False):
    id: str
    distributor_name: str
    scope: str
    exclusivity: str
    effective_from: str
    effective_until: str
    max_commercial_occupancy_cap: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Season(TypedDict, total=False):
    id: str
    rights_grant_id: str
    label: str
    regular_season_weeks: int
    season_start_date: str
    season_end_date: str
    phase: str
    grace_days: int
    student_discount_pct: int
    created_at: str
    updated_at: str
    version: int


class Market(TypedDict, total=False):
    id: str
    code: str
    name: str
    zip_prefixes: List[str]
    home_team_codes: List[str]
    created_at: str
    updated_at: str
    version: int


class Game(TypedDict, total=False):
    id: str
    season_id: str
    week_index: int
    away_team_code: str
    home_team_code: str
    kickoff_at: str
    home_market_code: str
    created_at: str
    updated_at: str
    version: int


class WeekSlate(TypedDict, total=False):
    id: str
    season_id: str
    week_index: int
    slate_status: str
    national_game_ids: List[str]
    finalized_game_ids: List[str]
    package_game_count: int
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict, total=False):
    id: str
    season_id: str
    plan_tier: str
    base_price_cents: int
    includes_multiview: bool
    includes_companion: bool
    valid_from: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    account_kind: str
    billing_zip: str
    billing_market_code: Optional[str]
    status: str
    commercial_flag_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StudentVerification(TypedDict, total=False):
    id: str
    account_id: str
    institution_name: str
    verification_method: str
    valid_through: str
    status: str
    created_at: str
    updated_at: str
    version: int


class VenueLicense(TypedDict, total=False):
    id: str
    account_id: str
    venue_name: str
    venue_zip: str
    fire_code_occupancy: int
    occupancy_tier: str
    annual_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    account_id: str
    offer_id: str
    season_id: str
    plan_tier: str
    purchase_week_index: int
    price_charged_cents: int
    paid_amount_cents: int
    status: str
    entitlement_state: str
    cancelled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only evidence row: id + created_at only (no updated_at, no version)
class Payment(TypedDict, total=False):
    id: str
    created_at: str
    subscription_id: str
    kind: str
    amount_cents: int
    reason: Optional[str]


# Append-only evidence row: id + created_at only (no updated_at, no version)
class TerritoryCheck(TypedDict, total=False):
    id: str
    created_at: str
    account_id: str
    subscription_id: str
    game_id: str
    device_zip: str
    device_market_code: Optional[str]
    effective_market_code: Optional[str]
    verdict: str
    checked_at: str


class GameEntitlement(TypedDict, total=False):
    id: str
    subscription_id: str
    game_id: str
    week_index: int
    status: str
    withdrawn_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplaintCase(TypedDict, total=False):
    id: str
    account_id: str
    subscription_id: str
    game_id: str
    category: str
    detail: str
    status: str
    refund_amount_cents: int
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EntitlementOverride(TypedDict, total=False):
    id: str
    account_id: str
    game_id: str
    reason_code: str
    created_by: str
    status: str
    created_at: str
    updated_at: str
    version: int
