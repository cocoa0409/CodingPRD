"""Domain assertions for the parcel billing suite.

Two families live here:

1. Instant comparison. The API renders timestamps with three fractional
   digits, while the PRD and the business vocabulary talk about instants such
   as ``2026-08-02T00:00:00Z``. ``assert_instant`` compares the two by
   normalising both sides to the same UTC instant, so a difference in
   sub-second rendering width never masquerades as a wrong value.

2. Shape and money assertions that recur across many tests: the common
   property block, the ``id``-plus-``created_at``-only block for the three
   entities declared without common fields, integer-cents typing, ledger
   invariants and the two-key error body.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_valid_uuid

from .types import Entity

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?"
    r"(Z|[+-]\d{2}:?\d{2})$"
)


# ---------------------------------------------------------------------------
# Instant handling
# ---------------------------------------------------------------------------
def parse_instant(value: str) -> datetime:
    """Parse an ISO-8601 UTC instant with or without fractional seconds."""
    assert isinstance(value, str), f"expected an ISO-8601 string, got {value!r}"
    match = _ISO_RE.match(value.strip())
    assert match, f"not an ISO-8601 UTC instant: {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    elif re.search(r"[+-]\d{4}$", text):
        text = text[:-2] + ":" + text[-2:]
    parsed = datetime.fromisoformat(text)
    return parsed.astimezone(timezone.utc)


def canonical_instant(value: str) -> str:
    """Render an instant in one canonical form: whole seconds, trailing Z.

    Sub-second digits are preserved only when they are non-zero, so
    ``2026-08-02T00:00:00.000Z`` and ``2026-08-02T00:00:00Z`` both canonicalise
    to the same text while a genuinely different instant does not.
    """
    moment = parse_instant(value)
    if moment.microsecond:
        return moment.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return moment.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def assert_instant(actual: Any, expected: str, label: str = "timestamp") -> None:
    """Assert that ``actual`` denotes the same UTC instant as ``expected``."""
    assert actual is not None, f"{label} is missing"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected instant {expected}, got {actual}"
    )


def assert_instants_equal(actual: Any, other: Any, label: str = "timestamp") -> None:
    """Assert that two rendered instants denote the same moment."""
    assert canonical_instant(actual) == canonical_instant(other), (
        f"{label}: {actual} and {other} are different instants"
    )


def instant_plus_seconds(value: str, seconds: int) -> str:
    """Shift an instant by whole seconds, keeping the canonical rendering."""
    moment = parse_instant(value) + timedelta(seconds=seconds)
    return moment.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def instant_plus_days(value: str, days: int) -> str:
    """Shift an instant by whole days, keeping the canonical rendering."""
    return instant_plus_seconds(value, days * 86400)


def assert_millisecond_precision(value: Any, label: str = "timestamp") -> None:
    """Assert an ISO-8601 UTC timestamp rendered with three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert re.match(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}(Z|\+00:00)$", value
    ), f"{label} must be ISO-8601 UTC with three fractional digits, got {value!r}"


def assert_date(value: Any, expected: str, label: str = "date") -> None:
    """Assert a calendar date field, tolerating a full-instant rendering."""
    assert value is not None, f"{label} is missing"
    text = str(value)
    assert text[:10] == expected, f"{label}: expected {expected}, got {value}"


