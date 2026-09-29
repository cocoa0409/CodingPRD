"""Domain assertion helpers.

These wrap the generic framework assertions with the PRD's own rules: the
common-property split between versioned and append-only registers, the two
conservation identities, monetary and ratio precision, and instant comparison
that is immune to sub-second formatting width.
"""

import re
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .api_client import canonical_instant

_REQ_ID_RE = re.compile(r"^req_[A-Za-z0-9]+$")
_THREE_FRACTIONAL_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


# ─── envelope ────────────────────────────────────────────────────────

def assert_envelope_meta(response) -> Dict[str, Any]:
    """The meta block carries a req_-prefixed id and a 3-fraction timestamp."""
    meta = response.json()["meta"]
    assert _REQ_ID_RE.match(meta["api_request_id"]), (
        f"api_request_id must start with 'req_': {meta['api_request_id']!r}"
    )
    assert _THREE_FRACTIONAL_RE.match(meta["api_request_timestamp"]), (
        "api_request_timestamp must be an ISO 8601 UTC timestamp with three "
        f"fractional digits: {meta['api_request_timestamp']!r}"
    )
    return meta


def assert_response_type(response, expected: str) -> None:
    actual = response.json()["response_type"]
    assert actual == expected, f"Expected response_type {expected!r}, got {actual!r}"


def assert_error_meta_only(response) -> None:
    """An error envelope's meta carries only the two request fields."""
    meta = response.json()["meta"]
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"Error meta must carry only the two request fields, got {sorted(meta)}"
    )


# ─── common resource properties ──────────────────────────────────────

def assert_versioned_row(row: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """A row from one of the ten registers that carry the full audit quartet."""
    assert is_valid_uuid(row["id"]), f"id must be a UUID string: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), (
        f"created_at must be an ISO 8601 UTC timestamp: {row['created_at']!r}"
    )
    assert is_iso8601_timestamp(row["updated_at"]), (
        f"updated_at must be an ISO 8601 UTC timestamp: {row['updated_at']!r}"
    )
    assert isinstance(row["version"], int), "version must be an integer"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"Expected version {expected_version}, got {row['version']}"
        )


def assert_append_only_row(row: Dict[str, Any]) -> None:
    """A row from one of the four append-only registers: no updated_at, no version."""
    assert is_valid_uuid(row["id"]), f"id must be a UUID string: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), (
        f"created_at must be an ISO 8601 UTC timestamp: {row['created_at']!r}"
    )
    assert "updated_at" not in row, (
        "updated_at must be absent from an append-only record"
    )
    assert "version" not in row, "version must be absent from an append-only record"


def assert_no_type_prefix(row: Dict[str, Any]) -> None:
    """Identifiers carry no type prefix of any kind."""
    assert is_valid_uuid(row["id"]), f"id must be a bare UUID: {row['id']!r}"


# ─── numeric precision ───────────────────────────────────────────────

def assert_money(actual: Any, expected: float, label: str = "amount") -> None:
    """Money is carried to two decimal places."""
    assert isinstance(actual, (int, float)), f"{label} must be numeric, got {actual!r}"
    assert round(float(actual), 2) == round(float(expected), 2), (
        f"{label}: expected {expected:.2f}, got {actual}"
    )
    assert round(float(actual), 2) == float(actual), (
        f"{label} carries more than two decimal places: {actual}"
    )


def assert_ratio(actual: Any, expected: float, label: str = "ratio") -> None:
    """Performance ratios and score components are carried to four decimals."""
    assert isinstance(actual, (int, float)), f"{label} must be numeric, got {actual!r}"
    assert round(float(actual), 4) == round(float(expected), 4), (
        f"{label}: expected {expected:.4f}, got {actual}"
    )
    assert round(float(actual), 4) == float(actual), (
        f"{label} carries more than four decimal places: {actual}"
    )


def assert_score(actual: Any, expected: float, label: str = "quality_score") -> None:
    """A service-quality score is carried to two decimal places."""
    assert_money(actual, expected, label)


def assert_one_decimal(actual: Any, expected: float, label: str = "value") -> None:
    """driving_miles_to_nearest_hub and annual_block_hours carry one decimal."""
    assert isinstance(actual, (int, float)), f"{label} must be numeric, got {actual!r}"
    assert round(float(actual), 1) == round(float(expected), 1), (
        f"{label}: expected {expected:.1f}, got {actual}"
    )


def assert_instant(actual: Any, expected: str, label: str = "instant") -> None:
    """Compare two ISO-8601 UTC instants ignoring sub-second formatting width."""
    assert isinstance(actual, str), f"{label} must be a string, got {actual!r}"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


# ─── conservation identities ─────────────────────────────────────────

def assert_obligation_identity(agreement: Dict[str, Any]) -> None:
    """obligated_remaining_usd + disbursed_to_date_usd == total_committed_usd."""
    remaining = float(agreement["obligated_remaining_usd"])
    disbursed = float(agreement["disbursed_to_date_usd"])
    committed = float(agreement["total_committed_usd"])
    assert round(remaining + disbursed, 2) == round(committed, 2), (
        f"Obligation identity violated: {remaining} + {disbursed} != {committed}"
    )


def assert_departure_identity(agreement: Dict[str, Any]) -> None:
    """cumulative_scheduled == completed + cancelled_carrier + cancelled_weather."""
    scheduled = agreement["cumulative_scheduled_departures"]
    parts = (
        agreement["cumulative_completed_departures"]
        + agreement["cumulative_cancelled_carrier_departures"]
        + agreement["cumulative_cancelled_weather_departures"]
    )
    assert scheduled == parts, (
        f"Departure identity violated: scheduled {scheduled} != sum {parts}"
    )


def assert_period_balanced(period: Dict[str, Any]) -> None:
    """completed + cancelled_carrier + cancelled_weather == scheduled."""
    total = (
        period["completed_departures"]
        + period["cancelled_carrier_departures"]
        + period["cancelled_weather_departures"]
    )
    assert total == period["scheduled_departures"], (
        f"Period does not balance: {total} != {period['scheduled_departures']}"
    )
    assert period["passengers_enplaned"] <= period["seats_offered"], (
        "passengers_enplaned may not exceed seats_offered"
    )


# ─── list ordering and pagination ────────────────────────────────────

def assert_pagination_meta(meta: Dict[str, Any], limit: int, offset: int,
                           total_count: int, has_more: bool) -> None:
    assert meta["limit"] == limit, f"Expected limit {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"Expected offset {offset}, got {meta['offset']}"
    assert meta["total_count"] == total_count, (
        f"Expected total_count {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"Expected has_more {has_more}, got {meta['has_more']}"
    )


def assert_ordered_by(rows: Sequence[Dict[str, Any]], field: str,
                      ascending: bool = True) -> None:
    values = [row[field] for row in rows]
    expected = sorted(values, reverse=not ascending)
    assert values == expected, (
        f"Rows are not ordered by {field} "
        f"{'ASC' if ascending else 'DESC'}: {values}"
    )


def assert_id_sequence(rows: Sequence[Dict[str, Any]], expected_ids: List[str]) -> None:
    actual = [row["id"] for row in rows]
    assert actual == list(expected_ids), (
        f"Expected id order {expected_ids}, got {actual}"
    )
