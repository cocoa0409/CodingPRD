"""Domain types for the OTP dosing, take-home privileges and compliance API.

Entity TypedDicts, status enumerations and the acting-role enumeration.
Every persisted resource in this API carries the same four system-managed
properties described in PRD §2.4: id, created_at, updated_at and version.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Acting roles (the six-member enumeration of PRD §2.1) ───────────────────

class UserRole(str, Enum):
    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
    PHYSICIAN = "Physician"
    NURSE = "Nurse"
    COUNSELOR = "Counselor"
    MEDICAL_DIRECTOR = "MedicalDirector"
    REGULATORY_AUDITOR = "RegulatoryAuditor"


# ─── Status enumerations ─────────────────────────────────────────────────────

class ProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ProgramPosture(str, Enum):
    NORMAL = "NORMAL"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class PatientStatus(str, Enum):
    PENDING_ADMISSION = "PENDING_ADMISSION"
    ADMITTED = "ADMITTED"
    ACTIVE = "ACTIVE"
    SUSPENDED_NON_COMPLIANT = "SUSPENDED_NON_COMPLIANT"
    ADMINISTRATIVELY_DISCHARGED = "ADMINISTRATIVELY_DISCHARGED"
    COMPLETED_WITHDRAWAL = "COMPLETED_WITHDRAWAL"


class TreatmentPhase(str, Enum):
    INDUCTION = "INDUCTION"
    STABILIZATION = "STABILIZATION"
    MAINTENANCE = "MAINTENANCE"
    MEDICAL_WITHDRAWAL = "MEDICAL_WITHDRAWAL"


class CounselingStanding(str, Enum):
    CURRENT = "CURRENT"
    COUNSELING_DEFICIENT = "COUNSELING_DEFICIENT"
    REVIEW_OVERDUE = "REVIEW_OVERDUE"


class DiversionStanding(str, Enum):
    CLEAR = "CLEAR"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    CONFIRMED_DIVERSION = "CONFIRMED_DIVERSION"


class RiskTier(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class Medication(str, Enum):
    METHADONE = "METHADONE"
    BUPRENORPHINE = "BUPRENORPHINE"


class DoseOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DISCONTINUED = "DISCONTINUED"


class DoseSourceType(str, Enum):
    OBSERVED_CLINIC = "OBSERVED_CLINIC"
    TAKE_HOME_ISSUANCE = "TAKE_HOME_ISSUANCE"
    GUEST_OBSERVED = "GUEST_OBSERVED"


class DoseStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ARRIVED_AT_CLINIC = "ARRIVED_AT_CLINIC"
    NURSE_VERIFIED = "NURSE_VERIFIED"
    DISPENSED = "DISPENSED"
    COMPLETED = "COMPLETED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    REFUSED = "REFUSED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class PrivilegeDecision(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    APPROVED_WITH_EXCEPTION = "APPROVED_WITH_EXCEPTION"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class DenialReasonCode(str, Enum):
    TIME_IN_TREATMENT_INSUFFICIENT = "TIME_IN_TREATMENT_INSUFFICIENT"
    STABILITY_BELOW_THRESHOLD = "STABILITY_BELOW_THRESHOLD"
    ACTIVE_DENIAL_HISTORY = "ACTIVE_DENIAL_HISTORY"
    TIMETABLE_LOOKAHEAD_FAILED = "TIMETABLE_LOOKAHEAD_FAILED"
    CLINIC_MAX_CARRIES_EXCEEDED = "CLINIC_MAX_CARRIES_EXCEEDED"
    SUPERVISOR_REVIEW_REQUIRED = "SUPERVISOR_REVIEW_REQUIRED"
    TRANSPORTATION_RISK_UNMITIGATED = "TRANSPORTATION_RISK_UNMITIGATED"
    DIVERSIONS_OR_FINDINGS_OPEN = "DIVERSIONS_OR_FINDINGS_OPEN"
    PROGRAM_POSTURE_RESTRICTED = "PROGRAM_POSTURE_RESTRICTED"


class EvaluationBasis(str, Enum):
    TIME_IN_TREATMENT = "TIME_IN_TREATMENT"
    PHASE_STABILITY = "PHASE_STABILITY"


class ExceptionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SUPERVISOR_REVIEW = "SUPERVISOR_REVIEW"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class LotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    IN_USE = "IN_USE"
    DEPLETED = "DEPLETED"
    QUARANTINED = "QUARANTINED"
    DESTROYED = "DESTROYED"


class TransactionType(str, Enum):
    RECEIPT = "RECEIPT"
    DISPENSE = "DISPENSE"
    WASTE = "WASTE"
    RETURN = "RETURN"
    ADJUSTMENT = "ADJUSTMENT"
    DESTRUCTION = "DESTRUCTION"


class TransactionStatus(str, Enum):
    RECORDED = "RECORDED"
    RECONCILED = "RECONCILED"
    FLAGGED = "FLAGGED"
    VOIDED = "VOIDED"


class CounselingSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ArrangementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_RECEIVING_ACK = "PENDING_RECEIVING_ACK"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DiversionCaseStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    CONFIRMED = "CONFIRMED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"
    CLOSED = "CLOSED"


class CorrectiveActionStatus(str, Enum):
    OPEN = "OPEN"
    IMPLEMENTED = "IMPLEMENTED"
    VERIFIED_CLOSED = "VERIFIED_CLOSED"
    CANCELED = "CANCELED"


# ─── Entity TypedDicts (every resource carries the four system properties) ───

class Program(TypedDict):
    id: str
    name: str
    state_code: str
    clinic_hours_start: str
    clinic_hours_end: str
    dose_checkin_grace_minutes: int
    open_days: List[str]
    max_daily_dose_slots: int
    max_daily_mg_methadone: float
    max_daily_mg_buprenorphine: float
    guest_dosing_enabled: bool
    posture: str
    posture_reason_code: Optional[str]
    open_diversion_case_count: int
    open_critical_finding_count: int
    latest_inventory_variance_mg: float
    pending_waste_mg: float
    cumulative_write_off_mg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CarryQuotaLedger(TypedDict):
    id: str
    program_id: str
    allotted_carries: int
    granted_carries: int
    released_carries: int
    available_carries: int
    held_privilege_count: int
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    program_id: str
    full_name: str
    date_of_birth: str
    government_id_hash: str
    diagnosis_code: str
    diagnosis_confirmed: bool
    home_state_code: str
    home_address: str
    transportation_type: str
    one_way_travel_minutes: int
    status: str
    treatment_phase: str
    counseling_standing: str
    diversion_standing: str
    admission_datetime: Optional[str]
    time_in_treatment_days: int
    risk_tier: str
    risk_score_points: float
    stability_posting: int
    stability_score: float
    denial_count_12mo: int
    missed_dose_streak: int
    carries_used: int
    journal_reconciled_through_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DoseOrder(TypedDict):
    id: str
    patient_id: str
    program_id: str
    medication: str
    ordered_daily_mg: float
    medication_ceiling_mg: float
    split_dose_authorized: bool
    previous_ordered_daily_mg: float
    phase_at_authorization: Optional[str]
    last_increase_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DoseDispense(TypedDict):
    id: str
    dose_order_id: str
    patient_id: str
    program_id: str
    dose_date: str
    scheduled_datetime: str
    source_type: str
    ordered_mg: float
    dispensed_mg: float
    wasted_mg: float
    returned_mg: float
    carry_count: int
    carries_before: int
    carries_after: int
    verification_result: Optional[str]
    inventory_lot_id: Optional[str]
    witness_staff_id: Optional[str]
    verification_staff_id: Optional[str]
    arrived_at: Optional[str]
    completed_at: Optional[str]
    guest_arrangement_id: Optional[str]
    privilege_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TakeHomePrivilege(TypedDict):
    id: str
    patient_id: str
    program_id: str
    requested_carries: int
    carry_interval_days: int
    approved_carries: int
    freed_carries: int
    expires_on: Optional[str]
    decision: str
    denial_reason_code: Optional[str]
    exception_id: Optional[str]
    evaluation_basis: Optional[str]
    timetable_reconciled: bool
    eligible_carry_cap: int
    reissued_from_privilege_id: Optional[str]
    hold_ledger_delta: int
    created_at: str
    updated_at: str
    version: int


class TakeHomeException(TypedDict):
    id: str
    patient_id: str
    program_id: str
    requested_carries: int
    exception_type: str
    clinical_justification: str
    requesting_physician_id: str
    supervisor_id: str
    granted_carries: int
    status: str
    evaluated_domain_b: bool
    created_at: str
    updated_at: str
    version: int


class TakeHomeCarryLedger(TypedDict):
    id: str
    patient_id: str
    program_id: str
    owns_privilege_count: int
    carries_used: int
    carry_variance: int
    carried_balance_mg: float
    carried_issued_mg: float
    carried_dispensed_mg: float
    carried_voided_mg: float
    carried_consumed_mg: float
    carries_held: int
    charges_held: int
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict):
    id: str
    program_id: str
    medication: str
    lot_number: str
    expiration_date: str
    quantity_received_mg: float
    dose_potency_mg_per_unit: float
    reusable_for_take_home: bool
    running_on_hand_mg: float
    on_hand_mg: float
    is_expired: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryTransaction(TypedDict):
    id: str
    lot_id: str
    program_id: str
    patient_id: Optional[str]
    dose_dispense_id: Optional[str]
    transaction_type: str
    quantity_mg: float
    reconciliation_period: str
    witness_staff_id: Optional[str]
    residual_variance_mg: float
    cumulative_write_off_mg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CounselingSession(TypedDict):
    id: str
    patient_id: str
    program_id: str
    session_type: str
    scheduled_datetime: str
    duration_minutes: int
    counselor_staff_id: Optional[str]
    completed_at: Optional[str]
    attended_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TreatmentPlanReview(TypedDict):
    id: str
    patient_id: str
    program_id: str
    reviewer_physician_id: str
    reviewed_at: str
    cadence_days_applied: int
    next_due_at: str
    signed_off: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class GuestDosingArrangement(TypedDict):
    id: str
    patient_id: str
    originating_program_id: str
    receiving_program_id: str
    travel_start_date: str
    travel_end_date: str
    dose_authorization_token: Optional[str]
    authorized_mg: Optional[float]
    token_consumed: bool
    status: str
    receiving_acknowledged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceInspection(TypedDict):
    id: str
    program_id: str
    inspecting_agency: str
    scheduled_date: str
    inspection_type: str
    readiness_score: float
    readiness_tier: str
    finding_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceFinding(TypedDict):
    id: str
    inspection_id: str
    program_id: str
    requirement_code: str
    severity: str
    status: str
    corrected_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CorrectiveAction(TypedDict):
    id: str
    program_id: str
    finding_id: Optional[str]
    severity: str
    plan_text: str
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DiversionCase(TypedDict):
    id: str
    program_id: str
    patient_id: str
    related_dose_dispense_id: Optional[str]
    opened_by_user_id: str
    detection_source: str
    severity: str
    status: str
    confirmed_at: Optional[str]
    outcome_summary: Optional[str]
    created_at: str
    updated_at: str
    version: int


class User(TypedDict):
    id: str
    program_id: Optional[str]
    full_name: str
    staff_role: str
    license_number: Optional[str]
    is_active: bool
    created_at: str
    updated_at: str
    version: int