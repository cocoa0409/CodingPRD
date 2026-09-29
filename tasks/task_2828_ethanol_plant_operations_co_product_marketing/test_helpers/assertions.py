"""
Domain assertions over Ethanol Plant Operations payloads.

These sit on top of the generic format helpers and encode the identity,
precision and instant conventions of PRD sections 2.2, 2.3, 2.4 and 2.6.
"""

import re
from typing import Any, Dict, Iterable, Optional

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant, instants_equal

_THREE_FRACTIONAL_DIGITS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

# Tolerances matching the pinned decimal widths of PRD section 2.6.
TOL_2DP = 0.005
TOL_3DP = 0.0005
TOL_4DP = 0.00005
TOL_6DP = 0.0000005


# ─── Identity and common fields ────────────────────────

def assert_uuid(value: Any, field: str = "id") -> None:
    assert is_valid_uuid(value), f"{field} must be a UUID string, got {value!r}"


def assert_no_id_prefix(value: str, field: str = "id") -> None:
    """PRD 2.4: the id is a UUID string with no type prefix of any kind."""
    assert_uuid(value, field)
    assert ":" not in value and "_" not in value, (
        f"{field} must carry no type prefix, got {value!r}"
    )


def assert_iso_instant(value: Any, field: str) -> None:
    assert is_iso8601_timestamp(value), (
        f"{field} must be an ISO 8601 UTC instant, got {value!r}"
    )


def assert_created_at_has_three_fractional_digits(value: str) -> None:
    """PRD 2.4: created_at carries exactly three fractional-second digits."""
    assert _THREE_FRACTIONAL_DIGITS.match(value), (
        f"created_at must carry exactly three fractional digits, got {value!r}"
    )


def assert_versioned_entity(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """A resource carrying the full identity quartet id/created_at/updated_at/version."""
    assert_no_id_prefix(entity["id"])
    assert_iso_instant(entity["created_at"], "created_at")
    assert_iso_instant(entity["updated_at"], "updated_at")
    assert isinstance(entity["version"], int), "version must be an integer"
    assert entity["version"] >= 1, "version starts at 1 on creation"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_append_only_entity(entity: Dict[str, Any]) -> None:
    """
    PRD 2.4: an append-only row carries only `id` and `created_at` — it has no
    `updated_at` and no `version` at all.
    """
    assert_no_id_prefix(entity["id"])
    assert_iso_instant(entity["created_at"], "created_at")
    assert "updated_at" not in entity, (
        "an append-only row must not carry updated_at"
    )
    assert "version" not in entity, "an append-only row must not carry version"


# ─── Instants ──────────────────────────────────────────

def assert_instant_equals(actual: Any, expected: str, field: str) -> None:
    """Precision-insensitive comparison of a stored instant against an expectation."""
    assert instants_equal(actual, expected), (
        f"{field}: expected {expected}, got {actual!r} "
        f"(canonicalised {canonical_instant(actual)!r})"
    )


def assert_null(value: Any, field: str) -> None:
    assert value is None, f"{field} must be null, got {value!r}"


def assert_not_null(value: Any, field: str) -> None:
    assert value is not None, f"{field} must not be null"


# ─── Numeric precision ────────────────────────────────

def assert_decimal_places(value: Any, places: int, field: str) -> None:
    """A numeric field carries at most `places` decimals (PRD 2.6)."""
    assert isinstance(value, (int, float)), (
        f"{field} must be numeric, got {type(value).__name__}: {value!r}"
    )
    assert round(float(value), places) == pytest.approx(float(value), abs=1e-9), (
        f"{field} carries more than {places} decimals: {value!r}"
    )


def assert_integer_cents(value: Any, field: str) -> None:
    """PRD 2.6: money crosses the boundary as integer cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be a whole number of cents, got {type(value).__name__}: {value!r}"
    )


def assert_amount(actual: Any, expected: float, field: str, tol: float = TOL_2DP) -> None:
    assert actual == pytest.approx(expected, abs=tol), (
        f"{field}: expected {expected}, got {actual!r}"
    )


def assert_2dp(actual: Any, expected: float, field: str) -> None:
    assert_decimal_places(actual, 2, field)
    assert_amount(actual, expected, field, TOL_2DP)


def assert_3dp(actual: Any, expected: float, field: str) -> None:
    assert_decimal_places(actual, 3, field)
    assert_amount(actual, expected, field, TOL_3DP)


def assert_4dp(actual: Any, expected: float, field: str) -> None:
    assert_decimal_places(actual, 4, field)
    assert_amount(actual, expected, field, TOL_4DP)


def assert_6dp(actual: Any, expected: float, field: str) -> None:
    assert_decimal_places(actual, 6, field)
    assert_amount(actual, expected, field, TOL_6DP)


def assert_1dp(actual: Any, expected: float, field: str) -> None:
    assert_decimal_places(actual, 1, field)
    assert_amount(actual, expected, field, 0.05)


# ─── Envelope and listing shape ───────────────────────

def assert_error_envelope_shape(body: Dict[str, Any]) -> None:
    """PRD 2.2: an error envelope's meta carries only the two request fields."""
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta must carry only api_request_id and api_request_timestamp, "
        f"got {sorted(body['meta'].keys())}"
    )
    assert body["data"]["message"].strip(), "error message must be non-empty"


def assert_pagination_meta(
    meta: Dict[str, Any],
    limit: int,
    offset: int,
    total_count: int,
    has_more: bool,
) -> None:
    """PRD 2.3: the four pagination fields of a list response's meta."""
    assert meta["limit"] == limit, f"meta.limit: expected {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, (
        f"meta.offset: expected {offset}, got {meta['offset']}"
    )
    assert meta["total_count"] == total_count, (
        f"meta.total_count: expected {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"meta.has_more: expected {has_more}, got {meta['has_more']}"
    )


def assert_ids_equal(actual: Any, expected: str, field: str) -> None:
    assert actual == expected, f"{field}: expected {expected}, got {actual!r}"


def ids_of(rows: Iterable[Dict[str, Any]]) -> list:
    return [row["id"] for row in rows]


# ─── Plant posture ────────────────────────────────────

def assert_plant_posture(
    plant: Dict[str, Any],
    compliance_posture: Optional[str] = None,
    procurement_posture: Optional[str] = None,
    daily_grind_cap_bushels: Optional[int] = None,
) -> None:
    """The two derived postures and the grind cap of PRD 2.8."""
    if compliance_posture is not None:
        assert plant["compliance_posture"] == compliance_posture, (
            f"compliance_posture: expected {compliance_posture}, "
            f"got {plant['compliance_posture']}"
        )
    if procurement_posture is not None:
        assert plant["procurement_posture"] == procurement_posture, (
            f"procurement_posture: expected {procurement_posture}, "
            f"got {plant['procurement_posture']}"
        )
    if daily_grind_cap_bushels is not None:
        assert plant["daily_grind_cap_bushels"] == daily_grind_cap_bushels, (
            f"daily_grind_cap_bushels: expected {daily_grind_cap_bushels}, "
            f"got {plant['daily_grind_cap_bushels']}"
        )
