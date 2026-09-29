"""Domain assertions for the accreditation registry.

Everything here works on the already-unwrapped ``data`` payload, so no
helper in this module indexes ``["data"]`` again -- the validators have
already done that unwrapping exactly once.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import requests

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .constants import (
    RATE_ON_SITE_DAY_CENTS,
    RATE_REMOTE_DAY_CENTS,
    RATE_TRAVEL_DAY_CENTS,
    RATE_WITNESS_DAY_CENTS,
    SCHEME_DEFAULT_CRITICAL_CLOSE_DAYS,
    SCHEME_DEFAULT_MAJOR_CLOSE_DAYS,
    SCHEME_DEFAULT_MINOR_CLOSE_DAYS,
    SCHEME_DEFAULT_POINTS_REQUIRED,
    SCHEME_DEFAULT_REASSESSMENT_INTERVAL_DAYS,
    SCHEME_DEFAULT_REMOTE_ASSESSMENT_ALLOWED,
    SCHEME_DEFAULT_SURVEILLANCE_INTERVAL_DAYS,
    SCHEME_DEFAULT_UNANNOUNCED_AUTHORITY,
    SCHEME_DEFAULT_WITNESS_MIN_COUNT,
    SCHEME_DRAFT,
)

PAGINATION_META_FIELDS = ("limit", "offset", "total_count", "has_more")


# --- Envelope shapes -----------------------------------------------------


def validate_unpaginated(response: requests.Response) -> List[Dict[str, Any]]:
    """Validate a list response, returning only the rows.

    Use where the test cares about the rows but not the pagination window.
    """
    data = validate_success(response, 200)
    assert isinstance(data, list), f"Expected an array payload, got {type(data)}"
    return data


def validate_list(response: requests.Response) -> Tuple[List[Dict[str, Any]], Dict]:
    """Validate a list response, returning ``(rows, meta)``."""
    rows, meta = validate_paginated(response)
    assert isinstance(rows, list), f"Expected an array payload, got {type(rows)}"
    return rows, meta


def assert_pagination_meta(
    meta: Dict[str, Any],
    limit: int,
    offset: int,
    total_count: int,
    has_more: bool,
) -> None:
    assert meta["limit"] == limit, f"meta.limit {meta['limit']} != {limit}"
    assert meta["offset"] == offset, f"meta.offset {meta['offset']} != {offset}"
    assert meta["total_count"] == total_count, (
        f"meta.total_count {meta['total_count']} != {total_count}"
    )
    assert meta["has_more"] is has_more, (
        f"meta.has_more {meta['has_more']!r} is not {has_more!r}"
    )


def assert_total_count(response: requests.Response, total_count: int) -> List[Dict]:
    rows, meta = validate_list(response)
    assert meta["total_count"] == total_count, (
        f"Expected total_count {total_count}, got {meta['total_count']}"
    )
    return rows


def assert_single_resource_envelope(response: requests.Response, expected_status: int = 200) -> Dict:
    """A single-resource response carries no pagination fields (section 2.3)."""
    body = response.json()
    data = validate_success(response, expected_status)
    assert body["response_type"] == "object", (
        f"Expected response_type 'object', got {body['response_type']!r}"
    )
    for field in PAGINATION_META_FIELDS:
        assert field not in body["meta"], (
            f"Single-resource responses omit pagination field {field!r}"
        )
    return data


# --- Identity and audit fields ------------------------------------------


def assert_audit_fields(resource: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """``id``, ``created_at``, ``updated_at`` and ``version`` (section 2.4)."""
    assert is_valid_uuid(resource["id"]), f"id is not a UUID: {resource['id']!r}"
    assert not resource["id"].startswith(("scheme_", "asr_", "app_")), (
        f"id must carry no type prefix: {resource['id']!r}"
    )
    assert_instant_format(resource["created_at"])
    assert_instant_format(resource["updated_at"])
    assert isinstance(resource["version"], int), "version must be an integer"
    if expected_version is not None:
        assert resource["version"] == expected_version, (
            f"Expected version {expected_version}, got {resource['version']}"
        )


def assert_append_only_fields(resource: Dict[str, Any]) -> None:
    """An ``ImpartialityDeclaration`` carries only ``id`` and ``created_at``."""
    assert is_valid_uuid(resource["id"]), f"id is not a UUID: {resource['id']!r}"
    assert_instant_format(resource["created_at"])
    assert "updated_at" not in resource, (
        "An immutable declaration must not carry updated_at"
    )
    assert "version" not in resource, "An immutable declaration must not carry version"


def assert_instant_format(value: str) -> None:
    """An ISO 8601 UTC instant with exactly three fractional digits."""
    assert is_iso8601_timestamp(value), f"Not an ISO 8601 UTC instant: {value!r}"
    assert value.endswith("Z"), f"Instant must be rendered in UTC: {value!r}"
    assert len(value) == 24 and value[19] == ".", (
        f"Instant must carry exactly three fractional digits: {value!r}"
    )


def canonical_instant(value: str) -> str:
    """Normalise an instant to three fractional digits for comparison.

    Accepts ``...T00:00:00Z``, ``...T00:00:00.0Z`` and ``...T00:00:00.000000Z``
    alike, so a test never fails merely because the server rendered a
    different sub-second width than the design index wrote down.
    """
    assert isinstance(value, str), f"Not an instant string: {value!r}"
    text = value.strip()
    assert text.endswith("Z"), f"Instant must end in Z: {value!r}"
    stem = text[:-1]
    if "." in stem:
        head, frac = stem.split(".", 1)
    else:
        head, frac = stem, ""
    frac = (frac + "000")[:3]
    parsed = datetime.strptime(head, "%Y-%m-%dT%H:%M:%S")
    return parsed.strftime("%Y-%m-%dT%H:%M:%S") + "." + frac + "Z"


def assert_instant_equals(actual: str, expected: str) -> None:
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"Instant {actual!r} does not equal {expected!r}"
    )


def assert_date_equals(actual: Any, expected: str) -> None:
    assert actual == expected, f"Expected date {expected!r}, got {actual!r}"


def assert_instant_on_date(actual: str, expected_date: str) -> None:
    assert canonical_instant(actual).startswith(expected_date), (
        f"Instant {actual!r} does not fall on {expected_date}"
    )


def add_days(iso_date: str, days: int) -> str:
    return (date.fromisoformat(iso_date) + timedelta(days=days)).isoformat()


def find_by_id(rows: Iterable[Dict[str, Any]], resource_id: str) -> Dict[str, Any]:
    for row in rows:
        if row.get("id") == resource_id:
            return row
    raise AssertionError(f"No row with id {resource_id!r} in {[r.get('id') for r in rows]}")


def assert_ids_in_order(rows: Sequence[Dict[str, Any]], expected_ids: Sequence[str]) -> None:
    actual = [row["id"] for row in rows]
    assert actual == list(expected_ids), f"Expected ids {list(expected_ids)}, got {actual}"


def assert_all_distinct(values: Sequence[Any], label: str = "values") -> None:
    assert len(set(values)) == len(values), (
        f"Expected pairwise-distinct {label}, got {list(values)}"
    )


# --- Numeric conventions -------------------------------------------------


def assert_points_equal(actual: Any, expected: str) -> None:
    """Competence points carried to exactly two decimal places."""
    assert actual is not None, f"Expected points {expected}, got null"
    assert Decimal(str(actual)) == Decimal(expected), (
        f"Expected points {expected}, got {actual!r}"
    )


def assert_cents(actual: Any, expected: int) -> None:
    """Money is a whole integer number of cents."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"Money must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"Expected {expected} cents, got {actual}"


