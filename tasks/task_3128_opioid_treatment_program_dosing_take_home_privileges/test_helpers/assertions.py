"""Entity assertions and domain invariant checkers.

Each ``assert_<entity>`` validates one response payload against the PRD's
declared field contract. The domain invariant checkers encode the conserved
quantities of PRD 2.7 (C1 and C2) and the risk/readiness tiers.
"""

import pytest

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

COMMON_FIELD_NAMES = ("id", "created_at", "updated_at", "version")


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_program(data: dict):
    """Program contract (PRD 2.4, 2.6, 2.8)."""
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["posture"] in ("NORMAL", "RESTRICTED", "FROZEN")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["open_days"], list)
    assert isinstance(data["max_daily_dose_slots"], int)
    assert isinstance(data["dose_checkin_grace_minutes"], int)


def assert_carry_quota_ledger(data: dict):
    """CarryQuotaLedger contract and the C1 identity (PRD 2.7)."""
    _assert_common(data)
    assert isinstance(data["allotted_carries"], int)
    assert isinstance(data["granted_carries"], int)
    assert isinstance(data["available_carries"], int)
    assert data["available_carries"] == data["allotted_carries"] - data["granted_carries"], (
        "C1 identity violated: available_carries must equal "
        "allotted_carries minus granted_carries"
    )


def assert_patient(data: dict):
    """Patient contract (PRD 2.4, 2.5, 3.1, 3.2)."""
    _assert_common(data)
    assert isinstance(data["program_id"], str) and data["program_id"]
    assert data["status"] in (
        "PENDING_ADMISSION", "ADMITTED", "ACTIVE", "SUSPENDED_NON_COMPLIANT",
        "ADMINISTRATIVELY_DISCHARGED", "COMPLETED_WITHDRAWAL",
    )
    assert data["treatment_phase"] in (
        "INDUCTION", "STABILIZATION", "MAINTENANCE", "MEDICAL_WITHDRAWAL",
    )
    assert data["counseling_standing"] in (
        "CURRENT", "COUNSELING_DEFICIENT", "REVIEW_OVERDUE",
    )
    assert data["diversion_standing"] in (
        "CLEAR", "UNDER_INVESTIGATION", "CONFIRMED_DIVERSION",
    )
    assert data["transportation_type"] in (
        "PRIVATE_VEHICLE", "PUBLIC_TRANSIT", "RIDE_SHARE", "NO_RELIABLE_TRANSPORT",
    )
    assert isinstance(data["stability_score"], (int, float))
    assert 0.0 <= data["stability_score"] <= 100.0, "stability_score must be clamped to [0, 100]"
    assert isinstance(data["time_in_treatment_days"], int)
    assert data["time_in_treatment_days"] >= 0
    assert data["risk_tier"] in ("LOW", "MODERATE", "HIGH")


def assert_dose_order(data: dict):
    """DoseOrder contract (PRD 3.3)."""
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "DISCONTINUED")
    assert data["medication"] in ("METHADONE", "BUPRENORPHINE")
    assert isinstance(data["ordered_daily_mg"], (int, float))
    assert isinstance(data["medication_ceiling_mg"], (int, float))


def assert_dose_dispense(data: dict):
    """DoseDispense contract (PRD 3.4)."""
    _assert_common(data)
    assert data["status"] in (
        "SCHEDULED", "ARRIVED_AT_CLINIC", "NURSE_VERIFIED", "DISPENSED",
        "COMPLETED", "VERIFICATION_FAILED", "REFUSED", "MISSED", "CANCELLED",
    )
    assert data["source_type"] in ("OBSERVED_CLINIC", "TAKE_HOME_ISSUANCE", "GUEST_OBSERVED")
    assert isinstance(data["ordered_mg"], (int, float))
    assert data["carry_count"] in (0, 1)
    if data["verification_result"] is not None:
        assert data["verification_result"] in ("PASSED", "FAILED")


def assert_privilege(data: dict):
    """TakeHomePrivilege contract (PRD 3.6)."""
    _assert_common(data)
    assert data["decision"] in (
        "PENDING_REVIEW", "APPROVED", "APPROVED_WITH_EXCEPTION", "DENIED", "REVOKED",
    )
    assert isinstance(data["requested_carries"], int)
    assert isinstance(data["approved_carries"], int)
    assert isinstance(data["freed_carries"], int)
    assert isinstance(data["eligible_carry_cap"], int)
    if data.get("evaluation_basis") is not None:
        assert data["evaluation_basis"] in ("TIME_IN_TREATMENT", "PHASE_STABILITY")


def assert_exception(data: dict):
    """TakeHomeException contract (PRD 3.9)."""
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "SUPERVISOR_REVIEW", "GRANTED", "DENIED", "REVOKED")
    assert data["exception_type"] in (
        "TIME_IN_TREATMENT_WAIVER", "TRAVEL_HARDSHIP", "CLINIC_CLOSURE", "EMERGENCY",
    )
    assert isinstance(data["evaluated_domain_b"], bool)


