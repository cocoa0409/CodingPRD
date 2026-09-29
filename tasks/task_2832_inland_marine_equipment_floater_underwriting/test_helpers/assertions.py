"""Domain assertions for the inland marine underwriting record.

Three groups of helper live here. The first canonicalises instants: the
specification requires a server-generated instant to carry exactly three
fractional-second digits, while a date-and-time literal in a test is naturally
written without them, so instant equality is compared on a canonical form rather
than on raw strings. The second group asserts the common resource properties,
including the ledger entry's deliberate exception. The third group asserts the
two conserved quantities: the premium balance against the premium ledger and the
part's aggregate identity.
"""

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import BASIS_POINT_SCALE
from .types import (
    COMMON_RESOURCE_FIELDS,
    LEDGER_ENTRY_FORBIDDEN_FIELDS,
    Ledger,
    LedgerEntryType,
)


# ─── Instants and dates ───────────────────────────────────────────────────────

def canonical_instant(value: str) -> str:
    """Reduce an ISO 8601 UTC instant to a millisecond-precision canonical form.

    ``2026-08-01T00:00:00Z`` and ``2026-08-01T00:00:00.000Z`` denote the same
    instant, so both canonicalise to the same string.
    """
    assert isinstance(value, str), f"Not an instant string: {value!r}"
    assert value.endswith("Z"), f"Instant must be UTC and end with Z: {value!r}"
    body = value[:-1]
    if "." in body:
        head, frac = body.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = body, "000"
    return f"{head}.{frac}Z"


def assert_instant_equals(actual: str, expected: str) -> None:
    """Assert two ISO 8601 UTC instants denote the same moment."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"Instant mismatch: expected {expected!r}, got {actual!r}"
    )


def assert_instant_has_millisecond_precision(value: str) -> None:
    """Assert an instant carries exactly three fractional-second digits."""
    assert isinstance(value, str) and value.endswith("Z"), (
        f"Not a UTC instant: {value!r}"
    )
    body = value[:-1]
    assert "." in body, f"Instant is missing its fractional digits: {value!r}"
    frac = body.split(".", 1)[1]
    assert len(frac) == 3 and frac.isdigit(), (
        f"Instant must carry exactly three fractional digits: {value!r}"
    )


def assert_is_date(value: str) -> None:
    """Assert a value is a calendar date formatted YYYY-MM-DD."""
    assert isinstance(value, str), f"Not a date string: {value!r}"
    parts = value.split("-")
    assert len(parts) == 3 and len(parts[0]) == 4 and len(parts[1]) == 2 and len(
        parts[2]
    ) == 2, f"Not a YYYY-MM-DD calendar date: {value!r}"
    assert all(p.isdigit() for p in parts), f"Not a calendar date: {value!r}"


# ─── Envelope and common properties ───────────────────────────────────────────

def assert_request_id(meta: Dict[str, Any]) -> None:
    """Assert the envelope's request identifier is present and prefixed req_."""
    request_id = meta.get("api_request_id")
    assert isinstance(request_id, str), "meta.api_request_id must be a string"
    assert request_id.startswith("req_"), (
        f"meta.api_request_id must start with 'req_': {request_id!r}"
    )


def assert_common_fields(resource: Dict[str, Any]) -> None:
    """Assert a resource carries the four system-managed properties."""
    for field in COMMON_RESOURCE_FIELDS:
        assert field in resource, f"Resource is missing {field}"
    assert is_valid_uuid(resource["id"]), (
        f"id must be a UUID with no type prefix: {resource['id']!r}"
    )
    assert_instant_has_millisecond_precision(resource["created_at"])
    assert_instant_has_millisecond_precision(resource["updated_at"])
    assert isinstance(resource["version"], int), "version must be an integer"
    assert resource["version"] >= 1, "version starts at 1 on creation"


def assert_ledger_entry_shape(entry: Dict[str, Any]) -> None:
    """Assert a ledger entry carries only id and created_at, never a version."""
    assert "id" in entry and "created_at" in entry, (
        "A ledger entry carries id and created_at"
    )
    assert is_valid_uuid(entry["id"]), f"Ledger entry id must be a UUID: {entry['id']!r}"
    assert is_iso8601_timestamp(entry["created_at"]), (
        f"Ledger entry created_at must be ISO 8601: {entry['created_at']!r}"
    )
    for forbidden in LEDGER_ENTRY_FORBIDDEN_FIELDS:
        assert forbidden not in entry, (
            f"A ledger entry is immutable and must not expose {forbidden}"
        )
    assert entry["entry_type"] in LedgerEntryType.ALL, (
        f"Unknown ledger entry type {entry.get('entry_type')!r}"
    )
    assert entry["ledger"] in Ledger.ALL, (
        f"Unknown ledger book {entry.get('ledger')!r}"
    )
    if entry["entry_type"] in LedgerEntryType.PREMIUM_BOOK:
        assert entry["ledger"] == Ledger.PREMIUM, (
            f"{entry['entry_type']} belongs to the PREMIUM ledger"
        )
    else:
        assert entry["ledger"] == Ledger.LOSS, (
            f"{entry['entry_type']} belongs to the LOSS ledger"
        )


