"""
Domain assertion helpers.

Every helper here takes an **already-unwrapped** resource dict — the value the
generic validators return out of the envelope's ``data`` member — and never
indexes ``["data"]`` itself. See the module docstring of ``api_client`` for the
single envelope decision this suite makes.
"""

import re
from typing import Any, Dict, Iterable, List, Optional

import pytest
from prd_bench_local_runner.testing import is_valid_uuid

from .api_client import canonical_instant
from .constants import (
    ENTRY_KIND_FINAL_SEGMENT,
    ENTRY_KIND_PROVISIONAL,
)

# PRD 2.4: "a ``created_at`` timestamp rendered as an ISO 8601 UTC instant with
# exactly three fractional digits (for example ``2026-08-01T00:00:00.000Z``)".
_THREE_DIGIT_INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

# Money fields the PRD declares as "whole-cent integers, never decimals and
# never strings" (PRD 2.7).
CENTS_FIELDS = frozenset(
    {
        "observation_cost_budget_cents",
        "observed_cost_to_date_cents",
        "hourly_rate_cents",
        "provisional_cost_cents",
        "final_cost_cents",
        "amount_cents",
        "subtotal_cents",
        "coverage_surcharge_cents",
        "charge_total_cents",
        "budget_increase_cents",
    }
)

# Fields the PRD declares as carrying "exactly one decimal place" (PRD 2.7).
ONE_DECIMAL_FIELDS = frozenset(
    {
        "elopement_risk_score",
        "score_before",
        "score_after",
        "acuity_weight",
        "active_acuity_weight",
    }
)

_INSTANT_SUFFIXES = ("_at", "_on", "_utc")


def assert_three_fractional_digits(value: str, label: str = "timestamp") -> None:
    """Assert an instant is rendered with exactly three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert _THREE_DIGIT_INSTANT_RE.match(value), (
        f"{label} must be an ISO 8601 UTC instant with exactly three fractional "
        f"digits, got {value!r}"
    )


def assert_instant(actual: Any, expected: Any, label: str = "instant") -> None:
    """Compare two instants after canonicalising both to the PRD's rendering."""
    if expected is None:
        assert actual is None, f"{label} must be null, got {actual!r}"
        return
    assert actual is not None, f"{label} must be {expected!r}, got null"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {canonical_instant(expected)}, got {actual!r}"
    )


