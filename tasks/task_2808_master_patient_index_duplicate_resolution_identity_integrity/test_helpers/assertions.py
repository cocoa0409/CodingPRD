"""Domain assertions layered on the framework's generic validators."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from .constants import SCORE_TOLERANCE

# ─── Timestamp handling ───────────────────────────────


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp, tolerating a trailing ``Z``."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant(actual: Optional[str], expected_iso: str, label: str = "timestamp"):
    """Compare two timestamps as instants, ignoring fractional-digit rendering."""
    assert actual is not None, f"{label} should be present, got null"
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{label}: expected the instant {expected_iso}, got {actual}"
    )


def assert_millisecond_timestamp(value: str, label: str = "timestamp"):
    """The API renders timestamps with exactly three fractional-second digits."""
    assert isinstance(value, str), f"{label} should be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{label} is not ISO 8601: {value!r}"
    assert "." in value, f"{label} should carry fractional seconds: {value!r}"
    fraction = value.split(".", 1)[1].rstrip("Z")
    assert len(fraction) == 3, (
        f"{label} should carry exactly three fractional digits, got {value!r}"
    )


def plus_hours(instant_iso: str, hours: int) -> str:
    """Return ``instant_iso`` shifted forward by ``hours`` hours."""
    shifted = parse_instant(instant_iso) + timedelta(hours=hours)
    return shifted.strftime("%Y-%m-%dT%H:%M:%SZ")


def plus_days(instant_iso: str, days: int) -> str:
    shifted = parse_instant(instant_iso) + timedelta(days=days)
    return shifted.strftime("%Y-%m-%dT%H:%M:%SZ")


def plus_seconds(instant_iso: str, seconds: int) -> str:
    shifted = parse_instant(instant_iso) + timedelta(seconds=seconds)
    return shifted.strftime("%Y-%m-%dT%H:%M:%SZ")


# ─── Numeric helpers ──────────────────────────────────


def assert_score(actual: Any, expected: float, label: str = "score"):
    """Assert a two-decimal monetary-style score value."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} should be a JSON number, got {actual!r}"
    )
    assert actual == pytest.approx(expected, abs=SCORE_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_two_decimal_places(actual: Any, label: str = "score"):
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} should be a JSON number, got {actual!r}"
    )
    assert round(float(actual), 2) == pytest.approx(float(actual), abs=1e-9), (
        f"{label} should carry at most two decimal places, got {actual}"
    )


def assert_integer(actual: Any, expected: int, label: str = "count"):
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} should be an integer, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


def assert_breakdown(
    breakdown: Dict[str, Any], expected: Dict[str, float], label: str = "breakdown"
):
    """Assert the published per-attribute contribution map exactly."""
    assert isinstance(breakdown, dict), f"{label} should be an object, got {breakdown!r}"
    assert set(breakdown.keys()) == set(expected.keys()), (
        f"{label} keys: expected {sorted(expected)}, got {sorted(breakdown)}"
    )
    for key, value in expected.items():
        assert_score(breakdown[key], value, f"{label}[{key}]")


# ─── Common-field helpers ─────────────────────────────


def assert_system_fields(entity: Dict[str, Any], expected_version: Optional[int] = None):
    """Every mutable resource carries a UUID id, timestamps and a version."""
    assert is_valid_uuid(entity["id"]), f"id should be a UUID: {entity['id']!r}"
    assert_millisecond_timestamp(entity["created_at"], "created_at")
    assert_millisecond_timestamp(entity["updated_at"], "updated_at")
    assert isinstance(entity["version"], int) and not isinstance(
        entity["version"], bool
    ), f"version should be an integer, got {entity['version']!r}"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"version: expected {expected_version}, got {entity['version']}"
        )


def assert_write_once_fields(entity: Dict[str, Any]):
    """Write-once event records carry only ``id`` and ``created_at``."""
    assert is_valid_uuid(entity["id"]), f"id should be a UUID: {entity['id']!r}"
    assert_millisecond_timestamp(entity["created_at"], "created_at")
    assert "updated_at" not in entity, "write-once records carry no updated_at"
    assert "version" not in entity, "write-once records carry no version"


def assert_version(entity: Dict[str, Any], expected: int, label: str = "version"):
    assert entity.get("version") == expected, (
        f"{label}: expected {expected}, got {entity.get('version')}"
    )


