"""
Domain assertions for the State Fish Hatchery Stocking Program API.

These build on the generic structural helpers and add the checks this PRD makes
specific: the common record properties of section 2.7, the three station ledgers
of section 2.5 that must balance after every write, the fish-conservation
identity on a rearing lot, the declared decimal scales of section 2.9, and
instant comparison that tolerates only the fractional-digit width the PRD leaves
free.
"""

from typing import Any, Dict, List, Optional, Sequence

import requests
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant


# ─── Envelope helpers ─────────────────────────────────

def validate_unpaginated(response: requests.Response) -> list:
    """
    Validate a successful list response without requiring the pagination block.

    Used for list reads whose assertion is about ordering or membership only.
    Where a test is about paging itself, validate_paginated() is used instead so
    that `limit`, `offset`, `total_count` and `has_more` are all checked.
    """
    assert response.status_code == 200, (
        f"Expected 200 for a list read, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body.get("response_type") == "array", (
        f"Expected response_type 'array', got {body.get('response_type')!r}"
    )
    assert isinstance(body.get("data"), list), "List response 'data' must be an array"
    return body["data"]


def assert_error_meta_is_minimal(response: requests.Response) -> None:
    """
    PRD 2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    """
    meta = response.json()["meta"]
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"Error meta must carry only api_request_id and api_request_timestamp, "
        f"got {sorted(meta.keys())}"
    )


def assert_request_id_prefix(response: requests.Response) -> None:
    """PRD 2.2: the `api_request_id` "starts with `req_`"."""
    request_id = response.json()["meta"]["api_request_id"]
    assert request_id.startswith("req_"), (
        f"api_request_id must start with 'req_', got {request_id!r}"
    )


# ─── Common record properties (PRD 2.7) ───────────────

def assert_common_fields(record: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """
    Assert the common properties every record but a discharge sample carries: a
    UUID `id` with no type prefix, a `created_at`, an `updated_at`, and a
    `version` integer that begins at 1.
    """
    assert is_valid_uuid(record.get("id", "")), (
        f"'id' must be a UUID with no prefix, got {record.get('id')!r}"
    )
    assert is_iso8601_timestamp(record.get("created_at", "")), (
        f"'created_at' must be an ISO 8601 UTC instant, got {record.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(record.get("updated_at", "")), (
        f"'updated_at' must be an ISO 8601 UTC instant, got {record.get('updated_at')!r}"
    )
    assert isinstance(record.get("version"), int) and not isinstance(
        record.get("version"), bool
    ), f"'version' must be an integer, got {record.get('version')!r}"
    assert record["version"] >= 1, f"'version' begins at 1, got {record['version']}"
    if expected_version is not None:
        assert record["version"] == expected_version, (
            f"Expected version {expected_version}, got {record['version']}"
        )


def assert_no_revision_fields(record: Dict[str, Any]) -> None:
    """
    Assert the one documented exception of PRD 2.7: "a discharge sample carries
    only `id` and `created_at`. Discharge samples have neither `updated_at` nor
    `version`".
    """
    assert is_valid_uuid(record.get("id", "")), (
        f"'id' must be a UUID, got {record.get('id')!r}"
    )
    assert is_iso8601_timestamp(record.get("created_at", "")), (
        f"'created_at' must be an ISO 8601 UTC instant, got {record.get('created_at')!r}"
    )
    assert "version" not in record, "A discharge sample must not carry a 'version'"
    assert "updated_at" not in record, "A discharge sample must not carry an 'updated_at'"


# ─── Instants and numbers ─────────────────────────────

def assert_instant_equals(actual: Any, expected: str, field: str = "instant") -> None:
    """Compare two ISO 8601 UTC instants in the PRD's three-fractional-digit form."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{field}: expected {canonical_instant(expected)}, got {actual!r}"
    )


def assert_instant_format(value: Any, field: str = "instant") -> None:
    """PRD 2.7: instants are ISO 8601 UTC timestamps with three fractional digits."""
    assert isinstance(value, str), f"{field} must be a string instant, got {value!r}"
    assert is_iso8601_timestamp(value), (
        f"{field} must be an ISO 8601 UTC instant, got {value!r}"
    )


def assert_number_equals(actual: Any, expected: float, places: int, field: str = "value") -> None:
    """
    Assert a numeric field equals the expected figure at the PRD's declared scale.

    The comparison is made on the value rounded to the declared number of decimal
    places so that binary floating-point representation never decides a test,
    while a value genuinely off at that place still fails.
    """
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{field} must be a number, got {actual!r}"
    )
    assert round(float(actual), places) == round(float(expected), places), (
        f"{field}: expected {expected} to {places} decimal places, got {actual}"
    )


def assert_integer_equals(actual: Any, expected: int, field: str = "value") -> None:
    """Assert an integer-valued field. Counts and cents are integers, always."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field} must be an integer, got {actual!r}"
    )
    assert actual == expected, f"{field}: expected {expected}, got {actual}"


