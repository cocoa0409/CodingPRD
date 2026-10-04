"""Entity assertions and domain invariant checkers."""
import pytest
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp, assert_cost_precision,
)

from .types import (
    VendorStatus, RfpCycleStatus, RfpProposalStatus, ContractStatus,
    LayoverStatus, AllocationKind, AllocationStatus, TripDirection, TripStatus,
    AuditStatus, AuditSeverity, InvoiceStatus, MinRoomStandard, QuietRoomStandard,
    FeedbackCategory, CrewType,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_station(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and len(data["code"]) == 3 and data["code"].isupper()
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["timezone"], str) and len(data["timezone"]) > 0
    assert isinstance(data["min_rest_hours"], int) and 1 <= data["min_rest_hours"] <= 24
    assert isinstance(data["transport_time_minutes"], int) and 5 <= data["transport_time_minutes"] <= 180
    assert isinstance(data["room_availability_commitment"], int) and data["room_availability_commitment"] >= 0


def assert_union_agreement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["crew_type"] in [c.value for c in CrewType]
    assert isinstance(data["min_rest_hours"], int) and 8 <= data["min_rest_hours"] <= 24
    assert isinstance(data["quiet_room_required"], bool)
    assert data["min_room_standard"] in [s.value for s in MinRoomStandard]
    assert isinstance(data["blackout_protection_required"], bool)
    assert isinstance(data["max_invoice_variance_pct"], (int, float))
    assert 0 < data["max_invoice_variance_pct"] <= 100


def assert_hotel_vendor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["contact_email"], str) and "@" in data["contact_email"]
    assert data["status"] in [s.value for s in VendorStatus]
    assert isinstance(data["security_certified"], bool)
    assert isinstance(data["quiet_rooms_count"], int) and data["quiet_rooms_count"] >= 0


def assert_rfp_cycle(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("station_id", ""))
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["status"] in [s.value for s in RfpCycleStatus]
    assert is_iso8601_timestamp(data.get("response_deadline", ""))
    assert isinstance(data["target_room_count"], int) and data["target_room_count"] >= 1
    assert isinstance(data["budget_cap_cents"], int) and data["budget_cap_cents"] > 0
    assert isinstance(data["negotiation_round"], int) and data["negotiation_round"] >= 0


def assert_rfp_proposal(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("rfp_cycle_id", ""))
    assert is_valid_uuid(data.get("vendor_id", ""))
    assert isinstance(data["offered_room_count"], int) and data["offered_room_count"] >= 1
    assert isinstance(data["offered_rate_cents"], int) and data["offered_rate_cents"] >= 0
    assert isinstance(data["current_rate_cents"], int) and data["current_rate_cents"] >= 0
    assert data["status"] in [s.value for s in RfpProposalStatus]
    assert isinstance(data["quiet_room_commitment"], int) and data["quiet_room_commitment"] >= 0
    assert isinstance(data["blackout_dates"], list)


def assert_contract(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("rfp_cycle_id", ""))
    assert is_valid_uuid(data.get("station_id", ""))
    assert is_valid_uuid(data.get("vendor_id", ""))
    assert is_valid_uuid(data.get("proposal_id", ""))
    assert data["status"] in [s.value for s in ContractStatus]
    assert isinstance(data["room_block_size"], int) and data["room_block_size"] >= 1
    assert isinstance(data["negotiated_rate_cents"], int) and data["negotiated_rate_cents"] >= 0
    assert is_iso8601_timestamp(data.get("start_date", ""))
    assert is_iso8601_timestamp(data.get("end_date", ""))
    assert isinstance(data["late_cancel_hours"], int) and data["late_cancel_hours"] >= 0
    assert data["quiet_room_standard"] in [s.value for s in QuietRoomStandard]
    assert isinstance(data["security_requirements"], list)
    assert isinstance(data["blackout_dates"], list)
    assert isinstance(data["blackout_protection"], bool)


def assert_layover(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("station_id", ""))
    assert data["crew_type"] in [c.value for c in CrewType]
    assert isinstance(data["crew_count"], int) and data["crew_count"] >= 1
    assert is_iso8601_timestamp(data.get("arrival_time", ""))
    assert is_iso8601_timestamp(data.get("departure_time", ""))
    assert isinstance(data["required_rest_hours"], int) and data["required_rest_hours"] >= 1
    assert data["status"] in [s.value for s in LayoverStatus]
    assert isinstance(data["is_irregular_ops"], bool)
    assert isinstance(data["rest_compliant"], bool)


def assert_allocation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("layover_requirement_id", ""))
    assert data["kind"] in [k.value for k in AllocationKind]
    assert data["status"] in [s.value for s in AllocationStatus]
    assert isinstance(data["rooms_held"], int) and data["rooms_held"] >= 1
    assert isinstance(data["nightly_rate_cents"], int) and data["nightly_rate_cents"] >= 0
    assert is_iso8601_timestamp(data.get("stay_date", ""))


def assert_transport_trip(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("layover_requirement_id", ""))
    assert data["direction"] in [d.value for d in TripDirection]
    assert is_iso8601_timestamp(data.get("pickup_time", ""))
    assert data["status"] in [s.value for s in TripStatus]
    assert isinstance(data["vehicle_capacity"], int) and data["vehicle_capacity"] >= 1


def assert_crew_feedback(data: dict):
    # Append-only: carries ONLY id + created_at — no updated_at, no version
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "CrewFeedback must not carry updated_at"
    assert "version" not in data, "CrewFeedback must not carry version"
    assert is_valid_uuid(data.get("contract_id", ""))
    assert is_valid_uuid(data.get("layover_requirement_id", ""))
    assert data["crew_type"] in [c.value for c in CrewType]
    assert isinstance(data["rating"], int) and 1 <= data["rating"] <= 5
    assert data["category"] in [c.value for c in FeedbackCategory]
    assert isinstance(data["comment"], str)


def assert_audit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("contract_id", ""))
    assert isinstance(data["auditor_id"], str) and len(data["auditor_id"]) > 0
    assert data["status"] in [s.value for s in AuditStatus]
    assert data["severity"] in [s.value for s in AuditSeverity]
    assert isinstance(data["findings"], str)
    assert is_iso8601_timestamp(data.get("opened_at", ""))


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("contract_id", ""))
    assert is_iso8601_timestamp(data.get("billing_period_start", ""))
    assert is_iso8601_timestamp(data.get("billing_period_end", ""))
    assert data["status"] in [s.value for s in InvoiceStatus]
    assert isinstance(data["billed_room_nights"], int) and data["billed_room_nights"] >= 0
    assert isinstance(data["billed_amount_cents"], int) and data["billed_amount_cents"] >= 0


def assert_contract_invariants(data: dict):
    """Domain invariants that must hold on any contract representation."""
    assert data["room_block_size"] >= 1
    assert data["negotiated_rate_cents"] >= 0
    if data.get("total_contract_value_cents") is not None:
        assert isinstance(data["total_contract_value_cents"], int)
        assert data["total_contract_value_cents"] >= 0
