"""Domain assertions.

Structural checks the contract demands of every response — the envelope, the
common property set, the append-only receipt surface, the two conservation
ledgers, timestamp rendering and decimal precision — expressed once so a test
can state its intent in a single line.

Instant comparisons always run through ``canonical_instant`` so that two
spellings of the same instant compare equal; raw string comparison would turn a
difference in fractional-second width into a false failure.
"""

import re
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant
from .constants import (
    RECEIPT_OMITTED_COMMON_FIELDS,
)

# An instant rendered exactly as the contract renders stamped timestamps:
# ISO 8601 UTC with three fractional digits.
_MILLIS_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


# ── Envelope ───────────────────────────────────────────────────────────────

def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """The response envelope carries a request identifier and a stamped instant."""
    assert "meta" in body, f"Response envelope has no meta block: {body!r}"
    meta = body["meta"]
    request_id = meta.get("api_request_id")
    assert isinstance(request_id, str), f"meta.api_request_id must be a string: {meta!r}"
    assert request_id.startswith("req_"), (
        f"meta.api_request_id must start with 'req_': {request_id!r}"
    )
    stamp = meta.get("api_request_timestamp")
    assert isinstance(stamp, str), f"meta.api_request_timestamp must be a string: {meta!r}"
    assert_millis_instant(stamp)


def assert_object_envelope(body: Dict[str, Any]) -> None:
    """A single-resource response reports the object shape."""
    assert_envelope_meta(body)
    assert body.get("response_type") == "object", (
        f"Expected response_type 'object', got {body.get('response_type')!r}"
    )


def assert_array_envelope(body: Dict[str, Any]) -> None:
    """A collection response reports the array shape."""
    assert_envelope_meta(body)
    assert body.get("response_type") == "array", (
        f"Expected response_type 'array', got {body.get('response_type')!r}"
    )
    assert isinstance(body.get("data"), list), "A collection response's data must be a list"


