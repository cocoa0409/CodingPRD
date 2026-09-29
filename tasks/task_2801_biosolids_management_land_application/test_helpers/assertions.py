"""Domain assertion helpers for the Biosolids Management & Land Application API."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, Optional

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from . import constants as C
from .api_client import canonical_iso

# ------------------------------------------------------------------ tolerances
CENT = 0.01
MILLI = 0.001
TEN_THOUSANDTH = 0.0001


def round_half_up(value: float, places: int) -> float:
    """Round half away from zero to the given number of decimal places."""
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


# ------------------------------------------------------------------ common fields
def assert_versioned_resource(entity: Dict[str, Any], expected_version: Optional[int] = None):
    """A resource that carries the full common-field set."""
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int), "version must be an integer"
    assert entity["version"] >= 1
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_append_only_resource(entity: Dict[str, Any]):
    """An append-only row carries only ``id`` and ``created_at``."""
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert "updated_at" not in entity, "append-only rows carry no updated_at"
    assert "version" not in entity, "append-only rows carry no version"


def assert_millisecond_timestamp(value: str):
    """Instants render with exactly three fractional digits."""
    assert isinstance(value, str), f"expected a timestamp string, got {value!r}"
    assert value.endswith("Z"), value
    assert "." in value, f"timestamp lacks fractional digits: {value}"
    assert len(value.split(".")[1]) == 4, (
        f"timestamp must carry exactly three fractional digits: {value}"
    )


def assert_instant_equals(actual: Optional[str], expected: Optional[str]):
    """Compare two instants independently of the rendered sub-second width."""
    assert canonical_iso(actual) == canonical_iso(expected), (
        f"expected instant {expected!r}, got {actual!r}"
    )


# ------------------------------------------------------------------ envelopes
def assert_object_envelope(body: Dict[str, Any]):
    assert body["response_type"] == "object"
    assert isinstance(body["data"], dict)
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_"), body["meta"]["api_request_id"]
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])


def assert_array_envelope(body: Dict[str, Any]):
    assert body["response_type"] == "array"
    assert isinstance(body["data"], list)
    meta = body["meta"]
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta, f"array envelope meta missing {key}"


def assert_error_envelope(body: Dict[str, Any]):
    assert body["response_type"] == "error"
    assert set(body["data"].keys()) == {"error_id", "message"}, body["data"]
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")


def assert_pagination_window(meta: Dict[str, Any], total_count: int, returned: int):
    """``has_more`` is true exactly when the page does not reach ``total_count``."""
    assert meta["total_count"] == total_count, (
        f"expected total_count {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is (meta["offset"] + returned < total_count), (
        f"has_more={meta['has_more']} with offset={meta['offset']}, "
        f"returned={returned}, total_count={total_count}"
    )


# ------------------------------------------------------------------ numeric scales
def assert_money(actual: float, expected: float):
    assert actual == pytest.approx(expected, abs=CENT), f"money {actual} != {expected}"


def assert_wet_tons(actual: float, expected: float):
    assert actual == pytest.approx(expected, abs=CENT), f"wet tons {actual} != {expected}"


def assert_acres(actual: float, expected: float):
    assert actual == pytest.approx(expected, abs=CENT), f"acres {actual} != {expected}"


def assert_dry_tons(actual: float, expected: float):
    assert actual == pytest.approx(expected, abs=MILLI), f"dry tons {actual} != {expected}"


def assert_percent(actual: float, expected: float):
    assert actual == pytest.approx(expected, abs=CENT), f"percent {actual} != {expected}"


def assert_loading_delta(actual: float, expected: float):
    assert actual == pytest.approx(expected, abs=TEN_THOUSANDTH), (
        f"kg/ha {actual} != {expected}"
    )


def assert_pan(actual: float, expected: float):
    assert actual == pytest.approx(expected, abs=TEN_THOUSANDTH), (
        f"plant available nitrogen {actual} != {expected}"
    )


def assert_decimal_places(value: float, places: int):
    assert value == pytest.approx(round_half_up(value, places), abs=1e-9), (
        f"{value} carries more than {places} decimal places"
    )


def assert_is_number(value: Any, field: str = "value"):
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be a JSON number, got {type(value).__name__}: {value!r}"
    )


# ------------------------------------------------------------------ facility
def assert_facility_storage(
    facility: Dict[str, Any],
    used_wet_tons: float,
    utilization_pct: float,
    posture: Optional[str] = None,
):
    assert_wet_tons(facility["storage_used_wet_tons"], used_wet_tons)
    assert_percent(facility["storage_utilization_pct"], utilization_pct)
    if posture is not None:
        assert facility["posture"] == posture, (
            f"expected posture {posture}, got {facility['posture']}"
        )


# ------------------------------------------------------------------ batch
def assert_batch_state(
    batch: Dict[str, Any],
    process_status: Optional[str] = None,
    quality_status: Optional[str] = None,
    disposition: Optional[str] = None,
):
    if process_status is not None:
        assert batch["process_status"] == process_status, batch["process_status"]
    if quality_status is not None:
        assert batch["quality_status"] == quality_status, batch["quality_status"]
    if disposition is not None:
        assert batch["disposition"] == disposition, batch["disposition"]


def assert_batch_allocation(
    batch: Dict[str, Any],
    unallocated: Optional[float] = None,
    reserved: Optional[float] = None,
    applied: Optional[float] = None,
    diverted: Optional[float] = None,
):
    if unallocated is not None:
        assert_dry_tons(batch["unallocated_dry_tons"], unallocated)
    if reserved is not None:
        assert_dry_tons(batch["reserved_dry_tons"], reserved)
    if applied is not None:
        assert_dry_tons(batch["applied_dry_tons"], applied)
    if diverted is not None:
        assert_dry_tons(batch["diverted_dry_tons"], diverted)


# ------------------------------------------------------------------ ledger
def assert_application_entry(entry: Dict[str, Any], site_id: str, event_id: str):
    assert_append_only_resource(entry)
    assert entry["entry_type"] == C.ENTRY_APPLICATION
    assert entry["reversal_of_id"] is None
    assert entry["site_id"] == site_id
    assert entry["source_event_id"] == event_id


def assert_reversal_entry(entry: Dict[str, Any], of_entry_id: Optional[str] = None):
    assert_append_only_resource(entry)
    assert entry["entry_type"] == C.ENTRY_REVERSAL
    assert entry["reversal_of_id"] is not None
    if of_entry_id is not None:
        assert entry["reversal_of_id"] == of_entry_id


def assert_cost_breakdown(
    order: Dict[str, Any],
    processing: float,
    hauling: float,
    subtotal: float,
    surcharge_pct: float,
    surcharge: float,
    total: float,
    per_dry_ton: float,
):
    assert_money(order["processing_cost"], processing)
    assert_money(order["hauling_cost"], hauling)
    assert_money(order["subtotal_cost"], subtotal)
    assert order["surcharge_pct"] == pytest.approx(surcharge_pct, abs=CENT)
    assert_money(order["surcharge_cost"], surcharge)
    assert_money(order["total_cost"], total)
    assert_money(order["cost_per_dry_ton"], per_dry_ton)


# ------------------------------------------------------------------ ordering
def assert_ordered_by(rows: Iterable[Dict[str, Any]], *keys: str):
    """Rows are non-decreasing on the given key tuple."""
    previous = None
    for row in rows:
        current = tuple(row[key] for key in keys)
        if previous is not None:
            assert previous <= current, (
                f"rows are not ordered by {keys}: {previous} then {current}"
            )
        previous = current
