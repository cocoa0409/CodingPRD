"""Domain assertion helpers.

Instant comparison goes through :func:`canonicalize_instant` so a server that
emits ``2026-08-01T00:00:00.000Z`` and a PRD literal of ``2026-08-01T00:00:00Z``
compare equal: section 2.5 fixes the ISO 8601 UTC form but not its sub-second
width, so a raw string comparison would be testing formatting rather than
behaviour.

Money is asserted to arrive as an integer number of cents, never as a string,
because section 2.6 declares every monetary field an integer count of cents.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    ACCESS_STATUS_PENDING,
    BASE_QUOTA,
    BASE_SCORE,
    POSTURE_INCOMPLETE,
    STATUS_IN_GOOD_STANDING,
    SUSPENSION_REASON_NONE,
    TIER_PLATINUM,
    format_instant,
    parse_instant,
)
from .types import COMMON_FIELDS, EVENT_COMMON_FIELDS, JsonDict


# ── Instants ──────────────────────────────────────────────────────────────────
def canonicalize_instant(value: str) -> str:
    """Reduce an ISO 8601 UTC instant to second resolution with a Z suffix."""
    return format_instant(parse_instant(value))


def assert_instant_equals(actual: Any, expected: str, field: str = "instant") -> None:
    """Assert two ISO 8601 instants denote the same moment."""
    assert isinstance(actual, str), f"{field} should be an ISO 8601 string, got {actual!r}"
    assert canonicalize_instant(actual) == canonicalize_instant(expected), (
        f"{field} should be {expected}, got {actual}"
    )


def assert_instant_is_none(entity: JsonDict, field: str) -> None:
    """Assert an optional instant field is present and null."""
    assert field in entity, f"{field} should be present in the response"
    assert entity[field] is None, f"{field} should be null, got {entity[field]!r}"


def assert_valid_instant(entity: JsonDict, field: str) -> None:
    """Assert a field carries a well-formed ISO 8601 UTC instant."""
    value = entity.get(field)
    assert isinstance(value, str), f"{field} should be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{field} should be ISO 8601 UTC, got {value!r}"


def assert_instant_order(entity: JsonDict, earlier_field: str, later_field: str) -> None:
    """Assert one instant field is strictly earlier than another."""
    earlier = parse_instant(entity[earlier_field])
    later = parse_instant(entity[later_field])
    assert earlier < later, (
        f"{earlier_field} ({entity[earlier_field]}) should precede "
        f"{later_field} ({entity[later_field]})"
    )


# ── Common resource properties (section 2.5) ──────────────────────────────────
def assert_common_fields(entity: JsonDict, expected_version: Optional[int] = None) -> None:
    """Assert the four common properties are present and well-formed."""
    for field in COMMON_FIELDS:
        assert field in entity, f"the response should carry the common property {field}"
    assert is_valid_uuid(entity["id"]), f"id should be a UUID, got {entity['id']!r}"
    assert_valid_instant(entity, "created_at")
    assert_valid_instant(entity, "updated_at")
    assert isinstance(entity["version"], int) and not isinstance(
        entity["version"], bool
    ), f"version should be an integer, got {entity['version']!r}"
    assert entity["version"] >= 0, "version should never be negative"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"version should be {expected_version}, got {entity['version']}"
        )


def assert_event_common_fields(entity: JsonDict) -> None:
    """Assert an append-only row carries only ``id`` and ``created_at``."""
    for field in EVENT_COMMON_FIELDS:
        assert field in entity, f"the response should carry {field}"
    assert is_valid_uuid(entity["id"]), f"id should be a UUID, got {entity['id']!r}"
    assert_valid_instant(entity, "created_at")
    assert "updated_at" not in entity, (
        "an immutable row carries no updated_at property at all"
    )
    assert "version" not in entity, (
        "an immutable row carries no version property at all"
    )


def assert_fields_present(entity: JsonDict, fields: Iterable[str]) -> None:
    """Assert every named field is present in the payload, even when null."""
    missing = [field for field in fields if field not in entity]
    assert not missing, f"the response is missing declared fields: {missing}"


def assert_version_bumped(before: JsonDict, after: JsonDict, by: int = 1) -> None:
    """Assert a successful write advanced the parent's version counter."""
    assert after["version"] == before["version"] + by, (
        f"version should advance from {before['version']} by {by}, got {after['version']}"
    )


