"""Domain assertions: envelope shapes, temporal formats and per-resource shapes.

Response unwrapping happens exactly once. The framework's ``validate_success``
returns the ``data`` member of the envelope, and every helper here accepts that
already-unwrapped payload rather than the envelope.
"""

import re
from datetime import datetime, timezone
from typing import Any, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

CALENDAR_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MILLIS_INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


# --- Envelope helpers -------------------------------------------------------
def validate_unpaginated(response, expected_status: int = 200) -> list:
    """Asserts a successful array response and returns the array.

    Used for list reads whose envelope is not expected to carry the four
    pagination members.
    """
    body = response.json()
    assert response.status_code == expected_status, (
        f"Expected HTTP {expected_status}, got {response.status_code}: {body}"
    )
    assert body.get("response_type") == "array", f"Expected an array response: {body}"
    data = body.get("data")
    assert isinstance(data, list), f"Expected data to be a list: {body}"
    return data


def validate_list(response, expected_total: Optional[int] = None) -> list:
    """Asserts a paginated list response and optionally its ``total_count``."""
    items, meta = validate_paginated(response)
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            f"Expected total_count {expected_total}, got {meta['total_count']}"
        )
    return items


def list_meta(response) -> dict:
    """Returns the pagination members of a paginated list response."""
    _, meta = validate_paginated(response)
    return meta


def single_resource_meta_omits_pagination(response) -> None:
    """Asserts a single-resource envelope carries no pagination members."""
    meta = response.json()["meta"]
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key not in meta, f"Single-resource meta must omit {key}: {meta}"


def find_by_id(items: list, resource_id: str) -> dict:
    """Returns the item in a list response whose ``id`` matches."""
    for item in items:
        if item.get("id") == resource_id:
            return item
    raise AssertionError(f"{resource_id} is not present in {[i.get('id') for i in items]}")


def ids_of(items: list) -> list:
    """Returns the ``id`` of every item in a list response, in order."""
    return [item.get("id") for item in items]


# --- Temporal helpers -------------------------------------------------------
def parse_instant(value: str) -> datetime:
    """Parses an ISO 8601 UTC instant into an aware datetime."""
    assert isinstance(value, str), f"Expected an ISO 8601 instant string, got {value!r}"
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: Any, expected: str) -> None:
    """Compares two instants by value, ignoring how many digits were printed."""
    assert actual is not None, f"Expected instant {expected}, got null"
    assert parse_instant(actual) == parse_instant(expected), (
        f"Expected instant {expected}, got {actual}"
    )


def assert_instant_field(data: dict, field: str) -> None:
    """Asserts a field holds a well-formed ISO 8601 UTC instant."""
    value = data.get(field)
    assert value is not None, f"{field} must be present"
    assert is_iso8601_timestamp(value), f"{field} is not an ISO 8601 instant: {value!r}"


def assert_millisecond_instant(value: Any) -> None:
    """Asserts an instant is rendered with exactly three fractional digits."""
    assert isinstance(value, str) and MILLIS_INSTANT_RE.match(value), (
        f"Expected an ISO 8601 UTC instant with three fractional digits: {value!r}"
    )


def assert_calendar_date(value: Any) -> None:
    """Asserts a value is a plain calendar date with no time component."""
    assert isinstance(value, str) and CALENDAR_DATE_RE.match(value), (
        f"Expected a plain YYYY-MM-DD calendar date, got {value!r}"
    )


# --- Numeric helpers --------------------------------------------------------
def assert_decimal_places(value: Any, places: int) -> None:
    """Asserts a number carries no more than the given number of decimals."""
    assert isinstance(value, (int, float)), f"Expected a number, got {value!r}"
    scaled = round(float(value) * (10**places))
    assert abs(float(value) * (10**places) - scaled) < 1e-6, (
        f"{value!r} is not rounded to {places} decimal places"
    )