# ─── Ordering and listing ─────────────────────────────────────────────────────

def assert_created_at_ascending(rows: List[Dict[str, Any]]) -> None:
    """Assert a list page is ordered by created_at ascending."""
    stamps = [canonical_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), f"Rows are not in created_at ascending order: {stamps}"


def assert_id_order(rows: List[Dict[str, Any]], expected_ids: Iterable[str]) -> None:
    """Assert a list page contains exactly these identifiers in this order."""
    actual = [row["id"] for row in rows]
    expected = list(expected_ids)
    assert actual == expected, f"Expected rows {expected}, got {actual}"


def assert_page(meta: Dict[str, Any], limit: int, offset: int, total_count: int,
                has_more: bool) -> None:
    """Assert the four pagination fields of a list response's meta object."""
    assert meta["limit"] == limit, f"Expected limit {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"Expected offset {offset}, got {meta['offset']}"
    assert meta["total_count"] == total_count, (
        f"total_count counts matching rows before pagination: expected "
        f"{total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"Expected has_more {has_more}, got {meta['has_more']}"
    )


# ─── Conserved quantities ─────────────────────────────────────────────────────

def assert_premium_balance_reconciles(policy: Dict[str, Any],
                                      premium_entries: List[Dict[str, Any]]) -> None:
    """Assert premium_balance_cents is the sum over the policy's PREMIUM book."""
    total = sum(entry["amount_cents"] for entry in premium_entries)
    assert policy["premium_balance_cents"] == total, (
        f"premium_balance_cents {policy['premium_balance_cents']} does not "
        f"reconcile against the premium ledger sum {total}"
    )


def assert_incurred_loss_reconciles(policy: Dict[str, Any],
                                    loss_entries: List[Dict[str, Any]]) -> None:
    """Assert incurred_loss_cents is the sum over the policy's LOSS book."""
    total = sum(entry["amount_cents"] for entry in loss_entries)
    assert policy["incurred_loss_cents"] == total, (
        f"incurred_loss_cents {policy['incurred_loss_cents']} does not "
        f"reconcile against the loss ledger sum {total}"
    )


def assert_aggregate_capacity_conserved(part: Dict[str, Any]) -> None:
    """Assert the part's aggregate identity holds at this observable moment."""
    assert part["aggregate_limit_cents"] == (
        part["aggregate_available_cents"] + part["aggregate_paid_net_cents"]
    ), (
        f"aggregate_limit_cents {part['aggregate_limit_cents']} must equal "
        f"available {part['aggregate_available_cents']} plus paid net "
        f"{part['aggregate_paid_net_cents']}"
    )


def assert_earned_plus_unearned_is_rated(floater: Dict[str, Any]) -> None:
    """Assert a floater's earned and unearned split sums back to its premium."""
    assert (
        floater["earned_premium_cents"] + floater["unearned_return_cents"]
        == floater["rated_premium_cents"]
    ), (
        "earned_premium_cents plus unearned_return_cents must sum exactly to "
        f"rated_premium_cents: {floater['earned_premium_cents']} + "
        f"{floater['unearned_return_cents']} != {floater['rated_premium_cents']}"
    )


# ─── Money helpers ────────────────────────────────────────────────────────────

def assert_money_field(value: Any, name: str = "amount") -> None:
    """Assert a monetary field is an integer number of cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{name} must be an integer number of cents, got {value!r}"
    )


def assert_basis_point_field(value: Any, name: str = "rate") -> None:
    """Assert a rate or factor field is a non-negative integer of basis points."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{name} must be an integer number of basis points, got {value!r}"
    )
    assert value >= 0, f"{name} may not be negative, got {value}"


def bp_of(amount: int, rate_bp: int) -> int:
    """Round-half-up evaluation of amount * rate_bp / 10000, for cross-checks."""
    numerator = amount * rate_bp * 2 + BASIS_POINT_SCALE
    return numerator // (BASIS_POINT_SCALE * 2)


def assert_null_fields(resource: Dict[str, Any], fields: Iterable[str]) -> None:
    """Assert each named field is present and null."""
    for field in fields:
        assert resource.get(field, "MISSING") is None, (
            f"{field} must be null, got {resource.get(field, 'MISSING')!r}"
        )


def assert_zero_fields(resource: Dict[str, Any], fields: Iterable[str]) -> None:
    """Assert each named field is present and zero."""
    for field in fields:
        assert resource.get(field) == 0, (
            f"{field} must be 0, got {resource.get(field)!r}"
        )


def find_entry(entries: List[Dict[str, Any]], entry_type: str) -> Optional[Dict[str, Any]]:
    """Return the first ledger entry of the given type, or None."""
    for entry in entries:
        if entry["entry_type"] == entry_type:
            return entry
    return None
