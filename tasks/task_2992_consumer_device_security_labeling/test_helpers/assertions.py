"""Domain assertion helpers.

Shape assertions follow the PRD's common-field rule: every resource carries
`id`, `created_at`, `updated_at` and `version`, except the immutable catalogue
records (security criteria and recognition surveys) whose payloads carry only
`id` and `created_at`.
"""
from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)

from .constants import canonical_instant

# --------------------------------------------------------------------------
# Common field shape
# --------------------------------------------------------------------------
MUTABLE_COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
IMMUTABLE_COMMON_FIELDS = ("id", "created_at")


def assert_common_fields(entity: Dict[str, Any]) -> None:
    """`id`, `created_at`, `updated_at` and `version` on a mutable resource."""
    for field in MUTABLE_COMMON_FIELDS:
        assert field in entity, f"missing common field {field!r} in {sorted(entity)}"
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int) and entity["version"] >= 1, entity["version"]


def assert_immutable_common_fields(entity: Dict[str, Any]) -> None:
    """`id` and `created_at` only - `updated_at` and `version` must be absent."""
    for field in IMMUTABLE_COMMON_FIELDS:
        assert field in entity, f"missing common field {field!r} in {sorted(entity)}"
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert "updated_at" not in entity, "updated_at must be absent on an immutable record"
    assert "version" not in entity, "version must be absent on an immutable record"


def assert_fields_present(entity: Dict[str, Any], *fields: str) -> None:
    missing = [f for f in fields if f not in entity]
    assert not missing, f"missing fields {missing} in {sorted(entity)}"


def assert_field_absent(entity: Dict[str, Any], field: str) -> None:
    assert field not in entity, f"{field!r} must be absent, got {entity.get(field)!r}"


# --------------------------------------------------------------------------
# Instants and numbers
# --------------------------------------------------------------------------
def assert_instant_equals(actual: Optional[str], expected: Optional[str], label: str = "instant") -> None:
    """Compare two instants after normalising fractional-second width."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def assert_instant(value: Any, label: str = "instant") -> None:
    assert isinstance(value, str) and is_iso8601_timestamp(value), f"{label} is not an instant: {value!r}"


def assert_money_cents(value: Any, expected: int, label: str = "amount_cents") -> None:
    """Monetary amounts are integer cents rendered as JSON numbers."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {type(value).__name__}: {value!r}"
    )
    assert value == expected, f"{label}: expected {expected}, got {value}"


