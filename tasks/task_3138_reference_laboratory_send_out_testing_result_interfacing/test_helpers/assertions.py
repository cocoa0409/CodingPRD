"""Entity assertions and domain invariant checkers (PRD 2.4 / 2.6 / 2.9)."""
import pytest

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)


def assert_common_fields(data: dict):
    """Every primary resource carries id, created_at, updated_at and version (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_client_laboratory(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["clia_number"], str) and data["clia_number"]
    assert data["client_type"] in (
        "HOSPITAL", "PHYSICIAN_OFFICE", "REFERENCE_LAB", "PATIENT_SERVICE_CENTER")
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["billing_arrangement"] in ("CLIENT", "PATIENT", "PAYER")
    assert data["status"] in (
        "PENDING_ONBOARDING", "ACTIVE", "CREDIT_HOLD", "SUSPENDED", "INACTIVE")
    assert data["onboarding_status"] in (
        "DOCUMENTS_PENDING", "REQUIREMENTS_PUBLISHED", "COURIER_CONFIGURED", "COMPLETE")
    assert data["interface_status"] in ("NOT_BUILT", "IN_BUILD", "CERTIFIED", "RETIRED")
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["outstanding_balance_cents"], (int, float))
    assert isinstance(data["billable_line_count"], int)
    assert isinstance(data["forward_utilization_score"], int)
    assert isinstance(data["settled_utilization_score"], int)
    assert isinstance(data["utilization_flag"], bool)


def assert_client_invariants(data: dict):
    """Derived counters stay sane after any operation (PRD 2.9 / 3.5)."""
    assert data["outstanding_balance_cents"] >= 0
    assert_cost_precision(data["outstanding_balance_cents"])
    assert data["settled_utilization_score"] >= 0
    assert data["forward_utilization_score"] >= 0
    assert data["settled_utilization_score"] <= data["forward_utilization_score"] or (
        data["forward_utilization_score"] >= 0
    )


def assert_courier_run(data: dict):
    assert_common_fields(data)
    assert isinstance(data["client_laboratory_id"], str)
    assert isinstance(data["route_code"], str) and data["route_code"]
    assert isinstance(data["vehicle_id"], str) and data["vehicle_id"]
    assert is_iso8601_timestamp(data["scheduled_departure_at"])
    assert is_iso8601_timestamp(data["scheduled_arrival_at"])
    assert is_iso8601_timestamp(data["scheduled_pickup_at"])
    assert is_iso8601_timestamp(data["scheduled_delivery_at"])
    assert data["temperature_control_mode"] in ("AMBIENT", "REFRIGERATED", "FROZEN", "MIXED")
    assert isinstance(data["specimen_count"], int)
    assert isinstance(data["transit_allowance_minutes"], (int, float))
    assert data["status"] in ("PLANNED", "DISPATCHED", "IN_TRANSIT", "COMPLETED", "ABORTED")


def assert_catalog_entry(data: dict):
    assert_common_fields(data)
    assert isinstance(data["test_code"], str) and data["test_code"]
    assert data["test_category"] in ("ROUTINE", "ESOTERIC", "GENETIC")
    assert data["required_specimen_type"] in (
        "WHOLE_BLOOD_EDTA", "SERUM_SST", "PLASMA_LITHIUM_HEPARIN", "URINE_RANDOM", "TISSUE_FRESH")
    assert data["container_type"] in (
        "LAVENDER_TOP", "GOLD_SST", "GREEN_TOP", "STERILE_CUP", "PARAFFIN_BLOCK")
    assert data["transport_temperature"] in ("AMBIENT", "REFRIGERATED", "FROZEN")
    assert isinstance(data["min_volume_ml"], (int, float))
    assert isinstance(data["base_tat_hours"], (int, float))
    assert isinstance(data["list_price_cents"], int)
    assert isinstance(data["floor_price_cents"], int)
    assert data["reflex_condition"] in (
        "ALWAYS", "RESULT_ABOVE_HIGH", "RESULT_BELOW_LOW", "NONE")
    assert isinstance(data["is_utilization_managed"], bool)
    assert data["status"] in ("DRAFT", "PUBLISHED", "DEPRECATED", "WITHDRAWN")


def assert_specimen(data: dict):
    assert_common_fields(data)
    assert isinstance(data["client_laboratory_id"], str)
    assert isinstance(data["accession_number"], str) and data["accession_number"]
    assert data["specimen_type"] in (
        "WHOLE_BLOOD_EDTA", "SERUM_SST", "PLASMA_LITHIUM_HEPARIN", "URINE_RANDOM", "TISSUE_FRESH")
    assert data["container_type"] in (
        "LAVENDER_TOP", "GOLD_SST", "GREEN_TOP", "STERILE_CUP", "PARAFFIN_BLOCK")
    assert data["transport_temperature"] in ("AMBIENT", "REFRIGERATED", "FROZEN")
    assert data["condition"] in (
        "ACCEPTABLE", "HEMOLYZED", "CLOTTED", "INSUFFICIENT_VOLUME", "TEMPERATURE_EXCURSION")
    assert isinstance(data["remaining_stability_hours"], (int, float))
    assert isinstance(data["total_aliquot_volume_ml"], (int, float))
    assert data["status"] in (
        "RECEIVED", "ACCESSIONED", "IN_TESTING", "RESULT_PENDING_REVIEW", "RELEASED", "REJECTED")


def assert_send_out_order(data: dict):
    assert_common_fields(data)
    assert isinstance(data["client_laboratory_id"], str)
    assert isinstance(data["specimen_id"], str)
    assert data["priority"] in ("ROUTINE", "STAT", "TIMED")
    assert data["order_status"] in (
        "SUBMITTED", "ACCESSIONED", "IN_TESTING", "INTERIM_REPORTED", "RESULT_RELEASED",
        "REFLEX_PENDING", "ON_HOLD", "CLOSED", "CANCELLED")
    assert data["billing_status"] in ("UNBILLED", "PROVISIONAL", "BILLED", "VOIDED")


def assert_order_test_line(data: dict):
    assert_common_fields(data)
    assert isinstance(data["send_out_order_id"], str)
    assert isinstance(data["test_catalog_entry_id"], str)
    assert isinstance(data["line_sequence"], int)
    assert isinstance(data["is_add_on"], bool)
    assert data["line_status"] in (
        "PENDING", "IN_PROGRESS", "INTERIM", "FINAL", "REPEAT_REQUIRED", "CANCELLED")
    if data.get("result_flag") is not None:
        assert data["result_flag"] in (
            "NORMAL", "HIGH", "LOW", "CRITICAL_HIGH", "CRITICAL_LOW")


def assert_instrument_run(data: dict):
    assert_common_fields(data)
    assert isinstance(data["instrument_code"], str) and data["instrument_code"]
    assert isinstance(data["section"], str) and data["section"]
    assert isinstance(data["decontamination_buffer_minutes"], int)
    assert is_iso8601_timestamp(data["reserved_start_at"])
    assert is_iso8601_timestamp(data["reserved_end_at"])
    assert is_iso8601_timestamp(data["occupied_until_at"])
    assert data["run_status"] in ("RESERVED", "RUNNING", "COMPLETED", "ABORTED")


def assert_interface_build(data: dict):
    assert_common_fields(data)
    assert isinstance(data["client_laboratory_id"], str)
    assert data["format"] in ("HL7_V2_5_1", "HL7_V2_8", "CSV_FLAT_FILE", "API_JSON")
    assert isinstance(data["order_interface_enabled"], bool)
    assert isinstance(data["result_interface_enabled"], bool)
    assert data["status"] in ("DRAFT", "IN_BUILD", "CERTIFIED", "SUPERSEDED", "RETIRED")


def assert_interface_message(data: dict):
    assert_common_fields(data)
    assert isinstance(data["send_out_order_id"], str)
    assert isinstance(data["interface_build_id"], str)
    assert data["message_type"] in ("ORDER", "RESULT", "INTERIM")
    assert isinstance(data["control_id"], str) and data["control_id"]
    assert isinstance(data["retry_count"], int)
    assert data["retry_count"] >= 0
    assert isinstance(data["next_retry_offset_minutes"], (int, float))
    assert data["status"] in (
        "QUEUED", "VALIDATED", "HELD", "TRANSMITTED", "FAILED", "ACKNOWLEDGED")


def assert_billing_ledger(data: dict):
    assert_common_fields(data)
    assert isinstance(data["client_laboratory_id"], str)
    assert isinstance(data["billed_cents"], (int, float))
    assert isinstance(data["voided_cents"], (int, float))
    assert isinstance(data["charge_entry_count"], int)
    assert data["status"] in ("OPEN", "HELD", "CLOSED")


def assert_billing_ledger_invariants(data: dict):
    """net_billed_cents is billed_cents minus voided_cents (PRD 3.10)."""
    assert data["net_billed_cents"] == pytest.approx(
        data["billed_cents"] - data["voided_cents"], abs=0.01), (
        "net_billed_cents must equal billed_cents minus voided_cents"
    )
    assert data["charge_entry_count"] >= 0


def assert_utilization_advisory(data: dict):
    assert_common_fields(data)
    assert isinstance(data["client_laboratory_id"], str)
    assert isinstance(data["test_catalog_entry_id"], str)
    assert data["advisory_type"] in ("DUPLICATE_ORDER", "UNNECESSARY_FREQUENCY", "REFLEX_REDUNDANT")
    assert isinstance(data["message"], str)
    assert isinstance(data["send_count"], int)
    assert data["status"] in ("OPEN", "SENT", "ACKNOWLEDGED", "DISMISSED", "ESCALATED")