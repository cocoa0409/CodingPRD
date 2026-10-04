"""Domain types: entity TypedDicts, status enums, role enum.

All ten resources carry the common system-managed fields of PRD §2.5:
``id``, ``created_at``, ``updated_at``, and ``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    FACILITY_OWNER = "FacilityOwner"
    IMPORTER = "Importer"
    ENTRY_REVIEWER = "EntryReviewer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    FIELD_INSPECTOR = "FieldInspector"
    RECALL_COORDINATOR = "RecallCoordinator"


ALL_ROLES = [r.value for r in UserRole]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class FacilityKind(str, Enum):
    DOMESTIC = "DOMESTIC"
    FOREIGN = "FOREIGN"


class FacilityStatus(str, Enum):
    REGISTERED = "REGISTERED"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"


class ImporterStanding(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    PROBATION = "PROBATION"
    REVOKED = "REVOKED"


class ProductRiskClass(str, Enum):
    LOW = "LOW"
    STANDARD = "STANDARD"
    HIGH = "HIGH"


class TransportMode(str, Enum):
    VESSEL = "VESSEL"
    AIR = "AIR"
    RAIL = "RAIL"
    ROAD = "ROAD"


class PriorNoticeStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    SUPERSEDED = "SUPERSEDED"
    COMPROMISED = "COMPROMISED"
    CONSUMED = "CONSUMED"


class ReviewStatus(str, Enum):
    PENDING_SCREENING = "PENDING_SCREENING"
    SCREENED = "SCREENED"


class DispositionStatus(str, Enum):
    PENDING = "PENDING"
    DETAINED = "DETAINED"
    RELEASED = "RELEASED"
    REFUSED = "REFUSED"
    EXPORTED = "EXPORTED"
    RECONDITIONED = "RECONDITIONED"


TERMINAL_DISPOSITIONS = frozenset(
    {
        DispositionStatus.RELEASED.value,
        DispositionStatus.REFUSED.value,
        DispositionStatus.EXPORTED.value,
        DispositionStatus.RECONDITIONED.value,
    }
)


class ScreeningDecision(str, Enum):
    NONE = "NONE"
    RELEASE = "RELEASE"
    SAMPLE = "SAMPLE"
    DETAIN = "DETAIN"


class ScoringVariant(str, Enum):
    BASE = "BASE"
    HISTORY_WEIGHTED = "HISTORY_WEIGHTED"


class SampleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RESULT_RECORDED = "RESULT_RECORDED"


class SampleResult(str, Enum):
    PENDING = "PENDING"
    COMPLIANT = "COMPLIANT"
    VIOLATIVE = "VIOLATIVE"


class AlertScopeType(str, Enum):
    FIRM = "FIRM"
    COUNTRY_PRODUCT = "COUNTRY_PRODUCT"


class AlertStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class PetitionStatus(str, Enum):
    EVIDENCE_REVIEW = "EVIDENCE_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class AdjudicationDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    REFUSED_BY_FACILITY = "REFUSED_BY_FACILITY"


class RecallStatus(str, Enum):
    INITIATED = "INITIATED"
    CLASSIFIED = "CLASSIFIED"
    TERMINATED = "TERMINATED"


class RecallClassification(str, Enum):
    NONE = "NONE"
    CLASS_I = "CLASS_I"
    CLASS_II = "CLASS_II"
    CLASS_III = "CLASS_III"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.5 common fields on every resource)
# ---------------------------------------------------------------------------


class Facility(TypedDict):
    id: str
    legal_name: str
    facility_kind: str
    country_code: str
    ufi: str
    registration_number: str
    registration_status: str
    registered_at: str
    expires_at: str
    violation_count: int
    open_detention_count: int
    created_at: str
    updated_at: str
    version: int


class ImporterFirm(TypedDict):
    id: str
    firm_name: str
    account_code: str
    standing: str
    refusal_count: int
    terminal_entry_count: int
    created_at: str
    updated_at: str
    version: int


class Laboratory(TypedDict):
    id: str
    lab_code: str
    daily_sample_capacity: int
    created_at: str
    updated_at: str
    version: int


class PriorNotice(TypedDict):
    id: str
    importer_id: str
    facility_id: str
    product_code: str
    product_risk_class: str
    transport_mode: str
    arrival_eta: str
    declared_units: int
    unit_value_cents: int
    port_code: str
    status: str
    is_amendment: bool
    parent_pn_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ImportEntry(TypedDict):
    id: str
    prior_notice_id: str
    importer_id: str
    facility_id: str
    product_code: str
    product_risk_class: str
    declared_units: int
    unit_value_cents: int
    is_amendment_pn: bool
    review_status: str
    disposition_status: str
    screening_decision: str
    screening_score: Optional[int]
    scoring_variant_applied: Optional[str]
    probation_adjustment_applied: int
    detained_at: Optional[str]
    response_deadline_at: Optional[str]
    detained_under_alert_id: Optional[str]
    units_held: int
    units_released: int
    units_refused: int
    units_exported: int
    units_destroyed: int
    bond_amount_cents: Optional[int]
    disposition_completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SampleAnalysis(TypedDict):
    id: str
    entry_id: str
    lab_code: str
    sample_units: int
    analysis_date: str
    status: str
    result: str
    created_at: str
    updated_at: str
    version: int


class ImportAlert(TypedDict):
    id: str
    scope_type: str
    facility_id: Optional[str]
    country_code: Optional[str]
    product_code: Optional[str]
    reason: str
    status: str
    created_by_user_id: str
    lifted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AlertPetition(TypedDict):
    id: str
    alert_id: str
    filed_by_facility_id: str
    evidence_links: List[str]
    status: str
    consecutive_compliant_count: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    facility_id: str
    inspector_user_id: str
    scheduled_start_at: str
    scheduled_end_at: str
    status: str
    findings_violation_count: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Recall(TypedDict):
    id: str
    facility_id: str
    product_code: str
    quantity_distributed: int
    classification: str
    status: str
    quantity_recovered: int
    quantity_corrected: int
    quantity_destroyed: int
    quantity_outstanding: int
    effectiveness_pct: float
    consignees_contacted: int
    consignees_total: int
    consignee_contact_pct: float
    created_at: str
    updated_at: str
    version: int
