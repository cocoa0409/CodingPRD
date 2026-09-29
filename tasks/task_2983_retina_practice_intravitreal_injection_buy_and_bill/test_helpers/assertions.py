"""
Domain assertions layered on the framework validators.

Nothing here re-implements a business rule; each helper only expresses "the
response looks the way the contract says this kind of response looks", or reads
one field out of it.  Rule arithmetic stays inline in the test that owns it, so
the expected numbers are visible next to the citation that produces them.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .api_client import canonical_instant

# --------------------------------------------------------------------------
# List validators
# --------------------------------------------------------------------------


def validate_unpaginated(response: requests.Response) -> List[Dict[str, Any]]:
    """
    Validate an array response whose meta carries no pagination block.

    Bulk-action and sub-resource arrays are returned without limit/offset, so the
    strict paginated validator would fail on them.  This companion checks only the
    array envelope and returns the rows.
    """
    data = validate_success(response, 200)
    assert isinstance(data, list), f"Expected an array payload, got {type(data).__name__}"
    body = response.json()
    assert body["response_type"] == "array", (
        f"Expected response_type 'array', got '{body['response_type']}'"
    )
    return data


def validate_list(response: requests.Response) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Validate a collection endpoint response and return ``(rows, meta)``."""
    rows, meta = validate_paginated(response)
    assert isinstance(rows, list), f"Expected an array payload, got {type(rows).__name__}"
    body = response.json()
    assert body["response_type"] == "array", (
        f"Expected response_type 'array', got '{body['response_type']}'"
    )
    return rows, meta


def list_ids(rows: Sequence[Dict[str, Any]]) -> List[str]:
    """Project the ``id`` of every row of a list response."""
    return [row["id"] for row in rows]


# --------------------------------------------------------------------------
# Envelope
# --------------------------------------------------------------------------


def assert_envelope_shape(response: requests.Response, expected_response_type: str) -> None:
    """
    Assert the three-key envelope and the two mandatory meta fields are present
    with the declared ``response_type``.
    """
    body = response.json()
    assert set(body.keys()) >= {"meta", "response_type", "data"}, (
        f"Envelope must carry meta, response_type and data; got {sorted(body.keys())}"
    )
    assert body["response_type"] == expected_response_type, (
        f"Expected response_type '{expected_response_type}', got '{body['response_type']}'"
    )
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"], (
        "meta.api_request_id must be a non-empty string"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp")), (
        f"meta.api_request_timestamp is not ISO-8601: {meta.get('api_request_timestamp')!r}"
    )


def assert_error_envelope(response: requests.Response) -> Dict[str, Any]:
    """Assert the error envelope shape and return its ``data`` object."""
    body = response.json()
    assert set(body.keys()) >= {"meta", "response_type", "data"}, (
        f"Error envelope must carry meta, response_type and data; got {sorted(body.keys())}"
    )
    assert body["response_type"] == "error"
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"]
    assert is_iso8601_timestamp(meta.get("api_request_timestamp"))
    data = body["data"]
    assert isinstance(data.get("error_id"), str) and data["error_id"]
    assert isinstance(data.get("message"), str) and data["message"].strip()
    return data


# --------------------------------------------------------------------------
# System fields
# --------------------------------------------------------------------------


def assert_system_fields(entity: Dict[str, Any], *, versioned: bool = True) -> None:
    """
    Assert the server-minted identity and audit fields of a mutable entity: a
    UUID id, ISO-8601 created_at and updated_at, and version 1 on creation.
    """
    assert is_valid_uuid(entity.get("id")), f"id is not a UUID: {entity.get('id')!r}"
    assert is_iso8601_timestamp(entity.get("created_at")), (
        f"created_at is not ISO-8601: {entity.get('created_at')!r}"
    )
    if versioned:
        assert is_iso8601_timestamp(entity.get("updated_at")), (
            f"updated_at is not ISO-8601: {entity.get('updated_at')!r}"
        )
        assert isinstance(entity.get("version"), int), "version must be an integer"
        assert entity["version"] >= 1, "version starts at 1"


def assert_immutable_entity_fields(entity: Dict[str, Any]) -> None:
    """
    Assert an immutable entity carries an id and created_at but neither of the
    mutability fields.
    """
    assert is_valid_uuid(entity.get("id")), f"id is not a UUID: {entity.get('id')!r}"
    assert is_iso8601_timestamp(entity.get("created_at"))
    assert "version" not in entity, "an immutable entity carries no version"
    assert "updated_at" not in entity, "an immutable entity carries no updated_at"


def assert_instant_equals(actual: Optional[str], expected: Optional[str], label: str = "") -> None:
    """Compare two ISO-8601 instants at second precision (fractional part ignored)."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label or 'instant'}: expected {expected!r}, got {actual!r}"
    )


# --------------------------------------------------------------------------
# Money
# --------------------------------------------------------------------------


def assert_money_cents(entity: Dict[str, Any], *fields: str) -> None:
    """
    Assert each named monetary field is an integer count of cents, not a string
    and not a float.
    """
    for field in fields:
        value = entity.get(field)
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{field} must be an integer number of cents, got {value!r} "
            f"({type(value).__name__})"
        )


def assert_fields_equal(entity: Dict[str, Any], expected: Dict[str, Any]) -> None:
    """Assert every ``expected`` key is present on ``entity`` with that exact value."""
    mismatches = {
        key: (value, entity.get(key))
        for key, value in expected.items()
        if entity.get(key) != value
    }
    assert not mismatches, "field mismatches (expected, actual): " + repr(mismatches)


# --------------------------------------------------------------------------
# Vial / lot conservation
# --------------------------------------------------------------------------

VIAL_COUNTER_FIELDS = (
    "vials_on_hand",
    "vials_reserved",
    "vials_administered",
    "vials_quarantined",
    "vials_returned",
    "vials_expired",
)


def assert_vial_counters(lot: Dict[str, Any], **expected: int) -> None:
    """Assert the named vial counters of a lot and that every counter is an int."""
    for field in VIAL_COUNTER_FIELDS:
        if field in lot:
            assert isinstance(lot[field], int), f"{field} must be an integer"
    for field, value in expected.items():
        assert lot.get(field) == value, (
            f"{field}: expected {value}, got {lot.get(field)!r}"
        )


def assert_vial_conservation(lot: Dict[str, Any], vials_received: int) -> None:
    """
    Assert the six mutually exclusive vial counters of a lot still sum to the
    number of vials booked in at receipt.
    """
    total = sum(int(lot.get(field, 0)) for field in VIAL_COUNTER_FIELDS)
    assert total == vials_received, (
        f"vial counters sum to {total} but the lot received {vials_received} vials: "
        + repr({field: lot.get(field) for field in VIAL_COUNTER_FIELDS})
    )
