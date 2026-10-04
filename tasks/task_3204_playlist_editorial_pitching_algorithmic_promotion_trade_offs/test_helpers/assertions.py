"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

VALID_ARTIST_STATUSES = ["ACTIVE", "SUSPENDED", "TERMINATED"]
VALID_RELEASE_STATUSES = ["SCHEDULED", "LIVE", "REMOVED"]
VALID_TRACK_STATUSES = ["AVAILABLE", "REMOVED"]
VALID_PITCH_STATUSES = [
    "PITCHED", "UNDER_REVIEW", "NEEDS_REVISION", "ACCEPTED", "REJECTED", "WITHDRAWN",
]
VALID_PLAYLIST_STATUSES = ["ACTIVE", "RETIRED"]
VALID_PLACEMENT_STATUSES = ["SCHEDULED", "ACTIVE", "ROTATED_OUT", "REINSTATED", "EVICTED"]
VALID_PROMOTION_STATUSES = ["ENROLLED", "SUSPENDED", "TERMINATED"]
VALID_FRAUD_VERDICTS = ["OPEN", "AUTO_FLAGGED", "CONFIRMED", "DISMISSED"]
VALID_PERIOD_STATUSES = ["OPEN", "CLOSED", "SETTLED"]
VALID_MODULE_STATUSES = ["ENABLED", "DISABLED"]
VALID_PRESAVE_STATUSES = ["SAVED", "CONVERTED", "CANCELLED"]
VALID_GENRES = ["POP", "HIPHOP", "ROCK", "ELECTRONIC", "LATIN", "COUNTRY", "JAZZ", "CLASSICAL"]
VALID_MOODS = ["CHILL", "ENERGETIC", "MELANCHOLY", "FOCUS", "PARTY", "ROMANTIC"]
VALID_MOOD_FOCI = VALID_MOODS + ["ANY"]
VALID_TEAMS = ["EDITORIAL_A", "EDITORIAL_B"]
VALID_SOURCES = ["EDITORIAL_PLAYLIST", "ALGORITHMIC", "ORGANIC"]
VALID_CLOSE_VARIANTS = ["GROSS", "EFFECTIVE"]
VALID_MODULE_TYPES = ["CANVAS", "MERCH"]
VALID_RELEASE_TYPES = ["SINGLE", "EP", "ALBUM"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be >= 1"


def assert_artist(data: dict):
    _assert_common(data)
    assert isinstance(data["stage_name"], str) and len(data["stage_name"]) > 0
    assert data["primary_genre"] in VALID_GENRES
    assert isinstance(data["home_territory"], str) and len(data["home_territory"]) == 2
    assert isinstance(data["follower_count"], int) and data["follower_count"] >= 0
    assert data["status"] in VALID_ARTIST_STATUSES
    assert isinstance(data["fraud_strikes"], int) and data["fraud_strikes"] >= 0


def assert_release(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("artist_id", "")), "artist_id must be a UUID"
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["release_type"] in VALID_RELEASE_TYPES
    assert is_iso8601_timestamp(data.get("release_date", "")), "release_date must be ISO 8601"
    assert isinstance(data["territory_allowlist"], list)
    assert isinstance(data["genre_tags"], list) and 1 <= len(data["genre_tags"]) <= 3
    assert isinstance(data["mood_tags"], list) and 0 <= len(data["mood_tags"]) <= 4
    assert data["status"] in VALID_RELEASE_STATUSES
    assert isinstance(data["date_change_count"], int) and data["date_change_count"] >= 0
    assert isinstance(data["presave_count"], int) and data["presave_count"] >= 0


def assert_track(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("release_id", "")), "release_id must be a UUID"
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert isinstance(data["duration_ms"], int) and data["duration_ms"] >= 30000
    assert isinstance(data["is_focus_track"], bool)
    assert data["status"] in VALID_TRACK_STATUSES


def assert_pitch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("track_id", "")), "track_id must be a UUID"
    assert isinstance(data["pitch_text"], str) and 1 <= len(data["pitch_text"]) <= 2000
    assert is_valid_uuid(data.get("target_playlist_id", "")), "target_playlist_id must be a UUID"
    assert data["status"] in VALID_PITCH_STATUSES
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0


