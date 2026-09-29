"""Typed response shapes for every entity the PRD declares.

Two identity blocks exist and the difference is contractual:

PRD §2.4: "Every resource carries an `id` that is a UUID string with no prefix
and a `created_at` timestamp read from the logical clock."

PRD §2.4: "`PolicyRule`, `CountryPolicyOverride`, `Advertiser`, `Reviewer`,
`AdCreative`, `ReviewTask`, `Certification`, `DisapprovalNotice`, `Appeal` and
`EnforcementAction` additionally carry an `updated_at` timestamp and an integer
`version` that starts at 1 and increases by exactly 1 on every mutation."

PRD §2.4: "`ScreeningRun`, `ClassifierDecision`, `DestinationCheck`,
`PoliticalArchiveEntry` and `ViolationLedgerEntry` are append-only records that
carry only `id` and `created_at`."

`MutableEntity` therefore models the first group and `AppendOnlyRecord` the
second; the append-only shapes deliberately have no `updated_at` and no
`version`.
"""

from typing import Any, Dict, List, Literal, Optional, TypedDict

UserRole = Literal["Advertiser", "PolicyReviewer", "IntegrityAnalyst", "PolicyAdmin"]

CategoryClass = Literal["PROHIBITED", "RESTRICTED", "REGULATED"]
Disposition = Literal[
    "BLOCKED", "RESTRICTED_CERT_REQUIRED", "ALLOWED_WITH_DISCLAIMER", "ALLOWED"
]
Queue = Literal["STANDARD", "REGULATED_CERT", "POLITICAL"]
IdentityStatus = Literal["PENDING", "VERIFIED", "FAILED"]
IndustryAuthorizationStatus = Literal["NOT_REQUIRED", "PENDING", "GRANTED", "DENIED"]
PoliticalEligibilityStatus = Literal[
    "NOT_REQUESTED", "PENDING", "ELIGIBLE", "INELIGIBLE"
]
AccountStatus = Literal["ACTIVE", "WARNED", "RESTRICTED", "SUSPENDED"]
ReviewStatus = Literal[
    "DRAFT",
    "SCREENING",
    "AUTO_APPROVED",
    "PENDING_MANUAL_REVIEW",
    "APPROVED_LIMITED",
    "DISAPPROVED",
    "SUSPENDED_HOLD",
    "WITHDRAWN",
]
DestinationStatus = Literal[
    "NOT_CHECKED",
    "DESTINATION_PENDING",
    "DESTINATION_CLEARED",
    "MISMATCH_FLAGGED",
    "CLOAKING_CONFIRMED",
]
ScreeningOutcome = Literal["AUTO_APPROVED", "ROUTED_MANUAL", "AUTO_DISAPPROVED"]
DecisionDisposition = Literal["AUTO_DISAPPROVE", "ROUTE_MANUAL", "BELOW_THRESHOLD"]
TaskStatus = Literal["QUEUED", "CLAIMED", "RESOLVED", "ESCALATED", "EXPIRED"]
TaskResolution = Literal[
    "PENDING", "APPROVE", "APPROVE_WITH_LIMITS", "DISAPPROVE", "ESCALATE"
]
ReviewerStatus = Literal["ACTIVE", "OFFLINE"]
CertificationStatus = Literal["SUBMITTED", "ACTIVE", "EXPIRED", "REVOKED"]
CheckType = Literal["INITIAL", "RECHECK"]
UserAgentVariant = Literal["CRAWLER", "USER"]
DestinationResult = Literal["CLEARED", "MISMATCH", "CLOAKING"]
MismatchDetail = Literal[
    "HOST_MISMATCH", "CATEGORY_MISMATCH", "UA_DIVERGENCE", "DEST_UNREACHABLE"
]
NoticeReasonCode = Literal[
    "AUTO_SCREENING",
    "MANUAL_REVIEW",
    "DESTINATION_MISMATCH",
    "CLOAKING",
    "CERT_MISSING",
    "POLITICAL_DISCLOSURE",
]
NoticeStatus = Literal[
    "ISSUED", "APPEALED", "APPEAL_GRANTED", "APPEAL_UPHELD", "EXPIRED"
]
AppealStatus = Literal["SUBMITTED", "GRANTED", "DENIED"]
LedgerReason = Literal["DISAPPROVAL_ASSESSED", "APPEAL_REVERSAL"]
ActionType = Literal["WARNING", "RESTRICTION", "SUSPENSION"]
ActionOrigin = Literal["SYSTEM_CASCADE", "MANUAL"]
ActionStatus = Literal["ACTIVE", "LIFTED", "SUPERSEDED", "EXPIRED"]


class MutableEntity(TypedDict):
    """Identity block for the ten rows that carry `updated_at` and `version`."""

    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyRecord(TypedDict):
    """Identity block for the five append-only records: `id` and `created_at` only."""

    id: str
    created_at: str


