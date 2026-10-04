"""Domain assertions for the Digital Makeline Capacity API.

These wrap the shared structural helpers with the vocabulary of this contract:
instants compare on their canonical form rather than on raw strings, money is
always an integer number of cents, and the common entity shape is checked once
here instead of in every test.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .api_client import canonical_instant


# ── Instants ───────────────────────────────────────────────────────────────

def assert_instant(actual: Optional[str], expected: Optional[str], label: str = "instant") -> None:
    """Assert two ISO 8601 UTC instants denote the same moment.

    Sub-second precision is not part of the comparison: both sides are reduced
    to a canonical three-digit form first, so a value rendered without a
    fractional part still matches the same moment rendered with one.
    """
    if expected is None:
        assert actual is None, f"{label}: expected null, got {actual!r}"
        return
    assert actual is not None, f"{label}: expected {expected!r}, got null"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def assert_instant_format(value: str, label: str = "instant") -> None:
    """Assert a value is an ISO 8601 UTC instant in the rendering the contract uses."""
    assert isinstance(value, str) and value, f"{label}: expected a non-empty string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{label}: not an ISO 8601 UTC instant: {value!r}"
    assert value.endswith("Z"), f"{label}: must be rendered in UTC with a Z suffix: {value!r}"


# ── Numbers ────────────────────────────────────────────────────────────────

def assert_cents(actual: Any, expected: int, label: str = "amount") -> None:
    """Assert a money amount, which the contract carries as an integer number of cents."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label}: money must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_int(actual: Any, expected: int, label: str = "value") -> None:
    """Assert an integer counter equals the expected figure exactly."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label}: must be an integer, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


# ── Envelope and common fields ─────────────────────────────────────────────

def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """Assert the meta block carries a prefixed request id and a UTC instant."""
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert_instant_format(meta["api_request_timestamp"], "meta.api_request_timestamp")


def assert_mutable_common_fields(data: Dict[str, Any], label: str = "entity") -> None:
    """Assert the full identity quartet on a resource that can be mutated."""
    assert is_valid_uuid(data.get("id")), f"{label}.id must be a UUID, got {data.get('id')!r}"
    assert_instant_format(data["created_at"], f"{label}.created_at")
    assert_instant_format(data["updated_at"], f"{label}.updated_at")
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version starts at 1, got {data['version']}"


def assert_created_equals_updated(data: Dict[str, Any], label: str = "entity") -> None:
    """Assert a freshly created resource has not been touched since creation."""
    assert_instant(data["updated_at"], data["created_at"], f"{label}.updated_at")
    assert data["version"] == 1, f"{label}.version on creation must be 1, got {data['version']}"


# ── Listing envelope ───────────────────────────────────────────────────────

def assert_list_page(meta: Dict[str, Any], limit: int, offset: int, total: int, has_more: bool) -> None:
    """Assert a list response reports the page it served and the size of the collection."""
    assert meta["limit"] == limit, f"meta.limit: expected {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"meta.offset: expected {offset}, got {meta['offset']}"
    assert meta["total_count"] == total, (
        f"meta.total_count: expected {total}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, f"meta.has_more: expected {has_more}, got {meta['has_more']}"
