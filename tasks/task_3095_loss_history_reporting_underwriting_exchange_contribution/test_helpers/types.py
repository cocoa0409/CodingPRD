"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    EXCHANGE_COMPLIANCE_OFFICER = "ExchangeComplianceOfficer"
    CARRIER_DATA_STEWARD = "CarrierDataSteward"
    CARRIER_UNDERWRITER = "CarrierUnderwriter"
    CONSUMER = "Consumer"


class CarrierStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class BatchStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    VOIDED = "VOIDED"


class ClaimStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNDER_DISPUTE = "UNDER_DISPUTE"
    AMENDED = "AMENDED"
    WITHDRAWN = "WITHDRAWN"


class LossType(str, Enum):
    COLLISION = "COLLISION"
    COMPREHENSIVE = "COMPREHENSIVE"
    LIABILITY = "LIABILITY"
    PROPERTY = "PROPERTY"
    OTHER = "OTHER"


class ClaimStatusCode(str, Enum):
    OPEN = "OPEN"
    CLOSED_WITH_PAYMENT = "CLOSED_WITH_PAYMENT"
    CLOSED_WITHOUT_PAYMENT = "CLOSED_WITHOUT_PAYMENT"
    SUBROGATED = "SUBROGATED"


class PermissiblePurpose(str, Enum):
    UNDERWRITING = "UNDERWRITING"
    CLAIMS = "CLAIMS"
    CONSUMER_REQUEST = "CONSUMER_REQUEST"


class MatchGrade(str, Enum):
    EXACT = "EXACT"
    FUZZY = "FUZZY"
    MISMATCH = "MISMATCH"
    ABSENT = "ABSENT"


class MatchDisposition(str, Enum):
    DEFINITE = "DEFINITE"
    PROBABLE = "PROBABLE"
    POSSIBLE = "POSSIBLE"
    UNMATCHED = "UNMATCHED"


class ReportBlockedReason(str, Enum):
    NONE = "NONE"
    FROZEN = "FROZEN"
    RECIPROCITY = "RECIPROCITY"


class ReportStatus(str, Enum):
    ISSUED = "ISSUED"
    FROZEN = "FROZEN"


class DisputeReason(str, Enum):
    NOT_MY_CLAIM = "NOT_MY_CLAIM"
    WRONG_AMOUNT = "WRONG_AMOUNT"
    WRONG_DATE = "WRONG_DATE"
    ALREADY_REMOVED = "ALREADY_REMOVED"
    OTHER = "OTHER"


class ResolutionCode(str, Enum):
    VERIFIED_ACCURATE = "VERIFIED_ACCURATE"
    AMENDED = "AMENDED"
    DELETED = "DELETED"


class DisputeStatus(str, Enum):
    FILED = "FILED"
    UNDER_REINVESTIGATION = "UNDER_REINVESTIGATION"
    RESOLVED_VERIFIED = "RESOLVED_VERIFIED"
    RESOLVED_AMENDED = "RESOLVED_AMENDED"
    RESOLVED_DELETED = "RESOLVED_DELETED"


class NoticeActionType(str, Enum):
    DECLINE = "DECLINE"
    RATE_INCREASE = "RATE_INCREASE"
    NON_RENEWAL = "NON_RENEWAL"
    CANCELLATION = "CANCELLATION"


class NoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CANCELLED = "CANCELLED"


class AuditEventType(str, Enum):
    BATCH_RECEIVED = "BATCH_RECEIVED"
    BATCH_COMPLETED = "BATCH_COMPLETED"
    BATCH_FAILED = "BATCH_FAILED"
    BATCH_VOIDED = "BATCH_VOIDED"
    BATCH_FROZEN_BY_CORRECTION = "BATCH_FROZEN_BY_CORRECTION"
    CLAIM_ACCEPTED = "CLAIM_ACCEPTED"
    CLAIM_REJECTED = "CLAIM_REJECTED"
    CLAIM_AMENDED = "CLAIM_AMENDED"
    CLAIM_WITHDRAWN = "CLAIM_WITHDRAWN"
    REPORT_ISSUED = "REPORT_ISSUED"
    REPORT_FROZEN = "REPORT_FROZEN"
    DISPUTE_FILED = "DISPUTE_FILED"
    DISPUTE_REINVESTIGATED = "DISPUTE_REINVESTIGATED"
    DISPUTE_OVERDUE = "DISPUTE_OVERDUE"
    DISPUTE_RESOLVED = "DISPUTE_RESOLVED"
    ADVERSE_ACTION_FILED = "ADVERSE_ACTION_FILED"
    ADVERSE_ACTION_SENT = "ADVERSE_ACTION_SENT"
    ADVERSE_ACTION_ACKNOWLEDGED = "ADVERSE_ACTION_ACKNOWLEDGED"
    DATA_FREEZE_APPLIED = "DATA_FREEZE_APPLIED"
    DATA_FREEZE_LIFTED = "DATA_FREEZE_LIFTED"
    CARRIER_SUSPENDED = "CARRIER_SUSPENDED"
    CARRIER_REACTIVATED = "CARRIER_REACTIVATED"
    RETENTION_REDACTED = "RETENTION_REDACTED"


