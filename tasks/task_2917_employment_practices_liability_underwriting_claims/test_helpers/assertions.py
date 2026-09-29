"""Domain-specific assertion helpers layered on the shared validator toolkit."""

import re
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_valid_uuid

from .api_client import canonical_instant

_INSTANT_3_DIGITS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def assert_instant_millis(value: Any, label: str = "timestamp") -> None:
    """An ISO-8601 UTC instant carried to exactly three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert _INSTANT_3_DIGITS.match(value), (
        f"{label} must be ISO-8601 UTC with exactly three fractional digits, got {value!r}"
    )


def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every entity carries id, created_at, updated_at and version."""
    assert is_valid_uuid(entity.get("id")), f"id must be a UUID, got {entity.get('id')!r}"
    assert_instant_millis(entity.get("created_at"), "created_at")
    assert_instant_millis(entity.get("updated_at"), "updated_at")
    assert isinstance(entity.get("version"), int), (
        f"version must be an integer, got {entity.get('version')!r}"
    )
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_money(value: Any, expected: int, label: str = "amount") -> None:
    """A money field is an integer count of whole cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )
    assert value == expected, f"expected {label} == {expected}, got {value}"


def assert_decimal_places(value: Any, places: int, label: str = "value") -> None:
    """A numeric field carried to at most ``places`` decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be numeric, got {value!r}"
    )
    quantised = round(float(value), places)
    assert abs(float(value) - quantised) < 1e-9, (
        f"{label} must carry at most {places} decimal places, got {value!r}"
    )


def assert_fields(entity: Dict[str, Any], expected: Dict[str, Any]) -> None:
    """Every key in ``expected`` is present on the entity with that exact value."""
    for key, want in expected.items():
        assert key in entity, f"missing field {key!r} on {sorted(entity)}"
        got = entity[key]
        assert got == want, f"expected {key} == {want!r}, got {got!r}"


def assert_present(entity: Dict[str, Any], keys: Iterable[str]) -> None:
    for key in keys:
        assert key in entity, f"missing field {key!r} on {sorted(entity)}"


def assert_null(entity: Dict[str, Any], keys: Iterable[str]) -> None:
    for key in keys:
        assert entity.get(key, "MISSING") is None, f"expected {key} to be null, got {entity.get(key)!r}"


def assert_id_order(rows: List[Dict[str, Any]], expected_ids: List[str]) -> None:
    """The returned rows appear in exactly the expected identifier order."""
    got = [row["id"] for row in rows]
    assert got == expected_ids, f"expected id order {expected_ids}, got {got}"


def assert_same_instant(actual: Any, expected: Any, label: str = "timestamp") -> None:
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"expected {label} == {expected!r}, got {actual!r}"
    )


def assert_version_bumped_by(before: Dict[str, Any], after: Dict[str, Any], delta: int = 1) -> None:
    assert after["version"] == before["version"] + delta, (
        f"expected version {before['version']} + {delta}, got {after['version']}"
    )


def assert_success_meta(body: Dict[str, Any]) -> None:
    """The success envelope meta block carries the five declared fields."""
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta.get('api_request_id')!r}"
    )
    assert_instant_millis(meta.get("api_request_timestamp"), "api_request_timestamp")


def assert_error_meta_only(body: Dict[str, Any]) -> None:
    """The error envelope meta block carries exactly the two declared fields."""
    meta = body["meta"]
    assert set(meta) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta must carry exactly api_request_id and api_request_timestamp, got {sorted(meta)}"
    )
    assert body["response_type"] == "error", f"response_type must be 'error', got {body['response_type']!r}"
