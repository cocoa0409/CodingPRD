"""
Domain assertions for the Renewable Land Origination API test suite.

The comparison helpers exist because the wire format is deliberately looser than
the values under test. Instants may render with or without fractional seconds,
acreage is a two-decimal quantity that JSON may deliver as int or float, and
money is an integer count of cents that must never be compared as a string.
Each helper narrows the wire value to the domain value before comparing, so a
formatting difference can never masquerade as a business-rule defect.
"""

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
)

from .constants import (
    COMMON_FIELDS,
    LEDGER_ROW_FIELDS,
    LEDGER_ROW_FORBIDDEN_FIELDS,
)

_INSTANT_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})T(?P<time>\d{2}:\d{2}:\d{2})(?:\.(?P<frac>\d+))?Z$"
)


# ─── Instants ─────────────────────────────────────────

def normalize_instant(value: str) -> str:
    """
    Reduce an ISO-8601 UTC instant to whole-second precision.

    Fractional-second width is a rendering choice, not a business fact, so two
    instants that name the same second must compare equal regardless of how many
    fractional digits either one carries.
    """
    assert isinstance(value, str), f"expected an instant string, got {value!r}"
    match = _INSTANT_RE.match(value)
    assert match is not None, f"not a UTC ISO-8601 instant: {value!r}"
    frac = match.group("frac")
    if frac is not None:
        # Only a zero fraction may be discarded; a non-zero fraction is a real
        # sub-second offset and must survive so a mismatch is still visible.
        assert int(frac) == 0, f"instant carries a non-zero fraction: {value!r}"
    return f"{match.group('date')}T{match.group('time')}Z"


def assert_instant_equals(actual: Any, expected: str, label: str = "instant") -> None:
    """Assert an instant names the expected second."""
    assert actual is not None, f"{label} is missing"
    assert normalize_instant(actual) == normalize_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_is_instant(value: Any, label: str = "instant") -> None:
    """Assert a value is a well-formed ISO-8601 UTC instant."""
    assert isinstance(value, str), f"{label} should be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{label} is not ISO-8601: {value!r}"


def assert_is_date(value: Any, label: str = "date") -> None:
    """Assert a value is a bare calendar date."""
    assert isinstance(value, str), f"{label} should be a string, got {value!r}"
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", value), f"{label} is not a date: {value!r}"


def assert_null(value: Any, label: str = "field") -> None:
    """Assert a nullable field is actually null."""
    assert value is None, f"{label} should be null, got {value!r}"


# ─── Money ────────────────────────────────────────────

def as_cents(value: Any, label: str = "amount") -> int:
    """
    Narrow a wire money value to an integer count of cents.

    Money is transported as an integer number of cents. A string is rejected
    outright rather than coerced, because a quoted amount is a contract defect
    the suite must surface rather than paper over.
    """
    assert not isinstance(value, str), (
        f"{label} must be an integer number of cents, not a string: {value!r}"
    )
    assert not isinstance(value, bool), f"{label} must be an integer, got {value!r}"
    assert isinstance(value, int), f"{label} must be an integer, got {value!r}"
    return value


def assert_cents_equals(actual: Any, expected: int, label: str = "amount") -> None:
    """Assert a money field equals an exact number of cents."""
    assert as_cents(actual, label) == expected, (
        f"{label}: expected {expected} cents, got {actual}"
    )


# ─── Acreage and other two-decimal quantities ─────────

def as_decimal2(value: Any, label: str = "quantity") -> float:
    """Narrow a wire two-decimal quantity to a float."""
    assert not isinstance(value, str), (
        f"{label} must be a number, not a string: {value!r}"
    )
    assert not isinstance(value, bool), f"{label} must be a number, got {value!r}"
    assert isinstance(value, (int, float)), f"{label} must be a number, got {value!r}"
    return float(value)


def assert_acres_equals(actual: Any, expected: float, label: str = "acres") -> None:
    """
    Assert an acreage equals an exact two-decimal value.

    The tolerance is half of the last retained decimal place, which admits only
    binary-float representation noise and never a genuine rounding difference.
    """
    got = as_decimal2(actual, label)
    assert abs(got - expected) < 0.005, (
        f"{label}: expected {expected:.2f} acres, got {got}"
    )


def assert_score_equals(actual: Any, expected: float, label: str = "score") -> None:
    """Assert a two-decimal score equals an exact value."""
    got = as_decimal2(actual, label)
    assert abs(got - expected) < 0.005, f"{label}: expected {expected:.2f}, got {got}"


def assert_rate_equals(actual: Any, expected: float, label: str = "rate") -> None:
    """Assert a four-decimal rate equals an exact value."""
    got = as_decimal2(actual, label)
    assert abs(got - expected) < 0.00005, f"{label}: expected {expected}, got {got}"


# ─── Common properties ────────────────────────────────

def assert_common_fields(resource: Dict[str, Any], label: str = "resource") -> None:
    """Assert a resource carries the full common set with well-formed values."""
    for field in COMMON_FIELDS:
        assert field in resource, f"{label} is missing {field}"
    assert is_valid_uuid(resource["id"]), f"{label}.id is not a UUID: {resource['id']}"
    assert_is_instant(resource["created_at"], f"{label}.created_at")
    assert_is_instant(resource["updated_at"], f"{label}.updated_at")
    assert isinstance(resource["version"], int) and not isinstance(
        resource["version"], bool
    ), f"{label}.version should be an integer, got {resource['version']!r}"
    assert resource["version"] >= 1, f"{label}.version should start at 1"


