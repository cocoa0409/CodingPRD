"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"


def _assert_versioned(data):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an integer starting at 1"


def assert_member(data: dict):
    _assert_versioned(data)
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["status"] in ["PENDING_ENROLLMENT", "ACTIVE", "SUSPENDED", "TERMINATED"]
    assert data["verification_level"] in ["NONE", "BIOMETRIC_ID", "FEDERAL_TRUSTED"]
    assert isinstance(data["document_reject_count_90d"], int)
    assert isinstance(data["risk_score"], int) and data["risk_score"] >= 0


def assert_enrollment(data: dict):
    _assert_versioned(data)
    assert data["status"] in ["DRAFT", "DOCUMENT_VERIFIED", "BIOMETRIC_CAPTURED",
                              "FRAUD_REVIEW", "COMPLETED", "REJECTED", "SUPERSEDED"]
    assert data["site_type"] in ["KIOSK", "ENROLLMENT_CENTER"]
    assert data["document_type"] in ["PASSPORT", "DRIVERS_LICENSE", "STATE_ID"]


def assert_kiosk(data: dict):
    _assert_versioned(data)
    assert data["status"] in ["PROVISIONING", "ACTIVE", "SUSPENDED", "RETIRED"]
    assert isinstance(data["consecutive_capture_failures"], int)


def assert_enrollment_center(data: dict):
    _assert_versioned(data)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["ambassador_capacity"], int) and data["ambassador_capacity"] >= 1


def assert_ambassador(data: dict):
    _assert_versioned(data)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_airport(data: dict):
    _assert_versioned(data)
    assert data["status"] in ["ONBOARDING", "ACTIVE", "SUSPENDED"]
    assert isinstance(data["iata_code"], str) and len(data["iata_code"]) == 3


def assert_agreement(data: dict):
    _assert_versioned(data)
    assert data["status"] in ["DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED", "EXPIRED"]
    assert 0 < data["rev_share_rate"] <= 0.30
    assert 0 < data["subscription_share_rate"] <= 0.30
    assert isinstance(data["monthly_minimum_cents"], int) and data["monthly_minimum_cents"] >= 0
    assert isinstance(data["lane_capacity"], int) and data["lane_capacity"] >= 0


def assert_lane(data: dict):
    _assert_versioned(data)
    assert data["status"] in ["PLANNED", "OPEN", "MAINTENANCE", "CLOSED"]
    assert isinstance(data["position_index"], int) and data["position_index"] >= 1
    assert 1 <= data["capacity_hours"] <= 24


def assert_venue(data: dict):
    _assert_versioned(data)
    assert data["venue_type"] in ["STADIUM", "ARENA", "OTHER"]
    assert data["access_rule_mode"] in ["AGE_18_PLUS", "AGE_21_PLUS", "ALL_MEMBERS"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_venue_event(data: dict):
    _assert_versioned(data)
    assert data["status"] in ["SCHEDULED", "CANCELLED"]
    assert 0 <= data["buffer_hours"] <= 12


def assert_subscription(data: dict):
    _assert_versioned(data)
    assert data["plan"] in ["INDIVIDUAL", "FAMILY"]
    assert data["status"] in ["ACTIVE", "PAST_DUE", "CANCELLED"]
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert 1 <= data["billing_cycle_day"] <= 28


def assert_family_group(data: dict):
    _assert_versioned(data)
    assert data["status"] in ["ACTIVE", "DISSOLVED"]
    assert 2 <= data["slots_total"] <= 3
    assert 0 <= data["slots_used"] <= data["slots_total"], \
        "invariant: slots_used <= slots_total"


def assert_discount(data: dict):
    _assert_versioned(data)
    assert data["status"] in ["ACTIVE", "EXHAUSTED", "SUSPENDED"]
    assert 1 <= data["percent_off"] <= 100
    assert data["max_redemptions"] >= 1
    assert data["redemptions_used"] >= 0


def assert_lane_verification(data: dict):
    _assert_versioned(data)
    assert data["escort_status"] in ["PENDING", "ESCORTED", "EXPIRED"]
    assert isinstance(data["version_confirmed"], int)


def assert_venue_access_event(data: dict):
    _assert_versioned(data)
    assert data["outcome"] in ["ADMITTED", "REJECTED"]
    if data["outcome"] == "REJECTED":
        assert data.get("reject_reason") in [
            "AGE_RULE", "VENUE_SUSPENDED", "MEMBER_INELIGIBLE", "NO_ACTIVE_EVENT"
        ]


def assert_dispute(data: dict):
    _assert_versioned(data)
    assert data["status"] in ["OPEN", "INVESTIGATING", "RESOLVED_CLEAR",
                              "RESOLVED_CONFIRMED"]
    assert data["reason"] in ["IDENTITY_TAKEOVER", "BIOMETRIC_FALSE_MATCH",
                              "DOCUMENT_FRAUD", "DATA_ERROR"]


def assert_retention_log(data: dict):
    # Append-only audit row: id + created_at only — NO updated_at, NO version.
    _assert_common(data)
    assert "updated_at" not in data, "retention log rows must not carry updated_at"
    assert "version" not in data, "retention log rows must not carry version"
    assert data["action"] in ["DELETION_SCHEDULED", "DELETED", "AUDIT_EXPORTED"]


def assert_settlement(data: dict):
    _assert_versioned(data)
    assert data["status"] in ["DRAFT", "FINALIZED", "PAID"]
    assert data["calculation_variant"] in ["AIRPORT", "VENUE"]
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0


def assert_invoice(data: dict):
    _assert_versioned(data)
    assert data["status"] in ["DUE", "PAID", "FAILED", "VOID"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0
