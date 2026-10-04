"""Domain types: entity record shapes, status enums, and the role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class ServiceLevelStatus(str, Enum):
    DRAFT = "DRAFT"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class Metric(str, Enum):
    ASA = "ASA"
    ABANDON = "ABANDON"
    QA_AVG = "QA_AVG"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class QueueStatus(str, Enum):
    OPEN = "OPEN"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"


class QueueType(str, Enum):
    GENERAL = "GENERAL"
    SPECIALTY = "SPECIALTY"


class CallStatus(str, Enum):
    WAITING = "WAITING"
    ASSIGNED = "ASSIGNED"
    ANSWERED = "ANSWERED"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class AssignedVia(str, Enum):
    PRIMARY = "PRIMARY"
    OVERFLOW = "OVERFLOW"


class ReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DISPUTED = "DISPUTED"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class CoachingPlanStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    ESCALATED = "ESCALATED"
    CANCELLED = "CANCELLED"


class CoachingTrigger(str, Enum):
    AUTO_QUALITY = "AUTO_QUALITY"
    MANUAL = "MANUAL"


class ArticleStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class SurgeType(str, Enum):
    ENROLLMENT_PERIOD = "ENROLLMENT_PERIOD"
    POLICY_CHANGE = "POLICY_CHANGE"
    PUBLIC_EVENT = "PUBLIC_EVENT"


class SurgeWindowStatus(str, Enum):
    DECLARED = "DECLARED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentCategory(str, Enum):
    PRIVACY_BREACH = "PRIVACY_BREACH"
    SECURITY = "SECURITY"
    DATA_QUALITY = "DATA_QUALITY"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    CONTAINED = "CONTAINED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    REJECTED = "REJECTED"


class CurePeriodStatus(str, Enum):
    PENDING = "PENDING"
    REMEDIED = "REMEDIED"
    FORFEIT = "FORFEIT"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    OPS_MANAGER = "OpsManager"
    SUPERVISOR = "Supervisor"
    AGENT = "Agent"
    QUALITY_ANALYST = "QualityAnalyst"
    KNOWLEDGE_MANAGER = "KnowledgeManager"
    SECURITY_OFFICER = "SecurityOfficer"
    BILLING_ANALYST = "BillingAnalyst"


class Contract(TypedDict, total=False):
    id: str
    agency_name: str
    measurement_tz: str
    cap_absolutes: bool
    status: str
    withheld_cents_cum: int
    cure_periods_used: int
    created_at: str
    updated_at: str
    version: int


class ServiceLevel(TypedDict, total=False):
    id: str
    contract_id: str
    program_code: str
    metric: str
    target: float
    cap_pct_of_gross: float
    remedy_fee_cents: int
    effective_from: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Agent(TypedDict, total=False):
    id: str
    full_name: str
    languages: List[str]
    employment_status: str
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict, total=False):
    # Append-only style record: no updated_at, no version.
    id: str
    agent_id: str
    program_code: str
    training_course_id: str
    valid_until: str
    invalidated_at: Optional[str]
    invalidated_by_article_id: Optional[str]
    created_at: str


class Queue(TypedDict, total=False):
    id: str
    contract_id: str
    program_code: str
    language_code: str
    overflow_queue_id: Optional[str]
    queue_type: str
    specialty_tag: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Call(TypedDict, total=False):
    id: str
    contract_id: str
    program_code: str
    language_code: str
    required_specialty: Optional[str]
    enqueued_at: str
    status: str
    queue_id: Optional[str]
    agent_id: Optional[str]
    assigned_via: Optional[str]
    route_depth: int
    answered_at: Optional[str]
    ended_at: Optional[str]
    abandoned_at: Optional[str]
    answer_seconds: Optional[int]
    talk_seconds: Optional[int]
    handled_by_agent_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QualityReview(TypedDict, total=False):
    id: str
    call_id: str
    accuracy_score: int
    compliance_score: int
    total_score: int
    accuracy_weight: float
    status: str
    final: bool
    created_at: str
    updated_at: str
    version: int


class CoachingPlan(TypedDict, total=False):
    id: str
    agent_id: str
    trigger: str
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class KnowledgeArticle(TypedDict, total=False):
    id: str
    program_code: str
    title: str
    body: str
    effective_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingCourse(TypedDict, total=False):
    id: str
    program_code: str
    knowledge_article_id: Optional[str]
    required: bool
    created_at: str
    updated_at: str
    version: int


class CourseCompletion(TypedDict, total=False):
    # Append-only style record: no updated_at, no version.
    id: str
    training_course_id: str
    agent_id: str
    completed_at: str
    created_at: str


class SurgeWindow(TypedDict, total=False):
    id: str
    contract_id: str
    program_code: str
    surge_type: str
    starts_on: str
    ends_on: str
    expected_volume_factor: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict, total=False):
    id: str
    contract_id: str
    severity: str
    category: str
    occurred_at: str
    reported_at: str
    description: str
    status: str
    sla_breached: bool
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    contract_id: str
    period: str
    status: str
    gross_cents: Optional[int]
    withheld_cents: int
    net_cents: Optional[int]
    auto_review: bool
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict, total=False):
    id: str
    invoice_id: str
    service_level_id: str
    metric: str
    measured_value: Optional[float]
    staffing_actual: int
    staffing_target: int
    compliant: bool
    withheld_cents: int
    created_at: str
    updated_at: str
    version: int


class CurePeriod(TypedDict, total=False):
    id: str
    invoice_line_id: str
    status: str
    opened_at: str
    deadline: str
    remedy_fee_cents: int
    created_at: str
    updated_at: str
    version: int
