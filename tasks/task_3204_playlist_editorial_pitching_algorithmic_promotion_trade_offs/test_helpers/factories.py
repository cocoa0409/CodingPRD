"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import TEST_DEFAULTS, THRESHOLDS


def create_artist_payload(**overrides) -> dict:
    defaults = {
        "stage_name": "Test Artist",
        "primary_genre": "POP",
        "home_territory": TEST_DEFAULTS["HOME_TERRITORY"],
        "follower_count": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_release_payload(artist_id, **overrides) -> dict:
    defaults = {
        "artist_id": artist_id,
        "title": "Test Release",
        "release_type": "SINGLE",
        "release_date": "2026-09-20T00:00:00Z",
        "genre_tags": ["POP"],
        "mood_tags": [],
    }
    defaults.update(overrides)
    return defaults


def create_track_payload(release_id, **overrides) -> dict:
    defaults = {
        "release_id": release_id,
        "title": "Test Track",
        "duration_ms": TEST_DEFAULTS["DURATION_MS"],
        "is_focus_track": True,
    }
    defaults.update(overrides)
    return defaults


def create_playlist_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Playlist",
        "genre_focus": "POP",
        "mood_focus": "ANY",
        "slot_count": 2,
        "rotation_cadence_days": 7,
        "owning_team": "EDITORIAL_A",
    }
    defaults.update(overrides)
    return defaults


def create_pitch_payload(track_id, target_playlist_id, **overrides) -> dict:
    defaults = {
        "track_id": track_id,
        "pitch_text": "a pitch",
        "target_playlist_id": target_playlist_id,
    }
    defaults.update(overrides)
    return defaults


def create_promotion_payload(track_id, **overrides) -> dict:
    defaults = {
        "track_id": track_id,
        "discount_factor": 0.5,
        "starts_on": "2026-09-10T00:00:00Z",
        "ends_on": "2026-09-20T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_stream_payload(track_id, **overrides) -> dict:
    defaults = {
        "track_id": track_id,
        "territory": TEST_DEFAULTS["HOME_TERRITORY"],
        "source": "ORGANIC",
        "occurred_on": "2026-09-11T00:00:00Z",
        "ms_played": TEST_DEFAULTS["DURATION_MS"],
    }
    defaults.update(overrides)
    return defaults


def create_fraud_case_payload(track_id, **overrides) -> dict:
    defaults = {
        "track_id": track_id,
        "window_start": "2026-09-11T00:00:00Z",
        "window_end": "2026-09-12T00:00:00Z",
        "signal_bot_ratio": 1.0,
        "signal_velocity_zscore": 1.0,
        "signal_device_concentration": 0.6,
    }
    defaults.update(overrides)
    return defaults


def create_royalty_period_payload(**overrides) -> dict:
    defaults = {
        "period_start": "2026-09-01T00:00:00Z",
        "period_end": "2026-10-01T00:00:00Z",
        "pool_cents": TEST_DEFAULTS["POOL_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_profile_module_payload(artist_id, **overrides) -> dict:
    defaults = {
        "artist_id": artist_id,
        "module_type": "CANVAS",
        "payload_uri": "https://cdn.example.com/canvas/default.mp4",
    }
    defaults.update(overrides)
    return defaults


def create_presave_payload(release_id, fan_token, **overrides) -> dict:
    defaults = {
        "release_id": release_id,
        "fan_token": fan_token,
        "territory": TEST_DEFAULTS["HOME_TERRITORY"],
    }
    defaults.update(overrides)
    return defaults
