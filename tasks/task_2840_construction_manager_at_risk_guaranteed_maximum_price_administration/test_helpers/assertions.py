"""Domain assertions for the CMAR guaranteed-maximum-price administration API.

Money arrives as a JSON number with two decimals, ratios with four, and instants
as ISO 8601 UTC strings. The helpers below normalise whatever concrete JSON form
a value arrives in before comparing, so a test failure always means the value was
wrong rather than that it was spelled differently.
"""

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    CONSTRAINED_POSTURE_PCT,
    MONEY_PRECISION,
    RATIO_PRECISION,
)
from .types import JsonArray, JsonObject, Numeric, PageMeta

MONEY_QUANT = Decimal("0.01")
RATIO_QUANT = Decimal("0.0001")


# --- normalisation ---------------------------------------------------------


def to_decimal(value: Numeric, field: str = "value") -> Decimal:
    """Coerce a JSON numeric (int, float, string or Decimal) to a ``Decimal``."""
    assert value is not None, f"{field} is null but a number was expected"
    assert not isinstance(value, bool), f"{field} is a boolean, not a number"
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):  # pragma: no cover - diagnostic path
        raise AssertionError(f"{field} is not a number: {value!r}")


def round_money(value: Numeric) -> Decimal:
    """Round to two decimals, half away from zero, as the money rule requires."""
    return to_decimal(value).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def round_ratio(value: Numeric) -> Decimal:
    """Round to four decimals, half away from zero, as the ratio rule requires."""
    return to_decimal(value).quantize(RATIO_QUANT, rounding=ROUND_HALF_UP)


def parse_instant(value: Any, field: str = "timestamp") -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating any fractional-second width."""
    assert isinstance(value, str), f"{field} must be an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:  # pragma: no cover - diagnostic path
        raise AssertionError(f"{field} is not an ISO 8601 instant: {value!r}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# --- scalar assertions -----------------------------------------------------


def assert_money(actual: Numeric, expected: Numeric, field: str = "money field") -> None:
    """Assert a money field equals ``expected`` when both are read as decimals."""
    actual_dec = to_decimal(actual, field)
    expected_dec = to_decimal(expected, field)
    assert actual_dec == expected_dec, (
        f"{field}: expected {expected_dec}, got {actual_dec}"
    )
    assert -actual_dec.as_tuple().exponent <= MONEY_PRECISION, (
        f"{field} carries more than two decimal places: {actual_dec}"
    )


def assert_ratio(actual: Numeric, expected: Numeric, field: str = "ratio field") -> None:
    """Assert a ratio field equals ``expected`` at four decimal places."""
    actual_dec = to_decimal(actual, field)
    expected_dec = to_decimal(expected, field)
    assert actual_dec == expected_dec, (
        f"{field}: expected {expected_dec}, got {actual_dec}"
    )
    assert -actual_dec.as_tuple().exponent <= RATIO_PRECISION, (
        f"{field} carries more than four decimal places: {actual_dec}"
    )


def assert_decimal_places(value: Numeric, places: int, field: str = "field") -> None:
    """Assert a numeric value carries at most ``places`` decimal places."""
    exponent = -to_decimal(value, field).as_tuple().exponent
    assert exponent <= places, (
        f"{field} carries {exponent} decimal places, at most {places} allowed: {value}"
    )


def assert_instant(actual: Any, expected: str, field: str = "timestamp") -> None:
    """Assert an instant field denotes the same moment as ``expected``."""
    assert parse_instant(actual, field) == parse_instant(expected, field), (
        f"{field}: expected {expected}, got {actual}"
    )


def assert_instant_format(value: Any, field: str = "timestamp") -> None:
    """Assert a value is a well-formed ISO 8601 UTC instant."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{field} is not ISO 8601 UTC: {value!r}"


