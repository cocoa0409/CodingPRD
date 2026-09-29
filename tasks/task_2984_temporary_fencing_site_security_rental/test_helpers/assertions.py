"""Domain assertions for the Temporary Fencing & Site Security Rental API.

These encode the cross-cutting invariants of PRD §2.4, §2.5, §2.6 and §2.10 so
that individual tests state the business fact rather than the plumbing.
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from . import constants as C
from .api_client import canonical_instant, parse_instant


# ---------------------------------------------------------------------------
# Common fields (PRD §2.4)
# ---------------------------------------------------------------------------


def assert_common_fields(entity: Dict[str, Any], *, expected_version: Optional[int] = None):
    """Every resource type carries ``id``, ``created_at``, ``updated_at``, ``version``."""
    assert is_valid_uuid(entity["id"]), f"id must be a bare UUID, got {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int) and not isinstance(
        entity["version"], bool
    ), "version must be an integer"
    assert entity["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_freshly_created(entity: Dict[str, Any]):
    """A freshly created row has ``version`` 1 and ``updated_at == created_at``."""
    assert_common_fields(entity, expected_version=1)
    assert canonical_instant(entity["updated_at"]) == canonical_instant(
        entity["created_at"]
    ), "updated_at must equal created_at on a freshly created row"


# ---------------------------------------------------------------------------
# Money and quantities (PRD §2.5)
# ---------------------------------------------------------------------------


def assert_cents(actual: Any, expected: int, label: str = "amount"):
    """Money is an integer number of cents, never a string and never fractional."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be a JSON integer of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_integer(actual: Any, expected: int, label: str = "count"):
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be a JSON integer, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


def assert_labor_hours(actual: Any, expected: float, label: str = "estimated_labor_hours"):
    """Labour hours carry two fractional digits and are a multiple of 0.25."""
    assert actual is not None, f"{label} must be present"
    value = float(actual)
    assert value == pytest.approx(expected, abs=0.001), (
        f"{label}: expected {expected}, got {actual}"
    )
    quarters = value / C.LABOR_HOURS_QUANTUM
    assert quarters == pytest.approx(round(quarters), abs=0.001), (
        f"{label} must be a multiple of 0.25, got {actual}"
    )


def assert_decimal(actual: Any, expected: float, label: str = "value"):
    assert float(actual) == pytest.approx(expected, abs=0.001), (
        f"{label}: expected {expected}, got {actual}"
    )


# ---------------------------------------------------------------------------
# Instants (PRD §2.6)
# ---------------------------------------------------------------------------


def assert_instant(actual: Any, expected: str, label: str = "instant"):
    """Compare two ISO 8601 UTC instants as moments, not as raw strings."""
    assert actual is not None, f"{label} must be present, expected {expected}"
    assert str(actual).endswith("Z"), (
        f"{label} must be an ISO 8601 UTC instant ending in Z, got {actual!r}"
    )
    assert parse_instant(str(actual)) == parse_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_instant_is_utc(actual: Any, label: str = "instant"):
    assert isinstance(actual, str) and actual.endswith("Z"), (
        f"{label} must be an ISO 8601 UTC instant ending in Z, got {actual!r}"
    )
    parse_instant(actual)


def assert_days_apart(later: str, earlier: str, days: int, label: str = "interval"):
    delta = parse_instant(later) - parse_instant(earlier)
    assert delta.total_seconds() == days * 86400, (
        f"{label}: expected {days} days between {earlier} and {later}, got {delta}"
    )


# ---------------------------------------------------------------------------
# Envelope meta (PRD §2.2)
# ---------------------------------------------------------------------------


def assert_envelope_meta(body: Dict[str, Any]):
    """``api_request_id`` is ``req_``-prefixed; the timestamp has three digits."""
    meta = body["meta"]
    assert isinstance(meta["api_request_id"], str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must carry the req_ prefix, got {meta['api_request_id']!r}"
    )
    stamp = meta["api_request_timestamp"]
    assert isinstance(stamp, str) and stamp.endswith("Z"), stamp
    assert "." in stamp, f"api_request_timestamp must carry fractional digits: {stamp}"
    fraction = stamp.split(".")[1][:-1]
    assert len(fraction) == 3, (
        f"api_request_timestamp must carry exactly three fractional digits: {stamp}"
    )


# ---------------------------------------------------------------------------
# Fleet conservation (PRD §2.10)
# ---------------------------------------------------------------------------


def assert_fleet_conservation(product: Dict[str, Any]):
    """The five buckets of PRD §2.10 always sum to ``owned_count``."""
    total = (
        product["available_count"]
        + product["reserved_count"]
        + product["deployed_count"]
        + product["damaged_count"]
        + product["lost_count"]
    )
    assert total == product["owned_count"], (
        "available + reserved + deployed + damaged + lost must equal owned_count: "
        f"{product}"
    )


