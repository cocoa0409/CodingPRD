"""Reusable assertions over the response envelope and the domain invariants.

Every helper here takes a `requests.Response` where the parameter is named
`response`, and the framework validators it delegates to already return the
`data` payload — nothing in this module indexes `["data"]` a second time.
"""
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import requests

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .api_client import canonical_instant
from .constants import (
    API_REQUEST_ID_PREFIX,
    COMMON_FIELDS,
    IMMUTABLE_FIELDS,
    RESPONSE_TYPE_ARRAY,
    RESPONSE_TYPE_OBJECT,
)


# ── Rounding, mirroring the PRD's half-up rule ─────────────────────────────
def round_half_up(value: Any, places: int = 2) -> float:
    """Round half up to `places` decimal places, as the PRD specifies."""
    quant = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def round_half_up_int(value: Any) -> int:
    """Round half up to a whole unit, used for cent figures."""
    return int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def assert_decimal_equals(actual: Any, expected: Any, places: int = 2) -> None:
    """Compare two decimal figures at a fixed number of places."""
    assert actual is not None, f"expected {expected}, got None"
    assert round_half_up(actual, places) == round_half_up(expected, places), (
        f"expected {expected} at {places} decimal places, got {actual}"
    )


def assert_cents(actual: Any, expected: int) -> None:
    """A money figure must be an integer count of cents, never a string."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"money must be an integer count of cents, got {actual!r} "
        f"({type(actual).__name__})"
    )
    assert actual == expected, f"expected {expected} cents, got {actual}"


# ── Envelope ───────────────────────────────────────────────────────────────
def assert_envelope_meta(response: requests.Response) -> Dict[str, Any]:
    """The meta block carries a prefixed request id and a formatted timestamp."""
    body = response.json()
    meta = body.get("meta")
    assert isinstance(meta, dict), f"meta must be an object, got {meta!r}"
    request_id = meta.get("api_request_id")
    assert isinstance(request_id, str) and request_id.startswith(
        API_REQUEST_ID_PREFIX
    ), f"api_request_id must start with {API_REQUEST_ID_PREFIX!r}, got {request_id!r}"
    stamp = meta.get("api_request_timestamp")
    assert is_iso8601_timestamp(stamp), (
        f"api_request_timestamp must be an ISO 8601 instant, got {stamp!r}"
    )
    return meta


def assert_response_type(response: requests.Response, expected: str) -> None:
    actual = response.json().get("response_type")
    assert actual == expected, f"expected response_type {expected!r}, got {actual!r}"


def assert_object_response(response: requests.Response) -> None:
    assert_response_type(response, RESPONSE_TYPE_OBJECT)
    assert_envelope_meta(response)


def assert_array_response(response: requests.Response) -> None:
    assert_response_type(response, RESPONSE_TYPE_ARRAY)
    assert_envelope_meta(response)


def validate_unpaginated(response: requests.Response) -> List[Any]:
    """Validate an array response without asserting on the pagination counters.

    Used where a test cares only about the collection contents; the paginated
    variant is the right choice when the counters themselves are under test.
    """
    data = validate_success(response, 200)
    assert isinstance(data, list), f"data must be an array, got {data!r}"
    assert_response_type(response, RESPONSE_TYPE_ARRAY)
    return data


def validate_list(response: requests.Response) -> Tuple[List[Any], Dict[str, Any]]:
    """Validate an array response together with its pagination counters."""
    return validate_paginated(response)


# ── Common resource properties ─────────────────────────────────────────────
def assert_common_fields(
    entity: Dict[str, Any], expected_version: Optional[int] = None
) -> None:
    """A resource in the versioned family exposes all four common properties."""
    for field in COMMON_FIELDS:
        assert field in entity, f"missing common field {field!r} on {entity!r}"
    assert is_valid_uuid(entity["id"]), f"id must be a UUID, got {entity['id']!r}"
    assert_instant_field(entity["created_at"], "created_at")
    assert_instant_field(entity["updated_at"], "updated_at")
    assert isinstance(entity["version"], int), (
        f"version must be an integer, got {entity['version']!r}"
    )
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_immutable_fields(entity: Dict[str, Any]) -> None:
    """An immutable resource carries only the identity pair.

    No revision counter and no update stamp: the two immutable resource kinds are
    written once and never modified.
    """
    for field in IMMUTABLE_FIELDS:
        assert field in entity, f"missing field {field!r} on {entity!r}"
    assert is_valid_uuid(entity["id"]), f"id must be a UUID, got {entity['id']!r}"
    assert_instant_field(entity["created_at"], "created_at")
    assert "updated_at" not in entity, "an immutable resource carries no updated_at"
    assert "version" not in entity, "an immutable resource carries no version"


def assert_instant_field(value: Any, label: str = "timestamp") -> None:
    """An instant is written in UTC in ISO 8601 form."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), (
        f"{label} must be an ISO 8601 UTC instant, got {value!r}"
    )
    assert value.endswith("Z"), f"{label} must be written in UTC, got {value!r}"


