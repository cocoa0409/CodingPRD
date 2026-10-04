"""Entity assertions and domain invariant checkers (PRD §2.5, §2.8)."""
import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

COMMON_FIELD_ENTITIES = (
    "Channel",
    "ContentItem",
    "ReferenceFile",
    "Claim",
    "CopyrightStrike",
    "ChannelStrike",
    "MembershipSchedule",
    "ChannelMembership",
    "PayoutBatch",
)


def assert_common_fields(data: dict, expect_version: bool = True):
    """Every resource with the common field set carries a bare UUID id, an
    ISO 8601 created_at and updated_at, and a version counter (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    if expect_version:
        assert isinstance(data.get("version"), int), "version must be an integer"


def assert_append_only_fields(data: dict):
    """Sub-resources without the common field set expose an id and a creation
    timestamp only — no updated_at, no version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "an append-only sub-resource carries no updated_at"
    assert "version" not in data, "an append-only sub-resource carries no version"


def assert_channel(data: dict):
    assert_common_fields(data)
    assert isinstance(data["channel_name"], str) and data["channel_name"]
    assert isinstance(data["country_code"], str) and len(data["country_code"]) == 2
    assert isinstance(data["lifetime_watch_hours"], int)
    assert isinstance(data["subscriber_count"], int)
    assert data["monetization_status"] in [
        "MONETIZATION_NOT_APPLIED", "MONETIZATION_PENDING", "MONETIZATION_APPROVED",
        "MONETIZATION_REJECTED", "MONETIZATION_REVOKED",
    ]
    assert data["monetization_posture"] in ["OPEN", "RESTRICTED", "FROZEN"]
    assert data["tax_tin_status"] in ["TIN_MISSING", "TIN_PROVIDED"]
    assert isinstance(data["copyright_strike_count"], int)
    assert isinstance(data["policy_strike_count"], int)
    assert isinstance(data["payment_threshold_cents"], int)


def assert_content_item(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["channel_id"]), "channel_id must be a bare UUID"
    assert data["upload_status"] in [
        "UPLOADED", "CLASSIFYING", "CLASSIFIED", "CLAIM_SCAN_COMPLETE",
    ]
    assert data["ad_suitability"] in [None, "AD_FRIENDLY", "LIMITED_ADS", "NO_ADS"]
    assert isinstance(data["gross_revenue_cents"], int)
    assert isinstance(data["routed_revenue_cents"], int)
    assert isinstance(data["holds_revenue"], bool)
    assert isinstance(data["takedown_flag"], bool)


def assert_reference_file(data: dict):
    assert_common_fields(data)
    assert data["asset_kind"] in ["AUDIO", "VIDEO", "VISUAL"]
    assert data["policy_mode"] in ["MONETIZE", "TRACK", "BLOCK"]
    assert isinstance(data["claimed_segment_seconds"], int)
    assert isinstance(data["is_active"], bool)


def assert_claim(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["content_item_id"]), "content_item_id must be a bare UUID"
    assert is_valid_uuid(data["reference_file_id"]), "reference_file_id must be a bare UUID"
    assert data["source"] in ["REFERENCE_AUTO", "MANUAL"]
    assert data["status"] in [
        "ACTIVE", "DISPUTED", "APPEALED", "REINSTATED", "RELEASED", "TAKEN_DOWN",
    ]
    assert data["claim_level"] in ["STANDARD", "HIGH"]
    assert data["lock_reason"] in ["NONE", "PENDING_RETRO", "RETROACTIVE_OWED"]
    assert isinstance(data["appeal_attempts"], int)
    assert isinstance(data["appeal_count"], int)
    assert isinstance(data["copyright_counter_notified"], bool)
    # revenue_locked is true exactly while lock_reason is not NONE (PRD §3.4).
    assert data["revenue_locked"] == (data["lock_reason"] != "NONE")


def assert_claim_dispute(data: dict):
    assert_append_only_fields(data)
    assert data["reason_code"] in [
        "FAIR_USE", "LICENSED", "PUBLIC_DOMAIN", "MISMATCH", "OWNERSHIP",
    ]
    assert data["status"] in ["FILED", "RELEASED"]


def assert_claim_appeal(data: dict):
    assert_append_only_fields(data)
    assert data["appeal_level"] in ["FIRST", "SECOND"]
    assert data["grounds_code"] in ["REVIEW_ERROR", "NEW_EVIDENCE", "MISIDENTIFIED"]
    assert data["status"] in ["PENDING", "UPHELD", "DENIED"]


def assert_copyright_strike(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["channel_id"]), "channel_id must be a bare UUID"
    assert data["status"] in ["ACTIVE", "EXPIRED"]
    assert isinstance(data["strike_sequence"], int)
    assert is_iso8601_timestamp(data["expires_at"]), "expires_at must be ISO 8601"