def assert_fleet_counts(
    product: Dict[str, Any],
    *,
    available: Optional[int] = None,
    reserved: Optional[int] = None,
    deployed: Optional[int] = None,
    damaged: Optional[int] = None,
    lost: Optional[int] = None,
):
    if available is not None:
        assert_integer(product["available_count"], available, "available_count")
    if reserved is not None:
        assert_integer(product["reserved_count"], reserved, "reserved_count")
    if deployed is not None:
        assert_integer(product["deployed_count"], deployed, "deployed_count")
    if damaged is not None:
        assert_integer(product["damaged_count"], damaged, "damaged_count")
    if lost is not None:
        assert_integer(product["lost_count"], lost, "lost_count")
    assert_fleet_conservation(product)


def assert_credit_hold(account: Dict[str, Any]):
    """``credit_hold_flag`` is true exactly when the balance strictly exceeds the limit."""
    expected = account["open_balance_cents"] > account["credit_limit_cents"]
    assert account["credit_hold_flag"] is expected, (
        "credit_hold_flag must be true exactly when open_balance_cents strictly "
        f"exceeds credit_limit_cents: {account}"
    )


# ---------------------------------------------------------------------------
# Invoices (PRD §3.8)
# ---------------------------------------------------------------------------


def line_by_type(invoice: Dict[str, Any], line_type: str) -> Dict[str, Any]:
    matches = [ln for ln in invoice["lines"] if ln["line_type"] == line_type]
    assert len(matches) == 1, (
        f"expected exactly one {line_type} line, got {len(matches)}: {invoice['lines']}"
    )
    return matches[0]


def assert_line_types(invoice: Dict[str, Any], expected: Sequence[str]):
    actual = [ln["line_type"] for ln in invoice["lines"]]
    assert actual == list(expected), (
        f"expected line types {list(expected)}, got {actual}"
    )


def assert_invoice_rollup(
    invoice: Dict[str, Any],
    *,
    subtotal: int,
    tax: int,
    late_fee: int,
    total: int,
):
    """Rollup of PRD §3.8: the late fee sits outside the taxable base."""
    assert_cents(invoice["subtotal_cents"], subtotal, "subtotal_cents")
    assert_cents(invoice["tax_cents"], tax, "tax_cents")
    assert_cents(invoice["late_fee_cents"], late_fee, "late_fee_cents")
    assert_cents(invoice["total_cents"], total, "total_cents")
    assert invoice["total_cents"] == (
        invoice["subtotal_cents"] + invoice["tax_cents"] + invoice["late_fee_cents"]
    ), "total_cents must be subtotal + tax + late fee"


def assert_fresh_invoice(invoice: Dict[str, Any], *, issued_by: str, issued_at: str):
    """Every invoice is born ``ISSUED`` with nothing paid and a 30-day due date."""
    assert invoice["status"] == C.INVOICE_ISSUED, invoice["status"]
    assert_cents(invoice["amount_paid_cents"], 0, "amount_paid_cents")
    assert invoice["void_reason_code"] is None
    assert_instant(invoice["issued_at_utc"], issued_at, "issued_at_utc")
    assert_days_apart(
        invoice["due_at_utc"], invoice["issued_at_utc"], C.INVOICE_DUE_DAYS, "due_at_utc"
    )
    assert invoice["issued_by_user_id"] == issued_by, (
        f"issued_by_user_id: expected {issued_by}, got {invoice['issued_by_user_id']}"
    )


def assert_non_periodic_period_fields(invoice: Dict[str, Any]):
    """Only ``PERIODIC`` invoices carry a period; the others are null/null/0."""
    assert invoice["period_start_utc"] is None
    assert invoice["period_end_utc"] is None
    assert_integer(invoice["billable_days"], 0, "billable_days")


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------


def ids_of(rows: Iterable[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


def assert_created_at_ascending(rows: Sequence[Dict[str, Any]]):
    """Default collection order of PRD §2.3 is ``created_at`` ascending."""
    stamps = [parse_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), f"rows must be ordered created_at ascending: {stamps}"


def assert_unpaginated(rows: Any, expected_len: Optional[int] = None) -> List[Any]:
    """A plain JSON array payload, with no pagination envelope of its own."""
    assert isinstance(rows, list), f"expected a JSON array, got {type(rows)}"
    if expected_len is not None:
        assert len(rows) == expected_len, f"expected {expected_len} entries, got {rows}"
    return rows


def entry_for_code(entries: Sequence[Dict[str, Any]], product_code: str) -> Dict[str, Any]:
    matches = [e for e in entries if e.get("product_code") == product_code]
    assert len(matches) == 1, (
        f"expected exactly one entry for {product_code}, got {matches}"
    )
    return matches[0]
