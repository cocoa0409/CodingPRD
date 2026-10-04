"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def assert_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "account id must be a valid UUID"
    assert isinstance(data["email"], str) and data["email"]
    assert data["region_code"] in ("NA", "LATAM", "EMEA", "APAC")
    assert data["plan_tier"] in ("BASIC", "STANDARD", "PREMIUM")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CANCELLED")
    assert data["verification_posture"] in ("VERIFIED", "CHALLENGE_PENDING", "LOCKED")
    assert isinstance(data["billing_anchor_day"], int) and 1 <= data["billing_anchor_day"] <= 28
    assert isinstance(data["owner_member_id"], str)
    assert isinstance(data["extra_member_billed_cents"], int)
    assert isinstance(data["extra_member_credit_cents"], int)
    assert isinstance(data["extra_member_net_revenue_cents"], int)
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int)


def assert_household(data: dict):
    assert is_valid_uuid(data.get("id", "")), "household id must be a valid UUID"
    assert isinstance(data["account_id"], str)
    assert isinstance(data["label"], str)
    assert isinstance(data["primary_location"], str)
    assert isinstance(data["network_fingerprint"], str)
    assert isinstance(data["geo_cell"], str)
    assert data["status"] in ("ESTABLISHED", "RELOCATING", "DISSOLVED")
    assert isinstance(data["trusted_device_count"], int)
    assert data.get("last_verified_at") is None or isinstance(data["last_verified_at"], str)
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int)


def assert_member(data: dict):
    assert is_valid_uuid(data.get("id", "")), "member id must be a valid UUID"
    assert isinstance(data["account_id"], str)
    assert isinstance(data["display_name"], str)
    assert data["member_role"] in ("OWNER", "HOUSEHOLD", "EXTRA")
    assert data["status"] in ("ACTIVE", "REMOVED")
    assert isinstance(data["current_streams"], int)
    assert isinstance(data["downloads_used_this_month"], int)
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int)


def assert_device(data: dict):
    assert is_valid_uuid(data.get("id", "")), "device id must be a valid UUID"
    assert isinstance(data["household_id"], str)
    assert isinstance(data["device_label"], str)
    assert data["device_type"] in ("TV", "MOBILE", "WEB", "CONSOLE")
    assert isinstance(data["network_fingerprint"], str)
    assert isinstance(data["geo_cell"], str)
    assert data["trust_status"] in ("UNTRUSTED", "TRUSTED", "REMOVED")
    assert is_iso8601_timestamp(data["last_signal_at"])
    assert isinstance(data["travel_pass_active"], bool)
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int)


def assert_slot(data: dict):
    assert is_valid_uuid(data.get("id", "")), "slot id must be a valid UUID"
    assert isinstance(data["account_id"], str)
    assert data.get("member_id") is None or isinstance(data["member_id"], str)
    assert isinstance(data["payer_member_id"], str)
    assert data["transfer_rights"] in ("TRANSFERABLE", "LOCKED")
    assert data["status"] in ("OFFERED", "ACTIVE", "REVOKED", "LAPSED")
    assert isinstance(data["slot_index"], int) and data["slot_index"] >= 1
    assert isinstance(data["price_cents_snapshot"], int)
    assert isinstance(data["credit_cents"], int)
    assert isinstance(data["purchased_day"], int)
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int)


def assert_challenge(data: dict):
    assert is_valid_uuid(data.get("id", "")), "challenge id must be a valid UUID"
    assert isinstance(data["account_id"], str)
    assert data["channel"] in ("EMAIL", "SMS", "VOICE_CALL")
    assert data["challenge_reason"] in ("NEW_DEVICE", "PERIODIC", "LOCATION_DRIFT")
    assert isinstance(data["code"], str) and len(data["code"]) == 6 and data["code"] != "000000"
    assert data["status"] in ("PENDING", "VERIFIED", "EXPIRED", "LOCKED_OUT")
    assert isinstance(data["attempts_used"], int)
    assert is_iso8601_timestamp(data["expires_at"])
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int)


