"""Domain assertion helpers.

These wrap the repeated shape checks so individual tests can concentrate on the
behaviour they are pinning. They never soften an expectation: every helper
either asserts exactly what the PRD states or takes the expected value from its
caller.
"""

from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant

PCT_TOLERANCE = 0.01


# --- Common resource properties (PRD 2.5) ---------------------------------


def assert_common_fields(row: Dict[str, Any], expected_version: Optional[int] = None):
    """Every persisted resource carries `id`, `created_at`, `updated_at`, and
    `version`; no entity is exempt."""
    assert is_valid_uuid(row["id"]), f"id must be a server-minted UUID, got {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), (
        f"created_at must be an ISO 8601 UTC timestamp, got {row['created_at']!r}"
    )
    assert is_iso8601_timestamp(row["updated_at"]), (
        f"updated_at must be an ISO 8601 UTC timestamp, got {row['updated_at']!r}"
    )
    assert isinstance(row["version"], int), "version must be an integer"
    assert row["version"] >= 1, "version starts at 1 and increments on every mutation"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"expected version {expected_version}, got {row['version']}"
        )


def assert_three_fractional_digits(value: str):
    """PRD 2.5 declares timestamps as ISO 8601 with three fractional digits."""
    assert isinstance(value, str) and value.endswith("Z"), (
        f"instant must end in Z, got {value!r}"
    )
    assert "." in value, f"instant must carry fractional digits, got {value!r}"
    frac = value.split(".", 1)[1][:-1]
    assert len(frac) == 3, f"instant must carry three fractional digits, got {value!r}"


def assert_instant_equals(actual: Optional[str], expected: Optional[str], label: str = ""):
    """Compare two instants irrespective of fractional-second width."""
    prefix = f"{label}: " if label else ""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{prefix}expected instant {expected!r}, got {actual!r}"
    )


def assert_fields(row: Dict[str, Any], **expected: Any):
    """Assert an exact value for each named field, reporting all mismatches."""
    mismatches = []
    for field, value in expected.items():
        assert field in row, f"response is missing field {field!r}"
        actual = row[field]
        if isinstance(value, float) or isinstance(actual, float):
            if actual != pytest.approx(value, abs=PCT_TOLERANCE):
                mismatches.append(f"{field}: expected {value!r}, got {actual!r}")
        elif actual != value:
            mismatches.append(f"{field}: expected {value!r}, got {actual!r}")
    assert not mismatches, "; ".join(mismatches)


def assert_nulls(row: Dict[str, Any], *fields: str):
    """Assert that each named field is present and null."""
    for field in fields:
        assert field in row, f"response is missing field {field!r}"
        assert row[field] is None, f"{field} must be null, got {row[field]!r}"


# --- Pagination and list shapes (PRD 2.3) --------------------------------


def assert_pagination_meta(
    meta: Dict[str, Any],
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
):
    """List responses carry `limit`, `offset`, `total_count`, and `has_more`
    inside the `meta` object of the envelope."""
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta, f"list meta must carry {key!r}"
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"expected total_count {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"expected has_more {has_more}, got {meta['has_more']}"
        )
    if limit is not None:
        assert meta["limit"] == limit, f"expected limit {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"expected offset {offset}, got {meta['offset']}"


def assert_created_at_ascending(rows: List[Dict[str, Any]]):
    """Every list endpoint returns its rows sorted by `created_at` ascending."""
    stamps = [canonical_instant(r["created_at"]) for r in rows]
    assert stamps == sorted(stamps), f"rows are not in ascending created_at order: {stamps}"


def assert_ids_equal(rows: List[Dict[str, Any]], expected_ids: List[str]):
    """Assert the returned rows are exactly these ids, in this order."""
    actual = [r["id"] for r in rows]
    assert actual == expected_ids, f"expected ids {expected_ids}, got {actual}"


def ids_of(rows: List[Dict[str, Any]]) -> List[str]:
    return [r["id"] for r in rows]


def find_row(rows: List[Dict[str, Any]], row_id: str) -> Dict[str, Any]:
    """Return the row with this id, failing loudly when it is absent."""
    for row in rows:
        if row["id"] == row_id:
            return row
    raise AssertionError(f"id {row_id!r} not present among {ids_of(rows)}")


