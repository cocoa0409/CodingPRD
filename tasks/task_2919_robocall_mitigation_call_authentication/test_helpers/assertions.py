"""Assertion helpers.

The response envelope is unwrapped exactly once, by the ``expect_*`` helpers.
Everything else in this module operates on an already-unwrapped entity mapping.
"""

from typing import Any, Iterable, Optional

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from .api_client import instants_equal, normalize_instant
from .types import Entity, Page

# Tolerance for comparing fixed-precision decimals returned as JSON numbers.
DECIMAL_TOLERANCE = 1e-9


# --- envelope unwrapping (exactly once) -------------------------------------


def expect_ok(response) -> Entity:
    """Assert a 200 success envelope and return its ``data`` member."""
    return validate_success(response, 200)


def expect_created(response) -> Entity:
    """Assert a 201 success envelope and return its ``data`` member."""
    return validate_success(response, 201)


def expect_error(response, error_id: str) -> Entity:
    """Assert an error envelope carrying ``error_id`` and its mapped status."""
    return validate_error(response, error_id)


def expect_error_one_of(response, error_ids: Iterable[str]) -> str:
    return validate_error_is_one_of(response, list(error_ids))


def expect_page(response) -> Page:
    """Assert a paginated array envelope and return ``(items, meta)``."""
    return validate_paginated(response)


def expect_list_total(response, expected_total: int) -> Page:
    """Assert a paginated read whose ``total_count`` equals ``expected_total``."""
    items, meta = validate_paginated(response)
    assert meta["total_count"] == expected_total, (
        f"expected total_count {expected_total}, got {meta['total_count']}"
    )
    return items, meta


# --- scalar field assertions ------------------------------------------------


def _as_number(value: Any) -> float:
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"expected a JSON number, got {value!r} ({type(value).__name__})"
    )
    return float(value)


def assert_equals(entity: Entity, field: str, expected: Any) -> None:
    """Assert one field equals ``expected``, tolerating instant fraction width."""
    assert field in entity, f"field {field!r} missing from {sorted(entity)}"
    actual = entity[field]
    if isinstance(expected, str) and isinstance(actual, str):
        assert instants_equal(actual, expected) or actual == expected, (
            f"{field}: expected {expected!r}, got {actual!r}"
        )
        return
    assert actual == expected, f"{field}: expected {expected!r}, got {actual!r}"


def assert_fields(entity: Entity, **expected: Any) -> None:
    """Assert several fields at once."""
    for field, value in expected.items():
        assert_equals(entity, field, value)


def assert_instant(entity: Entity, field: str, expected: str) -> None:
    """Assert a timestamp field equals ``expected`` regardless of fraction width."""
    actual = entity.get(field)
    assert isinstance(actual, str), f"{field}: expected a timestamp string, got {actual!r}"
    assert instants_equal(actual, expected), (
        f"{field}: expected {expected} (normalised {normalize_instant(expected)}), "
        f"got {actual} (normalised {normalize_instant(actual)})"
    )


def assert_null(entity: Entity, field: str) -> None:
    assert field in entity, f"field {field!r} missing from {sorted(entity)}"
    assert entity[field] is None, f"{field}: expected null, got {entity[field]!r}"


def assert_not_null(entity: Entity, field: str) -> None:
    assert field in entity, f"field {field!r} missing from {sorted(entity)}"
    assert entity[field] is not None, f"{field}: expected a value, got null"


def assert_absent(entity: Entity, field: str) -> None:
    """Assert the field is not present on the entity at all."""
    assert field not in entity, (
        f"{field!r} should not be present; entity carries {sorted(entity)}"
    )


def assert_decimal_4(entity: Entity, field: str, expected: float) -> None:
    """Assert a four-decimal quantity."""
    actual = _as_number(entity.get(field))
    assert actual == pytest.approx(expected, abs=DECIMAL_TOLERANCE), (
        f"{field}: expected {expected:.4f}, got {actual!r}"
    )
    assert round(actual, 4) == pytest.approx(actual, abs=DECIMAL_TOLERANCE), (
        f"{field}: {actual!r} carries more than four decimal places"
    )


def assert_decimal_2(entity: Entity, field: str, expected: float) -> None:
    """Assert a two-decimal quantity."""
    actual = _as_number(entity.get(field))
    assert actual == pytest.approx(expected, abs=DECIMAL_TOLERANCE), (
        f"{field}: expected {expected:.2f}, got {actual!r}"
    )
    assert round(actual, 2) == pytest.approx(actual, abs=DECIMAL_TOLERANCE), (
        f"{field}: {actual!r} carries more than two decimal places"
    )


