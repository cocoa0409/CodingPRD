"""Entity assertions and domain invariant checkers (PRD §2.4, §2.9, §3).

Datetime fields are compared as instants at second granularity (PRD §2.5:
"Datetime comparisons throughout this document are made at second
granularity"), never as raw strings, because the PRD pins the serialization
format only for created_at/updated_at and api_request_timestamp.
"""
from datetime import datetime, timezone

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import PCT_TOLERANCE


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp accepting trailing 'Z' or offsets."""
    assert isinstance(value, str), f"Expected ISO timestamp string, got {value!r}"
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc)


def assert_instant_equal(actual: str, expected: str, label: str = "instant"):
    """Two ISO timestamps must name the same instant (second granularity)."""
    a = parse_instant(actual).replace(microsecond=0)
    e = parse_instant(expected).replace(microsecond=0)
    assert a == e, f"{label}: expected instant {expected}, got {actual}"


def assert_pct(actual, expected, label: str = "repair_rate_pct"):
    """Percentages are stored at two decimals, rounded half-up (PRD §2.9)."""
    assert actual == pytest.approx(expected, abs=PCT_TOLERANCE), (
        f"{label}: expected {expected} (2dp half-up), got {actual}")


def _assert_primary_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601")
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601")
    assert isinstance(data.get("version"), int), (
        f"{entity}.version must be an integer")


def _assert_ledger_fields(data: dict, entity: str):
    """The five ledger records carry only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601")
    assert "updated_at" not in data, f"{entity} must not carry updated_at"
    assert "version" not in data, f"{entity} must not carry version"


def assert_shop(data: dict):
    _assert_primary_fields(data, "Shop")
    assert isinstance(data["shop_name"], str) and data["shop_name"]
    assert isinstance(data["aws_d1_1_revision"], str)
    assert isinstance(data["repair_rate_limit_pct"], int)
    assert is_iso8601_timestamp(data["current_utc"])


