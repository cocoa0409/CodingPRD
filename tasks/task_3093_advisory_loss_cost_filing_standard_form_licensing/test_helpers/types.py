"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    BUREAU_ADMIN = "BureauAdmin"
    BUREAU_ACTUARY = "BureauActuary"
    REGULATOR_ANALYST = "RegulatorAnalyst"
    INSURER_USER = "InsurerUser"


class InsurerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class SubmissionStatus(str, Enum):
    RECEIVED = "RECEIVED"
    EDITING = "EDITING"
    ACCEPTED = "ACCEPTED"
    ACCEPTED_WITH_WARNINGS = "ACCEPTED_WITH_WARNINGS"
    REJECTED = "REJECTED"


class FilingStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_ACTUARIAL_REVIEW = "IN_ACTUARIAL_REVIEW"
    REVIEWED = "REVIEWED"
    FILED = "FILED"
    OBJECTED = "OBJECTED"
    EFFECTIVE = "EFFECTIVE"
    WITHDRAWN = "WITHDRAWN"


class TrendSelection(str, Enum):
    EXPONENTIAL_LEAST_SQUARES = "EXPONENTIAL_LEAST_SQUARES"
    LINEAR_LEAST_SQUARES = "LINEAR_LEAST_SQUARES"


class AdoptionStatus(str, Enum):
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    REJECTED_BAND = "REJECTED_BAND"
    WITHDRAWN = "WITHDRAWN"


class FormStatus(str, Enum):
    DRAFTING = "DRAFTING"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    WITHDRAWN = "WITHDRAWN"


class FormKind(str, Enum):
    POLICY_FORM = "POLICY_FORM"
    ENDORSEMENT = "ENDORSEMENT"


class VariantReviewStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"


class VariantPublicationStatus(str, Enum):
    UNPUBLISHED = "UNPUBLISHED"
    SCHEDULED = "SCHEDULED"
    LIVE = "LIVE"
    RETIRED = "RETIRED"


class CircularStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class AgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    TERMINATED = "TERMINATED"


class ClassPlanStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"


class RevisionStatus(str, Enum):
    STAGED = "STAGED"
    ACTIVATED = "ACTIVATED"
    SUPERSEDED = "SUPERSEDED"


class FindingSeverity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"


# --- Primary resources: id + created_at + updated_at + version (PRD §2.5) ---

class MemberInsurer(TypedDict, total=False):
    id: str
    insurer_code: str
    legal_name: str
    insurer_status: str
    quality_score_bps: int
    created_at: str
    updated_at: str
    version: int


class StatisticalPlan(TypedDict, total=False):
    id: str
    plan_code: str
    line_of_business: str
    min_premium_cents: int
    max_record_age_months: int
    plan_status: str
    created_at: str
    updated_at: str
    version: int


class StatisticalSubmission(TypedDict, total=False):
    id: str
    insurer_id: str
    plan_id: str
    period_start: str
    period_end: str
    record_count: int
    written_premium_cents: int
    submission_status: str
    accepted_record_count: int
    error_finding_count: int
    warning_finding_count: int
    created_at: str
    updated_at: str
    version: int


class LossCostFiling(TypedDict, total=False):
    id: str
    filing_code: str
    state_code: str
    line_of_business: str
    filing_version: int
    supersedes_filing_id: Optional[str]
    trend_selection: str
    review_notes: Optional[str]
    filing_status: str
    last_submitted_by_admin_id: Optional[str]
    filed_at: Optional[str]
    indicated_change_pct: Optional[float]
    effective_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StateDepartment(TypedDict, total=False):
    id: str
    state_code: str
    department_name: str
    objection_window_days: int
    max_lcm_deviation_pct: int
    created_at: str
    updated_at: str
    version: int


class LossCostMultiplierAdoption(TypedDict, total=False):
    id: str
    insurer_id: str
    filing_id: str
    multiplier_pct: int
    adoption_status: str
    authorized_premium_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PolicyForm(TypedDict, total=False):
    id: str
    form_number: str
    form_title: str
    form_kind: str
    form_status: str
    created_at: str
    updated_at: str
    version: int


class FormVariant(TypedDict, total=False):
    id: str
    form_id: str
    state_code: str
    variant_text_ref: str
    review_status: str
    publication_status: str
    effective_from: str
    effective_to: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Circular(TypedDict, total=False):
    id: str
    circular_number: str
    subject: str
    implementation_date: str
    circular_status: str
    supersedes_circular_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LicenseAgreement(TypedDict, total=False):
    id: str
    insurer_id: str
    coverage_start: str
    coverage_end: str
    royalty_rate_bps: int
    agreement_status: str
    created_at: str
    updated_at: str
    version: int


class ClassPlan(TypedDict, total=False):
    id: str
    class_plan_code: str
    line_of_business: str
    current_revision_id: Optional[str]
    plan_status: str
    created_at: str
    updated_at: str
    version: int


class ClassPlanRevision(TypedDict, total=False):
    id: str
    class_plan_id: str
    revision_number: int
    class_count: int
    revision_status: str
    activates_at: str
    created_at: str
    updated_at: str
    version: int


# --- Immutable leaf resources: ONLY id + created_at (PRD §2.5) ---

class SubmissionEditFinding(TypedDict, total=False):
    id: str
    submission_id: str
    edit_code: str
    severity: str
    affected_records: int
    created_at: str


class LossCostCell(TypedDict, total=False):
    id: str
    filing_id: str
    class_code: str
    earned_premium_cents: int
    incurred_loss_cents: int
    weight_pct: int
    current_loss_cost_cents: int
    created_at: str


class RegulatoryObjection(TypedDict, total=False):
    id: str
    filing_id: str
    department_id: str
    objection_code: str
    objection_text: str
    raised_at: str
    created_at: str
