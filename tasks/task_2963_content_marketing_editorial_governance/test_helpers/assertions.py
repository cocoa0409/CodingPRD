"""
Domain assertions for the editorial governance API.

These wrap the shared structural helpers with the PRD's own vocabulary:
the envelope rules of section 2.2, the identity and timestamp rendering of
section 2.4, the pagination contract of section 2.3, the two-decimal
precision rule of section 2.7, the fixed collection orders of section 2.3,
and the nine-counter sweep tally of section 3.11.
"""

import re
from typing import Any, Dict, List, Optional, Sequence

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .constants import (
    DISTRIBUTION_CHANNEL_ORDER,
    GATE_FAN_OUT_ORDER,
    SWEEP_COUNTER_KEYS,
)

_THREE_FRACTIONAL_DIGITS = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)
_REQUEST_ID_PREFIX = "req_"

MONEY_TOLERANCE = 0
PCT_TOLERANCE = 0.005


# ─── Envelope (PRD 2.2) ───────────────────────────────

def assert_success_envelope(response, expected_status: int = 200) -> Any:
    """Validate the success envelope and return the ``data`` payload."""
    data = validate_success(response, expected_status)
    meta = response.json()["meta"]
    assert meta["api_request_id"].startswith(_REQUEST_ID_PREFIX), (
        f"meta.api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert_instant_precision(meta["api_request_timestamp"])
    return data


def assert_object_response(response, expected_status: int = 200) -> Dict[str, Any]:
    """A single-resource response carries ``response_type`` ``object``."""
    data = assert_success_envelope(response, expected_status)
    assert response.json()["response_type"] == "object", (
        f"Expected response_type 'object', got {response.json()['response_type']!r}"
    )
    return data


def assert_error_envelope_meta(response) -> None:
    """An error envelope's ``meta`` carries only the two request fields (PRD 2.2)."""
    meta = response.json()["meta"]
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"Error meta must hold exactly the two request fields, got {sorted(meta)}"
    )
    assert meta["api_request_id"].startswith(_REQUEST_ID_PREFIX)
    assert_instant_precision(meta["api_request_timestamp"])


# ─── Pagination (PRD 2.3) ─────────────────────────────

def assert_list_response(
    response,
    expected_total_count: Optional[int] = None,
    expected_has_more: Optional[bool] = None,
    expected_limit: Optional[int] = None,
    expected_offset: Optional[int] = None,
    expected_row_count: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Validate a collection response and its four pagination fields.

    Every list endpoint in this service reports ``limit``, ``offset``,
    ``total_count`` and ``has_more``, where ``total_count`` counts the rows
    matching the filters before the page window is applied.
    """
    rows, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array", (
        f"Expected response_type 'array', got {response.json()['response_type']!r}"
    )
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in meta, f"List meta missing '{field}'"
    if expected_total_count is not None:
        assert meta["total_count"] == expected_total_count, (
            f"Expected total_count {expected_total_count}, got {meta['total_count']}"
        )
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more, (
            f"Expected has_more {expected_has_more}, got {meta['has_more']}"
        )
    if expected_limit is not None:
        assert meta["limit"] == expected_limit
    if expected_offset is not None:
        assert meta["offset"] == expected_offset
    if expected_row_count is not None:
        assert len(rows) == expected_row_count, (
            f"Expected {expected_row_count} rows in the page, got {len(rows)}"
        )
    return rows


def assert_list_meta(response) -> Dict[str, Any]:
    """Return a validated list response's ``meta`` object."""
    _rows, meta = validate_paginated(response)
    return meta


# ─── Identity and timestamps (PRD 2.4) ────────────────

def assert_bare_uuid(value: str) -> None:
    """A resource ``id`` is a UUID string with no type prefix."""
    assert is_valid_uuid(value), f"Not a bare UUID identifier: {value!r}"


def assert_instant_precision(value: str) -> None:
    """Every rendered instant carries exactly three fractional digits."""
    assert is_iso8601_timestamp(value), f"Not an ISO 8601 UTC instant: {value!r}"
    assert _THREE_FRACTIONAL_DIGITS.match(value), (
        f"Instant must render three fractional digits, got {value!r}"
    )


def assert_mutable_row(row: Dict[str, Any]) -> None:
    """A mutable entity carries ``id``, ``created_at``, ``updated_at`` and ``version``."""
    assert_bare_uuid(row["id"])
    assert_instant_precision(row["created_at"])
    assert_instant_precision(row["updated_at"])
    assert isinstance(row["version"], int) and row["version"] >= 1, (
        f"version must be a positive integer, got {row.get('version')!r}"
    )


def assert_immutable_row(row: Dict[str, Any]) -> None:
    """
    An evidence row and a measurement period carry only ``id`` and ``created_at``.

    ``updated_at`` and ``version`` are absent from the response entirely.
    """
    assert_bare_uuid(row["id"])
    assert_instant_precision(row["created_at"])
    assert "updated_at" not in row, (
        f"Immutable row must not expose updated_at, got {row.get('updated_at')!r}"
    )
    assert "version" not in row, (
        f"Immutable row must not expose version, got {row.get('version')!r}"
    )


def assert_version(row: Dict[str, Any], expected: int) -> None:
    assert row["version"] == expected, (
        f"Expected version {expected}, got {row['version']}"
    )


# ─── Numeric precision (PRD 2.7) ──────────────────────

def assert_two_decimal_value(actual: Any, expected: float) -> None:
    """A decimal percentage or score is compared at two-decimal precision."""
    assert actual == pytest.approx(expected, abs=0.005), (
        f"Expected {expected:.2f}, got {actual}"
    )
    assert round(float(actual), 2) == pytest.approx(float(actual), abs=1e-9), (
        f"Value carries more than two decimal places: {actual}"
    )


def assert_integer_value(actual: Any, expected: int) -> None:
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"Expected an integer, got {actual!r} of type {type(actual).__name__}"
    )
    assert actual == expected, f"Expected {expected}, got {actual}"


