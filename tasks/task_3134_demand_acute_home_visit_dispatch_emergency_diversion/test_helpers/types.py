"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    TRIAGE_NURSE = "TriageNurse"
    DISPATCHER = "Dispatcher"
    CARE_TEAM_MEMBER = "CareTeamMember"
    ADVANCED_PRACTICE_PROVIDER = "AdvancedPracticeProvider"
    FIELD_TECHNICIAN = "FieldTechnician"
    SUPERVISING_PHYSICIAN = "SupervisingPhysician"
    BILLING_SPECIALIST = "BillingSpecialist"
    PAYER_ADJUDICATOR = "PayerAdjudicator"


class VisitRequestStatus(str, Enum):
    INTAKE = "INTAKE"
    TRIAGE_PENDING = "TRIAGE_PENDING"
    TRIAGED = "TRIAGED"
    EMS_DIVERTED = "EMS_DIVERTED"
    DECLINED = "DECLINED"
    DISPATCH_PENDING = "DISPATCH_PENDING"
    EN_ROUTE = "EN_ROUTE"
    ON_SCENE = "ON_SCENE"
    DISPOSITIONED = "DISPOSITIONED"
    ESCALATED_TRANSPORT = "ESCALATED_TRANSPORT"
    CLAIM_DRAFT = "CLAIM_DRAFT"
    CLAIM_SUBMITTED = "CLAIM_SUBMITTED"
    CLAIM_ADJUDICATED_PAID = "CLAIM_ADJUDICATED_PAID"
    CLAIM_ADJUDICATED_DENIED = "CLAIM_ADJUDICATED_DENIED"
    CLAIM_APPEALED = "CLAIM_APPEALED"
    CLOSED = "CLOSED"


class AcuityBand(str, Enum):
    EMERGENT = "EMERGENT"
    URGENT = "URGENT"
    STANDARD = "STANDARD"
    NON_ACUTE = "NON_ACUTE"


class TriageOutcome(str, Enum):
    DRAFT = "DRAFT"
    APPROPRIATE = "APPROPRIATE"
    EMERGENCY_DIVERTED = "EMERGENCY_DIVERTED"
    INAPPROPRIATE = "INAPPROPRIATE"


class CareTeamStatus(str, Enum):
    ROSTERED = "ROSTERED"
    AVAILABLE = "AVAILABLE"
    ON_DISPATCH = "ON_DISPATCH"
    OFF_DUTY = "OFF_DUTY"


class VehicleShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    EXTENDED = "EXTENDED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class DispatchAssignmentStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EN_ROUTE = "EN_ROUTE"
    ARRIVED = "ARRIVED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OnSiteEncounterStatus(str, Enum):
    STARTED = "STARTED"
    DIAGNOSTICS = "DIAGNOSTICS"
    DISPOSITION_REVIEW = "DISPOSITION_REVIEW"
    DISCHARGED_HOME = "DISCHARGED_HOME"
    ESCALATED_TRANSPORT = "ESCALATED_TRANSPORT"
    ABORTED = "ABORTED"


class DiagnosticOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    COLLECTED = "COLLECTED"
    RESULTED = "RESULTED"
    VERIFIED = "VERIFIED"
    AMENDED = "AMENDED"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ADJUDICATED_PAID = "ADJUDICATED_PAID"
    ADJUDICATED_DENIED = "ADJUDICATED_DENIED"
    APPEALED = "APPEALED"


class PayerContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class FacilityTransportStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    ARRIVED_AT_FACILITY = "ARRIVED_AT_FACILITY"
    CANCELLED = "CANCELLED"


