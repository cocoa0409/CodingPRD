"""Domain assertion helpers.

Everything here is a thin, explicit checker over an already-unwrapped resource
body (the dict that api_client returns).  Helpers never re-index ["data"].
"""

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# --------------------------------------------------------------------------
# Primitive shape helpers
# --------------------------------------------------------------------------


def assert_money_cents(value: Any, expected: Optional[int] = None, field: str = "value") -> None:
    """Whole-cent integers travel as JSON numbers, never as strings."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be a JSON integer number of cents, got {value!r}"
    )
    if expected is not None:
        assert value == expected, f"{field} expected {expected}, got {value}"


def assert_percent(value: Any, expected: Optional[float] = None, field: str = "pct") -> None:
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be a JSON number, got {value!r}"
    )
    if expected is not None:
        assert abs(float(value) - float(expected)) < 1e-9, (
            f"{field} expected {expected}, got {value}"
        )


def assert_instant(value: Any, field: str = "timestamp") -> None:
    assert isinstance(value, str) and value, f"{field} must be an ISO 8601 string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{field} is not a valid ISO 8601 instant: {value!r}"


def parse_instant(raw: str) -> datetime:
    """Parse an ISO 8601 UTC instant with any number of fractional digits."""
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(value: Any, expected: str, field: str = "timestamp") -> None:
    """Compare instants by their point in time, not by their textual width."""
    assert_instant(value, field)
    assert parse_instant(value) == parse_instant(expected), (
        f"{field} expected {expected}, got {value}"
    )


def assert_uuid(value: Any, field: str = "id") -> None:
    assert isinstance(value, str), f"{field} must be a string id, got {value!r}"
    assert is_valid_uuid(value), f"{field} is not a valid UUID: {value!r}"


def assert_common_fields(resource: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """id, created_at, updated_at and version on every resource that declares them."""
    assert_uuid(resource.get("id"), "id")
    assert_instant(resource.get("created_at"), "created_at")
    assert_instant(resource.get("updated_at"), "updated_at")
    version = resource.get("version")
    assert isinstance(version, int) and version >= 1, f"version must be >= 1, got {version!r}"
    if expected_version is not None:
        assert version == expected_version, (
            f"version expected {expected_version}, got {version}"
        )


def assert_append_only_shape(resource: Dict[str, Any]) -> None:
    """An append-only record carries id and created_at but no updated_at and no version."""
    assert_uuid(resource.get("id"), "id")
    assert_instant(resource.get("created_at"), "created_at")
    assert "updated_at" not in resource, "append-only record must not expose updated_at"
    assert "version" not in resource, "append-only record must not expose version"


def assert_fields(resource: Dict[str, Any], **expected) -> None:
    """Exact equality on a batch of named fields, reporting the first mismatch."""
    for field, want in expected.items():
        assert field in resource, f"missing field {field!r} in {sorted(resource)}"
        got = resource[field]
        if isinstance(want, float) or isinstance(got, float):
            assert abs(float(got) - float(want)) < 1e-9, (
                f"{field} expected {want}, got {got}"
            )
        else:
            assert got == want, f"{field} expected {want!r}, got {got!r}"


def assert_absent_or_none(resource: Dict[str, Any], *fields: str) -> None:
    for field in fields:
        assert resource.get(field) is None, f"{field} expected null, got {resource.get(field)!r}"


# --------------------------------------------------------------------------
# Lot invariants
# --------------------------------------------------------------------------


def assert_lot_units_conservation(lot: Dict[str, Any]) -> None:
    """quantity_original always equals qoh + sold + shrunk + donated."""
    total = (
        lot["quantity_on_hand"]
        + lot["units_sold"]
        + lot["units_shrunk"]
        + lot["units_donated"]
    )
    assert total == lot["quantity_original"], (
        "units conservation broken: quantity_original="
        f"{lot['quantity_original']} but qoh={lot['quantity_on_hand']} + "
        f"sold={lot['units_sold']} + shrunk={lot['units_shrunk']} + "
        f"donated={lot['units_donated']} = {total}"
    )


def assert_lot_pricing(
    lot: Dict[str, Any],
    current_price_cents: int,
    current_rung_index: int,
    total_discount_pct: float,
    status: Optional[str] = None,
) -> None:
    assert_money_cents(lot["current_price_cents"], current_price_cents, "current_price_cents")
    assert lot["current_rung_index"] == current_rung_index, (
        f"current_rung_index expected {current_rung_index}, got {lot['current_rung_index']}"
    )
    assert_percent(lot["total_discount_pct"], total_discount_pct, "total_discount_pct")
    if status is not None:
        assert lot["status"] == status, f"lot status expected {status}, got {lot['status']}"


def assert_fresh_unpriced_lot(lot: Dict[str, Any], base_retail_cents: int) -> None:
    """A lot that has never been marked down sits at base retail, rung -1, zero discount."""
    assert_lot_pricing(lot, base_retail_cents, -1, 0.0, status="FRESH")


# --------------------------------------------------------------------------
# Label invariants
# --------------------------------------------------------------------------


def expected_barcode(upc: str, to_price_cents: int) -> str:
    """MD- then the item's upc then - then the new price zero-padded to five digits."""
    return f"MD-{upc}-{to_price_cents:05d}"


