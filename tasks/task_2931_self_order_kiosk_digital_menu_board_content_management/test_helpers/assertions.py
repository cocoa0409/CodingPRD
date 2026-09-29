"""Domain assertion helpers.

These helpers operate on already-unwrapped payloads. The response envelope is
unwrapped by the framework validators (validate_success / validate_error /
validate_paginated / get_success_data) and never a second time here.
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant
from .types import JSON


# --- common resource properties ------------------------------------------
def assert_common_fields(entity: JSON, expect_version: Optional[int] = None) -> None:
    """Every resource except the audit trail carries id, created_at, updated_at, version."""
    assert is_valid_uuid(entity.get("id")), f"id is not a UUID: {entity.get('id')!r}"
    assert is_iso8601_timestamp(entity.get("created_at")), f"bad created_at: {entity!r}"
    assert is_iso8601_timestamp(entity.get("updated_at")), f"bad updated_at: {entity!r}"
    assert isinstance(entity.get("version"), int) and not isinstance(entity.get("version"), bool)
    assert entity["version"] >= 1, f"version must start at 1: {entity['version']!r}"
    if expect_version is not None:
        assert entity["version"] == expect_version, (
            f"expected version {expect_version}, got {entity['version']}"
        )


def assert_audit_row_shape(row: JSON) -> None:
    """An audit row carries only id and created_at: it has neither updated_at nor version."""
    assert is_valid_uuid(row.get("id")), f"audit id is not a UUID: {row.get('id')!r}"
    assert is_iso8601_timestamp(row.get("created_at")), f"bad audit created_at: {row!r}"
    assert "updated_at" not in row or row["updated_at"] is None
    assert "version" not in row or row["version"] is None


# --- money ---------------------------------------------------------------
def assert_money(actual: Any, expected: int, label: str = "amount") -> None:
    """All monetary amounts in this system are integers in minor units (cents)."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_money_fields(entity: JSON, **expected: int) -> None:
    for field, value in expected.items():
        assert_money(entity.get(field), value, field)


