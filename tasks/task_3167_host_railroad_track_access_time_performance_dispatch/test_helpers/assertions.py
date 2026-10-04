"""Entity assertions and small invariant helpers.

Each ``assert_<entity>`` checks the fields the contract declares for that
entity; the finer-grained helpers check the response envelope, instants, and
money/percentage precision.
"""

from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
)

from .api_client import canonical_instant


def assert_instant(actual: Optional[str], expected: Optional[str], label: str = "instant") -> None:
    """Two instants are equal when their canonical UTC spellings are equal."""
    if expected is None:
        assert actual is None, f"{label}: expected null, got {actual!r}"
        return
    assert actual is not None, f"{label}: expected {expected}, got null"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected}, got {actual!r}"
    )


def assert_instant_format(value: str, label: str = "instant") -> None:
    assert isinstance(value, str) and is_iso8601_timestamp(value), (
        f"{label}: not an ISO 8601 timestamp: {value!r}"
    )


def assert_cents(actual: Any, expected: int, label: str = "amount") -> None:
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label}: expected integer cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_envelope_meta(body: Dict[str, Any]) -> None:
    meta = body.get("meta", {})
    assert isinstance(meta, dict), "envelope meta missing"
    request_id = meta.get("api_request_id", "")
    assert isinstance(request_id, str) and request_id.startswith("req_"), (
        f"api_request_id must start with req_, got {request_id!r}"
    )
    assert_instant_format(meta.get("api_request_timestamp", ""), "meta.api_request_timestamp")


def assert_mutable_common_fields(data: Dict[str, Any], label: str = "entity") -> None:
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert_instant_format(data.get("created_at", ""), f"{label}.created_at")
    assert_instant_format(data.get("updated_at", ""), f"{label}.updated_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_created_equals_updated(data: Dict[str, Any], label: str = "entity") -> None:
    assert canonical_instant(data.get("created_at")) == canonical_instant(data.get("updated_at")), (
        f"{label}: created_at != updated_at on a freshly created row"
    )


def assert_list_page(meta: Dict[str, Any], limit: int, offset: int, total: int, has_more: bool) -> None:
    assert meta["limit"] == limit, f"meta.limit: expected {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"meta.offset: expected {offset}, got {meta['offset']}"
    assert meta["total_count"] == total, (
        f"meta.total_count: expected {total}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"meta.has_more: expected {has_more}, got {meta['has_more']}"
    )


def assert_single_read_omits_pagination(body: Dict[str, Any]) -> None:
    meta = body.get("meta", {})
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key not in meta, f"single-read envelope must not carry pagination field {key!r}"


def assert_ids_in_order(rows: Iterable[Dict[str, Any]], expected_ids: Iterable[str]) -> None:
    actual = [row["id"] for row in rows]
    expected = list(expected_ids)
    assert actual == expected, f"id order: expected {expected}, got {actual}"


def assert_host_railroad(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "host_railroad")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["reporting_mark"], str) and data["reporting_mark"]


def assert_corridor(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "corridor")
    assert is_valid_uuid(data["host_railroad_id"])
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_track_segment(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "track_segment")
    assert is_valid_uuid(data["corridor_id"])
    assert data["track_class"] in ("SINGLE", "DOUBLE")
    assert data["status"] in ("OPERABLE", "CAPITAL_HOLD")
    assert data["milepost_end"] > data["milepost_start"]


def assert_operating_agreement(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "operating_agreement")
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "EXPIRED")
    assert isinstance(data["amendment_seq"], int)


def assert_timetable(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "timetable")
    assert data["status"] in (
        "DRAFT", "PROPOSED", "UNDER_REVIEW", "RATIFIED", "PUBLISHED", "SUSPENDED", "SUPERSEDED",
    )
    assert isinstance(data["revision_no"], int)


def assert_train_run(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "train_run")
    assert data["status"] in ("SCHEDULED", "EN_ROUTE", "COMPLETED", "CANCELLED", "DISRUPTED")


def assert_segment_passage(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "segment_passage")
    assert data["status"] in ("PLANNED", "ACTUALIZED", "SKIPPED")


def assert_delay_incident(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "delay_incident")
    assert data["status"] in ("OPEN", "CONFIRMED", "DISPUTED", "REVERSED")
    assert data["origin"] in ("CODED", "SYSTEM_DISRUPTION")
    assert isinstance(data["host_attributable"], bool)


def assert_dispute(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "dispute")
    assert data["status"] in ("UNDER_REVIEW", "ESCALATED", "RESOLVED")


def assert_capital_project(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "capital_project")
    assert data["status"] in ("PROPOSED", "FUNDED", "IN_PROGRESS", "SUSPENDED", "COMPLETED")


def assert_maintenance_window(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "maintenance_window")
    assert data["status"] in ("PLANNED", "LOCKED", "RELEASED")


def assert_service_disruption(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "service_disruption")
    assert data["status"] in ("OPEN", "BRIDGED", "RECOVERED")
    assert isinstance(data["bus_bridge_active"], bool)


def assert_funding_agreement(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "funding_agreement")
    assert data["status"] in ("DRAFT", "COMMITTED", "SETTLED")


def assert_settlement_statement(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "settlement_statement")
    assert data["status"] in ("DRAFT", "ISSUED", "DISPUTED", "REISSUED", "PAID")
    assert data["computation_variant"] in ("GROSS", "NET")