# ─── Envelope helpers ─────────────────────────────────


def assert_error_envelope(response, expected_error_id: str, expected_status: int = None):
    """Validate a rejection and confirm the envelope declares an error."""
    error = validate_error(response, expected_error_id, expected_status)
    body = response.json()
    assert body["response_type"] == "error", (
        f"response_type should be 'error', got {body.get('response_type')!r}"
    )
    assert set(body["meta"].keys()) == {
        "api_request_id",
        "api_request_timestamp",
    }, f"error meta carries unexpected keys: {sorted(body['meta'])}"
    assert isinstance(error.get("error_id"), str) and error["error_id"], (
        "error_id should be a non-empty string"
    )
    assert isinstance(error.get("message"), str) and error["message"], (
        "message should be a non-empty string"
    )
    return error


def assert_list_meta(
    response,
    expected_total: Optional[int] = None,
    expected_limit: Optional[int] = None,
    expected_offset: Optional[int] = None,
    expected_has_more: Optional[bool] = None,
):
    """Validate a collection envelope and its pagination metadata."""
    rows, meta = validate_paginated(response)
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            f"total_count: expected {expected_total}, got {meta['total_count']}"
        )
    if expected_limit is not None:
        assert meta["limit"] == expected_limit, (
            f"limit: expected {expected_limit}, got {meta['limit']}"
        )
    if expected_offset is not None:
        assert meta["offset"] == expected_offset, (
            f"offset: expected {expected_offset}, got {meta['offset']}"
        )
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more, (
            f"has_more: expected {expected_has_more}, got {meta['has_more']}"
        )
    return rows, meta


def list_rows(response, expected_total: Optional[int] = None) -> List[Dict[str, Any]]:
    rows, _ = assert_list_meta(response, expected_total=expected_total)
    return rows


def assert_created(response) -> Dict[str, Any]:
    """A minting operation answers 201 Created."""
    return validate_success(response, 201)


def assert_ok(response) -> Dict[str, Any]:
    return validate_success(response, 200)


def mrns(rows: Iterable[Dict[str, Any]]) -> List[str]:
    return [row["mrn"] for row in rows]


def ids(rows: Iterable[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


def assert_record_condition(
    record: Dict[str, Any],
    identity_state: Optional[str] = None,
    integrity_state: Optional[str] = None,
    clinical_element_count: Optional[int] = None,
    subsumed_member_count: Optional[int] = None,
    survivor_record_id: Optional[str] = "__unset__",
    enterprise_id: Optional[str] = None,
    version: Optional[int] = None,
):
    """Assert the frequently-checked slice of a patient record's condition."""
    if identity_state is not None:
        assert record["identity_state"] == identity_state, (
            f"identity_state: expected {identity_state}, got {record['identity_state']}"
        )
    if integrity_state is not None:
        assert record["integrity_state"] == integrity_state, (
            f"integrity_state: expected {integrity_state}, "
            f"got {record['integrity_state']}"
        )
    if clinical_element_count is not None:
        assert_integer(
            record["clinical_element_count"], clinical_element_count,
            "clinical_element_count",
        )
    if subsumed_member_count is not None:
        assert_integer(
            record["subsumed_member_count"], subsumed_member_count,
            "subsumed_member_count",
        )
    if survivor_record_id != "__unset__":
        assert record["survivor_record_id"] == survivor_record_id, (
            f"survivor_record_id: expected {survivor_record_id}, "
            f"got {record['survivor_record_id']}"
        )
    if enterprise_id is not None:
        assert record["enterprise_id"] == enterprise_id, (
            f"enterprise_id: expected {enterprise_id}, got {record['enterprise_id']}"
        )
    if version is not None:
        assert_version(record, version)


def assert_site_counters(
    site: Dict[str, Any],
    active_record_count: Optional[int] = None,
    flagged_record_count: Optional[int] = None,
    version: Optional[int] = None,
):
    if active_record_count is not None:
        assert_integer(
            site["active_record_count"], active_record_count, "active_record_count"
        )
    if flagged_record_count is not None:
        assert_integer(
            site["flagged_record_count"], flagged_record_count, "flagged_record_count"
        )
    if version is not None:
        assert_version(site, version, "site version")
