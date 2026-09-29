"""Domain assertions for the Meeting Venue Sourcing & RFP API.

These wrap the repetitive checks the PRD's global specifications impose: the
two-decimal money convention, the four-decimal benchmark variance, the identity
field sets, the two conserved quantities and the declared collection orderings.
"""

import re
from typing import Any, Dict, Iterable, List, Optional

import pytest

from .constants import MONEY_TOLERANCE, PCT_4DP_TOLERANCE

ISO_INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
CALENDAR_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Numeric conventions
# ---------------------------------------------------------------------------
def assert_money(actual: Any, expected: float, label: str = "amount") -> None:
    """A monetary amount is a JSON number carried to exactly two decimals."""
    assert actual is not None, f"{label} is missing"
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be a JSON number, got {type(actual).__name__}: {actual!r}"
    )
    assert actual == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_money_field(entity: Dict[str, Any], field: str, expected: float) -> None:
    assert field in entity, f"{field} missing from payload"
    assert_money(entity[field], expected, field)


def assert_two_decimals(value: Any, label: str = "amount") -> None:
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be a JSON number, got {type(value).__name__}"
    )
    assert round(float(value), 2) == pytest.approx(float(value), abs=1e-9), (
        f"{label} carries more than two decimal places: {value}"
    )


def assert_variance_pct(actual: Any, expected: float) -> None:
    """``benchmark_variance_pct`` is carried to four decimal places."""
    assert actual is not None, "benchmark_variance_pct is missing"
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"benchmark_variance_pct must be a JSON number, got {actual!r}"
    )
    assert actual == pytest.approx(expected, abs=PCT_4DP_TOLERANCE), (
        f"benchmark_variance_pct: expected {expected}, got {actual}"
    )


def assert_integer(value: Any, expected: int, label: str = "count") -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer, got {type(value).__name__}: {value!r}"
    )
    assert value == expected, f"{label}: expected {expected}, got {value}"


# ---------------------------------------------------------------------------
# Identity, timestamps and versioning
# ---------------------------------------------------------------------------
def assert_iso_instant(value: Any, label: str = "timestamp") -> None:
    """ISO 8601 UTC with exactly three fractional digits."""
    assert isinstance(value, str) and ISO_INSTANT_RE.match(value), (
        f"{label} is not an ISO 8601 UTC instant with three fractional digits: {value!r}"
    )


def assert_calendar_date(value: Any, label: str = "date") -> None:
    assert isinstance(value, str) and CALENDAR_DATE_RE.match(value), (
        f"{label} is not a YYYY-MM-DD calendar date: {value!r}"
    )


def assert_versioned_entity(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """A resource carrying the full audit quartet id/created_at/updated_at/version."""
    for field in ("id", "created_at", "updated_at", "version"):
        assert field in entity, f"{field} missing from resource"
    assert isinstance(entity["id"], str) and entity["id"], "id must be a string"
    assert_iso_instant(entity["created_at"], "created_at")
    assert_iso_instant(entity["updated_at"], "updated_at")
    assert isinstance(entity["version"], int) and not isinstance(entity["version"], bool)
    assert entity["version"] >= 1, "version starts at 1 on creation"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"version: expected {expected_version}, got {entity['version']}"
        )


def assert_append_only_entity(entity: Dict[str, Any]) -> None:
    """An append-only record exposes only ``id`` and ``created_at``."""
    for field in ("id", "created_at"):
        assert field in entity, f"{field} missing from append-only record"
    assert_iso_instant(entity["created_at"], "created_at")
    assert "updated_at" not in entity, "an append-only record has no updated_at field"
    assert "version" not in entity, "an append-only record has no version field"


def assert_version_advanced(before: Dict[str, Any], after: Dict[str, Any], by: int = 1) -> None:
    assert after["version"] == before["version"] + by, (
        f"version should advance by {by}: {before['version']} -> {after['version']}"
    )


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------
def assert_envelope(response, expected_response_type: str) -> Dict[str, Any]:
    """Check the envelope's meta block and response_type, and return the body."""
    body = response.json()
    assert "meta" in body, "response envelope is missing meta"
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_: {meta['api_request_id']!r}"
    )
    assert_iso_instant(meta.get("api_request_timestamp"), "api_request_timestamp")
    assert body.get("response_type") == expected_response_type, (
        f"response_type: expected {expected_response_type}, got {body.get('response_type')}"
    )
    return body


