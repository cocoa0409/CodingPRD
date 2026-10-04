"""Payload factories — one per entity, input fields only (PRD section 4)."""
import uuid

from .constants import TEST_DEFAULTS

DEFAULT_CHECKLIST = {
    "deep_linking": True,
    "drm": True,
    "trick_play": True,
}


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def create_publisher_payload(**overrides) -> dict:
    defaults = {
        "legal_name": _uniq("Pub"),
        "default_ad_share_bps": TEST_DEFAULTS["AD_SHARE_BPS"],
        "billing_model": "GROSS_SHARE",
    }
    defaults.update(overrides)
    return defaults


def create_channel_payload(publisher_id, **overrides) -> dict:
    defaults = {
        "publisher_id": publisher_id,
        "name": _uniq("Channel"),
        "category": "VIDEO",
        "content_rating": "G",
    }
    defaults.update(overrides)
    return defaults


def create_channel_version_payload(expected_channel_version, **overrides) -> dict:
    defaults = {
        "version_label": _uniq("1.0."),
        "technical_checklist": dict(DEFAULT_CHECKLIST),
        "expected_channel_version": expected_channel_version,
    }
    defaults.update(overrides)
    return defaults


def create_viewer_account_payload(**overrides) -> dict:
    defaults = {"email": f"{_uniq('viewer')}@example.com"}
    defaults.update(overrides)
    return defaults


def create_subscription_payload(channel_id, **overrides) -> dict:
    defaults = {"channel_id": channel_id, "price_cents": 1000}
    defaults.update(overrides)
    return defaults


def create_ad_slot_grant_payload(channel_id, **overrides) -> dict:
    defaults = {
        "channel_id": channel_id,
        "period": "2026-09",
        "total_slots": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(publisher_id, channel_id, **overrides) -> dict:
    defaults = {
        "publisher_id": publisher_id,
        "channel_id": channel_id,
        "flight_start": TEST_DEFAULTS["FLIGHT_START"],
        "flight_end": TEST_DEFAULTS["FLIGHT_END"],
        "budget_cents": TEST_DEFAULTS["CAMPAIGN_BUDGET_CENTS"],
        "targeting_mode": "CONTEXTUAL",
    }
    defaults.update(overrides)
    return defaults


def create_placement_booking_payload(campaign_id, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "slot_code": "HOME_ROW_1",
        "window_start": "2026-09-10T09:00:00Z",
        "window_end": "2026-09-10T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_manufacturer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": _uniq("TV"),
        "royalty_per_device_cents": TEST_DEFAULTS["ROYALTY_PER_DEVICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_device_model_payload(manufacturer_id, **overrides) -> dict:
    defaults = {
        "manufacturer_id": manufacturer_id,
        "model_code": _uniq("MODEL"),
        "recovery_policy": "MONETIZATION",
    }
    defaults.update(overrides)
    return defaults


def create_lab_booking_payload(**overrides) -> dict:
    defaults = {
        "bench_code": "LAB_BENCH_1",
        "window_start": "2026-09-01T00:00:00Z",
        "window_end": "2026-09-01T08:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_os_update_payload(**overrides) -> dict:
    defaults = {
        "version_tag": _uniq("v"),
        "mandatory": True,
        "rollout_start": "2026-09-02T00:00:00Z",
        "compliance_deadline": "2026-09-20T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_device_unit_payload(device_model_id, **overrides) -> dict:
    defaults = {
        "device_model_id": device_model_id,
        "serial_number": _uniq("SN"),
        "hardware_cost_cents": 20000,
        "sale_price_cents": 9999,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(publisher_id, **overrides) -> dict:
    defaults = {
        "publisher_id": publisher_id,
        "subject_type": "CHANNEL_REMOVAL",
        "reason": "dispute rationale",
    }
    defaults.update(overrides)
    return defaults