# --- Scheme --------------------------------------------------------------


def assert_scheme_defaults(scheme: Dict[str, Any]) -> None:
    """Every optional rule-set field fell back to its declared default."""
    assert scheme["complexity_multiplier"] == 1.0, (
        f"complexity_multiplier default is 1.0000, got {scheme['complexity_multiplier']}"
    )
    assert scheme["witness_min_count"] == SCHEME_DEFAULT_WITNESS_MIN_COUNT
    assert float(scheme["qualification_points_required"]) == SCHEME_DEFAULT_POINTS_REQUIRED
    assert scheme["surveillance_interval_days"] == SCHEME_DEFAULT_SURVEILLANCE_INTERVAL_DAYS
    assert scheme["reassessment_interval_days"] == SCHEME_DEFAULT_REASSESSMENT_INTERVAL_DAYS
    assert scheme["critical_nc_close_days"] == SCHEME_DEFAULT_CRITICAL_CLOSE_DAYS
    assert scheme["major_nc_close_days"] == SCHEME_DEFAULT_MAJOR_CLOSE_DAYS
    assert scheme["minor_nc_close_days"] == SCHEME_DEFAULT_MINOR_CLOSE_DAYS
    assert scheme["unannounced_authority"] is SCHEME_DEFAULT_UNANNOUNCED_AUTHORITY
    assert scheme["remote_assessment_allowed"] is SCHEME_DEFAULT_REMOTE_ASSESSMENT_ALLOWED
    assert scheme["status"] == SCHEME_DRAFT
    assert scheme["rule_revision"] == 1
    assert scheme["revision_note"] is None
    assert scheme["published_at"] is None


# --- Assessor ledger ----------------------------------------------------


