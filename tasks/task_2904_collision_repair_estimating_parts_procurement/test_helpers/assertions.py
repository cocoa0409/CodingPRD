"""Domain assertions shared by the suite.

Money is compared as whole integer cents, hours at one decimal place, and every
instant through the canonical form so that a three-digit fractional part never
turns a correct value into a failure.
"""

from typing import Any, Dict, Iterable, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant
from .constants import (
    SECONDS_PER_DAY,
    WARRANTY_PREFIX,
    WARRANTY_TERM_DAYS,
)


# ---------------------------------------------------------------------------
# Scalars
# ---------------------------------------------------------------------------
def assert_cents(actual: Any, expected: int, label: str = "amount") -> None:
    """A money field is a whole number of cents, carried as a JSON integer."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_hours(actual: Any, expected: float, label: str = "hours") -> None:
    """An hours field carries at most one decimal place."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be numeric, got {actual!r}"
    )
    assert actual == pytest.approx(expected, abs=0.01), (
        f"{label}: expected {expected} hours, got {actual}"
    )


def assert_count(actual: Any, expected: int, label: str = "count") -> None:
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


def assert_instant(actual: Any, expected: str, label: str = "timestamp") -> None:
    """Compare two instants by their canonical form, not by raw string equality."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_instant_format(actual: Any, label: str = "timestamp") -> None:
    assert isinstance(actual, str), f"{label} must be a string, got {actual!r}"
    assert is_iso8601_timestamp(actual), f"{label} is not an ISO-8601 instant: {actual}"


def assert_null(actual: Any, label: str = "field") -> None:
    assert actual is None, f"{label} must be null, got {actual!r}"


def assert_plus_days(actual: Any, base: str, days: int, label: str = "expiry") -> None:
    """A day is 86,400 seconds, with no calendar or leap adjustment."""
    from datetime import datetime, timedelta, timezone

    parsed = datetime.strptime(
        canonical_instant(base), "%Y-%m-%dT%H:%M:%S.%fZ"
    ).replace(tzinfo=timezone.utc)
    expected = parsed + timedelta(seconds=days * SECONDS_PER_DAY)
    assert_instant(
        actual, expected.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z", label
    )


# ---------------------------------------------------------------------------
# The common field block
# ---------------------------------------------------------------------------
def assert_identity_fields(row: Dict[str, Any], label: str = "row") -> None:
    assert is_valid_uuid(row["id"]), f"{label}.id is not a UUID: {row['id']!r}"
    assert_instant_format(row["created_at"], f"{label}.created_at")


def assert_mutable_common_fields(row: Dict[str, Any], label: str = "row") -> None:
    """A resource that can be updated carries the full quartet."""
    assert_identity_fields(row, label)
    assert_instant_format(row["updated_at"], f"{label}.updated_at")
    assert isinstance(row["version"], int) and not isinstance(row["version"], bool), (
        f"{label}.version must be an integer, got {row['version']!r}"
    )
    assert row["version"] >= 1, f"{label}.version must start at 1, got {row['version']}"


def assert_append_only_common_fields(row: Dict[str, Any], label: str = "row") -> None:
    """A resource that is never updated carries no `updated_at` and no `version`."""
    assert_identity_fields(row, label)
    assert "updated_at" not in row, f"{label} must not carry updated_at"
    assert "version" not in row, f"{label} must not carry version"


def assert_version(row: Dict[str, Any], expected: int, label: str = "row") -> None:
    assert row["version"] == expected, (
        f"{label}.version: expected {expected}, got {row['version']}"
    )


def assert_envelope_meta(body: Dict[str, Any]) -> None:
    meta = body["meta"]
    assert isinstance(meta["api_request_id"], str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    )
    assert_instant_format(meta["api_request_timestamp"], "api_request_timestamp")


# ---------------------------------------------------------------------------
# The repair order
# ---------------------------------------------------------------------------
def assert_stage(order: Dict[str, Any], expected: str) -> None:
    assert order["stage"] == expected, (
        f"stage: expected {expected}, got {order['stage']}"
    )


def assert_posture(order: Dict[str, Any], expected: str) -> None:
    assert order["authorization_posture"] == expected, (
        f"authorization_posture: expected {expected}, "
        f"got {order['authorization_posture']}"
    )


def assert_totals(order: Dict[str, Any], **expected: int) -> None:
    """Compare any subset of the eight-step totals field by field."""
    for field, value in expected.items():
        assert_cents(order[field], value, field)


def assert_parts_conservation(order: Dict[str, Any]) -> None:
    """The append-only gross equals committed plus credit plus restocking loss."""
    gross = order["parts_ordered_gross_cents"]
    committed = order["parts_committed_cents"]
    credit = order["parts_return_credit_cents"]
    loss = order["parts_restocking_loss_cents"]
    assert gross == committed + credit + loss, (
        "parts conservation identity broken: "
        f"ordered_gross {gross} != committed {committed} + credit {credit} "
        f"+ restocking_loss {loss}"
    )


def assert_customer_pay_split(order: Dict[str, Any]) -> None:
    """The owner's share is whatever the pre-tax total leaves after the insurer."""
    assert (
        order["customer_pay_cents"]
        == order["pre_tax_total_cents"] - order["insurer_authorized_cents"]
    ), (
        "customer_pay_cents must be pre_tax_total_cents less insurer_authorized_cents: "
        f"{order['customer_pay_cents']} vs "
        f"{order['pre_tax_total_cents']} - {order['insurer_authorized_cents']}"
    )


