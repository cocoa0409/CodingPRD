"""Entity assertions and domain invariant checkers for the clinical-engineering API."""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

CE_POSTURES = ["NORMAL", "HEIGHTENED", "LOCKDOWN"]
BUDGET_STATES = ["OPEN", "WARNING", "ON_HOLD"]
OPERATIONAL_STATES = ["IN_SERVICE", "DOWN", "ON_LOAN", "RETIRED"]
SECURITY_STATES = ["UNASSESSED", "ASSESSED_OK", "VULNERABLE", "QUARANTINED", "REMEDIATED"]
RISK_CLASSES = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
PM_STATUSES = ["SCHEDULED", "DEFERRED", "COMPLETED", "MISSED"]
PM_RESULTS = ["PASS", "FAIL", "PASS_WITH_DEFECT", None]
WORK_ORDER_STATUSES = ["INTAKE", "IN_REPAIR", "AWAITING_PARTS", "REPAIR_COMPLETE",
                       "VERIFIED", "CLOSED", "CANCELLED"]
PRIORITIES = ["P1", "P2", "P3"]
LOANER_COVERAGE = ["NONE", "COVERED", "UNCOVERED"]
LOANER_STATUSES = ["DEPLOYED", "RETURNED", "CANCELLED"]
RECALL_STATUSES = ["DRAFT", "PUBLISHED", "MANDATORY_REMOVAL", "MONITORING", "CLOSED"]
HAZARD_CLASSES = ["CLASS_I", "CLASS_II", "CLASS_III"]
DISPOSITIONS = ["PENDING", "REMOVED", "REMEDIATED", "EXEMPTED"]
CONTRACT_STATUSES = ["ACTIVE", "EXHAUSTED"]
FINDING_STATUSES = ["OPEN", "REMEDIATION_SCHEDULED", "MITIGATED", "ACCEPTED_RISK"]
FINDING_SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]


