"""
Assertions for the Reentry Employment Services API.

Re-exports the shared envelope validators so test modules have a single import
site, and adds the domain-shaped assertions this API needs: common-field
checks, money-as-integer-cents checks, one-decimal-place rate checks, instant
equality that tolerates sub-second spelling, and two distinct list-shape
validators.

The PRD gives two different list shapes. Paginated collection reads carry
`limit`, `offset`, `total_count` and `has_more` in `meta`; single-resource reads
and writes omit those four fields from `meta`. A response of the second shape
must therefore never be pushed through the paginated validator, so
validate_unpaginated() exists alongside validate_paginated().
"""

from typing import Any, Dict, List, Optional, Sequence

import requests

from prd_bench_local_runner.testing import (  # noqa: F401
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from .api_client import canonical_instant

PAGINATION_META_KEYS = ("limit", "offset", "total_count", "has_more")


def validate_unpaginated(response: requests.Response, expected_status: int = 200) -> Any:
    """
    Validate a response that is NOT a paginated collection read.

    Asserts the success envelope and then asserts that `meta` omits the four
    pagination fields, which the PRD reserves for collection reads.
    """
    data = validate_success(response, expected_status)
    meta = response.json()["meta"]
    for key in PAGINATION_META_KEYS:
        assert key not in meta, (
            f"meta must omit '{key}' on a non-collection response, got {meta!r}"
        )
    return data


def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None):
    """
    Assert the four fields every resource in this API carries.

    `id` is a UUID, `created_at` and `updated_at` are ISO 8601 UTC instants, and
    `version` is a positive integer.
    """
    assert "id" in entity, f"missing 'id' on {entity!r}"
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']!r}"
    for field in ("created_at", "updated_at"):
        assert field in entity, f"missing '{field}'"
        assert is_iso8601_timestamp(canonical_instant(entity[field])), (
            f"{field} is not an ISO 8601 UTC instant: {entity[field]!r}"
        )
    assert isinstance(entity.get("version"), int) and not isinstance(
        entity.get("version"), bool
    ), f"version must be an integer, got {entity.get('version')!r}"
    assert entity["version"] >= 1, f"version must be at least 1, got {entity['version']}"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_instant_equals(actual: Any, expected: Any, field: str = "instant"):
    """Compare two ISO 8601 UTC instants without regard to sub-second spelling."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{field}: expected {expected!r}, got {actual!r}"
    )


def assert_money_cents(entity: Dict[str, Any], field: str, expected: int):
    """
    Assert a cents-denominated money field.

    Money in this API is always a whole number of cents transported as a JSON
    number, never a string and never a float with a fractional part.
    """
    actual = entity.get(field, "<missing>")
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{field}: expected {expected}, got {actual}"


def assert_int_field(entity: Dict[str, Any], field: str, expected: int):
    """Assert an integer counter field carries exactly the expected value."""
    actual = entity.get(field, "<missing>")
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field} must be an integer, got {actual!r}"
    )
    assert actual == expected, f"{field}: expected {expected}, got {actual}"


def assert_one_decimal_place(
    entity: Dict[str, Any], field: str, expected: Optional[float]
):
    """
    Assert a percentage field rounded half up to one decimal place.

    A JSON number is compared numerically, so 80 and 80.0 are the same value,
    but the field must not arrive as a string.
    """
    actual = entity.get(field, "<missing>")
    if expected is None:
        assert actual is None, f"{field}: expected null, got {actual!r}"
        return
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{field} must be a JSON number, got {actual!r}"
    )
    assert abs(float(actual) - float(expected)) < 1e-9, (
        f"{field}: expected {expected}, got {actual}"
    )


def assert_nullable_rate(
    entity: Dict[str, Any], field: str, expected: Optional[float]
):
    """
    Assert a rate that the PRD declares as exactly null in the zero-denominator
    case — present in the body with a null value, not omitted from it.
    """
    assert field in entity, f"{field} must be present in the body, even when null"
    assert_one_decimal_place(entity, field, expected)


def assert_created_at_stable(before: Dict[str, Any], after: Dict[str, Any]):
    """Assert a mutation refreshed `updated_at` without disturbing `created_at`."""
    assert_instant_equals(after["created_at"], before["created_at"], "created_at")


def assert_page_ids(rows: Sequence[Dict[str, Any]], expected_ids: Sequence[str]):
    """Assert a page carries exactly these row ids, in this order."""
    actual = [row["id"] for row in rows]
    assert actual == list(expected_ids), (
        f"expected page ids {list(expected_ids)}, got {actual}"
    )


def assert_ids_in_order(rows: Sequence[Dict[str, Any]], ordering_field: str):
    """
    Assert a list is non-decreasing on the named field.

    Used for the shift sub-resource list, which the PRD orders by `starts_at`
    ascending.
    """
    values = [canonical_instant(row[ordering_field]) for row in rows]
    assert values == sorted(values), (
        f"rows are not ordered by {ordering_field} ascending: {values}"
    )


def ids_of(rows: Sequence[Dict[str, Any]]) -> List[str]:
    """The `id` of every row, as a list."""
    return [row["id"] for row in rows]


def assert_all_null(entity: Dict[str, Any], fields: Sequence[str]):
    """Assert every named field is present and null."""
    for field in fields:
        assert field in entity, f"{field} must be present in the body"
        assert entity[field] is None, f"{field}: expected null, got {entity[field]!r}"


def assert_array_equals(
    entity: Dict[str, Any], field: str, expected: Sequence[Any]
):
    """Assert an array field equals the expected sequence exactly, in order."""
    actual = entity.get(field, "<missing>")
    assert isinstance(actual, list), f"{field} must be an array, got {actual!r}"
    assert actual == list(expected), f"{field}: expected {list(expected)}, got {actual}"


def assert_unordered_array_equals(
    entity: Dict[str, Any], field: str, expected: Sequence[Any]
):
    """Assert an array field carries exactly these members, order-insensitively."""
    actual = entity.get(field, "<missing>")
    assert isinstance(actual, list), f"{field} must be an array, got {actual!r}"
    assert sorted(actual) == sorted(expected), (
        f"{field}: expected members {sorted(expected)}, got {sorted(actual)}"
    )


def assert_match_breakdown(
    breakdown: Dict[str, Any],
    wage: int,
    hours: int,
    barrier_fit: int,
    access: int,
    readiness: int,
    wotc: int,
):
    """Assert the six match components the PRD stores under `match_breakdown`."""
    expected = {
        "wage_component": wage,
        "hours_component": hours,
        "barrier_fit_component": barrier_fit,
        "access_component": access,
        "readiness_component": readiness,
        "wotc_bonus": wotc,
    }
    for key, value in expected.items():
        assert key in breakdown, f"match_breakdown is missing '{key}'"
        assert breakdown[key] == value, (
            f"match_breakdown.{key}: expected {value}, got {breakdown[key]}"
        )


def assert_ledger_identity(ledger: Dict[str, Any]):
    """
    Assert the grant conservation identity: `authorized_cents` always equals
    `available_cents` plus `committed_cents` plus `disbursed_cents`.
    """
    total = (
        ledger["available_cents"] + ledger["committed_cents"] + ledger["disbursed_cents"]
    )
    assert ledger["authorized_cents"] == total, (
        f"authorized_cents {ledger['authorized_cents']} != available "
        f"{ledger['available_cents']} + committed {ledger['committed_cents']} "
        f"+ disbursed {ledger['disbursed_cents']}"
    )


def assert_opening_seat_identity(opening: Dict[str, Any]):
    """
    Assert the opening seat identity: `openings_count` always equals
    `offered_count` plus `filled_count` plus `remaining_openings`.
    """
    total = (
        opening["offered_count"]
        + opening["filled_count"]
        + opening["remaining_openings"]
    )
    assert opening["openings_count"] == total, (
        f"openings_count {opening['openings_count']} != offered "
        f"{opening['offered_count']} + filled {opening['filled_count']} "
        f"+ remaining {opening['remaining_openings']}"
    )


def assert_session_seat_identity(session: Dict[str, Any]):
    """
    Assert the session seat identity: `seat_capacity` always equals
    `enrolled_count` plus `remaining_seats`.
    """
    total = session["enrolled_count"] + session["remaining_seats"]
    assert session["seat_capacity"] == total, (
        f"seat_capacity {session['seat_capacity']} != enrolled "
        f"{session['enrolled_count']} + remaining {session['remaining_seats']}"
    )