def assert_pagination_meta(
    meta: Dict[str, Any], limit: int, offset: int, total_count: int, has_more: bool
) -> None:
    assert meta.get("limit") == limit, f"limit: expected {limit}, got {meta.get('limit')}"
    assert meta.get("offset") == offset, (
        f"offset: expected {offset}, got {meta.get('offset')}"
    )
    assert meta.get("total_count") == total_count, (
        f"total_count: expected {total_count}, got {meta.get('total_count')}"
    )
    assert meta.get("has_more") is has_more, (
        f"has_more: expected {has_more}, got {meta.get('has_more')}"
    )


# ---------------------------------------------------------------------------
# Conserved quantities
# ---------------------------------------------------------------------------
def assert_budget_envelope(event: Dict[str, Any]) -> None:
    """``budget_remaining_usd + committed_spend_usd + cancellation_liability_usd``
    equals ``budget_ceiling_usd`` exactly."""
    total = (
        event["budget_remaining_usd"]
        + event["committed_spend_usd"]
        + event["cancellation_liability_usd"]
    )
    assert total == pytest.approx(event["budget_ceiling_usd"], abs=MONEY_TOLERANCE), (
        "money identity broken: remaining {r} + committed {c} + liability {l} != ceiling {b}".format(
            r=event["budget_remaining_usd"],
            c=event["committed_spend_usd"],
            l=event["cancellation_liability_usd"],
            b=event["budget_ceiling_usd"],
        )
    )


def assert_room_night_inventory(venue: Dict[str, Any], expected_nights: int) -> None:
    """A venue's ``blocked_room_nights`` is an exact integer night count."""
    assert_integer(venue["blocked_room_nights"], expected_nights, "blocked_room_nights")


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------
def assert_ascending(items: List[Dict[str, Any]], field: str) -> None:
    values = [item[field] for item in items]
    assert values == sorted(values), f"{field} is not ascending: {values}"


def assert_sequence(items: List[Dict[str, Any]], field: str, expected: List[Any]) -> None:
    values = [item[field] for item in items]
    assert values == expected, f"{field}: expected {expected}, got {values}"


def assert_ids(items: Iterable[Dict[str, Any]], expected_ids: List[str]) -> None:
    assert [item["id"] for item in items] == expected_ids


# ---------------------------------------------------------------------------
# Composite domain checks
# ---------------------------------------------------------------------------
def assert_cost_components(snapshot: Dict[str, Any], expected: Dict[str, float]) -> None:
    """Compare a cost-model snapshot against expected component amounts."""
    for field, value in expected.items():
        if isinstance(value, int) and field.endswith("_nights_used"):
            assert_integer(snapshot[field], value, field)
        elif isinstance(value, str):
            assert snapshot[field] == value, (
                f"{field}: expected {value}, got {snapshot[field]}"
            )
        else:
            assert_money_field(snapshot, field, value)


def assert_fields_equal(entity: Dict[str, Any], expected: Dict[str, Any]) -> None:
    """Compare a set of non-monetary fields on a resource."""
    for field, value in expected.items():
        assert field in entity, f"{field} missing from resource"
        assert entity[field] == value, (
            f"{field}: expected {value!r}, got {entity[field]!r}"
        )


def assert_nulls(entity: Dict[str, Any], fields: Iterable[str]) -> None:
    for field in fields:
        assert field in entity, f"{field} missing from resource"
        assert entity[field] is None, f"{field} should be null, got {entity[field]!r}"


def assert_deposit_split_sums(installments: List[Dict[str, Any]], deposit_total: float) -> None:
    """The three installment amounts sum to the deposit total to the cent."""
    total = round(sum(i["amount_usd"] for i in installments), 2)
    assert total == pytest.approx(deposit_total, abs=1e-9), (
        f"installment amounts sum to {total}, deposit_total_usd is {deposit_total}"
    )
