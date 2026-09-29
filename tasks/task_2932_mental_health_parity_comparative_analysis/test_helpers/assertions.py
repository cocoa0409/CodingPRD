"""Domain assertion helpers layered on the framework's generic assertions."""

from typing import Any, Dict, Iterable, Optional

import requests

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from .api_client import canonical_instant


# ─── Shape assertions ─────────────────────────────────────────────────────────


def assert_versioned_resource(body: Dict[str, Any]) -> None:
    """Assert the four system-managed properties carried by a versioned resource."""
    assert is_valid_uuid(body.get("id")), f"id is not a UUID: {body.get('id')!r}"
    assert is_iso8601_timestamp(
        body.get("created_at")
    ), f"created_at is not ISO-8601: {body.get('created_at')!r}"
    assert is_iso8601_timestamp(
        body.get("updated_at")
    ), f"updated_at is not ISO-8601: {body.get('updated_at')!r}"
    assert isinstance(body.get("version"), int), f"version is not an integer: {body.get('version')!r}"
    assert body["version"] >= 1, f"version must start at 1, got {body['version']}"


def assert_append_only_resource(body: Dict[str, Any]) -> None:
    """Assert an append-only resource carries id/created_at and no version pair."""
    assert is_valid_uuid(body.get("id")), f"id is not a UUID: {body.get('id')!r}"
    assert is_iso8601_timestamp(
        body.get("created_at")
    ), f"created_at is not ISO-8601: {body.get('created_at')!r}"
    assert "updated_at" not in body, "append-only resource must not expose updated_at"
    assert "version" not in body, "append-only resource must not expose version"


def assert_instant_equals(actual: Optional[str], expected: Optional[str], label: str = "instant") -> None:
    """Compare two UTC instants after normalising sub-second precision."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def assert_cents(value: Any, expected: int, label: str = "amount_cents") -> None:
    """Assert a money amount is an integer count of cents equal to `expected`."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be a JSON integer number, got {value!r} ({type(value).__name__})"
    )
    assert value == expected, f"{label}: expected {expected}, got {value}"


def assert_ratio(value: Any, expected: float, places: int = 6, label: str = "ratio") -> None:
    """Assert a fractional value matches `expected` at the declared precision."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be a JSON number, got {value!r} ({type(value).__name__})"
    )
    assert round(float(value), places) == round(float(expected), places), (
        f"{label}: expected {expected} at {places} dp, got {value}"
    )


def assert_index(value: Any, expected: float, label: str = "index") -> None:
    """Assert a two-decimal index value."""
    assert_ratio(value, expected, places=2, label=label)


def assert_score(value: Any, expected: float, label: str = "score") -> None:
    """Assert a two-decimal score value."""
    assert_ratio(value, expected, places=2, label=label)


def assert_is_none(value: Any, label: str = "field") -> None:
    assert value is None, f"{label} must be null, got {value!r}"


# ─── Collection assertions ────────────────────────────────────────────────────


def assert_collection(
    response: requests.Response,
    expected_total: Optional[int] = None,
    expected_len: Optional[int] = None,
    has_more: Optional[bool] = None,
):
    """Validate a list response and optionally pin its counts."""
    rows, meta = validate_paginated(response)
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            f"total_count: expected {expected_total}, got {meta['total_count']}"
        )
    if expected_len is not None:
        assert len(rows) == expected_len, f"row count: expected {expected_len}, got {len(rows)}"
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"has_more: expected {has_more}, got {meta['has_more']}"
        )
    return rows, meta


def assert_ids_equal(rows: Iterable[Dict[str, Any]], expected_ids: Iterable[str]) -> None:
    actual = [row["id"] for row in rows]
    assert actual == list(expected_ids), f"row ids: expected {list(expected_ids)}, got {actual}"


def assert_id_set(rows: Iterable[Dict[str, Any]], expected_ids: Iterable[str]) -> None:
    actual = {row["id"] for row in rows}
    assert actual == set(expected_ids), f"row id set: expected {set(expected_ids)}, got {actual}"


def assert_empty_collection(response: requests.Response):
    return assert_collection(response, expected_total=0, expected_len=0, has_more=False)


# ─── Field-subset assertion ───────────────────────────────────────────────────


def assert_fields(body: Dict[str, Any], **expected: Any) -> None:
    """Assert every named field of `body` equals the supplied value."""
    mismatches = []
    for key, want in expected.items():
        got = body.get(key, "<<absent>>")
        if isinstance(want, float) and isinstance(got, (int, float)) and not isinstance(got, bool):
            if round(float(got), 6) == round(float(want), 6):
                continue
        elif got == want and type(got) is type(want):
            continue
        elif got == want:
            continue
        mismatches.append(f"  {key}: expected {want!r}, got {got!r}")
    assert not mismatches, "field mismatch:\n" + "\n".join(mismatches)


def assert_error(response: requests.Response, error_id: str, status: Optional[int] = None):
    """Assert an error envelope carrying exactly `error_id` (status cross-checked)."""
    return validate_error(response, error_id, status)


def assert_ok(response: requests.Response, status: int = 200):
    return validate_success(response, status)


def assert_created(response: requests.Response):
    return validate_success(response, 201)