class PolicyRule(MutableEntity):
    code: str
    title: str
    category_class: CategoryClass
    base_severity_weight: float
    requires_certification: bool
    requires_disclaimer: bool
    confidence_auto_disapprove_threshold: float
    confidence_manual_threshold: float
    review_sla_hours: int
    default_queue: Queue
    country_override_count: int


class CountryPolicyOverride(MutableEntity):
    policy_rule_id: str
    country_code: str
    disposition: Disposition
    requires_license: bool
    requires_disclaimer: bool
    severity_multiplier: float


class Advertiser(MutableEntity):
    legal_name: str
    country_code: str
    industry_code: str
    identity_status: IdentityStatus
    business_standing_status: IdentityStatus
    industry_authorization_status: IndustryAuthorizationStatus
    political_eligibility_status: PoliticalEligibilityStatus
    account_status: AccountStatus
    violation_points_raw: float
    violation_points_decayed: float
    severity_index: float
    ledger_entry_count: int


class Reviewer(MutableEntity):
    display_name: str
    queue_specialties: List[Queue]
    country_authorizations: List[str]
    max_concurrent_claims: int
    claimed_task_count: int
    status: ReviewerStatus


class AdCreative(MutableEntity):
    advertiser_id: str
    headline: str
    body_text: str
    declared_category_codes: List[str]
    target_country_codes: List[str]
    landing_page_url: str
    display_url: str
    political_flag: bool
    disclaimer_text: Optional[str]
    review_status: ReviewStatus
    destination_status: DestinationStatus
    risk_score_provisional: float
    risk_score_final: float
    serving_eligible: bool
    blocking_reason_codes: List[str]
    limited_country_codes: List[str]
    approved_under_certification_id: Optional[str]
    screening_run_count: int


class ScreeningRun(AppendOnlyRecord):
    ad_creative_id: str
    classifier_version: str
    sequence_index: int
    outcome: ScreeningOutcome
    decision_count: int
    max_confidence: float
    provisional_risk_score: float
    creative_version_at_run: int


class ClassifierDecision(AppendOnlyRecord):
    screening_run_id: str
    policy_rule_id: str
    confidence: float
    matched_snippet: str
    disposition: DecisionDisposition
    country_multiplier_applied: float
    assessed_points: float


class ReviewTask(MutableEntity):
    ad_creative_id: str
    primary_policy_rule_id: Optional[str]
    assigned_reviewer_id: Optional[str]
    queue: Queue
    status: TaskStatus
    resolution: TaskResolution
    priority_score: float
    sla_deadline_at: str
    cycle_count: int
    claimed_at: Optional[str]
    escalation_note: Optional[str]


class Certification(MutableEntity):
    advertiser_id: str
    policy_rule_id: str
    license_number: str
    issuing_country_code: str
    valid_from: str
    valid_until: str
    status: CertificationStatus
    revocation_reason: Optional[str]


class DestinationCheck(AppendOnlyRecord):
    ad_creative_id: str
    check_type: CheckType
    user_agent_variant: UserAgentVariant
    fetched_final_url: str
    fetched_content_category: str
    http_status: int
    result: DestinationResult
    mismatch_detail: Optional[MismatchDetail]


class DisapprovalNotice(MutableEntity):
    ad_creative_id: str
    decided_by_reviewer_id: Optional[str]
    reason_codes: List[NoticeReasonCode]
    policy_rule_codes: List[str]
    assessment_lines: List[Dict[str, Any]]
    assessed_points: float
    disclosed_points_total: float
    appeal_window_hours: int
    appeal_deadline_at: str
    status: NoticeStatus
    political_at_issue: bool


class Appeal(MutableEntity):
    disapproval_notice_id: str
    evidence_certification_id: Optional[str]
    decided_by_reviewer_id: Optional[str]
    justification: str
    status: AppealStatus
    decided_at: Optional[str]
    reinstated_review_status: Optional[ReviewStatus]


class EnforcementAction(MutableEntity):
    advertiser_id: str
    prior_action_id: Optional[str]
    source_notice_id: Optional[str]
    action_type: ActionType
    origin: ActionOrigin
    trigger_reason: str
    severity_index_at_issue: float
    effective_from: str
    effective_until: str
    status: ActionStatus


class PoliticalArchiveEntry(AppendOnlyRecord):
    ad_creative_id: str
    advertiser_id: str
    disclosure_text: Optional[str]
    payer_name: str
    headline_snapshot: str
    target_country_codes_snapshot: List[str]
    archived_at: str
    retention_until: str
    searchable: bool


class ViolationLedgerEntry(AppendOnlyRecord):
    advertiser_id: str
    source_notice_id: Optional[str]
    delta_points: float
    reason: LedgerReason
    balance_after: float
    entry_index: int


class SweepCounts(TypedDict):
    activated_certifications: int
    expired_certifications: int
    expired_notices: int
    expired_review_tasks: int
    requeued_review_tasks: int
    expired_enforcement_actions: int
    lifted_enforcement_actions: int
    released_hold_creatives: int
    decay_refreshed_advertisers: int


class ClockReading(TypedDict):
    current_utc: str
    previous_utc: str
