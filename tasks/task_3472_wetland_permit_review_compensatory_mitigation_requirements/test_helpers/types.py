"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1 — six roles, spelled exactly as the API expects them)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    APPLICANT = "Applicant"
    REVIEWER = "Reviewer"
    DISTRICT_ENGINEER = "DistrictEngineer"
    AGENCY_REVIEWER = "AgencyReviewer"
    ENFORCEMENT_OFFICER = "EnforcementOfficer"


ALL_ROLES = [r.value for r in UserRole]

# ---------------------------------------------------------------------------
# Vocabulary enums
# ---------------------------------------------------------------------------
class OrganizationType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    CORPORATION = "CORPORATION"
    GOVERNMENT = "GOVERNMENT"
    NONPROFIT = "NONPROFIT"


class ResourceType(str, Enum):
    EMERGENT_MARSH = "EMERGENT_MARSH"
    FORESTED_WETLAND = "FORESTED_WETLAND"
    OPEN_WATER = "OPEN_WATER"
    STREAM = "STREAM"


ALL_RESOURCE_TYPES = [r.value for r in ResourceType]


class JdType(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    APPROVED = "APPROVED"


class Determination(str, Enum):
    JURISDICTIONAL = "JURISDICTIONAL"
    NON_JURISDICTIONAL = "NON_JURISDICTIONAL"


class JdStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    REVERSED = "REVERSED"


class AppealStatus(str, Enum):
    FILED = "FILED"
    SUSTAINED = "SUSTAINED"
    DENIED = "DENIED"


class AppealOutcome(str, Enum):
    SUSTAINED = "SUSTAINED"
    DENIED = "DENIED"


class Pathway(str, Enum):
    GENERAL = "GENERAL"
    INDIVIDUAL = "INDIVIDUAL"
    ATF_GENERAL = "ATF_GENERAL"
    ATF_INDIVIDUAL = "ATF_INDIVIDUAL"


ATF_PATHWAYS = [Pathway.ATF_GENERAL.value, Pathway.ATF_INDIVIDUAL.value]
GENERAL_PATHWAYS = [Pathway.GENERAL.value, Pathway.ATF_GENERAL.value]
INDIVIDUAL_PATHWAYS = [Pathway.INDIVIDUAL.value, Pathway.ATF_INDIVIDUAL.value]
GENERAL_PERMIT_CODES = ["NWP-29", "NWP-39"]
GP_ALLOWED_RESOURCE_TYPES = [ResourceType.EMERGENT_MARSH.value, ResourceType.STREAM.value]


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SCREENING = "SCREENING"
    RETURNED_TO_APPLICANT = "RETURNED_TO_APPLICANT"
    ALTERNATIVES_REVIEW = "ALTERNATIVES_REVIEW"
    PUBLIC_NOTICE_OPEN = "PUBLIC_NOTICE_OPEN"
    DECISION_PENDING = "DECISION_PENDING"
    ISSUED = "ISSUED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    SUSPENDED_PENDING_JD = "SUSPENDED_PENDING_JD"


APPLICATION_TERMINAL_STATES = [
    ApplicationStatus.ISSUED.value,
    ApplicationStatus.DENIED.value,
    ApplicationStatus.WITHDRAWN.value,
]

# States from which withdraw is defined (any non-terminal pre-decision state).
APPLICATION_WITHDRAWABLE_STATES = [
    ApplicationStatus.DRAFT.value,
    ApplicationStatus.SUBMITTED.value,
    ApplicationStatus.SCREENING.value,
    ApplicationStatus.RETURNED_TO_APPLICANT.value,
    ApplicationStatus.ALTERNATIVES_REVIEW.value,
    ApplicationStatus.PUBLIC_NOTICE_OPEN.value,
    ApplicationStatus.DECISION_PENDING.value,
    ApplicationStatus.SUSPENDED_PENDING_JD.value,
]

# States the JD-reversal suspension cascade moves to SUSPENDED_PENDING_JD.
APPLICATION_SUSPENDABLE_STATES = [
    ApplicationStatus.SUBMITTED.value,
    ApplicationStatus.SCREENING.value,
    ApplicationStatus.RETURNED_TO_APPLICANT.value,
    ApplicationStatus.ALTERNATIVES_REVIEW.value,
    ApplicationStatus.PUBLIC_NOTICE_OPEN.value,
    ApplicationStatus.DECISION_PENDING.value,
]


class NoticeStatus(str, Enum):
    NONE = "NONE"
    PUBLISHED = "PUBLISHED"
    COMMENT_PERIOD_CLOSED = "COMMENT_PERIOD_CLOSED"


class PirOutcome(str, Enum):
    FAVORABLE = "FAVORABLE"
    UNFAVORABLE = "UNFAVORABLE"


class ScreeningAction(str, Enum):
    BEGIN = "BEGIN"
    RETURN = "RETURN"
    APPROVE = "APPROVE"


class DecisionOutcome(str, Enum):
    ISSUE = "ISSUE"
    DENY = "DENY"


class LedpaConclusion(str, Enum):
    PROPOSED_IS_LEDPA = "PROPOSED_IS_LEDPA"
    ALTERNATIVE_IS_LEDPA = "ALTERNATIVE_IS_LEDPA"
    UNDETERMINED = "UNDETERMINED"


class AaStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class AaVerdict(str, Enum):
    ACCEPT = "ACCEPT"
    REQUEST_REVISION = "REQUEST_REVISION"
    REJECT = "REJECT"


class Agency(str, Enum):
    EPA = "EPA"
    FWS = "FWS"
    NMFS = "NMFS"
    STATE_WATER_QUALITY = "STATE_WATER_QUALITY"
    TRIBAL_AUTHORITY = "TRIBAL_AUTHORITY"


class CommentType(str, Enum):
    ADVISORY = "ADVISORY"
    SUBSTANTIVE_OBJECTION = "SUBSTANTIVE_OBJECTION"
    CONCURRENCE = "CONCURRENCE"


class CommentStatus(str, Enum):
    FILED = "FILED"
    RESOLVED = "RESOLVED"


class Mechanism(str, Enum):
    BANK_CREDITS = "BANK_CREDITS"
    IN_LIEU_FEE = "IN_LIEU_FEE"
    PERMITTEE_RESPONSIBLE = "PERMITTEE_RESPONSIBLE"
    COMBINATION = "COMBINATION"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    CREDITS_SECURED = "CREDITS_SECURED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    DEFAULTED = "DEFAULTED"
    CANCELLED = "CANCELLED"


PLAN_TERMINAL_STATES = [
    PlanStatus.COMPLETED.value,
    PlanStatus.DEFAULTED.value,
    PlanStatus.CANCELLED.value,
]

PLAN_LIVE_STATES = [
    PlanStatus.DRAFT.value,
    PlanStatus.SUBMITTED.value,
    PlanStatus.REVISION_REQUESTED.value,
    PlanStatus.APPROVED.value,
    PlanStatus.CREDITS_SECURED.value,
    PlanStatus.ACTIVE.value,
]

# Plan statuses whose presence earns the PIR secured bonus (PRD §3.5).
PLAN_SECURED_BONUS_STATES = [
    PlanStatus.CREDITS_SECURED.value,
    PlanStatus.ACTIVE.value,
    PlanStatus.COMPLETED.value,
]


class PlanVerdict(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_REVISION = "REQUEST_REVISION"


class BankStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    OPERATIONAL = "OPERATIONAL"
    SUSPENDED = "SUSPENDED"


class CreditTxnStatus(str, Enum):
    RESERVED = "RESERVED"
    PURCHASED = "PURCHASED"
    RELEASED = "RELEASED"
    REFUNDED = "REFUNDED"


class PermitStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"


PERMIT_TERMINAL_STATES = [PermitStatus.CLOSED.value, PermitStatus.EXPIRED.value]


class ReportStatus(str, Enum):
    DUE = "DUE"
    OVERDUE = "OVERDUE"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DEFICIENT = "DEFICIENT"


class ReportOutcome(str, Enum):
    ACCEPTED = "ACCEPTED"
    DEFICIENT = "DEFICIENT"


class CaseSource(str, Enum):
    MANUAL = "MANUAL"
    MONITORING_BREACH = "MONITORING_BREACH"


class ResolutionTrack(str, Enum):
    NONE = "NONE"
    RESTORATION = "RESTORATION"
    AFTER_THE_FACT_PERMIT = "AFTER_THE_FACT_PERMIT"


class CaseStatus(str, Enum):
    OPENED = "OPENED"
    VIOLATION_CONFIRMED = "VIOLATION_CONFIRMED"
    RESOLUTION_PENDING = "RESOLUTION_PENDING"
    DEFAULTED = "DEFAULTED"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.4: every resource carries id, created_at,
# updated_at, version)
# ---------------------------------------------------------------------------
class Applicant(TypedDict, total=False):
    id: str
    legal_name: str
    organization_type: str
    contact_email: str
    prior_violation_count: int
    created_at: str
    updated_at: str
    version: int


class WatersSite(TypedDict, total=False):
    id: str
    applicant_id: str
    site_name: str
    state_code: str
    watershed_code: str
    total_acres: float
    resource_types_present: List[str]
    created_at: str
    updated_at: str
    version: int


class JurisdictionalDetermination(TypedDict, total=False):
    id: str
    site_id: str
    jd_type: str
    determination: str
    rationale: str
    issued_date: Optional[str]
    expiration_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    jd_id: str
    appellant_applicant_id: str
    grounds_text: str
    filed_date: str
    decided_date: Optional[str]
    decision_rationale: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ImpactLine(TypedDict):
    resource_type: str
    impact_acres: float


class PermitApplication(TypedDict, total=False):
    id: str
    applicant_id: str
    site_id: str
    jd_id: str
    pathway: str
    general_permit_code: Optional[str]
    impacts: List[ImpactLine]
    total_impact_acres: float
    is_after_the_fact: bool
    enforcement_case_id: Optional[str]
    project_purpose: str
    estimated_cost_dollars: float
    submitted_date: Optional[str]
    screening_reviewer_id: Optional[str]
    pir_score: Optional[float]
    pir_outcome: Optional[str]
    compensatory_mitigation_required: bool
    notice_status: str
    notice_published_date: Optional[str]
    comment_period_days: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class AlternativesAnalysis(TypedDict, total=False):
    id: str
    application_id: str
    avoidance_demonstrated: bool
    avoidance_narrative: str
    minimization_steps: List[str]
    ledpa_conclusion: str
    offsite_alternatives_considered: int
    revision_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AgencyComment(TypedDict, total=False):
    id: str
    application_id: str
    agency: str
    comment_type: str
    comment_text: str
    filed_date: str
    resolution_text: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MitigationPlan(TypedDict, total=False):
    id: str
    application_id: str
    mechanism: str
    financial_assurance_dollars: float
    stewardship_entity_name: Optional[str]
    long_term_stewardship_secured: bool
    required_credits_by_type: Dict[str, float]
    final_credits_required_by_type: Optional[Dict[str, float]]
    ilf_fee_due_dollars: Optional[float]
    ilf_fee_paid_dollars: float
    assurance_required_dollars: Optional[float]
    secured_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MitigationBank(TypedDict, total=False):
    id: str
    bank_name: str
    sponsor_name: str
    state_code: str
    service_area_watersheds: List[str]
    credit_capacity: Dict[str, float]
    base_price_per_credit: Dict[str, float]
    credits_reserved_by_type: Dict[str, float]
    credits_purchased_by_type: Dict[str, float]
    available_credits_by_type: Dict[str, float]
    revenue_dollars: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CreditTransaction(TypedDict, total=False):
    id: str
    bank_id: str
    plan_id: str
    resource_type: str
    credits: float
    price_per_credit_dollars: Optional[float]
    total_price_dollars: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict, total=False):
    id: str
    application_id: str
    permit_number: str
    issue_date: str
    expiration_date: str
    special_conditions: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MonitoringReport(TypedDict, total=False):
    id: str
    permit_id: str
    plan_id: str
    period_index: int
    due_date: str
    coverage_start: Optional[str]
    coverage_end: Optional[str]
    findings_text: Optional[str]
    submitted_date: Optional[str]
    outcome: Optional[str]
    deficiency_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EnforcementCase(TypedDict, total=False):
    id: str
    site_id: str
    responsible_applicant_id: str
    unauthorized_fill_acres: float
    description: str
    case_source: str
    opened_by_officer_id: str
    opened_date: str
    confirmed_date: Optional[str]
    penalty_accrued_dollars: float
    penalty_final_dollars: Optional[float]
    resolution_track: str
    atf_application_id: Optional[str]
    restoration_deadline: Optional[str]
    extension_used: bool
    case_status: str
    created_at: str
    updated_at: str
    version: int
