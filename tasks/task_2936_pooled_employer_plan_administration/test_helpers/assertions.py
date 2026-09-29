"""
Domain assertion helpers.

The envelope is unwrapped in exactly one place — the framework's
``validate_success``, which returns the ``data`` payload — and every helper
here builds on that single unwrap.  Two list shapes exist in the contract and
they get separate helpers: a collection response carries ``limit``, ``offset``,
``total_count`` and ``has_more`` in its meta, while a single-resource response
omits all four, so asserting the wrong shape is caught immediately.
"""

from typing import Any, Dict, List, Optional, Tuple

import requests
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .api_client import canonical_instant
from .constants import (
    COMMON_FIELDS,
    IMMUTABLE_COMMON_FIELDS,
    PAGINATION_META_FIELDS,
    REQUEST_META_FIELDS,
)
from .types import RESOURCE_SHAPES

_CALENDAR_DATE_LENGTH = len("2026-08-01")


# ─── Envelope shapes ──────────────────────────────────


def assert_request_meta(response: requests.Response) -> Dict[str, Any]:
    """Assert the two per-request meta fields every response carries."""
    meta = response.json()["meta"]
    for field in REQUEST_META_FIELDS:
        assert field in meta, f"meta.{field} missing from the response envelope"
    assert meta["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must start with 'req_', got "
        f"{meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), (
        f"meta.api_request_timestamp is not an ISO 8601 UTC instant: "
        f"{meta['api_request_timestamp']!r}"
    )
    assert meta["api_request_timestamp"].endswith("Z"), (
        "meta.api_request_timestamp must be expressed in UTC"
    )
    return meta


def validate_single(
    response: requests.Response, expected_status: int = 200
) -> Dict[str, Any]:
    """
    Validate a single-resource success response and return its data object.

    Asserts the response_type is ``object`` and that none of the four
    pagination fields appear, which is what distinguishes this shape from a
    collection response.
    """
    data = validate_success(response, expected_status)
    body = response.json()
    assert body["response_type"] == "object", (
        f"Expected response_type 'object' for a single resource, got "
        f"{body['response_type']!r}"
    )
    assert_request_meta(response)
    for field in PAGINATION_META_FIELDS:
        assert field not in body["meta"], (
            f"A single-resource response must omit meta.{field}"
        )
    assert isinstance(data, dict), "A single-resource data payload must be an object"
    return data


def validate_created(response: requests.Response) -> Dict[str, Any]:
    """Validate a 201 creation response and return its data object."""
    return validate_single(response, expected_status=201)


def validate_collection(
    response: requests.Response,
    expected_total: Optional[int] = None,
    expected_len: Optional[int] = None,
    expected_limit: Optional[int] = None,
    expected_offset: Optional[int] = None,
    expected_has_more: Optional[bool] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Validate a collection response and return ``(items, meta)``.

    The four pagination fields must all be present; the optional arguments
    assert individual values when a test cares about them.
    """
    items, meta = validate_paginated(response)
    body = response.json()
    assert body["response_type"] == "array", (
        f"Expected response_type 'array' for a collection, got "
        f"{body['response_type']!r}"
    )
    assert_request_meta(response)
    assert isinstance(items, list), "A collection data payload must be an array"
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            f"Expected total_count {expected_total}, got {meta['total_count']}"
        )
    if expected_len is not None:
        assert len(items) == expected_len, (
            f"Expected {expected_len} rows in the page, got {len(items)}"
        )
    if expected_limit is not None:
        assert meta["limit"] == expected_limit, (
            f"Expected limit {expected_limit}, got {meta['limit']}"
        )
    if expected_offset is not None:
        assert meta["offset"] == expected_offset, (
            f"Expected offset {expected_offset}, got {meta['offset']}"
        )
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more, (
            f"Expected has_more {expected_has_more}, got {meta['has_more']}"
        )
    return items, meta


def validate_empty_collection(
    response: requests.Response,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Validate a collection response that legitimately has no rows."""
    return validate_collection(
        response, expected_total=0, expected_len=0, expected_has_more=False
    )


# ─── Field-level helpers ──────────────────────────────


def assert_fields(data: Dict[str, Any], **expected: Any) -> None:
    """Assert a batch of exact field values with one message per mismatch."""
    for field, value in expected.items():
        assert field in data, f"Field {field!r} missing from the response payload"
        assert data[field] == value, (
            f"Expected {field} == {value!r}, got {data[field]!r}"
        )


def assert_null_fields(data: Dict[str, Any], *fields: str) -> None:
    """Assert each named field is present and null."""
    for field in fields:
        assert field in data, f"Field {field!r} missing from the response payload"
        assert data[field] is None, (
            f"Expected {field} to be null, got {data[field]!r}"
        )


def assert_instant(value: Any, field: str = "instant") -> None:
    """Assert a value is an ISO 8601 UTC instant with three fractional digits."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{field} is not an ISO 8601 instant: {value!r}"
    assert value.endswith("Z"), f"{field} must be expressed in UTC: {value!r}"
    assert len(value) == len("2026-08-01T00:00:00.000Z"), (
        f"{field} must carry exactly three fractional digits: {value!r}"
    )


def assert_instant_equals(actual: Any, expected: str, field: str = "instant") -> None:
    """Assert an echoed instant equals an expected instant, precision aside."""
    assert_instant(actual, field)
    assert actual == canonical_instant(expected), (
        f"Expected {field} == {canonical_instant(expected)!r}, got {actual!r}"
    )


def assert_calendar_date(value: Any, field: str = "date") -> None:
    """Assert a value is a bare ISO 8601 calendar date, not an instant."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert len(value) == _CALENDAR_DATE_LENGTH and value[4] == "-" and value[7] == "-", (
        f"{field} must be an ISO 8601 calendar date YYYY-MM-DD: {value!r}"
    )
    assert "T" not in value, f"{field} must be a calendar date, not an instant: {value!r}"


