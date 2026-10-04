"""Entity assertions and domain invariant checkers (PRD sections 2.5, 2.9, 3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ApplicationStatus,
    AssignmentStatus,
    ConductIncidentStatus,
    CredentialStatus,
    CredentialType,
    DormitoryAssignmentStatus,
    InfractionCode,
    OperatorContractStatus,
    ResidentialStatus,
    ServiceTrackStatus,
    SnapshotVariant,
    TradeProgramStatus,
    TrainingStatus,
    TransitionPlanStatus,
    WBLPlacementStatus,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_applicant(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["home_region_code"], str)
    assert isinstance(data["desired_trade_code"], str)
    assert data["assignment_status"] in {s.value for s in AssignmentStatus}


def assert_application(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("applicant_id", "")), "applicant_id must be UUID"
    assert isinstance(data["intake_counselor_id"], str)
    assert isinstance(data["household_size"], int)
    assert isinstance(data["annual_income_cents"], int)
    assert isinstance(data["barrier_flags"], list)
    assert data["status"] in {s.value for s in ApplicationStatus}
    assert isinstance(data["determination_reasons"], list)


def assert_center(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_code"], str)
    assert isinstance(data["total_beds"], int) and data["total_beds"] >= 1
    assert isinstance(data["beds_in_use"], int)
    assert isinstance(data["beds_available"], int)


def assert_center_bed_invariant(center: dict):
    """PRD section 2.9: beds_in_use + beds_available == total_beds after every mutation."""
    assert center["beds_in_use"] + center["beds_available"] == center["total_beds"], (
        f"bed invariant broken: {center['beds_in_use']} + "
        f"{center['beds_available']} != {center['total_beds']}"
    )


def assert_trade_program(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("center_id", "")), "center_id must be UUID"
    assert isinstance(data["trade_code"], str)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["required_credential_types"], list)
    assert isinstance(data["supports_remediation"], bool)
    assert isinstance(data["enrolled_count"], int)
    assert isinstance(data["open_seats"], int)
    assert data["status"] in {s.value for s in TradeProgramStatus}


def assert_program_seat_invariant(program: dict):
    """PRD section 2.9: enrolled_count + open_seats == capacity after every mutation."""
    assert program["enrolled_count"] + program["open_seats"] == program["capacity"], (
        f"seat invariant broken: {program['enrolled_count']} + "
        f"{program['open_seats']} != {program['capacity']}"
    )


def assert_enrollment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("applicant_id", "")), "applicant_id must be UUID"
    assert is_valid_uuid(data.get("trade_program_id", "")), (
        "trade_program_id must be UUID"
    )
    assert isinstance(data["residential_track"], bool)
    assert data["training_status"] in {s.value for s in TrainingStatus}
    assert data["residential_status"] in {s.value for s in ResidentialStatus}
    assert isinstance(data["conduct_hold"], bool)


def assert_dormitory_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("enrollment_id", "")), "enrollment_id must be UUID"
    assert isinstance(data["bed_label"], str)
    assert isinstance(data["move_in_date"], str)
    assert data["status"] in {s.value for s in DormitoryAssignmentStatus}


def assert_conduct_incident(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("enrollment_id", "")), "enrollment_id must be UUID"
    assert data["infraction_code"] in {c.value for c in InfractionCode}
    assert isinstance(data["zero_tolerance"], bool)
    assert isinstance(data["occurred_at"], str)
    assert data["status"] in {s.value for s in ConductIncidentStatus}


def assert_credential(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("enrollment_id", "")), "enrollment_id must be UUID"
    assert data["credential_type"] in {t.value for t in CredentialType}
    assert data["status"] in {s.value for s in CredentialStatus}
    assert isinstance(data["earned_at"], str)


def assert_employer_agreement(data: dict):
    _assert_common(data)
    assert isinstance(data["employer_name"], str) and data["employer_name"]
    assert isinstance(data["trade_code"], str)
    assert isinstance(data["region_code"], str)
    assert isinstance(data["slot_count"], int) and data["slot_count"] >= 1
    assert isinstance(data["hourly_wage_floor_cents"], int)
    assert isinstance(data["effective_start"], str)
    assert isinstance(data["effective_end"], str)
    assert data["status"] in ("ACTIVE", "EXPIRED")


def assert_wbl_placement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("enrollment_id", "")), "enrollment_id must be UUID"
    assert is_valid_uuid(data.get("employer_agreement_id", "")), (
        "employer_agreement_id must be UUID"
    )
    assert isinstance(data["supervisor_id"], str)
    assert isinstance(data["hourly_wage_cents"], int)
    assert isinstance(data["verified_hours_total"], int)
    assert isinstance(data["provisional_hours_total"], int)
    assert data["status"] in {s.value for s in WBLPlacementStatus}


def assert_transition_plan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("enrollment_id", "")), "enrollment_id must be UUID"
    assert isinstance(data["separation_date"], str)
    assert isinstance(data["expires_at"], str)
    assert data["status"] in {s.value for s in TransitionPlanStatus}
    assert data["job_placement_status"] in {s.value for s in ServiceTrackStatus}
    assert data["housing_status"] in {s.value for s in ServiceTrackStatus}
    assert data["transportation_status"] in {s.value for s in ServiceTrackStatus}


def assert_operator_contract(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("center_id", "")), "center_id must be UUID"
    assert isinstance(data["operator_name"], str) and data["operator_name"]
    assert isinstance(data["contract_code"], str) and data["contract_code"]
    assert data["status"] in {s.value for s in OperatorContractStatus}
    assert isinstance(data["current_period_start"], str)
    assert isinstance(data["period_sequence"], int)


def assert_performance_snapshot(data: dict):
    """Snapshots carry only id + created_at of the common fields (PRD 2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "snapshots never carry updated_at (PRD 2.5)"
    assert "version" not in data, "snapshots never carry version (PRD 2.5)"
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be UUID"
    assert data["variant"] == SnapshotVariant.FINAL.value, (
        "persisted snapshots are always FINAL"
    )
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["graduates_count"], int)
    assert isinstance(data["leavers_count"], int)
    assert isinstance(data["graduation_rate"], (int, float))
    assert isinstance(data["placement_rate"], (int, float))
    assert isinstance(data["avg_starting_wage_cents"], int)
    assert isinstance(data["payment_cents"], int)