# --- Numeric precision (PRD 2.8) ----------------------------------------


def assert_cents(actual: Any, expected: int, label: str = "amount"):
    """All money is expressed in whole US cents as integers."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_pct(actual: Any, expected: float, label: str = "percentage"):
    """Percentages are real numbers rounded half up to a fixed decimal place."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be numeric, got {actual!r}"
    )
    assert actual == pytest.approx(expected, abs=PCT_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_one_decimal_place(actual: float, label: str = "percentage"):
    """A value stored to one decimal place never carries a second."""
    assert round(float(actual), 1) == pytest.approx(float(actual), abs=1e-9), (
        f"{label} must be stored to one decimal place, got {actual!r}"
    )


# --- Site derived counters (PRD 3.8) ------------------------------------


def assert_site_capacity_counters(
    site: Dict[str, Any],
    busy_talkpaths: Optional[int] = None,
    peak_talkpaths: Optional[int] = None,
    granted_request_count: Optional[int] = None,
    busied_request_count: Optional[int] = None,
    grade_of_service_pct: Optional[float] = None,
):
    """Assert the four grade-of-service counters and the statistic itself."""
    if busy_talkpaths is not None:
        assert site["busy_talkpaths"] == busy_talkpaths, (
            f"expected busy_talkpaths {busy_talkpaths}, got {site['busy_talkpaths']}"
        )
    if peak_talkpaths is not None:
        assert site["peak_talkpaths"] == peak_talkpaths, (
            f"expected peak_talkpaths {peak_talkpaths}, got {site['peak_talkpaths']}"
        )
    if granted_request_count is not None:
        assert site["granted_request_count"] == granted_request_count, (
            f"expected granted_request_count {granted_request_count}, "
            f"got {site['granted_request_count']}"
        )
    if busied_request_count is not None:
        assert site["busied_request_count"] == busied_request_count, (
            f"expected busied_request_count {busied_request_count}, "
            f"got {site['busied_request_count']}"
        )
    if grade_of_service_pct is not None:
        assert_pct(
            site["grade_of_service_pct"], grade_of_service_pct, "grade_of_service_pct"
        )


def assert_coverage_result(
    site: Dict[str, Any],
    coverage_reliability_pct: float,
    coverage_derate_tier: str,
    coverage_class: str,
):
    """Assert the three derived coverage fields recomputed in one pinned pass."""
    assert_pct(
        site["coverage_reliability_pct"],
        coverage_reliability_pct,
        "coverage_reliability_pct",
    )
    assert site["coverage_derate_tier"] == coverage_derate_tier, (
        f"expected coverage_derate_tier {coverage_derate_tier}, "
        f"got {site['coverage_derate_tier']}"
    )
    assert site["coverage_class"] == coverage_class, (
        f"expected coverage_class {coverage_class}, got {site['coverage_class']}"
    )


# --- Cross-dimension guards (PRD 3.4) -----------------------------------


def assert_unit_dimensions(
    unit: Dict[str, Any], provision_status: str, key_status: str
):
    """A subscriber unit carries two state machines on one row, and they never
    touch each other; assert both dimensions together."""
    assert unit["provision_status"] == provision_status, (
        f"expected provision_status {provision_status}, got {unit['provision_status']}"
    )
    assert unit["key_status"] == key_status, (
        f"expected key_status {key_status}, got {unit['key_status']}"
    )


def assert_version_advanced(before: Dict[str, Any], after: Dict[str, Any], by: int = 1):
    """Assert a row's mutation counter advanced by exactly `by`."""
    assert after["version"] == before["version"] + by, (
        f"expected version {before['version'] + by}, got {after['version']}"
    )


def assert_unchanged(before: Dict[str, Any], after: Dict[str, Any], *fields: str):
    """Assert each named field survived an operation exactly as it was."""
    for field in fields:
        assert after[field] == before[field], (
            f"{field} must be left exactly as it was: was {before[field]!r}, "
            f"now {after[field]!r}"
        )
