"""Domain assertions and the arithmetic the PRD pins.

The rounding helpers exist so a test never re-implements the discipline of PRD
2.6: rates applied to money are rounded half up, quantities derived from rates
are floored. Instant comparison is normalised because the PRD fixes the wire
format at "an ISO 8601 UTC timestamp with three fractional digits" while the
logical clock is written in this document without them.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .constants import BPS_DENOMINATOR


# ---------------------------------------------------------------------------
# Arithmetic (PRD 2.6)
# ---------------------------------------------------------------------------
def apply_rate_half_up(amount_cents: int, bps: int) -> int:
    """``amount_cents * bps / 10000`` rounded half up to whole cents."""
    product = Decimal(amount_cents) * Decimal(bps)
    return int((product / Decimal(BPS_DENOMINATOR)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def apply_rate_floor(quantity: int, bps: int) -> int:
    """``quantity * bps / 10000`` floored, for quantities derived from a rate."""
    return (quantity * bps) // BPS_DENOMINATOR


def duty_suspended_value(on_hand_qty: int, unit_price_cents: int, duty_rate_bps: int, vat_rate_bps: int) -> int:
    """The PRD 2.9 revaluation: on-hand times price times the combined levy."""
    return apply_rate_half_up(on_hand_qty * unit_price_cents, duty_rate_bps + vat_rate_bps)


def line_duty_cents(qty: int, unit_price_cents: int, duty_rate_bps: int, vat_rate_bps: int) -> int:
    """The PRD 3.5 step-5 per-line levy, rounded half up on the line."""
    return apply_rate_half_up(qty * unit_price_cents, duty_rate_bps + vat_rate_bps)


# ---------------------------------------------------------------------------
# Instants
# ---------------------------------------------------------------------------
def normalise_instant(value: str) -> str:
    """Collapse an ISO 8601 UTC instant to a fixed millisecond form."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    elif text.endswith("+00:00"):
        text = text[: -len("+00:00")]
    if "." in text:
        head, fraction = text.split(".", 1)
        fraction = (fraction + "000")[:3]
    else:
        head, fraction = text, "000"
    return f"{head}.{fraction}Z"


def assert_instant(actual: Any, expected: str, label: str = "instant") -> None:
    """Assert two instants denote the same millisecond, whatever their width."""
    assert actual is not None, f"{label} should be stamped but was null"
    assert normalise_instant(actual) == normalise_instant(expected), (
        f"{label} should be {expected} but was {actual}"
    )


def assert_iso_instant(value: Any, label: str = "instant") -> None:
    """Assert a field carries a well-formed ISO 8601 UTC timestamp."""
    assert value is not None, f"{label} should be stamped but was null"
    assert is_iso8601_timestamp(value), f"{label} should be ISO 8601 but was {value!r}"


# ---------------------------------------------------------------------------
# Envelope and identity
# ---------------------------------------------------------------------------
def created(response) -> Dict[str, Any]:
    """Validate a 201 creation envelope and return its ``data`` object."""
    return validate_success(response, 201)


def ok(response) -> Dict[str, Any]:
    """Validate a 200 envelope and return its ``data`` object."""
    return validate_success(response, 200)


def page(response):
    """Validate a paginated list envelope and return ``(data, meta)``."""
    return validate_paginated(response)


def assert_identity(resource: Dict[str, Any], label: str = "resource") -> None:
    """Every resource carries a UUID ``id`` and an ISO 8601 ``created_at``."""
    assert is_valid_uuid(resource["id"]), f"{label} id should be a UUID: {resource['id']!r}"
    assert_iso_instant(resource["created_at"], f"{label} created_at")


def assert_versioned_shape(resource: Dict[str, Any], expected_version: Optional[int] = None, label: str = "resource") -> None:
    """A versioned resource carries ``updated_at`` and an integer ``version``."""
    assert_identity(resource, label)
    assert_iso_instant(resource["updated_at"], f"{label} updated_at")
    assert isinstance(resource["version"], int), f"{label} version should be an integer"
    if expected_version is not None:
        assert resource["version"] == expected_version, (
            f"{label} version should be {expected_version} but was {resource['version']}"
        )


def assert_movement_shape(movement: Dict[str, Any]) -> None:
    """A movement carries id and created_at only - no updated_at, no version."""
    assert_identity(movement, "movement")
    assert "updated_at" not in movement, "a movement must not carry updated_at"
    assert "version" not in movement, "a movement must not carry version"


