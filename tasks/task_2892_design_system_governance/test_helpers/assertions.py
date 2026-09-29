"""
Domain assertions for the Design System Governance API.

The helpers here read rows that have already been unwrapped from the response
envelope by the framework validators, so nothing in this module indexes `data`
again. Two conventions are enforced throughout: instants are compared through
canonicalisation rather than as raw strings, and decimal fields are compared at
the precision the PRD pins for them rather than as floating-point literals.
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .api_client import canonical_instant
from .constants import (
    AUDIT_METHOD_AUTOMATED,
    AUDIT_METHOD_MANUAL,
    CRITICAL_WEIGHT,
    MODERATE_WEIGHT,
    SERIOUS_WEIGHT,
)
from .types import Row


# ─── Numeric comparison ───────────────────────────────

def assert_decimal_equals(
    actual: Any, expected: float, places: int = 2, label: str = "value"
) -> None:
    """
    Assert a numeric field equals the expected figure at the pinned precision.

    The comparison is made on the rounded pair so that a JSON number decoded as
    a float still matches the exact decimal the PRD prescribes.
    """
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be a JSON number, got {actual!r}"
    )
    assert round(float(actual), places) == round(float(expected), places), (
        f"{label}: expected {expected:.{places}f}, got {actual}"
    )


def assert_decimal_places(actual: Any, places: int, label: str = "value") -> None:
    """Assert a numeric field carries no more precision than the PRD allows."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be a JSON number, got {actual!r}"
    )
    assert round(float(actual), places) == float(actual), (
        f"{label} carries more than {places} decimal places: {actual}"
    )


def assert_in_range(
    actual: Any, low: float, high: float, label: str = "value"
) -> None:
    """Assert a numeric field lies on the closed interval the PRD pins for it."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be a JSON number, got {actual!r}"
    )
    assert low <= float(actual) <= high, (
        f"{label} must lie between {low} and {high}, got {actual}"
    )


# ─── Instant comparison ───────────────────────────────

def assert_instant_equals(actual: Any, expected: str, label: str = "instant") -> None:
    """Assert two instants denote the same moment regardless of digit width."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_instant_format(actual: Any, label: str = "instant") -> None:
    """Assert a field is an ISO 8601 UTC instant."""
    assert is_iso8601_timestamp(actual), f"{label} is not an ISO 8601 instant: {actual!r}"


# ─── Field-set comparison ─────────────────────────────

def assert_fields(row: Row, expected: Dict[str, Any], label: str = "row") -> None:
    """
    Assert every named field of a row equals its expected value.

    Numeric expectations are compared at four decimal places, which is the widest
    precision any field in this API carries; instants are canonicalised first.
    """
    for field, want in expected.items():
        assert field in row, f"{label} is missing field '{field}': {sorted(row)}"
        got = row[field]
        if isinstance(want, float):
            assert_decimal_equals(got, want, places=4, label=f"{label}.{field}")
        elif isinstance(want, str) and is_iso8601_timestamp(want):
            assert_instant_equals(got, want, label=f"{label}.{field}")
        else:
            assert got == want, f"{label}.{field}: expected {want!r}, got {got!r}"


def assert_absent(row: Row, fields: Sequence[str], label: str = "row") -> None:
    """Assert the named fields do not appear on the row at all."""
    for field in fields:
        assert field not in row, (
            f"{label} must not carry '{field}', but it is present as {row[field]!r}"
        )


# ─── System-field discipline ──────────────────────────

def assert_versioned_row(row: Row, expected_version: Optional[int] = None,
                         label: str = "row") -> None:
    """
    Assert a row carries the full audit quadruple of the PRD's versioned entities.

    The `id` must be a bare server-minted UUID, and `created_at`, `updated_at`
    and `version` must all be present.
    """
    assert is_valid_uuid(row.get("id")), f"{label}.id is not a bare UUID: {row.get('id')!r}"
    assert_instant_format(row.get("created_at"), f"{label}.created_at")
    assert_instant_format(row.get("updated_at"), f"{label}.updated_at")
    assert isinstance(row.get("version"), int), f"{label}.version must be an integer"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"{label}.version: expected {expected_version}, got {row['version']}"
        )


def assert_append_only_row(row: Row, label: str = "row") -> None:
    """
    Assert a row belongs to the API's append-only family.

    Such rows carry an `id` and a `created_at` and nothing else from the system
    field set: neither `updated_at` nor `version` may appear.
    """
    assert is_valid_uuid(row.get("id")), f"{label}.id is not a bare UUID: {row.get('id')!r}"
    assert_instant_format(row.get("created_at"), f"{label}.created_at")
    assert_absent(row, ["updated_at", "version"], label)


