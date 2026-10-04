"""Entity assertions and small domain invariant checkers.

Each ``assert_<entity>`` validates the common properties the contract declares
for the resource and the shape of the entity-specific fields a reader can rely
on. Append-only records (tracking events, heartbeat records, ops runs) are
asserted to carry ``id`` and ``created_at`` only - no ``updated_at`` and no
``version``.
"""

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant


def assert_mutable_common_fields(data: Dict[str, Any]) -> None:
    """Primary resources carry id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must start at 1, got {data.get('version')!r}"
    )


def assert_append_only_common_fields(data: Dict[str, Any]) -> None:
    """Append-only child records carry id and created_at only."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only records must not carry updated_at"
    assert "version" not in data, "append-only records must not carry version"


def assert_carrier(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert isinstance(data["carrier_name"], str) and data["carrier_name"]
    assert isinstance(data["scac_code"], str) and data["scac_code"]


def assert_shipper(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert isinstance(data["company_name"], str) and data["company_name"]


def assert_consignee(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert isinstance(data["shipper_id"], str) and data["shipper_id"]
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["destination_code"], str) and data["destination_code"]


def assert_connection(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert data["channel"] in ("TELEMATICS", "TMS", "MANUAL")
    assert isinstance(data["supported_modes"], list) and len(data["supported_modes"]) >= 1
    assert data["status"] in (
        "DRAFT",
        "CREDENTIALS_SUBMITTED",
        "TESTING",
        "ACTIVE",
        "SUSPENDED",
        "RETIRED",
    )
    assert data["cadence_minutes"] in (15, 240, 1440)


def assert_purchase_order(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert isinstance(data["po_number"], str) and data["po_number"]
    assert isinstance(data["destination_code"], str) and data["destination_code"]
    assert isinstance(data["booking_reference"], str) and data["booking_reference"]
    assert isinstance(data["confirmed_link_count"], int) and data["confirmed_link_count"] >= 0


def assert_facility(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert isinstance(data["facility_name"], str) and data["facility_name"]
    assert data["facility_type"] in ("ORIGIN", "DESTINATION", "BOTH")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["total_dwell_minutes"], int) and data["total_dwell_minutes"] >= 0
    assert (
        isinstance(data["detention_exposure_minutes"], int)
        and data["detention_exposure_minutes"] >= 0
    )
    assert data["appointment_adherence_pct"] is None or isinstance(
        data["appointment_adherence_pct"], int
    )


def assert_shipment(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert data["mode"] in ("OCEAN", "RAIL", "PARCEL", "TRUCKLOAD")
    assert data["tracking_status"] in (
        "BOOKED",
        "IN_TRANSIT",
        "EXCEPTION",
        "OUT_FOR_DELIVERY",
        "DELIVERED",
        "CANCELLED",
    )
    assert data["identity_state"] in ("UNRESOLVED", "MATCHED_PROVISIONAL", "MATCHED_CONFIRMED")
    assert data["data_freshness"] in ("FRESH", "STALE")
    assert data["eta_variant"] in ("SCHEDULED_BASELINE", "TELEMETRY_BLENDED")
    assert isinstance(data["tracking_reference"], str) and data["tracking_reference"]
    assert isinstance(data["actual_delay_minutes"], int) and data["actual_delay_minutes"] >= 0


def assert_tracking_event(data: Dict[str, Any]) -> None:
    assert_append_only_common_fields(data)
    assert data["event_type"] in (
        "DEPARTED",
        "ARRIVED_WAYPOINT",
        "POSITION_UPDATE",
        "DELAY_REPORTED",
        "RECOVERED",
        "OUT_FOR_DELIVERY",
        "DELIVERED",
    )
    assert isinstance(data["is_late"], bool)
    assert isinstance(data["voided"], bool)


def assert_identity_link(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert data["status"] in ("PROPOSED", "CONFIRMED", "REJECTED")
    score = data["match_score"]
    assert isinstance(score, (int, float)) and 0 <= score <= 1
    # The score is a decimal with exactly two decimal places.
    assert round(float(score), 2) == float(score), f"match_score {score} must have two decimals"


def assert_alert(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert data["alert_type"] in ("DELAY_RISK", "CONNECTION_DEGRADED")
    assert data["severity"] in ("MEDIUM", "HIGH")
    assert data["assigned_queue"] in ("CS_TIER1", "CS_TIER2")
    assert data["status"] in ("OPEN", "ESCALATED", "ACKNOWLEDGED", "RESOLVED")


def assert_appointment(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "MISSED", "VOIDED")
    assert is_iso8601_timestamp(data.get("window_start", "")), "window_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("window_end", "")), "window_end must be ISO 8601"


def assert_data_share_grant(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data)
    assert data["grantee_type"] in ("CARRIER", "CONSIGNEE")
    assert data["scope"] in ("ETA_ONLY", "FULL_TRACE")
    assert data["status"] in ("ACTIVE", "REVOKED")


def assert_heartbeat_record(data: Dict[str, Any]) -> None:
    assert_append_only_common_fields(data)
    assert 0 <= data["payload_completeness_pct"] <= 100
    assert isinstance(data["on_time"], bool)


def assert_ops_run(data: Dict[str, Any]) -> None:
    assert_append_only_common_fields(data)
    assert isinstance(data["run_index"], int) and data["run_index"] >= 1
    for counter in (
        "connections_degraded",
        "testing_connections_reset",
        "etas_recomputed",
        "alerts_created",
        "alerts_escalated",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"{counter} must be a non-negative integer, got {data.get(counter)!r}"
        )


def assert_instant_equal(actual: Optional[str], expected: str, label: str = "instant") -> None:
    """Compare two instants on their canonical form so spelling differences do not matter."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_list_page(rows: List[Dict[str, Any]], meta: Dict[str, Any], expected_count: int) -> None:
    """A list page carries the requested slice and honest pagination metadata."""
    assert isinstance(rows, list)
    assert meta.get("total_count") == expected_count, (
        f"total_count must be {expected_count}, got {meta.get('total_count')!r}"
    )
    assert meta.get("has_more") == (meta.get("offset", 0) + len(rows) < expected_count), (
        f"has_more {meta.get('has_more')!r} inconsistent with offset/limit/total"
    )