def assert_carry_ledger(data: dict):
    """TakeHomeCarryLedger contract and the C2 identity (PRD 2.7)."""
    _assert_common(data)
    for field in ("carried_issued_mg", "carried_voided_mg", "carried_dispensed_mg",
                  "carried_consumed_mg", "carried_balance_mg"):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
    assert data["carry_variance"] == 0, "C1 patient-level carry_variance must stay 0"
    expected_balance = (
        data["carried_issued_mg"] - data["carried_voided_mg"]
        - data["carried_dispensed_mg"] - data["carried_consumed_mg"]
    )
    assert data["carried_balance_mg"] == pytest.approx(expected_balance, abs=0.01), (
        "C2 identity violated: carried_balance_mg must equal "
        "carried_issued_mg - carried_voided_mg - carried_dispensed_mg - carried_consumed_mg"
    )


def assert_lot(data: dict):
    """InventoryLot contract (PRD 2.9)."""
    _assert_common(data)
    assert data["status"] in ("RECEIVED", "IN_USE", "DEPLETED", "QUARANTINED", "DESTROYED")
    assert data["medication"] in ("METHADONE", "BUPRENORPHINE")
    assert isinstance(data["running_on_hand_mg"], (int, float))
    assert isinstance(data["is_expired"], bool)
    assert data["on_hand_mg"] == pytest.approx(data["running_on_hand_mg"], abs=0.01), (
        "on_hand_mg is the read alias of running_on_hand_mg"
    )


def assert_inventory_transaction(data: dict):
    """InventoryTransaction contract (PRD 3.12)."""
    _assert_common(data)
    assert data["transaction_type"] in (
        "RECEIPT", "DISPENSE", "WASTE", "RETURN", "ADJUSTMENT", "DESTRUCTION",
    )
    assert data["status"] in ("RECORDED", "RECONCILED", "FLAGGED", "VOIDED")
    assert isinstance(data["quantity_mg"], (int, float))


def assert_counseling_session(data: dict):
    """CounselingSession contract (PRD 3.8)."""
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED")
    assert data["session_type"] in ("INDIVIDUAL", "GROUP", "FAMILY")


def assert_plan_review(data: dict):
    """TreatmentPlanReview contract (PRD 3.8)."""
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "VOIDED")
    assert is_iso8601_timestamp(data["next_due_at"])


def assert_arrangement(data: dict):
    """GuestDosingArrangement contract (PRD 3.11)."""
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "PENDING_RECEIVING_ACK", "ACTIVE", "COMPLETED", "REJECTED", "CANCELLED",
    )
    assert isinstance(data["token_consumed"], bool)


def assert_inspection(data: dict):
    """ComplianceInspection contract (PRD 3.13)."""
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert data["readiness_tier"] in ("READY", "NEEDS_ATTENTION", "NOT_READY")
    assert isinstance(data["readiness_score"], (int, float))


def assert_finding(data: dict):
    """ComplianceFinding contract (PRD 3.13)."""
    _assert_common(data)
    assert data["status"] in ("OPEN", "CORRECTED", "WAIVED")
    assert data["severity"] in ("MINOR", "MAJOR", "CRITICAL")


def assert_corrective_action(data: dict):
    """CorrectiveAction contract (PRD 3.13)."""
    _assert_common(data)
    assert data["status"] in ("OPEN", "IMPLEMENTED", "VERIFIED_CLOSED", "CANCELED")
    assert data["severity"] in ("MINOR", "MAJOR", "CRITICAL")


def assert_diversion_case(data: dict):
    """DiversionCase contract (PRD 3.10)."""
    _assert_common(data)
    assert data["status"] in (
        "OPEN", "UNDER_REVIEW", "CONFIRMED", "UNSUBSTANTIATED", "CLOSED",
    )
    assert data["detection_source"] in (
        "COUNT_MISMATCH", "URINE_SCREEN", "WITNESS_REPORT", "GUEST_CLINIC_REPORT",
    )


def assert_user(data: dict):
    """User contract (PRD 3.15)."""
    _assert_common(data)
    assert data["staff_role"] in (
        "PHYSICIAN", "NURSE", "COUNSELOR", "MEDICAL_DIRECTOR", "PROGRAM_ADMIN", "REGULATOR",
    )
    assert isinstance(data["is_active"], bool)


# --- Domain invariant checkers ----------------------------------------------

def assert_carry_quota_invariant(ledger: dict):
    """C1 at the program level: available_carries == allotted_carries - granted_carries."""
    assert ledger["available_carries"] == ledger["allotted_carries"] - ledger["granted_carries"], (
        f"C1 violated: {ledger['allotted_carries']} - {ledger['granted_carries']} "
        f"!= {ledger['available_carries']}"
    )


def assert_carry_milligram_invariant(ledger: dict):
    """C2 at the patient level, plus carry_variance == 0."""
    assert ledger["carry_variance"] == 0
    expected = (ledger["carried_issued_mg"] - ledger["carried_voided_mg"]
                - ledger["carried_dispensed_mg"] - ledger["carried_consumed_mg"])
    assert ledger["carried_balance_mg"] == pytest.approx(expected, abs=0.01)


def assert_tariff_precision(value: float):
    """The dose tariff rounds to two decimal places (PRD 2.12)."""
    assert_cost_precision(value, 2)


def assert_readiness_precision(value: float):
    """The readiness score rounds to one decimal place (PRD 2.12)."""
    assert_cost_precision(value, 1)