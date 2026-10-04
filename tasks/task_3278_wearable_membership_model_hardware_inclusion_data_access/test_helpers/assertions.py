"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_member(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["member_status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["wallet_credit_cents"], int)
    assert data["data_sharing_posture"] in ["NORMAL", "SUPPRESSED"]
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at ISO 8601"
    assert isinstance(data["version"], int)


def assert_membership_term(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be valid UUID"
    assert data["term_status"] in [
        "ACTIVE",
        "PAUSED",
        "PAST_DUE",
        "CANCELLED_EARLY",
        "COMPLETED",
    ]
    assert data["hardware_tier"] in ["BAND_STD", "BAND_PRO"]
    assert data["cancel_fee_policy"] in ["REMAINING_MONTHS", "PAID_MONTHS_FLOOR"]
    assert isinstance(data["months_paid"], int)
    assert isinstance(data["pause_days_used"], int)
    assert isinstance(data["pause_windows"], list)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int)


def assert_device(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["device_status"] in [
        "PROVISIONED",
        "ACTIVE",
        "SUSPECT_FAULT",
        "RMA_INBOUND",
        "RETIRED",
    ]
    assert data["hardware_tier"] in ["BAND_STD", "BAND_PRO"]
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert isinstance(data["version"], int)


def assert_daily_metric_set(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["algorithm_version"], int)
    assert data["interpretation_status"] in ["CURRENT", "STALE", "RECOMPUTED"]
    assert isinstance(data["recovery_score"], int)
    assert isinstance(data["sleep_performance_pct"], int)
    assert isinstance(data["strain_score"], (int, float))
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_algorithm_release(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["release_status"] in ["DRAFT", "PUBLISHED", "SUPERSEDED"]
    assert isinstance(data["requires_member_ack"], bool)


def assert_team(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["team_type"] in ["SPORTS", "CORPORATE_WELLNESS"]
    assert isinstance(data["coach_user_id"], str) and data["coach_user_id"]


def assert_team_membership(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["membership_status"] in ["ACTIVE", "REMOVED"]
    assert isinstance(data["consent_scopes"], list)
    assert isinstance(data["version"], int)
    for entry in data["consent_scopes"]:
        assert entry["scope"] in ["STRAIN", "RECOVERY", "SLEEP"]
        assert entry["status"] in ["GRANTED", "REVOKED", "EXPIRED"]


def assert_research_study(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["study_status"] in ["RECRUITING", "CLOSED"]
    assert isinstance(data["min_paid_months"], int)


def assert_research_enrollment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["enrollment_status"] in ["ENROLLED", "WITHDRAWN"]
    assert isinstance(data["member_seq"], int) and data["member_seq"] >= 1


def assert_replacement_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["request_status"] in ["OPEN", "APPROVED", "REJECTED", "COMPLETED"]
    assert data["reason"] in ["HARDWARE_FAILURE", "BATTERY_DRAIN", "SENSOR_DRIFT"]


def assert_merch_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["order_status"] in ["PAID", "CANCELLED"]
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["member_discount_cents"], int)
    assert isinstance(data["bundle_discount_cents"], int)
    assert isinstance(data["discount_cents"], int)
    assert isinstance(data["total_cents"], int)


def assert_merch_pricing_invariants(order: dict):
    """Domain invariants that must hold for any merch order response."""
    assert order["total_cents"] == order["subtotal_cents"] - order["discount_cents"]
    assert order["discount_cents"] == min(
        order["member_discount_cents"] + order["bundle_discount_cents"],
        round_half_up_int(order["subtotal_cents"] * 30 / 100),
    )
    assert order["discount_cents"] >= 0


def round_half_up_int(value: float) -> int:
    """Round half-up to a whole number, per the PRD's rounding rule."""
    import math

    return math.floor(value + 0.5)