# ---------------------------------------------------------------------------
# Common property blocks
# ---------------------------------------------------------------------------
def assert_common_fields(entity: Entity, expected_version: Optional[int] = None) -> None:
    """Assert the full common property block: id, created_at, updated_at, version."""
    assert is_valid_uuid(entity.get("id", "")), f"id is not a UUID: {entity.get('id')!r}"
    assert "-" in str(entity["id"]) and len(str(entity["id"])) == 36, (
        "id must be a bare 36-character UUID with no type prefix"
    )
    assert_millisecond_precision(entity.get("created_at"), "created_at")
    assert_millisecond_precision(entity.get("updated_at"), "updated_at")
    assert isinstance(entity.get("version"), int), "version must be an integer"
    assert entity["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_created_only_fields(entity: Entity) -> None:
    """Assert the reduced block carried by entities declared without common fields.

    Such rows expose ``id`` and ``created_at`` and must not expose
    ``updated_at`` or ``version`` at all.
    """
    assert is_valid_uuid(entity.get("id", "")), f"id is not a UUID: {entity.get('id')!r}"
    assert_millisecond_precision(entity.get("created_at"), "created_at")
    assert "updated_at" not in entity, (
        "this entity carries no updated_at field, but one was returned"
    )
    assert "version" not in entity, (
        "this entity carries no version field, but one was returned"
    )


def assert_version_bumped_by(before: Entity, after: Entity, delta: int = 1) -> None:
    """Assert an entity's version advanced by exactly ``delta``."""
    assert after["version"] == before["version"] + delta, (
        f"expected version {before['version'] + delta}, got {after['version']}"
    )


def assert_version_unchanged(before: Entity, after: Entity) -> None:
    """Assert a rejected write left the version untouched."""
    assert after["version"] == before["version"], (
        f"version moved from {before['version']} to {after['version']} "
        "even though the write was rejected"
    )


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------
def assert_cents(value: Any, label: str = "amount") -> None:
    """Assert a monetary field is an integer number of cents, not a string."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r} "
        f"({type(value).__name__})"
    )


def assert_money_equals(actual: Any, expected: int, label: str = "amount") -> None:
    """Assert an integer-cents field equals an exact expected value."""
    assert_cents(actual, label)
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_pct(actual: Any, expected: float, label: str = "percentage") -> None:
    """Assert a two-decimal percentage field to the cent-equivalent precision."""
    assert actual is not None, f"{label} is missing"
    assert round(float(actual), 2) == round(float(expected), 2), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_lbs(actual: Any, expected: float, label: str = "weight") -> None:
    """Assert a one-decimal pound field."""
    assert actual is not None, f"{label} is missing"
    assert round(float(actual), 1) == round(float(expected), 1), (
        f"{label}: expected {expected}, got {actual}"
    )


# ---------------------------------------------------------------------------
# Entity-shaped assertions
# ---------------------------------------------------------------------------
def assert_fields(entity: Entity, expected: Dict[str, Any]) -> None:
    """Assert a batch of plain field equalities with a readable failure message."""
    for key, want in expected.items():
        assert key in entity, f"field {key} is missing from the response"
        assert entity[key] == want, (
            f"field {key}: expected {want!r}, got {entity[key]!r}"
        )


def assert_null_fields(entity: Entity, keys: Iterable[str]) -> None:
    """Assert every named field is present and null."""
    for key in keys:
        assert key in entity, f"field {key} is missing from the response"
        assert entity[key] is None, f"field {key} should be null, got {entity[key]!r}"


def assert_ledger(
    account: Entity,
    total: Optional[int] = None,
    unbilled: Optional[int] = None,
    billed: Optional[int] = None,
    credit_balance_cents: Optional[int] = None,
    open_charges_cents: Optional[int] = None,
) -> None:
    """Assert the shipper ledger aggregates that were supplied."""
    if total is not None:
        assert account["total_shipment_count"] == total, (
            f"total_shipment_count: expected {total}, "
            f"got {account['total_shipment_count']}"
        )
    if unbilled is not None:
        assert account["unbilled_shipment_count"] == unbilled, (
            f"unbilled_shipment_count: expected {unbilled}, "
            f"got {account['unbilled_shipment_count']}"
        )
    if billed is not None:
        assert account["billed_shipment_count"] == billed, (
            f"billed_shipment_count: expected {billed}, "
            f"got {account['billed_shipment_count']}"
        )
    if credit_balance_cents is not None:
        assert_money_equals(
            account["credit_balance_cents"], credit_balance_cents, "credit_balance_cents"
        )
    if open_charges_cents is not None:
        assert_money_equals(
            account["open_charges_cents"], open_charges_cents, "open_charges_cents"
        )


def assert_package_count_conserved(account: Entity) -> None:
    """Assert unbilled + billed equals the total shipment count."""
    assert (
        account["unbilled_shipment_count"] + account["billed_shipment_count"]
        == account["total_shipment_count"]
    ), (
        "package count is not conserved: "
        f"{account['unbilled_shipment_count']} unbilled + "
        f"{account['billed_shipment_count']} billed != "
        f"{account['total_shipment_count']} total"
    )


def assert_money_conserved(account: Entity, expected_total_cents: int) -> None:
    """Assert credit balance plus open charges equals the expected money total."""
    total = account["credit_balance_cents"] + account["open_charges_cents"]
    assert total == expected_total_cents, (
        "money is not conserved: "
        f"credit {account['credit_balance_cents']} + open "
        f"{account['open_charges_cents']} = {total}, expected {expected_total_cents}"
    )


def assert_error_body_shape(response) -> None:
    """Assert an error envelope carries exactly error_id and message under data."""
    body = response.json()
    assert body["response_type"] == "error", (
        f"expected response_type error, got {body.get('response_type')!r}"
    )
    assert set(body["data"].keys()) == {"error_id", "message"}, (
        f"error data must carry exactly error_id and message, got "
        f"{sorted(body['data'].keys())}"
    )
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str) and meta[
        "api_request_id"
    ].startswith("req_"), (
        f"meta.api_request_id must start with req_, got {meta.get('api_request_id')!r}"
    )
    assert_millisecond_precision(
        meta.get("api_request_timestamp"), "meta.api_request_timestamp"
    )


def assert_envelope_meta(response) -> None:
    """Assert the success envelope's meta block shape."""
    body = response.json()
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str) and meta[
        "api_request_id"
    ].startswith("req_"), (
        f"meta.api_request_id must start with req_, got {meta.get('api_request_id')!r}"
    )
    assert_millisecond_precision(
        meta.get("api_request_timestamp"), "meta.api_request_timestamp"
    )


def ids_of(rows: List[Entity]) -> List[str]:
    """Project a list response onto its ids, preserving order."""
    return [row["id"] for row in rows]


def find_row(rows: List[Entity], **match: Any) -> Entity:
    """Return the single row matching every keyword field, asserting uniqueness."""
    hits = [r for r in rows if all(r.get(k) == v for k, v in match.items())]
    assert len(hits) == 1, (
        f"expected exactly one row matching {match}, found {len(hits)}"
    )
    return hits[0]


def rows_matching(rows: List[Entity], **match: Any) -> List[Entity]:
    """Return every row matching the keyword fields."""
    return [r for r in rows if all(r.get(k) == v for k, v in match.items())]
