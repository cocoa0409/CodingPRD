"""Domain assertions: envelope/common-field shape, instant comparison and the
two conservation invariants the PRD declares always-true.
"""
import re
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .constants import (
    COMMON_FIELDS,
    HEADCOUNT_COVERAGE_STATUSES,
    HRA_LEDGER_BUCKETS,
)

# PRD 2.4: timestamps are ISO 8601 UTC with exactly three fractional digits.
_MILLIS_INSTANT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)
# PRD 2.6: the named calendar fields carry a date only, with no time part.
_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --------------------------------------------------------------------------- #
# Instants
# --------------------------------------------------------------------------- #
def normalize_instant(value: str) -> str:
    """Reduce an ISO 8601 UTC instant to a millisecond-resolution canonical form.

    PRD 2.6 compares instants at millisecond resolution, so a serialization that
    carries more or fewer fractional digits than the pinned literal, or writes
    the UTC designator as +00:00, still denotes the same instant. Comparisons go
    through this function; the exactly-three-digit rendering rule of PRD 2.4 is
    asserted separately by assert_millis_instant_format.
    """
    assert isinstance(value, str), f"instant must be a string, got {type(value)}"
    text = value.strip()
    if text.endswith("+00:00"):
        text = text[: -len("+00:00")] + "Z"
    if not text.endswith("Z"):
        text = text + "Z"
    body = text[:-1]
    if "." in body:
        head, frac = body.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = body, "000"
    return f"{head}.{frac}Z"


