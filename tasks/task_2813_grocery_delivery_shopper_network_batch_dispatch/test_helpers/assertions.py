"""Domain assertion helpers.

Every helper here takes an ALREADY-UNWRAPPED entity dict (the value returned
by validate_success / get_success_data) or a list from validate_paginated.
No helper reaches into ["data"] a second time.
"""

from typing import Any, Dict, Iterable, List, Optional

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .api_client import canonical_instant, normalize_timestamp
from .constants import APPEND_ONLY_FORBIDDEN_FIELDS


# --------------------------------------------------------------------------
# Identity and envelope shape
# --------------------------------------------------------------------------
def assert_versioned_identity(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """id / created_at / updated_at / version must all be present."""
    assert is_valid_uuid(entity["id"]), f"id must be a UUID, got {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at must be ISO-8601, got {entity['created_at']!r}"
    )
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"updated_at must be ISO-8601, got {entity['updated_at']!r}"
    )
    assert isinstance(entity["version"], int), "version must be an integer"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_append_only_identity(entity: Dict[str, Any]) -> None:
    """Append-only rows carry id and created_at and nothing else from the set."""
    assert is_valid_uuid(entity["id"]), f"id must be a UUID, got {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at must be ISO-8601, got {entity['created_at']!r}"
    )
    for forbidden in APPEND_ONLY_FORBIDDEN_FIELDS:
        assert forbidden not in entity, (
            f"append-only row must not expose {forbidden!r}: {sorted(entity)}"
        )


def assert_fields(entity: Dict[str, Any], **expected: Any) -> None:
    """Assert a batch of scalar field values with one readable message each."""
    for field, value in expected.items():
        assert field in entity, f"missing field {field!r} in {sorted(entity)}"
        actual = entity[field]
        if isinstance(value, float):
            assert actual == pytest.approx(value), (
                f"{field}: expected {value}, got {actual}"
            )
        else:
            assert actual == value, f"{field}: expected {value!r}, got {actual!r}"


def assert_money_is_integer(entity: Dict[str, Any], *fields: str) -> None:
    for field in fields:
        actual = entity[field]
        assert isinstance(actual, int) and not isinstance(actual, bool), (
            f"{field} must be an integer number of cents, got {actual!r}"
        )


# --------------------------------------------------------------------------
# Timestamps
# --------------------------------------------------------------------------
def assert_instant_equals(actual: str, expected: str, label: str = "instant") -> None:
    """Compare two ISO-8601 UTC instants regardless of sub-second spelling."""
    assert actual is not None, f"{label} must not be null"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {normalize_timestamp(expected)}, "
        f"got {normalize_timestamp(actual)}"
    )


def assert_instant_field(entity: Dict[str, Any], field: str, expected: str) -> None:
    assert_instant_equals(entity[field], expected, label=field)


def assert_null_instant(entity: Dict[str, Any], field: str) -> None:
    assert entity.get(field) is None, f"{field} must be null, got {entity.get(field)!r}"


# --------------------------------------------------------------------------
# Ratios and 4-decimal quantities
# --------------------------------------------------------------------------
def assert_four_decimals(actual: float, expected: float, label: str) -> None:
    assert actual == pytest.approx(expected, abs=1e-9), (
        f"{label}: expected {expected:.4f}, got {actual}"
    )


def assert_one_decimal(actual: float, expected: float, label: str) -> None:
    assert actual == pytest.approx(expected, abs=1e-9), (
        f"{label}: expected {expected:.1f}, got {actual}"
    )


# --------------------------------------------------------------------------
# List / pagination helpers
# --------------------------------------------------------------------------
def rows_and_meta(response) -> tuple:
    """Validate a list response and return (rows, meta)."""
    return validate_paginated(response)


def assert_total_count(response, expected: int) -> List[Dict[str, Any]]:
    rows, meta = validate_paginated(response)
    assert meta["total_count"] == expected, (
        f"expected total_count {expected}, got {meta['total_count']}"
    )
    return rows


def assert_row_ids(rows: Iterable[Dict[str, Any]], expected_ids: List[str]) -> None:
    actual = [row["id"] for row in rows]
    assert actual == expected_ids, f"expected ids {expected_ids}, got {actual}"


def single_row(response) -> Dict[str, Any]:
    rows, meta = validate_paginated(response)
    assert meta["total_count"] == 1, (
        f"expected exactly one row, got total_count {meta['total_count']}"
    )
    assert len(rows) == 1, f"expected exactly one row in the window, got {len(rows)}"
    return rows[0]


