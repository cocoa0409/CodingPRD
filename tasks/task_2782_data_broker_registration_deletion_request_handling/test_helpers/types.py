"""Domain types: entity TypedDicts, status enums and the role enum."""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    BROKER_ADMIN = "BrokerAdmin"
    CONSUMER = "Consumer"
    INTAKE_AGENT = "IntakeAgent"
    PRIVACY_REVIEWER = "PrivacyReviewer"
    STATE_PLATFORM = "StatePlatform"
    REGULATOR = "Regulator"
    PLATFORM_ADMIN = "PlatformAdmin"


class RegistryStanding(str, Enum):
    COMPLIANT = "COMPLIANT"
    DELINQUENT = "DELINQUENT"
    SUSPENDED = "SUSPENDED"


class RegistrationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class RejectionReasonCode(str, Enum):
    INCOMPLETE_DISCLOSURE = "INCOMPLETE_DISCLOSURE"
    INACCURATE_DESCRIPTION = "INACCURATE_DESCRIPTION"
    FEE_DISPUTE = "FEE_DISPUTE"


class DisclosureCategory(str, Enum):
    SOURCES = "SOURCES"
    RECIPIENTS = "RECIPIENTS"
    RETENTION = "RETENTION"
    SENSITIVE_CATEGORIES = "SENSITIVE_CATEGORIES"
    OPT_OUT_MECHANISM = "OPT_OUT_MECHANISM"
    MINORS_DATA = "MINORS_DATA"


class CollectionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PURGE_PENDING = "PURGE_PENDING"
    PURGED = "PURGED"
    REACQUIRED = "REACQUIRED"


class ConsentStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    CONSENT_PENDING = "CONSENT_PENDING"
    CONSENT_GRANTED = "CONSENT_GRANTED"
    CONSENT_REVOKED = "CONSENT_REVOKED"


class ConsentAction(str, Enum):
    REQUEST = "REQUEST"
    GRANT = "GRANT"
    REVOKE = "REVOKE"


class SensitiveCategory(str, Enum):
    PRECISE_GEOLOCATION = "PRECISE_GEOLOCATION"
    BIOMETRIC = "BIOMETRIC"
    HEALTH = "HEALTH"
    RACE_OR_ETHNICITY = "RACE_OR_ETHNICITY"
    SEXUAL_ORIENTATION = "SEXUAL_ORIENTATION"
    IMMIGRATION_STATUS = "IMMIGRATION_STATUS"
    MINOR_STATUS = "MINOR_STATUS"


class IntakeChannel(str, Enum):
    DIRECT_PORTAL = "DIRECT_PORTAL"
    STATE_PLATFORM = "STATE_PLATFORM"
    AUTHORIZED_AGENT = "AUTHORIZED_AGENT"
    EMAIL = "EMAIL"


class RequestedScope(str, Enum):
    DELETE_ALL = "DELETE_ALL"
    DELETE_SENSITIVE_ONLY = "DELETE_SENSITIVE_ONLY"


class DeletionRequestStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VERIFICATION_PENDING = "VERIFICATION_PENDING"
    VERIFIED = "VERIFIED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class DenialReasonCode(str, Enum):
    IDENTITY_UNVERIFIED = "IDENTITY_UNVERIFIED"
    EXEMPT_RECORD = "EXEMPT_RECORD"
    DUPLICATE_REQUEST = "DUPLICATE_REQUEST"


class VerificationMethod(str, Enum):
    GOVT_ID = "GOVT_ID"
    TWO_DATA_POINTS = "TWO_DATA_POINTS"
    PLATFORM_ASSERTION = "PLATFORM_ASSERTION"
    AGENT_LOA = "AGENT_LOA"


class AssuranceVariant(str, Enum):
    FRAUD_WEIGHTED = "FRAUD_WEIGHTED"
    PLATFORM_ASSERTED = "PLATFORM_ASSERTED"


class AttemptOutcome(str, Enum):
    PASS = "PASS"
    INCONCLUSIVE = "INCONCLUSIVE"
    FAIL = "FAIL"


class VerificationDecision(str, Enum):
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class RecipientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class TargetKind(str, Enum):
    ACTIVE_DATABASE = "ACTIVE_DATABASE"
    BACKUP_ARCHIVE = "BACKUP_ARCHIVE"
    DERIVED_DATASET = "DERIVED_DATASET"
    DOWNSTREAM_RECIPIENT = "DOWNSTREAM_RECIPIENT"


class PropagationTaskStatus(str, Enum):
    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    DEFERRED = "DEFERRED"
    FAILED = "FAILED"
    ACKED = "ACKED"
    WAIVED = "WAIVED"
    ABANDONED = "ABANDONED"