def assert_capacity_ledger(
    assessor: Dict[str, Any],
    committed: Optional[int] = None,
    available: Optional[int] = None,
) -> None:
    """``annual_witness_capacity_days == committed + available`` (section 2.8)."""
    capacity = assessor["annual_witness_capacity_days"]
    actual_committed = assessor["committed_witness_days"]
    actual_available = assessor["available_witness_days"]
    assert actual_committed + actual_available == capacity, (
        f"Ledger identity broken: {actual_committed} + {actual_available} != {capacity}"
    )
    if committed is not None:
        assert actual_committed == committed, (
            f"Expected committed_witness_days {committed}, got {actual_committed}"
        )
    if available is not None:
        assert actual_available == available, (
            f"Expected available_witness_days {available}, got {actual_available}"
        )


# --- Cycle finding ledger -----------------------------------------------


def assert_finding_ledger(
    application: Dict[str, Any],
    total: Optional[int] = None,
    blocking: Optional[int] = None,
    closed: Optional[int] = None,
    observation: Optional[int] = None,
) -> None:
    """``blocking + closed == total - observation`` (section 2.8)."""
    actual_total = application["nc_total_count"]
    actual_blocking = application["nc_blocking_open_count"]
    actual_closed = application["nc_closed_count"]
    actual_observation = application["nc_observation_count"]
    assert actual_blocking + actual_closed == actual_total - actual_observation, (
        "Finding ledger identity broken: "
        f"{actual_blocking} + {actual_closed} != {actual_total} - {actual_observation}"
    )
    if total is not None:
        assert actual_total == total, f"Expected nc_total_count {total}, got {actual_total}"
    if blocking is not None:
        assert actual_blocking == blocking, (
            f"Expected nc_blocking_open_count {blocking}, got {actual_blocking}"
        )
    if closed is not None:
        assert actual_closed == closed, (
            f"Expected nc_closed_count {closed}, got {actual_closed}"
        )
    if observation is not None:
        assert actual_observation == observation, (
            f"Expected nc_observation_count {observation}, got {actual_observation}"
        )


# --- Plan effort and fee ------------------------------------------------


def assert_effort_breakdown(
    plan: Dict[str, Any],
    witness_days_planned: int,
    core_days: int,
    travel_days: int,
    total_effort_days: int,
) -> None:
    assert plan["witness_days_planned"] == witness_days_planned, (
        f"Expected witness_days_planned {witness_days_planned}, "
        f"got {plan['witness_days_planned']}"
    )
    assert plan["core_days"] == core_days, (
        f"Expected core_days {core_days}, got {plan['core_days']}"
    )
    assert plan["travel_days"] == travel_days, (
        f"Expected travel_days {travel_days}, got {plan['travel_days']}"
    )
    assert plan["total_effort_days"] == total_effort_days, (
        f"Expected total_effort_days {total_effort_days}, got {plan['total_effort_days']}"
    )
    assert plan["core_days"] + plan["travel_days"] == plan["total_effort_days"], (
        "total_effort_days must be core_days plus travel_days"
    )


def assert_fee_lines(
    plan: Dict[str, Any],
    on_site_cents: int,
    remote_cents: int,
    witness_cents: int,
    travel_cents: int,
    total_cents: int,
) -> None:
    assert_cents(plan["fee_line_on_site_cents"], on_site_cents)
    assert_cents(plan["fee_line_remote_cents"], remote_cents)
    assert_cents(plan["fee_line_witness_cents"], witness_cents)
    assert_cents(plan["fee_line_travel_cents"], travel_cents)
    assert_cents(plan["assessment_fee_cents"], total_cents)
    assert (
        on_site_cents + remote_cents + witness_cents + travel_cents == total_cents
    ), "assessment_fee_cents must be the plain sum of the four rounded lines"


def assert_travel_line_is_unmultiplied(plan: Dict[str, Any]) -> None:
    """The complexity multiplier never applies to travel (section 3.5)."""
    assert_cents(
        plan["fee_line_travel_cents"], plan["travel_days"] * RATE_TRAVEL_DAY_CENTS
    )


def rounded_fee_line(days: int, day_rate_cents: int, multiplier: str) -> int:
    """One fee line, rounded half up to whole cents before any summing."""
    exact = Decimal(days) * Decimal(day_rate_cents) * Decimal(multiplier)
    return int(exact.quantize(Decimal("1"), rounding="ROUND_HALF_UP"))


DAY_RATES = {
    "on_site": RATE_ON_SITE_DAY_CENTS,
    "remote": RATE_REMOTE_DAY_CENTS,
    "witness": RATE_WITNESS_DAY_CENTS,
    "travel": RATE_TRAVEL_DAY_CENTS,
}