def assert_one_decimal(value: Any, label: str) -> None:
    """Assert a score/weight carries at most one decimal place."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be numeric, got {value!r}"
    )
    assert round(float(value), 1) == pytest.approx(float(value), abs=1e-9), (
        f"{label} must carry exactly one decimal place, got {value!r}"
    )


def assert_cents(value: Any, label: str) -> None:
    """Assert a money field is a whole-cent integer, not a decimal and not a string."""
    assert not isinstance(value, str), (
        f"{label} must be an integer count of cents, never a string; got {value!r}"
    )
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer count of cents, got {value!r}"
    )


def assert_field(row: Dict[str, Any], key: str, expected: Any, label: str = "") -> None:
    """
    Compare one field of a resource against its expected value, applying the
    precision contract the PRD declares for that field's kind.
    """
    prefix = f"{label}." if label else ""
    assert key in row, f"{prefix}{key} missing from {sorted(row)}"
    actual = row[key]

    if key in CENTS_FIELDS and expected is not None:
        assert_cents(actual, f"{prefix}{key}")
        assert actual == expected, f"{prefix}{key}: expected {expected}, got {actual}"
        return

    if key in ONE_DECIMAL_FIELDS and expected is not None:
        assert_one_decimal(actual, f"{prefix}{key}")
        assert float(actual) == pytest.approx(float(expected), abs=0.01), (
            f"{prefix}{key}: expected {expected}, got {actual}"
        )
        return

    if key.endswith(_INSTANT_SUFFIXES):
        assert_instant(actual, expected, f"{prefix}{key}")
        return

    if isinstance(expected, float):
        assert float(actual) == pytest.approx(expected, abs=0.01), (
            f"{prefix}{key}: expected {expected}, got {actual}"
        )
        return

    if isinstance(expected, list) and isinstance(actual, list):
        assert sorted(actual, key=str) == sorted(expected, key=str), (
            f"{prefix}{key}: expected {expected}, got {actual}"
        )
        return

    assert actual == expected, f"{prefix}{key}: expected {expected!r}, got {actual!r}"


def assert_fields(row: Dict[str, Any], label: str = "", **expected: Any) -> None:
    """Assert a batch of fields on one resource."""
    for key, value in expected.items():
        assert_field(row, key, value, label)


def assert_absent(row: Dict[str, Any], *keys: str, label: str = "") -> None:
    """Assert a resource does not carry the named fields at all."""
    prefix = f"{label} " if label else ""
    for key in keys:
        assert key not in row, (
            f"{prefix}must not carry a {key!r} field at all; got {sorted(row)}"
        )


def assert_common_fields(row: Dict[str, Any], label: str = "resource") -> None:
    """
    Assert the four common properties PRD 2.4 requires of every entity except the
    reassessment record: a UUID ``id`` with no type prefix, a three-fractional-digit
    ``created_at``, an ``updated_at``, and an integer ``version`` starting at 1.
    """
    assert "id" in row, f"{label} missing id"
    assert is_valid_uuid(row["id"]), (
        f"{label}.id must be a UUID with no type prefix, got {row['id']!r}"
    )
    assert_three_fractional_digits(row.get("created_at"), f"{label}.created_at")
    assert_three_fractional_digits(row.get("updated_at"), f"{label}.updated_at")
    assert isinstance(row.get("version"), int) and not isinstance(row["version"], bool), (
        f"{label}.version must be an integer, got {row.get('version')!r}"
    )
    assert row["version"] >= 1, f"{label}.version starts at 1, got {row['version']}"


def assert_reassessment_common_fields(row: Dict[str, Any]) -> None:
    """
    The reassessment record's own shape: PRD 2.4 says "it carries only ``id`` and
    ``created_at``. It has no ``updated_at`` and no ``version`` field at all".
    """
    assert "id" in row, "reassessment missing id"
    assert is_valid_uuid(row["id"]), (
        f"reassessment.id must be a UUID with no type prefix, got {row['id']!r}"
    )
    assert_three_fractional_digits(row.get("created_at"), "reassessment.created_at")
    assert_absent(row, "updated_at", "version", label="a Reassessment")


def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """
    Assert the envelope ``meta`` block PRD 2.2 declares: an ``api_request_id``
    "that starts with ``req_``" and an ``api_request_timestamp`` that is "a
    server-generated ISO 8601 UTC timestamp with three fractional digits".
    """
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert_three_fractional_digits(
        meta.get("api_request_timestamp"), "meta.api_request_timestamp"
    )


def assert_version_is(row: Dict[str, Any], expected: int, label: str = "resource") -> None:
    """Assert an exact version, for the places the PRD pins a mutation count."""
    assert row.get("version") == expected, (
        f"{label}.version: expected {expected}, got {row.get('version')}"
    )


# ─── Collection helpers ───────────────────────────────

def rows_where(rows: Iterable[Dict[str, Any]], **filters: Any) -> List[Dict[str, Any]]:
    """Every row matching all the given field values."""
    return [
        row
        for row in rows
        if all(row.get(key) == value for key, value in filters.items())
    ]


def exactly_one(rows: Iterable[Dict[str, Any]], **filters: Any) -> Dict[str, Any]:
    """The single row matching all the given field values; fails otherwise."""
    matches = rows_where(rows, **filters)
    assert len(matches) == 1, (
        f"Expected exactly one row matching {filters}, found {len(matches)}"
    )
    return matches[0]


def assert_row_count(rows: List[Dict[str, Any]], expected: int, label: str = "rows") -> None:
    assert len(rows) == expected, (
        f"Expected exactly {expected} {label}, got {len(rows)}"
    )


def assert_created_at_ascending(rows: List[Dict[str, Any]], label: str = "rows") -> None:
    """
    PRD 2.3: "list results are sorted by ``created_at`` in ascending order".
    """
    stamps = [canonical_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), f"{label} are not in ascending created_at order"


# ─── Ledger helpers (PRD 2.10) ────────────────────────

def posted_total(rows: Iterable[Dict[str, Any]]) -> int:
    """
    The sum PRD 2.10 defines: "the sum of ``amount_cents`` across every
    ``CostEntry`` ... whose ``status`` is ``POSTED``".
    """
    from .constants import COST_POSTED

    return sum(row["amount_cents"] for row in rows if row["status"] == COST_POSTED)


def provisional_row(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """The single PROVISIONAL ledger row of an assignment."""
    return exactly_one(rows, entry_kind=ENTRY_KIND_PROVISIONAL)


def final_segment_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """An assignment's FINAL_SEGMENT rows, in ascending segment_index."""
    segments = rows_where(rows, entry_kind=ENTRY_KIND_FINAL_SEGMENT)
    return sorted(segments, key=lambda row: row["segment_index"])