def assert_instant_equals(actual: Any, expected: str, label: str = "instant") -> None:
    """Compare two instants after canonicalising their fractional-second width."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"expected {label} {expected}, got {actual}"
    )


def assert_version_is(
    entity: Dict[str, Any], expected: int, label: str = "resource"
) -> None:
    assert entity.get("version") == expected, (
        f"expected {label} version {expected}, got {entity.get('version')}"
    )


# ── Domain ledger invariants ───────────────────────────────────────────────
def assert_room_power_identity(room: Dict[str, Any]) -> None:
    """power_load_va plus power_headroom_va always equals ups_capacity_va."""
    assert (
        room["power_load_va"] + room["power_headroom_va"] == room["ups_capacity_va"]
    ), (
        "power_load_va plus power_headroom_va must equal ups_capacity_va: "
        f"{room['power_load_va']} + {room['power_headroom_va']} != "
        f"{room['ups_capacity_va']}"
    )


def assert_rack_ru_identity(rack: Dict[str, Any]) -> None:
    """available_ru is total_ru less occupied_ru at every instant."""
    assert rack["available_ru"] == rack["total_ru"] - rack["occupied_ru"], (
        "available_ru must be total_ru less occupied_ru: "
        f"{rack['available_ru']} != {rack['total_ru']} - {rack['occupied_ru']}"
    )


def assert_fill_ledger(segment: Dict[str, Any]) -> None:
    """fill_ratio is the used area over the usable area at four decimal places."""
    expected = round_half_up(
        segment["fill_area_used_sq_mm"] / segment["usable_area_sq_mm"], 4
    )
    assert_decimal_equals(segment["fill_ratio"], expected, 4)


def assert_completeness(
    project: Dict[str, Any], strict: float, provisional: float
) -> None:
    assert_decimal_equals(project["completeness_pct_strict"], strict, 2)
    assert_decimal_equals(project["completeness_pct_provisional"], provisional, 2)


# ── Collection helpers ─────────────────────────────────────────────────────
def ids_of(rows: Iterable[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


def assert_contains_id(rows: Sequence[Dict[str, Any]], expected_id: str) -> None:
    assert expected_id in ids_of(rows), f"expected id {expected_id} among {ids_of(rows)}"


def assert_excludes_id(rows: Sequence[Dict[str, Any]], unwanted_id: str) -> None:
    assert unwanted_id not in ids_of(rows), (
        f"did not expect id {unwanted_id} among {ids_of(rows)}"
    )


def assert_created_at_ascending(rows: Sequence[Dict[str, Any]]) -> None:
    stamps = [canonical_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), f"rows must be created_at ascending, got {stamps}"


def created(response: requests.Response) -> Dict[str, Any]:
    """Validate a creation response and return the created resource."""
    return validate_success(response, 201)


def ok(response: requests.Response) -> Dict[str, Any]:
    """Validate a 200 response and return its data."""
    return validate_success(response, 200)
