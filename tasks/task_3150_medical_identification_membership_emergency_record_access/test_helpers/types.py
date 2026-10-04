"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class MembershipTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    LIFETIME = "LIFETIME"


class MemberType(str, Enum):
    ADULT = "ADULT"
    MINOR = "MINOR"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class GuardianLinkStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class ItemKind(str, Enum):
    CONDITION = "CONDITION"
    MEDICATION = "MEDICATION"
    ALLERGY = "ALLERGY"


class ConditionKind(str, Enum):
    GENERAL = "GENERAL"
    COGNITIVE = "COGNITIVE"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RecordItemStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ContactStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class DirectiveType(str, Enum):
    DNR = "DNR"
    POLST = "POLST"
    LIVING_WILL = "LIVING_WILL"
    HEALTHCARE_PROXY = "HEALTHCARE_PROXY"


class ReleaseScope(str, Enum):
    EMERGENCY_ONLY = "EMERGENCY_ONLY"
    EMERGENCY_AND_CONTACTS = "EMERGENCY_AND_CONTACTS"
    FULL = "FULL"


class DirectiveStatus(str, Enum):
    STORED = "STORED"
    RELEASED = "RELEASED"
    REVOKED = "REVOKED"


class EngraveMode(str, Enum):
    MANUAL = "MANUAL"
    SYNC_WITH_RECORD = "SYNC_WITH_RECORD"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    ENGRAVED = "ENGRAVED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class AccessTier(str, Enum):
    BASIC = "BASIC"
    FULL = "FULL"


class ResponderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class LookupMethod(str, Enum):
    IDENTIFIER = "IDENTIFIER"
    HOTLINE = "HOTLINE"


class AccessOutcome(str, Enum):
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class WanderingCaseStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class ReminderKind(str, Enum):
    RENEWAL = "RENEWAL"
    RECORD_UPDATE = "RECORD_UPDATE"
    LAPSE_WARNING = "LAPSE_WARNING"


class ReminderStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    CANCELLED = "CANCELLED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_CORRECTED = "RESOLVED_CORRECTED"
    DISMISSED = "DISMISSED"


class UserRole(str, Enum):
    MEMBER = "Member"
    GUARDIAN = "Guardian"
    RECORD_VERIFIER = "RecordVerifier"
    RESPONDER = "Responder"
    HOTLINE_OPERATOR = "HotlineOperator"
    FULFILLMENT_AGENT = "FulfillmentAgent"
    PLATFORM_ADMIN = "PlatformAdmin"


# --- Entity payloads -----------------------------------------------------------
# Most resources carry id + created_at + updated_at + version.
# AccessEvent, Reminder, and AuditEvent are append-only logs and carry
# only id + created_at (no updated_at, no version).


class Member(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    membership_tier: str
    member_type: str
    date_of_birth: str
    has_cognitive_condition: bool
    first_lifetime_sync_order_consumed: bool
    status: str
    expires_on: Optional[str]
    identifier_code: str
    balance_cents: int
    wallet_credit_cents: int
    record_revision: int
    created_at: str
    updated_at: str
    version: int


class GuardianLink(TypedDict, total=False):
    id: str
    member_id: str
    guardian_member_id: str
    relation_label: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MedicalRecordItem(TypedDict, total=False):
    id: str
    member_id: str
    item_kind: str
    condition_kind: str
    label: str
    detail: str
    severity: str
    provider_document_ref: str
    record_revision: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VerificationTicket(TypedDict, total=False):
    id: str
    record_item_id: str
    member_id: str
    provider_document_ref: str
    submission_round: int
    decision_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EmergencyContact(TypedDict, total=False):
    id: str
    member_id: str
    contact_name: str
    phone: str
    priority_rank: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AdvanceDirective(TypedDict, total=False):
    id: str
    member_id: str
    directive_type: str
    document_ref: str
    release_scope: str
    status: str
    created_at: str
    updated_at: str
    version: int


class IDProduct(TypedDict, total=False):
    id: str
    product_sku: str
    product_name: str
    base_price_cents: int
    max_engrave_chars: int
    created_at: str
    updated_at: str
    version: int


class ProductOrder(TypedDict, total=False):
    id: str
    member_id: str
    product_id: str
    engraving_text: str
    engrave_mode: str
    synced_revision: int
    price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ResponderCredential(TypedDict, total=False):
    id: str
    agency_name: str
    credential_code: str
    access_tier: str
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AccessEvent(TypedDict, total=False):
    # Append-only log: id + created_at only, no updated_at / version
    id: str
    member_id: str
    responder_id: str
    lookup_method: str
    operator_id: Optional[str]
    disclosed_scope: List[str]
    is_escalated: bool
    outcome: str
    reason_code: Optional[str]
    created_at: str


class WanderingCase(TypedDict, total=False):
    id: str
    member_id: str
    opened_via: str
    opened_at: str
    resolved_at: Optional[str]
    outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Reminder(TypedDict, total=False):
    # Append-only log: id + created_at only, no updated_at / version
    id: str
    member_id: str
    reminder_kind: str
    due_on: str
    sent_on: Optional[str]
    status: str
    created_at: str


class Dispute(TypedDict, total=False):
    id: str
    member_id: str
    record_item_id: str
    claim_text: str
    resolution_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditEvent(TypedDict, total=False):
    # Append-only log: id + created_at only, no updated_at / version
    id: str
    member_id: str
    actor_role: str
    actor_id: str
    action: str
    detail: Dict[str, Any]
    created_at: str
