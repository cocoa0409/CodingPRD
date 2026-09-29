"""Domain assertion helpers.

Numeric comparisons go through ``pytest.approx`` because the PRD carries barrel
figures to three decimal places and ounce figures to two, and a JSON float
round-trip is not bit-exact. Timestamp comparisons canonicalise sub-second
precision first: PRD §2.2 fixes only the ``meta`` timestamp's three fractional
digits, so a resource instant may legitimately come back with or without a
fractional part and must never be compared as a raw string.
"""

import re
from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    OZ_PER_BBL,
    OZ_PER_GAL,
)

BBL_TOL = 0.0005
OZ_TOL = 0.005

_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?"
    r"(Z|[+-]\d{2}:?\d{2})?$"
)


def canonical_instant(value: str) -> str:
    """Reduce an ISO-8601 instant to ``YYYY-MM-DDTHH:MM:SSZ``.

    Trailing zero fractional seconds and an explicit ``+00:00`` offset are
    dropped so that ``2026-08-01T00:00:00.000Z``, ``2026-08-01T00:00:00Z`` and
    ``2026-08-01T00:00:00+00:00`` all compare equal. A non-zero fractional part
    is preserved, trimmed of its trailing zeros.
    """
    assert isinstance(value, str), f"expected an ISO-8601 instant string, got {value!r}"
    match = _TS_RE.match(value.strip())
    assert match, f"not an ISO-8601 instant: {value!r}"
    y, mo, d, h, mi, s, frac, _off = match.groups()
    stem = f"{y}-{mo}-{d}T{h}:{mi}:{s}"
    if frac:
        frac = frac.rstrip("0")
        if frac:
            return f"{stem}.{frac}Z"
    return f"{stem}Z"


def assert_instant_equals(actual: Any, expected: str, label: str = "instant") -> None:
    """Compare two ISO-8601 instants ignoring sub-second formatting."""
    assert actual is not None, f"{label} is null, expected {expected}"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_bbl(actual: Any, expected: float, label: str = "barrels") -> None:
    """Compare a three-decimal barrel figure."""
    assert actual is not None, f"{label} is null, expected {expected}"
    assert isinstance(actual, (int, float)), f"{label} must be numeric, got {actual!r}"
    assert actual == pytest.approx(expected, abs=BBL_TOL), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_oz(actual: Any, expected: float, label: str = "ounces") -> None:
    """Compare a two-decimal fluid-ounce figure."""
    assert actual is not None, f"{label} is null, expected {expected}"
    assert isinstance(actual, (int, float)), f"{label} must be numeric, got {actual!r}"
    assert actual == pytest.approx(expected, abs=OZ_TOL), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_cents(actual: Any, expected: int, label: str = "cents") -> None:
    """Cents are whole integers (§2.6), so this comparison is exact."""
    assert actual == expected, f"{label}: expected {expected}, got {actual}"
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be a whole integer, got {actual!r}"
    )


def assert_common_fields(resource: Dict[str, Any], expected_version: Optional[int] = None):
    """Assert the mutable-resource common fields of §2.4."""
    assert is_valid_uuid(resource["id"]), f"id must be a UUID: {resource['id']!r}"
    assert is_iso8601_timestamp(resource["created_at"])
    assert is_iso8601_timestamp(resource["updated_at"])
    assert isinstance(resource["version"], int)
    assert resource["version"] >= 1
    if expected_version is not None:
        assert resource["version"] == expected_version, (
            f"version: expected {expected_version}, got {resource['version']}"
        )


def assert_pour_shape(pour: Dict[str, Any]) -> None:
    """A pour carries id and created_at only — no updated_at, no version (§2.4)."""
    assert is_valid_uuid(pour["id"]), f"id must be a UUID: {pour['id']!r}"
    assert is_iso8601_timestamp(pour["created_at"])
    assert "updated_at" not in pour, "a taproom pour must not carry updated_at"
    assert "version" not in pour, "a taproom pour must not carry version"


def assert_no_prefix_uuid(value: str) -> None:
    """§2.4: the identifier is a UUID string with no prefix of any kind."""
    assert is_valid_uuid(value), f"expected a bare UUID, got {value!r}"


def assert_pagination_meta(
    meta: Dict[str, Any],
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> None:
    """Assert the four list-response meta fields of §2.3."""
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta, f"list meta must carry {key}"
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"total_count: expected {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"has_more: expected {has_more}, got {meta['has_more']}"
        )
    if limit is not None:
        assert meta["limit"] == limit
    if offset is not None:
        assert meta["offset"] == offset


def assert_ledger_conserved(run: Dict[str, Any]) -> None:
    """§3.3: bbl_removed equals available + allocated + shipped."""
    total = run["available_bbl"] + run["allocated_bbl"] + run["shipped_bbl"]
    assert run["bbl_removed"] == pytest.approx(total, abs=BBL_TOL), (
        "run ledger not conserved: bbl_removed="
        f"{run['bbl_removed']} vs available+allocated+shipped={total}"
    )


def assert_batch_conserved(batch: Dict[str, Any]) -> None:
    """§3.3: actual_yield_bbl equals packaged_bbl plus remaining_bbl."""
    assert batch["actual_yield_bbl"] is not None, "batch has no measured yield yet"
    total = batch["packaged_bbl"] + batch["remaining_bbl"]
    assert batch["actual_yield_bbl"] == pytest.approx(total, abs=BBL_TOL), (
        f"batch identity broken: actual_yield_bbl={batch['actual_yield_bbl']} "
        f"vs packaged+remaining={total}"
    )


def assert_allocation_lines(
    lines: List[Dict[str, Any]], expected: List[tuple]
) -> None:
    """Assert allocation_lines in draw-down order (§3.7).

    ``expected`` is a list of ``(packaging_run_id, bbl)`` pairs in the order the
    waterfall must have produced them.
    """
    assert len(lines) == len(expected), (
        f"expected {len(expected)} allocation lines, got {len(lines)}: {lines}"
    )
    for index, (line, (run_id, bbl)) in enumerate(zip(lines, expected)):
        assert line["packaging_run_id"] == run_id, (
            f"allocation line {index}: expected run {run_id}, "
            f"got {line['packaging_run_id']}"
        )
        assert line["bbl"] == pytest.approx(bbl, abs=BBL_TOL), (
            f"allocation line {index}: expected {bbl} bbl, got {line['bbl']}"
        )


def oz_to_bbl(ounces: float) -> float:
    """Convert fluid ounces to barrels at the §2.6 rate."""
    return ounces / OZ_PER_BBL


def gal_to_oz(gallons: float) -> float:
    """Convert US gallons to fluid ounces at the §2.6 rate."""
    return gallons * OZ_PER_GAL


def assert_decimal_places(value: Any, places: int, label: str = "value") -> None:
    """Assert a numeric response field carries no more than ``places`` decimals."""
    text = f"{float(value):.10f}".rstrip("0")
    fractional = text.split(".")[1] if "." in text else ""
    assert len(fractional) <= places, (
        f"{label}: {value} carries more than {places} decimal places"
    )
