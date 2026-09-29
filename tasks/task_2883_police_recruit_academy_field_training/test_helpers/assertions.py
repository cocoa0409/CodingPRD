"""Domain assertions.

These build on the framework validators, which are the single place the
response envelope is stripped.  Nothing here unwraps ``["data"]`` a second
time: an assertion helper that takes an ``entity`` argument expects the object
a validator already returned.

Timestamp comparisons are always made through ``same_instant`` /
``assert_instant_equals``, which canonicalise both sides before comparing, so a
correct implementation is never failed for the width of its fractional-second
field.
"""
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .api_errors import LADDER_RUNG
from .constants import (
    ATTRITION_STAGE_ORDER,
    HOURS_DECIMALS,
    META_KEYS,
    REQUEST_ID_PREFIX,
    money2,
    parse_instant,
    rate4,
)


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------
def assert_is_json_number(value: Any, label: str = "value") -> None:
    """A monetary/hours/score reading must be a JSON number, never a string."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be a JSON number, got {type(value).__name__}: {value!r}"
    )


def assert_decimal_equals(actual: Any, expected, label: str = "value",
                          places: int = HOURS_DECIMALS) -> None:
    """Compare a numeric reading against an expected value at fixed places."""
    assert_is_json_number(actual, label)
    got = Decimal(str(actual))
    want = Decimal(str(expected))
    assert got.quantize(Decimal(1).scaleb(-places)) == want.quantize(
        Decimal(1).scaleb(-places)), f"{label}: expected {want}, got {got}"


def assert_hours_equals(actual: Any, expected, label: str = "hours") -> None:
    assert_decimal_equals(actual, money2(expected), label, HOURS_DECIMALS)


def assert_score_equals(actual: Any, expected, label: str = "score") -> None:
    assert_decimal_equals(actual, money2(expected), label, HOURS_DECIMALS)


def assert_rate_equals(actual: Any, expected, label: str = "rate") -> None:
    assert_decimal_equals(actual, rate4(expected), label, 4)


def assert_decimal_places_at_most(value: Any, places: int,
                                  label: str = "value") -> None:
    assert_is_json_number(value, label)
    exponent = Decimal(str(value)).normalize().as_tuple().exponent
    assert exponent >= -places, (
        f"{label} carries more than {places} decimal places: {value!r}")


# ---------------------------------------------------------------------------
# Instants and dates
# ---------------------------------------------------------------------------
def same_instant(left: str, right: str) -> bool:
    """True when two ISO 8601 strings name the same moment, whatever their width."""
    if left is None or right is None:
        return left is right
    return parse_instant(left) == parse_instant(right)


def assert_instant_equals(actual: Optional[str], expected: Optional[str],
                          label: str = "instant") -> None:
    assert same_instant(actual, expected), (
        f"{label}: expected the instant {expected!r}, got {actual!r}")


def assert_is_instant(value: Any, label: str = "instant") -> None:
    assert isinstance(value, str) and value, f"{label} must be a string: {value!r}"
    assert is_iso8601_timestamp(value), f"{label} is not ISO 8601: {value!r}"


def assert_is_date(value: Any, label: str = "date") -> None:
    assert isinstance(value, str), f"{label} must be a string: {value!r}"
    assert len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"{label} must be a YYYY-MM-DD calendar date: {value!r}")


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------
def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """Every response carries the full meta block."""
    meta = body["meta"]
    for key in META_KEYS:
        assert key in meta, f"meta is missing {key}"
    assert isinstance(meta["api_request_id"], str)
    assert meta["api_request_id"].startswith(REQUEST_ID_PREFIX), (
        f"api_request_id must start with {REQUEST_ID_PREFIX!r}: "
        f"{meta['api_request_id']!r}")
    assert_is_instant(meta["api_request_timestamp"], "api_request_timestamp")


def assert_request_timestamp_millis(timestamp: str) -> None:
    """The request timestamp is UTC with exactly three fractional digits."""
    assert timestamp.endswith("Z"), (
        f"api_request_timestamp must be UTC and end with Z: {timestamp!r}")
    assert "." in timestamp, (
        f"api_request_timestamp must carry fractional seconds: {timestamp!r}")
    fraction = timestamp.split(".")[1][:-1]
    assert len(fraction) == 3 and fraction.isdigit(), (
        f"api_request_timestamp must carry exactly three fractional digits: "
        f"{timestamp!r}")


# ---------------------------------------------------------------------------
# Common properties
# ---------------------------------------------------------------------------
def assert_common_fields(entity: Dict[str, Any], label: str = "entity") -> None:
    """id, created_at, updated_at and version are present and well formed."""
    assert is_valid_uuid(entity["id"]), f"{label}.id is not a UUID: {entity['id']!r}"
    assert_is_instant(entity["created_at"], f"{label}.created_at")
    assert_is_instant(entity["updated_at"], f"{label}.updated_at")
    assert isinstance(entity["version"], int) and entity["version"] >= 1, (
        f"{label}.version must be a positive integer: {entity.get('version')!r}")


def assert_append_only_fields(entity: Dict[str, Any],
                              label: str = "training record entry") -> None:
    """An append-only row carries id and created_at, and neither of the mutable pair."""
    assert is_valid_uuid(entity["id"]), f"{label}.id is not a UUID: {entity['id']!r}"
    assert_is_instant(entity["created_at"], f"{label}.created_at")
    for absent in ("updated_at", "version"):
        assert absent not in entity or entity[absent] is None, (
            f"{label} must not carry {absent}: {entity.get(absent)!r}")


def assert_version_is(entity: Dict[str, Any], expected: int,
                      label: str = "entity") -> None:
    assert entity["version"] == expected, (
        f"{label}.version: expected {expected}, got {entity['version']}")


def assert_unchanged(before: Dict[str, Any], after: Dict[str, Any],
                     fields: Iterable[str], label: str = "entity") -> None:
    for field in fields:
        assert before.get(field) == after.get(field), (
            f"{label}.{field} changed from {before.get(field)!r} "
            f"to {after.get(field)!r}")


# ---------------------------------------------------------------------------
# Precedence
# ---------------------------------------------------------------------------
def assert_ladder_precedence(observed_error_id: str, winner: str, loser: str) -> None:
    """The lower rung of two simultaneously violated rules is the one reported."""
    assert LADDER_RUNG[winner] < LADDER_RUNG[loser], (
        f"{winner} (rung {LADDER_RUNG[winner]}) is expected to sit above "
        f"{loser} (rung {LADDER_RUNG[loser]})")
    assert observed_error_id == winner, (
        f"expected {winner} to win precedence over {loser}, got {observed_error_id}")


# ---------------------------------------------------------------------------
# Ordered maps and reports
# ---------------------------------------------------------------------------
def assert_key_order(mapping: Dict[str, Any], expected_keys: List[str],
                     label: str = "map") -> None:
    """A derived map carries exactly these keys in exactly this order."""
    assert list(mapping.keys()) == list(expected_keys), (
        f"{label} keys: expected {list(expected_keys)}, got {list(mapping.keys())}")


def assert_stage_order(stages: List[Dict[str, Any]]) -> None:
    """The attrition report carries one entry per stage in the fixed order."""
    assert [s["stage_code"] for s in stages] == ATTRITION_STAGE_ORDER, (
        f"stages must read {ATTRITION_STAGE_ORDER}, got "
        f"{[s.get('stage_code') for s in stages]}")


def assert_created_at_ascending(rows: List[Dict[str, Any]],
                                label: str = "rows") -> None:
    stamps = [parse_instant(r["created_at"]) for r in rows]
    assert stamps == sorted(stamps), f"{label} are not in created_at ascending order"


def assert_skip_reason(skipped: List[Dict[str, Any]], recruit_id: str,
                       expected_reason: str) -> None:
    """The named recruit appears in the skipped array with this reason code."""
    matches = [row for row in skipped if row["recruit_id"] == recruit_id]
    assert matches, f"recruit {recruit_id} is absent from the skipped array"
    assert matches[0]["reason_code"] == expected_reason, (
        f"recruit {recruit_id}: expected skip reason {expected_reason}, "
        f"got {matches[0]['reason_code']}")


def find_entry(entries: List[Dict[str, Any]], **criteria) -> Optional[Dict[str, Any]]:
    """First training record entry matching every supplied field value."""
    for entry in entries:
        if all(entry.get(key) == value for key, value in criteria.items()):
            return entry
    return None


def count_entries(entries: List[Dict[str, Any]], **criteria) -> int:
    return sum(
        1 for entry in entries
        if all(entry.get(key) == value for key, value in criteria.items())
    )
