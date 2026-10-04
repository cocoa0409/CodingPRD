"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _parse_instant(value: str) -> datetime:
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    d = datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str):
    """Compare two ISO 8601 timestamps by instant, not by string rendering.

    PRD pins three-fractional-digit rendering only for created_at/updated_at and
    api_request_timestamp; computed deadline fields (expires_at, return_deadline,
    temp_tag_expires_at, registration_due_at) have a derivable instant but no
    mandated string format, so equality must be on the instant.
    """
    assert is_iso8601_timestamp(actual), f"Not a valid ISO 8601 timestamp: {actual!r}"
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"instant {actual!r} != {expected!r}"
    )


def assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def assert_customer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["state_code"] in {"GA", "TX", "CA", "FL", "NY"}
    assert data["default_fulfillment_choice"] in {"HOME_DELIVERY", "VENDING_MACHINE"}


def assert_vehicle(data: dict):
    assert_common_fields(data)
    assert isinstance(data["vin"], str) and len(data["vin"]) == 17
    assert data["status"] in {
        "INTAKE", "IN_RECON", "LISTED", "RESERVED", "SOLD", "RETURN_INBOUND", "REMOVED",
    }
    assert isinstance(data["listed_price_cents"], int)
    assert isinstance(data["annotation_count"], int)


def assert_annotation(data: dict):
    assert_common_fields(data)
    assert data["status"] in {"ACTIVE", "RETRACTED"}
    assert data["severity"] in {"COSMETIC", "MINOR", "MODERATE", "MAJOR"}
    assert isinstance(data["deduction_cents"], int)
    assert isinstance(data["image_count"], int)


def assert_prequalification(data: dict):
    assert_common_fields(data)
    assert data["status"] in {"PREQUALIFIED", "LOCKED", "EXPIRED"}
    assert data["pricing_mode"] in {"STANDARD", "CONSERVATIVE"}
    assert isinstance(data["max_amount_cents"], int)
    assert isinstance(data["apr_bps"], int)
    assert isinstance(data["monthly_payment_cents"], int)


def assert_trade_in_offer(data: dict):
    assert_common_fields(data)
    assert data["status"] in {"OFFERED", "INSPECTED", "CONFIRMED", "DECLINED", "EXPIRED"}
    assert isinstance(data["initial_offer_cents"], int)


def assert_purchase_order(data: dict):
    assert_common_fields(data)
    assert data["status"] in {
        "DRAFT", "RESERVED", "STRUCTURED", "APPOINTMENT_SET",
        "COMPLETED", "RETURN_INITIATED", "RETURN_COMPLETED", "CANCELLED",
    }
    assert data["payment_status"] in {"UNPAID", "FINANCED", "PAID", "REFUND_PENDING", "REFUNDED"}
    assert data["delivery_status"] in {"NOT_SCHEDULED", "SCHEDULED", "DELIVERED"}
    assert data["fulfillment_choice"] in {"HOME_DELIVERY", "VENDING_MACHINE"}


def assert_title_registration(data: dict):
    assert_common_fields(data)
    assert data["status"] in {"PENDING", "TEMP_TAG_ISSUED", "FILED", "REGISTERED", "BLOCKED"}


def assert_delivery_appointment(data: dict):
    assert_common_fields(data)
    assert data["status"] in {"SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED"}
    assert data["kind"] in {"HOME_DELIVERY", "VENDING_MACHINE"}


def assert_return_transit(data: dict):
    assert_common_fields(data)
    assert data["status"] in {"PICKUP_SCHEDULED", "PICKED_UP", "ARRIVED_AT_CENTER", "INTAKE_DONE"}


def assert_defect_claim(data: dict):
    assert_common_fields(data)
    assert data["status"] in {"FILED", "UNDER_REVIEW", "AUTHORIZED", "DENIED", "REPAIR_COMPLETE"}
    assert data["disclosure_flag"] in {"DISCLOSED", "UNDISCLOSED"}


def assert_repair_authorization(data: dict):
    assert_common_fields(data)
    assert data["status"] in {"ISSUED", "COMPLETED", "VOIDED"}
    assert isinstance(data["covered_amount_cents"], int)
    assert isinstance(data["deductible_cents"], int)


def assert_recon_intake(data: dict):
    assert_common_fields(data)
    assert data["status"] in {"PENDING_ARRIVAL", "RECEIVED", "IN_WORK", "COMPLETE", "CANCELLED"}


def assert_warranty_split(estimate_cents: int, covered: int, deductible: int):
    """PRD §3.8: covered = min(estimate, cap); deductible = estimate - covered."""
    assert covered == min(estimate_cents, 400000), (
        f"covered {covered} != min(estimate {estimate_cents}, 400000)"
    )
    assert deductible == estimate_cents - covered, (
        f"deductible {deductible} != estimate {estimate_cents} - covered {covered}"
    )
