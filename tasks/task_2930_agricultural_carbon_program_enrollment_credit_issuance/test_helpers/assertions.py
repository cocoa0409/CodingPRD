"""Domain assertions for the agricultural carbon programme contract.

These helpers keep the tests readable and, more importantly, keep the numeric
and temporal comparisons honest: tonnages carry three decimals, percentages and
acreages two, monetary amounts are integer cents, and every timestamp is an
ISO 8601 UTC instant whose sub-second width is not part of the contract.
"""

import re
from typing import Any, Dict, Iterable, Optional

import pytest

from prd_bench_local_runner.testing import (
    assert_timestamp_format,
    is_iso8601_timestamp,
    is_valid_uuid,
)

TONNE_TOLERANCE = 0.0005
PCT_TOLERANCE = 0.005
ACRE_TOLERANCE = 0.005
RATE_TOLERANCE = 0.00005

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.(\d+))?(?:Z|\+00:00)?$"
)


def canonical_instant(value: str) -> str:
    """Normalise an ISO 8601 UTC instant to second precision with a ``Z`` suffix.

    Sub-second width is an encoding detail, so two instants that name the same
    second compare equal through this helper.
    """
    assert isinstance(value, str), f"expected an ISO 8601 instant string, got {value!r}"
    match = _INSTANT_RE.match(value.strip())
    assert match, f"not an ISO 8601 UTC instant: {value!r}"
    return f"{match.group(1)}T{match.group(2)}Z"


def assert_instant_equals(actual: str, expected: str) -> None:
    """Assert two ISO 8601 UTC instants name the same second."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"instant mismatch: actual={actual!r} expected={expected!r}"
    )


def assert_is_instant(value: str) -> None:
    """Assert a value is an ISO 8601 UTC instant."""
    assert_timestamp_format(value)


def assert_iso_date(value: str) -> None:
    """Assert a value carries a calendar date in ISO 8601 order."""
    assert isinstance(value, str), f"expected a date string, got {value!r}"
    assert re.match(r"^\d{4}-\d{2}-\d{2}", value), f"not an ISO 8601 date: {value!r}"


def visit_day(value: str) -> str:
    """Reduce a site-visit boundary to its calendar day.

    A site-visit boundary is filed as a calendar date but arrival recording
    restamps the start with the logical clock instant, so comparisons are made
    on the calendar day the value names.
    """
    assert isinstance(value, str) and len(value) >= 10, (
        f"expected a site-visit date, got {value!r}"
    )
    return value[:10]


def assert_visit_day(actual: str, expected: str) -> None:
    """Assert a site-visit boundary names the expected calendar day."""
    assert visit_day(actual) == visit_day(expected), (
        f"site-visit day mismatch: actual={actual!r} expected={expected!r}"
    )


def assert_common_fields(entity: Dict[str, Any]) -> None:
    """Assert the four audit fields carried by every mutable resource."""
    for key in ("id", "created_at", "updated_at", "version"):
        assert key in entity, f"missing audit field {key!r} in {sorted(entity)}"
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at is not an ISO 8601 instant: {entity['created_at']!r}"
    )
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"updated_at is not an ISO 8601 instant: {entity['updated_at']!r}"
    )
    assert isinstance(entity["version"], int) and not isinstance(entity["version"], bool), (
        f"version is not an integer: {entity['version']!r}"
    )
    assert entity["version"] >= 1, f"version must start at 1, got {entity['version']!r}"


def assert_immutable_common_fields(entity: Dict[str, Any]) -> None:
    """Assert an immutable resource carries only ``id`` and ``created_at``."""
    for key in ("id", "created_at"):
        assert key in entity, f"missing audit field {key!r} in {sorted(entity)}"
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at is not an ISO 8601 instant: {entity['created_at']!r}"
    )
    for key in ("updated_at", "version"):
        assert key not in entity, f"immutable resource must not carry {key!r}"


def assert_tonnes(actual: Any, expected: float) -> None:
    """Assert a tonnage figure at the three-decimal precision of the contract."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"tonnage must be a JSON number, got {actual!r}"
    )
    assert actual == pytest.approx(expected, abs=TONNE_TOLERANCE), (
        f"tonnage mismatch: actual={actual!r} expected={expected!r}"
    )


def assert_pct(actual: Any, expected: float) -> None:
    """Assert a percentage figure at the two-decimal precision of the contract."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"percentage must be a JSON number, got {actual!r}"
    )
    assert actual == pytest.approx(expected, abs=PCT_TOLERANCE), (
        f"percentage mismatch: actual={actual!r} expected={expected!r}"
    )


def assert_acres(actual: Any, expected: float) -> None:
    """Assert an acreage figure at the two-decimal precision of the contract."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"acreage must be a JSON number, got {actual!r}"
    )
    assert actual == pytest.approx(expected, abs=ACRE_TOLERANCE), (
        f"acreage mismatch: actual={actual!r} expected={expected!r}"
    )