def assert_uuid(value: Any, field: str = "id") -> None:
    """Assert a value is a UUID string."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert is_valid_uuid(value), f"{field} is not a UUID: {value!r}"


def assert_null(row: Mapping[str, Any], *fields: str) -> None:
    """Assert each named field is present on the row and null."""
    for field in fields:
        assert field in row, f"expected field {field} to be present on the response"
        assert row[field] is None, f"expected {field} to be null, got {row[field]!r}"


def assert_equals(row: Mapping[str, Any], field: str, expected: Any) -> None:
    """Assert a plain (non-numeric) field equals ``expected``."""
    assert field in row, f"expected field {field} to be present on the response"
    assert row[field] == expected, (
        f"{field}: expected {expected!r}, got {row[field]!r}"
    )


# --- row-shape assertions --------------------------------------------------


def assert_system_fields(row: Mapping[str, Any], expected_version: Optional[int] = None) -> None:
    """Assert the four fields every stored row carries."""
    assert_uuid(row.get("id"), "id")
    assert_instant_format(row.get("created_at"), "created_at")
    assert_instant_format(row.get("updated_at"), "updated_at")
    version = row.get("version")
    assert isinstance(version, int) and not isinstance(version, bool), (
        f"version must be an integer, got {version!r}"
    )
    assert version >= 1, f"version must start at 1, got {version}"
    if expected_version is not None:
        assert version == expected_version, (
            f"version: expected {expected_version}, got {version}"
        )


def assert_version(row: Mapping[str, Any], expected: int) -> None:
    """Assert the row's optimistic-concurrency counter reads ``expected``."""
    assert row.get("version") == expected, (
        f"version: expected {expected}, got {row.get('version')}"
    )


def assert_money_fields(row: Mapping[str, Any], expected: Mapping[str, Numeric]) -> None:
    """Assert several money fields on one row in a single call."""
    for field, value in expected.items():
        assert field in row, f"expected money field {field} to be present"
        assert_money(row[field], value, field)


def assert_all_zero_money(row: Mapping[str, Any], fields: Iterable[str]) -> None:
    """Assert each named money field reads 0.00."""
    for field in fields:
        assert field in row, f"expected money field {field} to be present"
        assert_money(row[field], Decimal("0.00"), field)


def assert_fields(row: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    """Assert several plain fields on one row in a single call."""
    for field, value in expected.items():
        assert_equals(row, field, value)


# --- pagination ------------------------------------------------------------


def assert_page_meta(
    meta: PageMeta,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> None:
    """Assert the pagination block of a list response."""
    for key in ("total_count", "has_more", "limit", "offset"):
        assert key in meta, f"pagination meta is missing {key}"
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"total_count: expected {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"has_more: expected {has_more}, got {meta['has_more']!r}"
        )
    if limit is not None:
        assert meta["limit"] == limit, f"limit: expected {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, (
            f"offset: expected {offset}, got {meta['offset']}"
        )


def assert_ordered_by_created_at(rows: Sequence[Mapping[str, Any]]) -> None:
    """Assert a list response is ordered by creation instant, ascending."""
    instants = [parse_instant(row["created_at"], "created_at") for row in rows]
    assert instants == sorted(instants), (
        "list results are not ordered by creation timestamp ascending"
    )


def ids_of(rows: Iterable[Mapping[str, Any]]) -> list:
    """The ``id`` of each row, in order."""
    return [row["id"] for row in rows]


# --- project-level invariants ---------------------------------------------


GMP_IDENTITY_TERMS = (
    "cost_of_work_budget_total",
    "general_conditions_total",
    "insurance_amount",
    "cm_fee_amount",
    "owner_contingency_remaining",
    "construction_contingency_remaining",
    "contingency_drawn_to_cost_total",
)


def assert_gmp_identity(project: Mapping[str, Any]) -> None:
    """Assert the seven stored terms still sum to the guaranteed maximum price."""
    total = sum(
        (to_decimal(project[field], field) for field in GMP_IDENTITY_TERMS),
        Decimal("0.00"),
    )
    assert_money(project["gmp_amount"], total, "gmp_amount (seven-term identity)")


def assert_project_axes(
    project: Mapping[str, Any],
    gmp_status: Optional[str] = None,
    contingency_posture: Optional[str] = None,
    audit_status: Optional[str] = None,
    closeout_status: Optional[str] = None,
) -> None:
    """Assert any subset of the four independent project state axes."""
    expected = {
        "gmp_status": gmp_status,
        "contingency_posture": contingency_posture,
        "audit_status": audit_status,
        "closeout_status": closeout_status,
    }
    for field, value in expected.items():
        if value is not None:
            assert_equals(project, field, value)


