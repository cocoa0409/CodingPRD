"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import PERIOD_END, PERIOD_START, TEST_DEFAULTS

DEFAULTS = {
    "CHANNEL_NAME": "Test Channel",
    "COUNTRY_CODE": TEST_DEFAULTS["COUNTRY_CODE"],
    "WATCH_HOURS": TEST_DEFAULTS["WATCH_HOURS"],
    "SUBSCRIBERS": TEST_DEFAULTS["SUBSCRIBERS"],
    "PAYMENT_THRESHOLD_CENTS": TEST_DEFAULTS["PAYMENT_THRESHOLD_CENTS"],
    "ITEM_TITLE": "Test Upload",
    "DURATION_SECONDS": TEST_DEFAULTS["DURATION_SECONDS"],
    "CATEGORY_CODE": "MUSIC",
    "FINGERPRINT": "fp-default-1",
    "SEGMENT_SECONDS": 90,
    "GROSS_CENTS": TEST_DEFAULTS["AD_GROSS_CENTS"],
    "TIER_NAME": "Test Tier",
    "MEMBER_NAME": "Test Member",
}


def create_channel_payload(**overrides) -> dict:
    """POST /api/channels input.  Only the four counters are mandatory; the
    optional attributes are omitted unless the caller supplies them."""
    payload = {
        "channel_name": DEFAULTS["CHANNEL_NAME"],
        "country_code": DEFAULTS["COUNTRY_CODE"],
        "lifetime_watch_hours": DEFAULTS["WATCH_HOURS"],
        "subscriber_count": DEFAULTS["SUBSCRIBERS"],
    }
    payload.update(overrides)
    return payload


def create_content_item_payload(**overrides) -> dict:
    """POST /api/channels/{id}/content-items input."""
    payload = {
        "title": DEFAULTS["ITEM_TITLE"],
        "duration_seconds": DEFAULTS["DURATION_SECONDS"],
        "category_code": DEFAULTS["CATEGORY_CODE"],
    }
    payload.update(overrides)
    return payload


def create_reference_file_payload(**overrides) -> dict:
    """POST /api/reference-files input."""
    payload = {
        "rights_holder_name": "Test Rights Holder",
        "asset_kind": "AUDIO",
        "reference_fingerprint": DEFAULTS["FINGERPRINT"],
        "policy_mode": "MONETIZE",
        "claimed_segment_seconds": DEFAULTS["SEGMENT_SECONDS"],
    }
    payload.update(overrides)
    return payload


def create_claim_payload(content_item_id: str, reference_file_id: str, **overrides) -> dict:
    """POST /api/claims input."""
    payload = {
        "content_item_id": content_item_id,
        "reference_file_id": reference_file_id,
        "match_confidence": 0.900,
    }
    payload.update(overrides)
    return payload


def create_dispute_payload(expected_claim_version: int, **overrides) -> dict:
    """POST /api/claims/{id}/dispute input."""
    payload = {
        "expected_claim_version": expected_claim_version,
        "reason_code": "FAIR_USE",
    }
    payload.update(overrides)
    return payload


def create_appeal_payload(**overrides) -> dict:
    """POST /api/claims/{id}/appeals input."""
    payload = {"grounds_code": "REVIEW_ERROR"}
    payload.update(overrides)
    return payload


def create_revenue_routing_payload(content_item_id: str,
                                   expected_content_item_version: int,
                                   **overrides) -> dict:
    """POST /api/revenue-routings input."""
    payload = {
        "content_item_id": content_item_id,
        "stream_type": "AD",
        "gross_revenue_cents": DEFAULTS["GROSS_CENTS"],
        "expected_content_item_version": expected_content_item_version,
    }
    payload.update(overrides)
    return payload


def create_revenue_event_payload(**overrides) -> dict:
    """POST /api/channels/{id}/revenue-events input."""
    payload = {"stream_type": "AD", "amount_cents": DEFAULTS["GROSS_CENTS"]}
    payload.update(overrides)
    return payload


def create_strike_payload(**overrides) -> dict:
    """POST /api/channels/{id}/strikes input."""
    payload = {"kind": "COMMUNITY", "reason_code": "VIOLENT_CONTENT"}
    payload.update(overrides)
    return payload


def create_membership_schedule_payload(**overrides) -> dict:
    """POST /api/channels/{id}/membership-schedules input."""
    payload = {"tier_name": DEFAULTS["TIER_NAME"], "monthly_fee_cents": 1999}
    payload.update(overrides)
    return payload


def create_membership_payload(**overrides) -> dict:
    """POST /api/channels/{id}/memberships input."""
    payload = {"member_name": DEFAULTS["MEMBER_NAME"], "monthly_fee_cents": 499}
    payload.update(overrides)
    return payload


def create_classification_payload(category_codes, **overrides) -> dict:
    """POST /api/content-items/{id}/classifications input."""
    payload = {
        "category_codes": list(category_codes),
        "like_count": 10,
        "comment_count": 5,
    }
    payload.update(overrides)
    return payload


def create_payout_lock_payload(expected_channel_version: int, **overrides) -> dict:
    """POST /api/channels/{id}/payouts/lock input."""
    payload = {
        "period_start_at": PERIOD_START,
        "period_end_at": PERIOD_END,
        "expected_channel_version": expected_channel_version,
    }
    payload.update(overrides)
    return payload