def assert_server_minted_id(row: Row, rejected_id: str, label: str = "row") -> None:
    """Assert the server minted its own id rather than honouring a client's."""
    assert is_valid_uuid(row.get("id")), f"{label}.id is not a bare UUID: {row.get('id')!r}"
    assert row["id"] != rejected_id, (
        f"{label}.id echoed the client-supplied id {rejected_id}"
    )


# ─── Envelope shape ───────────────────────────────────

def assert_object_envelope(response) -> None:
    """Assert a single-resource response declares itself as an object."""
    body = response.json()
    assert body.get("response_type") == "object", (
        f"expected response_type 'object', got {body.get('response_type')!r}"
    )


def assert_array_envelope(response) -> None:
    """Assert a listing response declares itself as an array."""
    body = response.json()
    assert body.get("response_type") == "array", (
        f"expected response_type 'array', got {body.get('response_type')!r}"
    )
    assert isinstance(body.get("data"), list), "listing data must be an array"


def assert_error_envelope(response) -> None:
    """Assert a refusal declares itself as an error."""
    body = response.json()
    assert body.get("response_type") == "error", (
        f"expected response_type 'error', got {body.get('response_type')!r}"
    )


def assert_request_meta(response) -> None:
    """Assert the envelope's request identifier and timestamp obey their formats."""
    meta = response.json()["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert_instant_format(meta.get("api_request_timestamp"), "meta.api_request_timestamp")


def assert_page_meta(
    meta: Dict[str, Any],
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> None:
    """Assert the pagination counters carried alongside a listing."""
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"meta.total_count: expected {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"meta.has_more: expected {has_more}, got {meta['has_more']}"
        )
    if limit is not None:
        assert meta["limit"] == limit, f"meta.limit: expected {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, (
            f"meta.offset: expected {offset}, got {meta['offset']}"
        )


# ─── Ordering ─────────────────────────────────────────

def assert_ascending(rows: List[Row], field: str) -> None:
    """Assert rows are ordered by a field ascending."""
    values = [row[field] for row in rows]
    assert values == sorted(values), f"rows are not ascending by {field}: {values}"


def assert_descending(rows: List[Row], field: str) -> None:
    """Assert rows are ordered by a field descending."""
    values = [row[field] for row in rows]
    assert values == sorted(values, reverse=True), (
        f"rows are not descending by {field}: {values}"
    )


def assert_created_at_ascending(rows: List[Row]) -> None:
    """Assert rows follow the API's default creation-order listing."""
    values = [canonical_instant(row["created_at"]) for row in rows]
    assert values == sorted(values), f"rows are not in created_at order: {values}"


# ─── Derived arithmetic mirrors ───────────────────────

def defect_load(critical: int, serious: int, moderate: int) -> int:
    """The PRD's severity-weighted defect load for one audit row."""
    return (
        CRITICAL_WEIGHT * critical
        + SERIOUS_WEIGHT * serious
        + MODERATE_WEIGHT * moderate
    )


def assert_defect_load(row: Row, critical: int, serious: int, moderate: int) -> None:
    """Assert an audit row's stored defect load matches the weighted sum."""
    expected = defect_load(critical, serious, moderate)
    assert row["defect_load"] == expected, (
        f"defect_load: expected {expected} for "
        f"({critical} critical, {serious} serious, {moderate} moderate), "
        f"got {row['defect_load']}"
    )


def assert_audit_row(
    row: Row,
    audit_sequence: int,
    critical: int,
    serious: int,
    moderate: int,
    method: str = AUDIT_METHOD_AUTOMATED,
) -> None:
    """Assert the shape and arithmetic of one filed accessibility audit."""
    assert_append_only_row(row, "audit")
    assert row["audit_sequence"] == audit_sequence, (
        f"audit_sequence: expected {audit_sequence}, got {row['audit_sequence']}"
    )
    assert row["method"] == method
    assert_defect_load(row, critical, serious, moderate)


def assert_conformance_score(row: Row, expected: float, field: str = "conformance_score") -> None:
    """Assert a conformance score reads the expected figure to two places."""
    assert_decimal_equals(row[field], expected, places=2, label=field)
    assert_in_range(row[field], 0.00, 100.00, field)


def assert_breaking_ratio(row: Row, expected: float) -> None:
    """Assert the release breaking ratio reads to the four places the PRD pins."""
    assert_decimal_equals(row["breaking_ratio"], expected, places=4, label="breaking_ratio")
    assert_in_range(row["breaking_ratio"], 0.0000, 1.0000, "breaking_ratio")


def assert_debt_points(row: Row, expected: float, field: str = "debt_points") -> None:
    """Assert a debt figure reads to two places and is never negative."""
    assert_decimal_equals(row[field], expected, places=2, label=field)
    assert float(row[field]) >= 0.0, f"{field} may not be negative, got {row[field]}"


AUDIT_METHODS_FOR_SCORING = [AUDIT_METHOD_AUTOMATED, AUDIT_METHOD_MANUAL]
