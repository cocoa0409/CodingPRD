"""Domain types: entity TypedDicts, status enums, role enum.

All entities here carry the common system-managed fields (id, created_at,
updated_at, version) described in PRD section 2.5.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    AD_OPS = "AdOps"
    PUBLISHER = "Publisher"
    VIEWER = "Viewer"
    TV_MANUFACTURER = "TvManufacturer"


class PublisherStanding(str, Enum):
    GOOD = "GOOD"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class RevenueTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIER = "PREMIER"


class BillingModel(str, Enum):
    GROSS_SHARE = "GROSS_SHARE"
    NET_OF_FEES = "NET_OF_FEES"


class ChannelStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    CERTIFIED = "CERTIFIED"
    PUBLISHED = "PUBLISHED"
    SUSPENDED = "SUSPENDED"
    REMOVED = "REMOVED"


class ChannelVersionReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    PASSED = "PASSED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


class ViewerAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class AdConsent(str, Enum):
    PERSONALIZED = "PERSONALIZED"
    NON_PERSONALIZED = "NON_PERSONALIZED"
    OPTED_OUT = "OPTED_OUT"


class SubscriptionBillingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class SubscriptionEntitlementStatus(str, Enum):
    ENTITLED = "ENTITLED"
    REVOKED = "REVOKED"


class AdSlotGrantStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class AdCampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PlacementBookingStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class LicenseStatus(str, Enum):
    LICENSED = "LICENSED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class DeviceModelCertStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    LAB_TESTING = "LAB_TESTING"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"
    DECERTIFIED = "DECERTIFIED"


class DeviceModelUpdateCompliance(str, Enum):
    COMPLIANT = "COMPLIANT"
    GRACE = "GRACE"
    OVERDUE = "OVERDUE"


class RecoveryPolicy(str, Enum):
    STRAIGHT_LINE = "STRAIGHT_LINE"
    MONETIZATION = "MONETIZATION"


class LabBookingStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OsUpdateStatus(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    ROLLING = "ROLLING"
    WITHDRAWN = "WITHDRAWN"


class DeviceUnitStatus(str, Enum):
    MANUFACTURED = "MANUFACTURED"
    SOLD = "SOLD"
    ACTIVATED = "ACTIVATED"
    DEACTIVATED = "DEACTIVATED"


class RevenueStatementStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"


class DisputeStatus(str, Enum):
    FILED = "FILED"
    TRIAGE = "TRIAGE"
    EVIDENCE = "EVIDENCE"
    DECIDED = "DECIDED"
    APPEALED = "APPEALED"
    CLOSED = "CLOSED"


class DisputeSubjectType(str, Enum):
    CHANNEL_REMOVAL = "CHANNEL_REMOVAL"
    STATEMENT = "STATEMENT"


class DisputeDecision(str, Enum):
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class TargetingMode(str, Enum):
    CONTEXTUAL = "CONTEXTUAL"
    PERSONALIZED = "PERSONALIZED"


class Publisher(TypedDict):
    id: str
    legal_name: str
    default_ad_share_bps: int
    billing_model: str
    standing: str
    revenue_tier: str
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Channel(TypedDict):
    id: str
    publisher_id: str
    name: str
    category: str
    content_rating: str
    status: str
    active_version_id: Optional[str]
    policy_hold: bool
    removed_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChannelVersion(TypedDict):
    id: str
    channel_id: str
    version_label: str
    technical_checklist: dict
    review_status: str
    failure_codes: List[str]
    created_at: str
    updated_at: str
    version: int


class ViewerAccount(TypedDict):
    id: str
    email: str
    ad_consent: str
    data_retention_opt_out: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    viewer_id: str
    channel_id: str
    price_cents: int
    billing_status: str
    entitlement_status: str
    period_start: str
    refunded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdSlotGrant(TypedDict):
    id: str
    channel_id: str
    period: str
    total_slots: int
    publisher_share_bps: int
    publisher_slots: int
    platform_slots: int
    ad_gross_cents: int
    publisher_payout_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AdCampaign(TypedDict):
    id: str
    publisher_id: str
    channel_id: str
    flight_start: str
    flight_end: str
    budget_cents: int
    targeting_mode: str
    spent_cents: int
    impressions_delivered: int
    expected_spend_cents: int
    pacing_delta_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PlacementBooking(TypedDict):
    id: str
    campaign_id: str
    slot_code: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TvManufacturer(TypedDict):
    id: str
    legal_name: str
    royalty_per_device_cents: int
    license_status: str
    created_at: str
    updated_at: str
    version: int


class DeviceModel(TypedDict):
    id: str
    manufacturer_id: str
    model_code: str
    recovery_policy: str
    cert_status: str
    update_compliance: str
    created_at: str
    updated_at: str
    version: int


class LabBooking(TypedDict):
    id: str
    manufacturer_id: str
    device_model_id: str
    bench_code: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OsUpdate(TypedDict):
    id: str
    version_tag: str
    mandatory: bool
    rollout_start: str
    compliance_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DeviceUnit(TypedDict):
    id: str
    device_model_id: str
    viewer_id: Optional[str]
    serial_number: str
    hardware_cost_cents: int
    sale_price_cents: int
    subsidy_cents: int
    subsidy_recovered_cents: int
    subsidy_written_off_cents: int
    subsidy_outstanding_cents: int
    os_version_tag: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RevenueStatement(TypedDict):
    id: str
    publisher_id: str
    period: str
    subscription_gross_cents: int
    refund_cents: int
    charge_count: int
    applied_tier: Optional[str]
    applied_fee_bps: Optional[int]
    sub_payout_cents: int
    platform_sub_fee_cents: int
    ad_gross_cents: int
    ad_payout_cents: int
    platform_ad_fee_cents: int
    placement_spend_cents: int
    net_payout_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    publisher_id: str
    subject_type: str
    channel_id: Optional[str]
    statement_id: Optional[str]
    reason: str
    status: str
    decision: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
