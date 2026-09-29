"""Request-payload builders.

Each builder returns a complete, valid payload for one write endpoint and
accepts keyword overrides. Monetary fields are plain integers of cents, decimal
quantities are plain numbers, and instants are whole-second ISO-8601 UTC
strings with a trailing ``Z``.
"""

from itertools import count

from .constants import CLIENT_USER_ID

_sequence = count(1)


def unique_suffix() -> str:
    """A short suffix that keeps unique-per-collection codes distinct."""
    return f"{next(_sequence):04d}"


# --------------------------------------------------------------------------
# Facility configuration
# --------------------------------------------------------------------------


def clock_payload(current_utc="2026-09-01T00:00:00Z", **overrides):
    payload = {"current_utc": current_utc}
    payload.update(overrides)
    return payload


def platform_spec_payload(
    platform="THEATRICAL",
    spec_label="Theatrical Gate Spec",
    target_lufs=-24.00,
    tolerance_lu=0.50,
    true_peak_max_dbtp=-2.00,
    channel_layout="5_1",
    **overrides,
):
    payload = {
        "platform": platform,
        "spec_label": spec_label,
        "target_lufs": target_lufs,
        "tolerance_lu": tolerance_lu,
        "true_peak_max_dbtp": true_peak_max_dbtp,
        "channel_layout": channel_layout,
    }
    payload.update(overrides)
    return payload


def mix_stage_payload(
    room_code=None,
    display_name="Stage A",
    hourly_rate_cents=120000,
    supports_remote_review=True,
    changeover_minutes=45,
    **overrides,
):
    payload = {
        "room_code": room_code if room_code is not None else f"STAGE_{unique_suffix()}",
        "display_name": display_name,
        "hourly_rate_cents": hourly_rate_cents,
        "supports_remote_review": supports_remote_review,
        "changeover_minutes": changeover_minutes,
    }
    payload.update(overrides)
    return payload


def mixer_payload(
    full_name="Jo Mixer",
    certified_platforms=("THEATRICAL",),
    max_daily_hours=10.00,
    **overrides,
):
    payload = {
        "full_name": full_name,
        "certified_platforms": list(certified_platforms),
        "max_daily_hours": max_daily_hours,
    }
    payload.update(overrides)
    return payload


def voice_talent_payload(
    full_name="Vera Voice",
    union_status="UNION",
    daily_cap_minutes=240,
    min_call_minutes=60,
    **overrides,
):
    payload = {
        "full_name": full_name,
        "union_status": union_status,
        "daily_cap_minutes": daily_cap_minutes,
        "min_call_minutes": min_call_minutes,
    }
    payload.update(overrides)
    return payload


def library_asset_payload(
    asset_code=None,
    kind="MUSIC_LIBRARY",
    license_type="RIGHTS_MANAGED",
    territory_scope="WORLDWIDE",
    fee_cents=25000,
    **overrides,
):
    payload = {
        "asset_code": asset_code if asset_code is not None else f"ASSET-{unique_suffix()}",
        "kind": kind,
        "license_type": license_type,
        "territory_scope": territory_scope,
        "fee_cents": fee_cents,
    }
    payload.update(overrides)
    return payload


def revoke_payload(revocation_reason="licence terminated by the publisher", **overrides):
    payload = {"revocation_reason": revocation_reason}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Projects
# --------------------------------------------------------------------------


def project_payload(
    title="Feature Alpha",
    client_name="Distributor Co",
    client_user_id=CLIENT_USER_ID,
    delivery_deadline_utc="2026-12-31T00:00:00Z",
    **overrides,
):
    payload = {
        "title": title,
        "client_name": client_name,
        "client_user_id": client_user_id,
        "delivery_deadline_utc": delivery_deadline_utc,
    }
    payload.update(overrides)
    return payload


def picture_lock_payload(**overrides):
    payload = {}
    payload.update(overrides)
    return payload


def break_picture_lock_payload(break_reason="a new cut arrived from the editor", **overrides):
    payload = {"break_reason": break_reason}
    payload.update(overrides)
    return payload