# ── Money and ratios (section 2.6) ────────────────────────────────────────────
def assert_money_cents(entity: JsonDict, field: str, expected: int) -> None:
    """Assert a monetary field is an integer count of cents with the expected value."""
    value = entity.get(field)
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} should be an integer number of cents, got {value!r}"
    )
    assert value == expected, f"{field} should be {expected} cents, got {value}"


def assert_integer_field(entity: JsonDict, field: str, expected: int) -> None:
    """Assert an integer counter equals the expected value."""
    value = entity.get(field)
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} should be an integer, got {value!r}"
    )
    assert value == expected, f"{field} should be {expected}, got {value}"


def assert_ratio_four_places(value: Any, expected: float) -> None:
    """Assert a ratio matches to the four decimal places section 2.6 pins."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"a ratio should be a JSON number, got {value!r}"
    )
    assert round(float(value), 4) == round(expected, 4), (
        f"the ratio should be {expected} to four places, got {value}"
    )


# ── Birth-state assertions (section 3.1) ──────────────────────────────────────
def assert_vendor_birth_values(vendor: JsonDict) -> None:
    """Assert a freshly created vendor carries every declared birth value."""
    assert_integer_field(vendor, "provisional_compliance_score", BASE_SCORE)
    assert_integer_field(vendor, "adjudicated_compliance_score", BASE_SCORE)
    assert vendor["scorecard_tier"] == TIER_PLATINUM
    assert vendor["compliance_status"] == STATUS_IN_GOOD_STANDING
    assert_integer_field(vendor, "access_quota_in_effect", BASE_QUOTA)
    assert_integer_field(vendor, "authorizations_used_epoch", 0)
    assert_money_cents(vendor, "late_fee_balance_cents", 0)
    assert_integer_field(vendor, "open_pir_count", 0)
    assert_integer_field(vendor, "last_sweep_epoch", 0)


def assert_rep_birth_values(rep: JsonDict) -> None:
    """Assert a freshly registered representative carries every declared birth value."""
    assert rep["access_status"] == ACCESS_STATUS_PENDING
    assert rep["credential_posture"] == POSTURE_INCOMPLETE
    assert rep["suspension_reason"] == SUSPENSION_REASON_NONE
    assert rep["ever_credentialed"] is False
    assert_integer_field(rep, "open_authorization_count", 0)
    assert rep.get("revoked_by_user_id") is None
    assert rep.get("revoked_at_utc") is None
    assert rep.get("reinstated_at_utc") is None


# ── Listing assertions (section 2.3) ──────────────────────────────────────────
def assert_total_count(meta: Dict[str, Any], expected: int) -> None:
    """Assert a paginated envelope reports the expected total row count."""
    assert meta["total_count"] == expected, (
        f"total_count should be {expected}, got {meta['total_count']}"
    )


def assert_ids_in_order(items: Sequence[JsonDict], expected_ids: Sequence[str]) -> None:
    """Assert a listing returned exactly these ids in exactly this order."""
    actual = [item["id"] for item in items]
    assert actual == list(expected_ids), (
        f"the listing should return {list(expected_ids)} in order, got {actual}"
    )


def assert_created_at_ascending(items: Sequence[JsonDict]) -> None:
    """Assert a listing is ordered by ``created_at`` ascending."""
    stamps = [parse_instant(item["created_at"]) for item in items]
    assert stamps == sorted(stamps), "a listing should be ordered by created_at ascending"


def find_by_id(items: Sequence[JsonDict], target_id: str) -> JsonDict:
    """Return the row with the given id, failing the test when it is absent."""
    for item in items:
        if item["id"] == target_id:
            return item
    raise AssertionError(f"the listing does not contain the row {target_id}")


def ids_of(items: Sequence[JsonDict]) -> list:
    """The ids of a listing's rows, in the order returned."""
    return [item["id"] for item in items]
