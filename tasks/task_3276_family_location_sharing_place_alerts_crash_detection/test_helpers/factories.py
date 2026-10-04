"""Payload factories — one per entity, input fields only."""

ADULT_BIRTHDATE = "1990-01-01T00:00:00Z"
MINOR_BIRTHDATE = "2012-01-01T00:00:00Z"  # age 14 at the boot clock


def create_circle_payload(**overrides) -> dict:
    """Input for POST /api/circles."""
    defaults = {
        "name": "TestFamily",
        "subscription_tier": "PROTECT",
        "billing_anchor_day": 1,
        "owner_display_name": "Owner",
        "owner_birthdate": "1980-01-01T00:00:00Z",
        "owner_email": "owner@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    """Input for POST /api/circles/{id}/members."""
    defaults = {
        "display_name": "Member",
        "birthdate": ADULT_BIRTHDATE,
        "email": "member@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_minor_member_payload(**overrides) -> dict:
    defaults = create_member_payload(
        display_name="Minor",
        birthdate=MINOR_BIRTHDATE,
        email="minor@example.com",
    )
    defaults.update(overrides)
    return defaults


def grant_consent_payload(**overrides) -> dict:
    defaults = {"scope": "FULL", "monetization_opt_in": False}
    defaults.update(overrides)
    return defaults


def create_place_payload(**overrides) -> dict:
    defaults = {
        "label": "Home",
        "center_lat": 37.7000,
        "center_lng": -122.4000,
        "radius_m": 200,
        "accuracy_floor_m": 100,
        "notify_on_arrive": True,
        "notify_on_depart": True,
        "dwell_bucket_seconds": 60,
    }
    defaults.update(overrides)
    return defaults


def create_fix_payload(**overrides) -> dict:
    """Input for POST .../fixes. recorded_at must stay within +/-300s of the
    logical clock (boot: 2026-09-01T00:00:00Z)."""
    defaults = {
        "recorded_at": "2026-09-01T00:00:00Z",
        "lat": 37.7000,
        "lng": -122.4000,
        "accuracy_m": 20,
        "speed_mps": 0.0,
        "battery_pct": 90,
        "phone_in_use": False,
        "motion_context": "STILL",
    }
    defaults.update(overrides)
    return defaults


def report_crash_payload(trip_report_id, delta_v=20.0, **overrides) -> dict:
    defaults = {
        "trip_report_id": trip_report_id,
        "delta_v": delta_v,
        "note": "hard impact",
    }
    defaults.update(overrides)
    return defaults


def false_alarm_payload(**overrides) -> dict:
    defaults = {"false_alarm_reason": "dropped phone, not a crash"}
    defaults.update(overrides)
    return defaults


def verify_dispatch_payload(**overrides) -> dict:
    defaults = {"verification_note": "voice confirmation attempted, no answer"}
    defaults.update(overrides)
    return defaults


def change_tier_payload(to_tier, expected_circle_version, **overrides) -> dict:
    defaults = {
        "to_tier": to_tier,
        "expected_circle_version": expected_circle_version,
    }
    defaults.update(overrides)
    return defaults


def privacy_payload(privacy_mode, expected_member_version) -> dict:
    return {
        "privacy_mode": privacy_mode,
        "expected_member_version": expected_member_version,
    }


def compliance_hold_payload(**overrides) -> dict:
    defaults = {
        "hold_kind": "DATA_SHARING_DISCLOSURE",
        "opened_reason": "disclosure_version_bump_v2",
    }
    defaults.update(overrides)
    return defaults
