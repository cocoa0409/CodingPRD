"""Domain assertion helpers.

These wrap the repeated shape checks so that individual tests read as statements
about programme behaviour rather than about dictionaries.
"""
from typing import Any, Dict, Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant

_DECIMAL_TOLERANCE = 1e-9


# ------------------------------------------------------------------------- instants
def assert_instant_equals(actual: Optional[str], expected: Optional[str], label: str = "instant"):
    """Compare two instants ignoring sub-second textual width."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def assert_is_instant(value: Any, label: str = "instant"):
    assert isinstance(value, str) and is_iso8601_timestamp(value), (
        f"{label} is not an ISO-8601 instant: {value!r}"
    )
    assert canonical_instant(value).endswith("Z"), f"{label} is not UTC-suffixed: {value!r}"


def assert_three_fractional_digits(value: str, label: str = "timestamp"):
    """The API renders instants with exactly three fractional-second digits."""
    assert isinstance(value, str), f"{label} is not a string: {value!r}"
    body = value[:-1] if value.endswith("Z") else value
    assert "." in body, f"{label} carries no fractional part: {value!r}"
    assert len(body.split(".")[-1]) == 3, (
        f"{label} does not carry exactly three fractional digits: {value!r}"
    )


# --------------------------------------------------------------------- common fields
def assert_common_fields(entity: Dict[str, Any], label: str = "entity"):
    """id / created_at / updated_at / version, as every versioned entity carries them."""
    assert is_valid_uuid(entity.get("id")), f"{label}.id is not a UUID: {entity.get('id')!r}"
    assert_is_instant(entity.get("created_at"), f"{label}.created_at")
    assert_is_instant(entity.get("updated_at"), f"{label}.updated_at")
    assert isinstance(entity.get("version"), int) and not isinstance(entity.get("version"), bool), (
        f"{label}.version is not an integer: {entity.get('version')!r}"
    )
    assert entity["version"] >= 1, f"{label}.version is below 1: {entity['version']}"


def assert_measurement_fields(entity: Dict[str, Any], label: str = "entity"):
    """A measurement record carries only id and created_at from the common set."""
    assert is_valid_uuid(entity.get("id")), f"{label}.id is not a UUID: {entity.get('id')!r}"
    assert_is_instant(entity.get("created_at"), f"{label}.created_at")
    assert "updated_at" not in entity, f"{label} unexpectedly carries updated_at"
    assert "version" not in entity, f"{label} unexpectedly carries version"


def assert_version_bumped(before: Dict[str, Any], after: Dict[str, Any], by: int = 1):
    assert after["version"] == before["version"] + by, (
        f"version moved {before['version']} -> {after['version']}, expected +{by}"
    )


def assert_version_unchanged(before: Dict[str, Any], after: Dict[str, Any]):
    assert after["version"] == before["version"], (
        f"version changed {before['version']} -> {after['version']}"
    )


# ------------------------------------------------------------------------- envelopes
def assert_request_id(body: Dict[str, Any]):
    meta = body.get("meta") or {}
    request_id = meta.get("api_request_id")
    assert isinstance(request_id, str) and request_id.startswith("req_"), (
        f"meta.api_request_id is not a req_-prefixed string: {request_id!r}"
    )


# ---------------------------------------------------------------------- field compare
def assert_fields(entity: Dict[str, Any], label: str = "entity", **expected: Any):
    """Assert a subset of fields, canonicalising instants and tolerating float width."""
    problems: List[str] = []
    for field, want in expected.items():
        assert field in entity, f"{label} has no field {field!r}"
        got = entity[field]
        if isinstance(want, str) and canonical_instant(want) != want:
            if canonical_instant(got) != canonical_instant(want):
                problems.append(f"{field}: expected {want!r}, got {got!r}")
        elif isinstance(want, float) and isinstance(got, (int, float)):
            if abs(float(got) - want) > _DECIMAL_TOLERANCE:
                problems.append(f"{field}: expected {want!r}, got {got!r}")
        elif got != want:
            problems.append(f"{field}: expected {want!r}, got {got!r}")
    assert not problems, f"{label} field mismatch: " + "; ".join(problems)


def assert_decimal_equals(actual: Any, expected: float, label: str = "value"):
    """A monetary-style decimal is a JSON number, compared at full precision."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} is not a JSON number: {actual!r}"
    )
    assert abs(float(actual) - float(expected)) <= _DECIMAL_TOLERANCE, (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_nulls(entity: Dict[str, Any], fields: Iterable[str], label: str = "entity"):
    for field in fields:
        assert field in entity, f"{label} has no field {field!r}"
        assert entity[field] is None, f"{label}.{field} should be null, got {entity[field]!r}"


# ----------------------------------------------------------------------- collections
def assert_ordered_by(items: Sequence[Dict[str, Any]], *keys: str, descending: bool = False):
    """Assert a list is sorted on the given keys, instants canonicalised."""
    def sort_key(item):
        return tuple(canonical_instant(item.get(k)) or "" if isinstance(item.get(k), str)
                     else item.get(k) for k in keys)

    values = [sort_key(i) for i in items]
    expected = sorted(values, reverse=descending)
    assert values == expected, f"list is not ordered by {keys} (descending={descending}): {values}"


def assert_id_sequence(items: Sequence[Dict[str, Any]], expected_ids: Sequence[str]):
    got = [i["id"] for i in items]
    assert got == list(expected_ids), f"expected id order {list(expected_ids)}, got {got}"


def assert_contains_ids(items: Sequence[Dict[str, Any]], expected_ids: Iterable[str]):
    got = {i["id"] for i in items}
    missing = [i for i in expected_ids if i not in got]
    assert not missing, f"ids missing from the list: {missing}"


def assert_excludes_ids(items: Sequence[Dict[str, Any]], excluded_ids: Iterable[str]):
    got = {i["id"] for i in items}
    present = [i for i in excluded_ids if i in got]
    assert not present, f"ids unexpectedly present in the list: {present}"


# ----------------------------------------------------------------- domain shorthands
def assert_pool_availability(
    product: Dict[str, Any],
    available_sustained_rpm: Optional[int] = None,
    available_monthly_calls: Optional[int] = None,
    allocated_sustained_rpm: Optional[int] = None,
    allocated_monthly_calls: Optional[int] = None,
):
    expected = {}
    if available_sustained_rpm is not None:
        expected["available_sustained_rpm"] = available_sustained_rpm
    if available_monthly_calls is not None:
        expected["available_monthly_calls"] = available_monthly_calls
    if allocated_sustained_rpm is not None:
        expected["allocated_sustained_rpm"] = allocated_sustained_rpm
    if allocated_monthly_calls is not None:
        expected["allocated_monthly_calls"] = allocated_monthly_calls
    assert_fields(product, "ApiProduct", **expected)


def assert_entitlement_dimensions(
    assignment: Dict[str, Any],
    entitlement_state: Optional[str] = None,
    throttle_state: Optional[str] = None,
):
    expected = {}
    if entitlement_state is not None:
        expected["entitlement_state"] = entitlement_state
    if throttle_state is not None:
        expected["throttle_state"] = throttle_state
    assert_fields(assignment, "QuotaAssignment", **expected)


def assert_trust_scores(
    developer: Dict[str, Any],
    trust_score: Optional[int] = None,
    audited_trust_score: Optional[int] = None,
):
    expected = {}
    if trust_score is not None:
        expected["trust_score"] = trust_score
    if audited_trust_score is not None:
        expected["audited_trust_score"] = audited_trust_score
    assert_fields(developer, "Developer", **expected)
