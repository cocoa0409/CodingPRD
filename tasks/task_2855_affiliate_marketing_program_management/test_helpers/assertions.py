"""Domain assertions for the affiliate program contract.

These wrap the framework validators and add the shape rules the PRD states
explicitly: the `req_` prefix on `meta.api_request_id` (§2.2), the
three-fractional-digit instant format (§2.4), integer-cents money (§2.6),
one-decimal scores (§2.6), the four append-only resources that carry neither
`updated_at` nor `version` (§2.4), and the pagination meta of §2.3.
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from .constants import (
    REQUEST_ID_PREFIX,
    RESPONSE_TYPE_ARRAY,
    RESPONSE_TYPE_ERROR,
    RESPONSE_TYPE_OBJECT,
)

_INSTANT_SUFFIX_LENGTH = len(".000Z")


# ── envelope ────────────────────────────────────────────────────────────────


def assert_meta_envelope(body: Dict[str, Any]) -> None:
    """§2.2: `api_request_id` "starts with `req_`" and the timestamp is ISO 8601."""
    meta = body["meta"]
    request_id = meta["api_request_id"]
    assert request_id.startswith(REQUEST_ID_PREFIX), (
        f"meta.api_request_id must start with '{REQUEST_ID_PREFIX}', got {request_id!r}"
    )
    timestamp = meta["api_request_timestamp"]
    assert is_iso8601_timestamp(timestamp), (
        f"meta.api_request_timestamp must be an ISO 8601 UTC timestamp, got {timestamp!r}"
    )


def assert_object_response(response, expected_status: int = 200) -> Dict[str, Any]:
    """Validate a single-resource success envelope and return ``data``."""
    data = validate_success(response, expected_status)
    body = response.json()
    assert body["response_type"] == RESPONSE_TYPE_OBJECT, (
        f"expected response_type 'object' for a single resource, "
        f"got {body['response_type']!r}"
    )
    assert_meta_envelope(body)
    return data


def assert_created(response) -> Dict[str, Any]:
    """§4: "Operations that create a new resource answer `201 Created`"."""
    return assert_object_response(response, 201)


def assert_list_response(response) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Validate a list envelope and return ``(rows, meta)``."""
    rows, meta = validate_paginated(response)
    body = response.json()
    assert body["response_type"] == RESPONSE_TYPE_ARRAY, (
        f"expected response_type 'array' for a list, got {body['response_type']!r}"
    )
    assert_meta_envelope(body)
    return rows, meta


def assert_error_response(response, error_id: str, status: Optional[int] = None):
    """Validate an error envelope carrying ``error_id`` (and its §5 status)."""
    error = validate_error(response, error_id, status)
    body = response.json()
    assert body["response_type"] == RESPONSE_TYPE_ERROR, (
        f"expected response_type 'error', got {body['response_type']!r}"
    )
    assert_meta_envelope(body)
    assert error["message"].strip(), "data.message must be a non-empty string"
    return error


# ── identity, timestamps, counters ──────────────────────────────────────────


def assert_resource_identity(row: Dict[str, Any]) -> None:
    """§2.4: a server-minted UUID `id` with no type prefix, plus `created_at`."""
    assert is_valid_uuid(row["id"]), (
        f"id must be a server-generated UUID carrying no type prefix, got {row['id']!r}"
    )
    assert_instant_format(row["created_at"], "created_at")


def assert_instant_format(value: str, label: str = "instant") -> None:
    """§2.4: ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert value.endswith("Z"), f"{label} must be a UTC instant ending in Z, got {value!r}"
    assert len(value) == len("2026-08-01T00:00:00.000Z") and value[19] == ".", (
        f"{label} must carry exactly three fractional digits, got {value!r}"
    )
    assert is_iso8601_timestamp(value), f"{label} is not a valid ISO 8601 value: {value!r}"


def assert_mutable_row(row: Dict[str, Any], expected_version: Optional[int] = None):
    """§2.4: a mutable resource carries `updated_at` and an integer `version`."""
    assert_resource_identity(row)
    assert "updated_at" in row, "a mutable resource must carry updated_at"
    assert_instant_format(row["updated_at"], "updated_at")
    assert isinstance(row["version"], int), "version must be an integer"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"expected version {expected_version}, got {row['version']}"
        )


def assert_append_only_row(row: Dict[str, Any]) -> None:
    """§2.4: an append-only row has "**no** `updated_at` field and **no** `version`"."""
    assert_resource_identity(row)
    assert "version" not in row, (
        "an append-only resource must expose no version field, "
        f"got version={row.get('version')!r}"
    )
    assert "updated_at" not in row, (
        "an append-only resource must expose no updated_at field, "
        f"got updated_at={row.get('updated_at')!r}"
    )


def assert_fresh_creation(row: Dict[str, Any]) -> None:
    """A newly created mutable row starts at version 1 with created_at == updated_at."""
    assert_mutable_row(row, expected_version=1)
    assert row["created_at"] == row["updated_at"], (
        "a freshly created row must have created_at equal to updated_at, got "
        f"{row['created_at']!r} and {row['updated_at']!r}"
    )


def assert_version_bumped(row: Dict[str, Any], previous_version: int, label: str = "row"):
    """§2.11: every touched row's `version` "increments by exactly 1"."""
    assert row["version"] == previous_version + 1, (
        f"{label} version must advance from {previous_version} to "
        f"{previous_version + 1}, got {row['version']}"
    )


