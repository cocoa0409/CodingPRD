"""Domain assertions for the Student Data Privacy Vendor Vetting API.

These wrap the recurring checks so tests read as statements about the domain:
two-decimal score comparison that tolerates no drift, instant comparison that
ignores incidental fractional-digit width, and the PRD §2.4 common-field
contract.
"""

from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant, parse_instant

# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------


def assert_decimal_equals(actual: Any, expected: str, label: str = "value") -> None:
    """Assert a two-decimal score equals ``expected`` exactly.

    ``expected`` is written as a string such as ``"60.67"`` so the intended
    value cannot be perturbed by binary floating point in the test itself.
    The response value must be a JSON number, not a string.
    """
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be a JSON number, got {type(actual).__name__}: {actual!r}"
    )
    got = Decimal(str(actual))
    want = Decimal(expected)
    assert got == want, f"{label}: expected {want}, got {got}"


def assert_two_decimal_scale(actual: Any, label: str = "value") -> None:
    """Assert a number carries no more than two decimal places (PRD §2.8)."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be a JSON number, got {type(actual).__name__}: {actual!r}"
    )
    exponent = Decimal(str(actual)).normalize().as_tuple().exponent
    assert isinstance(exponent, int) and exponent >= -2, (
        f"{label} must be rounded to at most two decimals, got {actual!r}"
    )


def assert_integer_equals(actual: Any, expected: int, label: str = "counter") -> None:
    """Assert an integer counter equals ``expected`` and is a JSON integer."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be a JSON integer, got {type(actual).__name__}: {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


# ---------------------------------------------------------------------------
# Instants
# ---------------------------------------------------------------------------


def assert_instant_equals(actual: Any, expected: str, label: str = "instant") -> None:
    """Assert two ISO-8601 instants denote the same moment.

    Comparison is on the instant, not on the raw string, so a fixture literal
    written as ``2026-08-01T00:00:00Z`` matches a stored rendering of
    ``2026-08-01T00:00:00.000Z``.
    """
    assert isinstance(actual, str), (
        f"{label} must be an ISO-8601 string, got {type(actual).__name__}: {actual!r}"
    )
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {canonical_instant(expected)}, "
        f"got {canonical_instant(actual)}"
    )


def assert_three_fraction_digits(actual: Any, label: str = "instant") -> None:
    """Assert an instant is rendered UTC with exactly three fractional digits.

    PRD §2.4 pins this rendering, so it is asserted directly where a design
    instance calls for it rather than being smuggled into every comparison.
    """
    assert isinstance(actual, str), f"{label} must be a string, got {actual!r}"
    assert is_iso8601_timestamp(actual), f"{label} is not ISO-8601: {actual!r}"
    body, _, fraction = actual.partition(".")
    assert fraction, f"{label} must carry a fractional part: {actual!r}"
    digits = fraction.rstrip("Z")
    assert len(digits) == 3 and digits.isdigit(), (
        f"{label} must carry exactly three fractional digits, got {actual!r}"
    )
    assert actual.endswith("Z"), f"{label} must be rendered in UTC, got {actual!r}"
    assert body, f"{label} is malformed: {actual!r}"


def assert_instant_before(earlier: str, later: str) -> None:
    """Assert ``earlier`` is strictly before ``later``."""
    assert parse_instant(earlier) < parse_instant(later), (
        f"expected {earlier} to be strictly before {later}"
    )


# ---------------------------------------------------------------------------
# Identifiers and common fields
# ---------------------------------------------------------------------------


def assert_bare_uuid(value: Any, label: str = "id") -> None:
    """Assert an identifier is a bare UUID with no type prefix (PRD §2.4)."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert is_valid_uuid(value), f"{label} must be a bare UUID, got {value!r}"


def assert_common_fields(row: Dict[str, Any], expected_version: Optional[int] = None):
    """Assert the PRD §2.4 common fields are present and well formed."""
    assert_bare_uuid(row.get("id"), "id")
    assert_three_fraction_digits(row.get("created_at"), "created_at")
    assert_three_fraction_digits(row.get("updated_at"), "updated_at")
    version = row.get("version")
    assert isinstance(version, int) and not isinstance(version, bool), (
        f"version must be a JSON integer, got {version!r}"
    )
    assert version >= 1, f"version starts at 1, got {version}"
    if expected_version is not None:
        assert version == expected_version, (
            f"version: expected {expected_version}, got {version}"
        )


def assert_unchanged(before: Dict[str, Any], after: Dict[str, Any], *fields: str):
    """Assert the named fields are byte-identical across two reads."""
    for name in fields:
        assert before.get(name) == after.get(name), (
            f"{name} changed from {before.get(name)!r} to {after.get(name)!r}"
        )


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------


def assert_pagination_meta(
    meta: Dict[str, Any],
    limit: int,
    offset: int,
    total_count: int,
    has_more: bool,
) -> None:
    """Assert the four list-meta fields of PRD §2.2 exactly."""
    assert_integer_equals(meta.get("limit"), limit, "meta.limit")
    assert_integer_equals(meta.get("offset"), offset, "meta.offset")
    assert_integer_equals(meta.get("total_count"), total_count, "meta.total_count")
    assert meta.get("has_more") is has_more, (
        f"meta.has_more: expected {has_more}, got {meta.get('has_more')!r}"
    )


def ids_of(rows: Iterable[Dict[str, Any]]) -> List[str]:
    """Project the ``id`` field out of a list of rows."""
    return [row["id"] for row in rows]


def assert_covers_exactly(pages: Iterable[Iterable[Dict[str, Any]]], expected: Iterable[str]):
    """Assert the union of several pages covers each expected id exactly once."""
    seen: List[str] = []
    for page in pages:
        seen.extend(ids_of(page))
    assert len(seen) == len(set(seen)), f"a row appeared on two pages: {seen}"
    assert set(seen) == set(expected), (
        f"pages covered {sorted(set(seen))}, expected {sorted(set(expected))}"
    )


def assert_ascending_by_created_at(rows: List[Dict[str, Any]]) -> None:
    """Assert rows are ordered by created_at ascending (PRD §2.3)."""
    stamps = [parse_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), "rows are not ordered by created_at ascending"


# ---------------------------------------------------------------------------
# Vendor risk and posture
# ---------------------------------------------------------------------------


def assert_risk_and_posture(vendor: Dict[str, Any], risk_score: str, posture: str):
    """Assert a vendor's live risk score and the posture derived from it."""
    assert_decimal_equals(vendor.get("risk_score"), risk_score, "risk_score")
    assert vendor.get("privacy_posture") == posture, (
        f"privacy_posture: expected {posture}, got {vendor.get('privacy_posture')!r}"
    )
