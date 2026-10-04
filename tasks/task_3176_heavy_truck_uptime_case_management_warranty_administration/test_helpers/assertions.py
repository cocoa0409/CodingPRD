"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def _assert_append_only_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "append-only rows must not carry updated_at"
    assert "version" not in data, "append-only rows must not carry version"


def assert_fleet(data: dict):
    _assert_common(data)
    assert isinstance(data["fleet_name"], str) and data["fleet_name"]
    assert isinstance(data["home_region"], str) and data["home_region"]
    assert data["fleet_status"] in ["ACTIVE", "SUSPENDED", "CLOSED"]
    assert isinstance(data["reliability_score"], int)
    assert data["reliability_score"] >= 0, "reliability_score floor is 0"
    assert isinstance(data["total_downtime_hours"], (int, float))
    assert isinstance(data["open_case_count"], int) and data["open_case_count"] >= 0


def assert_truck(data: dict):
    _assert_common(data)
    assert isinstance(data["fleet_id"], str) and data["fleet_id"]
    assert isinstance(data["vin"], str) and len(data["vin"]) == 17
    assert isinstance(data["model_code"], str) and data["model_code"]
    assert isinstance(data["odometer_miles"], int) and data["odometer_miles"] >= 0
    assert isinstance(data["base_warranty_until_miles"], int)
    assert data["truck_status"] in ["IN_SERVICE", "DOWN", "DECOMMISSIONED"]
    assert isinstance(data["open_case_count"], int) and data["open_case_count"] >= 0
    assert isinstance(data["repeat_repair_flag"], bool)