def assert_list_page(
    body: Dict[str, Any],
    total_count: Optional[int] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    has_more: Optional[bool] = None,
    page_size: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Check the pagination block a collection echoes, and return the page."""
    assert_array_envelope(body)
    meta = body["meta"]
    rows = body["data"]
    if total_count is not None:
        assert meta.get("total_count") == total_count, (
            f"Expected total_count {total_count}, got {meta.get('total_count')}"
        )
    if limit is not None:
        assert meta.get("limit") == limit, f"Expected limit {limit}, got {meta.get('limit')}"
    if offset is not None:
        assert meta.get("offset") == offset, (
            f"Expected offset {offset}, got {meta.get('offset')}"
        )
    if has_more is not None:
        assert meta.get("has_more") is has_more, (
            f"Expected has_more {has_more}, got {meta.get('has_more')!r}"
        )
    if page_size is not None:
        assert len(rows) == page_size, f"Expected {page_size} rows on the page, got {len(rows)}"
    return rows


# ── Timestamps ─────────────────────────────────────────────────────────────

def assert_millis_instant(value: str) -> None:
    """A stamped instant is ISO 8601 UTC with three fractional digits."""
    assert isinstance(value, str) and _MILLIS_INSTANT.match(value), (
        f"Not an ISO 8601 UTC instant with three fractional digits: {value!r}"
    )


def assert_instant_format(value: str) -> None:
    """A value is a well-formed ISO 8601 UTC instant."""
    assert is_iso8601_timestamp(value), f"Not an ISO 8601 UTC instant: {value!r}"


def assert_instant(actual: Optional[str], expected: Optional[str], label: str = "instant") -> None:
    """Two instants name the same moment, whatever their fractional width."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


# ── Common property set ────────────────────────────────────────────────────

def assert_identity(row: Dict[str, Any]) -> None:
    """Every row is identified by a bare UUID."""
    row_id = row.get("id")
    assert is_valid_uuid(row_id), f"Row id must be a UUID with no type prefix: {row_id!r}"


def assert_mutable_common_fields(row: Dict[str, Any], version: Optional[int] = None) -> None:
    """A versioned entity carries id, created_at, updated_at and version."""
    assert_identity(row)
    assert_millis_instant(row.get("created_at"))
    assert_millis_instant(row.get("updated_at"))
    assert isinstance(row.get("version"), int), f"version must be an integer: {row!r}"
    assert row["version"] >= 1, f"version starts at 1, got {row['version']}"
    if version is not None:
        assert row["version"] == version, (
            f"Expected version {version}, got {row['version']}"
        )


def assert_created_equals_updated(row: Dict[str, Any]) -> None:
    """A row that has never been mutated reports the same two stamps and version 1."""
    assert_instant(row.get("updated_at"), row.get("created_at"), "updated_at")
    assert row.get("version") == 1, f"A freshly created row is at version 1: {row!r}"


def assert_receipt_common_fields(row: Dict[str, Any]) -> None:
    """An append-only receipt carries only id and created_at from the common set."""
    assert_identity(row)
    assert_millis_instant(row.get("created_at"))
    for field in RECEIPT_OMITTED_COMMON_FIELDS:
        assert field not in row, (
            f"An append-only receipt is never updated or versioned, so it must not "
            f"carry {field!r}: {row!r}"
        )


def assert_version_advanced(new_row: Dict[str, Any], old_version: int, by: int = 1) -> None:
    """An accepted mutation advances the row's version by exactly ``by``."""
    assert new_row.get("version") == old_version + by, (
        f"Expected version {old_version + by}, got {new_row.get('version')}"
    )


def assert_version_unchanged(row: Dict[str, Any], version: int) -> None:
    """A refused write leaves the row's version where it was."""
    assert row.get("version") == version, (
        f"A refused write must not advance the version: expected {version}, "
        f"got {row.get('version')}"
    )


# ── Numbers ────────────────────────────────────────────────────────────────

def assert_two_dp(value: Any, label: str = "value") -> Decimal:
    """A two-decimal quantity is rendered with no more than two decimal places."""
    assert isinstance(value, (int, float)), f"{label} must be a JSON number: {value!r}"
    quantised = Decimal(str(value))
    assert -quantised.as_tuple().exponent <= 2, (
        f"{label} carries more than two decimal places: {value!r}"
    )
    return quantised


def assert_score(actual: Any, expected: str, label: str = "discrimination_score") -> None:
    """A discrimination score equals this exact two-decimal figure."""
    quantised = assert_two_dp(actual, label)
    assert quantised == Decimal(expected), (
        f"{label}: expected {expected}, got {actual!r}"
    )


def assert_bps(value: Any, expected: Optional[int] = None, label: str = "rate_bps") -> None:
    """A rate in basis points is a plain integer, never a rounded float."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of basis points: {value!r}"
    )
    if expected is not None:
        assert value == expected, f"{label}: expected {expected}, got {value}"


# ── Conservation ledgers ───────────────────────────────────────────────────

def assert_solicitation_ledger(request: Dict[str, Any], total: Optional[int] = None) -> None:
    """The five solicitation buckets always add up to ``solicitation_count``."""
    buckets = (
        request["pending_count"],
        request["shared_count"],
        request["declined_count"],
        request["expired_count"],
        request["withdrawn_count"],
    )
    assert sum(buckets) == request["solicitation_count"], (
        "solicitation_count must equal pending + shared + declined + expired + "
        f"withdrawn; got {request['solicitation_count']} against {buckets}"
    )
    if total is not None:
        assert request["solicitation_count"] == total, (
            f"Expected solicitation_count {total}, got {request['solicitation_count']}"
        )


def assert_solicitation_buckets(
    request: Dict[str, Any],
    pending: int,
    shared: int,
    declined: int,
    expired: int,
    withdrawn: int,
) -> None:
    """Every solicitation bucket sits exactly here, and the sum still reconciles."""
    observed = (
        request["pending_count"],
        request["shared_count"],
        request["declined_count"],
        request["expired_count"],
        request["withdrawn_count"],
    )
    assert observed == (pending, shared, declined, expired, withdrawn), (
        f"Expected buckets (pending, shared, declined, expired, withdrawn) "
        f"{(pending, shared, declined, expired, withdrawn)}, got {observed}"
    )
    assert_solicitation_ledger(request)


def assert_footage_ledger(
    resident: Dict[str, Any],
    lifetime: Optional[int] = None,
    retained: Optional[int] = None,
    purged: Optional[int] = None,
) -> None:
    """Lifetime footage seconds always equal retained plus purged seconds."""
    assert (
        resident["lifetime_shared_footage_seconds"]
        == resident["retained_footage_seconds"] + resident["purged_footage_seconds"]
    ), (
        "lifetime_shared_footage_seconds must equal retained_footage_seconds + "
        f"purged_footage_seconds; got {resident['lifetime_shared_footage_seconds']} "
        f"against {resident['retained_footage_seconds']} + "
        f"{resident['purged_footage_seconds']}"
    )
    if lifetime is not None:
        assert resident["lifetime_shared_footage_seconds"] == lifetime, (
            f"Expected lifetime_shared_footage_seconds {lifetime}, got "
            f"{resident['lifetime_shared_footage_seconds']}"
        )
    if retained is not None:
        assert resident["retained_footage_seconds"] == retained, (
            f"Expected retained_footage_seconds {retained}, got "
            f"{resident['retained_footage_seconds']}"
        )
    if purged is not None:
        assert resident["purged_footage_seconds"] == purged, (
            f"Expected purged_footage_seconds {purged}, got "
            f"{resident['purged_footage_seconds']}"
        )


def assert_fanout_conservation(post: Dict[str, Any], cap: int) -> None:
    """Delivered plus suppressed alerts equal the capped candidate count."""
    expected = min(post["alert_candidate_count"], cap)
    assert post["alert_fanout_count"] + post["alert_suppressed_count"] == expected, (
        "alert_fanout_count + alert_suppressed_count must equal "
        f"min(alert_candidate_count, alert_fanout_cap) = {expected}; got "
        f"{post['alert_fanout_count']} + {post['alert_suppressed_count']}"
    )


def assert_strike_ladder(resident: Dict[str, Any]) -> None:
    """The strike score weighs a discrimination strike twice an accuracy strike."""
    expected = resident["accuracy_strike_count"] + 2 * resident["discrimination_strike_count"]
    assert resident["total_strike_score"] == expected, (
        "total_strike_score must equal accuracy_strike_count plus twice "
        f"discrimination_strike_count = {expected}; got {resident['total_strike_score']}"
    )


# ── Ordering ───────────────────────────────────────────────────────────────

def assert_ids_in_order(rows: Sequence[Dict[str, Any]], expected_ids: Sequence[str]) -> None:
    """A page carries exactly these identifiers, in exactly this order."""
    observed = [row["id"] for row in rows]
    assert observed == list(expected_ids), (
        f"Expected identifiers in order {list(expected_ids)}, got {observed}"
    )


def assert_field_sequence(
    rows: Sequence[Dict[str, Any]], field: str, expected: Sequence[Any]
) -> None:
    """A page's values for one field run in exactly this order."""
    observed = [row.get(field) for row in rows]
    assert observed == list(expected), (
        f"Expected {field} sequence {list(expected)}, got {observed}"
    )


def assert_ascending(rows: Sequence[Dict[str, Any]], field: str) -> None:
    """A page is ordered by ascending values of one field."""
    values = [row.get(field) for row in rows]
    assert values == sorted(values), f"Rows are not ordered by ascending {field}: {values}"


# ── Entity spot checks ─────────────────────────────────────────────────────

def assert_zero_counters(row: Dict[str, Any], *fields: str) -> None:
    """A freshly created row starts every named counter at zero."""
    for field in fields:
        assert row.get(field) == 0, f"Expected {field} to start at 0, got {row.get(field)!r}"


def assert_nulls(row: Dict[str, Any], *fields: str) -> None:
    """Each named field is present and null."""
    for field in fields:
        assert field in row, f"Expected field {field!r} to be present: {row!r}"
        assert row[field] is None, f"Expected {field} to be null, got {row[field]!r}"


def assert_subset(row: Dict[str, Any], expected: Dict[str, Any]) -> None:
    """Every named field carries exactly this value."""
    for field, value in expected.items():
        assert row.get(field) == value, (
            f"Expected {field} == {value!r}, got {row.get(field)!r}"
        )
