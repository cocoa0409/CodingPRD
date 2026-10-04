"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp, assert_cost_precision,
)


def assert_distributor(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["distributor_name"], str) and data["distributor_name"]
    assert isinstance(data["guarantee_floor_cents"], int)
    assert isinstance(data["ticket_price_default_cents"], int)
    assert isinstance(data["bookable_title_count"], int) and data["bookable_title_count"] >= 0


def assert_circuit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)
    assert data["status"] in ["PENDING", "ACCREDITED", "SUSPENDED"]
    assert data["credit_rating"] in ["A", "B", "C"]
    assert data["settlement_terms"] in ["NET_30", "NET_60", "GROSS_ON_GROSS", "FOUR_WALL"]
    assert isinstance(data["screen_pool_total"], int) and data["screen_pool_total"] >= 1
    assert isinstance(data["committed_screens_balance"], int)
    assert data["committed_screens_balance"] >= 0


def assert_theater(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)
    assert data["status"] in ["ACTIVE", "DARK", "SUSPENDED"]
    assert isinstance(data["circuit_id"], str) and data["circuit_id"]
    assert isinstance(data["seats_total"], int) and data["seats_total"] >= 1
    assert isinstance(data["screen_count"], int) and data["screen_count"] >= 1
    assert isinstance(data["showtime_buffer_minutes"], int)
    assert isinstance(data["pending_rekey_count"], int) and data["pending_rekey_count"] >= 0


def assert_title(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)
    assert data["status"] in ["DRAFT", "BOOKABLE", "CLEARED", "RIGHTS_EXPIRED",
                              "WITHDRAWN", "ARCHIVED"]
    assert data["content_type"] in ["CONCERT", "ANNIVERSARY", "FAITH",
                                    "LIVE_BROADCAST", "SPECIAL"]
    assert isinstance(data["is_live"], bool)
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] >= 1
    assert isinstance(data["territory_state_codes"], list)
    assert len(data["territory_state_codes"]) >= 1
    assert isinstance(data["max_screen_commitment"], int)
    assert isinstance(data["bookable_window_days"], int)
    assert isinstance(data["booking_count"], int) and data["booking_count"] >= 0


def assert_booking(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)
    assert data["status"] in ["DRAFT", "PENDING_APPROVAL", "COUNTERED", "APPROVED",
                              "ON_SALE", "ON_HOLD", "CONFIRMED", "CANCELLED",
                              "SETTLED", "TERMINAL"]
    assert data["showtime_count"] in (1, 2)
    assert isinstance(data["showtime_plan"], list)
    assert len(data["showtime_plan"]) == data["showtime_count"]
    assert isinstance(data["guarantee_cents"], int)
    assert isinstance(data["revenue_share_pct"], (int, float))
    assert isinstance(data["committed_screens_total"], int)
    assert isinstance(data["guarantee_ceiling_cents"], int)
    assert isinstance(data["pre_sale_tickets"], int) and data["pre_sale_tickets"] >= 0
    assert isinstance(data["live_feed_event_count"], int)
    assert isinstance(data["makegood_credit_cents"], int)


def assert_booking_line(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)
    assert data["exhibit_state"] in ["PROPOSED", "COMMITTED", "RELEASED"]
    assert isinstance(data["committed_screens"], int) and data["committed_screens"] >= 1
    assert isinstance(data["expected_attendance"], int) and data["expected_attendance"] >= 0
    assert isinstance(data["sold_tickets"], int)
    assert isinstance(data["guarantee_applied_cents"], int)
    assert isinstance(data["credit_issued_cents"], int)


def assert_screening(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)
    assert data["state"] in ["SCHEDULED", "SCREENED", "SKIPPED_INCOMPLETE",
                             "SKIPPED_CANCELLED", "VOID"]
    assert isinstance(data["is_encore"], bool)
    assert isinstance(data["auditorium"], str) and data["auditorium"]


def assert_encore_window(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)
    assert data["status"] in ["DRAFT", "SCHEDULED", "WITHDRAWN", "EXPIRED"]
    assert isinstance(data["derived_encore_price_cents"], int)
    assert isinstance(data["encore_screening_count"], int)


def assert_content_delivery(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)
    assert data["status"] in ["SCHEDULED", "DELIVERED", "VERIFIED", "FAILED"]
    assert data["delivery_method"] in ["SATELLITE", "FILE", "BOTH"]


def assert_encryption_key(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)
    assert data["issuance_status"] in ["PENDING", "ISSUED", "REVOKED"]
    assert data["validity_state"] in ["NOT_YET_VALID", "VALID", "EXPIRED"]
    assert is_iso8601_timestamp(data["not_valid_before_utc"])
    assert is_iso8601_timestamp(data["not_valid_after_utc"])


def assert_feed_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)
    assert data["state"] in ["DETECTED", "CONFIRMED", "VOIDED", "RESOLVED"]
    assert data["failure_type"] in ["FEED_LOSS", "CONTENT_FAILURE",
                                    "SATELLITE_OUTAGE", "KEY_FAILURE"]
    assert isinstance(data["outage_minutes"], int) and data["outage_minutes"] >= 0
    assert isinstance(data["affected_screening_count"], int)


def assert_settlement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)
    assert data["status"] in ["OPEN", "CLOSED", "REOPENED"]
    for field in ("gross_box_office_cents", "topup_paid_cents", "adjustment_cents",
                  "feed_failure_credit_cents", "makegood_credit_cents",
                  "distributor_net_cents", "exhibitor_net_cents",
                  "invariant_drift_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer cent count"


def assert_no_fractional_cents(data: dict, field_names):
    """Every money field must be an integer number of cents (PRD §2.7)."""
    for name in field_names:
        if name in data and data[name] is not None:
            assert isinstance(data[name], int), (
                f"{name} must be an integer cent count, got {data[name]!r}")


def assert_settlement_invariant(data: dict):
    """distributor_net + exhibitor_net == gross + topup + adjustment (PRD §3.6)."""
    total = (data["gross_box_office_cents"] + data["topup_paid_cents"]
             + data["adjustment_cents"])
    assert data["distributor_net_cents"] + data["exhibitor_net_cents"] == total, (
        "settlement must conserve money: "
        f"{data['distributor_net_cents']} + {data['exhibitor_net_cents']} != {total}"
    )
    assert data["invariant_drift_cents"] == 0


def assert_cost_precision_cents(value):
    assert_cost_precision(value)


def assert_booking_invariants(data: dict):
    """Derived counters stay non-negative and consistent (PRD §2.10)."""
    assert data["committed_screens_total"] >= 0
    assert data["pre_sale_tickets"] >= 0
    assert data["live_feed_event_count"] >= 0
    assert data["makegood_credit_cents"] >= 0


def assert_theater_invariants(data: dict):
    assert data["pending_rekey_count"] >= 0
    assert data["status"] in ["ACTIVE", "DARK", "SUSPENDED"]