# --- instants ------------------------------------------------------------
def assert_instant_equals(actual: Optional[str], expected: Optional[str], label: str = "instant") -> None:
    """Compare two ISO-8601 UTC instants without depending on sub-second width."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


# --- generic field comparison -------------------------------------------
def assert_fields(entity: JSON, **expected: Any) -> None:
    """Assert a set of scalar fields on one payload, reporting every mismatch at once."""
    problems = []
    for field, value in expected.items():
        actual = entity.get(field)
        if actual != value:
            problems.append(f"{field}: expected {value!r}, got {actual!r}")
    assert not problems, "; ".join(problems)


def assert_state(entity: JSON, expected: str, field: str = "state") -> None:
    assert entity.get(field) == expected, (
        f"expected {field} {expected!r}, got {entity.get(field)!r}"
    )


# --- pagination ----------------------------------------------------------
def assert_meta(meta: JSON, total_count: Optional[int] = None, limit: Optional[int] = None,
                offset: Optional[int] = None, has_more: Optional[bool] = None) -> None:
    """List responses carry limit, offset, total_count and has_more inside meta."""
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"expected total_count {total_count}, got {meta['total_count']}"
        )
    if limit is not None:
        assert meta["limit"] == limit
    if offset is not None:
        assert meta["offset"] == offset
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"expected has_more {has_more}, got {meta['has_more']!r}"
        )


def ids_of(rows: Sequence[JSON]) -> List[str]:
    return [row["id"] for row in rows]


# --- audit trail ---------------------------------------------------------
def audit_rows_for(rows: Sequence[JSON], action: Optional[str] = None,
                   subject_kind: Optional[str] = None,
                   subject_id: Optional[str] = None) -> List[JSON]:
    selected = list(rows)
    if action is not None:
        selected = [r for r in selected if r.get("action") == action]
    if subject_kind is not None:
        selected = [r for r in selected if r.get("subject_kind") == subject_kind]
    if subject_id is not None:
        selected = [r for r in selected if r.get("subject_id") == subject_id]
    return selected


def assert_audit_actions(rows: Sequence[JSON], expected: Sequence[str]) -> None:
    """The audit collection is ordered by sequence_no ascending."""
    actual = [r.get("action") for r in rows]
    assert actual == list(expected), f"expected audit actions {list(expected)}, got {actual}"


def assert_audit_action_present(rows: Sequence[JSON], action: str, count: int = 1,
                                subject_kind: Optional[str] = None,
                                subject_id: Optional[str] = None) -> List[JSON]:
    found = audit_rows_for(rows, action=action, subject_kind=subject_kind, subject_id=subject_id)
    assert len(found) == count, (
        f"expected {count} {action} audit row(s), got {len(found)}: "
        f"{[r.get('action') for r in rows]}"
    )
    return found


def assert_audit_action_absent(rows: Sequence[JSON], action: str) -> None:
    found = audit_rows_for(rows, action=action)
    assert not found, f"unexpected {action} audit row present"


def assert_sequence_numbers(rows: Sequence[JSON]) -> None:
    """sequence_no is a 1-based counter assigned within each subject_kind and subject_id pair."""
    buckets: Dict[Any, List[int]] = {}
    for row in rows:
        key = (row.get("subject_kind"), row.get("subject_id"))
        buckets.setdefault(key, []).append(row.get("sequence_no"))
    for key, seqs in buckets.items():
        assert seqs == list(range(1, len(seqs) + 1)), (
            f"sequence_no for {key} must run 1..n without skipping, got {seqs}"
        )


def assert_audit_money(row: JSON, before_value_cents: Optional[int],
                        after_value_cents: Optional[int]) -> None:
    assert row.get("before_value_cents") == before_value_cents, (
        f"before_value_cents: expected {before_value_cents}, got {row.get('before_value_cents')}"
    )
    assert row.get("after_value_cents") == after_value_cents, (
        f"after_value_cents: expected {after_value_cents}, got {row.get('after_value_cents')}"
    )


# --- order pricing -------------------------------------------------------
def assert_priced_line(line: JSON, menu_item_id: str, qty: int, unit_price_cents: int,
                        gross_line_cents: int, line_discount_cents: int) -> None:
    """The three values are stored on the line in priced_lines, alongside its menu_item_id and qty."""
    assert line.get("menu_item_id") == menu_item_id
    assert line.get("qty") == qty
    assert_money(line.get("unit_price_cents"), unit_price_cents, "unit_price_cents")
    assert_money(line.get("gross_line_cents"), gross_line_cents, "gross_line_cents")
    assert_money(line.get("line_discount_cents"), line_discount_cents, "line_discount_cents")


def assert_order_totals(order: JSON, subtotal_cents: int, discount_cents: int,
                         tax_cents: int, total_cents: int) -> None:
    assert_money(order.get("subtotal_cents"), subtotal_cents, "subtotal_cents")
    assert_money(order.get("discount_cents"), discount_cents, "discount_cents")
    assert_money(order.get("tax_cents"), tax_cents, "tax_cents")
    assert_money(order.get("total_cents"), total_cents, "total_cents")


# --- pricing / snapshot helpers -----------------------------------------
def override_for_zone(item: JSON, price_zone_id: str) -> Optional[JSON]:
    for entry in item.get("zone_price_overrides") or []:
        if entry.get("price_zone_id") == price_zone_id:
            return entry
    return None


def snapshot_price(bundle: JSON, menu_item_id: str, price_zone_id: str) -> Optional[int]:
    for entry in bundle.get("price_snapshot") or []:
        if entry.get("menu_item_id") == menu_item_id and entry.get("price_zone_id") == price_zone_id:
            return entry.get("price_cents")
    return None


def projection_item(projection: JSON, menu_item_id: str) -> Optional[JSON]:
    for entry in projection.get("items") or []:
        if entry.get("menu_item_id") == menu_item_id or entry.get("id") == menu_item_id:
            return entry
    return None


# --- envelope ------------------------------------------------------------
def assert_envelope(response: Any, expected_response_type: str = "object") -> JSON:
    """The raw envelope: meta.api_request_id, meta.api_request_timestamp, response_type.

    This reads the transport body once for shape checking only; payload assertions
    still go through the framework validators, which are the single unwrap layer.
    """
    body = response.json()
    meta = body.get("meta") or {}
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"], (
        f"meta.api_request_id missing or empty: {meta!r}"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp")), (
        f"meta.api_request_timestamp is not an ISO-8601 instant: {meta!r}"
    )
    assert body.get("response_type") == expected_response_type, (
        f"expected response_type {expected_response_type!r}, got {body.get('response_type')!r}"
    )
    return body