def assert_pagination_meta(meta: Dict[str, Any], limit: int, offset: int, total_count: int, has_more: bool) -> None:
    assert meta["limit"] == limit, f"limit should be {limit} but was {meta['limit']}"
    assert meta["offset"] == offset, f"offset should be {offset} but was {meta['offset']}"
    assert meta["total_count"] == total_count, (
        f"total_count should be {total_count} but was {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, f"has_more should be {has_more} but was {meta['has_more']}"


# ---------------------------------------------------------------------------
# Domain-specific reconciliations
# ---------------------------------------------------------------------------
def assert_stock_quantities(
    stock_item: Dict[str, Any],
    on_hand: Optional[int] = None,
    reserved: Optional[int] = None,
    duty_suspended_value_cents: Optional[int] = None,
    available: Optional[int] = None,
    on_hand_qty: Optional[int] = None,
    reserved_qty: Optional[int] = None,
) -> None:
    """Assert the derived triple, including ``available_qty`` as the difference."""
    if on_hand is None:
        on_hand = on_hand_qty
    if reserved is None:
        reserved = reserved_qty
    assert on_hand is not None and reserved is not None, "on_hand and reserved are required"
    assert stock_item["on_hand_qty"] == on_hand, (
        f"on_hand_qty should be {on_hand} but was {stock_item['on_hand_qty']}"
    )
    assert stock_item["reserved_qty"] == reserved, (
        f"reserved_qty should be {reserved} but was {stock_item['reserved_qty']}"
    )
    assert stock_item["available_qty"] == on_hand - reserved, (
        "available_qty should be on_hand_qty less reserved_qty but was "
        f"{stock_item['available_qty']}"
    )
    if available is not None:
        assert stock_item["available_qty"] == available, (
            f"available_qty should be {available} but was {stock_item['available_qty']}"
        )
    if duty_suspended_value_cents is not None:
        assert stock_item["duty_suspended_value_cents"] == duty_suspended_value_cents, (
            f"duty_suspended_value_cents should be {duty_suspended_value_cents} but was "
            f"{stock_item['duty_suspended_value_cents']}"
        )


def assert_sale_dimensions(sale: Dict[str, Any], fulfillment_status: str, duty_status: str) -> None:
    """The till dimension and the customs dimension are asserted independently."""
    assert sale["fulfillment_status"] == fulfillment_status, (
        f"fulfillment_status should be {fulfillment_status} but was {sale['fulfillment_status']}"
    )
    assert sale["duty_status"] == duty_status, (
        f"duty_status should be {duty_status} but was {sale['duty_status']}"
    )


def assert_sale_amounts(sale: Dict[str, Any], gross: int, exempt: int, duty: int) -> None:
    assert sale["gross_amount_cents"] == gross, (
        f"gross_amount_cents should be {gross} but was {sale['gross_amount_cents']}"
    )
    assert sale["exempt_amount_cents"] == exempt, (
        f"exempt_amount_cents should be {exempt} but was {sale['exempt_amount_cents']}"
    )
    assert sale["duty_liability_cents"] == duty, (
        f"duty_liability_cents should be {duty} but was {sale['duty_liability_cents']}"
    )


def assert_line_split(line: Dict[str, Any], excess_qty: int, exempt_cents: int, duty_cents: int) -> None:
    assert line["allowance_excess_qty"] == excess_qty, (
        f"allowance_excess_qty should be {excess_qty} but was {line['allowance_excess_qty']}"
    )
    assert line["line_exempt_cents"] == exempt_cents, (
        f"line_exempt_cents should be {exempt_cents} but was {line['line_exempt_cents']}"
    )
    assert line["line_duty_cents"] == duty_cents, (
        f"line_duty_cents should be {duty_cents} but was {line['line_duty_cents']}"
    )


def assert_nulls(resource: Dict[str, Any], *fields: str) -> None:
    for field in fields:
        assert resource[field] is None, f"{field} should be null but was {resource[field]!r}"


def assert_created_at_ascending(records: List[Dict[str, Any]]) -> None:
    """Assert a list read came back in ``created_at`` ascending order."""
    stamps = [normalise_instant(record["created_at"]) for record in records]
    assert stamps == sorted(stamps), f"records should be created_at ascending: {stamps}"


def ids_of(records: List[Dict[str, Any]]) -> List[str]:
    return [record["id"] for record in records]
