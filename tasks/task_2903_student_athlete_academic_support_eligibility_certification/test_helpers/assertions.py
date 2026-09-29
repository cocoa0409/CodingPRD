"""Domain assertion helpers.

Envelope unwrapping happens exactly once, inside the framework validators; the
helpers below all operate on the already-unwrapped ``data`` payload so no
response is ever double-unwrapped.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, List, Optional, Sequence

import pytest
import requests

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from .api_client import canonical_instant
from .types import JsonArray, JsonObject

# Entities that carry all four common properties (PRD 2.4).
VERSIONED_ENTITIES = (
    "Term",
    "DegreeProgram",
    "Course",
    "DegreeApplicabilityRule",
    "StudentAthlete",
    "Enrollment",
    "EligibilityCertification",
    "Tutor",
    "TutorAssignment",
    "CompetitionEvent",
    "MissedClassRequest",
    "EligibilityAppeal",
    "ComplianceIncident",
)


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------
def round_half_up(value: float, places: int) -> float:
    """Round half up to ``places`` decimals, matching PRD 2.5 discipline."""
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def assert_close(actual: Any, expected: float, tolerance: float = 0.01) -> None:
    """Assert a numeric field equals ``expected`` within ``tolerance``."""
    assert isinstance(actual, (int, float)), f"Expected a number, got {actual!r}"
    assert actual == pytest.approx(expected, abs=tolerance), (
        f"Expected {expected}, got {actual}"
    )


def assert_decimal_places(value: Any, places: int) -> None:
    """Assert a stored numeric never carries more precision than declared."""
    assert isinstance(value, (int, float)), f"Expected a number, got {value!r}"
    rounded = round_half_up(float(value), places)
    assert float(value) == pytest.approx(rounded, abs=1e-9), (
        f"Value {value} carries more than {places} decimal places"
    )


def assert_whole_number(value: Any) -> None:
    """Assert a point counter holds a whole number (PRD 2.5)."""
    assert isinstance(value, (int, float)), f"Expected a number, got {value!r}"
    assert float(value) == float(int(value)), f"Expected a whole number, got {value}"


# ---------------------------------------------------------------------------
# Envelope / shape helpers
# ---------------------------------------------------------------------------
def created(response: requests.Response) -> JsonObject:
    """Validate a 201 creation response and return its ``data``."""
    return validate_success(response, 201)


def ok(response: requests.Response) -> JsonObject:
    """Validate a 200 response and return its ``data``."""
    return validate_success(response, 200)


def page(response: requests.Response) -> tuple:
    """Validate a list response and return ``(rows, meta)``."""
    return validate_paginated(response)


def error(
    response: requests.Response,
    expected_error_id: str,
    expected_status: Optional[int] = None,
) -> JsonObject:
    """Validate an error response against the catalogue."""
    return validate_error(response, expected_error_id, expected_status)


def assert_common_fields(row: JsonObject, expect_version: int = 1) -> None:
    """Assert the four common properties of a versioned entity (PRD 2.4)."""
    assert is_valid_uuid(row.get("id")), f"id must be a bare UUID, got {row.get('id')!r}"
    assert "_" not in str(row.get("id")), "id must carry no type prefix"
    assert is_iso8601_timestamp(row.get("created_at")), (
        f"created_at must be ISO-8601, got {row.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(row.get("updated_at")), (
        f"updated_at must be ISO-8601, got {row.get('updated_at')!r}"
    )
    assert row.get("version") == expect_version, (
        f"Expected version {expect_version}, got {row.get('version')}"
    )
    assert_three_fractional_digits(row["created_at"])
    assert_three_fractional_digits(row["updated_at"])


def assert_three_fractional_digits(instant: str) -> None:
    """Assert an instant is rendered with exactly three fractional digits."""
    assert isinstance(instant, str), f"Expected a string instant, got {instant!r}"
    assert instant.endswith("Z"), f"Instant must be UTC 'Z'-suffixed: {instant}"
    assert "." in instant, f"Instant must carry fractional digits: {instant}"
    fraction = instant[:-1].split(".", 1)[1]
    assert len(fraction) == 3, (
        f"Instant must carry exactly three fractional digits: {instant}"
    )


def assert_immutable_session_shape(session: JsonObject) -> None:
    """A logged session carries only ``id`` and ``created_at`` (PRD 2.4)."""
    assert is_valid_uuid(session.get("id")), "session id must be a bare UUID"
    assert is_iso8601_timestamp(session.get("created_at")), (
        "session created_at must be ISO-8601"
    )
    assert "updated_at" not in session, (
        "SupportSession must expose no updated_at key at all"
    )
    assert "version" not in session, (
        "SupportSession must expose no version key at all"
    )


def assert_field_absent(row: JsonObject, field: str) -> None:
    assert field not in row, f"Expected no '{field}' key, found {row.get(field)!r}"


def assert_instant_equals(actual: Any, expected: str) -> None:
    """Compare instants after canonicalising sub-second width."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"Expected instant {expected}, got {actual}"
    )


def assert_null(row: JsonObject, *fields: str) -> None:
    for field in fields:
        assert field in row, f"Expected key '{field}' to be present"
        assert row[field] is None, f"Expected {field} to be null, got {row[field]!r}"