def assert_welder(data: dict):
    _assert_primary_fields(data, "Welder")
    assert isinstance(data["stencil"], str) and data["stencil"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")


def assert_ndt_vendor(data: dict):
    _assert_primary_fields(data, "NDTVendor")
    assert isinstance(data["vendor_name"], str) and data["vendor_name"]
    assert isinstance(data["supported_methods"], list)
    assert all(m in ("VT", "UT", "RT") for m in data["supported_methods"])
    assert isinstance(data["hourly_capacity"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_oven(data: dict):
    _assert_primary_fields(data, "Oven")
    assert isinstance(data["oven_code"], str) and data["oven_code"]
    assert isinstance(data["holding_temp_c"], int)
    assert isinstance(data["capacity_electrodes_kg"], int)
    assert data["status"] in ("ONLINE", "OFFLINE", "QUARANTINED")


def assert_pqr(data: dict):
    _assert_primary_fields(data, "PQR")
    assert isinstance(data["pqr_number"], str) and data["pqr_number"]
    assert data["process"] in ("SMAW", "GMAW", "FCAW", "GTAW", "SAW")
    assert isinstance(data["base_metal_spec"], str)
    assert data["thickness_range_min_mm"] is not None
    assert data["thickness_range_max_mm"] is not None
    assert data["status"] in ("DRAFT", "APPROVED", "REJECTED")


def assert_wps(data: dict):
    _assert_primary_fields(data, "WPS")
    assert isinstance(data["wps_number"], str) and data["wps_number"]
    assert isinstance(data["revision"], int)
    assert is_valid_uuid(data["pqr_id"])
    assert data["process"] in ("SMAW", "GMAW", "FCAW", "GTAW", "SAW")
    assert data["status"] in ("DRAFT", "APPROVED", "REJECTED", "SUPERSEDED")


def assert_welder_qualification(data: dict):
    _assert_primary_fields(data, "WelderQualification")
    assert is_valid_uuid(data["welder_id"])
    assert is_valid_uuid(data["wps_id"])
    assert data["process"] in ("SMAW", "GMAW", "FCAW", "GTAW", "SAW")
    assert data["status"] in ("QUALIFIED", "LAPSED", "REVOKED")
    assert isinstance(data["qualified_at_utc"], str)
    assert isinstance(data["last_weld_at_utc"], str)
    assert isinstance(data["continuity_expires_at_utc"], str)


def assert_consumable_lot(data: dict):
    _assert_primary_fields(data, "ConsumableLot")
    assert isinstance(data["lot_number"], str) and data["lot_number"]
    assert data["process"] in ("SMAW", "GMAW", "FCAW", "GTAW", "SAW")
    assert data["received_kg"] is not None
    assert data["remaining_kg"] is not None
    assert isinstance(data["exposed_minutes_total"], int)
    assert isinstance(data["rebake_count"], int)
    assert data["status"] in (
        "IN_OVEN", "ISSUED", "EXPOSED", "QUARANTINED", "EXHAUSTED", "CONSUMED")


def assert_consumable_issue(data: dict):
    _assert_ledger_fields(data, "ConsumableIssue")
    assert is_valid_uuid(data["lot_id"])
    assert is_valid_uuid(data["oven_id"])
    assert is_valid_uuid(data["issued_to_welder_id"])
    assert data["issued_kg"] is not None
    assert isinstance(data["issued_at_utc"], str)
    assert data["status"] in ("OPEN", "RETURNED", "VOID")


def assert_fixture(data: dict):
    _assert_primary_fields(data, "Fixture")
    assert isinstance(data["fixture_code"], str) and data["fixture_code"]
    assert isinstance(data["capacity_weldments"], int)
    assert data["capacity_weldments"] >= 1
    assert data["owner_party"] in ("SHOP", "CUSTOMER")
    assert data["status"] in ("AVAILABLE", "RESERVED", "IN_USE", "UNDER_REPAIR")


def assert_shop_order(data: dict):
    _assert_primary_fields(data, "ShopOrder")
    assert isinstance(data["po_number"], str) and data["po_number"]
    assert isinstance(data["customer_name"], str) and data["customer_name"]
    assert isinstance(data["promised_ship_date_utc"], str)
    assert data["status"] in ("OPEN", "IN_PROGRESS", "COMPLETE", "CANCELLED")


def assert_weldment(data: dict):
    _assert_primary_fields(data, "Weldment")
    assert is_valid_uuid(data["shop_order_id"])
    assert isinstance(data["weldment_serial"], str) and data["weldment_serial"]
    assert is_valid_uuid(data["fixture_id"])
    assert data["posture"] in (
        "OPEN", "RESTRICTED", "FROZEN", "REPAIR_REVIEW", "SHIPPED", "CANCELLED")
    assert isinstance(data["repair_pass_count"], int)
    assert isinstance(data["total_pass_count"], int)
    assert isinstance(data["distortion_count"], int)


def assert_joint(data: dict):
    _assert_primary_fields(data, "Joint")
    assert is_valid_uuid(data["weldment_id"])
    assert isinstance(data["joint_number"], str) and data["joint_number"]
    assert is_valid_uuid(data["wps_id"])
    assert data["base_metal_thickness_mm"] is not None
    assert isinstance(data["required_ndt_methods"], list)
    assert all(m in ("VT", "UT", "RT") for m in data["required_ndt_methods"])
    assert data["fabrication_status"] in (
        "PENDING", "IN_PROGRESS", "WELDED_OUT", "ON_HOLD", "CANCELLED")
    assert data["inspection_status"] in (
        "NOT_READY", "READY_FOR_VT", "VT_PASSED", "NDT_IN_PROGRESS",
        "NDT_PASSED", "NDT_FAILED", "REPAIR_REQUIRED", "REPAIR_WELDED_OUT")
    assert isinstance(data["repair_cycle_count"], int)


def assert_weld_pass(data: dict):
    _assert_ledger_fields(data, "WeldPass")
    assert is_valid_uuid(data["joint_id"])
    assert is_valid_uuid(data["welder_id"])
    assert is_valid_uuid(data["qualification_id"])
    assert is_valid_uuid(data["consumable_lot_id"])
    assert data["consumable_used_kg"] is not None
    assert isinstance(data["is_repair"], bool)
    assert isinstance(data["welded_at_utc"], str)


def assert_distortion_report(data: dict):
    _assert_ledger_fields(data, "DistortionReport")
    assert is_valid_uuid(data["weldment_id"])
    assert is_valid_uuid(data["joint_id"])
    assert data["measured_deviation_mm"] is not None
    assert data["tolerance_mm"] is not None
    assert isinstance(data["reported_by_user_id"], str)
    assert isinstance(data["reported_at_utc"], str)
    assert data["disposition"] in ("PENDING", "REWORK", "USE_AS_IS", "SCRAP")


def assert_inspection(data: dict):
    _assert_ledger_fields(data, "Inspection")
    assert is_valid_uuid(data["joint_id"])
    assert data["method"] in ("VT", "UT", "RT")
    assert isinstance(data["inspector_user_id"], str)
    assert isinstance(data["scheduled_start_utc"], str)
    assert isinstance(data["scheduled_end_utc"], str)
    assert isinstance(data["hold_point_released"], bool)


def assert_traveler_sign_off(data: dict):
    _assert_ledger_fields(data, "TravelerSignOff")
    assert is_valid_uuid(data["weldment_id"])
    assert data["step_code"] in ("FIT_UP", "WELD_OUT", "VT", "NDT", "FINAL")
    assert isinstance(data["signed_by_user_id"], str)
    assert isinstance(data["signed_at_utc"], str)


def assert_weldment_counters_invariants(data: dict):
    """Weldment counter invariants that must hold after any operation."""
    assert data["total_pass_count"] >= 0
    assert 0 <= data["repair_pass_count"] <= data["total_pass_count"]
    assert data["distortion_count"] >= 0
    if data["total_pass_count"] == 0:
        assert_pct(data["repair_rate_pct"], 0.0)
    assert 0.0 <= data["repair_rate_pct"] <= 100.0
