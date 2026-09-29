"""
Domain assertion helpers.

These wrap the generic framework helpers with the shapes this API declares:
the ISO-8601 instant format of PRD §2.4 (UTC, exactly three fractional digits),
the append-only entities that carry no ``updated_at`` / ``version``, the ledger
row shape and ordering of PRD §2.11, and the benefit-entitlement census.
"""

import re
from typing import Iterable, List, Optional

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)

_INSTANT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?Z$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ─── Timestamp handling ───────────────────────────────────────────────────────

def canonical_instant(value: str) -> str:
    """
    Reduce an ISO-8601 UTC instant to second precision so instants can be
    compared without tripping over fractional-second width.
    """
    assert isinstance(value, str), f"expected an instant string, got {value!r}"
    match = _INSTANT_RE.match(value)
    assert match, f"not an ISO-8601 UTC instant ending in Z: {value!r}"
    return match.group(1) + "Z"


def assert_instant_equals(actual: Optional[str], expected: str) -> None:
    """Compare two instants ignoring fractional-second width."""
    assert actual is not None, f"expected instant {expected}, got None"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"expected instant {expected}, got {actual}"
    )


def assert_system_timestamp(value: str) -> None:
    """A system instant must be UTC ISO-8601 with exactly three fractional digits."""
    assert isinstance(value, str), f"expected a timestamp string, got {value!r}"
    assert is_iso8601_timestamp(value), f"not an ISO-8601 UTC timestamp: {value!r}"
    assert re.match(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", value
    ), f"expected exactly three fractional digits and a trailing Z: {value!r}"


def assert_date(value: str) -> None:
    """A calendar date field must be YYYY-MM-DD."""
    assert isinstance(value, str) and _DATE_RE.match(value), (
        f"expected a YYYY-MM-DD date, got {value!r}"
    )


# ─── Entity system fields ─────────────────────────────────────────────────────

def assert_mutable_entity(entity: dict) -> None:
    """Mutable entities carry id, created_at, updated_at and version."""
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']!r}"
    assert not entity["id"].startswith(("sub_", "prop_", "sku_")), (
        "id must be a bare UUID with no prefix"
    )
    assert_system_timestamp(entity["created_at"])
    assert_system_timestamp(entity["updated_at"])
    assert isinstance(entity["version"], int) and entity["version"] >= 1


def assert_immutable_entity(entity: dict) -> None:
    """
    Append-only rows carry only id and created_at: no updated_at, no version.
    """
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']!r}"
    assert_system_timestamp(entity["created_at"])
    assert "updated_at" not in entity, (
        "append-only rows must not expose updated_at"
    )
    assert "version" not in entity, "append-only rows must not expose version"


def assert_envelope_meta(response) -> dict:
    """Validate the meta block of any successful envelope (PRD §2.2)."""
    body = response.json()
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_': {meta['api_request_id']!r}"
    )
    assert_system_timestamp(meta["api_request_timestamp"])
    return meta


# ─── Money ────────────────────────────────────────────────────────────────────

def assert_cents(actual, expected: int, label: str = "amount") -> None:
    """Cent amounts are exact integers — never floats, never strings."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_decimal_string(actual, expected: str, label: str = "value") -> None:
    """
    Fixed-scale decimals the PRD serialises as strings (e.g. waiver_credit_pct)
    must arrive as strings with their declared scale preserved.
    """
    assert isinstance(actual, str), (
        f"{label} must be a decimal string, got {actual!r} ({type(actual).__name__})"
    )
    assert actual == expected, f"{label}: expected {expected!r}, got {actual!r}"


# ─── Ledger (PRD §2.11) ───────────────────────────────────────────────────────

def assert_ledger_row(
    row: dict,
    entry_type: str,
    amount_cents: int,
    billed_party: Optional[str] = None,
    source_ref_id: Optional[str] = None,
) -> None:
    """Assert one ledger row's type, signed amount and billed party."""
    assert row["entry_type"] == entry_type, (
        f"expected entry_type {entry_type}, got {row['entry_type']}"
    )
    assert_cents(row["amount_cents"], amount_cents, f"{entry_type}.amount_cents")
    if billed_party is not None:
        assert row["billed_party"] == billed_party, (
            f"{entry_type}: expected billed_party {billed_party}, "
            f"got {row['billed_party']}"
        )
    if source_ref_id is not None:
        assert row["source_ref_id"] == source_ref_id, (
            f"{entry_type}: expected source_ref_id {source_ref_id}, "
            f"got {row['source_ref_id']}"
        )
    assert_immutable_entity(row)


