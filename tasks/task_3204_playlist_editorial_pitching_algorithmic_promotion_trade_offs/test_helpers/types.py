"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class ArtistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ReleaseStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LIVE = "LIVE"
    REMOVED = "REMOVED"


class TrackStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    REMOVED = "REMOVED"


class PitchStatus(str, Enum):
    PITCHED = "PITCHED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_REVISION = "NEEDS_REVISION"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class PlaylistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PlacementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    ROTATED_OUT = "ROTATED_OUT"
    REINSTATED = "REINSTATED"
    EVICTED = "EVICTED"


class PromotionStatus(str, Enum):
    ENROLLED = "ENROLLED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class FraudVerdict(str, Enum):
    OPEN = "OPEN"
    AUTO_FLAGGED = "AUTO_FLAGGED"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class PeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"


class ModuleStatus(str, Enum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class PreSaveStatus(str, Enum):
    SAVED = "SAVED"
    CONVERTED = "CONVERTED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    RIGHTS_HOLDER = "RightsHolder"
    PLAYLIST_EDITOR = "PlaylistEditor"
    EDITORIAL_LEAD = "EditorialLead"
    FRAUD_ANALYST = "FraudAnalyst"
    PLATFORM_ADMIN = "PlatformAdmin"


GENRES = ["POP", "HIPHOP", "ROCK", "ELECTRONIC", "LATIN", "COUNTRY", "JAZZ", "CLASSICAL"]
MOODS = ["CHILL", "ENERGETIC", "MELANCHOLY", "FOCUS", "PARTY", "ROMANTIC"]
RELEASE_TYPES = ["SINGLE", "EP", "ALBUM"]
STREAM_SOURCES = ["EDITORIAL_PLAYLIST", "ALGORITHMIC", "ORGANIC"]
OWNING_TEAMS = ["EDITORIAL_A", "EDITORIAL_B"]
MODULE_TYPES = ["CANVAS", "MERCH"]
CLOSE_VARIANTS = ["GROSS", "EFFECTIVE"]


# --- Entities carrying the full common set (id, created_at, updated_at, version) ---

class Artist(TypedDict, total=False):
    id: str
    stage_name: str
    primary_genre: str
    home_territory: str
    follower_count: int
    status: str
    fraud_strikes: int
    created_at: str
    updated_at: str
    version: int


class Release(TypedDict, total=False):
    id: str
    artist_id: str
    title: str
    release_type: str
    release_date: str
    territory_allowlist: List[str]
    genre_tags: List[str]
    mood_tags: List[str]
    status: str
    date_change_count: int
    presave_count: int
    created_at: str
    updated_at: str
    version: int


class Track(TypedDict, total=False):
    id: str
    release_id: str
    title: str
    duration_ms: int
    is_focus_track: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PitchSubmission(TypedDict, total=False):
    id: str
    track_id: str
    pitch_text: str
    target_playlist_id: str
    status: str
    submitted_days_before_release: int
    revision_round: int
    created_at: str
    updated_at: str
    version: int


class EditorialPlaylist(TypedDict, total=False):
    id: str
    name: str
    genre_focus: str
    mood_focus: str
    slot_count: int
    rotation_cadence_days: int
    owning_team: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PlaylistPlacement(TypedDict, total=False):
    id: str
    playlist_id: str
    track_id: str
    pitch_id: str
    slot_index: int
    activated_on: Optional[str]
    scheduled_rotation_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PromotionEnrollment(TypedDict, total=False):
    id: str
    track_id: str
    discount_factor: float
    starts_on: str
    ends_on: str
    disclosure_token: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FraudCase(TypedDict, total=False):
    id: str
    track_id: str
    window_start: str
    window_end: str
    signal_bot_ratio: float
    signal_velocity_zscore: float
    signal_device_concentration: float
    confidence_score: float
    verdict: str
    clawback_cents: float
    created_at: str
    updated_at: str
    version: int


class RoyaltyPeriod(TypedDict, total=False):
    id: str
    period_start: str
    period_end: str
    pool_cents: int
    status: str
    closed_variant: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RoyaltyStatement(TypedDict, total=False):
    id: str
    period_id: str
    artist_id: str
    raw_streams: int
    effective_streams: float
    share_bps: int
    gross_payout_cents: int
    clawback_cents: float
    net_payout_cents: float
    created_at: str
    updated_at: str
    version: int


class ProfileModule(TypedDict, total=False):
    id: str
    artist_id: str
    module_type: str
    track_id: Optional[str]
    payload_uri: str
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only resources: id + created_at only (PRD §2.5) ---

class StreamEvent(TypedDict, total=False):
    id: str
    track_id: str
    territory: str
    source: str
    occurred_on: str
    ms_played: int
    is_tainted: bool
    royalty_period_id: str
    created_at: str


class PreSave(TypedDict, total=False):
    id: str
    release_id: str
    fan_token: str
    territory: str
    status: str
    created_at: str
