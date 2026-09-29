"""Domain assertion helpers.

Thin wrappers over the runner's generic validators plus the few shape checks
this API needs repeatedly. Note that :func:`validate_success` already returns
the inner ``data`` payload, so nothing here re-indexes ``["data"]``.
"""

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)

from .api_client import raw_json
from .constants import DEFAULT_LIMIT, DEFAULT_OFFSET

_INSTANT_WITH_MILLIS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def validate_unpaginated(
    response: requests.Response, expected_status: int = 200
) -> Tuple[List[Any], Dict[str, Any]]:
    """Validate a list response that takes no `limit`/`offset` inputs.

    PRD 2.3 states that both paginated and unpaginated list responses expose
    `limit`, `offset`, `total_count` and `has_more` inside `meta`, so those keys
    are required here too - but no assumption is made about their values.
    Returns ``(rows, meta)``.
    """
    data = validate_success(response, expected_status)
    assert isinstance(data, list), f"Expected a list payload, got {type(data)}"
    meta = response.json()["meta"]
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta, f"meta.{key} missing from list response"
    assert isinstance(meta["total_count"], int), "meta.total_count must be an integer"
    assert isinstance(meta["has_more"], bool), "meta.has_more must be a boolean"
    return data, meta


def assert_meta_pagination(
    response: requests.Response,
    expected_limit: int = DEFAULT_LIMIT,
    expected_offset: int = DEFAULT_OFFSET,
    expected_total_count: Optional[int] = None,
    expected_has_more: Optional[bool] = None,
) -> Dict[str, Any]:
    """Assert the four pagination fields inside `meta` (PRD 2.3)."""
    meta = response.json()["meta"]
    assert meta["limit"] == expected_limit, f"meta.limit: {meta['limit']}"
    assert meta["offset"] == expected_offset, f"meta.offset: {meta['offset']}"
    if expected_total_count is not None:
        assert meta["total_count"] == expected_total_count, (
            f"meta.total_count: {meta['total_count']}"
        )
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more, f"meta.has_more: {meta['has_more']}"
    return meta


def assert_total_count(response: requests.Response, expected: int) -> None:
    """Assert `meta.total_count` on any list response."""
    meta = response.json()["meta"]
    assert meta["total_count"] == expected, (
        f"Expected total_count {expected}, got {meta['total_count']}"
    )


def assert_versioned_entity(entity: Dict[str, Any]) -> None:
    """Assert the common fields PRD 2.4 puts on every versioned entity."""
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at is not an ISO-8601 instant: {entity['created_at']}"
    )
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"updated_at is not an ISO-8601 instant: {entity['updated_at']}"
    )
    assert isinstance(entity["version"], int), "version must be an integer"
    assert entity["version"] >= 1, f"version must start at 1, got {entity['version']}"


def assert_unversioned_entity(entity: Dict[str, Any]) -> None:
    """Assert the common fields of an entity that carries only `id`/`created_at`."""
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at is not an ISO-8601 instant: {entity['created_at']}"
    )
    assert "updated_at" not in entity, "this entity must not carry updated_at"
    assert "version" not in entity, "this entity must not carry version"


def assert_millisecond_instants(
    response: requests.Response, fields: Sequence[str]
) -> None:
    """Assert the named instant fields are serialised with exactly three
    fractional digits (PRD 2.4). Reads the raw body, before canonicalisation."""
    data = raw_json(response)["data"]
    for field in fields:
        value = data[field]
        assert _INSTANT_WITH_MILLIS.match(value), (
            f"{field} must be an ISO-8601 instant with exactly three "
            f"fractional digits, got {value!r}"
        )


def assert_numbers_not_strings(payload: Dict[str, Any], fields: Sequence[str]) -> None:
    """Assert the named fields are JSON numbers, never strings (PRD 2.9)."""
    for field in fields:
        value = payload[field]
        assert isinstance(value, (int, float)) and not isinstance(value, bool), (
            f"{field} must be a JSON number, got {type(value).__name__}: {value!r}"
        )


def assert_hours(payload: Dict[str, Any], field: str, expected: float) -> None:
    """Assert an hours figure equals `expected` to two decimal places (PRD 2.9)."""
    value = payload[field]
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be a JSON number, got {type(value).__name__}"
    )
    assert round(float(value), 2) == round(float(expected), 2), (
        f"Expected {field} == {expected:.2f}, got {value}"
    )


def assert_ratio(payload: Dict[str, Any], field: str, expected: float) -> None:
    """Assert a ratio equals `expected` to four decimal places (PRD 2.9)."""
    value = payload[field]
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be a JSON number, got {type(value).__name__}"
    )
    assert round(float(value), 4) == round(float(expected), 4), (
        f"Expected {field} == {expected:.4f}, got {value}"
    )


def assert_units(payload: Dict[str, Any], field: str, expected: int) -> None:
    """Assert a billable-unit figure is an integer equal to `expected` (PRD 2.9)."""
    value = payload[field]
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer number of units, got {type(value).__name__}: {value!r}"
    )
    assert value == expected, f"Expected {field} == {expected}, got {value}"


def assert_edit_codes(timesheet: Dict[str, Any], expected: Sequence[str]) -> None:
    """Assert `edit_codes` is exactly the expected ascending-sorted set (PRD 3.7)."""
    actual = timesheet["edit_codes"]
    assert isinstance(actual, list), "edit_codes must be an array"
    assert actual == sorted(actual), f"edit_codes must be ascending, got {actual}"
    assert len(actual) == len(set(actual)), f"edit_codes must be a set, got {actual}"
    assert actual == list(expected), f"Expected edit_codes {list(expected)}, got {actual}"


def assert_shift_axes(shift: Dict[str, Any], staffing_status: str, evv_status: str) -> None:
    """Assert both of a shift's independent state axes at once (PRD 3.1)."""
    assert shift["staffing_status"] == staffing_status, (
        f"Expected staffing_status {staffing_status}, got {shift['staffing_status']}"
    )
    assert shift["evv_status"] == evv_status, (
        f"Expected evv_status {evv_status}, got {shift['evv_status']}"
    )


def assert_version_is(entity: Dict[str, Any], expected: int) -> None:
    """Assert an entity's `version` is exactly `expected`."""
    assert entity["version"] == expected, (
        f"Expected version {expected}, got {entity['version']}"
    )


def field_names(payload: Dict[str, Any]) -> List[str]:
    """The sorted key set of a payload, handy for shape diffs."""
    return sorted(payload.keys())
