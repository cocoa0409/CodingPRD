"""Domain assertion helpers.

Money fields are JSON numbers carrying two decimal places, so they are compared
through Decimal at a fixed scale rather than as floats. Instant fields are
compared as instants, so a response that writes an instant with a different
sub-second width still matches the value the PRD specifies.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# ---------------------------------------------------------------------------
# money and numbers
# ---------------------------------------------------------------------------


def to_decimal(value: Any) -> Decimal:
    assert value is not None, "expected a numeric value, got null"
    assert not isinstance(value, str), (
        f"money and rate fields must be JSON numbers, got the string {value!r}"
    )
    assert not isinstance(value, bool), f"expected a number, got the boolean {value!r}"
    return Decimal(str(value))


def assert_money(actual: Any, expected: float, field: str = "amount") -> None:
    """Compare a 2-decimal money field."""
    got = to_decimal(actual).quantize(Decimal("0.01"))
    want = Decimal(str(expected)).quantize(Decimal("0.01"))
    assert got == want, f"{field}: expected {want}, got {got}"


def assert_money_fields(payload: Dict[str, Any], expected: Dict[str, float]) -> None:
    for field, value in expected.items():
        assert field in payload, f"missing field {field} in {sorted(payload)}"
        assert_money(payload[field], value, field)


def assert_number(actual: Any, expected: float, field: str = "value") -> None:
    """Compare a numeric field that keeps the precision it was supplied with."""
    got = to_decimal(actual)
    want = Decimal(str(expected))
    assert got == want, f"{field}: expected {want}, got {got}"


def assert_two_decimal_places(value: Any, field: str = "amount") -> None:
    dec = to_decimal(value)
    assert -dec.as_tuple().exponent <= 2, (
        f"{field}: expected at most 2 decimal places, got {dec}"
    )


def assert_int(actual: Any, expected: int, field: str = "count") -> None:
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field}: expected an integer, got {actual!r}"
    )
    assert actual == expected, f"{field}: expected {expected}, got {actual}"


def assert_fields(payload: Dict[str, Any], expected: Dict[str, Any]) -> None:
    """Exact equality for non-money fields (enums, ids, booleans, counts)."""
    for field, value in expected.items():
        assert field in payload, f"missing field {field} in {sorted(payload)}"
        assert payload[field] == value, (
            f"{field}: expected {value!r}, got {payload[field]!r}"
        )


def assert_null_fields(payload: Dict[str, Any], fields: Iterable[str]) -> None:
    for field in fields:
        assert field in payload, f"missing field {field} in {sorted(payload)}"
        assert payload[field] is None, f"{field}: expected null, got {payload[field]!r}"


# ---------------------------------------------------------------------------
# instants and dates
# ---------------------------------------------------------------------------


def parse_instant(value: str) -> datetime:
    assert isinstance(value, str), f"expected an ISO-8601 instant string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: Any, expected: str, field: str = "timestamp") -> None:
    """Compare two ISO-8601 instants regardless of sub-second width."""
    assert actual is not None, f"{field}: expected {expected}, got null"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{field}: expected instant {expected}, got {actual}"
    )


def assert_is_instant(value: Any, field: str = "timestamp") -> None:
    assert value is not None, f"{field}: expected an instant, got null"
    assert is_iso8601_timestamp(value), f"{field}: {value!r} is not ISO-8601"


def assert_calendar_date(value: Any, expected: str, field: str = "date") -> None:
    assert value == expected, f"{field}: expected {expected}, got {value!r}"


# ---------------------------------------------------------------------------
# common fields
# ---------------------------------------------------------------------------


def assert_common_fields(entity: Dict[str, Any], expected_version: int = None) -> None:
    """Every entity except JournalPosting carries id, created_at, updated_at, version."""
    assert is_valid_uuid(entity.get("id")), f"id is not a UUID: {entity.get('id')!r}"
    assert_is_instant(entity.get("created_at"), "created_at")
    assert_is_instant(entity.get("updated_at"), "updated_at")
    assert isinstance(entity.get("version"), int), (
        f"version must be an integer, got {entity.get('version')!r}"
    )
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"version: expected {expected_version}, got {entity['version']}"
        )


def assert_append_only_shape(posting: Dict[str, Any]) -> None:
    """A journal posting carries id and created_at but no updated_at and no version."""
    assert is_valid_uuid(posting.get("id")), f"id is not a UUID: {posting.get('id')!r}"
    assert_is_instant(posting.get("created_at"), "created_at")
    assert "updated_at" not in posting, "journal postings must not carry updated_at"
    assert "version" not in posting, "journal postings must not carry version"


# ---------------------------------------------------------------------------
# collections
# ---------------------------------------------------------------------------


def ids_of(rows: List[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


def assert_ids_equal(rows: List[Dict[str, Any]], expected_ids: List[str]) -> None:
    assert ids_of(rows) == list(expected_ids), (
        f"expected ids {list(expected_ids)}, got {ids_of(rows)}"
    )


def assert_id_set(rows: List[Dict[str, Any]], expected_ids: Iterable[str]) -> None:
    assert set(ids_of(rows)) == set(expected_ids), (
        f"expected id set {sorted(set(expected_ids))}, got {sorted(set(ids_of(rows)))}"
    )


def assert_empty(rows: List[Any], what: str = "list") -> None:
    assert rows == [], f"expected an empty {what}, got {rows}"


def assert_row_count(rows: List[Any], expected: int, what: str = "list") -> None:
    assert len(rows) == expected, (
        f"expected {expected} rows in the {what}, got {len(rows)}: {rows}"
    )


def assert_created_at_ascending(rows: List[Dict[str, Any]]) -> None:
    stamps = [parse_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), "rows are not ordered by created_at ascending"


def single(rows: List[Dict[str, Any]], what: str = "row") -> Dict[str, Any]:
    assert len(rows) == 1, f"expected exactly one {what}, got {len(rows)}: {rows}"
    return rows[0]


def find_by(rows: List[Dict[str, Any]], **criteria: Any) -> List[Dict[str, Any]]:
    return [
        row for row in rows if all(row.get(k) == v for k, v in criteria.items())
    ]


def sum_amounts(rows: List[Dict[str, Any]], field: str = "amount") -> Decimal:
    total = Decimal("0.00")
    for row in rows:
        total += to_decimal(row[field])
    return total.quantize(Decimal("0.01"))


def assert_sum_equals(rows: List[Dict[str, Any]], expected: float, field: str = "amount") -> None:
    got = sum_amounts(rows, field)
    want = Decimal(str(expected)).quantize(Decimal("0.01"))
    assert got == want, f"sum of {field}: expected {want}, got {got}"


# ---------------------------------------------------------------------------
# pagination metadata
# ---------------------------------------------------------------------------


def assert_page_meta(
    meta: Dict[str, Any],
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> None:
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
        assert meta["offset"] == offset, f"offset: expected {offset}, got {meta['offset']}"