def assert_rate(actual: Any, expected: float) -> None:
    """Assert a per-acre rate at the four-decimal precision of the contract."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"rate must be a JSON number, got {actual!r}"
    )
    assert actual == pytest.approx(expected, abs=RATE_TOLERANCE), (
        f"rate mismatch: actual={actual!r} expected={expected!r}"
    )


def assert_cents(actual: Any, expected: int) -> None:
    """Assert a monetary amount is the exact integer number of cents."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"monetary amount must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"cents mismatch: actual={actual!r} expected={expected!r}"


def assert_credits(actual: Any, expected: int) -> None:
    """Assert a credit count is the exact whole number of credits."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"credit count must be a whole number, got {actual!r}"
    )
    assert actual == expected, f"credit mismatch: actual={actual!r} expected={expected!r}"


def assert_fields_equal(entity: Dict[str, Any], expected: Dict[str, Any]) -> None:
    """Assert every named field of a resource, comparing numbers tolerantly."""
    for key, want in expected.items():
        assert key in entity, f"missing field {key!r} in {sorted(entity)}"
        got = entity[key]
        if isinstance(want, float):
            assert got == pytest.approx(want, abs=PCT_TOLERANCE), (
                f"field {key!r} mismatch: actual={got!r} expected={want!r}"
            )
        else:
            assert got == want, f"field {key!r} mismatch: actual={got!r} expected={want!r}"


def assert_unchanged(before: Dict[str, Any], after: Dict[str, Any],
                     keys: Iterable[str]) -> None:
    """Assert the named fields did not move between two reads of a resource."""
    for key in keys:
        assert before.get(key) == after.get(key), (
            f"field {key!r} moved: before={before.get(key)!r} after={after.get(key)!r}"
        )


def assert_version_unchanged(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    """Assert a refused write left the optimistic-concurrency version alone."""
    assert after["version"] == before["version"], (
        f"version moved on a refused write: {before['version']} -> {after['version']}"
    )


def assert_ids(entities: Iterable[Dict[str, Any]], expected_ids: Iterable[str]) -> None:
    """Assert a listing carries exactly the expected resource ids, order-free."""
    got = sorted(e["id"] for e in entities)
    want = sorted(expected_ids)
    assert got == want, f"listing id mismatch: actual={got} expected={want}"


def assert_ordered_by(entities: Iterable[Dict[str, Any]], key: str,
                      descending: bool = False) -> None:
    """Assert a listing is ordered by one field."""
    values = [e[key] for e in entities]
    expected = sorted(values, reverse=descending)
    assert values == expected, f"listing not ordered by {key!r}: {values}"


def assert_error_envelope(body: Dict[str, Any], expected_error_id: Optional[str] = None) -> None:
    """Assert the error envelope: meta with two keys, ``error`` type, error_id and message."""
    assert body.get("response_type") == "error", (
        f"expected response_type 'error', got {body.get('response_type')!r}"
    )
    meta = body.get("meta")
    assert isinstance(meta, dict), f"expected a meta object, got {body!r}"
    assert set(meta) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta must carry only api_request_id and api_request_timestamp, got {sorted(meta)}"
    )
    assert isinstance(meta["api_request_id"], str) and meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_': {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), (
        f"api_request_timestamp must be an ISO 8601 UTC timestamp: "
        f"{meta['api_request_timestamp']!r}"
    )
    error = body.get("data")
    assert isinstance(error, dict), f"expected an error payload in data, got {body!r}"
    for key in ("error_id", "message"):
        assert key in error, f"missing error field {key!r} in {sorted(error)}"
    assert isinstance(error["message"], str) and error["message"].strip(), (
        "error message must be non-empty"
    )
    if expected_error_id is not None:
        assert error["error_id"] == expected_error_id, (
            f"error_id mismatch: actual={error['error_id']!r} expected={expected_error_id!r}"
        )


def assert_success_envelope(body: Dict[str, Any], expected_response_type: str = "object") -> None:
    """Assert the success envelope: meta, a declared response type, and a data payload."""
    assert "meta" in body, f"expected a meta object, got {sorted(body)}"
    assert "data" in body, f"expected a data payload, got {sorted(body)}"
    assert body.get("response_type") == expected_response_type, (
        f"expected response_type {expected_response_type!r}, got {body.get('response_type')!r}"
    )
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str), "meta.api_request_id must be a string"
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_': {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), (
        f"api_request_timestamp must be an ISO 8601 UTC timestamp: "
        f"{meta.get('api_request_timestamp')!r}"
    )
