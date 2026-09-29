"""Domain assertion helpers.

Two conventions matter here and are applied consistently:

1. Envelope. ``validate_success`` and ``get_success_data`` already return the
   inner ``data`` payload, so every helper below takes a resource dictionary,
   never a full envelope, and never indexes ``["data"]`` again.
2. Decimals. PRD 2.5 fixes a decimal scale per field, so a decimal-valued field
   is compared through ``Decimal(str(value))`` quantised to that scale. This
   accepts a JSON number and a JSON string spelling of the same value and
   rejects a value whose scale is wrong for the field.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant
from .constants import COMMON_FIELDS_FULL, COMMON_FIELDS_WRITE_ONCE


def as_decimal(value: Any) -> Decimal:
    """Coerce a JSON number or numeric string to ``Decimal`` losslessly."""
    assert value is not None, "expected a numeric value, got null"
    return Decimal(str(value))


def quantize(value: Any, places: int) -> Decimal:
    exp = Decimal(1).scaleb(-places)
    return as_decimal(value).quantize(exp, rounding=ROUND_HALF_UP)


def assert_decimal_equals(actual: Any, expected: str, places: int,
                          field: str = "value") -> None:
    """Assert a decimal-valued field equals ``expected`` at ``places`` decimals."""
    assert actual is not None, f"{field}: expected {expected}, got null"
    got = as_decimal(actual)
    want = Decimal(expected)
    assert got == want, f"{field}: expected {expected}, got {actual}"
    assert quantize(actual, places) == want, (
        f"{field}: expected {expected} at {places} decimals, got {actual}"
    )


def assert_pct_2dp(actual: Any, expected: str, field: str = "percentage") -> None:
    """A two-decimal percentage field (PRD 2.5)."""
    assert_decimal_equals(actual, expected, 2, field)


def assert_pct_3dp(actual: Any, expected: str, field: str = "percentage") -> None:
    """A three-decimal percentage field (PRD 2.5)."""
    assert_decimal_equals(actual, expected, 3, field)


def assert_ratio_4dp(actual: Any, expected: str, field: str = "ratio") -> None:
    """A four-decimal ratio field (PRD 2.5)."""
    assert_decimal_equals(actual, expected, 4, field)


def assert_money(actual: Any, expected: int, field: str = "amount_cents") -> None:
    """A money field: PRD 2.5 declares monetary amounts as integer cents."""
    assert actual is not None, f"{field}: expected {expected}, got null"
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field}: expected an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{field}: expected {expected}, got {actual}"


def assert_is_null(row: Dict[str, Any], *fields: str) -> None:
    for field in fields:
        assert field in row, f"missing field {field}"
        assert row[field] is None, f"{field}: expected null, got {row[field]!r}"


def assert_fields(row: Dict[str, Any], expected: Dict[str, Any]) -> None:
    """Assert a batch of exact-equality fields on one resource row."""
    for field, want in expected.items():
        assert field in row, f"missing field {field}"
        assert row[field] == want, f"{field}: expected {want!r}, got {row[field]!r}"


def assert_common_fields(row: Dict[str, Any], write_once: bool = False) -> None:
    """PRD 2.4 common fields.

    Every resource carries a UUID ``id`` and an ISO-8601 ``created_at``. Every
    resource except the write-once credit event also carries ``updated_at`` and
    an integer ``version``.
    """
    names = COMMON_FIELDS_WRITE_ONCE if write_once else COMMON_FIELDS_FULL
    for field in names:
        assert field in row, f"missing common field {field}"
    assert is_valid_uuid(row["id"]), f"id is not a UUID: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), (
        f"created_at is not an ISO-8601 timestamp: {row['created_at']!r}"
    )
    if not write_once:
        assert is_iso8601_timestamp(row["updated_at"]), (
            f"updated_at is not an ISO-8601 timestamp: {row['updated_at']!r}"
        )
        assert isinstance(row["version"], int) and not isinstance(row["version"], bool), (
            f"version is not an integer: {row['version']!r}"
        )


def assert_created_row(row: Dict[str, Any], write_once: bool = False) -> None:
    """A freshly created resource: common fields present and ``version`` is 1."""
    assert_common_fields(row, write_once=write_once)
    if not write_once:
        assert row["version"] == 1, f"new resource version: expected 1, got {row['version']}"


def assert_version(row: Dict[str, Any], expected: int) -> None:
    assert row["version"] == expected, (
        f"version: expected {expected}, got {row['version']}"
    )


def assert_instant_equals(actual: Optional[str], expected: str,
                          field: str = "timestamp") -> None:
    """Compare two ISO-8601 instants irrespective of sub-second width."""
    assert actual is not None, f"{field}: expected {expected}, got null"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{field}: expected {expected}, got {actual}"
    )


def assert_codes_in_order(actual: Sequence[str], expected: Sequence[str],
                          field: str = "codes") -> None:
    """An array field the PRD emits in a fixed order: order is part of the value."""
    assert list(actual) == list(expected), (
        f"{field}: expected {list(expected)}, got {list(actual)}"
    )


def ids_of(rows: Iterable[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


def assert_ids_equal(rows: Iterable[Dict[str, Any]], expected: Sequence[str],
                     field: str = "ids") -> None:
    assert ids_of(rows) == list(expected), (
        f"{field}: expected {list(expected)}, got {ids_of(rows)}"
    )


def assert_created_at_ascending(rows: Sequence[Dict[str, Any]]) -> None:
    """PRD 2.3 orders every collection by ``created_at`` ascending."""
    stamps = [canonical_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), f"rows are not in created_at order: {stamps}"


def assert_meta_pagination(meta: Dict[str, Any], limit: int, offset: int,
                           total_count: int, has_more: bool) -> None:
    """PRD 2.2 pagination metadata."""
    assert_fields(meta, {"limit": limit, "offset": offset,
                         "total_count": total_count, "has_more": has_more})
