"""Domain types for the Esign Envelope Workflow API.

Entity TypedDicts, status enums and the role enum derived from the PRD's entity
and lifecycle descriptions.  Entities that carry the standard resource fields
have ``created_at``/``updated_at``/``version``; the append-only ``AuditEvent``
deliberately has neither ``updated_at`` nor ``version``.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ACCOUNT = "Account"
    RECIPIENT = "Recipient"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class EnvelopeStatus(str, Enum):
    CREATED = "CREATED"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"


class RoutingMode(str, Enum):
    SEQUENTIAL = "SEQUENTIAL"
    PARALLEL = "PARALLEL"


class RecipientRole(str, Enum):
    SIGNER = "SIGNER"
    APPROVER = "APPROVER"
    COPY = "COPY"


class RecipientStatus(str, Enum):
    WAITING = "WAITING"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    SIGNING = "SIGNING"
    SIGNED = "SIGNED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"


class AuthStatus(str, Enum):
    PENDING = "PENDING"
    AUTHENTICATED = "AUTHENTICATED"
    FAILED = "FAILED"


class AuthLevel(str, Enum):
    EMAIL_ACCESS = "EMAIL_ACCESS"
    ACCESS_CODE = "ACCESS_CODE"
    KBA = "KBA"
    ID_DOCUMENT = "ID_DOCUMENT"


class SigningSessionStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class FieldType(str, Enum):
    SIGNATURE = "SIGNATURE"
    INITIAL = "INITIAL"
    DATE = "DATE"
    TEXT = "TEXT"
    CHECKBOX = "CHECKBOX"


class TemplateStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class AccountTier(str, Enum):
    STANDARD = "STANDARD"
    PRO = "PRO"
    ENTERPRISE = "ENTERPRISE"


class RetentionScope(str, Enum):
    ACCOUNT = "ACCOUNT"
    GLOBAL = "GLOBAL"


class PurgeMode(str, Enum):
    ANONYMIZE_METADATA = "ANONYMIZE_METADATA"
    DELETE_ALL = "DELETE_ALL"


class AuditEventType(str, Enum):
    ENVELOPE_CREATED = "ENVELOPE_CREATED"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    SESSION_OPENED = "SESSION_OPENED"
    AUTH_SUCCEEDED = "AUTH_SUCCEEDED"
    AUTH_FAILED = "AUTH_FAILED"
    CONSENT_ACCEPTED = "CONSENT_ACCEPTED"
    FIELD_COMPLETED = "FIELD_COMPLETED"
    RECIPIENT_SIGNED = "RECIPIENT_SIGNED"
    RECIPIENT_APPROVED = "RECIPIENT_APPROVED"
    RECIPIENT_DECLINED = "RECIPIENT_DECLINED"
    DOCUMENT_HASHED = "DOCUMENT_HASHED"
    SEALED = "SEALED"
    CERTIFICATE_GENERATED = "CERTIFICATE_GENERATED"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"
    REMINDER_SENT = "REMINDER_SENT"
    PURGED = "PURGED"


class BulkSendStatus(str, Enum):
    CREATED = "CREATED"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (standard resources: id + created_at + updated_at + version)
# ---------------------------------------------------------------------------
class Account(TypedDict):
    id: str
    name: str
    state_code: str
    status: str
    credit_balance: int
    tier: str
    page_allowance: int
    created_at: str
    updated_at: str
    version: int


class RetentionPolicy(TypedDict):
    id: str
    name: str
    scope: str
    retention_years: int
    purge_mode: str
    purge_grace_days: int
    created_at: str
    updated_at: str
    version: int


class Envelope(TypedDict):
    id: str
    sender_account_id: str
    subject: str
    status: str
    routing_mode: str
    sender_visible_window_days: int
    sent_at: Optional[str]
    expires_at: Optional[str]
    expires_after_days: int
    sender_visible_expires_at: Optional[str]
    is_sealed: bool
    seal_hash: Optional[str]
    certificate_hash: Optional[str]
    audit_certificate_id: Optional[str]
    retention_policy_id: str
    legal_hold: bool
    legal_hold_started_at: Optional[str]
    legal_hold_until: Optional[str]
    purged_at: Optional[str]
    decline_reason: Optional[str]
    void_reason: Optional[str]
    template_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EnvelopeDocument(TypedDict):
    id: str
    envelope_id: str
    name: str
    page_count: int
    document_hash: Optional[str]
    is_certificate: bool
    created_at: str
    updated_at: str
    version: int


class Recipient(TypedDict):
    id: str
    envelope_id: str
    role: str
    email: str
    routing_order: int
    status: str
    auth_status: str
    auth_level: str
    access_code: Optional[str]
    kba_fail_count: int
    identity_verified: bool
    consent_accepted: bool
    consent_accepted_at: Optional[str]
    auth_risk_score: int
    auth_risk_score_final: int
    signed_at: Optional[str]
    reminder_count: int
    last_reminder_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FieldPlacement(TypedDict):
    id: str
    envelope_id: str
    envelope_document_id: str
    recipient_id: str
    field_type: str
    required: bool
    value: Optional[str]
    page_number: int
    tab_order: int
    created_at: str
    updated_at: str
    version: int


class SigningSession(TypedDict):
    id: str
    recipient_id: str
    envelope_id: str
    status: str
    consent_to_electronic_records: bool
    consent_captured_at: Optional[str]
    opened_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Template(TypedDict):
    id: str
    owning_account_id: str
    name: str
    default_routing_mode: str
    default_auth_level: str
    page_count: int
    status: str
    role_slot_count: int
    times_used: int
    created_at: str
    updated_at: str
    version: int


class BulkSendBatch(TypedDict):
    id: str
    account_id: str
    template_id: str
    total_rows: int
    status: str
    succeeded_count: int
    failed_count: int
    created_at: str
    updated_at: str
    version: int


class AuditEvent(TypedDict):
    """Append-only and immutable: carries ONLY id and created_at."""
    id: str
    created_at: str
    envelope_id: str
    sequence_number: int
    event_type: str
    recipient_id: Optional[str]
    event_at: str
    prev_hash: Optional[str]
    event_hash: str
    detail: Optional[str]


class FeeQuote(TypedDict):
    total_pages: int
    page_component: float
    subtotal: float
    discount: float
    total_fee: float


class FeeBreakdown(TypedDict):
    per_document_fee: float
    total_page_fee: float


class AuditCertificate(TypedDict):
    certificate_hash: str
    seal_hash: str
    event_count: int


# Convenience collections used by assertions and parametrized tests.
ENVELOPE_STATES: List[str] = [s.value for s in EnvelopeStatus]
TERMINAL_ENVELOPE_STATES: List[str] = [
    EnvelopeStatus.COMPLETED.value,
    EnvelopeStatus.DECLINED.value,
    EnvelopeStatus.VOIDED.value,
    EnvelopeStatus.EXPIRED.value,
]
RECIPIENT_STATES: List[str] = [s.value for s in RecipientStatus]
TERMINAL_RECIPIENT_STATES: List[str] = [
    RecipientStatus.SIGNED.value,
    RecipientStatus.APPROVED.value,
    RecipientStatus.DECLINED.value,
    RecipientStatus.VOIDED.value,
    RecipientStatus.EXPIRED.value,
]