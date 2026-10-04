"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_dealer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data["dealer_code"], str) and data["dealer_code"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert 0.0 <= data["holdback_rate"] <= 0.5
    assert data["quality_tier"] in ("TIER_1", "TIER_2", "TIER_3")
    assert data["standing"] in ("ACTIVE", "WATCH", "SUSPENDED")
    assert data["chargeback_balance_due_cents"] >= 0
    assert data["holdback_reserve_cents"] >= 0
    assert data["funded_package_count"] >= 0


def assert_dealer_invariants(data: dict):
    """Invariants that must hold after any operation on a dealer."""
    assert data["chargeback_balance_due_cents"] >= 0
    assert data["holdback_reserve_cents"] >= 0
    assert data["standing"] in ("ACTIVE", "WATCH", "SUSPENDED")


def assert_contract(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert data["source_channel"] in ("DIRECT", "DEALER")
    assert data["contract_status"] in (
        "PENDING_VALIDATION", "ACTIVE", "DELINQUENT", "CANCELLED", "ASSUMED",
    )
    assert data["equipment_config_code"] in ("BASE", "PREMIUM", "ELITE")
    assert 300 <= data["credit_score"] <= 850
    assert 12 <= data["contract_term_months"] <= 84
    assert data["monthly_monitoring_cents"] > 0


def assert_package(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert data["package_status"] in (
        "DRAFT", "UNDER_REVIEW", "APPROVED", "FUNDED", "DECLINED", "EXPIRED",
    )
    assert data["funded_count"] >= 0
    assert data["declined_count"] >= 0


def assert_customer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("PENDING_ACTIVATION", "ACTIVE", "CANCELLED", "ASSUMED")
    assert isinstance(data["email"], str) and "@" in data["email"]


def assert_installation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["install_status"] in ("SCHEDULED", "COMPLETED", "FAILED")
    assert isinstance(data["activation_committed"], bool)


def assert_monitoring_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["provision_state"] in ("UNPROVISIONED", "PROVISIONED", "SUSPENDED", "CLOSED")
    assert isinstance(data["activation_gate_met"], bool)


def assert_alarm_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["verification_outcome"] in ("PENDING", "VERIFIED", "FALSE_ALARM")
    assert isinstance(data["counted_for_false_alarm"], bool)
    assert isinstance(data["counted_for_window_total"], bool)


def assert_dispatch_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["dispatch_status"] in (
        "REQUESTED", "DISPATCHED", "COMPLETED", "ABORTED", "CLOSED",
    )


def assert_service_visit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["visit_status"] in ("REQUESTED", "SCHEDULED", "PERFORMED", "CANCELLED")
    assert data["work_type"] in ("REPAIR", "WARRANTY_REPAIR")
    assert data["billing_route"] in ("CUSTOMER", "DEALER_HOLDBACK", None)


def assert_assumption_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["request_status"] in (
        "PENDING_NEGOTIATION", "REJECTED", "ACCEPTED", "COMPLETED",
    )
    assert data["rejection_count"] >= 0


def assert_rescission_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["request_status"] in ("REQUESTED", "APPROVED", "DECLINED")
    assert isinstance(data["days_since_funding"], int)


def assert_attrition_sweep(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["flagged_contract_ids"], list)
    assert data["delinquent_count"] >= 0
    assert data["resumed_count"] >= 0


def assert_contract_owner(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["ownership_status"] in ("CURRENT", "SUPERSEDED")
    if data["ownership_status"] == "CURRENT":
        assert data.get("ended_at") is None
    else:
        assert data.get("ended_at") is not None


def assert_monitoring_account_invariants(data: dict):
    assert data["provision_state"] in ("UNPROVISIONED", "PROVISIONED", "SUSPENDED", "CLOSED")
    if data["provision_state"] == "PROVISIONED":
        assert data["activation_gate_met"] is True