# ─── Collection ordering (PRD 2.3) ────────────────────

def assert_ordered_by(
    rows: Sequence[Dict[str, Any]],
    key: str,
    descending: bool = False,
    tiebreak_key: Optional[str] = "id",
) -> None:
    """Assert a collection is sorted on ``key``, with an optional tie-breaker."""
    def sort_key(row: Dict[str, Any]):
        primary = row.get(key)
        if tiebreak_key is None:
            return (primary,)
        return (primary, row.get(tiebreak_key))

    expected = sorted(rows, key=sort_key, reverse=descending)
    assert [row["id"] for row in rows] == [row["id"] for row in expected], (
        f"Rows are not ordered by {key} "
        f"{'descending' if descending else 'ascending'}: "
        f"{[row.get(key) for row in rows]}"
    )


def assert_gate_dimension_order(gates: Sequence[Dict[str, Any]]) -> None:
    """Review gates come back in the order SME, LEGAL, BRAND, ACCESSIBILITY."""
    actual = [gate["gate_type"] for gate in gates]
    expected = [name for name in GATE_FAN_OUT_ORDER if name in actual]
    assert actual == expected, (
        f"Gates must follow the fixed dimension order {expected}, got {actual}"
    )


def assert_distribution_channel_order(rows: Sequence[Dict[str, Any]]) -> None:
    """Distribution rows come back in the order OWNED, EMAIL, SOCIAL."""
    actual = [row["channel"] for row in rows]
    expected = [name for name in DISTRIBUTION_CHANNEL_ORDER if name in actual]
    assert actual == expected, (
        f"Distributions must follow the fixed channel order {expected}, got {actual}"
    )


# ─── Entity shape assertions ──────────────────────────