class FollowUpNoticeStatus(str, Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    FAILED = "FAILED"


class MonitoringCheckInStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    ESCALATED = "ESCALATED"


class RequestorRole(str, Enum):
    PATIENT = "PATIENT"
    PAYER = "PAYER"
    PROVIDER = "PROVIDER"
    FACILITY = "FACILITY"


class OrderKind(str, Enum):
    POCT = "POCT"
    IMAGING = "IMAGING"
    IV_INFUSION = "IV_INFUSION"


class Disposition(str, Enum):
    DISCHARGE_HOME = "DISCHARGE_HOME"
    ESCALATE_TO_FACILITY = "ESCALATE_TO_FACILITY"


class LineKind(str, Enum):
    BASE_VISIT = "BASE_VISIT"
    DIAGNOSTIC = "DIAGNOSTIC"
    IV_DRUG = "IV_DRUG"


# --- Entity TypedDicts (all entities carry common fields) -------------------


class MarketCoverageArea(TypedDict, total=False):
    id: str
    market_code: str
    display_name: str
    polygon_geojson: str
    response_window_minutes_urgent: int
    response_window_minutes_standard: int
    is_active: bool
    open_visit_count: int
    created_at: str
    updated_at: str
    version: int


class PayerContract(TypedDict, total=False):
    id: str
    payer_code: str
    market_id: str
    urgent_base_rate_cents: int
    standard_base_rate_cents: int
    place_of_service_modifier_pct: float
    max_claim_cents: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FormularyEntry(TypedDict, total=False):
    id: str
    payer_contract_id: str
    drug_code: str
    max_units_per_visit: int
    requires_physician_preauth: bool
    unit_price_cents: int
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    payer_code: str
    member_id: str
    pcp_name: str
    pcp_npi: str
    comorbidity_count: int
    home_address_geo: str
    created_at: str
    updated_at: str
    version: int


class CareTeam(TypedDict, total=False):
    id: str
    market_id: str
    app_user_id: str
    tech_user_id: str
    supervising_physician_user_id: str
    skill_tags: list
    status: str
    active_dispatch_count: int
    created_at: str
    updated_at: str
    version: int


class VehicleShift(TypedDict, total=False):
    id: str
    care_team_id: str
    market_id: str
    vehicle_plate: str
    window_start: str
    window_end: str
    status: str
    overtime_minutes: int
    created_at: str
    updated_at: str
    version: int


class VisitRequest(TypedDict, total=False):
    id: str
    patient_id: str
    market_id: str
    requestor_role: str
    chief_complaint: str
    requested_at: str
    status: str
    acuity_band: Optional[str]
    assigned_care_team_id: Optional[str]
    sla_deadline_at: Optional[str]
    sla_breached: bool
    claim_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TriageAssessment(TypedDict, total=False):
    id: str
    visit_request_id: str
    heart_rate: int
    systolic_bp: int
    spo2_pct: int
    is_chest_pain: bool
    is_stroke_signs: bool
    is_severe_trauma: bool
    is_altered_mental_status: bool
    acuity_score: int
    outcome: str
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DispatchAssignment(TypedDict, total=False):
    id: str
    visit_request_id: str
    care_team_id: str
    vehicle_shift_id: str
    offered_at: str
    accepted_at: Optional[str]
    selection_score: float
    status: str
    created_at: str
    updated_at: str
    version: int


class OnSiteEncounter(TypedDict, total=False):
    id: str
    visit_request_id: str
    dispatch_assignment_id: str
    started_at: str
    ended_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DiagnosticOrder(TypedDict, total=False):
    id: str
    encounter_id: str
    order_kind: str
    code: str
    units: int
    result_value: Optional[str]
    physician_preauth_obtained: bool
    physician_preauth_by: Optional[str]
    unit_price_cents: int
    line_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    visit_request_id: str
    payer_contract_id: str
    provisional_total_cents: int
    final_total_cents: int
    submitted_at: Optional[str]
    adjudicated_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ClaimLine(TypedDict, total=False):
    id: str
    claim_id: str
    line_kind: str
    ref_diagnostic_order_id: Optional[str]
    description: str
    amount_cents: int
    created_at: str
    updated_at: str
    version: int


class FollowUpNotice(TypedDict, total=False):
    id: str
    visit_request_id: str
    pcp_npi: str
    payload_summary: str
    sent_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MonitoringCheckIn(TypedDict, total=False):
    id: str
    visit_request_id: str
    scheduled_at: str
    completed_at: Optional[str]
    outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