def remaining_contingency_pct(project: Mapping[str, Any]) -> Decimal:
    """The remaining construction-contingency percentage, rounded to four decimals."""
    original = to_decimal(
        project["construction_contingency_original"], "construction_contingency_original"
    )
    if original == Decimal("0.00"):
        return Decimal("0.0000")
    remaining = to_decimal(
        project["construction_contingency_remaining"],
        "construction_contingency_remaining",
    )
    return round_ratio(remaining / original)


def assert_posture_matches_remaining(project: Mapping[str, Any]) -> None:
    """Assert the posture agrees with the remaining construction-contingency ratio."""
    if project["closeout_status"] == "SETTLEMENT_EXECUTED":
        assert_equals(project, "contingency_posture", "FROZEN")
        return
    pct = remaining_contingency_pct(project)
    expected = "CONSTRAINED" if pct <= CONSTRAINED_POSTURE_PCT else "OPEN"
    assert project["contingency_posture"] == expected, (
        f"contingency_posture: remaining ratio {pct} implies {expected}, "
        f"got {project['contingency_posture']}"
    )


# --- allowance ledger -----------------------------------------------------


def assert_allowance_ledger_invariant(item: Mapping[str, Any]) -> None:
    """Assert allocated units still equal remaining units plus reconciled units."""
    allocated = to_decimal(item["allocated_units"], "allocated_units")
    remaining = to_decimal(item["remaining_units"], "remaining_units")
    reconciled = to_decimal(item["reconciled_units"], "reconciled_units")
    assert allocated == remaining + reconciled, (
        f"allocated_units {allocated} != remaining_units {remaining} "
        f"+ reconciled_units {reconciled}"
    )


# --- cost report ----------------------------------------------------------


def assert_cost_report_totals(report: Mapping[str, Any]) -> None:
    """Assert the reported total is the sum of the undisputed and disputed totals."""
    reported = to_decimal(report["reported_cost_total"], "reported_cost_total")
    undisputed = to_decimal(report["undisputed_cost_total"], "undisputed_cost_total")
    disputed = to_decimal(report["disputed_cost_total"], "disputed_cost_total")
    assert reported == undisputed + disputed, (
        f"reported_cost_total {reported} != undisputed {undisputed} "
        f"+ disputed {disputed}"
    )


def line_by_seq(report: Mapping[str, Any], line_seq: int) -> JsonObject:
    """The stored cost line at ``line_seq`` on a cost report representation."""
    lines = report.get("lines")
    assert isinstance(lines, list), "cost report response has no lines array"
    matches = [line for line in lines if line.get("line_seq") == line_seq]
    assert len(matches) == 1, (
        f"expected exactly one line at line_seq {line_seq}, found {len(matches)}"
    )
    return matches[0]


def row_by_id(rows: JsonArray, row_id: str) -> JsonObject:
    """The single row in a list response carrying ``row_id``."""
    matches = [row for row in rows if row.get("id") == row_id]
    assert len(matches) == 1, (
        f"expected exactly one row with id {row_id}, found {len(matches)}"
    )
    return matches[0]


def rows_by_field(rows: JsonArray, field: str, value: Any) -> JsonArray:
    """Every row in a list response whose ``field`` equals ``value``."""
    return [row for row in rows if row.get(field) == value]


def single_row(rows: JsonArray, field: str, value: Any) -> JsonObject:
    """The single row in a list response whose ``field`` equals ``value``."""
    matches = rows_by_field(rows, field, value)
    assert len(matches) == 1, (
        f"expected exactly one row with {field} == {value!r}, found {len(matches)}"
    )
    return matches[0]


def assert_unchanged(
    before: Mapping[str, Any], after: Mapping[str, Any], *fields: str
) -> None:
    """Assert the named fields hold the same value in two reads of a row."""
    for field in fields:
        assert before.get(field) == after.get(field), (
            f"{field} changed from {before.get(field)!r} to {after.get(field)!r} "
            f"when it should have been left alone"
        )


def snapshot(row: Mapping[str, Any], fields: Iterable[str]) -> Dict[str, Any]:
    """Copy the named fields out of a row so they can be compared after a refusal."""
    return {field: row.get(field) for field in fields}