def assert_dealer(data: dict):
    _assert_common(data)
    assert isinstance(data["dealer_name"], str) and data["dealer_name"]
    assert isinstance(data["region"], str) and data["region"]
    assert isinstance(data["hourly_labor_rate_cents"], int)
    assert data["hourly_labor_rate_cents"] > 0
    assert data["dealer_status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["bay_count"], int) and data["bay_count"] >= 0
    assert isinstance(data["active_case_count"], int) and data["active_case_count"] >= 0


def assert_service_bay(data: dict):
    _assert_common(data)
    assert isinstance(data["dealer_id"], str) and data["dealer_id"]
    assert isinstance(data["bay_code"], str) and data["bay_code"]
    assert data["bay_status"] in [
        "AVAILABLE",
        "RESERVED",
        "IN_USE",
        "DOWN",
        "DECOMMISSIONED",
    ]


def assert_fault_event(data: dict):
    _assert_append_only_common(data)
    assert isinstance(data["truck_id"], str) and data["truck_id"]
    assert isinstance(data["fault_code"], str) and data["fault_code"]
    assert data["severity"] in ["INFO", "WARNING", "CRITICAL"]
    assert data["recommended_action"] in [
        "MONITOR",
        "SCHEDULE_SERVICE",
        "STOP_IMMEDIATELY",
    ]
    assert data["event_status"] in ["UNLINKED", "LINKED", "DISMISSED"]


def assert_case(data: dict):
    _assert_common(data)
    assert isinstance(data["truck_id"], str) and data["truck_id"]
    assert isinstance(data["fleet_id"], str) and data["fleet_id"]
    assert data["case_status"] in [
        "OPEN",
        "TRIAGE",
        "SCHEDULED",
        "IN_SERVICE",
        "AWAITING_PART",
        "PENDING_CLOSE",
        "CLOSED",
        "CANCELLED",
    ]
    assert isinstance(data["fault_code"], str) and data["fault_code"]
    assert isinstance(data["downtime_hours"], (int, float))
    assert data["downtime_hours"] >= 0.0, "downtime_hours is never negative"
    assert isinstance(data["diagnostic_minutes_authorized"], int)
    assert data["diagnostic_minutes_authorized"] >= 0
    assert isinstance(data["expedite_count"], int) and data["expedite_count"] >= 0


def assert_work_order(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str) and data["case_id"]
    assert isinstance(data["dealer_id"], str) and data["dealer_id"]
    assert isinstance(data["bay_id"], str) and data["bay_id"]
    assert data["work_order_status"] in [
        "DRAFT",
        "AUTHORIZED",
        "IN_PROGRESS",
        "COMPLETED",
        "CANCELLED",
    ]
    assert isinstance(data["diagnostic_minutes_authorized"], int)
    assert isinstance(data["labor_minutes_actual"], int)


def assert_part_order(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str) and data["case_id"]
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["expedite_decision"] in [
        "PENDING_EVAL",
        "EXPEDITE_OVERNIGHT",
        "EXPEDITE_STANDARD",
        "DENIED",
    ]
    assert data["part_order_status"] in [
        "PENDING",
        "SHIPPED",
        "RECEIVED",
        "INSTALLED",
        "CANCELLED",
    ]
    assert isinstance(data["expedite_cost_cents"], int)
    assert data["expedite_cost_cents"] >= 0
    assert isinstance(data["downtime_cost_cents"], int)
    assert data["downtime_cost_cents"] >= 0


def assert_warranty_claim(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str) and data["case_id"]
    assert data["claim_type"] in [
        "BASE_WARRANTY",
        "EXTENDED_COVERAGE",
        "CAMPAIGN",
        "GOODWILL",
    ]
    assert isinstance(data["labor_minutes_claimed"], int)
    assert isinstance(data["parts_claimed_cents"], int)
    assert data["parts_claimed_cents"] >= 0
    assert isinstance(data["labor_rate_cents_per_hour"], int)
    assert isinstance(data["recovery_amount_cents"], int)
    assert data["recovery_amount_cents"] >= 0
    assert data["submission_status"] in [
        "DRAFT",
        "SUBMITTED",
        "UNDER_REVIEW",
        "APPROVED",
        "DENIED",
        "PARTIAL_APPROVED",
    ]
    assert data["recovery_status"] in [
        "NOT_INITIATED",
        "PART_RETURN_REQUESTED",
        "PART_IN_TRANSIT",
        "PART_RECEIVED",
        "RECOVERY_FILED",
        "RECOVERY_PAID",
        "RECOVERY_DENIED",
    ]


def assert_part_return(data: dict):
    _assert_common(data)
    assert isinstance(data["claim_id"], str) and data["claim_id"]
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert isinstance(data["return_window_days"], int)
    assert data["return_window_days"] in [30, 45]
    assert data["part_return_status"] in [
        "REQUESTED",
        "IN_TRANSIT",
        "RECEIVED",
        "INSPECTED_OK",
        "INSPECTED_FAILED",
        "LATE_REJECTED",
    ]


def assert_supplier_recovery(data: dict):
    _assert_common(data)
    assert isinstance(data["claim_id"], str) and data["claim_id"]
    assert isinstance(data["part_return_id"], str) and data["part_return_id"]
    assert isinstance(data["supplier_id"], str) and data["supplier_id"]
    assert isinstance(data["claimed_amount_cents"], int)
    assert data["claimed_amount_cents"] >= 0
    assert isinstance(data["paid_amount_cents"], int) and data["paid_amount_cents"] >= 0
    assert data["recovery_status"] in ["FILED", "UNDER_DISPUTE", "PAID", "DENIED"]


def assert_coverage_contract(data: dict):
    _assert_common(data)
    assert isinstance(data["truck_id"], str) and data["truck_id"]
    assert data["contract_type"] in [
        "EXTENDED_POWERTRAIN",
        "EXTENDED_AFTERTREATMENT",
        "EXTENDED_FULL",
    ]
    assert isinstance(data["max_miles"], int)
    assert isinstance(data["premium_cents"], int)
    assert data["contract_status"] in ["ACTIVE", "EXPIRED", "CANCELLED"]
    assert isinstance(data["prorated_credit_cents"], int)
    assert data["prorated_credit_cents"] >= 0


def assert_campaign(data: dict):
    _assert_common(data)
    assert isinstance(data["campaign_code"], str) and data["campaign_code"]
    assert data["campaign_kind"] in ["RECALL", "SERVICE_CAMPAIGN"]
    assert isinstance(data["affected_model_codes"], list)
    assert isinstance(data["fault_code"], str) and data["fault_code"]
    assert data["campaign_status"] in ["OPEN", "CLOSED"]
    assert isinstance(data["completion_pct"], (int, float))
    assert 0.0 <= data["completion_pct"] <= 100.0
    assert isinstance(data["overdue_count"], int) and data["overdue_count"] >= 0


def assert_campaign_completion(data: dict):
    _assert_common(data)
    assert isinstance(data["campaign_id"], str) and data["campaign_id"]
    assert isinstance(data["truck_id"], str) and data["truck_id"]
    assert data["completion_status"] in [
        "OPEN",
        "SCHEDULED",
        "COMPLETED",
        "EXEMPTED",
    ]


def assert_reliability_report(data: dict):
    _assert_append_only_common(data)
    assert isinstance(data["fleet_id"], str) and data["fleet_id"]
    assert isinstance(data["ops_run_index"], int) and data["ops_run_index"] >= 1
    assert isinstance(data["trucks_in_service"], int)
    assert isinstance(data["trucks_down"], int)
    assert isinstance(data["total_downtime_hours"], (int, float))
    assert isinstance(data["repeat_repair_truck_count"], int)
    assert isinstance(data["campaign_completion_pct"], (int, float))
    assert isinstance(data["reliability_score"], int)


def assert_fleet_invariants(fleet: dict):
    """Fleet invariants that must hold after any operation."""
    assert fleet["reliability_score"] >= 0, "reliability_score floor is 0"
    assert fleet["reliability_score"] <= 1000, "reliability_score starts at 1000"
    assert fleet["open_case_count"] >= 0
    assert fleet["total_downtime_hours"] >= 0