class Carrier(TypedDict, total=False):
    id: str
    legal_name: str
    naic_code: str
    status: str
    contribution_lag_days: Optional[int]
    accepted_batch_count: int
    accepted_claim_count: int
    created_at: str
    updated_at: str
    version: int


class Consumer(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    address_line: str
    driver_license_number: str
    file_frozen: bool
    frozen_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContributionBatch(TypedDict, total=False):
    id: str
    carrier_id: str
    submitted_at: str
    claim_count: int
    accepted_count: int
    rejected_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LossClaim(TypedDict, total=False):
    id: str
    contributing_carrier_id: str
    batch_id: str
    consumer_id: str
    policy_number: str
    claim_number: str
    loss_date: str
    loss_type: str
    cause_of_loss_code: str
    paid_amount_cents: int
    claim_status_code: str
    vehicle_identifier: str
    status: str
    amendment_of_id: Optional[str]
    retention_expires_on: str
    created_at: str
    updated_at: str
    version: int


class QuoteInquiry(TypedDict, total=False):
    id: str
    carrier_id: str
    subject_name: str
    subject_dob: str
    subject_address: str
    subject_driver_license: str
    subject_vehicle_identifier: str
    permissible_purpose: str
    matched_consumer_id: Optional[str]
    individual_match_grade: Optional[str]
    address_match_grade: Optional[str]
    vehicle_match_grade: Optional[str]
    match_score: int
    match_disposition: str
    report_id: Optional[str]
    report_blocked_reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LossHistoryReport(TypedDict, total=False):
    id: str
    inquiry_id: str
    carrier_id: str
    consumer_id: str
    match_disposition: str
    risk_score_certainty: float
    risk_score_count: int
    risk_score_premium_weighted_cents: int
    claim_count_reported: int
    status: str
    delivered_at: str
    created_at: str
    updated_at: str
    version: int


class ReportClaimEntry(TypedDict, total=False):
    # Snapshot kind: carries only id + created_at, no updated_at / version
    id: str
    report_id: str
    loss_claim_id: str
    consumer_id: str
    entry_sequence: int
    loss_date: str
    loss_type: str
    cause_of_loss_code: str
    paid_amount_cents: int
    claim_status_code: str
    contributing_carrier_id: str
    created_at: str


class ConsumerDispute(TypedDict, total=False):
    id: str
    consumer_id: str
    loss_claim_id: str
    dispute_reason: str
    dispute_statement: str
    filed_at: str
    reinvestigation_due_at: str
    resolved_at: Optional[str]
    resolution_code: Optional[str]
    resolution_notes: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AdverseActionNotice(TypedDict, total=False):
    id: str
    carrier_id: str
    report_id: str
    consumer_id: str
    action_type: str
    notice_reason_codes: List[str]
    report_influence_rank: int
    disclosure_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ExchangeRule(TypedDict, total=False):
    id: str
    retention_years: int
    reinvestigation_days: int
    correction_hold_days: int
    data_freeze_days: int
    reciprocity_lag_threshold_days: int
    max_outstanding_inquiries: int
    min_batch_claims: int
    max_batch_claims: int
    disclosure_window_days: int
    premium_weight_cap_cents: int
    created_at: str
    updated_at: str
    version: int


class ContributionAuditEvent(TypedDict, total=False):
    # Snapshot kind: carries only id + created_at, no updated_at / version
    id: str
    carrier_id: str
    consumer_id: Optional[str]
    event_type: str
    event_at: str
    details: Dict[str, Any]
    created_at: str