def archive_package_payload(session_file_count=12, **overrides):
    payload = {"session_file_count": session_file_count}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Editorial
# --------------------------------------------------------------------------


def stem_package_payload(project_id, reel_label="R1", stem_layout="5_1", **overrides):
    payload = {
        "project_id": project_id,
        "reel_label": reel_label,
        "stem_layout": stem_layout,
    }
    payload.update(overrides)
    return payload


def music_cue_payload(
    expected_stem_package_version,
    cue_number="1M1",
    duration_seconds=120,
    source="COMPOSER_ORIGINAL",
    **overrides,
):
    payload = {
        "expected_stem_package_version": expected_stem_package_version,
        "cue_number": cue_number,
        "duration_seconds": duration_seconds,
        "source": source,
    }
    payload.update(overrides)
    return payload


def asset_usage_payload(
    library_asset_id,
    stem_package_id,
    usage_seconds=100,
    territory_declared="WORLDWIDE",
    **overrides,
):
    payload = {
        "library_asset_id": library_asset_id,
        "stem_package_id": stem_package_id,
        "usage_seconds": usage_seconds,
        "territory_declared": territory_declared,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# ADR
# --------------------------------------------------------------------------


def adr_session_payload(
    project_id,
    voice_talent_id,
    window_start_utc="2026-09-14T09:00:00Z",
    window_end_utc="2026-09-14T10:00:00Z",
    lines_scheduled=10,
    **overrides,
):
    payload = {
        "project_id": project_id,
        "voice_talent_id": voice_talent_id,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
        "lines_scheduled": lines_scheduled,
    }
    payload.update(overrides)
    return payload


def adr_record_payload(lines_recorded=10, **overrides):
    payload = {"lines_recorded": lines_recorded}
    payload.update(overrides)
    return payload


def adr_cancel_payload(cancellation_reason="CLIENT_REQUEST", **overrides):
    payload = {"cancellation_reason": cancellation_reason}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Mix stage bookings
# --------------------------------------------------------------------------


def mix_booking_payload(
    expected_project_version,
    project_id,
    mix_stage_id,
    mixer_id,
    booking_type="FINAL_MIX",
    platform="THEATRICAL",
    window_start_utc="2026-09-14T10:00:00Z",
    window_end_utc="2026-09-14T13:00:00Z",
    client_attendance="ONSITE",
    **overrides,
):
    payload = {
        "expected_project_version": expected_project_version,
        "project_id": project_id,
        "mix_stage_id": mix_stage_id,
        "mixer_id": mixer_id,
        "booking_type": booking_type,
        "platform": platform,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
        "client_attendance": client_attendance,
    }
    payload.update(overrides)
    return payload


def release_payload(release_reason="client postponed the mix", **overrides):
    payload = {"release_reason": release_reason}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Deliverables and QC
# --------------------------------------------------------------------------


def deliverable_payload(
    expected_project_version,
    project_id,
    platform_spec_id,
    stem_package_id,
    mix_booking_id,
    **overrides,
):
    payload = {
        "expected_project_version": expected_project_version,
        "project_id": project_id,
        "platform_spec_id": platform_spec_id,
        "stem_package_id": stem_package_id,
        "mix_booking_id": mix_booking_id,
    }
    payload.update(overrides)
    return payload


def qc_submit_payload(
    measured_integrated_lufs=-24.20,
    measured_true_peak_dbtp=-3.00,
    me_stems_present=False,
    **overrides,
):
    payload = {
        "measured_integrated_lufs": measured_integrated_lufs,
        "measured_true_peak_dbtp": measured_true_peak_dbtp,
        "me_stems_present": me_stems_present,
    }
    payload.update(overrides)
    return payload


def remediate_payload(**overrides):
    payload = {}
    payload.update(overrides)
    return payload


def deliver_payload(delivery_reference="PLATFORM-ACK-0001", **overrides):
    payload = {"delivery_reference": delivery_reference}
    payload.update(overrides)
    return payload