def assert_score(value: Any, expected: float, label: str = "score") -> None:
    """Scores are numbers carrying exactly two decimal places of significance."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be a JSON number, got {type(value).__name__}: {value!r}"
    )
    assert round(float(value), 2) == round(float(expected), 2), (
        f"{label}: expected {expected}, got {value}"
    )
    assert abs(float(value) - round(float(value), 2)) < 1e-9, (
        f"{label} carries more than two decimals: {value!r}"
    )


def assert_two_decimals(value: Any, label: str = "value") -> None:
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be a JSON number, got {value!r}"
    )
    assert abs(float(value) - round(float(value), 2)) < 1e-9, (
        f"{label} carries more than two decimals: {value!r}"
    )


# --------------------------------------------------------------------------
# List responses
# --------------------------------------------------------------------------
def validate_unpaginated(response) -> List[Dict[str, Any]]:
    """A collection response whose `data` is a bare JSON array.

    Use this for the zero-or-one element registry-entry read and for any other
    array-valued read whose `meta` carries no pagination fields.
    """
    data = validate_success(response)
    assert isinstance(data, list), f"expected a bare array in data, got {type(data).__name__}"
    return data


def assert_ids_in_order(items: Sequence[Dict[str, Any]], expected_ids: Sequence[str]) -> None:
    actual = [item["id"] for item in items]
    assert actual == list(expected_ids), f"expected order {list(expected_ids)}, got {actual}"


def assert_contains_id(items: Sequence[Dict[str, Any]], entity_id: str) -> None:
    assert any(item["id"] == entity_id for item in items), (
        f"{entity_id} absent from {[i['id'] for i in items]}"
    )


def assert_excludes_id(items: Sequence[Dict[str, Any]], entity_id: str) -> None:
    assert all(item["id"] != entity_id for item in items), f"{entity_id} should not be listed"


def assert_pagination_meta(
    meta: Dict[str, Any],
    limit: int,
    offset: int,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    """`limit`, `offset`, `total_count` and `has_more` as declared for list reads."""
    assert meta.get("limit") == limit, f"limit: expected {limit}, got {meta.get('limit')}"
    assert meta.get("offset") == offset, f"offset: expected {offset}, got {meta.get('offset')}"
    if total_count is not None:
        assert meta.get("total_count") == total_count, (
            f"total_count: expected {total_count}, got {meta.get('total_count')}"
        )
    if has_more is not None:
        assert meta.get("has_more") is has_more, (
            f"has_more: expected {has_more}, got {meta.get('has_more')}"
        )


# --------------------------------------------------------------------------
# Status assertions
# --------------------------------------------------------------------------
def assert_status(entity: Dict[str, Any], field: str, expected: str) -> None:
    actual = entity.get(field)
    expected_value = getattr(expected, "value", expected)
    assert actual == expected_value, f"{field}: expected {expected_value!r}, got {actual!r}"


def assert_assessment_status(assessment: Dict[str, Any], expected: str) -> None:
    assert_status(assessment, "status", expected)


def assert_grant_statuses(grant: Dict[str, Any], grant_status: str, registry_publication_status: str) -> None:
    """The two independent status dimensions a label grant carries."""
    assert_status(grant, "grant_status", grant_status)
    assert_status(grant, "registry_publication_status", registry_publication_status)


def assert_case_statuses(case: Dict[str, Any], case_status: str, penalty_status: str) -> None:
    """The two independent status dimensions an enforcement case carries."""
    assert_status(case, "case_status", case_status)
    assert_status(case, "penalty_status", penalty_status)


def assert_version_is(entity: Dict[str, Any], expected: int) -> None:
    assert entity.get("version") == expected, (
        f"version: expected {expected}, got {entity.get('version')}"
    )


def assert_unchanged(before: Dict[str, Any], after: Dict[str, Any], *fields: str) -> None:
    """Nothing in `fields` moved - used to prove a rejected write had no effect."""
    for field in fields:
        assert before.get(field) == after.get(field), (
            f"{field} changed from {before.get(field)!r} to {after.get(field)!r}"
        )
    if "version" in before and "version" in after:
        assert before["version"] == after["version"], (
            f"version changed from {before['version']} to {after['version']}"
        )


# --------------------------------------------------------------------------
# Conserved ledgers
# --------------------------------------------------------------------------
def assert_bench_hour_ledger(lab: Dict[str, Any], reserved: Optional[int] = None) -> None:
    """`reserved_bench_hours + available_bench_hours == total_bench_hours`."""
    total = lab["total_bench_hours"]
    reserved_actual = lab["reserved_bench_hours"]
    available = lab["available_bench_hours"]
    assert reserved_actual + available == total, (
        f"bench-hour ledger broken: reserved {reserved_actual} + available {available} != total {total}"
    )
    if reserved is not None:
        assert reserved_actual == reserved, (
            f"reserved_bench_hours: expected {reserved}, got {reserved_actual}"
        )


def assert_penalty_ledger(
    manufacturer: Dict[str, Any],
    outstanding: Optional[int] = None,
    paid: Optional[int] = None,
    vacated: Optional[int] = None,
) -> None:
    """`outstanding + paid + vacated == total_assessed`, all in whole cents."""
    total = manufacturer["total_assessed_penalty_cents"]
    out = manufacturer["outstanding_penalty_cents"]
    pd = manufacturer["paid_penalty_cents"]
    vac = manufacturer["vacated_penalty_cents"]
    for label, value in (
        ("total_assessed_penalty_cents", total),
        ("outstanding_penalty_cents", out),
        ("paid_penalty_cents", pd),
        ("vacated_penalty_cents", vac),
    ):
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{label} must be an integer number of cents, got {value!r}"
        )
    assert out + pd + vac == total, (
        f"penalty ledger broken: outstanding {out} + paid {pd} + vacated {vac} != total {total}"
    )
    if outstanding is not None:
        assert out == outstanding, f"outstanding_penalty_cents: expected {outstanding}, got {out}"
    if paid is not None:
        assert pd == paid, f"paid_penalty_cents: expected {paid}, got {pd}"
    if vacated is not None:
        assert vac == vacated, f"vacated_penalty_cents: expected {vacated}, got {vac}"
