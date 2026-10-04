"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    REGISTRATION_COORDINATOR = "RegistrationCoordinator"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"
    ENTITY_COMPLIANCE_OFFICER = "EntityComplianceOfficer"
    CIP_ASSET_MANAGER = "CIPAssetManager"
    REGIONAL_ENTITY_REVIEWER = "RegionalEntityReviewer"
    FEDERAL_REVIEWER = "FederalReviewer"


class ComplianceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"


class EngagementType(str, Enum):
    AUDIT = "AUDIT"
    SPOT_CHECK = "SPOT_CHECK"
    SELF_CERTIFICATION = "SELF_CERTIFICATION"


class EngagementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ArtifactKind(str, Enum):
    OPERATING_RECORD = "OPERATING_RECORD"
    ACCESS_LOG = "ACCESS_LOG"
    MAINTENANCE_RECORD = "MAINTENANCE_RECORD"


class EvidenceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class SelfReportStatus(str, Enum):
    RECEIVED = "RECEIVED"
    TRIAGED = "TRIAGED"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class ViolationSourceType(str, Enum):
    AUDIT = "AUDIT"
    SPOT_CHECK = "SPOT_CHECK"
    SELF_REPORT = "SELF_REPORT"
    SELF_LOG = "SELF_LOG"


class ViolationRiskFactor(str, Enum):
    MINIMAL = "MINIMAL"
    MODERATE = "MODERATE"
    SERIOUS = "SERIOUS"


class SeverityLevel(str, Enum):
    LOWER = "LOWER"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    SEVERE = "SEVERE"


class ViolationStatus(str, Enum):
    OPEN = "OPEN"
    MITIGATION_SUBMITTED = "MITIGATION_SUBMITTED"
    MITIGATION_IN_PROGRESS = "MITIGATION_IN_PROGRESS"
    MITIGATION_COMPLETE = "MITIGATION_COMPLETE"
    APPEALED = "APPEALED"
    CLOSED = "CLOSED"
    DISMISSED = "DISMISSED"


class MitigationPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VERIFIED = "VERIFIED"


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"


class SelfLogEntryStatus(str, Enum):
    LOGGED = "LOGGED"
    REVIEWED_OK = "REVIEWED_OK"
    ESCALATED = "ESCALATED"


class ReviewPeriodStatus(str, Enum):
    OPEN = "OPEN"
    REVIEWING = "REVIEWING"
    CLOSED = "CLOSED"


class ImpactRating(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class AssetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECOMMISSIONED = "DECOMMISSIONED"


class GrantScope(str, Enum):
    PHYSICAL = "PHYSICAL"
    ELECTRONIC = "ELECTRONIC"


class GrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class PenaltyStatus(str, Enum):
    ASSESSED = "ASSESSED"
    CONFIRMED = "CONFIRMED"
    SETTLED = "SETTLED"
    WAIVED = "WAIVED"


class AppealStatus(str, Enum):
    APPEAL_PENDING_REVIEW = "APPEAL_PENDING_REVIEW"
    APPEAL_GRANTED = "APPEAL_GRANTED"
    APPEAL_DENIED = "APPEAL_DENIED"
    FEDERAL_REVIEW_REQUESTED = "FEDERAL_REVIEW_REQUESTED"


class RegisteredEntity(TypedDict, total=False):
    id: str
    legal_name: str
    registration_functions: List[str]
    applicable_standards: List[Dict[str, str]]
    applicable_standard_count: int
    compliance_status: str
    enrollment_self_logging: bool
    open_violation_count: int
    unresolved_appeal_count: int
    created_at: str
    updated_at: str
    version: int


class Engagement(TypedDict, total=False):
    id: str
    entity_id: str
    engagement_type: str
    standard_ids: List[str]
    period_start: str
    period_end: str
    status: str
    coverage_fraction: float
    created_at: str
    updated_at: str
    version: int


class EvidenceArtifact(TypedDict, total=False):
    id: str
    engagement_id: str
    standard_id: str
    artifact_kind: str
    coverage_start: str
    coverage_end: str
    submitted_at: str
    status: str
    review_note: str
    cip_asset_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SelfReport(TypedDict, total=False):
    id: str
    entity_id: str
    standard_id: str
    description: str
    occurred_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict, total=False):
    id: str
    entity_id: str
    standard_id: str
    source_type: str
    source_engagement_id: Optional[str]
    source_self_report_id: Optional[str]
    violation_start: str
    violation_end: str
    violation_risk_factor: str
    severity_level: str
    status: str
    proposed_penalty: float
    final_penalty: Optional[float]
    is_self_logging_qualified: bool
    created_at: str
    updated_at: str
    version: int


class MitigationPlan(TypedDict, total=False):
    id: str
    violation_id: str
    description: str
    submitted_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Milestone(TypedDict, total=False):
    id: str
    plan_id: str
    title: str
    due_date: str
    completed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SelfLogEntry(TypedDict, total=False):
    id: str
    entity_id: str
    standard_id: str
    exception_note: str
    logged_at: str
    period_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReviewPeriod(TypedDict, total=False):
    id: str
    open_at: str
    closed_at: Optional[str]
    status: str
    entry_count: int
    reviewed_ok_count: int
    escalated_count: int
    created_at: str
    updated_at: str
    version: int


class CIPAsset(TypedDict, total=False):
    id: str
    entity_id: str
    asset_name: str
    impact_rating: str
    is_bes_cyber_asset: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class AccessGrant(TypedDict, total=False):
    id: str
    asset_id: str
    grantee_badge: str
    scope: str
    granted_at: str
    revoked_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Penalty(TypedDict, total=False):
    id: str
    violation_id: str
    base_amount: float
    adjustment_factor: float
    amount: float
    issued_at: str
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    violation_id: str
    grounds: str
    submitted_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
