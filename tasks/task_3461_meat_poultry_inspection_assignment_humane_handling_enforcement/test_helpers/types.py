"""Domain types for the Meat & Poultry Inspection API.

Entity payloads as declared in the PRD: every primary resource carries the
mutable common fields (``id``, ``created_at``, ``updated_at``, ``version``);
the recall effectiveness check is an append-only event record and carries only
``id`` and ``created_at`` as system fields (PRD: "it carries ``id`` and
``created_at`` only, with no ``updated_at`` and no ``version``").
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ── Role enum ────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    ESTABLISHMENT_MANAGER = "EstablishmentManager"
    INSPECTOR = "Inspector"
    SUPERVISORY_REVIEWER = "SupervisoryReviewer"
    DISTRICT_MANAGER = "DistrictManager"
    LABEL_OFFICER = "LabelOfficer"
    RECALL_COORDINATOR = "RecallCoordinator"
    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"


# ── Shared enums ─────────────────────────────────────────────────────────────

class SpeciesClass(str, Enum):
    CATTLE = "CATTLE"
    SWINE = "SWINE"
    POULTRY = "POULTRY"
    SHEEP = "SHEEP"


class RegulationFamily(str, Enum):
    SANITATION = "SANITATION"
    HACCP = "HACCP"
    HUMANE = "HUMANE"
    LABELING = "LABELING"
    OTHER = "OTHER"


# ── Establishment enums ──────────────────────────────────────────────────────

class GrantStatus(str, Enum):
    UNGRANTED = "UNGRANTED"
    GRANTED = "GRANTED"
    WITHDRAWN = "WITHDRAWN"


class InspectionStatus(str, Enum):
    INACTIVE = "INACTIVE"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PathogenCategory(str, Enum):
    CAT_1 = "CAT_1"
    CAT_2 = "CAT_2"
    CAT_3 = "CAT_3"


# ── Grant application enums ──────────────────────────────────────────────────

class AdequacyDimension(str, Enum):
    FACILITY = "FACILITY"
    SANITATION = "SANITATION"
    HACCP = "HACCP"


class AdequacyFinding(str, Enum):
    PENDING = "PENDING"
    ADEQUATE = "ADEQUATE"
    DEFICIENT = "DEFICIENT"


class GrantDecision(str, Enum):
    GRANT = "GRANT"
    DENY = "DENY"


class GrantApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


# ── Inspector / shift enums ──────────────────────────────────────────────────

class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ShiftType(str, Enum):
    SLAUGHTER = "SLAUGHTER"
    PROCESSING = "PROCESSING"


class ShiftWindowStatus(str, Enum):
    PLANNED = "PLANNED"
    VERIFIED_COVERED = "VERIFIED_COVERED"
    COVERAGE_GAP_FLAGGED = "COVERAGE_GAP_FLAGGED"
    BLOCKED = "BLOCKED"


class ShiftAssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


# ── Noncompliance record enums ───────────────────────────────────────────────

class NoncomplianceRecordStatus(str, Enum):
    OPEN = "OPEN"
    RESPONSE_SUBMITTED = "RESPONSE_SUBMITTED"
    ESCALATED = "ESCALATED"
    APPEALED = "APPEALED"
    VERIFIED = "VERIFIED"
    VACATED = "VACATED"


class VerifyOutcome(str, Enum):
    VERIFY = "VERIFY"
    ESCALATE = "ESCALATE"


# ── Enforcement enums ────────────────────────────────────────────────────────

class EnforcementActionType(str, Enum):
    NOTICE_OF_INTENDED_ENFORCEMENT = "NOTICE_OF_INTENDED_ENFORCEMENT"
    WITHHOLD_MARKS = "WITHHOLD_MARKS"
    SUSPENSION = "SUSPENSION"
    WITHDRAWAL = "WITHDRAWAL"


class EnforcementBasis(str, Enum):
    NR_LINKAGE = "NR_LINKAGE"
    EGREGIOUS_HUMANE = "EGREGIOUS_HUMANE"
    CATEGORY_3_PATHOGEN = "CATEGORY_3_PATHOGEN"
    ADMINISTRATIVE = "ADMINISTRATIVE"


class EnforcementActionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    IN_EFFECT = "IN_EFFECT"
    LIFTED = "LIFTED"


# ── Humane handling enums ────────────────────────────────────────────────────

class HumaneSeverity(str, Enum):
    EGREGIOUS = "EGREGIOUS"
    NON_EGREGIOUS = "NON_EGREGIOUS"


class HumaneEventStatus(str, Enum):
    REPORTED = "REPORTED"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


# ── Pathogen sampling enums ──────────────────────────────────────────────────

class Pathogen(str, Enum):
    SALMONELLA = "SALMONELLA"
    CAMPYLOBACTER = "CAMPYLOBACTER"


class SampleResult(str, Enum):
    PENDING = "PENDING"
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"


# ── Label application enums ──────────────────────────────────────────────────

class LabelClaim(str, Enum):
    GRASS_FED = "GRASS_FED"
    NO_ANTIBIOTICS = "NO_ANTIBIOTICS"
    ORGANIC = "ORGANIC"
    BREED_SPECIFIC = "BREED_SPECIFIC"


class LabelDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    RETURN = "RETURN"


class LabelApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RETURNED = "RETURNED"
    HELD = "HELD"


# ── Recall enums ─────────────────────────────────────────────────────────────

class RecallReasonCode(str, Enum):
    PATHOGEN = "PATHOGEN"
    MISBRANDING = "MISBRANDING"
    FOREIGN_MATTER = "FOREIGN_MATTER"


class RecallClass(str, Enum):
    CLASS_I = "CLASS_I"
    CLASS_II = "CLASS_II"
    CLASS_III = "CLASS_III"


class RecallStatus(str, Enum):
    INITIATED = "INITIATED"
    CLASS_DETERMINED = "CLASS_DETERMINED"
    CLOSED_EFFECTIVE = "CLOSED_EFFECTIVE"
    CLOSED_INEFFECTIVE = "CLOSED_INEFFECTIVE"


class EffectivenessOutcome(str, Enum):
    EFFECTIVE = "EFFECTIVE"
    INEFFECTIVE = "INEFFECTIVE"


# ── Appeal enums ─────────────────────────────────────────────────────────────

class AppealOutcome(str, Enum):
    AFFIRM = "AFFIRM"
    REMAND = "REMAND"
    VACATE = "VACATE"


class AppealStatus(str, Enum):
    FILED = "FILED"
    AFFIRMED = "AFFIRMED"
    REMANDED = "REMANDED"
    VACATED = "VACATED"


# ── Entity payloads ──────────────────────────────────────────────────────────

class Establishment(TypedDict):
    id: str
    name: str
    species_classes: List[str]
    slaughter_capable: bool
    grant_status: str
    inspection_status: str
    pathogen_category: Optional[str]
    open_nr_count: int
    suspension_count: int
    compliance_score: float
    enforcement_priority_score: int
    rolling_risk_score: int
    lifetime_risk_score: int
    created_at: str
    updated_at: str
    version: int


class GrantApplication(TypedDict):
    id: str
    establishment_id: str
    facility_doc_ref: str
    sanitation_plan_ref: str
    haccp_plan_ref: str
    facility_finding: str
    sanitation_finding: str
    haccp_finding: str
    status: str
    revision_count: int
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict):
    id: str
    full_name: str
    badge_number: str
    species_qualifications: List[str]
    employment_status: str
    created_at: str
    updated_at: str
    version: int


class ShiftWindow(TypedDict):
    id: str
    establishment_id: str
    start_utc: str
    end_utc: str
    shift_type: str
    planned_line_count: int
    status: str
    provisional_gap_minutes: Optional[int]
    final_gap_minutes: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ShiftAssignment(TypedDict):
    id: str
    shift_window_id: str
    establishment_id: str
    inspector_id: str
    line_index: int
    start_utc: str
    end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class NoncomplianceRecord(TypedDict):
    id: str
    establishment_id: str
    issued_by_inspector_id: str
    shift_window_id: Optional[str]
    regulation_family: str
    description: str
    observed_at: str
    issued_at: str
    status: str
    status_before_appeal: Optional[str]
    response_text: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EnforcementAction(TypedDict):
    id: str
    establishment_id: str
    action_type: str
    basis: str
    regulation_family: Optional[str]
    status: str
    auto_created: bool
    effective_at: Optional[str]
    abatement_evidence: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HumaneHandlingEvent(TypedDict):
    id: str
    establishment_id: str
    reported_by_inspector_id: str
    species: str
    severity: str
    observed_at: str
    description: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PathogenSample(TypedDict):
    id: str
    establishment_id: str
    collected_by_inspector_id: str
    pathogen: str
    collected_at: str
    result: str
    resulted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LabelApplication(TypedDict):
    id: str
    establishment_id: str
    product_name: str
    label_claim: str
    documentation_refs: List[str]
    status: str
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class Recall(TypedDict):
    id: str
    establishment_id: str
    product_description: str
    quantity_lbs: float
    reason_code: str
    recall_class: Optional[str]
    status: str
    required_min_checks: Optional[int]
    required_effectiveness_ratio: Optional[float]
    checks_performed: int
    checks_effective: int
    effectiveness_ratio: Optional[float]
    created_at: str
    updated_at: str
    version: int


class RecallEffectivenessCheck(TypedDict):
    # Append-only event record: id + created_at are the ONLY system fields.
    id: str
    recall_id: str
    consignee_name: str
    outcome: str
    checked_at: str
    created_at: str


class Appeal(TypedDict):
    id: str
    noncompliance_record_id: str
    grounds: str
    status: str
    decided_by_reviewer_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