def assert_common_fields(data: dict, entity_name: str = "resource"):
    """Every resource carries id, created_at, updated_at and version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a bare server-minted UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_facility(data: dict):
    assert_common_fields(data, "Facility")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["facility_code"], str) and 1 <= len(data["facility_code"]) <= 16
    assert 0.0 <= float(data["pm_compliance_target_pct"]) <= 100.0
    assert data["ce_posture"] in CE_POSTURES, f"unexpected ce_posture {data['ce_posture']!r}"
    assert 0.0 <= float(data["pm_compliance_pct_strict"]) <= 100.0
    assert 0.0 <= float(data["pm_compliance_pct_operational"]) <= 100.0
    assert isinstance(data["pm_audit_index"], int) and data["pm_audit_index"] >= 0
    assert isinstance(data["open_class_i_recall_count"], int) and data["open_class_i_recall_count"] >= 0
    assert isinstance(data["departments_on_hold_count"], int) and data["departments_on_hold_count"] >= 0


def assert_department(data: dict):
    assert_common_fields(data, "Department")
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["cost_center_code"], str)
    assert isinstance(data["downtime_budget_cents"], int) and data["downtime_budget_cents"] > 0
    assert isinstance(data["downtime_spend_cents"], int) and data["downtime_spend_cents"] >= 0
    assert data["budget_state"] in BUDGET_STATES


def assert_vendor(data: dict):
    assert_common_fields(data, "Vendor")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["vendor_code"], str)
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] >= 0
    assert isinstance(data["travel_flat_cents"], int) and data["travel_flat_cents"] >= 0
    assert isinstance(data["security_attestation_on_file"], bool)
    assert isinstance(data["is_approved"], bool)


def assert_device_model(data: dict):
    assert_common_fields(data, "DeviceModel")
    assert isinstance(data["manufacturer"], str) and data["manufacturer"]
    assert isinstance(data["model_number"], str)
    assert isinstance(data["device_family"], str)
    assert isinstance(data["is_network_connected"], bool)
    assert isinstance(data["expected_life_years"], int) and data["expected_life_years"] > 0
    assert isinstance(data["replacement_cost_cents"], int) and data["replacement_cost_cents"] > 0


def assert_device(data: dict):
    assert_common_fields(data, "Device")
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["department_id"])
    assert is_valid_uuid(data["device_model_id"])
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert isinstance(data["acquisition_date"], str)
    assert isinstance(data["acquisition_cost_cents"], int) and data["acquisition_cost_cents"] >= 0
    assert 1 <= data["function_code"] <= 10
    assert 1 <= data["physical_risk_code"] <= 5
    assert 1 <= data["maintenance_requirement_code"] <= 5
    assert 1 <= data["condition_score"] <= 5
    assert isinstance(data["utilization_hours"], int) and data["utilization_hours"] >= 0
    assert isinstance(data["is_loaner_pool"], bool)
    assert isinstance(data["risk_score"], int)
    assert data["risk_class"] in RISK_CLASSES
    assert data["pm_interval_days"] in (90, 180, 270, 365)
    assert data["operational_state"] in OPERATIONAL_STATES
    assert data["security_state"] in SECURITY_STATES
    assert isinstance(data["recall_hold"], bool)
    assert isinstance(data["lifetime_maintenance_cost_cents"], int)
    assert 0.0 <= float(data["replacement_priority_score"]) <= 100.0
    assert isinstance(data["plan_rank"], int) and data["plan_rank"] >= 0
    assert isinstance(data["plan_funded"], bool)


def assert_pm_task(data: dict):
    assert_common_fields(data, "PMTask")
    assert is_valid_uuid(data["device_id"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert is_iso8601_timestamp(data["due_at"])
    assert is_iso8601_timestamp(data["original_due_at"])
    assert data["status"] in PM_STATUSES
    assert isinstance(data["deferral_count"], int) and 0 <= data["deferral_count"] <= 2
    assert data["result"] in PM_RESULTS
    assert isinstance(data["labor_minutes"], int) and data["labor_minutes"] >= 0
    assert isinstance(data["on_time"], bool)


def assert_work_order(data: dict):
    assert_common_fields(data, "WorkOrder")
    assert is_valid_uuid(data["device_id"])
    assert data["reported_severity"] in ["PATIENT_HARM", "CLINICAL_IMPACT", "ROUTINE"]
    assert isinstance(data["problem_summary"], str)
    assert is_iso8601_timestamp(data["reported_at"])
    assert data["status"] in WORK_ORDER_STATUSES
    assert data["priority"] in PRIORITIES
    assert data["sla_hours"] in (4, 24, 72)
    assert data["service_mode"] in ["IN_HOUSE", "VENDOR", None]
    assert isinstance(data["active_repair_seconds"], int) and data["active_repair_seconds"] >= 0
    assert float(data["active_repair_hours"]) >= 0
    assert float(data["turnaround_hours"]) >= 0
    assert isinstance(data["sla_met"], bool)
    assert isinstance(data["labor_minutes"], int) and data["labor_minutes"] >= 0
    assert isinstance(data["parts_cost_cents"], int) and data["parts_cost_cents"] >= 0
    assert float(data["shift_multiplier_applied"]) in (1.0, 1.5)
    assert isinstance(data["estimated_cost_cents"], int) and data["estimated_cost_cents"] >= 0
    assert isinstance(data["final_cost_cents"], int) and data["final_cost_cents"] >= 0
    assert isinstance(data["department_charge_cents"], int) and data["department_charge_cents"] >= 0
    assert isinstance(data["verify_fail_count"], int) and data["verify_fail_count"] >= 0
    assert data["loaner_status"] in LOANER_COVERAGE


def assert_loaner_assignment(data: dict):
    assert_common_fields(data, "LoanerAssignment")
    assert is_valid_uuid(data["work_order_id"])
    assert data["source"] in ["POOL", "RENTAL"]
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert data["status"] in LOANER_STATUSES
    assert isinstance(data["billable_days"], int) and data["billable_days"] >= 0
    assert isinstance(data["rental_cost_cents"], int) and data["rental_cost_cents"] >= 0


def assert_recall_notice(data: dict):
    assert_common_fields(data, "RecallNotice")
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["device_model_id"])
    assert isinstance(data["source_reference"], str)
    assert data["hazard_class"] in HAZARD_CLASSES
    assert isinstance(data["affected_lot_numbers"], list)
    assert is_iso8601_timestamp(data["response_due_at"])
    assert data["status"] in RECALL_STATUSES
    assert isinstance(data["matched_device_count"], int) and data["matched_device_count"] >= 0
    assert isinstance(data["pending_match_count"], int) and data["pending_match_count"] >= 0


def assert_recall_match(data: dict):
    assert_common_fields(data, "RecallMatch")
    assert is_valid_uuid(data["recall_notice_id"])
    assert is_valid_uuid(data["device_id"])
    assert data["match_basis"] in ["MODEL_ONLY", "MODEL_AND_LOT"]
    assert data["disposition"] in DISPOSITIONS


def assert_service_contract(data: dict):
    assert_common_fields(data, "ServiceContract")
    assert is_valid_uuid(data["vendor_id"])
    assert is_valid_uuid(data["device_model_id"])
    assert is_iso8601_timestamp(data["coverage_start"])
    assert is_iso8601_timestamp(data["coverage_end"])
    assert isinstance(data["annual_premium_cents"], int) and data["annual_premium_cents"] >= 0
    assert isinstance(data["deductible_cents"], int) and data["deductible_cents"] >= 0
    assert isinstance(data["covered_event_cap"], int) and data["covered_event_cap"] >= 1
    assert isinstance(data["covered_events_used"], int) and data["covered_events_used"] >= 0
    assert data["status"] in CONTRACT_STATUSES


def assert_security_finding(data: dict):
    assert_common_fields(data, "SecurityFinding")
    assert is_valid_uuid(data["device_id"])
    assert data["severity"] in FINDING_SEVERITIES
    assert isinstance(data["advisory_reference"], str)
    assert isinstance(data["requires_downtime"], bool)
    assert is_iso8601_timestamp(data["discovered_at"])
    assert is_iso8601_timestamp(data["remediation_due_at"])
    assert data["status"] in FINDING_STATUSES


# ─── Domain invariant checkers ─────────────────────────────────────────────

def assert_two_decimals(value, label: str = "value"):
    """Percentages and hour figures are carried to exactly two decimals (PRD §2.6)."""
    number = float(value)
    assert round(number, 2) == number, f"{label} must carry at most 2 decimals, got {value!r}"


def assert_budget_state_consistent(department: dict):
    """budget_state must follow from spend vs budget by the rule in PRD §2.9."""
    spend = department["downtime_spend_cents"]
    budget = department["downtime_budget_cents"]
    if spend >= budget:
        expected = "ON_HOLD"
    elif spend * 100 >= budget * 80:
        expected = "WARNING"
    else:
        expected = "OPEN"
    assert department["budget_state"] == expected, (
        f"Expected budget_state {expected} for spend {spend} of budget {budget}, "
        f"got {department['budget_state']}"
    )


def assert_timestamp_equals(actual: str, expected_instant: str, label: str = "timestamp"):
    """Compare an ISO 8601 instant ignoring the optional fractional-second digits."""
    def norm(value: str) -> str:
        assert isinstance(value, str), f"{label} must be a string, got {value!r}"
        text = value.replace("Z", "")
        if "." in text:
            text = text.split(".")[0]
        return text
    assert norm(actual) == norm(expected_instant), (
        f"Expected {label} {expected_instant}, got {actual}"
    )
