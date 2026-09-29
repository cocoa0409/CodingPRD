"""Domain assertion helpers.

These wrap the shared envelope validators with the vocabulary of this service:
the two-dimensional unit state model, the four housekeeping properties, the
reduced property set of the three immutable event records, and the half-up
integer-cent arithmetic the money formulas are pinned to.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import requests

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

JsonDict = Dict[str, Any]

_INSTANT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?Z$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

HOUSEKEEPING_FIELDS = ("id", "created_at", "updated_at", "version")
EVENT_FIELDS = ("id", "created_at")


# ---------------------------------------------------------------------------
# Timestamps and dates
# ---------------------------------------------------------------------------


def canonical_instant(value: str) -> str:
    """Reduce an ISO 8601 UTC instant to second precision for comparison.

    The service renders instants with exactly three fractional digits, while a
    fixture names the same moment without them.  Comparing at second precision
    lets one literal serve both without weakening the assertion, because every
    instant this suite pins falls on a whole second.
    """
    assert isinstance(value, str), f"expected an ISO 8601 instant string, got {value!r}"
    match = _INSTANT_RE.match(value)
    assert match, f"not an ISO 8601 UTC instant: {value!r}"
    fraction = match.group(2)
    if fraction is not None:
        assert set(fraction[1:]) <= set("0"), (
            f"instant {value!r} carries a non-zero fractional part; this suite only "
            "pins whole-second instants"
        )
    return f"{match.group(1)}Z"


def assert_instant(actual: Any, expected: str, field: str = "instant") -> None:
    """Assert that ``actual`` names the same UTC instant as ``expected``."""
    assert actual is not None, f"{field} is null, expected {expected}"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{field} is {actual!r}, expected {expected!r}"
    )


def assert_instant_format(value: Any, field: str = "instant") -> None:
    """Assert the published rendering: ISO 8601 UTC with three fractional digits."""
    assert isinstance(value, str), f"{field} is not a string: {value!r}"
    assert is_iso8601_timestamp(value), f"{field} is not an ISO 8601 UTC instant: {value!r}"


def assert_date(actual: Any, expected: str, field: str = "date") -> None:
    """Assert a UTC calendar day rendered as ``YYYY-MM-DD``."""
    assert actual is not None, f"{field} is null, expected {expected}"
    assert _DATE_RE.match(str(actual)), f"{field} is not a YYYY-MM-DD date: {actual!r}"
    assert actual == expected, f"{field} is {actual!r}, expected {expected!r}"


def assert_null(payload: JsonDict, *fields: str) -> None:
    for field in fields:
        assert field in payload, f"field {field!r} is absent from {sorted(payload)}"
        assert payload[field] is None, f"{field} is {payload[field]!r}, expected null"


def assert_not_null(payload: JsonDict, *fields: str) -> None:
    for field in fields:
        assert payload.get(field) is not None, f"{field} is null, expected a value"


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


def assert_object_envelope(response: requests.Response, expected_status: int = 200) -> JsonDict:
    """Validate the single-resource envelope and return the resource object."""
    body = response.json()
    assert body.get("response_type") == "object", (
        f"response_type is {body.get('response_type')!r}, expected 'object'"
    )
    data = validate_success(response, expected_status)
    assert isinstance(data, dict), f"data is not an object: {data!r}"
    return data


def assert_created(response: requests.Response) -> JsonDict:
    """Validate a 201 Created single-resource envelope."""
    return assert_object_envelope(response, 201)


def assert_ok(response: requests.Response) -> JsonDict:
    """Validate a 200 OK single-resource envelope."""
    return assert_object_envelope(response, 200)


def assert_list(
    response: requests.Response,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    page_size: Optional[int] = None,
) -> Tuple[List[JsonDict], JsonDict]:
    """Validate a collection envelope and optionally pin its pagination meta."""
    body = response.json()
    assert body.get("response_type") == "array", (
        f"response_type is {body.get('response_type')!r}, expected 'array'"
    )
    rows, meta = validate_paginated(response)
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"total_count is {meta['total_count']}, expected {total_count}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"has_more is {meta['has_more']!r}, expected {has_more!r}"
        )
    if limit is not None:
        assert meta["limit"] == limit, f"limit is {meta['limit']}, expected {limit}"
    if offset is not None:
        assert meta["offset"] == offset, f"offset is {meta['offset']}, expected {offset}"
    if page_size is not None:
        assert len(rows) == page_size, (
            f"page carries {len(rows)} rows, expected {page_size}"
        )
    return rows, meta


def assert_total_count(response: requests.Response, total_count: int) -> List[JsonDict]:
    rows, _ = assert_list(response, total_count=total_count)
    return rows


def assert_error(
    response: requests.Response, expected_error_id: str
) -> JsonDict:
    """Validate the error envelope; the HTTP status is cross-checked from the map."""
    body = response.json()
    assert body.get("response_type") == "error", (
        f"response_type is {body.get('response_type')!r}, expected 'error'"
    )
    meta = body.get("meta") or {}
    assert set(meta) == {"api_request_id", "api_request_timestamp"}, (
        "an error response's meta carries only api_request_id and "
        f"api_request_timestamp, got {sorted(meta)}"
    )
    payload = validate_error(response, expected_error_id)
    assert isinstance(payload.get("message"), str) and payload["message"].strip(), (
        f"error message is empty: {payload!r}"
    )
    return payload


# ---------------------------------------------------------------------------
# Housekeeping properties
# ---------------------------------------------------------------------------


def assert_common_fields(entity: JsonDict, expected_version: Optional[int] = None) -> None:
    """Assert the four housekeeping properties of a mutable resource."""
    for field in HOUSEKEEPING_FIELDS:
        assert field in entity, f"housekeeping field {field!r} is absent"
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']!r}"
    assert_instant_format(entity["created_at"], "created_at")
    assert_instant_format(entity["updated_at"], "updated_at")
    assert isinstance(entity["version"], int) and not isinstance(entity["version"], bool), (
        f"version is not an integer: {entity['version']!r}"
    )
    assert entity["version"] >= 1, f"version is {entity['version']}, expected at least 1"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"version is {entity['version']}, expected {expected_version}"
        )


def assert_event_fields(record: JsonDict) -> None:
    """Assert the reduced property set of an immutable event record."""
    for field in EVENT_FIELDS:
        assert field in record, f"event field {field!r} is absent"
    assert is_valid_uuid(record["id"]), f"id is not a UUID: {record['id']!r}"
    assert_instant_format(record["created_at"], "created_at")
    for forbidden in ("updated_at", "version"):
        assert forbidden not in record, (
            f"{forbidden!r} must be absent from an immutable event record entirely, "
            f"got {record[forbidden]!r}"
        )


def assert_fields(entity: JsonDict, **expected: Any) -> None:
    """Assert a batch of exact field values with a readable failure message."""
    for field, value in expected.items():
        assert field in entity, f"field {field!r} is absent from {sorted(entity)}"
        actual = entity[field]
        if isinstance(value, bool) or value is None:
            assert actual is value, f"{field} is {actual!r}, expected {value!r}"
        else:
            assert actual == value, f"{field} is {actual!r}, expected {value!r}"


def assert_money(entity: JsonDict, **expected: int) -> None:
    """Assert money fields, insisting each is a JSON integer of cents."""
    for field, value in expected.items():
        assert field in entity, f"money field {field!r} is absent from {sorted(entity)}"
        actual = entity[field]
        assert isinstance(actual, int) and not isinstance(actual, bool), (
            f"{field} is {actual!r}; money must be a JSON integer of cents"
        )
        assert actual == value, f"{field} is {actual}, expected {value}"


# ---------------------------------------------------------------------------
# The two-dimensional unit state model
# ---------------------------------------------------------------------------


def assert_unit_position(
    unit: JsonDict,
    availability_state: Optional[str] = None,
    condition_state: Optional[str] = None,
    condition_grade: Optional[str] = None,
    quarantine_hold: Optional[bool] = None,
) -> None:
    """Assert a rental unit's logistics and physical dimensions independently."""
    if availability_state is not None:
        assert unit["availability_state"] == availability_state, (
            f"availability_state is {unit['availability_state']!r}, "
            f"expected {availability_state!r}"
        )
    if condition_state is not None:
        assert unit["condition_state"] == condition_state, (
            f"condition_state is {unit['condition_state']!r}, expected {condition_state!r}"
        )
    if condition_grade is not None:
        assert unit["condition_grade"] == condition_grade, (
            f"condition_grade is {unit['condition_grade']!r}, expected {condition_grade!r}"
        )
    if quarantine_hold is not None:
        assert unit["quarantine_hold"] is quarantine_hold, (
            f"quarantine_hold is {unit['quarantine_hold']!r}, expected {quarantine_hold!r}"
        )