def assert_ledger_row_shape(row: Dict[str, Any], label: str = "ledger row") -> None:
    """
    Assert an immutable ledger row carries id and created_at and nothing else
    from the common set.
    """
    for field in LEDGER_ROW_FIELDS:
        assert field in row, f"{label} is missing {field}"
    assert is_valid_uuid(row["id"]), f"{label}.id is not a UUID: {row['id']}"
    assert_is_instant(row["created_at"], f"{label}.created_at")
    for field in LEDGER_ROW_FORBIDDEN_FIELDS:
        assert field not in row, f"{label} should not carry {field}"


def assert_version_is(resource: Dict[str, Any], expected: int, label: str = "resource") -> None:
    """Assert a resource sits at an exact version."""
    assert resource["version"] == expected, (
        f"{label}.version: expected {expected}, got {resource['version']}"
    )


def assert_version_advanced(
    before: Dict[str, Any], after: Dict[str, Any], label: str = "resource"
) -> None:
    """
    Assert a row's version moved forward.

    The exact size of the step is deliberately not pinned. §2.4 states that a
    cascade-driven parcel write leaves the row "two or three higher" because each
    procedure in the chain touches it in turn, so the only fact a cascade
    assertion may rely on is that the counter advanced.
    """
    assert after["version"] > before["version"], (
        f"{label}.version did not advance: was {before['version']}, "
        f"still {after['version']}"
    )


def assert_unchanged(
    before: Dict[str, Any],
    after: Dict[str, Any],
    fields: Sequence[str],
    label: str = "resource",
) -> None:
    """Assert a set of fields is byte-identical across two reads."""
    for field in fields:
        assert before.get(field) == after.get(field), (
            f"{label}.{field} changed from {before.get(field)!r} to {after.get(field)!r}"
        )


# ─── Collections ──────────────────────────────────────

def assert_ids_equal(
    rows: Iterable[Dict[str, Any]], expected_ids: Sequence[str], label: str = "list"
) -> None:
    """Assert a collection holds exactly the expected ids, in order."""
    actual = [row["id"] for row in rows]
    assert actual == list(expected_ids), (
        f"{label}: expected ids {list(expected_ids)}, got {actual}"
    )


def assert_id_set(
    rows: Iterable[Dict[str, Any]], expected_ids: Sequence[str], label: str = "list"
) -> None:
    """Assert a collection holds exactly the expected ids, in any order."""
    actual = sorted(row["id"] for row in rows)
    assert actual == sorted(expected_ids), (
        f"{label}: expected ids {sorted(expected_ids)}, got {actual}"
    )


def assert_contains_id(
    rows: Iterable[Dict[str, Any]], expected_id: str, label: str = "list"
) -> Dict[str, Any]:
    """Assert a collection contains a given id and return that row."""
    for row in rows:
        if row.get("id") == expected_id:
            return row
    raise AssertionError(f"{label} does not contain id {expected_id}")


def assert_excludes_id(
    rows: Iterable[Dict[str, Any]], forbidden_id: str, label: str = "list"
) -> None:
    """Assert a collection does not contain a given id."""
    ids = [row.get("id") for row in rows]
    assert forbidden_id not in ids, f"{label} unexpectedly contains id {forbidden_id}"


def assert_page_meta(
    meta: Dict[str, Any],
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> None:
    """Assert the pagination block reports the expected window."""
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"total_count: expected {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"has_more: expected {has_more}, got {meta['has_more']}"
        )
    if limit is not None:
        assert meta["limit"] == limit, f"limit: expected {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, (
            f"offset: expected {offset}, got {meta['offset']}"
        )


def assert_ascending_by_created_at(rows: List[Dict[str, Any]], label: str = "list") -> None:
    """Assert a collection is ordered oldest first, which is the only order here."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), (
        f"{label} is not ordered by created_at ascending: {stamps}"
    )


# ─── Status helpers ───────────────────────────────────

def assert_status(resource: Dict[str, Any], expected: str, label: str = "resource") -> None:
    """Assert a resource sits in an exact status."""
    assert resource.get("status") == expected, (
        f"{label}.status: expected {expected}, got {resource.get('status')!r}"
    )


def assert_lease_dimensions(
    lease: Dict[str, Any], rent_status: str, recording_status: str
) -> None:
    """
    Assert both of a lease's independent lifecycle dimensions at once.

    A lease advances along a rent dimension and a recording dimension that move
    independently, so pinning one without the other would leave the pair
    unverified.
    """
    assert lease.get("rent_status") == rent_status, (
        f"lease.rent_status: expected {rent_status}, got {lease.get('rent_status')!r}"
    )
    assert lease.get("recording_status") == recording_status, (
        "lease.recording_status: expected "
        f"{recording_status}, got {lease.get('recording_status')!r}"
    )


__all__ = [
    "normalize_instant",
    "assert_instant_equals",
    "assert_is_instant",
    "assert_is_date",
    "assert_null",
    "as_cents",
    "assert_cents_equals",
    "as_decimal2",
    "assert_acres_equals",
    "assert_score_equals",
    "assert_rate_equals",
    "assert_common_fields",
    "assert_ledger_row_shape",
    "assert_version_is",
    "assert_version_advanced",
    "assert_unchanged",
    "assert_ids_equal",
    "assert_id_set",
    "assert_contains_id",
    "assert_excludes_id",
    "assert_page_meta",
    "assert_ascending_by_created_at",
    "assert_status",
    "assert_lease_dimensions",
    "validate_paginated",
]