def assert_campaign_counters(
    campaign: Dict[str, Any],
    breached_gate_count: int = 0,
    expired_usage_count: int = 0,
    unsubstantiated_published_claim_count: int = 0,
    committed_points_total: Optional[int] = None,
) -> None:
    """Assert the three governance counters and the commitment ledger."""
    assert campaign["breached_gate_count"] == breached_gate_count, (
        f"Expected breached_gate_count {breached_gate_count}, "
        f"got {campaign['breached_gate_count']}"
    )
    assert campaign["expired_usage_count"] == expired_usage_count, (
        f"Expected expired_usage_count {expired_usage_count}, "
        f"got {campaign['expired_usage_count']}"
    )
    assert (
        campaign["unsubstantiated_published_claim_count"]
        == unsubstantiated_published_claim_count
    ), (
        "Expected unsubstantiated_published_claim_count "
        f"{unsubstantiated_published_claim_count}, "
        f"got {campaign['unsubstantiated_published_claim_count']}"
    )
    if committed_points_total is not None:
        assert campaign["committed_points_total"] == committed_points_total, (
            f"Expected committed_points_total {committed_points_total}, "
            f"got {campaign['committed_points_total']}"
        )


def assert_posture(campaign: Dict[str, Any], expected: str) -> None:
    assert campaign["governance_posture"] == expected, (
        f"Expected governance_posture {expected}, "
        f"got {campaign['governance_posture']}"
    )


def assert_slot_commitment(
    slot: Dict[str, Any],
    committed_points: int,
    utilization_pct: float,
    status: Optional[str] = None,
) -> None:
    """Assert a slot's commitment, its two-decimal utilization and its status."""
    assert_integer_value(slot["committed_points"], committed_points)
    assert_two_decimal_value(slot["utilization_pct"], utilization_pct)
    if status is not None:
        assert slot["status"] == status, (
            f"Expected slot status {status}, got {slot['status']}"
        )


def assert_gate(
    gate: Dict[str, Any],
    gate_type: Optional[str] = None,
    state: Optional[str] = None,
    sla_hours: Optional[int] = None,
    due_at: Optional[str] = None,
    opened_at: Optional[str] = None,
    turnaround_hours: Optional[float] = None,
    sla_breached: Optional[bool] = None,
) -> None:
    """Assert the service-level and decision fields of one review gate."""
    if gate_type is not None:
        assert gate["gate_type"] == gate_type
    if state is not None:
        assert gate["state"] == state, (
            f"Expected {gate.get('gate_type')} gate in {state}, got {gate['state']}"
        )
    if sla_hours is not None:
        assert_integer_value(gate["sla_hours"], sla_hours)
    if due_at is not None:
        assert gate["due_at"] == due_at, (
            f"Expected due_at {due_at}, got {gate['due_at']}"
        )
    if opened_at is not None:
        assert gate["opened_at"] == opened_at
    if turnaround_hours is not None:
        assert_two_decimal_value(gate["turnaround_hours"], turnaround_hours)
    if sla_breached is not None:
        assert gate["sla_breached"] is sla_breached, (
            f"Expected sla_breached {sla_breached}, got {gate['sla_breached']}"
        )


def assert_asset_rights(
    asset: Dict[str, Any],
    status: Optional[str] = None,
    active_use_count: Optional[int] = None,
    remaining_licensed_uses: Optional[int] = None,
) -> None:
    if status is not None:
        assert asset["status"] == status, (
            f"Expected asset status {status}, got {asset['status']}"
        )
    if active_use_count is not None:
        assert_integer_value(asset["active_use_count"], active_use_count)
    if remaining_licensed_uses is not None:
        assert_integer_value(asset["remaining_licensed_uses"], remaining_licensed_uses)


# ─── Sweep tally (PRD 3.11) ───────────────────────────

def assert_sweep_tally(tally: Dict[str, Any], **expected: int) -> None:
    """
    Assert the nine-counter sweep tally.

    Every counter the caller does not name is expected to be 0, which is what
    makes a replayed sweep at an unmoved clock assertable in one call.
    """
    unknown = set(expected) - set(SWEEP_COUNTER_KEYS)
    assert not unknown, f"Unknown sweep counter(s): {sorted(unknown)}"
    for key in SWEEP_COUNTER_KEYS:
        assert key in tally, f"Sweep tally missing counter '{key}'"
        want = expected.get(key, 0)
        assert tally[key] == want, (
            f"Expected {key} {want}, got {tally[key]} (full tally: {tally})"
        )


def assert_no_op_sweep(tally: Dict[str, Any]) -> None:
    """A replayed sweep at an unmoved clock reports 0 for all nine counters."""
    assert_sweep_tally(tally)
