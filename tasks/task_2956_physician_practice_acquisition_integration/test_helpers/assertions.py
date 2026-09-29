"""Domain assertions for the Practice Acquisition Integration API.

Covers the shapes the PRD pins: the common field block, the three-fractional-digit
instant rendering, money as integer cents, basis points as integers, percentages
carried to exactly two decimals, and the two acquisition ledger identities.
"""

import re
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import requests

from prd_bench_local_runner.testing import is_valid_uuid, validate_paginated

from .api_client import canonical_instant

Entity = Dict[str, Any]

_THREE_FRACTION_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --- Envelope / list helpers ------------------------------------------------


def validate_unpaginated_list(response: requests.Response) -> List[Entity]:
    """Validate a list response without asserting any pagination metadata.

    Use where a test only cares about the rows themselves; use
    `validate_paginated` where the test is about `total_count`, `has_more`,
    `limit` or `offset`.
    """
    assert response.status_code == 200, (
        f"Expected 200 for list response, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert "data" in body, "Missing 'data' in list envelope"
    assert isinstance(body["data"], list), "list endpoint 'data' must be a JSON array"
    assert body.get("response_type") == "array", (
        f"Expected response_type 'array', got '{body.get('response_type')}'"
    )
    return body["data"]


def list_rows_and_meta(response: requests.Response) -> Tuple[List[Entity], Dict[str, Any]]:
    """Paginated list access: returns (rows, meta)."""
    return validate_paginated(response)


def assert_total_count(response: requests.Response, expected: int) -> List[Entity]:
    rows, meta = validate_paginated(response)
    assert meta["total_count"] == expected, (
        f"Expected total_count {expected}, got {meta['total_count']}"
    )
    return rows


def assert_has_more(response: requests.Response, expected: bool) -> None:
    _rows, meta = validate_paginated(response)
    assert meta["has_more"] is expected, (
        f"Expected has_more {expected}, got {meta['has_more']}"
    )


def ids_of(rows: Iterable[Entity]) -> List[str]:
    return [row["id"] for row in rows]


def assert_contains_id(rows: Iterable[Entity], entity_id: str) -> None:
    found = ids_of(rows)
    assert entity_id in found, f"Expected {entity_id} among {found}"


def assert_excludes_id(rows: Iterable[Entity], entity_id: str) -> None:
    found = ids_of(rows)
    assert entity_id not in found, f"Did not expect {entity_id} among {found}"


def assert_ordered_by_created_at(rows: Sequence[Entity]) -> None:
    stamps = [canonical_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), f"Rows are not ordered by created_at ascending: {stamps}"


# --- Common fields ----------------------------------------------------------


def assert_instant_format(value: Any, label: str = "timestamp") -> None:
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert _THREE_FRACTION_INSTANT.match(value), (
        f"{label} must be an ISO 8601 UTC instant with exactly three fractional "
        f"digits, got {value!r}"
    )


def assert_date_only(value: Any, label: str = "date") -> None:
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert _DATE_ONLY.match(value), f"{label} must be a YYYY-MM-DD date, got {value!r}"


def assert_instant_equals(actual: Any, expected: str, label: str = "timestamp") -> None:
    """Compare two instants without letting sub-second width decide the result."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def assert_common_fields(entity: Entity, expected_version: Optional[int] = None) -> None:
    """Assert the id / created_at / updated_at / version block."""
    assert is_valid_uuid(entity.get("id")), (
        f"id must be a server-generated UUID with no prefix, got {entity.get('id')!r}"
    )
    assert_instant_format(entity.get("created_at"), "created_at")
    assert_instant_format(entity.get("updated_at"), "updated_at")
    assert isinstance(entity.get("version"), int), (
        f"version must be an integer, got {entity.get('version')!r}"
    )
    assert entity["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"Expected version {expected_version}, got {entity['version']}"
        )


def assert_report_common_fields(report: Entity) -> None:
    """Performance reports carry only `id` and `created_at`."""
    assert is_valid_uuid(report.get("id")), f"id must be a UUID, got {report.get('id')!r}"
    assert_instant_format(report.get("created_at"), "created_at")
    assert "updated_at" not in report, (
        "performance reports carry no updated_at field"
    )
    assert "version" not in report, "performance reports carry no version field"


def assert_version_bumped_by(before: Entity, after: Entity, delta: int = 1) -> None:
    assert after["version"] == before["version"] + delta, (
        f"Expected version {before['version'] + delta}, got {after['version']}"
    )


def assert_version_unchanged(before: Entity, after: Entity) -> None:
    assert after["version"] == before["version"], (
        f"Expected version to stay {before['version']}, got {after['version']}"
    )


# --- Money, basis points, percentages --------------------------------------


def assert_money_cents(value: Any, label: str = "money field") -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )


def assert_money_equals(actual: Any, expected: int, label: str = "money field") -> None:
    assert_money_cents(actual, label)
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_bps(value: Any, label: str = "basis point field") -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of basis points, got {value!r}"
    )


def assert_two_decimal_percentage(value: Any, label: str = "percentage") -> None:
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be numeric, got {value!r}"
    )
    quantised = Decimal(str(value)).quantize(Decimal("0.01"))
    assert Decimal(str(value)) == quantised, (
        f"{label} must carry exactly two decimal places, got {value!r}"
    )


def assert_percentage_equals(actual: Any, expected: float, label: str = "percentage") -> None:
    assert_two_decimal_percentage(actual, label)
    assert Decimal(str(actual)) == Decimal(str(expected)), (
        f"{label}: expected {expected}, got {actual}"
    )


# --- Acquisition ledgers ----------------------------------------------------


def assert_retention_pool(
    acquisition: Entity, total: int, committed: int, available: int
) -> None:
    assert_money_equals(
        acquisition["retention_pool_total_cents"], total, "retention_pool_total_cents"
    )
    assert_money_equals(
        acquisition["retention_pool_committed_cents"],
        committed,
        "retention_pool_committed_cents",
    )
    assert_money_equals(
        acquisition["retention_pool_available_cents"],
        available,
        "retention_pool_available_cents",
    )
    assert available == total - committed, (
        "retention_pool_available_cents must equal total minus committed"
    )


def assert_escrow(acquisition: Entity, total: int, committed: int, available: int) -> None:
    assert_money_equals(acquisition["escrow_total_cents"], total, "escrow_total_cents")
    assert_money_equals(
        acquisition["escrow_committed_cents"], committed, "escrow_committed_cents"
    )
    assert_money_equals(
        acquisition["escrow_available_cents"], available, "escrow_available_cents"
    )
    assert available == total - committed, (
        "escrow_available_cents must equal total minus committed"
    )


def assert_consideration_all_null(acquisition: Entity) -> None:
    for field in (
        "purchase_price_cents",
        "integration_reserve_cents",
        "gross_consideration_cents",
        "synergy_credit_bps",
        "synergy_credit_cents",
        "net_consideration_cents",
    ):
        assert acquisition[field] is None, f"{field} must be null, got {acquisition[field]!r}"


def assert_consideration_chain(
    acquisition: Entity,
    purchase_price_cents: int,
    integration_reserve_cents: int,
    gross_consideration_cents: int,
    synergy_credit_bps: int,
    synergy_credit_cents: int,
    net_consideration_cents: int,
) -> None:
    assert_money_equals(
        acquisition["purchase_price_cents"], purchase_price_cents, "purchase_price_cents"
    )
    assert_money_equals(
        acquisition["integration_reserve_cents"],
        integration_reserve_cents,
        "integration_reserve_cents",
    )
    assert_money_equals(
        acquisition["gross_consideration_cents"],
        gross_consideration_cents,
        "gross_consideration_cents",
    )
    assert_bps(acquisition["synergy_credit_bps"], "synergy_credit_bps")
    assert acquisition["synergy_credit_bps"] == synergy_credit_bps, (
        f"Expected synergy_credit_bps {synergy_credit_bps}, "
        f"got {acquisition['synergy_credit_bps']}"
    )
    assert_money_equals(
        acquisition["synergy_credit_cents"], synergy_credit_cents, "synergy_credit_cents"
    )
    assert_money_equals(
        acquisition["net_consideration_cents"],
        net_consideration_cents,
        "net_consideration_cents",
    )
    assert (
        acquisition["net_consideration_cents"]
        == acquisition["gross_consideration_cents"] - acquisition["synergy_credit_cents"]
    ), "net_consideration_cents must equal gross minus the synergy credit"


# --- Generic field helpers -------------------------------------------------


def assert_fields_null(entity: Entity, *fields: str) -> None:
    for field in fields:
        assert entity[field] is None, f"{field} must be null, got {entity[field]!r}"


def assert_status(entity: Entity, expected: str, field: str = "status") -> None:
    assert entity[field] == expected, (
        f"Expected {field} {expected}, got {entity[field]!r}"
    )