class FailureCode(str, Enum):
    RECIPIENT_UNREACHABLE = "RECIPIENT_UNREACHABLE"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    LEGAL_HOLD = "LEGAL_HOLD"


class DeferralReason(str, Enum):
    RECIPIENT_SUSPENDED = "RECIPIENT_SUSPENDED"
    BROKER_DELINQUENT = "BROKER_DELINQUENT"


class SuppressionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"
    EXPIRED = "EXPIRED"


class SourceScope(str, Enum):
    ALL_SOURCES = "ALL_SOURCES"
    SINGLE_SOURCE = "SINGLE_SOURCE"


class SignalType(str, Enum):
    GPC_BROWSER = "GPC_BROWSER"
    PLATFORM_BULK = "PLATFORM_BULK"
    WRITTEN_REQUEST = "WRITTEN_REQUEST"
    AGENT_SUBMITTED = "AGENT_SUBMITTED"


class OptOutScope(str, Enum):
    SALE = "SALE"
    SHARING = "SHARING"
    SALE_AND_SHARING = "SALE_AND_SHARING"


class OptOutSignalStatus(str, Enum):
    RECEIVED = "RECEIVED"
    HONORED = "HONORED"
    SUPERSEDED = "SUPERSEDED"


class InquiryStatus(str, Enum):
    OPEN = "OPEN"
    RESPONDED = "RESPONDED"
    CLOSED = "CLOSED"
    ESCALATED = "ESCALATED"


class AdequacyVerdict(str, Enum):
    UNRATED = "UNRATED"
    ADEQUATE = "ADEQUATE"
    DEFICIENT = "DEFICIENT"


class DeficiencyCode(str, Enum):
    MISSING_AUDIT_TRAIL = "MISSING_AUDIT_TRAIL"
    UNVERIFIED_IDENTITY_PRACTICE = "UNVERIFIED_IDENTITY_PRACTICE"
    PROPAGATION_GAP = "PROPAGATION_GAP"


class SubjectKind(str, Enum):
    BROKER = "BROKER"
    REGISTRATION = "REGISTRATION"
    DISCLOSURE = "DISCLOSURE"
    CONSUMER = "CONSUMER"
    DELETION_REQUEST = "DELETION_REQUEST"
    VERIFICATION_ATTEMPT = "VERIFICATION_ATTEMPT"
    PROPAGATION_TASK = "PROPAGATION_TASK"
    RECIPIENT = "RECIPIENT"
    SUPPRESSION_ENTRY = "SUPPRESSION_ENTRY"
    OPT_OUT_SIGNAL = "OPT_OUT_SIGNAL"
    INQUIRY = "INQUIRY"


AUDIT_EVENT_TYPES = [
    "BROKER_REGISTERED",
    "FEE_DEPOSITED",
    "REGISTRATION_CREATED",
    "DISCLOSURE_ADDED",
    "REGISTRATION_SUBMITTED",
    "REGISTRATION_ACCEPTED",
    "REGISTRATION_REJECTED",
    "REGISTRATION_WITHDRAWN",
    "REGISTRATION_EXPIRED",
    "STANDING_CHANGED",
    "CONSUMER_RECORDED",
    "CONSUMER_COLLECTION_RECORDED",
    "RECOLLECTION_BLOCKED",
    "CONSENT_CHANGED",
    "DELETION_REQUEST_RECEIVED",
    "DELETION_REQUEST_SUPERSEDED",
    "VERIFICATION_ATTEMPT_RECORDED",
    "VERIFICATION_DECIDED",
    "DELETION_EXECUTED",
    "PROPAGATION_DISPATCHED",
    "PROPAGATION_ACKED",
    "PROPAGATION_FAILED",
    "PROPAGATION_WAIVED",
    "PROPAGATION_DEFERRED",
    "PROPAGATION_ABANDONED",
    "DELETION_COMPLETED",
    "DELETION_DENIED",
    "DELETION_WITHDRAWN",
    "SUPPRESSION_CREATED",
    "SUPPRESSION_LIFTED",
    "SUPPRESSION_EXPIRED",
    "RECIPIENT_REGISTERED",
    "RECIPIENT_STATUS_CHANGED",
    "OPT_OUT_RECEIVED",
    "OPT_OUT_HONORED",
    "INQUIRY_OPENED",
    "INQUIRY_RESPONDED",
    "INQUIRY_CLOSED",
    "INQUIRY_ESCALATED",
]


# --- entity payload shapes ---------------------------------------------------
# Entities that carry the common fields id / created_at / updated_at / version.