def assert_ledger_ordering(rows: List[dict]) -> None:
    """Ledger listings are ordered by created_at ASC then period_start ASC."""
    keys = [
        (canonical_instant(r["created_at"]), r.get("period_start") or "")
        for r in rows
    ]
    assert keys == sorted(keys), f"ledger rows are not in (created_at, period_start) order: {keys}"


def ledger_entry_types(rows: Iterable[dict]) -> List[str]:
    return [r["entry_type"] for r in rows]


def find_ledger_rows(rows: Iterable[dict], entry_type: str) -> List[dict]:
    return [r for r in rows if r["entry_type"] == entry_type]


# ─── Benefit entitlements ─────────────────────────────────────────────────────

def entitlement_by_code(rows: Iterable[dict], benefit_code: str) -> dict:
    matches = [r for r in rows if r["benefit_code"] == benefit_code]
    assert len(matches) == 1, (
        f"expected exactly one {benefit_code} entitlement, got {len(matches)}"
    )
    return matches[0]

def assert_entitlement(
    row: dict,
    state: str,
    suspended_by_property_event: Optional[bool] = None,
    forfeit_reason: Optional[str] = "__unset__",
) -> None:
    """Assert one entitlement's state and its two policy flags."""
    assert row["state"] == state, (
        f"{row['benefit_code']}: expected state {state}, got {row['state']}"
    )
    if suspended_by_property_event is not None:
        assert row["suspended_by_property_event"] is suspended_by_property_event, (
            f"{row['benefit_code']}: expected suspended_by_property_event="
            f"{suspended_by_property_event}, got {row['suspended_by_property_event']}"
        )
    if forfeit_reason != "__unset__":
        assert row["forfeit_reason"] == forfeit_reason, (
            f"{row['benefit_code']}: expected forfeit_reason {forfeit_reason}, "
            f"got {row['forfeit_reason']}"
        )


def active_benefit_codes(rows: Iterable[dict]) -> List[str]:
    """Sorted benefit_code list of the entitlements currently in state ACTIVE."""
    return sorted(r["benefit_code"] for r in rows if r["state"] == "ACTIVE")


# ─── Pagination ───────────────────────────────────────────────────────────────

def assert_page_meta(meta: dict, limit: int, offset: int, total_count: int, has_more: bool) -> None:
    assert meta["limit"] == limit, f"expected limit {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"expected offset {offset}, got {meta['offset']}"
    assert meta["total_count"] == total_count, (
        f"expected total_count {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"expected has_more {has_more}, got {meta['has_more']}"
    )


def assert_created_at_ascending(rows: List[dict]) -> None:
    stamps = [canonical_instant(r["created_at"]) for r in rows]
    assert stamps == sorted(stamps), f"rows are not in created_at ASC order: {stamps}"


# ─── Convenience readers ──────────────────────────────────────────────────────

def property_balance(api, property_id: str, headers: dict) -> int:
    """Read Property.outstanding_balance_cents through the public endpoint."""
    data = validate_success(api.get_property(property_id, headers))
    return data["outstanding_balance_cents"]


def subscription_version(api, subscription_id: str, headers: dict) -> int:
    data = validate_success(api.get_subscription(subscription_id, headers))
    return data["version"]


def assert_approx_cents(actual: float, expected: float, label: str = "amount") -> None:
    """For any monetary field the PRD models as a decimal rather than cents."""
    assert actual == pytest.approx(expected, abs=0.01), (
        f"{label}: expected {expected}, got {actual}"
    )