def assert_version_unchanged(row: Dict[str, Any], expected: int, label: str = "row"):
    """§2.10: when a rule rejects a request "nothing is persisted"."""
    assert row["version"] == expected, (
        f"{label} version must still be {expected} after a rejected write, "
        f"got {row['version']}"
    )


# ── money, basis points and scores ──────────────────────────────────────────


def assert_cents(row: Dict[str, Any], field: str, expected: int) -> None:
    """§2.6: "any field whose name ends in `_cents` is an integer"."""
    actual = row[field]
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field} must be an integer count of cents, got {actual!r}"
    )
    assert actual == expected, f"expected {field} == {expected}, got {actual}"


def assert_bps(row: Dict[str, Any], field: str, expected: int) -> None:
    """§2.6: "Any field whose name ends in `_bps` is an integer count of basis points"."""
    actual = row[field]
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field} must be an integer count of basis points, got {actual!r}"
    )
    assert actual == expected, f"expected {field} == {expected}, got {actual}"


def assert_one_decimal_score(row: Dict[str, Any], field: str, expected: float) -> None:
    """§2.6: scores are "numbers rounded half up to exactly one decimal place"."""
    actual = row[field]
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{field} must be a decimal number, got {actual!r}"
    )
    assert actual == pytest.approx(expected, abs=0.01), (
        f"expected {field} == {expected}, got {actual}"
    )
    assert round(float(actual), 1) == pytest.approx(float(actual), abs=1e-9), (
        f"{field} must carry at most one decimal place, got {actual}"
    )


def assert_field(row: Dict[str, Any], field: str, expected: Any) -> None:
    """Assert one field equals an expected literal, naming the field on failure."""
    assert field in row, f"response is missing the {field} field"
    assert row[field] == expected, (
        f"expected {field} == {expected!r}, got {row[field]!r}"
    )


def assert_fields(row: Dict[str, Any], expected: Dict[str, Any]) -> None:
    """Assert a whole bundle of field literals."""
    for field, value in expected.items():
        assert_field(row, field, value)


def assert_null(row: Dict[str, Any], *fields: str) -> None:
    """Assert each named field is null."""
    for field in fields:
        assert field in row, f"response is missing the {field} field"
        assert row[field] is None, f"expected {field} to be null, got {row[field]!r}"


# ── pagination (§2.3) ───────────────────────────────────────────────────────


def assert_pagination_meta(
    meta: Dict[str, Any],
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    """§2.3: list responses carry `limit`, `offset`, `total_count` and `has_more`."""
    if limit is not None:
        assert meta["limit"] == limit, f"expected meta.limit == {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, (
            f"expected meta.offset == {offset}, got {meta['offset']}"
        )
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"expected meta.total_count == {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"expected meta.has_more == {has_more}, got {meta['has_more']}"
        )


def assert_total_count(response, expected: int) -> List[Dict[str, Any]]:
    """Validate a list envelope and assert its `total_count`."""
    rows, meta = assert_list_response(response)
    assert_pagination_meta(meta, total_count=expected)
    return rows


def assert_created_at_ascending(rows: Sequence[Dict[str, Any]]) -> None:
    """§2.3: "every list endpoint returns its rows sorted by `created_at`"."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), (
        f"list rows must be sorted by created_at ascending, got {stamps}"
    )


def assert_ids(rows: Iterable[Dict[str, Any]], expected_ids: Sequence[str]) -> None:
    """Assert the row ids in order."""
    actual = [row["id"] for row in rows]
    assert actual == list(expected_ids), f"expected ids {list(expected_ids)}, got {actual}"


# ── convenience readers ─────────────────────────────────────────────────────


def rows_by(rows: Sequence[Dict[str, Any]], field: str) -> Dict[Any, Dict[str, Any]]:
    """Index a list of rows by one field's value."""
    return {row[field]: row for row in rows}
