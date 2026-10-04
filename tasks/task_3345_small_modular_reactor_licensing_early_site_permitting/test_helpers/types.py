"""Typed shapes and status vocabularies for the SMR Licensing & Early Site Permitting API.

Each TypedDict mirrors the field list the PRD declares for that resource.
Every primary resource carries ``id``, ``created_at``, ``updated_at`` and
``version``. The single deliberate exception is ``TestResult``, an append-only
evidentiary record carrying only ``id`` and ``created_at`` alongside its own
fields; its shape therefore omits ``updated_at`` and ``version``.
"""

from enum import Enum
from typing import Optional, TypedDict


# ── Status vocabularies ────────────────────────────────────────────────────


class DcaStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SAFETY_REVIEW = "SAFETY_REVIEW"
    ADVANCED_REVIEW = "ADVANCED_REVIEW"
    CERTIFIED = "CERTIFIED"
    WITHDRAWN = "WITHDRAWN"


class SarStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    READY_FOR_PHASE_ADVANCE = "READY_FOR_PHASE_ADVANCE"


class RaiStatus(str, Enum):
    OPEN = "OPEN"
    RESPONSE_SUBMITTED = "RESPONSE_SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REOPENED = "REOPENED"
    SUPERSEDED = "SUPERSEDED"


class TestProgramStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    ADEQUATE = "ADEQUATE"
    INSUFFICIENT = "INSUFFICIENT"


class TestOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class QualificationStatus(str, Enum):
    AUDIT_SCHEDULED = "AUDIT_SCHEDULED"
    CONDITIONALLY_QUALIFIED = "CONDITIONALLY_QUALIFIED"
    FULLY_QUALIFIED = "FULLY_QUALIFIED"
    DISQUALIFIED = "DISQUALIFIED"
    SUPERSEDED = "SUPERSEDED"


class QualifiedVariant(str, Enum):
    FULLY_QUALIFIED = "FULLY_QUALIFIED"
    CONDITIONALLY_QUALIFIED = "CONDITIONALLY_QUALIFIED"
    UNQUALIFIED = "UNQUALIFIED"


class ComponentLotStatus(str, Enum):
    PROCURED = "PROCURED"
    DELIVERED = "DELIVERED"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"


class PermitType(str, Enum):
    ESP = "ESP"
    COL = "COL"


class SitePermitStatus(str, Enum):
    DRAFT = "DRAFT"
    ENVIRONMENTAL_REVIEW = "ENVIRONMENTAL_REVIEW"
    HEARINGS = "HEARINGS"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"
    CONTENDED = "CONTENDED"


class SubscriptionStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    LOCKED = "LOCKED"
    WITHDRAWN = "WITHDRAWN"


class PipelineStatus(str, Enum):
    ENROLLING = "ENROLLING"
    TRAINING = "TRAINING"
    GRADUATING = "GRADUATING"
    STAFFED = "STAFFED"


class LicenseStatus(str, Enum):
    ENROLLED = "ENROLLED"
    LICENSED = "LICENSED"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class UserRole(str, Enum):
    DCA_APPLICANT = "DcaApplicant"
    NRC_REVIEWER = "NrcReviewer"
    DOE_PROGRAM = "DoeProgram"
    UTILITY_PARTICIPANT = "UtilityParticipant"
    SUPPLY_CHAIN_MANAGER = "SupplyChainManager"
    VENDOR_AUDITOR = "VendorAuditor"
    SITE_PERMIT_APPLICANT = "SitePermitApplicant"
    PUBLIC_INTERVENOR = "PublicIntervenor"
    WORKFORCE_COORDINATOR = "WorkforceCoordinator"


# ── Entity shapes ──────────────────────────────────────────────────────────


class DesignCertification(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    docket_number: str
    reactor_model: str
    target_power_mwt: int
    plant_net_capacity_mw: int
    source_term_fraction: float
    site_boundary_miles: float
    status: str
    review_phase: int
    epz_radius_deterministic_miles: float
    epz_radius_dose_based_miles: float
    epz_radius_selected_miles: float
    subscribed_mw: int
    available_mw: int
    funding_gap_usd: int


class SafetyAnalysisReport(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    dca_id: str
    section_code: str
    revision_number: int
    status: str
    open_rais: int


class RAI(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    dca_id: str
    sar_section_code: str
    question_text: str
    due_date: str
    status: str
    response_text: Optional[str]
    responded_at: Optional[str]
    late_response: bool
    authored_by_user_id: str


class TestProgram(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    dca_id: str
    program_code: str
    required_tests: int
    completed_tests: int
    status: str


class TestResult(TypedDict):
    # Append-only evidentiary record: id and created_at only, no updated_at,
    # no version.
    id: str
    created_at: str
    program_id: str
    outcome: str
    run_at: str
    notes: Optional[str]


class Vendor(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    capability_scope: str
    qualified: bool
    has_active_qualification: bool


class VendorQualification(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    vendor_id: str
    cycle_number: int
    audit_date: str
    defects_found: int
    qualified_variant: str
    status: str


class ComponentLot(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    vendor_id: str
    program_id: str
    component_type: str
    nuclear_grade: bool
    quantity: int
    status: str


class SitePermit(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    permit_type: str
    dca_id: str
    site_name: str
    epz_radius_miles: float
    status: str


class PublicHearing(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    permit_id: str
    scheduled_at: str
    location: str
    status: str


class SubscriptionCommitment(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    dca_id: str
    utility_id: str
    committed_mw: int
    price_per_mwh_usd: float
    status: str
    cost_share_total_usd: int
    allocated_overrun_usd: int
    withdrawal_reserve_usd: int
    offload_penalty_usd: int


class CostShareAgreement(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    dca_id: str
    total_cost_usd: int
    gov_contribution_usd: int
    participant_share_usd: int
    allocated_to_participants_usd: int


class WorkforcePipeline(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    dca_id: str
    cohort_code: str
    required_operators: int
    graduates: int
    status: str


class OperatorLicense(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    pipeline_id: str
    candidate_name: str
    license_status: str