def assert_integer_cents(value: Any) -> None:
    """Asserts a money field is an integer count of cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"Money must be an integer number of cents, got {value!r}"
    )


def assert_close(actual: Any, expected: float, places: int = 3) -> None:
    """Compares two decimal quantities at the given precision."""
    assert actual is not None, f"Expected {expected}, got null"
    assert abs(float(actual) - float(expected)) < 0.5 * 10 ** (-places), (
        f"Expected {expected} at {places} decimal places, got {actual}"
    )


# --- Shared resource shape --------------------------------------------------
def assert_versioned_resource(data: dict) -> None:
    """Asserts the identity, timestamp and version fields of a resource."""
    assert is_valid_uuid(data.get("id")), f"id must be a bare UUID: {data.get('id')!r}"
    assert_millisecond_instant(data.get("created_at"))
    assert_millisecond_instant(data.get("updated_at"))
    version = data.get("version")
    assert isinstance(version, int) and version >= 1, (
        f"version must start at 1 and increase: {version!r}"
    )


def assert_append_only_resource(data: dict) -> None:
    """Asserts an append-only record carries neither ``updated_at`` nor ``version``."""
    assert is_valid_uuid(data.get("id")), f"id must be a bare UUID: {data.get('id')!r}"
    assert_millisecond_instant(data.get("created_at"))
    assert "updated_at" not in data, f"append-only records carry no updated_at: {data}"
    assert "version" not in data, f"append-only records carry no version: {data}"


# --- Per-resource shapes ----------------------------------------------------
def assert_host_store(data: dict) -> None:
    """Asserts the shape of a host store."""
    assert_versioned_resource(data)
    for field in (
        "name",
        "banner_chain",
        "store_number",
        "state_code",
        "pos_integration_status",
        "space_compliance_state",
    ):
        assert isinstance(data.get(field), str), f"{field} must be a string: {data}"
    assert re.match(r"^[A-Z]{2}$", data["state_code"]), (
        f"state_code must be exactly two uppercase letters: {data['state_code']!r}"
    )
    for field in (
        "weekly_traffic_count",
        "sushi_space_sqft",
        "refrigerated_case_capacity_packs",
        "pos_terminal_count",
    ):
        assert isinstance(data.get(field), int), f"{field} must be an integer: {data}"
    assert isinstance(data.get("refrigerated_case_linear_ft"), (int, float))
    if data.get("last_attested_on") is not None:
        assert_calendar_date(data["last_attested_on"])


def assert_license_agreement(data: dict) -> None:
    """Asserts the shape of a license agreement."""
    assert_versioned_resource(data)
    assert is_valid_uuid(data.get("host_store_id"))
    for field in ("status", "revenue_share_model", "markdown_policy"):
        assert isinstance(data.get(field), str), f"{field} must be a string: {data}"
    assert_calendar_date(data.get("effective_from"))
    assert_calendar_date(data.get("effective_to"))
    for field in (
        "min_space_sqft_obligation",
        "space_credit_cents_per_sqft",
        "space_shortfall_sqft",
        "active_kiosk_count",
        "lifetime_share_accrued_cents",
    ):
        assert isinstance(data.get(field), int), f"{field} must be an integer: {data}"
    assert_integer_cents(data["lifetime_share_accrued_cents"])


def assert_kiosk(data: dict) -> None:
    """Asserts the shape of a kiosk, including both state dimensions."""
    assert_versioned_resource(data)
    assert is_valid_uuid(data.get("license_agreement_id"))
    assert isinstance(data.get("kiosk_code"), str)
    for field in ("operational_state", "sanitation_posture"):
        assert isinstance(data.get(field), str), f"{field} must be a string: {data}"
    for field in (
        "daily_pack_cap",
        "certified_chef_count",
        "risk_points",
        "open_critical_finding_count",
        "consecutive_clean_audits",
    ):
        assert isinstance(data.get(field), int), f"{field} must be an integer: {data}"
    assert 0 <= data["risk_points"] <= 40, (
        f"risk_points must be clamped into 0..40: {data['risk_points']}"
    )
    if data.get("commissioned_on") is not None:
        assert_calendar_date(data["commissioned_on"])


def assert_chef(data: dict) -> None:
    """Asserts the shape of a chef."""
    assert_versioned_resource(data)
    assert isinstance(data.get("full_name"), str)
    assert isinstance(data.get("status"), str)
    assert isinstance(data.get("training_hours_logged"), (int, float))
    assert isinstance(data.get("valid_cert_count"), int)
    for field in ("food_handler_cert_expires_at", "haccp_cert_expires_at"):
        if data.get(field) is not None:
            assert_millisecond_instant(data[field])


def assert_certification(data: dict) -> None:
    """Asserts the shape of a certification."""
    assert_versioned_resource(data)
    assert is_valid_uuid(data.get("chef_id"))
    assert isinstance(data.get("cert_type"), str)
    assert isinstance(data.get("status"), str)
    assert isinstance(data.get("valid_days"), int)
    assert 0 <= float(data.get("exam_score")) <= 100
    assert_millisecond_instant(data.get("expires_at"))
    assert_instant_field(data, "issued_at")


def assert_production_plan(data: dict) -> None:
    """Asserts the shape of a production plan."""
    assert_versioned_resource(data)
    assert is_valid_uuid(data.get("kiosk_id"))
    assert_calendar_date(data.get("production_date"))
    assert isinstance(data.get("status"), str)
    for field in ("traffic_forecast", "planned_pack_count", "actual_pack_count"):
        assert isinstance(data.get(field), int), f"{field} must be an integer: {data}"
    assert isinstance(data.get("planned_rice_kg"), (int, float))
    assert_decimal_places(data["planned_rice_kg"], 2)
    if data.get("forecast_variance_pct") is not None:
        assert_decimal_places(data["forecast_variance_pct"], 2)


def assert_rice_batch(data: dict) -> None:
    """Asserts the shape of a rice batch."""
    assert_versioned_resource(data)
    assert is_valid_uuid(data.get("production_plan_id"))
    assert is_valid_uuid(data.get("chef_id"))
    assert isinstance(data.get("status"), str)
    assert isinstance(data.get("max_pack_yield"), int)
    # ``exposure_minutes`` is only computed when the time/temperature control
    # record is verified, so it is null on a batch that is still MIXING or
    # ACIDIFYING.
    if data.get("exposure_minutes") is not None:
        assert isinstance(data["exposure_minutes"], int)
    assert_instant_field(data, "hold_start_at")
    assert_instant_field(data, "hold_end_at")


def assert_fish_lot(data: dict) -> None:
    """Asserts the shape of a fish lot."""
    assert_versioned_resource(data)
    assert is_valid_uuid(data.get("kiosk_id"))
    for field in ("species", "supplier_code", "harvest_method", "status"):
        assert isinstance(data.get(field), str), f"{field} must be a string: {data}"
    assert isinstance(data.get("parasite_destruction_required"), bool)
    assert isinstance(data.get("parasite_destruction_compliant"), bool)
    assert isinstance(data.get("cold_chain_breach_minutes"), int)
    assert isinstance(data.get("allocated_kg"), (int, float))
    assert_decimal_places(data["allocated_kg"], 3)
    if data.get("remaining_kg") is not None:
        assert_decimal_places(data["remaining_kg"], 3)
    assert_instant_field(data, "received_at")


def assert_cold_chain_reading(data: dict) -> None:
    """Asserts the shape of an append-only cold-chain reading."""
    assert_append_only_resource(data)
    assert is_valid_uuid(data.get("fish_lot_id"))
    assert_instant_field(data, "recorded_at")
    assert isinstance(data.get("temp_c"), (int, float))
    assert isinstance(data.get("breach_minutes_attributed"), int)
    assert isinstance(data.get("lot_breach_minutes_after"), int)
    if data.get("interval_minutes_from_previous") is not None:
        assert isinstance(data["interval_minutes_from_previous"], int)


def assert_pack_lot(data: dict) -> None:
    """Asserts the shape of a pack lot and its unit decomposition invariant."""
    assert_versioned_resource(data)
    assert is_valid_uuid(data.get("rice_batch_id"))
    assert is_valid_uuid(data.get("fish_lot_id"))
    assert isinstance(data.get("sku_code"), str)
    assert isinstance(data.get("status"), str)
    for field in ("pack_count", "sold_count", "discarded_count", "unsold_count"):
        assert isinstance(data.get(field), int), f"{field} must be an integer: {data}"
    assert_integer_cents(data.get("list_price_cents"))
    if data.get("markdown_price_cents") is not None:
        assert_integer_cents(data["markdown_price_cents"])
    if data.get("advisory_markdown_price_cents") is not None:
        assert_integer_cents(data["advisory_markdown_price_cents"])
    assert_decimal_places(data.get("consumed_fish_kg"), 3)
    assert_instant_field(data, "produced_at")
    assert_instant_field(data, "shelf_expiry_at")
    assert_pack_lot_decomposition(data)


def assert_pack_lot_decomposition(data: dict) -> None:
    """Asserts pack_count always equals sold plus discarded plus unsold."""
    assert data["pack_count"] == (
        data["sold_count"] + data["discarded_count"] + data["unsold_count"]
    ), (
        "pack_count must equal sold_count + discarded_count + unsold_count: "
        f"{data['pack_count']} vs {data['sold_count']}+{data['discarded_count']}"
        f"+{data['unsold_count']}"
    )


def assert_discard_event(data: dict) -> None:
    """Asserts the shape of an append-only discard event."""
    assert_append_only_resource(data)
    assert is_valid_uuid(data.get("pack_lot_id"))
    assert isinstance(data.get("reason"), str)
    assert isinstance(data.get("discarded_count"), int)
    assert_integer_cents(data.get("unit_value_cents"))
    assert_integer_cents(data.get("discard_value_cents"))
    assert isinstance(data.get("settlement_credit_eligible"), bool)
    assert isinstance(data.get("recorded_by_user_id"), str)
    assert data["discard_value_cents"] == (
        data["unit_value_cents"] * data["discarded_count"]
    ), f"discard_value_cents must be the unit value times the count: {data}"


def assert_pos_sales_feed(data: dict) -> None:
    """Asserts the shape of a POS sales feed."""
    assert_versioned_resource(data)
    assert is_valid_uuid(data.get("host_store_id"))
    assert_calendar_date(data.get("business_date"))
    assert isinstance(data.get("status"), str)
    for field in ("gross_sales_cents", "markdown_sales_cents"):
        assert_integer_cents(data.get(field))
    assert data["markdown_sales_cents"] <= data["gross_sales_cents"]
    for field in ("full_price_units", "markdown_units", "reconciled_unit_total"):
        assert isinstance(data.get(field), int), f"{field} must be an integer: {data}"
    assert isinstance(data.get("lines"), list)


def assert_settlement_statement(data: dict) -> None:
    """Asserts the shape of a settlement statement."""
    assert_versioned_resource(data)
    assert is_valid_uuid(data.get("license_agreement_id"))
    assert_calendar_date(data.get("period_start"))
    assert_calendar_date(data.get("period_end"))
    assert isinstance(data.get("status"), str)
    for field in (
        "gross_sales_cents",
        "markdown_sales_cents",
        "settlement_base_cents",
        "binding_share_cents",
        "advisory_share_cents",
        "variance_cents",
        "space_shortfall_credit_cents",
        "period_discard_value_cents",
        "discard_credit_cents",
        "net_due_cents",
    ):
        assert_integer_cents(data.get(field))
    assert data["variance_cents"] == (
        data["binding_share_cents"] - data["advisory_share_cents"]
    ), f"variance_cents must be binding minus advisory: {data}"
    assert data["net_due_cents"] >= 0, "net_due_cents is floored at zero"
    assert isinstance(data.get("revision_round"), int)
    if data.get("paid_at") is not None:
        assert_instant_field(data, "paid_at")


def assert_audit(data: dict) -> None:
    """Asserts the shape of a food safety audit."""
    assert_versioned_resource(data)
    assert is_valid_uuid(data.get("kiosk_id"))
    assert_calendar_date(data.get("scheduled_for"))
    assert isinstance(data.get("status"), str)
    for field in (
        "round_count",
        "critical_finding_count",
        "open_finding_count",
        "score",
    ):
        assert isinstance(data.get(field), int), f"{field} must be an integer: {data}"
    assert data["score"] >= 0, "score is floored at zero"


def assert_audit_finding(data: dict) -> None:
    """Asserts the shape of an audit finding."""
    assert_versioned_resource(data)
    assert is_valid_uuid(data.get("audit_id"))
    for field in ("severity", "finding_code", "description", "status"):
        assert isinstance(data.get(field), str), f"{field} must be a string: {data}"
    assert isinstance(data.get("risk_points"), int)


def assert_risk_summary(data: dict) -> None:
    """Asserts the shape of a kiosk risk summary read."""
    assert is_valid_uuid(data.get("kiosk_id"))
    for field in (
        "minor_open",
        "major_open",
        "critical_open",
        "approved_variance_count",
        "quarantined_lot_count",
        "clean_audit_credit",
        "raw_risk_points",
        "risk_points",
    ):
        assert isinstance(data.get(field), int), f"{field} must be an integer: {data}"
    assert isinstance(data.get("sanitation_posture"), str)
    assert isinstance(data.get("posture_forced_by_critical"), bool)
    assert 0 <= data["risk_points"] <= 40


__all__ = [
    "validate_success",
    "validate_paginated",
    "validate_unpaginated",
    "validate_list",
    "list_meta",
    "single_resource_meta_omits_pagination",
    "find_by_id",
    "ids_of",
    "parse_instant",
    "assert_instant_equals",
    "assert_instant_field",
    "assert_millisecond_instant",
    "assert_calendar_date",
    "assert_decimal_places",
    "assert_integer_cents",
    "assert_close",
    "assert_versioned_resource",
    "assert_append_only_resource",
    "assert_host_store",
    "assert_license_agreement",
    "assert_kiosk",
    "assert_chef",
    "assert_certification",
    "assert_production_plan",
    "assert_rice_batch",
    "assert_fish_lot",
    "assert_cold_chain_reading",
    "assert_pack_lot",
    "assert_pack_lot_decomposition",
    "assert_discard_event",
    "assert_pos_sales_feed",
    "assert_settlement_statement",
    "assert_audit",
    "assert_audit_finding",
    "assert_risk_summary",
]
