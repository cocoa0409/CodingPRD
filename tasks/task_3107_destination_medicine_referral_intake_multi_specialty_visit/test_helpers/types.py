"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    INTAKE_COORDINATOR = "IntakeCoordinator"
    CASE_REVIEWER = "CaseReviewer"
    FINANCIAL_COUNSELOR = "FinancialCounselor"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"


class ReferralStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RECORDS_PENDING = "RECORDS_PENDING"
    IN_REVIEW = "IN_REVIEW"
    REVIEWED = "REVIEWED"
    DECLINED = "DECLINED"
    CLOSED = "CLOSED"


class MedicalRecordStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class RecordType(str, Enum):
    IMAGING = "IMAGING"
    LAB = "LAB"
    PATHOLOGY = "PATHOLOGY"
    CLINICAL_NOTES = "CLINICAL_NOTES"
    MEDICATION_LIST = "MEDICATION_LIST"


class CaseType(str, Enum):
    DESTINATION = "DESTINATION"
    SECOND_OPINION = "SECOND_OPINION"
    REMOTE_CONSULT = "REMOTE_CONSULT"


class VisitCaseStatus(str, Enum):
    INTAKE = "INTAKE"
    AWAITING_FINANCIAL = "AWAITING_FINANCIAL"
    FINANCIAL_CLEARED = "FINANCIAL_CLEARED"
    SCHEDULING = "SCHEDULING"
    SCHEDULED = "SCHEDULED"
    READY_TO_TRAVEL = "READY_TO_TRAVEL"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"
    DECLINED = "DECLINED"


class ReviewOutcome(str, Enum):
    APPROVE = "APPROVE"
    DECLINE = "DECLINE"


class EstimateLetterStatus(str, Enum):
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"


class FinancialClearanceStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    FORFEITED = "FORFEITED"
    SETTLED = "SETTLED"
    WAIVED = "WAIVED"


class ItineraryStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    LOCKED = "LOCKED"
    CANCELLED = "CANCELLED"


class AppointmentSlotStatus(str, Enum):
    OPEN = "OPEN"
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class VisitType(str, Enum):
    CONSULT = "CONSULT"
    IMAGING = "IMAGING"
    LAB_TEST = "LAB_TEST"
    PROCEDURE = "PROCEDURE"


class VisitStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class ArrangementType(str, Enum):
    TRAVEL = "TRAVEL"
    LODGING = "LODGING"
    INTERPRETER = "INTERPRETER"


class LogisticsStatus(str, Enum):
    REQUESTED = "REQUESTED"
    BOOKED = "BOOKED"
    CANCELLED = "CANCELLED"


class CommType(str, Enum):
    RESULTS_TO_REFERRER = "RESULTS_TO_REFERRER"
    CONTINUITY_PLAN = "CONTINUITY_PLAN"


class ContinuityOwner(str, Enum):
    LOCAL_PHYSICIAN = "LOCAL_PHYSICIAN"
    DESTINATION_TEAM = "DESTINATION_TEAM"
    SHARED = "SHARED"


class TxnType(str, Enum):
    DEPOSIT = "DEPOSIT"
    SETTLEMENT = "SETTLEMENT"
    REFUND = "REFUND"


class TxnStatus(str, Enum):
    POSTED = "POSTED"
    VOID = "VOID"


class SpecialtyService(TypedDict, total=False):
    id: str
    code: str
    name: str
    destination_daily_capacity: int
    service_window_start_min: int
    service_window_end_min: int
    supports_imaging: bool
    supports_remote_products: bool
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict, total=False):
    id: str
    patient: dict
    referring_physician_name: str
    referring_physician_contact: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    residence_country: str
    residence_state: Optional[str]
    preferred_language: str
    is_international: bool
    requires_interpreter: bool
    created_at: str
    updated_at: str
    version: int


class MedicalRecord(TypedDict, total=False):
    id: str
    referral_id: str
    record_type: str
    source_facility: str
    received_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class VisitCase(TypedDict, total=False):
    id: str
    referral_id: str
    case_type: str
    assigned_coordinator_id: str
    care_team_specialty_ids: List[str]
    review_days_used: int
    fatigue_score: int
    status: str
    deposit_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class CaseReview(TypedDict, total=False):
    id: str
    visit_case_id: str
    reviewer_id: str
    outcome: str
    notes: str
    reviewed_on_date: str
    created_at: str
    updated_at: str
    version: int


class EstimateLetter(TypedDict, total=False):
    id: str
    visit_case_id: str
    itinerary_revision_at_issue: int
    provisional_estimate_cents: int
    final_estimate_cents: int
    deposit_amount_cents: int
    is_stale: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class FinancialClearance(TypedDict, total=False):
    id: str
    visit_case_id: str
    required_deposit_cents: int
    deposit_paid_cents: int
    holds_released: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Itinerary(TypedDict, total=False):
    id: str
    visit_case_id: str
    revision: int
    provisional_total_cents: int
    final_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AppointmentSlot(TypedDict, total=False):
    id: str
    specialty_service_id: str
    slot_date: str
    start_min: int
    end_min: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict, total=False):
    id: str
    itinerary_id: str
    visit_case_id: str
    appointment_slot_id: str
    specialty_service_id: str
    visit_type: str
    listed_price_cents: int
    sequencing_priority: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LogisticsArrangement(TypedDict, total=False):
    id: str
    visit_case_id: str
    arrangement_type: str
    details: str
    companion_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Communication(TypedDict, total=False):
    id: str
    visit_case_id: str
    comm_type: str
    body: str
    continuity_plan: Optional[dict]
    sent_at: str
    created_at: str
    updated_at: str
    version: int


class BillingTransaction(TypedDict, total=False):
    id: str
    visit_case_id: str
    financial_clearance_id: str
    txn_type: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
