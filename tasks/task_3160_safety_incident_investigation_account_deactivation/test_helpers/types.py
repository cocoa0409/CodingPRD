"""Domain types: entity TypedDicts, status enums, role enum.

Every top-level resource in this domain carries the common skeleton
(id + created_at + updated_at + version); no entity trims the skeleton.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class AccountType(str, Enum):
    RIDER = "RIDER"
    DRIVER = "DRIVER"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNDER_HOLD = "UNDER_HOLD"
    PENDING_DECISION = "PENDING_DECISION"
    RESTRICTED = "RESTRICTED"
    DEACTIVATED = "DEACTIVATED"
    APPEAL_PENDING = "APPEAL_PENDING"
    REINSTATED = "REINSTATED"


class SafetyPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class RiskTier(str, Enum):
    TIER_LOW = "TIER_LOW"
    TIER_ELEVATED = "TIER_ELEVATED"
    TIER_HIGH = "TIER_HIGH"
    TIER_SEVERE = "TIER_SEVERE"


class ClusterStatus(str, Enum):
    OPEN = "OPEN"
    WATCHLIST = "WATCHLIST"
    BANNED = "BANNED"


class LinkStatus(str, Enum):
    LINKED = "LINKED"
    DORMANT = "DORMANT"
    SEVERED = "SEVERED"


class TripStatus(str, Enum):
    REQUESTED = "REQUESTED"
    COMPLETED_PENDING = "COMPLETED_PENDING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    PENDING_DECISION = "PENDING_DECISION"
    MANDATORY_REPORTED_BLOCKED = "MANDATORY_REPORTED_BLOCKED"
    DECIDED = "DECIDED"
    APPEAL_PENDING = "APPEAL_PENDING"
    APPEAL_UPHELD = "APPEAL_UPHELD"
    APPEAL_OVERTURNED = "APPEAL_OVERTURNED"
    WITHDRAWN = "WITHDRAWN"


class IncidentCategory(str, Enum):
    PHYSICAL_ASSAULT = "PHYSICAL_ASSAULT"
    SEXUAL_MISCONDUCT = "SEXUAL_MISCONDUCT"
    HARASSMENT = "HARASSMENT"
    SAFETY_VIOLATION = "SAFETY_VIOLATION"
    FRAUD_IDENTITY = "FRAUD_IDENTITY"
    DISCRIMINATION = "DISCRIMINATION"
    PROPERTY_DAMAGE = "PROPERTY_DAMAGE"


class Severity(str, Enum):
    S1 = "S1"
    S2 = "S2"
    S3 = "S3"
    S4 = "S4"


class DecisionCategory(str, Enum):
    PENDING = "PENDING"
    NO_ACTION = "NO_ACTION"
    WARNING = "WARNING"
    RESTRICTED = "RESTRICTED"
    DEACTIVATED = "DEACTIVATED"


class ReporterType(str, Enum):
    RIDER = "RIDER"
    DRIVER = "DRIVER"
    THIRD_PARTY = "THIRD_PARTY"


class EvidenceType(str, Enum):
    TRIP_DATA = "TRIP_DATA"
    IN_APP_MESSAGE = "IN_APP_MESSAGE"
    RATINGS_HISTORY = "RATINGS_HISTORY"
    LAW_ENFORCEMENT_CONTACT = "LAW_ENFORCEMENT_CONTACT"
    DEVICE_LINK = "DEVICE_LINK"
    EXTERNAL_RECORD = "EXTERNAL_RECORD"


class EvidenceWeight(str, Enum):
    WEAK = "WEAK"
    STANDARD = "STANDARD"
    STRONG = "STRONG"
    DISPOSITIVE = "DISPOSITIVE"


class EvidenceStatus(str, Enum):
    PENDING = "PENDING"
    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"


class EnforcementOutcome(str, Enum):
    WARNING = "WARNING"
    RESTRICTED = "RESTRICTED"
    DEACTIVATED = "DEACTIVATED"


class EnforcementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    MANDATORY_REPORTED = "MANDATORY_REPORTED"
    APPEAL_PENDING = "APPEAL_PENDING"
    REVERTED = "REVERTED"
    EXPIRED = "EXPIRED"


class ReportChannel(str, Enum):
    REGULATOR_PORTAL = "REGULATOR_PORTAL"
    LAW_ENFORCEMENT = "LAW_ENFORCEMENT"


class FilingBasis(str, Enum):
    PENDING = "PENDING"
    ROLLUP_THRESHOLD = "ROLLUP_THRESHOLD"
    ALWAYS_LAW_ENFORCEMENT = "ALWAYS_LAW_ENFORCEMENT"
    BLOCKED_WINDOW_TRIGGER = "BLOCKED_WINDOW_TRIGGER"


class ReportStatus(str, Enum):
    BACKLOG = "BACKLOG"
    BLOCKED = "BLOCKED"
    FILED = "FILED"


class CheckKind(str, Enum):
    CONTINUOUS_MONITOR = "CONTINUOUS_MONITOR"
    RESCREEN = "RESCREEN"


class CheckStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_REVIEW = "IN_REVIEW"
    COMPLETED = "COMPLETED"


class Adjudication(str, Enum):
    PENDING = "PENDING"
    CLEAR = "CLEAR"
    ADVERSE = "ADVERSE"
    INCONCLUSIVE = "INCONCLUSIVE"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SAFETY_INVESTIGATOR = "SafetyInvestigator"
    SAFETY_APPEAL_REVIEWER = "SafetyAppealReviewer"
    SAFETY_OPERATIONS_LEAD = "SafetyOperationsLead"
    REGULATOR_LIAISON = "RegulatorLiaison"
    BACKGROUND_REVIEWER = "BackgroundReviewer"
    RIDER = "Rider"
    DRIVER = "Driver"


class Account(TypedDict, total=False):
    id: str
    account_type: str
    home_region_code: str
    legal_name: str
    contact_email: str
    status: str
    safety_posture: str
    risk_score: float
    risk_tier: str
    standing_enforcement_count: int
    deactivation_count: int
    three_year_drift_last_run_index: int
    prior_reinstatement_count: int
    policy_generation_index: int
    created_at: str
    updated_at: str
    version: int


class DeviceCluster(TypedDict, total=False):
    id: str
    cluster_key: str
    region_code: str
    aggregate_cluster_risk: float
    clustered_actor_incident_count: int
    cluster_risk_generation_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AccountDeviceLink(TypedDict, total=False):
    id: str
    account_id: str
    device_cluster_id: str
    fingerprint_hash: str
    first_seen_at: str
    last_seen_at: str
    link_status: str
    created_at: str
    updated_at: str
    version: int


class Trip(TypedDict, total=False):
    id: str
    rider_account_id: str
    driver_account_id: str
    region_code: str
    requested_at: str
    completed_at: Optional[str]
    status: str
    in_app_message_count: int
    law_enforcement_contact_logged: bool
    created_at: str
    updated_at: str
    version: int


class SafetyIncident(TypedDict, total=False):
    id: str
    account_id: str
    referenced_trip_id: Optional[str]
    reporter_type: str
    reporter_account_id: Optional[str]
    incident_category: str
    severity: str
    aggravator_codes: List[str]
    derivative_severity_flagged: bool
    incident_status: str
    decision_category: str
    decided_at: Optional[str]
    decision_basis: Optional[str]
    decision_evidence_score: float
    decision_support: float
    decision_distinct_evidence_sources: int
    appeal_reviewer_user_id: Optional[str]
    decision_maker_user_id: Optional[str]
    prior_incident_count_at_intake: int
    cluster_risk_multiplier_pct: int
    created_at: str
    updated_at: str
    version: int


class IncidentEvidence(TypedDict, total=False):
    id: str
    incident_id: str
    evidence_type: str
    source_entity_id: Optional[str]
    evidence_weight: str
    evidence_status: str
    recorded_at: str
    exclusion_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EnforcementAction(TypedDict, total=False):
    id: str
    account_id: str
    incident_id: str
    outcome: str
    enforcement_status: str
    effective_at: str
    review_due_at: str
    expires_at: str
    appeal_deadline_at: str
    decision_made_at: str
    last_applied_appeal_deadline: Optional[str]
    reinstatement_generation: int
    rehabilitation_credit: int
    regulator_report_required: bool
    cluster_watchlist_triggered: bool
    created_at: str
    updated_at: str
    version: int


class RegulatorReport(TypedDict, total=False):
    id: str
    incident_id: str
    region_code: str
    report_channel: str
    filing_basis: str
    filed_at: Optional[str]
    report_status: str
    created_at: str
    updated_at: str
    version: int


class BackgroundCheck(TypedDict, total=False):
    id: str
    account_id: str
    check_kind: str
    scheduled_due_at: str
    trigger_source: str
    triggered_by_incident_id: Optional[str]
    completed_at: Optional[str]
    adjudication: str
    adverse_reason_code: Optional[str]
    monitor_generation: int
    check_status: str
    created_at: str
    updated_at: str
    version: int


class PlatformPolicy(TypedDict, total=False):
    id: str
    region_code: str
    sd_floor_severity: str
    sd_floor_enabled: bool
    rollup_window_days: int
    rollup_threshold: int
    cluster_watchlist_threshold: int
    cluster_purge_threshold: float
    escalation_enabled: bool
    expedite_appeal_baseline_count: int
    expedite_review_days: int
    standard_review_days: int
    appeal_window_days: int
    rescreen_refresh_days: int
    continuous_monitor_ack_deadline_days: int
    review_generation_index: int
    knob_generation_index: int
    created_at: str
    updated_at: str
    version: int


class EvidenceScoreView(TypedDict, total=False):
    incident_id: str
    evidence_score: float
    support_score: float
    distinct_evidence_source_count: int
    applied_evidence_cap: float
    confidence_ratio: float
    dispositive_promotable: bool


class DecisionCriteriaView(TypedDict, total=False):
    incident_id: str
    category_tier: str
    evidence_tier: str
    proposed_decision: str
    scope_ratio: float
    regulator_report_required: bool


class AppealEligibilityView(TypedDict, total=False):
    incident_id: str
    appealable: bool
    appeal_track: str
    review_due_at: str
    appeal_deadline_at: str
    prior_incident_count_at_intake: int