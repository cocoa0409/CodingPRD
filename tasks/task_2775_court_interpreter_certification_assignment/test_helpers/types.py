"""Domain types for the court-interpreter certification and assignment program.

Entity TypedDicts, status enums and the role enum. Generic envelope types live
in prd_bench_local_runner.testing and are never redefined here.

Two entities are append-only (SCAFFOLD common_fields: false) and therefore carry
ONLY `id` and `created_at`: ExamAttempt and UnmetNeedReport. Their TypedDicts
deliberately omit `updated_at` and `version`.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    CREDENTIALING_OFFICER = "CredentialingOfficer"
    SCHEDULING_COORDINATOR = "SchedulingCoordinator"
    FISCAL_OFFICER = "FiscalOfficer"
    QUALITY_REVIEWER = "QualityReviewer"
    INTERPRETER = "Interpreter"


# --------------------------------------------------------------------------
# Configuration enums
# --------------------------------------------------------------------------
class LanguageTierClass(str, Enum):
    DESIGNATED = "DESIGNATED"
    NON_DESIGNATED = "NON_DESIGNATED"
    RARE = "RARE"


class RemoteEquipmentTier(str, Enum):
    NONE = "NONE"
    BASIC = "BASIC"
    CERTIFIED_VRI = "CERTIFIED_VRI"


class CourthouseStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


# --------------------------------------------------------------------------
# Roster enums
# --------------------------------------------------------------------------
class RosterStatus(str, Enum):
    APPLICANT = "APPLICANT"
    CANDIDATE = "CANDIDATE"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    INACTIVE = "INACTIVE"
    REVOKED = "REVOKED"


class EthicsTrainingStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    COMPLETED = "COMPLETED"


class CredentialTier(str, Enum):
    MASTER = "MASTER"
    CERTIFIED = "CERTIFIED"
    REGISTERED = "REGISTERED"
    PROVISIONAL = "PROVISIONAL"
    NONE = "NONE"


class CredentialStatus(str, Enum):
    PENDING_WRITTEN = "PENDING_WRITTEN"
    PENDING_ORAL = "PENDING_ORAL"
    PENDING_ETHICS = "PENDING_ETHICS"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    REVOKED = "REVOKED"


class ExamType(str, Enum):
    WRITTEN = "WRITTEN"
    ORAL = "ORAL"


class ExamResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


# --------------------------------------------------------------------------
# Calendar and service enums
# --------------------------------------------------------------------------
class HearingType(str, Enum):
    ARRAIGNMENT = "ARRAIGNMENT"
    DETENTION_REVIEW = "DETENTION_REVIEW"
    TRIAL = "TRIAL"
    PLEA = "PLEA"
    SENTENCING = "SENTENCING"
    MOTION = "MOTION"
    CIVIL_MOTION = "CIVIL_MOTION"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COVERED = "COVERED"
    SERVED = "SERVED"
    UNMET = "UNMET"
    CONTINUED = "CONTINUED"


class PriorityClass(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class ContinuanceReasonCode(str, Enum):
    COURT_CONGESTION = "COURT_CONGESTION"
    PARTY_REQUEST = "PARTY_REQUEST"
    NO_INTERPRETER_AVAILABLE = "NO_INTERPRETER_AVAILABLE"


class DeliveryMode(str, Enum):
    IN_PERSON = "IN_PERSON"
    VRI = "VRI"
    TELEPHONIC = "TELEPHONIC"


class AssignmentServiceStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"
    NO_SHOW = "NO_SHOW"


class AssignmentComplianceStatus(str, Enum):
    CLEAR = "CLEAR"
    UNDER_QUALITY_REVIEW = "UNDER_QUALITY_REVIEW"
    SUBSTANTIATED_DEFECT = "SUBSTANTIATED_DEFECT"


class CancelReasonCode(str, Enum):
    INTERPRETER_DECLINED = "INTERPRETER_DECLINED"
    COURT_CONTINUANCE = "COURT_CONTINUANCE"
    INTERPRETER_SUSPENDED = "INTERPRETER_SUSPENDED"
    CREDENTIAL_LAPSED = "CREDENTIAL_LAPSED"
    CREDENTIAL_REVOKED = "CREDENTIAL_REVOKED"
    EQUIPMENT_WITHDRAWN = "EQUIPMENT_WITHDRAWN"
    COORDINATOR_CANCELLED = "COORDINATOR_CANCELLED"


# --------------------------------------------------------------------------
# Money enums
# --------------------------------------------------------------------------
class PayClaimVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class PayClaimStatus(str, Enum):
    ENCUMBERED = "ENCUMBERED"
    FINALIZED = "FINALIZED"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    VOIDED = "VOIDED"


# --------------------------------------------------------------------------
# Discipline enums
# --------------------------------------------------------------------------
class ComplaintCategory(str, Enum):
    ACCURACY = "ACCURACY"
    ETHICS = "ETHICS"
    PROFESSIONALISM = "PROFESSIONALISM"
    NO_SHOW = "NO_SHOW"


class ComplaintSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    SEVERE = "SEVERE"


class ComplaintStatus(str, Enum):
    FILED = "FILED"
    REVIEWED = "REVIEWED"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"
    APPEALED = "APPEALED"
    UPHELD = "UPHELD"
    VACATED = "VACATED"


class ReviewRecommendation(str, Enum):
    SUBSTANTIATE = "SUBSTANTIATE"
    DISMISS = "DISMISS"


class Disposition(str, Enum):
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"


class AppealOutcome(str, Enum):
    UPHELD = "UPHELD"
    VACATED = "VACATED"
    REMANDED = "REMANDED"


class SanctionType(str, Enum):
    LETTER = "LETTER"
    PROBATION = "PROBATION"
    SUSPENSION = "SUSPENSION"
    REVOCATION = "REVOCATION"


class DisciplinaryActionStatus(str, Enum):
    IN_EFFECT = "IN_EFFECT"
    EXPIRED = "EXPIRED"
    RESCINDED = "RESCINDED"


class ReportComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    CORRECTIVE_ACTION_REQUIRED = "CORRECTIVE_ACTION_REQUIRED"
    NON_COMPLIANT = "NON_COMPLIANT"


# --------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.4, §3.1-§3.10)
# --------------------------------------------------------------------------
class Language(TypedDict):
    id: str
    code: str
    name: str
    tier_class: str
    oral_exam_available: bool
    telephonic_vendor_available: bool
    active_credentialed_count: int
    created_at: str
    updated_at: str
    version: int


class Courthouse(TypedDict):
    id: str
    name: str
    county_code: str
    courtroom_count: int
    remote_equipment_tier: str
    vri_concurrent_capacity: int
    status: str
    pay_budget_cents: int
    encumbered_pay_cents: int
    obligated_pay_cents: int
    available_pay_cents: int
    created_at: str
    updated_at: str
    version: int


class RateSchedule(TypedDict):
    id: str
    effective_from: str
    effective_through: Optional[str]
    master_hourly_cents: int
    certified_hourly_cents: int
    registered_hourly_cents: int
    provisional_hourly_cents: int
    minimum_call_hours: float
    travel_mileage_rate_cents: float
    travel_free_radius_miles: float
    remote_rate_multiplier: float
    late_cancellation_hours: int
    late_cancellation_pay_hours: float
    rare_premium_low_pct: float
    rare_premium_high_pct: float
    rare_premium_bracket_cents: int
    created_at: str
    updated_at: str
    version: int


class Interpreter(TypedDict):
    id: str
    full_name: str
    email: str
    phone: Optional[str]
    home_county_code: str
    accepts_in_person: bool
    accepts_remote: bool
    roster_status: str
    ethics_training_status: str
    ethics_completed_on: Optional[str]
    credential_tier: str
    credentialed_language_ids: List[str]
    complaint_points: int
    rolling_12_month_score: float
    lifetime_score: float
    pending_pay_cents: int
    paid_pay_cents: int
    suspension_through: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Credential(TypedDict):
    id: str
    interpreter_id: str
    language_id: str
    target_tier: str
    tier: Optional[str]
    status: str
    written_best_score: Optional[float]
    oral_best_score: Optional[float]
    written_attempt_count: int
    oral_attempt_count: int
    issued_on: Optional[str]
    expires_on: Optional[str]
    grace_through: Optional[str]
    cycle_credit_hours: float
    renewal_count: int
    created_at: str
    updated_at: str
    version: int


class ExamAttempt(TypedDict):
    """Append-only (common_fields: false) — carries only id + created_at."""
    id: str
    credential_id: str
    exam_type: str
    score: float
    taken_on: str
    attempt_ordinal: int
    result: str
    created_at: str


class Hearing(TypedDict):
    id: str
    courthouse_id: str
    language_id: str
    case_number: str
    hearing_type: str
    in_custody: bool
    scheduled_start: str
    scheduled_end: str
    requested_delivery_mode: str
    status: str
    lead_time_days: int
    priority_score: int
    priority_class: str
    continuance_count: int
    continuance_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    hearing_id: str
    interpreter_id: Optional[str]
    credential_id: Optional[str]
    credential_tier_snapshot: Optional[str]
    delivery_mode: str
    vendor_served: bool
    estimated_one_way_miles: float
    actual_one_way_miles: Optional[float]
    service_status: str
    compliance_status: str
    check_in_utc: Optional[str]
    actual_end_utc: Optional[str]
    cancel_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayClaim(TypedDict):
    id: str
    assignment_id: str
    rate_schedule_id: str
    variant: str
    status: str
    billable_hours: float
    service_cents: int
    rare_premium_cents: int
    travel_cents: int
    provisional_total_cents: int
    final_total_cents: Optional[int]
    late_cancellation: bool
    payment_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    interpreter_id: str
    assignment_id: Optional[str]
    category: str
    severity: str
    narrative: str
    filed_by_user_id: str
    reviewer_user_id: Optional[str]
    reviewer_recommendation: Optional[str]
    adjudicator_user_id: Optional[str]
    disposition: Optional[str]
    status: str
    adjudicated_at: Optional[str]
    appeal_filed_at: Optional[str]
    remand_count: int
    created_at: str
    updated_at: str
    version: int


class DisciplinaryAction(TypedDict):
    id: str
    complaint_id: str
    interpreter_id: str
    action_type: str
    points: int
    effective_from: str
    effective_through: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class UnmetNeedReport(TypedDict):
    """Append-only (common_fields: false) — carries only id + created_at."""
    id: str
    courthouse_id: str
    period_start: str
    period_end: str
    resolved_hearing_count: int
    served_hearing_count: int
    unmet_hearing_count: int
    rare_language_unmet_count: int
    coverage_rate_pct: float
    compliance_status: str
    by_language: Dict[str, Any]
    created_at: str


class QualityScoreRead(TypedDict):
    """Computed read returned by GET /interpreters/{id}/quality-score (PRD §3.2)."""
    interpreter_id: str
    rolling_12_month_score: float
    lifetime_score: float
    complaint_points: int
    recent_points: int
    older_points: int