def assert_label(
    label: Dict[str, Any],
    status: str,
    from_price_cents: int,
    to_price_cents: int,
    discount_pct: float,
    reason: Optional[str] = None,
    barcode: Optional[str] = None,
) -> None:
    assert label["status"] == status, f"label status expected {status}, got {label['status']}"
    assert_money_cents(label["from_price_cents"], from_price_cents, "from_price_cents")
    assert_money_cents(label["to_price_cents"], to_price_cents, "to_price_cents")
    assert_percent(label["discount_pct"], discount_pct, "discount_pct")
    if reason is not None:
        assert label["reason"] == reason, f"label reason expected {reason}, got {label['reason']}"
    if barcode is not None:
        assert label["barcode"] == barcode, (
            f"barcode expected {barcode}, got {label['barcode']}"
        )


# --------------------------------------------------------------------------
# Department / compliance invariants
# --------------------------------------------------------------------------


def assert_department_posture(
    department: Dict[str, Any],
    compliance_status: str,
    shrink_cost_ratio_pct: Optional[float] = None,
    markdown_liability_cents: Optional[int] = None,
    open_finding_count: Optional[int] = None,
) -> None:
    assert department["compliance_status"] == compliance_status, (
        f"compliance_status expected {compliance_status}, got {department['compliance_status']}"
    )
    if shrink_cost_ratio_pct is not None:
        assert_percent(
            department["shrink_cost_ratio_pct"], shrink_cost_ratio_pct, "shrink_cost_ratio_pct"
        )
    if markdown_liability_cents is not None:
        assert_money_cents(
            department["markdown_liability_cents"],
            markdown_liability_cents,
            "markdown_liability_cents",
        )
    if open_finding_count is not None:
        assert department["open_finding_count"] == open_finding_count, (
            f"open_finding_count expected {open_finding_count}, "
            f"got {department['open_finding_count']}"
        )


def assert_unchanged(before: Dict[str, Any], after: Dict[str, Any], *fields: str) -> None:
    """A refused write must leave every named field byte-identical."""
    for field in fields:
        assert before.get(field) == after.get(field), (
            f"{field} changed from {before.get(field)!r} to {after.get(field)!r}"
        )


def assert_ids_equal(actual: Iterable[Dict[str, Any]], expected_ids: Iterable[str]) -> None:
    """Ordered comparison of a listing's ids."""
    got = [row["id"] for row in actual]
    want = list(expected_ids)
    assert got == want, f"listing ids expected {want}, got {got}"


def assert_contains_ids(actual: Iterable[Dict[str, Any]], expected_ids: Iterable[str]) -> None:
    got = {row["id"] for row in actual}
    for wanted in expected_ids:
        assert wanted in got, f"expected id {wanted} in listing, got {sorted(got)}"


def assert_excludes_ids(actual: Iterable[Dict[str, Any]], excluded_ids: Iterable[str]) -> None:
    got = {row["id"] for row in actual}
    for banned in excluded_ids:
        assert banned not in got, f"id {banned} must not appear in listing"
