"""Domain assertions for the SafeSport compliance platform.

These wrap the checks that recur across the suite: the four common fields that
PRD 2.4 puts on every resource, the integer-cents discipline of PRD 2.7, the
two-decimal score representation, and the deterministic list orderings of
PRD 2.3.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant


def assert_common_fields(resource: Dict[str, Any]) -> None:
    """Every resource carries id, created_at, updated_at and version (PRD 2.4)."""
    assert is_valid_uuid(resource.get("id")), f"id is not a UUID: {resource.get('id')}"
    assert is_iso8601_timestamp(
        resource.get("created_at")
    ), f"created_at is not ISO 8601: {resource.get('created_at')}"
    assert is_iso8601_timestamp(
        resource.get("updated_at")
    ), f"updated_at is not ISO 8601: {resource.get('updated_at')}"
    assert isinstance(resource.get("version"), int) and not isinstance(
        resource.get("version"), bool
    ), f"version is not an integer: {resource.get('version')}"
    assert resource["version"] >= 1, f"version starts at 1, got {resource['version']}"


def assert_created_version_is_one(resource: Dict[str, Any]) -> None:
    """A freshly created resource is at version 1 (PRD 2.4)."""
    assert_common_fields(resource)
    assert resource["version"] == 1, f"expected version 1, got {resource['version']}"


def assert_integer_cents(resource: Dict[str, Any], *fields: str) -> None:
    """Monetary fields are integers counting cents, never strings (PRD 2.7)."""
    for field in fields:
        value = resource.get(field)
        assert isinstance(value, int) and not isinstance(
            value, bool
        ), f"{field} must be an integer number of cents, got {value!r}"


def assert_money_equals(resource: Dict[str, Any], field: str, expected: int) -> None:
    """A monetary field equals the expected integer number of cents (PRD 2.7)."""
    assert_integer_cents(resource, field)
    assert resource[field] == expected, (
        f"{field} expected {expected} cents, got {resource[field]} cents"
    )


def assert_score_equals(actual: Any, expected: str) -> None:
    """Scores carry exactly two decimal places (PRD 2.7)."""
    assert actual is not None, f"expected score {expected}, got None"
    got = Decimal(str(actual)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    want = Decimal(expected)
    assert got == want, f"expected score {want}, got {actual!r}"


def assert_instant_equals(actual: Any, expected: str) -> None:
    """Two ISO 8601 instants denote the same moment (PRD 2.2)."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"expected instant {expected}, got {actual!r}"
    )


def assert_version_is(resource: Dict[str, Any], expected: int) -> None:
    """The optimistic-concurrency counter has the expected value (PRD 2.4)."""
    assert resource.get("version") == expected, (
        f"expected version {expected}, got {resource.get('version')}"
    )


def ids_of(rows: Iterable[Dict[str, Any]]) -> List[str]:
    """Project a list payload onto its resource ids, order preserved."""
    return [row["id"] for row in rows]


def assert_id_order(rows: Sequence[Dict[str, Any]], expected_ids: Sequence[str]) -> None:
    """A list endpoint returned exactly these resources in exactly this order (PRD 2.3)."""
    assert ids_of(rows) == list(expected_ids), (
        f"expected ids {list(expected_ids)}, got {ids_of(rows)}"
    )


def assert_ascending_by(rows: Sequence[Dict[str, Any]], field: str) -> None:
    """Rows are non-decreasing on the given field (PRD 2.3 default ordering)."""
    values = [canonical_instant(row.get(field)) for row in rows]
    assert values == sorted(values), f"{field} is not ascending: {values}"


def assert_descending_by(rows: Sequence[Dict[str, Any]], field: str) -> None:
    """Rows are non-increasing on the given field (PRD 2.3 deviating ordering)."""
    values = [canonical_instant(row.get(field)) for row in rows]
    assert values == sorted(values, reverse=True), (
        f"{field} is not descending: {values}"
    )


def assert_pagination_meta(
    meta: Dict[str, Any],
    *,
    total: Optional[int] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> None:
    """The pagination block reports the window the caller asked for (PRD 2.3)."""
    for key in ("total_count", "limit", "offset", "has_more"):
        assert key in meta, f"pagination meta is missing {key}: {meta}"
    if total is not None:
        assert meta["total_count"] == total, (
            f"expected total_count {total}, got {meta['total_count']}"
        )
    if limit is not None:
        assert meta["limit"] == limit, f"expected limit {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"expected offset {offset}, got {meta['offset']}"
    if total is not None and limit is not None and offset is not None:
        assert bool(meta["has_more"]) is (offset + limit < total), (
            f"has_more {meta['has_more']} disagrees with total_count={total} "
            f"limit={limit} offset={offset}"
        )


def assert_state(resource: Dict[str, Any], field: str, expected: str) -> None:
    """A lifecycle field holds the expected state name."""
    assert resource.get(field) == expected, (
        f"expected {field} == {expected}, got {resource.get(field)!r}"
    )


def assert_counters(resource: Dict[str, Any], **expected: int) -> None:
    """Derived integer counters hold their expected values (PRD 2.7)."""
    for field, want in expected.items():
        got = resource.get(field)
        assert isinstance(got, int) and not isinstance(got, bool), (
            f"{field} must be an integer counter, got {got!r}"
        )
        assert got == want, f"expected {field} == {want}, got {got}"


def assert_escrow_conservation(
    club: Dict[str, Any], screening_orders: Iterable[Dict[str, Any]]
) -> None:
    """The balance plus every live order's charge equals total_funded_cents (PRD 2.12).

    Only orders in ``ORDERED``, ``RESULT_RETURNED`` or ``ADJUDICATED`` enter the
    sum; a ``VOIDED`` order keeps its ``charged_cents`` on the row but drops out.
    """
    assert_integer_cents(club, "escrow_balance_cents", "total_funded_cents")
    live_statuses = ("ORDERED", "RESULT_RETURNED", "ADJUDICATED")
    outstanding = sum(
        order["charged_cents"]
        for order in screening_orders
        if order.get("status") in live_statuses
    )
    assert club["escrow_balance_cents"] + outstanding == club["total_funded_cents"], (
        "escrow conservation broken: balance="
        f"{club['escrow_balance_cents']} + outstanding={outstanding} != funded="
        f"{club['total_funded_cents']}"
    )


def assert_finding_partition(audit: Dict[str, Any], written_findings: int) -> None:
    """finding_total_count splits exactly into open, remediated and waived (PRD 2.12)."""
    assert_counters(audit, finding_total_count=written_findings)
    parts = (
        audit["open_finding_count"]
        + audit["remediated_finding_count"]
        + audit["waived_finding_count"]
    )
    assert parts == audit["finding_total_count"], (
        "finding partition broken: open="
        f"{audit['open_finding_count']} remediated="
        f"{audit['remediated_finding_count']} waived="
        f"{audit['waived_finding_count']} total={audit['finding_total_count']}"
    )
