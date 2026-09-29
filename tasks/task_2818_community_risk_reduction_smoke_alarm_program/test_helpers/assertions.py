"""Domain assertions for the Community Risk Reduction API.

These wrap the PRD's own rules: instants carry exactly three fractional digits,
decimal metrics are rounded half up to a fixed scale, empty aggregates are null
rather than zero, monetary amounts are integers, updatable rows carry a version
while append-only rows do not, and the device/money ledgers must always balance.
"""

import re
from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def normalize_instant(value: str) -> str:
    """Reduce an ISO 8601 UTC instant to millisecond precision with a ``Z`` suffix.

    Comparisons of instants are made at millisecond resolution, so any trailing
    offset spelling or extra fractional digits are collapsed before comparing.
    """
    assert isinstance(value, str), f"expected an ISO 8601 instant string, got {value!r}"
    text = value.strip()
    if text.endswith("+00:00"):
        text = text[:-6] + "Z"
    assert text.endswith("Z"), f"instant must be expressed in UTC: {value!r}"
    body = text[:-1]
    if "." in body:
        head, frac = body.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = body, "000"
    return f"{head}.{frac}Z"


def assert_instant_equals(actual: Any, expected: str, field: str = "instant") -> None:
    """Compare two instants at millisecond resolution."""
    assert actual is not None, f"{field} must not be null"
    assert normalize_instant(actual) == normalize_instant(expected), (
        f"{field}: expected {expected}, got {actual}"
    )


def assert_millisecond_instant(value: Any, field: str = "timestamp") -> None:
    """Every timestamp the API emits carries exactly three fractional digits."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert _INSTANT_RE.match(value), (
        f"{field} must be an ISO 8601 UTC instant with exactly three "
        f"fractional-second digits, got {value!r}"
    )
    assert is_iso8601_timestamp(value), f"{field} is not a valid ISO 8601 instant: {value!r}"


def assert_calendar_date(value: Any, field: str = "date") -> None:
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert _DATE_RE.match(value), f"{field} must be YYYY-MM-DD, got {value!r}"


def assert_envelope_meta(response) -> Dict[str, Any]:
    """The response envelope's own contract: request id, timestamp and type."""
    body = response.json()
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert_millisecond_instant(meta.get("api_request_timestamp"), "api_request_timestamp")
    assert body["response_type"] in ("object", "array", "error")
    return body


def assert_mutable_record(data: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """An updatable row carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data["id"]), f"id must be a UUID, got {data['id']!r}"
    assert_millisecond_instant(data.get("created_at"), "created_at")
    assert_millisecond_instant(data.get("updated_at"), "updated_at")
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"expected version {expected_version}, got {data['version']}"
        )


def assert_append_only_record(data: Dict[str, Any]) -> None:
    """An append-only row carries only id and created_at - no updated_at, no version."""
    assert is_valid_uuid(data["id"]), f"id must be a UUID, got {data['id']!r}"
    assert_millisecond_instant(data.get("created_at"), "created_at")
    assert "updated_at" not in data, (
        "append-only records are never updated, so they carry no updated_at"
    )
    assert "version" not in data, (
        "append-only records are never updated, so they carry no version"
    )


def assert_integer_cents(value: Any, field: str = "amount") -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be a whole number of cents expressed as an integer, got {value!r}"
    )


def assert_decimal_scale(value: Any, places: int, field: str = "value") -> None:
    """A rounded metric must not carry more precision than the PRD allows."""
    assert value is not None, f"{field} must not be null here"
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be numeric, got {value!r}"
    )
    quantized = round(float(value), places)
    assert abs(float(value) - quantized) < 1e-9, (
        f"{field} must be rounded to {places} decimal places, got {value!r}"
    )


def assert_two_dp(value: Any, field: str = "value") -> None:
    assert_decimal_scale(value, 2, field)


def assert_four_dp(value: Any, field: str = "value") -> None:
    assert_decimal_scale(value, 4, field)


def assert_null_not_zero(value: Any, field: str = "value") -> None:
    """An aggregate over an empty set is an explicit null, never 0.00."""
    assert value is None, (
        f"{field} must be null when its input set is empty, got {value!r}"
    )


def assert_number_equals(actual: Any, expected: float, field: str = "value") -> None:
    assert actual is not None, f"{field} must not be null"
    assert abs(float(actual) - float(expected)) < 1e-9, (
        f"{field}: expected {expected}, got {actual}"
    )


def assert_lot_units_conserved(lot: Dict[str, Any]) -> None:
    """received_qty always equals on_hand_qty plus consumed_qty."""
    assert lot["received_qty"] == lot["on_hand_qty"] + lot["consumed_qty"], (
        "received_qty must equal on_hand_qty + consumed_qty, got "
        f"{lot['received_qty']} != {lot['on_hand_qty']} + {lot['consumed_qty']}"
    )
    assert 0 <= lot["reserved_qty"] <= lot["on_hand_qty"], (
        "reserved_qty must be a subset of on_hand_qty, got "
        f"reserved {lot['reserved_qty']} of on_hand {lot['on_hand_qty']}"
    )


def assert_lot_status_derived(lot: Dict[str, Any]) -> None:
    """A lot is DEPLETED exactly when nothing is left on hand."""
    expected = "DEPLETED" if lot["on_hand_qty"] == 0 else "AVAILABLE"
    assert lot["status"] == expected, (
        f"lot with on_hand_qty {lot['on_hand_qty']} must be {expected}, "
        f"got {lot['status']}"
    )


def assert_grant_money_balanced(grant: Dict[str, Any]) -> None:
    """authorized_cents always equals reserved + committed + available."""
    for field in ("authorized_cents", "reserved_cents", "committed_cents", "available_cents"):
        assert_integer_cents(grant[field], field)
    total = grant["reserved_cents"] + grant["committed_cents"] + grant["available_cents"]
    assert total == grant["authorized_cents"], (
        "reserved + committed + available must equal authorized, got "
        f"{grant['reserved_cents']} + {grant['committed_cents']} + "
        f"{grant['available_cents']} != {grant['authorized_cents']}"
    )


def assert_pagination_defaults(meta: Dict[str, Any], total_count: int) -> None:
    assert meta["limit"] == 10, "the default page size is 10"
    assert meta["offset"] == 0, "the default offset is 0"
    assert meta["total_count"] == total_count
    assert meta["has_more"] is (total_count > meta["offset"] + meta["limit"])


def assert_ordered_by(rows: Iterable[Dict[str, Any]], field: str) -> None:
    values = [row[field] for row in rows]
    assert values == sorted(values), f"rows must be ordered by {field} ascending: {values}"


def assert_version_bumped_by(before: Dict[str, Any], after: Dict[str, Any], delta: int) -> None:
    assert after["version"] == before["version"] + delta, (
        f"expected version {before['version']} + {delta}, got {after['version']}"
    )
