"""Domain types: entity TypedDicts, status enums, and the role enum.

Accounts, brands, campaigns, sender numbers, and messages carry the full
common field set (id, created_at, updated_at, version). Consent records,
feedback events, charges, daily snapshots, and ops runs are append-style
records: they carry only id and created_at, and expose neither updated_at
nor version (PRD section 2.4).
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    BRAND_MANAGER = "BrandManager"
    CAMPAIGN_MANAGER = "CampaignManager"
    CARRIER_REVIEWER = "CarrierReviewer"
    NUMBER_PROVISIONER = "NumberProvisioner"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    DELIVERABILITY_ANALYST = "DeliverabilityAnalyst"
    SYSTEM_DRIVER = "SystemDriver"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class BrandStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    REVOKED = "REVOKED"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


class NumberStatus(str, Enum):
    PENDING = "PENDING"
    PORTING = "PORTING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    FAILED = "FAILED"
    RELEASED = "RELEASED"


class ConsentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class MessageStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    QUEUED = "QUEUED"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    UNDELIVERED = "UNDELIVERED"
    FAILED = "FAILED"
    FILTERED = "FILTERED"
    STALE_CANCELLED = "STALE_CANCELLED"


class FeedbackStatus(str, Enum):
    RECORDED = "RECORDED"
    APPLIED = "APPLIED"


class Account(TypedDict, total=False):
    id: str
    name: str
    plan_tier: str
    country_code: str
    suspend_reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Brand(TypedDict, total=False):
    id: str
    account_id: str
    legal_name: str
    tax_id: str
    business_type: str
    address_line1: str
    city: str
    region_code: str
    postal_code: str
    country_code: str
    website_url: str
    opt_in_mechanism: str
    identity_score: int
    resubmission_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict, total=False):
    id: str
    account_id: str
    brand_id: str
    use_case: str
    description: str
    sample_messages: List[str]
    help_message: str
    stop_message: str
    path_kind: str
    trust_score: int
    allocated_mps: int
    rejection_reason_code: str
    rejected_cycle_count: int
    recurring_fee_last_charge_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SenderNumber(TypedDict, total=False):
    id: str
    account_id: str
    campaign_id: str
    e164: str
    phone_number: str
    number_type: str
    country_code: str
    provisioning_source: str
    port_phone_number: str
    port_letter_of_agency: str
    port_losing_carrier: str
    base_mps: int
    suspended_reason: str
    port_requested_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsentRecord(TypedDict, total=False):
    id: str
    account_id: str
    brand_id: str
    phone_number: str
    evidence_url: str
    evidence_text: str
    captured_at: str
    retention_expires_at: str
    consent_method: str
    revoked_at: Optional[str]
    revoked_by_keyword: str
    status: str
    created_at: str


class Message(TypedDict, total=False):
    id: str
    account_id: str
    campaign_id: str
    sender_number_id: str
    to_number: str
    consent_record_id: str
    body: str
    carrier_code: str
    segments: int
    queued_at: Optional[str]
    queued_run_index: int
    failed_error_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FeedbackEvent(TypedDict, total=False):
    id: str
    account_id: str
    campaign_id: str
    message_id: str
    kind: str
    keyword: str
    to_number: str
    status: str
    created_at: str


class Charge(TypedDict, total=False):
    id: str
    account_id: str
    kind: str
    reference_type: str
    reference_id: str
    amount_cents: int
    currency: str
    status: str
    created_at: str


class DailySnapshot(TypedDict, total=False):
    id: str
    account_id: str
    campaign_id: str
    day_utc: str
    attempted: int
    delivered: int
    blocked: int
    spam: int
    delivery_rate_pct: float
    block_rate_bps: int
    spam_rate_bps: int
    created_at: str


class OpsRun(TypedDict, total=False):
    id: str
    account_id: str
    run_index: int
    executed_at: str
    messages_dequeued: int
    messages_stale_cancelled: int
    recurring_fees_charged: int
    number_fees_charged: int
    created_at: str
