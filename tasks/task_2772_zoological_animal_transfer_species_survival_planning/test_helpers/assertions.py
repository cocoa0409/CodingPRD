"""Domain assertions for the zoological transfer API."""

from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_uuid_id(entity: Dict[str, Any]) -> None:
    """Every entity identifier is an unprefixed UUID."""
    assert "id" in entity, f"entity has no id: {entity}"
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']!r}"


def assert_millisecond_timestamp(value: Any, field: str = "timestamp") -> None:
    """Timestamps are ISO 8601 UTC with exactly three fractional-second digits."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{field} is not ISO 8601: {value!r}"
    fraction = value.split(".")[-1].rstrip("Z") if "." in value else ""
    assert len(fraction) == 3, (
        f"{field} must carry exactly three fractional-second digits: {value!r}"
    )


def assert_versioned_system_fields(entity: Dict[str, Any]) -> None:
    """A mutable entity exposes id, created_at, updated_at and version."""
    assert_uuid_id(entity)
    assert_millisecond_timestamp(entity.get("created_at"), "created_at")
    assert_millisecond_timestamp(entity.get("updated_at"), "updated_at")
    assert isinstance(entity.get("version"), int), (
        f"version must be an integer: {entity.get('version')!r}"
    )
    assert entity["version"] >= 1, "version starts at 1"


def assert_immutable_system_fields(entity: Dict[str, Any]) -> None:
    """The immutable pre-shipment test record carries only id and created_at."""
    assert_uuid_id(entity)
    assert_millisecond_timestamp(entity.get("created_at"), "created_at")
    assert "updated_at" not in entity, "an immutable record carries no updated_at"
    assert "version" not in entity, "an immutable record carries no version"


def assert_money(actual: Any, expected: float, field: str = "amount") -> None:
    """A two-decimal quantity equals the expected value."""
    assert actual is not None, f"{field} must not be null"
    assert float(actual) == pytest.approx(expected, abs=0.005), (
        f"{field}: expected {expected}, got {actual}"
    )


def assert_two_decimals(actual: Any, field: str = "amount") -> None:
    """A quantity is carried to at most two decimal places."""
    assert actual is not None, f"{field} must not be null"
    quantised = round(float(actual) * 100) / 100
    assert float(actual) == pytest.approx(quantised, abs=1e-9), (
        f"{field} must be carried to two decimals: {actual}"
    )


def assert_four_decimals(actual: Any, expected: float,
                        field: str = "coefficient") -> None:
    """A four-decimal coefficient equals the expected value."""
    assert actual is not None, f"{field} must not be null"
    assert float(actual) == pytest.approx(expected, abs=0.00005), (
        f"{field}: expected {expected}, got {actual}"
    )


def assert_date_equals(actual: Any, expected: str, field: str = "date") -> None:
    """A calendar-date field equals the expected YYYY-MM-DD value."""
    assert actual is not None, f"{field} must not be null"
    assert str(actual)[:10] == expected, (
        f"{field}: expected {expected}, got {actual}"
    )


def assert_instant_on_date(actual: Any, expected_date: str,
                          field: str = "stamp") -> None:
    """A stamp taken from the logical clock falls on the expected calendar date."""
    assert actual is not None, f"{field} must not be null"
    assert str(actual).startswith(expected_date), (
        f"{field}: expected a stamp on {expected_date}, got {actual}"
    )


def assert_no_list_meta(response_meta: Dict[str, Any]) -> None:
    """A single-resource read omits the list-only pagination members."""
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key not in response_meta, (
            f"a single-resource read must omit meta.{key}"
        )


def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """The envelope's meta block carries a request id and a millisecond stamp."""
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_': {meta['api_request_id']!r}"
    )
    assert_millisecond_timestamp(meta.get("api_request_timestamp"),
                                 "api_request_timestamp")


def assert_ascending_by_created_at(rows: Iterable[Dict[str, Any]]) -> None:
    """Collections come back oldest first."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows are not ascending by created_at: {stamps}"


def assert_ids_in_order(rows: Iterable[Dict[str, Any]], expected_ids) -> None:
    """The listing returns exactly these ids in exactly this order."""
    assert [row["id"] for row in rows] == list(expected_ids)


def assert_slot_counts(institution: Dict[str, Any], occupied: int,
                      reserved: int) -> None:
    """The institution reports the expected occupied and reserved slot counts."""
    assert institution["occupied_slots"] == occupied, (
        f"occupied_slots: expected {occupied}, got {institution['occupied_slots']}"
    )
    assert institution["reserved_slots"] == reserved, (
        f"reserved_slots: expected {reserved}, got {institution['reserved_slots']}"
    )


def assert_unchanged(before: Dict[str, Any], after: Dict[str, Any],
                    *fields: str) -> None:
    """The named fields did not move between two reads of the same row."""
    for field in fields:
        assert before.get(field) == after.get(field), (
            f"{field} changed from {before.get(field)!r} to {after.get(field)!r}"
        )


def days_after(iso_date: str, days: int) -> str:
    """The calendar date the given number of days after an ISO date."""
    return (date.fromisoformat(iso_date[:10]) + timedelta(days=days)).isoformat()


def days_between(start_iso_date: str, end_iso_date: str) -> int:
    """Whole days from the first date to the second."""
    return (date.fromisoformat(end_iso_date[:10])
            - date.fromisoformat(start_iso_date[:10])).days


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating the trailing Z."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_error_shape(body: Dict[str, Any],
                      expected_error_id: Optional[str] = None) -> None:
    """An error envelope reports response_type 'error' with an id and message."""
    assert body.get("response_type") == "error"
    data = body["data"]
    assert isinstance(data.get("error_id"), str) and data["error_id"]
    assert isinstance(data.get("message"), str) and data["message"].strip()
    if expected_error_id is not None:
        assert data["error_id"] == expected_error_id