def assert_depth_fields(
    style: JsonDict,
    floor_ready_unit_count: Optional[int] = None,
    active_unit_count: Optional[int] = None,
    required_depth_units: Optional[int] = None,
    depth_gap_units: Optional[int] = None,
    replenishment_flag: Optional[bool] = None,
    demand_score: Optional[int] = None,
) -> None:
    """Assert the derived depth-planning block of a style."""
    expectations = {
        "floor_ready_unit_count": floor_ready_unit_count,
        "active_unit_count": active_unit_count,
        "required_depth_units": required_depth_units,
        "depth_gap_units": depth_gap_units,
        "replenishment_flag": replenishment_flag,
        "demand_score": demand_score,
    }
    for field, value in expectations.items():
        if value is None:
            continue
        actual = style[field]
        if isinstance(value, bool):
            assert actual is value, f"{field} is {actual!r}, expected {value!r}"
        else:
            assert actual == value, f"{field} is {actual!r}, expected {value!r}"


def assert_position_count_conserved(
    before: Sequence[JsonDict], after: Sequence[JsonDict]
) -> None:
    """Assert the unit-position count for each style/size pair is unchanged."""
    counted = (
        "IN_STOCK",
        "RESERVED",
        "OUT",
        "INBOUND",
        "PROCESSING",
        "RETIRED",
        "SOLD",
    )

    def tally(units: Iterable[JsonDict]) -> Dict[Tuple[str, str], int]:
        out: Dict[Tuple[str, str], int] = {}
        for unit in units:
            if unit["availability_state"] in counted:
                key = (unit["style_id"], unit["size"])
                out[key] = out.get(key, 0) + 1
        return out

    assert tally(before) == tally(after), (
        f"unit positions drifted: {tally(before)} became {tally(after)}"
    )