def assert_instant_equals(actual: Optional[str], expected: str, label: str = "instant"):
    """Assert two ISO 8601 UTC instants denote the same millisecond."""
    assert actual is not None, f"{label}: expected {expected}, got None"
    assert normalize_instant(actual) == normalize_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_millis_instant_format(value: str, label: str = "timestamp"):
    """Assert the PRD 2.4 rendering: ISO 8601 UTC with exactly three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {type(value)}"
    assert _MILLIS_INSTANT_RE.match(value), (
        f"{label} must be ISO 8601 UTC with exactly three fractional digits "
        f"and a trailing Z, got {value!r}"
    )


def assert_date_only(value: str, label: str = "date"):
    """Assert a PRD 2.6 date-only field carries no time component."""
    assert isinstance(value, str), f"{label} must be a string, got {type(value)}"
    assert _DATE_ONLY_RE.match(value), (
        f"{label} must be a date with no time part (YYYY-MM-DD), got {value!r}"
    )


# --------------------------------------------------------------------------- #
# Common fields (PRD 2.4)
# --------------------------------------------------------------------------- #
def assert_common_fields(entity: Dict[str, Any], label: str = "entity"):
    """Assert the four fields every entity carries: id, created_at, updated_at, version."""
    for field in COMMON_FIELDS:
        assert field in entity, f"{label} is missing common field {field}"
    assert is_valid_uuid(entity["id"]), f"{label}.id must be a UUID, got {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"{label}.created_at must be an ISO 8601 timestamp, got {entity['created_at']!r}"
    )
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"{label}.updated_at must be an ISO 8601 timestamp, got {entity['updated_at']!r}"
    )
    assert isinstance(entity["version"], int) and not isinstance(
        entity["version"], bool
    ), f"{label}.version must be an integer, got {entity['version']!r}"
    assert entity["version"] >= 1, (
        f"{label}.version starts at 1, got {entity['version']}"
    )


def assert_fields_equal(entity: Dict[str, Any], expected: Dict[str, Any], label: str = "entity"):
    """Assert every key in `expected` is present on the entity with that exact value."""
    for key, want in expected.items():
        assert key in entity, f"{label} is missing field {key}"
        assert entity[key] == want, (
            f"{label}.{key}: expected {want!r}, got {entity[key]!r}"
        )


def assert_integer_cents(entity: Dict[str, Any], *fields: str, label: str = "entity"):
    """Assert the named money fields are integers, per the PRD 2.6 cents rule."""
    for field in fields:
        assert field in entity, f"{label} is missing money field {field}"
        value = entity[field]
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{label}.{field} must be an integer number of cents, got {value!r}"
        )


# --------------------------------------------------------------------------- #
# Conservation invariants (PRD 2.10)
# --------------------------------------------------------------------------- #
def assert_hra_ledger_conservation(account: Dict[str, Any], label: str = "HraAccount"):
    """funded_cents == the sum of the five ledger buckets, exactly, always."""
    assert_integer_cents(account, "funded_cents", *HRA_LEDGER_BUCKETS, label=label)
    total = sum(account[bucket] for bucket in HRA_LEDGER_BUCKETS)
    assert account["funded_cents"] == total, (
        f"{label} ledger conservation violated: funded_cents "
        f"{account['funded_cents']} != "
        + " + ".join(f"{b}={account[b]}" for b in HRA_LEDGER_BUCKETS)
        + f" (sum {total})"
    )


def assert_hra_buckets(account: Dict[str, Any], label: str = "HraAccount", **expected: int):
    """Assert named ledger bucket values and re-check conservation afterwards."""
    assert_fields_equal(account, expected, label=label)
    assert_hra_ledger_conservation(account, label=label)


def assert_enrolled_count_conservation(
    enrolled_count: int,
    enrollments: Sequence[Dict[str, Any]],
    label: str = "PlanOption.enrolled_count",
):
    """enrolled_count equals the number of the option's enrollments whose
    coverage_status is PENDING, ACTIVE or SUSPENDED (PRD 2.10)."""
    counted = [
        e for e in enrollments if e.get("coverage_status") in HEADCOUNT_COVERAGE_STATUSES
    ]
    assert enrolled_count == len(counted), (
        f"{label} conservation violated: counter is {enrolled_count} but "
        f"{len(counted)} enrollment(s) are in {HEADCOUNT_COVERAGE_STATUSES} "
        f"(statuses seen: {[e.get('coverage_status') for e in enrollments]})"
    )


# --------------------------------------------------------------------------- #
# List helpers
# --------------------------------------------------------------------------- #
def assert_list_ids(items: Sequence[Dict[str, Any]], expected_ids: Sequence[str], label: str = "list"):
    """Assert a list endpoint returned exactly these ids in exactly this order."""
    actual = [item["id"] for item in items]
    assert actual == list(expected_ids), (
        f"{label}: expected ids {list(expected_ids)}, got {actual}"
    )


def assert_created_at_ascending(items: Sequence[Dict[str, Any]], label: str = "list"):
    """Assert a list endpoint ordered its rows by created_at ascending (PRD 2.3)."""
    stamps = [normalize_instant(item["created_at"]) for item in items]
    assert stamps == sorted(stamps), (
        f"{label} must be ordered by created_at ascending, got {stamps}"
    )


def collect_all(response) -> List[Dict[str, Any]]:
    """Return the rows of a paginated list response."""
    rows, _meta = validate_paginated(response)
    return rows


def assert_pagination_meta(
    meta: Dict[str, Any],
    limit: int,
    offset: int,
    total_count: int,
    has_more: bool,
    label: str = "meta",
):
    """Assert the four pagination meta fields the PRD requires on list responses."""
    assert meta["limit"] == limit, f"{label}.limit: expected {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, (
        f"{label}.offset: expected {offset}, got {meta['offset']}"
    )
    assert meta["total_count"] == total_count, (
        f"{label}.total_count: expected {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"{label}.has_more: expected {has_more}, got {meta['has_more']}"
    )


def assert_version_is(entity: Dict[str, Any], expected: int, label: str = "entity"):
    """Assert an entity's version counter (PRD 2.4: starts at 1, +1 per mutation)."""
    assert entity["version"] == expected, (
        f"{label}.version: expected {expected}, got {entity['version']}"
    )


__all__ = [
    "normalize_instant",
    "assert_instant_equals",
    "assert_millis_instant_format",
    "assert_date_only",
    "assert_common_fields",
    "assert_fields_equal",
    "assert_integer_cents",
    "assert_hra_ledger_conservation",
    "assert_hra_buckets",
    "assert_enrolled_count_conservation",
    "assert_list_ids",
    "assert_created_at_ascending",
    "collect_all",
    "assert_pagination_meta",
    "assert_version_is",
]