def assert_decimal_places(value: Any, places: int, field: str = "value") -> None:
    """Assert a numeric field carries no more precision than the PRD declares."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be a number, got {value!r}"
    )
    assert round(float(value), places) == round(float(value), places + 6), (
        f"{field} carries more than {places} decimal places: {value}"
    )


def assert_is_none(value: Any, field: str = "value") -> None:
    assert value is None, f"{field} must be null, got {value!r}"


# ─── Station ledgers (PRD 2.5) ────────────────────────

def assert_water_right_ledger(hatchery: Dict[str, Any]) -> None:
    """
    PRD 2.5: "`water_available_af` is the `annual_water_right_af` minus
    `water_reserved_af` minus `water_used_af`, carried to four decimal places."
    """
    expected = (
        float(hatchery["annual_water_right_af"])
        - float(hatchery["water_reserved_af"])
        - float(hatchery["water_used_af"])
    )
    assert round(float(hatchery["water_available_af"]), 4) == round(expected, 4), (
        "Water-right ledger does not balance: "
        f"right={hatchery['annual_water_right_af']} "
        f"reserved={hatchery['water_reserved_af']} "
        f"used={hatchery['water_used_af']} "
        f"available={hatchery['water_available_af']}"
    )


def assert_appropriation_ledger(hatchery: Dict[str, Any]) -> None:
    """
    PRD 2.5: "`budget_available_cents` is `annual_budget_cents` minus
    `budget_committed_cents` minus `budget_spent_cents`."
    """
    expected = (
        int(hatchery["annual_budget_cents"])
        - int(hatchery["budget_committed_cents"])
        - int(hatchery["budget_spent_cents"])
    )
    assert int(hatchery["budget_available_cents"]) == expected, (
        "Appropriation ledger does not balance: "
        f"budget={hatchery['annual_budget_cents']} "
        f"committed={hatchery['budget_committed_cents']} "
        f"spent={hatchery['budget_spent_cents']} "
        f"available={hatchery['budget_available_cents']}"
    )


def assert_female_ledger(brood_stock: Dict[str, Any]) -> None:
    """
    PRD 3.2: "`females_available` — the `female_count` less the reserved and the
    spent".
    """
    expected = (
        int(brood_stock["female_count"])
        - int(brood_stock["females_reserved"])
        - int(brood_stock["females_spent"])
    )
    assert int(brood_stock["females_available"]) == expected, (
        "Female ledger does not balance: "
        f"count={brood_stock['female_count']} "
        f"reserved={brood_stock['females_reserved']} "
        f"spent={brood_stock['females_spent']} "
        f"available={brood_stock['females_available']}"
    )


def assert_fish_conservation(lot: Dict[str, Any], released_total: int = 0) -> None:
    """
    PRD 2.5: "a lot's `initial_count` always equals its `count_on_hand`, plus its
    `reserved_count`, plus its `cumulative_mortality_count`, plus the fish
    already released out of it."
    """
    total = (
        int(lot["count_on_hand"])
        + int(lot["reserved_count"])
        + int(lot["cumulative_mortality_count"])
        + int(released_total)
    )
    assert int(lot["initial_count"]) == total, (
        "Fish conservation identity broken: "
        f"initial={lot['initial_count']} on_hand={lot['count_on_hand']} "
        f"reserved={lot['reserved_count']} "
        f"mortality={lot['cumulative_mortality_count']} released={released_total}"
    )


# ─── Ordering (PRD 2.3) ───────────────────────────────

def assert_ascending_by(records: Sequence[Dict[str, Any]], key: str = "created_at") -> None:
    """PRD 2.3: "list endpoints return records in ascending `created_at` order"."""
    values = [canonical_instant(r[key]) for r in records]
    assert values == sorted(values), f"Records are not ascending by {key}: {values}"


def assert_descending_by(records: Sequence[Dict[str, Any]], key: str = "sampled_at") -> None:
    """PRD 2.3: the discharge-monitoring record "is returned newest sample first"."""
    values = [canonical_instant(r[key]) for r in records]
    assert values == sorted(values, reverse=True), (
        f"Records are not descending by {key}: {values}"
    )


def ids_of(records: Sequence[Dict[str, Any]]) -> List[str]:
    return [r["id"] for r in records]