def assert_cents(entity: Entity, field: str, expected: int) -> None:
    """Assert a monetary field is an integer count of cents equal to ``expected``."""
    actual = entity.get(field)
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field}: monetary amounts are integer cents, got {actual!r}"
    )
    assert actual == expected, f"{field}: expected {expected} cents, got {actual}"


# --- identity and audit assertions ------------------------------------------


def assert_server_minted_id(entity: Entity) -> None:
    """Assert ``id`` is a server-minted UUID carrying no prefix."""
    value = entity.get("id")
    assert isinstance(value, str) and value, f"id: expected a string, got {value!r}"
    assert is_valid_uuid(value), f"id: expected a UUID, got {value!r}"
    assert ":" not in value and "_" not in value, (
        f"id: expected a bare UUID with no prefix, got {value!r}"
    )


def assert_created_at(entity: Entity) -> None:
    value = entity.get("created_at")
    assert isinstance(value, str) and is_iso8601_timestamp(value), (
        f"created_at: expected an ISO-8601 instant, got {value!r}"
    )


def assert_versioned_row(entity: Entity, expected_version: Optional[int] = None) -> None:
    """Assert the row carries the mutable audit pair, optionally at a version."""
    assert_server_minted_id(entity)
    assert_created_at(entity)
    assert isinstance(entity.get("version"), int) and not isinstance(
        entity.get("version"), bool
    ), f"version: expected an integer, got {entity.get('version')!r}"
    assert isinstance(entity.get("updated_at"), str), (
        f"updated_at: expected a timestamp, got {entity.get('updated_at')!r}"
    )
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"version: expected {expected_version}, got {entity['version']}"
        )


def assert_append_only_row(entity: Entity) -> None:
    """Assert an append-only row carries no ``updated_at`` and no ``version``."""
    assert_server_minted_id(entity)
    assert_created_at(entity)
    assert_absent(entity, "version")
    assert_absent(entity, "updated_at")


def assert_version_advanced(new_entity: Entity, old_entity: Entity) -> None:
    """Assert a mutation moved the version forward."""
    assert new_entity["version"] > old_entity["version"], (
        f"version did not advance: was {old_entity['version']}, "
        f"is {new_entity['version']}"
    )


def assert_unchanged(new_entity: Entity, old_entity: Entity, *fields: str) -> None:
    for field in fields:
        assert_equals(new_entity, field, old_entity[field])


# --- domain-shaped assertions -----------------------------------------------


def assert_provider_counters(provider: Entity, **expected: Any) -> None:
    """Assert a set of derived provider counters in one call."""
    for field, value in expected.items():
        if field == "blocking_false_positive_rate":
            assert_decimal_4(provider, field, value)
        elif field == "outstanding_forfeiture_cents":
            assert_cents(provider, field, value)
        else:
            assert_equals(provider, field, value)


def assert_passport_token(attestation: Entity, certificate_id: str, level: str) -> None:
    """Assert the passport identity token is built from the certificate and level."""
    token = attestation.get("passport_identity_token")
    assert isinstance(token, str) and token, (
        f"passport_identity_token: expected a string, got {token!r}"
    )
    assert token == f"shaken;{certificate_id};{level}", (
        f"passport_identity_token: expected 'shaken;{certificate_id};{level}', "
        f"got {token!r}"
    )


def assert_attestation_outcome(
    attestation: Entity,
    level: str,
    reason_code: str,
    ownership_verified: bool,
    risk_tier_at_signing: Optional[str] = None,
) -> None:
    """Assert the four observable outputs of the attestation ladder."""
    assert_equals(attestation, "attestation_level", level)
    assert_equals(attestation, "attestation_reason_code", reason_code)
    assert_equals(attestation, "ownership_verified", ownership_verified)
    if risk_tier_at_signing is not None:
        assert_equals(attestation, "risk_tier_at_signing", risk_tier_at_signing)


def assert_ids_in_order(items, expected_ids) -> None:
    """Assert a listing returned exactly these identifiers in this order."""
    actual = [item["id"] for item in items]
    assert actual == list(expected_ids), (
        f"listing order: expected {list(expected_ids)}, got {actual}"
    )


def find_by_id(items, entity_id: str) -> Entity:
    for item in items:
        if item.get("id") == entity_id:
            return item
    raise AssertionError(f"{entity_id} not present in listing of {len(items)} rows")