# ---------------------------------------------------------------------------
# The fee ledger
# ---------------------------------------------------------------------------


def assert_ledger_entry(
    entry: JsonDict,
    kind: str,
    amount_cents: int,
    balance_after_cents: int,
    direction: Optional[str] = None,
) -> None:
    """Assert one append-only ledger row, including its derived direction."""
    assert_event_fields(entry)
    assert entry["kind"] == kind, f"kind is {entry['kind']!r}, expected {kind!r}"
    assert_money(entry, amount_cents=amount_cents, balance_after_cents=balance_after_cents)
    expected_direction = direction
    if expected_direction is None:
        expected_direction = "DEBIT" if amount_cents > 0 else "CREDIT"
    if amount_cents != 0:
        assert entry["direction"] == expected_direction, (
            f"direction is {entry['direction']!r}, expected {expected_direction!r}"
        )


def assert_balance_invariant(member: JsonDict, entries: Sequence[JsonDict]) -> None:
    """Assert the member's balance equals the signed sum of their ledger rows."""
    signed_sum = sum(entry["amount_cents"] for entry in entries)
    assert member["outstanding_fee_cents"] == signed_sum, (
        f"outstanding_fee_cents is {member['outstanding_fee_cents']}, but the signed "
        f"sum of {len(entries)} ledger rows is {signed_sum}"
    )
    running = 0
    for index, entry in enumerate(entries):
        running += entry["amount_cents"]
        assert entry["balance_after_cents"] == running, (
            f"ledger row {index} reports balance_after_cents "
            f"{entry['balance_after_cents']}, expected the running sum {running}"
        )


# ---------------------------------------------------------------------------
# Arithmetic mirrors used to derive expected values
# ---------------------------------------------------------------------------


def round_half_up(value: Any) -> int:
    """Round to a whole cent, half away from zero, exactly as the money rules do."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_units(numerator: int, denominator: int) -> int:
    """Ceiling division, as depth planning requires rather than a half-up round."""
    return -(-numerator // denominator)


def clamp_score(value: int, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, value))