def assert_travel_pass(data: dict):
    assert is_valid_uuid(data.get("id", "")), "travel pass id must be a valid UUID"
    assert isinstance(data["device_id"], str)
    assert data["grant_type"] in ("TEMPORARY_14D", "TEMPORARY_30D")
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert data["status"] in ("ACTIVE", "EXPIRED", "REVOKED", "CONVERTED")
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int)


def assert_transfer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "transfer id must be a valid UUID"
    assert isinstance(data["source_account_id"], str)
    assert isinstance(data["member_id"], str)
    assert isinstance(data["target_email"], str)
    assert data["status"] in ("AWAITING_ACCEPTANCE", "COMPLETED", "CANCELLED", "EXPIRED")
    assert is_iso8601_timestamp(data["expires_at"])
    assert isinstance(data["history_snapshot"], list)
    assert isinstance(data["recommendation_snapshot"], str)
    assert data.get("target_account_id") is None or isinstance(data["target_account_id"], str)
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int)


def assert_playback_session(data: dict):
    """Append-only resource: id + created_at only among the common fields."""
    assert is_valid_uuid(data.get("id", "")), "session id must be a valid UUID"
    assert isinstance(data["member_id"], str)
    assert isinstance(data["device_id"], str)
    assert data["requested_resolution"] in ("SD", "HD", "UHD")
    assert data["resolution_granted"] in ("SD", "HD", "UHD")
    assert data["status"] in ("ACTIVE", "ENDED")
    assert is_iso8601_timestamp(data["started_at"])
    assert data.get("ended_at") is None or isinstance(data["ended_at"], str)
    assert is_iso8601_timestamp(data["created_at"])


def assert_download(data: dict):
    """Append-only resource: id + created_at only among the common fields."""
    assert is_valid_uuid(data.get("id", "")), "download id must be a valid UUID"
    assert isinstance(data["member_id"], str)
    assert isinstance(data["device_id"], str)
    assert isinstance(data["title_id"], str)
    assert data["status"] in ("ACTIVE", "EXPIRED", "DELETED")
    assert isinstance(data["billing_month"], str) and len(data["billing_month"]) == 7
    assert is_iso8601_timestamp(data["created_at"])


def assert_policy(data: dict):
    assert is_valid_uuid(data.get("id", "")), "policy id must be a valid UUID"
    assert data["region_code"] in ("NA", "LATAM", "EMEA", "APAC")
    assert isinstance(data["enforcement_enabled"], bool)
    assert isinstance(data["grace_days"], int) and data["grace_days"] >= 0
    assert data["messaging_variant"] in ("SOFT", "HARD")
    assert is_iso8601_timestamp(data["effective_from"])
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int)


def assert_enforcement_metric(data: dict):
    """Append-only resource: id + created_at only among the common fields."""
    assert is_valid_uuid(data.get("id", "")), "metric id must be a valid UUID"
    assert isinstance(data["account_id"], str)
    assert data["metric_type"] in ("CHURN_SIGNAL", "COMPLAINT", "WINBACK")
    assert isinstance(data["notes"], str)
    assert is_iso8601_timestamp(data["recorded_at"])
    assert is_iso8601_timestamp(data["created_at"])


def assert_revenue_invariants(account: dict):
    """The net-revenue counter is always billed lifetime gross minus lifetime credits."""
    assert (
        account["extra_member_net_revenue_cents"]
        == account["extra_member_billed_cents"] - account["extra_member_credit_cents"]
    ), (
        f"net revenue {account['extra_member_net_revenue_cents']} != billed "
        f"{account['extra_member_billed_cents']} - credit {account['extra_member_credit_cents']}"
    )
    assert account["extra_member_billed_cents"] >= 0
    assert account["extra_member_credit_cents"] >= 0
