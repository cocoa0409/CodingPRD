"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    LAB_MANAGER = "LabManager"
    EDITORIAL_DIRECTOR = "EditorialDirector"
    METHODOLOGY_OFFICER = "MethodologyOfficer"
    PURCHASING_AGENT = "PurchasingAgent"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    LAB_TECHNICIAN = "LabTechnician"
    SURVEY_DIRECTOR = "SurveyDirector"
    CONTENT_EDITOR = "ContentEditor"
    SAFETY_OFFICER = "SafetyOfficer"
    MEMBER = "Member"


class ProductCategoryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class TestProgramStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    SAMPLE_SOURCING = "SAMPLE_SOURCING"
    TESTING = "TESTING"
    SCORING = "SCORING"
    READY_FOR_PUBLICATION = "READY_FOR_PUBLICATION"
    PUBLISHED = "PUBLISHED"
    CANCELLED = "CANCELLED"


class LabProtocolStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class TestSampleStatus(str, Enum):
    PLANNED = "PLANNED"
    SOURCING = "SOURCING"
    IN_LAB = "IN_LAB"
    SCORED = "SCORED"


class PurchaseOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"
    RECEIVED = "RECEIVED"
    VERIFIED = "VERIFIED"
    CANCELLED = "CANCELLED"


class SurveyWaveStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    QUALIFIED = "QUALIFIED"
    DISQUALIFIED = "DISQUALIFIED"


class RatingPublicationStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    WITHDRAWN = "WITHDRAWN"


class SafetyFindingStatus(str, Enum):
    OPEN = "OPEN"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"


class Designation(str, Enum):
    BEST_BUY = "BEST_BUY"
    RECOMMENDED = "RECOMMENDED"
    STANDARD = "STANDARD"
    NOT_RECOMMENDED = "NOT_RECOMMENDED"


class ProductCategory(TypedDict, total=False):
    id: str
    name: str
    refresh_cycle_months: int
    market_share_pct: float
    member_interest_pct: float
    last_published_at: Optional[str]
    selection_score: float
    status: str
    created_at: str
    updated_at: str
    version: int


class TestProgram(TypedDict, total=False):
    id: str
    category_id: str
    fiscal_year: int
    budget_cents: int
    committed_cents: int
    proposed_by_user_id: str
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LabProtocol(TypedDict, total=False):
    id: str
    category_id: str
    protocol_code: str
    measurement_repeat_min: int
    perf_weight_pct: int
    reliability_weight_pct: int
    convenience_weight_pct: int
    activated_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TestSample(TypedDict, total=False):
    id: str
    program_id: str
    model_label: str
    required_units: int
    sourcing_mode: str
    sourced_units: int
    sourcing_complete: bool
    tested_units: int
    testing_complete: bool
    lab_score: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class PurchaseOrderLine(TypedDict, total=False):
    sample_id: str
    unit_price_cents: int
    qty: int
    tax_rate_bp: int
    line_tax_cents: int


class PurchaseOrder(TypedDict, total=False):
    id: str
    program_id: str
    buyer_alias: str
    retailer_name: str
    receipt_doc_ref: str
    lines: List[PurchaseOrderLine]
    subtotal_cents: int
    shipping_cents: int
    tax_cents: int
    total_cents: int
    placed_by_user_id: Optional[str]
    verified_by_user_id: Optional[str]
    placed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Measurement(TypedDict, total=False):
    # append-only record: id + created_at only, NO updated_at, NO version
    id: str
    sample_id: str
    unit_index: int
    metric_code: str
    value_num: float
    recorded_at: str
    recorded_by_user_id: str
    created_at: str


class SurveyResponse(TypedDict, total=False):
    response_index: int
    member_id: str
    model_label: str
    reliability_score: float
    satisfaction_score: float
    submitted_at: str
    submitted_by_user_id: str
    status: str


class SurveyWave(TypedDict, total=False):
    id: str
    category_id: str
    field_start: str
    field_end: str
    min_responses: int
    responses: List[SurveyResponse]
    response_count: int
    threshold_met: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RatedModel(TypedDict, total=False):
    sample_id: str
    lab_score: Optional[float]
    survey_score: Optional[float]
    overall_score: float
    designation: str
    price_cents: Optional[int]


class ManufacturerResponse(TypedDict, total=False):
    response_index: int
    manufacturer_name: str
    body_text: str
    received_at: str
    status: str


class RatingPublication(TypedDict, total=False):
    id: str
    program_id: str
    embargo_until: str
    version_note: str
    rated_models: List[RatedModel]
    model_count: int
    protocol_id_snapshot: Optional[str]
    survey_wave_id_snapshot: Optional[str]
    manufacturer_responses: List[ManufacturerResponse]
    manufacturer_response_text: Optional[str]
    published_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SafetyFinding(TypedDict, total=False):
    id: str
    program_id: str
    sample_id: str
    severity: str
    description_text: str
    hazard_flag: bool
    recalled_model_count: int
    escalation_tier: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    subscription_id: str
    plan_tier: str
    term_start: str
    term_end: str
    grace_until: str
    status: str
    renewal_count: int


class Member(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    subscriptions: List[Subscription]
    status: str
    created_at: str
    updated_at: str
    version: int
