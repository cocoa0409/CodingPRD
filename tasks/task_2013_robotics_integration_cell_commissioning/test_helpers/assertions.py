"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def assert_integrator_org(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["brand_specialization"] in ("FANUC", "ABB", "DUAL")
    assert isinstance(data["retention_rate_bps"], int)
    assert 0 <= data["retention_rate_bps"] <= 2000
    assert data["default_pl_category_target"] in ("PLc", "PLd", "PLe")


def assert_integrator_user(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["user_role"] in (
        "PROJECT_ENGINEER",
        "SAFETY_LEAD",
        "CONTROLS_PROGRAMMER",
        "SITE_SUPERVISOR",
        "TRAINER",
        "SERVICE_MANAGER",
        "FINANCE_ADMIN",
    )
    assert isinstance(data["active"], bool)


def assert_customer_site(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["site_name"], str) and data["site_name"]
    assert isinstance(data["plant_tz"], str) and data["plant_tz"]
    assert isinstance(data["shift_windows_per_day"], int)
    assert 1 <= data["shift_windows_per_day"] <= 3


def assert_cell_project(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["project_code"], str) and data["project_code"]
    assert data["contracted_cycle_time_s"] > 0
    assert isinstance(data["contract_value_cents"], int)
    assert data["contract_value_cents"] > 0
    assert data["status"] in (
        "DRAFT",
        "STUDY",
        "DESIGN",
        "BUILD",
        "FAT",
        "SHIP",
        "SAT",
        "TRAINING",
        "GUARANTEE",
        "CLOSED",
        "ON_HOLD",
        "TERMINATED",
    )
    assert isinstance(data["rework_count"], int) and data["rework_count"] >= 0
    assert isinstance(data["retention_balance_cents"], int)
    assert 50.0 <= data["guaranteed_oee_pct"] <= 99.9
    assert isinstance(data["guarantee_window_days"], int)
    assert 30 <= data["guarantee_window_days"] <= 365


def assert_application_study(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert data["sim_cycle_time_s"] > 0
    assert 0 < data["sim_confidence_pct"] <= 100
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "APPROVED",
        "SUPERSEDED",
        "REJECTED",
    )


def assert_safety_risk_assessment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["assessment_revision"], int)
    assert data["assessment_revision"] >= 1
    assert isinstance(data["risk_score_pre_mitigation"], int)
    assert 1 <= data["risk_score_pre_mitigation"] <= 1000
    assert data["pl_target"] in ("PLc", "PLd", "PLe")
    assert data["status"] in ("DRAFT", "IN_REVIEW", "APPROVED", "REJECTED", "SUPERSEDED")


def assert_robot_selection(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["robot_model"], str) and data["robot_model"]
    assert data["brand"] in ("FANUC", "ABB")
    assert data["rated_payload_kg"] > 0
    assert data["end_effector_weight_kg"] >= 0
    assert data["part_weight_kg"] >= 0
    assert data["wrist_inertia_kgm2"] >= 0
    assert data["wrist_inertia_limit_kgm2"] > 0
    assert data["selection_status"] in ("PROPOSED", "VALIDATED", "REJECTED", "LOCKED")


def assert_robot_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_name"], str) and data["program_name"]
    assert data["dev_status"] in (
        "OUTLINE",
        "CODED",
        "PEER_REVIEWED",
        "RELEASED",
        "REWORK",
    )
    assert data["sim_status"] in (
        "UNSIMULATED",
        "SIM_RUNNING",
        "SIM_PASSED",
        "SIM_FAILED",
    )
    assert isinstance(data["sim_iteration_count"], int)
    assert data["sim_iteration_count"] >= 0
    assert isinstance(data["release_revision"], int) and data["release_revision"] >= 0


def assert_acceptance_test(data: dict):
    _assert_common_fields(data)
    assert data["phase"] in ("FAT", "SAT")
    assert isinstance(data["attempt"], int) and data["attempt"] >= 1
    assert data["measured_cycle_time_s"] is not None
    assert data["measured_oee_pct"] is not None
    assert isinstance(data["defects_observed"], int) and data["defects_observed"] >= 0
    assert data["verdict"] in ("PENDING", "PASS", "CONDITIONAL_PASS", "FAIL")
    assert isinstance(data["recorded_by_user_id"], str)


def assert_spare_parts_package(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["package_code"], str) and data["package_code"]
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] >= 0
    assert isinstance(data["recommended_coverage_months"], int)
    assert 1 <= data["recommended_coverage_months"] <= 60
    assert data["package_status"] in ("QUOTED", "ORDERED", "DELIVERED", "SUPERSEDED")


def assert_maintenance_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["interval_operating_hours"], int)
    assert 500 <= data["interval_operating_hours"] <= 10000
    assert isinstance(data["first_due_at_hours"], int) and data["first_due_at_hours"] >= 0
    assert data["plan_status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["current_operating_hours"], int)


def assert_training_session(data: dict):
    _assert_common_fields(data)
    assert data["audience"] in ("OPERATOR", "TECHNICIAN")
    assert is_iso8601_timestamp(data["scheduled_start_utc"])
    assert is_iso8601_timestamp(data["scheduled_end_utc"])
    assert isinstance(data["trainer_user_id"], str)
    assert isinstance(data["attendee_count"], int)
    assert 1 <= data["attendee_count"] <= 12
    assert data["session_status"] in (
        "SCHEDULED",
        "IN_PROGRESS",
        "COMPLETED",
        "CANCELLED",
        "NO_SHOW",
    )


def assert_throughput_guarantee(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["guarantee_window_days"], int)
    assert 30 <= data["guarantee_window_days"] <= 365
    assert data["guarantee_status"] in (
        "NOT_STARTED",
        "MEASURING",
        "MET",
        "MISSED",
        "WAIVED",
    )


def assert_retention_ledger_entry(data: dict):
    """Append-only: PRD §2.4 — id and created_at only; no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "ledger entries must not carry updated_at"
    assert "version" not in data, "ledger entries must not carry version"
    assert data["entry_type"] in ("WITHHOLD", "RELEASE", "PENALTY", "ADJUST")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["milestone_ref"], str)
    assert is_iso8601_timestamp(data.get("recorded_at_utc", ""))
