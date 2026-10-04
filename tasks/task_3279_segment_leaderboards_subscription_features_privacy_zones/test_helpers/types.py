"""Domain types for the Segment Leaderboards, Subscription Features & Privacy Zones API.

Entity TypedDicts, status enums, and the role enum. Every entity in this
system carries the full common-field set (id, created_at, updated_at,
version) per the PRD's common-resource-properties section, so every
TypedDict lists all four.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    ATHLETE = "Athlete"
    MODERATOR = "Moderator"
    PLATFORM_ADMIN = "PlatformAdmin"


class AthleteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELETED = "DELETED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    LAPSED = "LAPSED"


class SubscriptionPlan(str, Enum):
    SUMMIT_MONTHLY = "SUMMIT_MONTHLY"
    SUMMIT_ANNUAL = "SUMMIT_ANNUAL"


class PrivacyZoneStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class ActivityStatus(str, Enum):
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    DUPLICATE = "DUPLICATE"
    REJECTED = "REJECTED"


class ActivityFlagStatus(str, Enum):
    NONE = "NONE"
    FLAGGED = "FLAGGED"
    CLEARED = "CLEARED"
    CONFIRMED = "CONFIRMED"


class ActivitySportType(str, Enum):
    RIDE = "RIDE"
    RUN = "RUN"
    VIRTUAL_RIDE = "VIRTUAL_RIDE"
    VIRTUAL_RUN = "VIRTUAL_RUN"
    SWIM = "SWIM"
    EBIKE_RIDE = "EBikeRide"


class SegmentSportType(str, Enum):
    RIDE = "RIDE"
    RUN = "RUN"
    SWIM = "SWIM"


class SegmentStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class EffortFlagStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    FLAGGED = "FLAGGED"
    EXCLUDED = "EXCLUDED"


class ExclusionReason(str, Enum):
    SPEED_IMPOSSIBLE = "SPEED_IMPOSSIBLE"
    VEHICLE_ASSISTED = "VEHICLE_ASSISTED"
    CATEGORY_MISMATCH = "CATEGORY_MISMATCH"
    SEGMENT_HAZARDOUS = "SEGMENT_HAZARDOUS"
    FLAG_UPHELD = "FLAG_UPHELD"


class FlagReason(str, Enum):
    IMPOSSIBLE_TIME = "IMPOSSIBLE_TIME"
    VEHICLE_ASSISTED = "VEHICLE_ASSISTED"
    WRONG_CATEGORY = "WRONG_CATEGORY"


class FlagStatus(str, Enum):
    OPEN = "OPEN"
    UPHELD = "UPHELD"
    REJECTED = "REJECTED"


class ClubStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ClubSportType(str, Enum):
    RIDE = "RIDE"
    RUN = "RUN"
    SWIM = "SWIM"
    MULTI = "MULTI"


class JoinPolicy(str, Enum):
    OPEN = "OPEN"
    APPROVAL = "APPROVAL"


class MembershipRole(str, Enum):
    MEMBER = "MEMBER"
    ADMIN = "ADMIN"


class MembershipStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"
    LEFT = "LEFT"


class ChallengeGoalType(str, Enum):
    DISTANCE_M = "DISTANCE_M"
    ELEVATION_M = "ELEVATION_M"
    ACTIVE_DAYS = "ACTIVE_DAYS"


class ChallengeJoinMode(str, Enum):
    OPEN = "OPEN"
    INVITE = "INVITE"


class ChallengeStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ParticipationStatus(str, Enum):
    JOINED = "JOINED"
    WITHDRAWN = "WITHDRAWN"
    COMPLETED = "COMPLETED"


class EventStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class RsvpStatus(str, Enum):
    GOING = "GOING"
    DECLINED = "DECLINED"


class BeaconStatus(str, Enum):
    LIVE = "LIVE"
    ENDED = "ENDED"


class HeatmapSportType(str, Enum):
    RIDE = "RIDE"
    RUN = "RUN"


class Athlete(TypedDict, total=False):
    id: str
    email: str
    display_name: str
    home_lat: float
    home_lng: float
    tier: str
    status: str
    heatmap_opt_out: bool
    safety_score: int
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    athlete_id: str
    plan: str
    started_at: str
    expires_at: str
    status: str
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PrivacyZone(TypedDict, total=False):
    id: str
    athlete_id: str
    center_lat: float
    center_lng: float
    radius_m: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TrackPoint(TypedDict):
    lat: float
    lng: float
    t_offset_s: int


class Activity(TypedDict, total=False):
    id: str
    athlete_id: str
    device_source: str
    sport_type: str
    started_at: str
    duration_s: int
    distance_m: float
    track_points: List[TrackPoint]
    start_lat: float
    start_lng: float
    end_lat: float
    end_lng: float
    idempotency_key: str
    effort_hints: List[Dict[str, Any]]
    duplicate_of_id: Optional[str]
    status: str
    flag_status: str
    auto_hidden: bool
    corrected_sport_type: Optional[str]
    obfuscated_track: List[TrackPoint]
    obfuscated_start_lat: Optional[float]
    obfuscated_start_lng: Optional[float]
    obfuscated_end_lat: Optional[float]
    obfuscated_end_lng: Optional[float]
    elevation_gain_m: float
    created_at: str
    updated_at: str
    version: int


class Segment(TypedDict, total=False):
    id: str
    creator_id: str
    name: str
    sport_type: str
    start_lat: float
    start_lng: float
    end_lat: float
    end_lng: float
    distance_m: float
    city: str
    hazard_index: int
    status: str
    effort_count: int
    created_at: str
    updated_at: str
    version: int


class SegmentEffort(TypedDict, total=False):
    id: str
    activity_id: str
    segment_id: str
    athlete_id: str
    elapsed_time_s: int
    distance_m: float
    elevation_gain_m: float
    avg_speed_kmh: float
    flag_status: str
    exclusion_reason: Optional[str]
    rank_snapshot: int
    created_at: str
    updated_at: str
    version: int


class Flag(TypedDict, total=False):
    id: str
    effort_id: str
    reporter_id: str
    reason: str
    note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Club(TypedDict, total=False):
    id: str
    owner_id: str
    name: str
    sport_type: str
    join_policy: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ClubMembership(TypedDict, total=False):
    id: str
    club_id: str
    athlete_id: str
    role: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Challenge(TypedDict, total=False):
    id: str
    club_id: str
    name: str
    goal_type: str
    goal_target: float
    start_date: str
    end_date: str
    join_mode: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ChallengeParticipation(TypedDict, total=False):
    id: str
    challenge_id: str
    athlete_id: str
    status: str
    progress_value: float
    joined_at: str
    created_at: str
    updated_at: str
    version: int


class VirtualEvent(TypedDict, total=False):
    id: str
    club_id: str
    name: str
    segment_id: str
    scheduled_at: str
    capacity: int
    status: str
    rsvp_count: int
    created_at: str
    updated_at: str
    version: int


class EventRSVP(TypedDict, total=False):
    id: str
    event_id: str
    athlete_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SafetyContact(TypedDict, total=False):
    id: str
    athlete_id: str
    contact_email: str
    label: str
    created_at: str
    updated_at: str
    version: int


class BeaconSession(TypedDict, total=False):
    id: str
    athlete_id: str
    started_at: str
    last_location: Optional[Dict[str, float]]
    status: str
    created_at: str
    updated_at: str
    version: int


class HeatmapCell(TypedDict, total=False):
    id: str
    city: str
    sport_type: str
    contribution_count: int
    created_at: str
    updated_at: str
    version: int


class RoutePlan(TypedDict, total=False):
    id: str
    athlete_id: str
    name: str
    waypoints: List[Dict[str, float]]
    distance_m: float
    week_start: str
    estimated_load_score: float
    created_at: str
    updated_at: str
    version: int
