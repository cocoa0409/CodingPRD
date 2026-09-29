"""Domain types for the Aging Life Care Coordination API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------- roles ------
class UserRole(str, Enum):
    CARE_MANAGER = "CareManager"
    PRACTICE_SUPERVISOR = "PracticeSupervisor"
    FAMILY_DECISION_MAKER = "FamilyDecisionMaker"
    BILLING_ADMINISTRATOR = "BillingAdministrator"
    PRACTICE_ADMIN = "PracticeAdmin"


# ------------------------------------------------------------ enumerations ---
class ClientStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ASSESSMENT_IN_PROGRESS = "ASSESSMENT_IN_PROGRESS"
    ACTIVE_CARE = "ACTIVE_CARE"
    SUSPENDED_NONPAYMENT = "SUSPENDED_NONPAYMENT"
    DISCHARGED = "DISCHARGED"


class CapacityStatus(str, Enum):
    PRESUMED_CAPABLE = "PRESUMED_CAPABLE"
    DIMINISHED_DOCUMENTED = "DIMINISHED_DOCUMENTED"
    ADJUDICATED_INCAPACITATED = "ADJUDICATED_INCAPACITATED"


class RiskPosture(str, Enum):
    ROUTINE = "ROUTINE"
    ELEVATED = "ELEVATED"
    CRISIS = "CRISIS"


class ResidenceSetting(str, Enum):
    PRIVATE_HOME = "PRIVATE_HOME"
    ASSISTED_LIVING = "ASSISTED_LIVING"
    SKILLED_NURSING = "SKILLED_NURSING"
    HOSPITAL = "HOSPITAL"


class ProtectiveEscalationStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class Credential(str, Enum):
    CMC = "CMC"
    CCM = "CCM"
    CMAC = "CMAC"
    C_ASWCM = "C_ASWCM"


class VendorType(str, Enum):
    HOME_CARE = "HOME_CARE"
    MEDICAL = "MEDICAL"
    LEGAL = "LEGAL"
    HOUSING = "HOUSING"


class VendorStanding(str, Enum):
    APPROVED = "APPROVED"
    PROBATION = "PROBATION"
    BARRED = "BARRED"


class ContactRole(str, Enum):
    POA_HEALTHCARE = "POA_HEALTHCARE"
    POA_FINANCIAL = "POA_FINANCIAL"
    GUARDIAN = "GUARDIAN"
    RESPONSIBLE_PARTY = "RESPONSIBLE_PARTY"
    INTERESTED_FAMILY = "INTERESTED_FAMILY"


class ReportStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    CURRENT = "CURRENT"
    DUE = "DUE"
    OVERDUE = "OVERDUE"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    ACCEPTED = "ACCEPTED"
    WITHDRAWN = "WITHDRAWN"


class CarePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_FAMILY_APPROVAL = "PENDING_FAMILY_APPROVAL"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class AuthStatus(str, Enum):
    PROPOSED = "PROPOSED"
    AUTHORIZED = "AUTHORIZED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class CoiStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING_DISCLOSURE = "PENDING_DISCLOSURE"
    DISCLOSED = "DISCLOSED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class CoiAction(str, Enum):
    DISCLOSE = "DISCLOSE"
    ACKNOWLEDGE = "ACKNOWLEDGE"


class SuspensionReason(str, Enum):
    NONE = "NONE"
    NONPAYMENT = "NONPAYMENT"
    VENDOR_STANDING = "VENDOR_STANDING"
    FAMILY_REQUEST = "FAMILY_REQUEST"


class TerminationReason(str, Enum):
    NONE = "NONE"
    CARE_MANAGER_REQUEST = "CARE_MANAGER_REQUEST"
    DECISION_RESCINDED = "DECISION_RESCINDED"
    PLAN_SUPERSEDED = "PLAN_SUPERSEDED"
    VENDOR_STANDING = "VENDOR_STANDING"
    CLIENT_DISCHARGED = "CLIENT_DISCHARGED"


class ConferenceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONVENED = "CONVENED"
    DOCUMENTED = "DOCUMENTED"
    RESCHEDULED = "RESCHEDULED"
    CANCELLED = "CANCELLED"


class DecisionType(str, Enum):
    VENDOR_ENGAGEMENT = "VENDOR_ENGAGEMENT"
    PLACEMENT_CHANGE = "PLACEMENT_CHANGE"
    CARE_LEVEL_CHANGE = "CARE_LEVEL_CHANGE"
    ESCALATE_GUARDIANSHIP_PETITION = "ESCALATE_GUARDIANSHIP_PETITION"
    ESCALATE_APS_REPORT = "ESCALATE_APS_REPORT"


class DecisionStatus(str, Enum):
    RECORDED = "RECORDED"
    RATIFIED = "RATIFIED"
    ESCALATED = "ESCALATED"
    ESCALATION_ACCEPTED = "ESCALATION_ACCEPTED"
    ESCALATION_DECLINED = "ESCALATION_DECLINED"
    RESCINDED = "RESCINDED"


class CrisisTriggerType(str, Enum):
    HOSPITAL_ADMISSION = "HOSPITAL_ADMISSION"
    FALL = "FALL"
    CAREGIVER_NO_SHOW = "CAREGIVER_NO_SHOW"
    ACUTE_BEHAVIORAL = "ACUTE_BEHAVIORAL"
    ELDER_ABUSE_SUSPICION = "ELDER_ABUSE_SUSPICION"


class CrisisEpisodeStatus(str, Enum):
    OPEN = "OPEN"
    STABILIZED = "STABILIZED"
    TRANSITION_OVERSIGHT = "TRANSITION_OVERSIGHT"
    CLOSED = "CLOSED"


class ServiceType(str, Enum):
    ASSESSMENT = "ASSESSMENT"
    CARE_COORDINATION = "CARE_COORDINATION"
    CRISIS_RESPONSE = "CRISIS_RESPONSE"
    TRAVEL = "TRAVEL"
    CONFERENCE = "CONFERENCE"


class TimeEntryStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    INVOICED = "INVOICED"
    VOIDED = "VOIDED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class InvoiceVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


# ----------------------------------------------------------- entity shapes ---
# Every entity in this system carries id, created_at, updated_at and version.
class Client(TypedDict):
    id: str
    full_name: str
    residence_setting: str
    status: str
    capacity_status: str
    capacity_basis: Optional[str]
    risk_posture: str
    acuity_score: int
    billing_increment_min: int
    travel_billing_pct: int
    retainer_floor_cents: int
    authorized_concurrent_caregivers: int
    retainer_deposits_total_cents: int
    retainer_balance_cents: int
    unbilled_accrual_cents: int
    authorized_coverage_hours: float
    protective_escalation_status: str
    created_at: str
    updated_at: str
    version: int


class CareManager(TypedDict):
    id: str
    full_name: str
    credential: str
    hourly_rate_cents: int
    is_supervisor: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    name: str
    vendor_type: str
    has_referral_relationship: bool
    referral_fee_pct: float
    standing: str
    created_at: str
    updated_at: str
    version: int


class FamilyContact(TypedDict):
    id: str
    client_id: str
    full_name: str
    contact_role: str
    is_surrogate_decision_maker: bool
    is_long_distance: bool
    reporting_cadence_days: int
    last_report_sent_at: Optional[str]
    reports_sent_count: int
    report_status: str
    days_overdue: int
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict):
    id: str
    client_id: str
    care_manager_id: str
    reviewed_by_care_manager_id: Optional[str]
    domain_scores: Dict[str, int]
    narrative: Optional[str]
    status: str
    revision_round: int
    screening_acuity: Optional[int]
    comprehensive_acuity: Optional[int]
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CarePlan(TypedDict):
    id: str
    client_id: str
    source_assessment_id: str
    supersedes_care_plan_id: Optional[str]
    approved_by_contact_id: Optional[str]
    goals: List[str]
    review_interval_days: int
    pinned_assessment_version: int
    status: str
    rejection_rounds: int
    coverage_gap_flag: bool
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceAuthorization(TypedDict):
    id: str
    care_plan_id: str
    vendor_id: str
    client_id: str
    authorizing_decision_id: Optional[str]
    coi_acknowledged_by_contact_id: Optional[str]
    coverage_start: str
    coverage_end: str
    concurrent_caregivers: int
    hourly_cost_cents: int
    coverage_hours: float
    base_cost_cents: int
    coordination_fee_cents: int
    total_projected_cost_cents: int
    auth_status: str
    coi_status: str
    disclosure_text: Optional[str]
    suspension_reason: str
    termination_reason: str
    created_at: str
    updated_at: str
    version: int


class FamilyConference(TypedDict):
    id: str
    client_id: str
    scheduled_start: str
    scheduled_end: str
    invited_contact_ids: List[str]
    attended_contact_ids: List[str]
    agenda: Optional[str]
    status: str
    reschedule_count: int
    quorum_met: bool
    surrogate_present: bool
    convened_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConferenceDecision(TypedDict):
    id: str
    family_conference_id: str
    decided_by_contact_id: str
    decision_type: str
    decision_text: str
    capacity_basis: Optional[str]
    status: str
    ratified_at: Optional[str]
    escalated_at: Optional[str]
    rescinded_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CrisisEpisode(TypedDict):
    id: str
    client_id: str
    assigned_care_manager_id: Optional[str]
    trigger_type: str
    hospital_name: Optional[str]
    opened_at: str
    stabilized_at: Optional[str]
    discharge_at: Optional[str]
    closed_at: Optional[str]
    status: str
    readmission_count: int
    created_at: str
    updated_at: str
    version: int


class TimeEntry(TypedDict):
    id: str
    client_id: str
    care_manager_id: str
    approved_by_care_manager_id: Optional[str]
    invoice_id: Optional[str]
    crisis_episode_id: Optional[str]
    service_type: str
    start_at: str
    end_at: str
    service_location_id: str
    service_date: str
    raw_minutes: int
    rounded_minutes: int
    rate_multiplier: float
    after_hours_factor: float
    billable_amount_cents: int
    status: str
    note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    client_id: str
    period_start: str
    period_end: str
    variant: str
    line_entry_ids: List[str]
    line_subtotal_cents: int
    admin_fee_cents: int
    total_due_cents: int
    retainer_applied_cents: int
    balance_due_cents: int
    amount_paid_cents: int
    status: str
    issued_at: Optional[str]
    voided_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