# ---------------------------------------------------------------------------
# Parts lines
# ---------------------------------------------------------------------------
def assert_parts_line_state(
    line: Dict[str, Any],
    procurement_status: Optional[str] = None,
    authorization_status: Optional[str] = None,
) -> None:
    """The two parallel dimensions of a parts line, checked independently."""
    if procurement_status is not None:
        assert line["procurement_status"] == procurement_status, (
            f"procurement_status: expected {procurement_status}, "
            f"got {line['procurement_status']}"
        )
    if authorization_status is not None:
        assert line["authorization_status"] == authorization_status, (
            f"authorization_status: expected {authorization_status}, "
            f"got {line['authorization_status']}"
        )


def assert_extension(line: Dict[str, Any], unit_extended: int, extended: int) -> None:
    assert_cents(line["unit_extended_cents"], unit_extended, "unit_extended_cents")
    assert_cents(line["extended_price_cents"], extended, "extended_price_cents")


# ---------------------------------------------------------------------------
# Supplier scores
# ---------------------------------------------------------------------------
def assert_scores(vendor: Dict[str, Any], rolling: int, lifetime: int) -> None:
    assert_count(vendor["fulfillment_score_rolling"], rolling, "fulfillment_score_rolling")
    assert_count(
        vendor["fulfillment_score_lifetime"], lifetime, "fulfillment_score_lifetime"
    )


# ---------------------------------------------------------------------------
# Warranty
# ---------------------------------------------------------------------------
def assert_warranty(
    inspection: Dict[str, Any], claim_number: str, issued_at: str
) -> None:
    """The certificate number is composed, and the expiry is 365 days on."""
    expected_number = (
        f"{WARRANTY_PREFIX}{claim_number}-{inspection['sequence_number']}"
    )
    assert inspection["warranty_certificate_number"] == expected_number, (
        "warranty_certificate_number: expected "
        f"{expected_number}, got {inspection['warranty_certificate_number']}"
    )
    assert_plus_days(
        inspection["warranty_expires_at"],
        issued_at,
        WARRANTY_TERM_DAYS,
        "warranty_expires_at",
    )


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------
def assert_page(
    meta: Dict[str, Any],
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> None:
    if total_count is not None:
        assert_count(meta["total_count"], total_count, "total_count")
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"has_more: expected {has_more}, got {meta['has_more']}"
        )
    if limit is not None:
        assert_count(meta["limit"], limit, "limit")
    if offset is not None:
        assert_count(meta["offset"], offset, "offset")


def assert_ids(rows: Iterable[Dict[str, Any]], expected_ids: Iterable[str]) -> None:
    """A listing carries exactly these rows, in this order."""
    actual = [row["id"] for row in rows]
    expected = list(expected_ids)
    assert actual == expected, f"listing ids: expected {expected}, got {actual}"


def assert_created_at_ascending(rows: Iterable[Dict[str, Any]]) -> None:
    stamps = [canonical_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), f"listing is not in created_at order: {stamps}"