def rows_of(response) -> List[Dict[str, Any]]:
    rows, _ = validate_paginated(response)
    return rows


# --------------------------------------------------------------------------
# Convenience readers built on top of the client
# --------------------------------------------------------------------------
def read_order(api, order_id: str, headers) -> Dict[str, Any]:
    return validate_success(api.get_order(order_id, headers))


def read_line(api, line_id: str, headers) -> Dict[str, Any]:
    return validate_success(api.get_order_line(line_id, headers))


def read_batch(api, batch_id: str, headers) -> Dict[str, Any]:
    return validate_success(api.get_batch(batch_id, headers))


def read_shopper(api, shopper_id: str, headers) -> Dict[str, Any]:
    return validate_success(api.get_shopper(shopper_id, headers))


def read_customer(api, customer_id: str, headers) -> Dict[str, Any]:
    return validate_success(api.get_customer(customer_id, headers))


def read_retailer(api, retailer_id: str, headers) -> Dict[str, Any]:
    return validate_success(api.get_retailer(retailer_id, headers))


def read_catalog_item(api, item_id: str, headers) -> Dict[str, Any]:
    return validate_success(api.get_catalog_item(item_id, headers))


def read_replacement(api, request_id: str, headers) -> Dict[str, Any]:
    return validate_success(api.get_replacement_request(request_id, headers))


def payout_for_batch(api, batch_id: str, headers) -> Dict[str, Any]:
    """The single ShopperPayout row of a batch."""
    return single_row(api.list_shopper_payouts(headers, {"batch_id": batch_id}))


def payouts_for_batch(api, batch_id: str, headers) -> List[Dict[str, Any]]:
    return rows_of(api.list_shopper_payouts(headers, {"batch_id": batch_id}))


def credit_entries_for_customer(api, customer_id: str, headers) -> List[Dict[str, Any]]:
    return rows_of(
        api.list_credit_ledger_entries(headers, {"customer_id": customer_id, "limit": 100})
    )


def lines_of_order(api, order_id: str, headers) -> List[Dict[str, Any]]:
    return rows_of(api.list_order_lines(headers, {"order_id": order_id, "limit": 100}))


def batch_orders_of_batch(api, batch_id: str, headers) -> List[Dict[str, Any]]:
    rows, _ = validate_paginated(api.list_batch_orders_of_batch(batch_id, headers))
    return rows


def assert_credit_reasons(entries: List[Dict[str, Any]], expected: Dict[str, int]) -> None:
    """Assert the multiset of (reason_code -> amount_cents) on a credit ledger."""
    actual = {}
    for entry in entries:
        actual.setdefault(entry["reason_code"], []).append(entry["amount_cents"])
    for reason, amount in expected.items():
        assert reason in actual, (
            f"expected a credit entry with reason {reason}, got {sorted(actual)}"
        )
        assert amount in actual[reason], (
            f"reason {reason}: expected amount {amount}, got {actual[reason]}"
        )


def assert_no_credit_reason(entries: List[Dict[str, Any]], reason: str) -> None:
    reasons = [entry["reason_code"] for entry in entries]
    assert reason not in reasons, f"no {reason} entry expected, got {reasons}"


# --------------------------------------------------------------------------
# Conservation invariants (PRD 2.10)
# --------------------------------------------------------------------------
def assert_benefit_funds_conserved(customer: Dict[str, Any], total: int) -> None:
    actual = customer["ebt_snap_balance_cents"] + customer["ebt_captured_total_cents"]
    assert actual == total, (
        "ebt_snap_balance_cents + ebt_captured_total_cents must stay constant at "
        f"{total}, got {actual} "
        f"({customer['ebt_snap_balance_cents']} + {customer['ebt_captured_total_cents']})"
    )


def assert_committed_units_matches_ledger(
    api, shopper: Dict[str, Any], headers, live_statuses=("CLAIMED", "SHOPPING", "CHECKED_OUT")
) -> None:
    """Recompute the capacity ledger from batches and compare with the field."""
    total = 0
    for status in live_statuses:
        rows = rows_of(
            api.list_batches(
                headers,
                {"claimed_shopper_id": shopper["id"], "status": status, "limit": 100},
            )
        )
        total += sum(row["total_units"] for row in rows)
    assert shopper["committed_units"] == total, (
        f"committed_units {shopper['committed_units']} must equal the ledger sum {total}"
    )