def assert_version_is(row: JsonObject, expected: int) -> None:
    assert row.get("version") == expected, (
        f"Expected version {expected}, got {row.get('version')}"
    )


def assert_version_advanced(before: JsonObject, after: JsonObject, by: int = 1) -> None:
    assert after["version"] == before["version"] + by, (
        f"Expected version to advance by {by} from {before['version']}, "
        f"got {after['version']}"
    )


# ---------------------------------------------------------------------------
# Ordering / pagination helpers
# ---------------------------------------------------------------------------
def ids_of(rows: Sequence[JsonObject]) -> List[str]:
    return [row["id"] for row in rows]


def assert_ids_equal(rows: Sequence[JsonObject], expected_ids: Iterable[str]) -> None:
    assert ids_of(rows) == list(expected_ids), (
        f"Expected ids {list(expected_ids)}, got {ids_of(rows)}"
    )


def assert_page_meta(
    meta: JsonObject,
    limit: int,
    offset: int,
    total_count: int,
    has_more: bool,
) -> None:
    assert meta["limit"] == limit, f"Expected limit {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"Expected offset {offset}, got {meta['offset']}"
    assert meta["total_count"] == total_count, (
        f"Expected total_count {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"Expected has_more {has_more}, got {meta['has_more']}"
    )


def assert_non_decreasing(values: Sequence[Any], label: str = "values") -> None:
    for earlier, later in zip(values, values[1:]):
        assert earlier <= later, f"{label} not ascending: {values}"


# ---------------------------------------------------------------------------
# Conservation invariants (PRD 2.10)
# ---------------------------------------------------------------------------
def assert_missed_class_budget_conserved(student: JsonObject) -> None:
    """``allowance == charged + remaining`` on the student row."""
    allowance = student["missed_class_units_allowance"]
    charged = student["missed_class_units_charged"]
    remaining = student["missed_class_units_remaining"]
    assert charged + remaining == pytest.approx(allowance, abs=0.01), (
        f"missed-class budget broken: allowance {allowance} != charged "
        f"{charged} + remaining {remaining}"
    )


def assert_apr_ledger_conserved(student: JsonObject) -> None:
    """``apr_points_possible == apr_points_earned + apr_points_forfeited``."""
    possible = student["apr_points_possible"]
    earned = student["apr_points_earned"]
    forfeited = student["apr_points_forfeited"]
    assert earned + forfeited == possible, (
        f"APR ledger broken: possible {possible} != earned {earned} + "
        f"forfeited {forfeited}"
    )


def assert_tutor_capacity_conserved(
    tutor: JsonObject, assignments: Sequence[JsonObject]
) -> None:
    """``assigned_weekly_hours`` equals the ACTIVE assignments' hours sum."""
    active_sum = sum(
        a["weekly_hours"] for a in assignments if a.get("status") == "ACTIVE"
    )
    assert tutor["assigned_weekly_hours"] == pytest.approx(active_sum, abs=0.01), (
        f"tutor capacity broken: assigned_weekly_hours "
        f"{tutor['assigned_weekly_hours']} != sum over ACTIVE assignments "
        f"{active_sum}"
    )
    assert tutor["assigned_weekly_hours"] >= 0, "capacity is never negative"


def assert_all_conserved(
    student: JsonObject,
    tutor: Optional[JsonObject] = None,
    assignments: Optional[Sequence[JsonObject]] = None,
) -> None:
    """Check every ledger identity that applies to the rows supplied."""
    assert_missed_class_budget_conserved(student)
    assert_apr_ledger_conserved(student)
    if tutor is not None and assignments is not None:
        assert_tutor_capacity_conserved(tutor, assignments)


# ---------------------------------------------------------------------------
# Domain-shaped assertions
# ---------------------------------------------------------------------------
def assert_benchmark(
    row: JsonObject,
    result: str,
    failure_reasons: Optional[List[str]] = None,
) -> None:
    """Assert ``benchmark_result`` and the ordered ``failure_reasons`` list."""
    assert row["benchmark_result"] == result, (
        f"Expected benchmark_result {result}, got {row['benchmark_result']}"
    )
    expected_reasons = failure_reasons if failure_reasons is not None else []
    assert row["failure_reasons"] == expected_reasons, (
        f"Expected failure_reasons {expected_reasons}, got {row['failure_reasons']}"
    )


def assert_risk(row: JsonObject, score: float, tier: str) -> None:
    assert_close(row["risk_score"], score)
    assert row["risk_tier"] == tier, (
        f"Expected risk_tier {tier} for score {row['risk_score']}, "
        f"got {row['risk_tier']}"
    )


def assert_student_dimensions(
    student: JsonObject,
    eligibility_state: Optional[str] = None,
    support_status: Optional[str] = None,
) -> None:
    """Assert the two independent state dimensions of a student row."""
    if eligibility_state is not None:
        assert student["eligibility_state"] == eligibility_state, (
            f"Expected eligibility_state {eligibility_state}, "
            f"got {student['eligibility_state']}"
        )
    if support_status is not None:
        assert student["support_status"] == support_status, (
            f"Expected support_status {support_status}, "
            f"got {student['support_status']}"
        )


def assert_status(row: JsonObject, expected: str, field: str = "status") -> None:
    assert row[field] == expected, (
        f"Expected {field} {expected}, got {row[field]}"
    )