def assert_percentage(actual: Any, expected: float, field: str = "percentage") -> None:
    """Assert a percentage matches to the declared two decimal places."""
    assert actual is not None, f"{field} must not be null"
    assert round(float(actual), 2) == round(float(expected), 2), (
        f"Expected {field} == {expected}, got {actual}"
    )


def assert_common_fields(data: Dict[str, Any], resource: str) -> None:
    """
    Assert the common-field contract for a resource.

    Every resource carries a server-minted UUID ``id`` and a ``created_at``
    instant.  All but the immutable fee disclosure additionally carry
    ``updated_at`` and an integer ``version`` starting at 1; the fee disclosure
    must not carry either.
    """
    assert resource in RESOURCE_SHAPES, f"Unknown resource {resource!r}"
    _, common = RESOURCE_SHAPES[resource]
    assert is_valid_uuid(data.get("id", "")), (
        f"{resource}.id must be a server-minted UUID, got {data.get('id')!r}"
    )
    assert_instant(data.get("created_at"), f"{resource}.created_at")
    if common is COMMON_FIELDS:
        assert_instant(data.get("updated_at"), f"{resource}.updated_at")
        assert isinstance(data.get("version"), int), (
            f"{resource}.version must be an integer, got {data.get('version')!r}"
        )
        assert data["version"] >= 1, f"{resource}.version must start at 1"
    else:
        assert common is IMMUTABLE_COMMON_FIELDS
        assert "updated_at" not in data, (
            f"{resource} is an immutable event row and must carry no updated_at"
        )
        assert "version" not in data, (
            f"{resource} is an immutable event row and must carry no version"
        )


def assert_resource_shape(data: Dict[str, Any], resource: str) -> None:
    """Assert every declared field of a resource is present in the payload."""
    assert_common_fields(data, resource)
    fields, _ = RESOURCE_SHAPES[resource]
    missing = [field for field in fields if field not in data]
    assert not missing, f"{resource} payload is missing fields: {missing}"


def assert_version(data: Dict[str, Any], expected: int, resource: str = "row") -> None:
    """Assert a row's version counter."""
    assert data.get("version") == expected, (
        f"Expected {resource} version {expected}, got {data.get('version')}"
    )


# ─── Domain invariants ────────────────────────────────


def assert_plan_control_invariants(plan: Dict[str, Any]) -> None:
    """Assert both plan-level control deltas are exactly zero."""
    assert plan["contribution_control_delta_cents"] == 0, (
        "contribution_control_delta_cents must be exactly 0, got "
        f"{plan['contribution_control_delta_cents']}"
    )
    assert plan["headcount_control_delta"] == 0, (
        "headcount_control_delta must be exactly 0, got "
        f"{plan['headcount_control_delta']}"
    )


def assert_created_at_ascending(items: List[Dict[str, Any]]) -> None:
    """Assert a collection page is ordered by created_at ascending."""
    stamps = [row["created_at"] for row in items]
    assert stamps == sorted(stamps), (
        f"Collection is not ordered by created_at ascending: {stamps}"
    )


def ids_of(items: List[Dict[str, Any]]) -> List[str]:
    """Return the ids of a collection page in page order."""
    return [row["id"] for row in items]


def assert_same_object(first: Dict[str, Any], second: Dict[str, Any]) -> None:
    """Assert two data payloads are field-for-field identical."""
    assert first == second, (
        "Expected the two payloads to be field-for-field identical.\n"
        f"first:  {first}\nsecond: {second}"
    )