class DataBroker(TypedDict):
    id: str
    legal_name: str
    primary_contact_email: str
    home_state_code: str
    operating_state_codes: List[str]
    business_description: str
    registry_standing: str
    delinquent_since: Optional[str]
    fee_deposited_cents: int
    fee_paid_cents: int
    fee_credit_cents: int
    open_breach_count: int
    request_intake_total: int
    request_open_count: int
    request_completed_count: int
    request_terminated_count: int
    audit_sequence_high_water: int
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict):
    id: str
    broker_id: str
    state_code: str
    status: str
    coverage_period_start: str
    coverage_period_end: str
    coverage_days: int
    business_description: str
    disclosure_completeness_score: float
    provisional_filing_fee_cents: int
    final_filing_fee_cents: Optional[int]
    charged_fee_cents: int
    submitted_at: Optional[str]
    accepted_at: Optional[str]
    rejection_reason_code: Optional[str]
    revision_count: int
    superseded_registration_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Consumer(TypedDict):
    id: str
    broker_id: str
    identity_hash: str
    state_code: str
    sensitive_categories: List[str]
    derived_profile_count: int
    source_label: str
    collection_status: str
    consent_status: str
    collection_event_count: int
    opt_out_sale: bool
    opt_out_sharing: bool
    last_purged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeletionRequest(TypedDict):
    id: str
    broker_id: str
    consumer_id: str
    intake_channel: str
    requested_scope: str
    status: str
    identity_assurance_score: float
    verification_attempt_count: int
    failed_attempt_count: int
    agent_loa_reference: Optional[str]
    intake_user_id: str
    verification_decided_by_user_id: Optional[str]
    executed_by_user_id: Optional[str]
    propagation_required_count: int
    downstream_task_count: int
    acked_task_count: int
    waived_task_count: int
    abandoned_task_count: int
    outstanding_task_count: int
    completion_ratio: float
    compliance_breach: bool
    executed_at: Optional[str]
    denial_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DownstreamRecipient(TypedDict):
    id: str
    broker_id: str
    name: str
    contract_propagation_required: bool
    ack_sla_days: int
    status: str
    on_time_ack_count: int
    late_ack_count: int
    fail_count: int
    waive_count: int
    reliability_score: float
    created_at: str
    updated_at: str
    version: int


class PropagationTask(TypedDict):
    id: str
    deletion_request_id: str
    recipient_id: Optional[str]
    target_kind: str
    status: str
    weight: int
    sla_days: int
    due_at: str
    dispatched_at: Optional[str]
    acknowledged_at: Optional[str]
    ack_was_late: bool
    dispatch_count: int
    failure_code: Optional[str]
    deferral_reason: Optional[str]
    waiver_justification: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SuppressionEntry(TypedDict):
    id: str
    broker_id: str
    consumer_id: str
    originating_request_id: Optional[str]
    window_start: str
    window_end: str
    source_scope: str
    status: str
    lift_justification: Optional[str]
    blocked_recollection_count: int
    created_at: str
    updated_at: str
    version: int


class OptOutSignal(TypedDict):
    id: str
    broker_id: str
    consumer_id: str
    signal_type: str
    scope: str
    gpc_header_value: Optional[str]
    agent_reference: Optional[str]
    status: str
    honor_deadline_at: str
    honored_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RegulatorInquiry(TypedDict):
    id: str
    broker_id: str
    scope_note: str
    response_due_at: str
    status: str
    cited_audit_event_ids: List[str]
    cited_event_count: int
    coverage_bonus_applied: bool
    evidence_score: float
    deficiency_penalty: float
    late_response_penalty: float
    adequacy_score: float
    adequacy_verdict: str
    responded_at: Optional[str]
    deficiency_code: Optional[str]
    escalation_count: int
    created_at: str
    updated_at: str
    version: int


# --- append-only families: only id and created_at, no updated_at, no version --


class DisclosureItem(TypedDict):
    id: str
    registration_id: str
    category: str
    content: str
    content_length: int
    covers_sensitive_categories: bool
    weight_credit: float
    surcharge_cents: int
    created_at: str


class VerificationAttempt(TypedDict):
    id: str
    deletion_request_id: str
    method: str
    evidence_points_count: int
    document_quality_score: float
    platform_assertion_reference: Optional[str]
    variant_applied: str
    raw_score: float
    fraud_penalty_applied: float
    assurance_score: float
    outcome: str
    recorded_by_user_id: str
    created_at: str


class AuditEvent(TypedDict):
    id: str
    broker_id: str
    sequence_no: int
    event_type: str
    subject_kind: str
    subject_id: str
    actor_role: str
    actor_user_id: Optional[str]
    summary: str
    retention_expires_at: str
    created_at: str