def assert_playlist(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["genre_focus"] in VALID_GENRES
    assert data["mood_focus"] in VALID_MOOD_FOCI
    assert isinstance(data["slot_count"], int) and 1 <= data["slot_count"] <= 50
    assert isinstance(data["rotation_cadence_days"], int) and data["rotation_cadence_days"] >= 1
    assert data["owning_team"] in VALID_TEAMS
    assert data["status"] in VALID_PLAYLIST_STATUSES


def assert_placement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("playlist_id", "")), "playlist_id must be a UUID"
    assert is_valid_uuid(data.get("track_id", "")), "track_id must be a UUID"
    assert is_valid_uuid(data.get("pitch_id", "")), "pitch_id must be a UUID"
    assert isinstance(data["slot_index"], int) and data["slot_index"] >= 0
    assert data["status"] in VALID_PLACEMENT_STATUSES


def assert_promotion(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("track_id", "")), "track_id must be a UUID"
    assert 0 < data["discount_factor"] < 1
    assert is_iso8601_timestamp(data.get("starts_on", "")), "starts_on must be ISO 8601"
    assert is_iso8601_timestamp(data.get("ends_on", "")), "ends_on must be ISO 8601"
    assert data["status"] in VALID_PROMOTION_STATUSES


def assert_stream_event(data: dict):
    """StreamEvent carries only id and created_at from the common set (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "StreamEvent must not carry a version field"
    assert "updated_at" not in data, "StreamEvent must not carry an updated_at field"
    assert is_valid_uuid(data.get("track_id", "")), "track_id must be a UUID"
    assert data["source"] in VALID_SOURCES
    assert isinstance(data["ms_played"], int) and data["ms_played"] >= 0
    assert isinstance(data["is_tainted"], bool)


def assert_fraud_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("track_id", "")), "track_id must be a UUID"
    assert is_iso8601_timestamp(data.get("window_start", "")), "window_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("window_end", "")), "window_end must be ISO 8601"
    assert 0 <= data["signal_bot_ratio"] <= 1
    assert 0 <= data["signal_velocity_zscore"] <= 1
    assert 0 <= data["signal_device_concentration"] <= 1
    assert data["verdict"] in VALID_FRAUD_VERDICTS


def assert_royalty_period(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("period_start", "")), "period_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("period_end", "")), "period_end must be ISO 8601"
    assert isinstance(data["pool_cents"], int) and data["pool_cents"] >= 0
    assert data["status"] in VALID_PERIOD_STATUSES


def assert_royalty_statement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("period_id", "")), "period_id must be a UUID"
    assert is_valid_uuid(data.get("artist_id", "")), "artist_id must be a UUID"
    assert isinstance(data["raw_streams"], int) and data["raw_streams"] >= 0
    assert isinstance(data["share_bps"], int) and 0 <= data["share_bps"] <= 10000
    assert isinstance(data["gross_payout_cents"], int)


def assert_profile_module(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("artist_id", "")), "artist_id must be a UUID"
    assert data["module_type"] in VALID_MODULE_TYPES
    assert isinstance(data["payload_uri"], str) and len(data["payload_uri"]) > 0
    assert data["status"] in VALID_MODULE_STATUSES


def assert_presave(data: dict):
    """PreSave carries only id and created_at from the common set (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "PreSave must not carry a version field"
    assert "updated_at" not in data, "PreSave must not carry an updated_at field"
    assert is_valid_uuid(data.get("release_id", "")), "release_id must be a UUID"
    assert isinstance(data["fan_token"], str) and len(data["fan_token"]) > 0
    assert data["status"] in VALID_PRESAVE_STATUSES
