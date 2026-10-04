"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_system_fields(data: dict):
    """Standard system-managed fields per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version starts at 1"


def assert_site(data: dict):
    _assert_system_fields(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["code"], str) and 1 <= len(data["code"]) <= 40


def assert_assessment(data: dict):
    _assert_system_fields(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED")
    assert isinstance(data["forklift_count"], int) and data["forklift_count"] >= 1


def assert_supply_contract(data: dict):
    _assert_system_fields(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "EXPIRED", "TERMINATED")
    assert data["supply_mode"] in ("DELIVERED_LIQUID", "ON_SITE_GENERATION", "PIPELINE")


def assert_station(data: dict):
    _assert_system_fields(data)
    assert data["construction_status"] in (
        "PLANNED", "PERMITTED", "CONSTRUCTION", "COMMISSIONED", "SUSPENDED")
    assert data["location_type"] in ("INDOOR", "OUTDOOR")


def assert_permit(data: dict):
    _assert_system_fields(data)
    assert data["status"] in ("PENDING", "ISSUED", "REJECTED", "EXPIRED")
    assert data["permit_type"] in ("CONSTRUCTION", "FIRE", "DISPENSING_INDOOR")


def assert_conversion_plan(data: dict):
    _assert_system_fields(data)
    assert data["status"] in ("DRAFT", "SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")


def assert_conversion_event(data: dict):
    _assert_system_fields(data)
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")


def assert_technician(data: dict):
    _assert_system_fields(data)
    assert data["certification_level"] in ("BASIC", "ADVANCED", "MASTER")


def assert_service_agreement(data: dict):
    _assert_system_fields(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "TERMINATED", "EXPIRED")


def assert_fueling_event(data: dict):
    _assert_system_fields(data)
    assert data["kg_dispensed"] > 0


def assert_invoice(data: dict):
    _assert_system_fields(data)
    assert data["status"] in ("DRAFT", "ISSUED", "PAID", "DISPUTED", "VOID")
    for money in ("subtotal_cents", "credit_cents", "total_cents"):
        assert isinstance(data[money], int), f"{money} must be integer cents (PRD §2.8)"
    assert_invoice_money_invariants(data)


def assert_invoice_money_invariants(data: dict):
    """Invoice money invariants from PRD §3.6: total = max(0, subtotal - credit),
    credit never exceeds subtotal, total never negative."""
    assert data["credit_cents"] >= 0, "credit_cents must be >= 0"
    assert data["total_cents"] >= 0, "total_cents is floored at zero"
    assert data["credit_cents"] <= data["subtotal_cents"], "credit capped at subtotal"
    assert data["total_cents"] == max(0, data["subtotal_cents"] - data["credit_cents"]), (
        "total_cents = subtotal_cents - credit_cents, floored at zero")


def assert_line_item(data: dict):
    _assert_system_fields(data)
    assert data["kg"] > 0
    assert isinstance(data["line_amount_cents"], int)


def assert_incentive_claim(data: dict):
    _assert_system_fields(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED")
    assert data["incentive_type"] in ("FEDERAL_ITC", "STATE_REBATE", "UTILITY_GRANT")


def assert_training_record(data: dict):
    _assert_system_fields(data)
    assert data["status"] in ("VALID", "EXPIRED")
    assert data["course_code"] in ("H2_BASIC", "H2_OPERATOR", "H2_EMERGENCY")