def assert_channel_strike(data: dict):
    assert_common_fields(data)
    assert data["kind"] == "COMMUNITY"
    assert data["reason_code"] in ["SEXUAL_CONTENT", "VIOLENT_CONTENT", "HATE_SPEECH"]
    assert data["status"] in ["ACTIVE", "EXPIRED"]
    assert is_iso8601_timestamp(data["issued_at"]), "issued_at must be ISO 8601"
    assert is_iso8601_timestamp(data["expires_at"]), "expires_at must be ISO 8601"


def assert_membership_schedule(data: dict):
    assert_common_fields(data)
    assert isinstance(data["tier_name"], str) and data["tier_name"]
    assert isinstance(data["monthly_fee_cents"], int)
    assert isinstance(data["perks"], list)
    for field in ("creator_share_cents", "platform_share_cents",
                  "network_fee_cents", "member_charge_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer count of cents"


def assert_channel_membership(data: dict):
    assert_common_fields(data)
    assert isinstance(data["member_name"], str) and data["member_name"]
    assert data["status"] == "ACTIVE"
    assert isinstance(data["paid_member_months"], int)
    assert isinstance(data["payout_cents"], int)


def assert_payout_batch(data: dict):
    assert_common_fields(data)
    assert data["stage"] in ["ROUTE", "PAYOUT"]
    assert data["status"] in ["LOCKED", "RELEASED", "FAILED"]
    for field in ("gross_cents", "creator_share_cents", "partner_share_cents",
                  "held_cents", "tax_withheld_cents", "adjusted_net_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer count of cents"


def assert_revenue_routing(data: dict):
    assert_append_only_fields(data)
    assert data["stream_type"] in ["AD", "MEMBERSHIP", "SUPER_CHAT", "SHOPPING"]
    assert data["status"] in [
        "ESCROW", "PAID_CREATOR", "RETROACTIVE_OWED", "RELEASED_TO_CREATOR",
    ]
    assert isinstance(data["gross_revenue_cents"], int)
    assert isinstance(data["creator_share_cents"], int)
    assert isinstance(data["partner_share_cents"], int)
    assert_share_conservation(data)


def assert_revenue_event(data: dict):
    assert_append_only_fields(data)
    assert data["stream_type"] in ["AD", "MEMBERSHIP", "SUPER_CHAT", "SHOPPING"]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["routed"], bool)
    assert is_iso8601_timestamp(data["occurred_at"]), "occurred_at must be ISO 8601"


def assert_ad_review(data: dict):
    assert_append_only_fields(data)
    assert data["outcome"] in ["AD_FRIENDLY", "LIMITED_ADS", "NO_ADS"]
    assert data["appeal_outcome"] in ["NONE", "UPHELD"]
    assert isinstance(data["is_visible"], bool)
    assert isinstance(data["reason_codes"], list)
    assert isinstance(data["matched_categories"], list)


# ─── Domain invariant checkers ───────────────────────

def assert_share_conservation(routing: dict):
    """creator_share_cents + partner_share_cents always equals the record's
    gross_revenue_cents with no drift (PRD §3.8)."""
    assert routing["creator_share_cents"] + routing["partner_share_cents"] == \
        routing["gross_revenue_cents"], (
            "the two shares must sum exactly to the record's gross amount")


def assert_item_invariants(data: dict):
    """ContentItem invariants that hold after any operation (PRD §3.8)."""
    assert data["gross_revenue_cents"] >= 0
    assert data["routed_revenue_cents"] >= 0
    assert data["routed_revenue_cents"] <= data["gross_revenue_cents"]
    assert isinstance(data["holds_revenue"], bool)


def assert_channel_posture_matches_facts(channel: dict):
    """monetization_posture is derived, never stored independently: the four
    ordered branches of PRD §2.4 must reproduce the reported value."""
    if channel["monetization_status"] == "MONETIZATION_REVOKED":
        expected = "FROZEN"
    elif channel["policy_strike_count"] > 0:
        expected = "RESTRICTED"
    elif channel["copyright_strike_count"] >= 2:
        expected = "RESTRICTED"
    else:
        expected = "OPEN"
    assert channel["monetization_posture"] == expected, (
        f"posture {channel['monetization_posture']} does not follow from "
        f"status={channel['monetization_status']}, "
        f"policy_strike_count={channel['policy_strike_count']}, "
        f"copyright_strike_count={channel['copyright_strike_count']}")


def assert_cents(value, label: str = "amount"):
    """Every monetary quantity is an integer count of cents (PRD §2.8)."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer count of cents, got {value!r}")
    rounded = round(float(value))
    assert rounded == pytest.approx(float(value)), f"{label} must not carry fractional cents"