"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this PRD carry the standard system-managed fields
(id, created_at, updated_at, version) — none are append-only.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    OWNER = "Owner"
    ADMIN = "Admin"
    MEMBER = "Member"
    MINOR = "Minor"
    SYSTEM = "System"


class SubscriptionTier(str, Enum):
    FREE = "FREE"
    PLUS = "PLUS"
    PROTECT = "PROTECT"


class SubscriptionStatus(str, Enum):
    TRIALING = "TRIALING"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class CirclePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class MemberRole(str, Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"
    MINOR = "MINOR"


class ConsentState(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class PrivacyMode(str, Enum):
    PRECISE = "PRECISE"
    BLURRED = "BLURRED"
    HIDDEN = "HIDDEN"


class SamplingProfile(str, Enum):
    HIGH = "HIGH"
    BALANCED = "BALANCED"
    SAVER = "SAVER"


class PlaceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class FixStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED_ACCURACY = "REJECTED_ACCURACY"
    REJECTED_STALE = "REJECTED_STALE"
    REJECTED_CONSENT = "REJECTED_CONSENT"
    RETIRED = "RETIRED"


class MotionContext(str, Enum):
    STILL = "STILL"
    WALKING = "WALKING"
    DRIVING = "DRIVING"
    UNKNOWN = "UNKNOWN"


class AlertEventKind(str, Enum):
    ARRIVAL = "ARRIVAL"
    DEPARTURE = "DEPARTURE"


class AlertStatus(str, Enum):
    PENDING_DWELL = "PENDING_DWELL"
    CONFIRMED = "CONFIRMED"
    SUPPRESSED = "SUPPRESSED"
    CANCELLED = "CANCELLED"


class SuppressedReason(str, Enum):
    PRIVACY_HIDDEN = "PRIVACY_HIDDEN"
    TIER_HISTORY = "TIER_HISTORY"
    DUPLICATE_EVENT = "DUPLICATE_EVENT"


class TripStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ABANDONED = "ABANDONED"


class CrashSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    SEVERE = "SEVERE"


class CrashStatus(str, Enum):
    DETECTED = "DETECTED"
    WELLNESS_PENDING = "WELLNESS_PENDING"
    CONFIRMED_OK = "CONFIRMED_OK"
    ESCALATED = "ESCALATED"
    DISPATCHED = "DISPATCHED"
    RESOLVED = "RESOLVED"
    FALSE_ALARM = "FALSE_ALARM"


class CheckStatus(str, Enum):
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    UNANSWERED = "UNANSWERED"
    CANCELLED = "CANCELLED"


class DispatchStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    STAGED = "STAGED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SubscriptionEventKind(str, Enum):
    TIER_CHANGE = "TIER_CHANGE"
    RENEWAL = "RENEWAL"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    SUSPENDED = "SUSPENDED"
    REACTIVATED = "REACTIVATED"
    CANCELLED = "CANCELLED"
    ASSISTANCE_GRANT = "ASSISTANCE_GRANT"
    ASSISTANCE_CONSUME = "ASSISTANCE_CONSUME"
    IDENTITY_CREDIT_CONSUME = "IDENTITY_CREDIT_CONSUME"


class ConsentScope(str, Enum):
    LOCATION = "LOCATION"
    DRIVING = "DRIVING"
    CRASH = "CRASH"
    FULL = "FULL"


class ConsentAction(str, Enum):
    GRANT = "GRANT"
    REVOKE = "REVOKE"
    EXPIRE = "EXPIRE"


class HoldKind(str, Enum):
    DATA_SHARING_DISCLOSURE = "DATA_SHARING_DISCLOSURE"
    MONETIZATION_OPT_OUT_SWEEP = "MONETIZATION_OPT_OUT_SWEEP"
    MINOR_PRIVACY_AUDIT = "MINOR_PRIVACY_AUDIT"


class HoldStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class Circle(TypedDict, total=False):
    id: str
    name: str
    owner_member_id: str
    subscription_tier: str
    subscription_status: str
    billing_anchor_day: int
    circle_posture: str
    assistance_units_balance: int
    identity_protection_credits: int
    history_retention_days: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    circle_id: str
    display_name: str
    birthdate: str
    role: str
    age_years: int
    consent_state: str
    privacy_mode: str
    sampling_profile: str
    effective_sample_interval_seconds: int
    current_battery_pct: int
    last_known_fix_id: Optional[str]
    tension_flag: bool
    created_at: str
    updated_at: str
    version: int


class Place(TypedDict, total=False):
    id: str
    circle_id: str
    label: str
    center_lat: float
    center_lng: float
    radius_m: int
    accuracy_floor_m: int
    notify_on_arrive: bool
    notify_on_depart: bool
    dwell_bucket_seconds: int
    place_status: str
    created_at: str
    updated_at: str
    version: int


class LocationFix(TypedDict, total=False):
    id: str
    member_id: str
    recorded_at: str
    lat: float
    lng: float
    accuracy_m: float
    speed_mps: float
    battery_pct: int
    phone_in_use: bool
    motion_context: str
    fix_status: str
    place_ids_inside: List[str]
    created_at: str
    updated_at: str
    version: int


class PlaceAlert(TypedDict, total=False):
    id: str
    place_id: str
    member_id: str
    event_kind: str
    alert_status: str
    window_open_fix_id: str
    window_close_fix_id: Optional[str]
    suppressed_reason: Optional[str]
    visible_to_owner: bool
    created_at: str
    updated_at: str
    version: int


class TripReport(TypedDict, total=False):
    id: str
    member_id: str
    started_at: str
    ended_at: str
    trip_status: str
    distance_m: int
    max_speed_mps: float
    speed_event_count: int
    phone_use_event_count: int
    driver_score: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CrashEvent(TypedDict, total=False):
    id: str
    member_id: str
    trip_report_id: str
    detected_at: str
    severity: str
    crash_status: str
    wellness_check_id: str
    dispatch_id: Optional[str]
    false_alarm_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WellnessCheck(TypedDict, total=False):
    id: str
    crash_event_id: str
    check_status: str
    deadline_at: str
    acknowledged_by_member_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EmergencyDispatch(TypedDict, total=False):
    id: str
    crash_event_id: str
    dispatch_status: str
    verification_note: Optional[str]
    staged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubscriptionEvent(TypedDict, total=False):
    id: str
    circle_id: str
    event_kind: str
    from_tier: Optional[str]
    to_tier: Optional[str]
    effective_at: str
    units_delta: int
    billing_period_index: int
    created_at: str
    updated_at: str
    version: int


class ConsentRecord(TypedDict, total=False):
    id: str
    member_id: str
    granted_by_member_id: str
    scope: str
    consent_action: str
    effective_at: str
    monetization_opt_in: bool
    created_at: str
    updated_at: str
    version: int


class ComplianceHold(TypedDict, total=False):
    id: str
    circle_id: str
    hold_kind: str
    hold_status: str
    opened_reason: str
    resolved_by_member_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
