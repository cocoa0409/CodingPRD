"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def assert_publisher(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["default_ad_share_bps"], int)
    assert 0 <= data["default_ad_share_bps"] <= 10000
    assert data["billing_model"] in ("GROSS_SHARE", "NET_OF_FEES")
    assert data["standing"] in ("GOOD", "PROBATION", "SUSPENDED", "TERMINATED")
    assert data["revenue_tier"] in ("STANDARD", "PREMIER")
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["outstanding_balance_cents"] >= 0


def assert_channel(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["publisher_id"], str) and data["publisher_id"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["category"] in ("VIDEO", "AUDIO", "GAME", "NEWS", "KIDS")
    assert data["content_rating"] in ("G", "PG", "R18")
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "IN_REVIEW", "CHANGES_REQUESTED",
        "CERTIFIED", "PUBLISHED", "SUSPENDED", "REMOVED",
    )
    assert isinstance(data["policy_hold"], bool)


def assert_channel_version(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["channel_id"], str) and data["channel_id"]
    assert isinstance(data["version_label"], str) and data["version_label"]
    assert data["review_status"] in (
        "SUBMITTED", "IN_REVIEW", "PASSED", "FAILED", "SUPERSEDED",
    )


def assert_viewer_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["email"], str) and data["email"]
    assert data["ad_consent"] in (
        "PERSONALIZED", "NON_PERSONALIZED", "OPTED_OUT",
    )
    assert isinstance(data["data_retention_opt_out"], bool)
    assert data["status"] in ("ACTIVE", "CLOSED")


def assert_subscription(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["channel_id"], str) and data["channel_id"]
    assert isinstance(data["price_cents"], int) and data["price_cents"] > 0
    assert data["billing_status"] in ("ACTIVE", "CANCELLED", "REFUNDED")
    assert data["entitlement_status"] in ("ENTITLED", "REVOKED")


def assert_ad_slot_grant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["channel_id"], str) and data["channel_id"]
    assert isinstance(data["total_slots"], int) and data["total_slots"] >= 1
    assert isinstance(data["publisher_share_bps"], int)
    assert isinstance(data["publisher_slots"], int)
    assert isinstance(data["platform_slots"], int)
    assert data["status"] in ("OPEN", "CLOSED")
    assert_slot_split_invariant(data)


def assert_slot_split_invariant(grant: dict):
    """INV-SLOT (PRD section 3.4): publisher_slots + platform_slots == total_slots."""
    assert (
        grant["publisher_slots"] + grant["platform_slots"]
        == grant["total_slots"]
    ), (
        f"INV-SLOT violated: {grant['publisher_slots']} + "
        f"{grant['platform_slots']} != {grant['total_slots']}"
    )


def assert_ad_campaign(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["publisher_id"], str) and data["publisher_id"]
    assert isinstance(data["channel_id"], str) and data["channel_id"]
    assert isinstance(data["budget_cents"], int) and data["budget_cents"] > 0
    assert data["targeting_mode"] in ("CONTEXTUAL", "PERSONALIZED")
    assert data["status"] in (
        "DRAFT", "SCHEDULED", "ACTIVE", "PAUSED", "COMPLETED", "CANCELLED",
    )
    assert isinstance(data["spent_cents"], int) and data["spent_cents"] >= 0
    assert isinstance(data["impressions_delivered"], int)


def assert_placement_booking(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["campaign_id"], str) and data["campaign_id"]
    assert isinstance(data["slot_code"], str) and data["slot_code"]
    assert data["status"] in ("HELD", "CONFIRMED", "RELEASED", "EXPIRED")


def assert_manufacturer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["royalty_per_device_cents"], int)
    assert data["royalty_per_device_cents"] >= 0
    assert data["license_status"] in ("LICENSED", "SUSPENDED", "REVOKED")


def assert_device_model(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["manufacturer_id"], str) and data["manufacturer_id"]
    assert isinstance(data["model_code"], str) and data["model_code"]
    assert data["recovery_policy"] in ("STRAIGHT_LINE", "MONETIZATION")
    assert data["cert_status"] in (
        "SUBMITTED", "LAB_TESTING", "CERTIFIED", "REJECTED", "DECERTIFIED",
    )
    assert data["update_compliance"] in ("COMPLIANT", "GRACE", "OVERDUE")


def assert_lab_booking(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["device_model_id"], str) and data["device_model_id"]
    assert isinstance(data["bench_code"], str) and data["bench_code"]
    assert data["status"] in ("BOOKED", "COMPLETED", "CANCELLED")


def assert_os_update(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["version_tag"], str) and data["version_tag"]
    assert isinstance(data["mandatory"], bool)
    assert data["status"] in ("ANNOUNCED", "ROLLING", "WITHDRAWN")


def assert_device_unit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["device_model_id"], str) and data["device_model_id"]
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert isinstance(data["hardware_cost_cents"], int)
    assert data["hardware_cost_cents"] > 0
    assert isinstance(data["sale_price_cents"], int)
    assert data["sale_price_cents"] >= 0
    assert data["status"] in (
        "MANUFACTURED", "SOLD", "ACTIVATED", "DEACTIVATED",
    )
    assert_subsidy_invariant(data)


def assert_subsidy_invariant(unit: dict):
    """INV-SUBSIDY (PRD section 3.10):
    subsidy_cents == recovered + written_off + outstanding."""
    total = (
        unit["subsidy_recovered_cents"]
        + unit["subsidy_written_off_cents"]
        + unit["subsidy_outstanding_cents"]
    )
    assert unit["subsidy_cents"] == total, (
        f"INV-SUBSIDY violated: subsidy {unit['subsidy_cents']} != "
        f"{unit['subsidy_recovered_cents']} + "
        f"{unit['subsidy_written_off_cents']} + "
        f"{unit['subsidy_outstanding_cents']}"
    )


def assert_revenue_statement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["publisher_id"], str) and data["publisher_id"]
    assert isinstance(data["period"], str) and len(data["period"]) == 7
    assert data["status"] in ("OPEN", "FINALIZED", "DISPUTED", "SETTLED")
    assert isinstance(data["subscription_gross_cents"], int)
    assert isinstance(data["refund_cents"], int)
    assert isinstance(data["charge_count"], int)
    assert isinstance(data["net_payout_cents"], int)


def assert_dispute(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["publisher_id"], str) and data["publisher_id"]
    assert data["subject_type"] in ("CHANNEL_REMOVAL", "STATEMENT")
    assert data["status"] in (
        "FILED", "TRIAGE", "EVIDENCE", "DECIDED", "APPEALED", "CLOSED",
    )
