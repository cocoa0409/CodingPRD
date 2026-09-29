"""Domain assertion helpers.

These wrap the framework validators with the contract's own rounding rules:
deductions, sub-scores, rates and lead hours carry two decimals, the two
inspection scores carry one, and money is an integer count of cents.
"""

from typing import Any, Dict, Optional, Sequence

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from .api_client import canonicalize_instant
from .api_errors import HTTP_STATUS_CODES

# Tolerances: a two-decimal figure and a one-decimal figure are each compared
# well inside half of their least significant digit.
TWO_DECIMAL_TOLERANCE = 0.0005
ONE_DECIMAL_TOLERANCE = 0.005


# ---------------------------------------------------------------------------
# Numeric comparisons
# ---------------------------------------------------------------------------
def assert_two_decimals(actual: Any, expected: float, label: str = "value") -> None:
    """Assert a two-decimal figure, which must arrive as a JSON number."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        "{0} must be a JSON number, got {1!r}".format(label, actual)
    )
    assert actual == pytest.approx(expected, abs=TWO_DECIMAL_TOLERANCE), (
        "{0}: expected {1}, got {2}".format(label, expected, actual)
    )


def assert_one_decimal(actual: Any, expected: float, label: str = "score") -> None:
    """Assert a one-decimal figure such as provisional_score or final_score."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        "{0} must be a JSON number, got {1!r}".format(label, actual)
    )
    assert actual == pytest.approx(expected, abs=ONE_DECIMAL_TOLERANCE), (
        "{0}: expected {1}, got {2}".format(label, expected, actual)
    )


def assert_points(actual: Any, expected: float) -> None:
    assert_two_decimals(actual, expected, "points_deducted")


def assert_cents(actual: Any, expected: int, label: str = "cents") -> None:
    """Assert an integer count of cents, emitted as a JSON number."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        "{0} must be an integer number of cents, got {1!r}".format(label, actual)
    )
    assert actual == expected, "{0}: expected {1}, got {2}".format(
        label, expected, actual
    )


def assert_integer(actual: Any, expected: int, label: str = "count") -> None:
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        "{0} must be an integer, got {1!r}".format(label, actual)
    )
    assert actual == expected, "{0}: expected {1}, got {2}".format(
        label, expected, actual
    )


# ---------------------------------------------------------------------------
# Instants
# ---------------------------------------------------------------------------
def assert_instant(actual: Any, expected: str, label: str = "timestamp") -> None:
    """Assert one ISO-8601 instant, compared at millisecond precision."""
    assert isinstance(actual, str), "{0} must be a string, got {1!r}".format(
        label, actual
    )
    assert canonicalize_instant(actual) == canonicalize_instant(expected), (
        "{0}: expected {1}, got {2}".format(label, expected, actual)
    )


def assert_instant_format(actual: Any, label: str = "timestamp") -> None:
    """Assert the value is an ISO-8601 UTC instant with three fractional digits."""
    assert isinstance(actual, str), "{0} must be a string, got {1!r}".format(
        label, actual
    )
    assert is_iso8601_timestamp(actual), "{0} is not ISO-8601: {1!r}".format(
        label, actual
    )
    assert actual.endswith("Z"), "{0} must be UTC: {1!r}".format(label, actual)
    assert len(actual) == len("2026-08-01T00:00:00.000Z"), (
        "{0} must carry exactly three fractional digits: {1!r}".format(label, actual)
    )


def assert_null(row: Dict[str, Any], *field_names: str) -> None:
    for field_name in field_names:
        assert field_name in row, "field {0} is absent".format(field_name)
        assert row[field_name] is None, "{0}: expected null, got {1!r}".format(
            field_name, row[field_name]
        )


def assert_fields(row: Dict[str, Any], **expected: Any) -> None:
    """Assert plain equality for a batch of scalar fields."""
    for field_name, value in expected.items():
        assert field_name in row, "field {0} is absent".format(field_name)
        assert row[field_name] == value, "{0}: expected {1!r}, got {2!r}".format(
            field_name, value, row[field_name]
        )


# ---------------------------------------------------------------------------
# Common fields carried by all twelve resource types
# ---------------------------------------------------------------------------
def assert_common_fields(row: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Assert id, created_at, updated_at and version are all present and sane."""
    assert is_valid_uuid(row.get("id")), "id must be a UUID, got {0!r}".format(
        row.get("id")
    )
    assert_instant_format(row.get("created_at"), "created_at")
    assert_instant_format(row.get("updated_at"), "updated_at")
    version = row.get("version")
    assert isinstance(version, int) and not isinstance(version, bool), (
        "version must be an integer, got {0!r}".format(version)
    )
    assert version >= 1, "version must start at 1, got {0}".format(version)
    if expected_version is not None:
        assert version == expected_version, "version: expected {0}, got {1}".format(
            expected_version, version
        )


