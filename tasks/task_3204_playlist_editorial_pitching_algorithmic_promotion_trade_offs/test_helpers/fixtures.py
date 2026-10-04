"""Composite setup helpers for the playlist editorial promotion domain.

Every helper builds its preconditions from scratch against a freshly restarted
server (the runner restarts the API before every test, so the database starts
empty and the logical clock reads 2026-09-01T00:00:00Z).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .factories import (
    create_artist_payload,
    create_fraud_case_payload,
    create_pitch_payload,
    create_playlist_payload,
    create_presave_payload,
    create_profile_module_payload,
    create_promotion_payload,
    create_release_payload,
    create_royalty_period_payload,
    create_stream_payload,
    create_track_payload,
)
from .test_users import TEST_USERS, make_rights_holder_headers

PA = TEST_USERS["platform_admin_headers"]
PE = TEST_USERS["playlist_editor_headers"]
EL = TEST_USERS["editorial_lead_headers"]
FA = TEST_USERS["fraud_analyst_headers"]


# ---------------------------------------------------------------------------
# Tier 1: basic entity setup
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    return get_success_data(api.set_clock(to_iso8601, PA))


def create_artist(**overrides):
    return get_success_data(api.create_artist(create_artist_payload(**overrides), PA))


def create_release(artist_id, **overrides):
    payload = create_release_payload(artist_id, **overrides)
    return get_success_data(api.create_release(payload, make_rights_holder_headers(artist_id)))


def create_track(release_id, artist_id, **overrides):
    payload = create_track_payload(release_id, **overrides)
    return get_success_data(api.create_track(payload, make_rights_holder_headers(artist_id)))


def create_playlist(**overrides):
    return get_success_data(api.create_playlist(create_playlist_payload(**overrides), EL))


def create_pitch(track_id, target_playlist_id, artist_id, **overrides):
    payload = create_pitch_payload(track_id, target_playlist_id, **overrides)
    return get_success_data(api.create_pitch(payload, make_rights_holder_headers(artist_id)))


def create_promotion(track_id, artist_id, **overrides):
    payload = create_promotion_payload(track_id, **overrides)
    return get_success_data(api.create_promotion(payload, make_rights_holder_headers(artist_id)))


def create_stream(track_id, **overrides):
    return get_success_data(api.create_stream(create_stream_payload(track_id, **overrides), PA))


def create_fraud_case(track_id, **overrides):
    return get_success_data(api.create_fraud_case(create_fraud_case_payload(track_id, **overrides), FA))


def create_royalty_period(**overrides):
    return get_success_data(api.create_royalty_period(create_royalty_period_payload(**overrides), PA))


def create_profile_module(artist_id, **overrides):
    payload = create_profile_module_payload(artist_id, **overrides)
    return get_success_data(
        api.create_profile_module(payload, make_rights_holder_headers(artist_id))
    )


def create_presave(release_id, fan_token, **overrides):
    payload = create_presave_payload(release_id, fan_token, **overrides)
    return get_success_data(api.create_presave(payload, PA))


def setup_artist_with_release_and_focus_track(
    artist_overrides=None,
    release_date="2026-09-20T00:00:00Z",
    **release_overrides,
):
    """One artist + one SCHEDULED release + one AVAILABLE focus track.

    Returns (artist, release, track).
    """
    artist = create_artist(**(artist_overrides or {}))
    release = create_release(artist["id"], release_date=release_date, **release_overrides)
    track = create_track(release["id"], artist["id"])
    return artist, release, track


def setup_artist_release_track_playlist(
    artist_overrides=None,
    release_date="2026-09-20T00:00:00Z",
    playlist_overrides=None,
    **release_overrides,
):
    """Artist + SCHEDULED release + focus track + ACTIVE playlist.

    Returns (artist, release, track, playlist).
    """
    artist, release, track = setup_artist_with_release_and_focus_track(
        artist_overrides=artist_overrides, release_date=release_date, **release_overrides
    )
    playlist = create_playlist(**(playlist_overrides or {}))
    return artist, release, track, playlist


# ---------------------------------------------------------------------------
# Tier 2: pitch pipeline
# ---------------------------------------------------------------------------

def create_submitted_pitch(artist, track, playlist, pitch_text="a pitch"):
    return create_pitch(track["id"], playlist["id"], artist["id"], pitch_text=pitch_text)


def claim_pitch(pitch_id, team="EDITORIAL_A"):
    return get_success_data(api.claim_pitch(pitch_id, team, PE))


def request_revision(pitch_id):
    return get_success_data(api.request_revision(pitch_id, PE))


def revise_pitch(pitch_id, pitch_text, artist_id):
    return get_success_data(
        api.revise_pitch(pitch_id, pitch_text, make_rights_holder_headers(artist_id))
    )


def decide_pitch(pitch_id, decision):
    return get_success_data(api.decide_pitch(pitch_id, decision, EL))


def withdraw_pitch(pitch_id, artist_id):
    return get_success_data(api.withdraw_pitch(pitch_id, make_rights_holder_headers(artist_id)))


def setup_pitch_under_review(
    artist_overrides=None,
    release_date="2026-09-20T00:00:00Z",
    playlist_overrides=None,
    pitch_text="a pitch",
):
    """Artist + SCHEDULED release + focus track + playlist + pitch claimed
    into UNDER_REVIEW. Returns (artist, release, track, playlist, pitch).
    """
    artist, release, track, playlist = setup_artist_release_track_playlist(
        artist_overrides=artist_overrides,
        release_date=release_date,
        playlist_overrides=playlist_overrides,
    )
    pitch = create_submitted_pitch(artist, track, playlist, pitch_text)
    claim_pitch(pitch["id"], team=playlist["owning_team"])
    return artist, release, track, playlist, pitch


# ---------------------------------------------------------------------------
# Tier 3: placement pipeline
# ---------------------------------------------------------------------------

def accept_pitch_and_get_placement(pitch_id):
    """Decide ACCEPT and fetch the SCHEDULED placement it created."""
    decide_pitch(pitch_id, "ACCEPT")
    rows, _meta = _list_placements({"pitch_id": pitch_id})
    assert len(rows) == 1, f"expected exactly one placement for pitch {pitch_id}"
    return rows[0]


def _list_placements(params):
    from prd_bench_local_runner.testing import validate_paginated

    resp = api.list_placements(EL, params=params)
    return validate_paginated(resp)


def setup_accepted_placement(
    artist_overrides=None,
    release_date="2026-09-20T00:00:00Z",
    playlist_overrides=None,
    pitch_text="a pitch",
):
    """Pitch accepted: returns (artist, release, track, playlist, pitch, placement)
    with the placement in SCHEDULED status."""
    artist, release, track, playlist, pitch = setup_pitch_under_review(
        artist_overrides=artist_overrides,
        release_date=release_date,
        playlist_overrides=playlist_overrides,
        pitch_text=pitch_text,
    )
    placement = accept_pitch_and_get_placement(pitch["id"])
    return artist, release, track, playlist, pitch, placement


def setup_active_placement(
    artist_overrides=None,
    release_date="2026-09-10T00:00:00Z",
    playlist_overrides=None,
    pitch_text="a pitch",
    activate_at=None,
):
    """Pitch accepted, clock advanced to release date (release goes LIVE),
    placement activated. Returns (artist, release, track, playlist, pitch,
    placement) with the placement ACTIVE.

    activate_at defaults to release_date.
    """
    artist, release, track, playlist, pitch, placement = setup_accepted_placement(
        artist_overrides=artist_overrides,
        release_date=release_date,
        playlist_overrides=playlist_overrides,
        pitch_text=pitch_text,
    )
    when = activate_at or release_date
    set_clock(when)
    placement = get_success_data(api.activate_placement(placement["id"], PE))
    return artist, release, track, playlist, pitch, placement


# ---------------------------------------------------------------------------
# Tier 4: fraud pipeline
# ---------------------------------------------------------------------------

def open_fraud_case(track_id, window_start, window_end, bot, velocity, device):
    return create_fraud_case(
        track_id,
        window_start=window_start,
        window_end=window_end,
        signal_bot_ratio=bot,
        signal_velocity_zscore=velocity,
        signal_device_concentration=device,
    )


def confirm_fraud_case(case_id):
    return get_success_data(api.adjudicate_fraud_case(case_id, "CONFIRM", FA))


# ---------------------------------------------------------------------------
# Tier 5: royalty period pipeline
# ---------------------------------------------------------------------------

def close_period(period_id, variant, expected_version):
    return get_success_data(
        api.close_royalty_period(
            period_id,
            {"variant": variant, "expected_period_version": expected_version},
            PA,
        )
    )


def list_statements(period_id=None, artist_id=None):
    from prd_bench_local_runner.testing import validate_paginated

    params = {}
    if period_id is not None:
        params["period_id"] = period_id
    if artist_id is not None:
        params["artist_id"] = artist_id
    resp = api.list_royalty_statements(PA, params=params)
    rows, _meta = validate_paginated(resp)
    return rows


def get_statement_for_artist(period_id, artist_id):
    rows = list_statements(period_id=period_id, artist_id=artist_id)
    assert len(rows) == 1, f"expected 1 statement for artist {artist_id}, got {len(rows)}"
    return rows[0]
