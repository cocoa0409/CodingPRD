"""Domain assertions for the Dam Safety API.

Thin wrappers over the shared structural helpers, plus comparisons tuned to the
precision rules the PRD declares: money in whole cents, consequence score and
freeboard to two decimals, acre-feet to three decimals.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .api_client import canonical_instant
from .constants import (
    COMPLIANCE_SUMMARY_FIELDS,
    PENALTY_PREVIEW_FIELDS,
    SWEEP_RESULT_FIELDS,
)


# ---------------------------------------------------------------------------
# Identity / envelope structure
# ---------------------------------------------------------------------------
def assert_server_minted_id(row: dict) -> str:
    """Every stored row carries a server-minted uuid ``id``."""
    row_id = row.get("id")
    assert is_valid_uuid(row_id), f"id is not a server-minted uuid: {row_id!r}"
    return row_id


def assert_created_at(row: dict) -> str:
    """Every stored row carries an ISO-8601 ``created_at``."""
    created_at = row.get("created_at")
    assert is_iso8601_timestamp(created_at), (
        f"created_at is not an ISO-8601 instant: {created_at!r}"
    )
    return created_at


def assert_versioned_row(row: dict, expected_version: Optional[int] = None) -> int:
    """A versioned row exposes ``updated_at`` and an integer ``version``."""
    assert is_iso8601_timestamp(row.get("updated_at")), (
        f"updated_at is not an ISO-8601 instant: {row.get('updated_at')!r}"
    )
    version = row.get("version")
    assert isinstance(version, int), f"version must be an integer, got {version!r}"
    if expected_version is not None:
        assert version == expected_version, (
            f"expected version {expected_version}, got {version}"
        )
    return version


def assert_append_only_row(row: dict) -> None:
    """Append-only rows carry ``id`` and ``created_at`` and no version field."""
    assert_server_minted_id(row)
    assert_created_at(row)
    assert "version" not in row, "append-only row must not expose a version field"
    assert "updated_at" not in row, "append-only row must not expose updated_at"


def assert_exact_fields(payload: dict, expected: Iterable[str]) -> None:
    """The payload's key set is exactly ``expected``."""
    assert set(payload.keys()) == set(expected), (
        f"unexpected field set\n  extra: {sorted(set(payload) - set(expected))}"
        f"\n  missing: {sorted(set(expected) - set(payload))}"
    )


def assert_compliance_summary_shape(summary: dict) -> None:
    assert_exact_fields(summary, COMPLIANCE_SUMMARY_FIELDS)


def assert_penalty_preview_shape(preview: dict) -> None:
    assert_exact_fields(preview, PENALTY_PREVIEW_FIELDS)


def assert_sweep_result_shape(result: dict) -> None:
    assert_exact_fields(result, SWEEP_RESULT_FIELDS)


# ---------------------------------------------------------------------------
# Instants
# ---------------------------------------------------------------------------
def assert_instant(actual: Any, expected: str, label: str = "instant") -> None:
    """Compare two instants ignoring sub-second trailing-zero differences."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_null(value: Any, label: str = "field") -> None:
    assert value is None, f"{label}: expected null, got {value!r}"


# ---------------------------------------------------------------------------
# Numeric precision
# ---------------------------------------------------------------------------
def assert_cents(actual: Any, expected: int, label: str = "amount_cents") -> None:
    """Money is expressed in whole integer cents."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


def assert_decimal(actual: Any, expected: float, places: int, label: str) -> None:
    """Compare a decimal quantity at the PRD's declared precision."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be numeric, got {actual!r}"
    )
    assert round(float(actual), places) == round(float(expected), places), (
        f"{label}: expected {expected} (at {places}dp), got {actual}"
    )


def assert_score(actual: Any, expected: float, label: str = "consequence score") -> None:
    """Consequence scores are carried to two decimal places."""
    assert_decimal(actual, expected, 2, label)


def assert_freeboard(actual: Any, expected: float, label: str = "freeboard_ft") -> None:
    """Freeboard is carried to two decimal places."""
    assert_decimal(actual, expected, 2, label)


def assert_acre_feet(actual: Any, expected: float, label: str = "acre-feet") -> None:
    """Acre-foot volumes are carried to three decimal places."""
    assert_decimal(actual, expected, 3, label)


def assert_cfs(actual: Any, expected: float, label: str = "cfs") -> None:
    assert_decimal(actual, expected, 3, label)


# ---------------------------------------------------------------------------
# Ordering / listing
# ---------------------------------------------------------------------------
def assert_created_at_ascending(rows: list[dict]) -> None:
    """Collections are ordered by ``created_at`` ascending."""
    stamps = [canonical_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), f"rows are not ordered by created_at ASC: {stamps}"


def assert_ids_in_order(rows: list[dict], expected_ids: list[str]) -> None:
    assert [row["id"] for row in rows] == list(expected_ids), (
        f"expected ids {expected_ids}, got {[row['id'] for row in rows]}"
    )


def assert_total_count(meta: dict, expected: int) -> None:
    assert meta["total_count"] == expected, (
        f"expected total_count {expected}, got {meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# Storage conservation invariant
# ---------------------------------------------------------------------------
def assert_storage_conservation(dam: dict) -> None:
    """Committed drawdown plus available conservation storage equals gross storage."""
    committed = float(dam["committed_drawdown_acre_ft"])
    available = float(dam["available_conservation_storage_acre_ft"])
    gross = float(dam["gross_storage_acre_ft"])
    assert round(committed + available, 3) == round(gross, 3), (
        f"conservation identity broken: {committed} + {available} != {gross}"
    )