def assert_version_bumped_by(row: Dict[str, Any], baseline: int, steps: int = 1) -> None:
    """Assert the row's version advanced by exactly `steps` from `baseline`."""
    assert row["version"] == baseline + steps, (
        "version: expected {0} (baseline {1} + {2}), got {3}".format(
            baseline + steps, baseline, steps, row["version"]
        )
    )


def assert_version_unchanged(row: Dict[str, Any], baseline: int) -> None:
    assert row["version"] == baseline, (
        "version must not have moved: expected {0}, got {1}".format(
            baseline, row["version"]
        )
    )


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------
def assert_error(response: Any, error_id: str) -> Dict[str, Any]:
    """Assert an error envelope carrying `error_id` and its catalogued status."""
    return validate_error(response, error_id, HTTP_STATUS_CODES.get(error_id))


def assert_created(response: Any) -> Dict[str, Any]:
    """Assert a 201 envelope and return its data object."""
    return validate_success(response, 201)


def assert_ok(response: Any) -> Dict[str, Any]:
    """Assert a 200 envelope and return its data object."""
    return validate_success(response, 200)


def assert_total_count(response: Any, expected_total: int) -> Sequence[Any]:
    """Assert a paginated envelope's total_count and return its rows."""
    rows, meta = validate_paginated(response)
    assert meta["total_count"] == expected_total, (
        "total_count: expected {0}, got {1}".format(expected_total, meta["total_count"])
    )
    return rows


def assert_pagination_meta(
    response: Any,
    expected_total: int,
    expected_limit: int,
    expected_offset: int,
    expected_has_more: bool,
) -> Sequence[Any]:
    rows, meta = validate_paginated(response)
    assert_integer(meta["total_count"], expected_total, "total_count")
    assert_integer(meta["limit"], expected_limit, "limit")
    assert_integer(meta["offset"], expected_offset, "offset")
    assert meta["has_more"] is expected_has_more, (
        "has_more: expected {0}, got {1!r}".format(expected_has_more, meta["has_more"])
    )
    return rows


# ---------------------------------------------------------------------------
# Domain-shaped composites
# ---------------------------------------------------------------------------
def assert_property_state(
    row: Dict[str, Any],
    readiness_posture: str,
    open_life_threatening_count: int,
    overdue_life_threatening_count: int,
    open_severe_count: int,
) -> None:
    """Assert the posture together with the three counters that derive it."""
    assert_fields(row, readiness_posture=readiness_posture)
    assert_integer(
        row["open_life_threatening_count"],
        open_life_threatening_count,
        "open_life_threatening_count",
    )
    assert_integer(
        row["overdue_life_threatening_count"],
        overdue_life_threatening_count,
        "overdue_life_threatening_count",
    )
    assert_integer(row["open_severe_count"], open_severe_count, "open_severe_count")


def assert_sweep_counters(
    row: Dict[str, Any],
    generated: int,
    verified: int,
    voided: int,
    urgent: int,
    closure_verified_rate: float,
) -> None:
    assert_integer(row["generated_work_order_count"], generated, "generated_work_order_count")
    assert_integer(row["verified_work_order_count"], verified, "verified_work_order_count")
    assert_integer(row["void_work_order_count"], voided, "void_work_order_count")
    assert_integer(row["urgent_work_order_count"], urgent, "urgent_work_order_count")
    assert_two_decimals(
        row["closure_verified_rate"], closure_verified_rate, "closure_verified_rate"
    )


def assert_work_order_dimensions(
    row: Dict[str, Any], repair_status: str, verification_status: str
) -> None:
    """Assert the two independent status dimensions of a work order."""
    assert_fields(
        row, repair_status=repair_status, verification_status=verification_status
    )


def assert_area_points(
    row: Dict[str, Any], unit_points: float, inside_points: float, outside_points: float
) -> None:
    assert_two_decimals(row["unit_area_points"], unit_points, "unit_area_points")
    assert_two_decimals(row["inside_area_points"], inside_points, "inside_area_points")
    assert_two_decimals(
        row["outside_area_points"], outside_points, "outside_area_points"
    )


def assert_scores(
    row: Dict[str, Any], provisional_score: float, final_score: float
) -> None:
    assert_one_decimal(row["provisional_score"], provisional_score, "provisional_score")
    assert_one_decimal(row["final_score"], final_score, "final_score")


def assert_allocation_sums_to(rows: Sequence[Dict[str, Any]], reserve_cents: int) -> None:
    """Assert the floor-plus-remainder walk conserves the whole reserve."""
    total = sum(row["allocated_reserve_cents"] for row in rows)
    assert total == reserve_cents, (
        "allocated cents must sum to the reserve exactly: expected {0}, got {1}".format(
            reserve_cents, total
        )
    )


def rows_by(rows: Sequence[Dict[str, Any]], field_name: str) -> Dict[Any, Dict[str, Any]]:
    """Index a list of rows by one of their fields."""
    return {row[field_name]: row for row in rows}
