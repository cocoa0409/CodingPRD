"""Domain types: entity TypedDicts, status enums and the role enum.

Entities that carry common fields expose ``id``, ``created_at``, ``updated_at``
and ``version``.  Configuration records — the subscription tier and the benefit
network — carry only ``id`` and ``created_at``.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class StudioStatus(str, Enum):
    TRIAL = "TRIAL"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class SubscriptionStatus(str, Enum):
    TRIAL = "TRIAL"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    GRACE = "GRACE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class DunningStage(str, Enum):
    CURRENT = "CURRENT"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class DataOwnershipState(str, Enum):
    OWNED = "OWNED"
    PORTABILITY_PENDING = "PORTABILITY_PENDING"
    PORTABILITY_GRANTED = "PORTABILITY_GRANTED"
    EXPORT_CLOSED = "EXPORT_CLOSED"


class StaffRole(str, Enum):
    INSTRUCTOR = "INSTRUCTOR"
    FRONT_DESK = "FRONT_DESK"
    MANAGER = "MANAGER"


class StaffStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUBSTITUTE_ONLY = "SUBSTITUTE_ONLY"
    INACTIVE = "INACTIVE"


class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    PORTABILITY_HOLD = "PORTABILITY_HOLD"
    PORTED = "PORTED"
    ANONYMIZED = "ANONYMIZED"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED_BY_STUDIO = "CANCELLED_BY_STUDIO"


class FullnessPosture(str, Enum):
    OPEN = "OPEN"
    WAITLIST_ONLY = "WAITLIST_ONLY"
    FULL = "FULL"
    CANCELLED = "CANCELLED"


class PromoOfferState(str, Enum):
    NONE = "NONE"
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class BookingChannel(str, Enum):
    STUDIO = "STUDIO"
    MARKETPLACE = "MARKETPLACE"


class PaymentSource(str, Enum):
    DROP_IN = "DROP_IN"
    MEMBERSHIP = "MEMBERSHIP"
    CLASS_PACK = "CLASS_PACK"
    BENEFIT_NETWORK = "BENEFIT_NETWORK"


class BookingStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_IN = "CHECKED_IN"
    NO_SHOW = "NO_SHOW"
    ATTENDED = "ATTENDED"
    CANCELLED = "CANCELLED"
    LATE_CANCELLED = "LATE_CANCELLED"
    WAITLISTED = "WAITLISTED"


class FeeStatus(str, Enum):
    NONE = "NONE"
    CHARGED = "CHARGED"
    PAYROLL_DEDUCTED = "PAYROLL_DEDUCTED"
    WAIVED = "WAIVED"


class ClaimStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    DENIED = "DENIED"


class WaitlistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    STANDBY = "STANDBY"
    OFFERED = "OFFERED"
    CLAIMED = "CLAIMED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class PositionMode(str, Enum):
    QUEUED = "QUEUED"
    STANDBY_ANY = "STANDBY_ANY"


class MembershipStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    PAST_DUE = "PAST_DUE"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ClassPackStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    DEPLETED = "DEPLETED"
    FROZEN = "FROZEN"


class CommissionStatus(str, Enum):
    ACCRUED = "ACCRUED"
    PAID = "PAID"
    REVERSED = "REVERSED"


class PayrollPeriodStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"


class PortabilityStatus(str, Enum):
    PENDING = "PENDING"
    OBJECTED = "OBJECTED"
    RESOLVED_RELEASE = "RESOLVED_RELEASE"
    RESOLVED_DENIED = "RESOLVED_DENIED"
    EXPORT_ISSUED = "EXPORT_ISSUED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class Tier(str, Enum):
    STARTER = "STARTER"
    GROWTH = "GROWTH"
    ENTERPRISE = "ENTERPRISE"


class BillingPeriod(str, Enum):
    MONTHLY = "MONTHLY"
    ANNUAL = "ANNUAL"


class PayrollCapMode(str, Enum):
    BONUS_OUTSIDE_CAP = "BONUS_OUTSIDE_CAP"
    BONUS_INSIDE_CAP = "BONUS_INSIDE_CAP"


class ExpiryScheme(str, Enum):
    NONE = "NONE"
    SEASONAL = "SEASONAL"
    PROMOTIONAL = "PROMOTIONAL"


class UserRole(str, Enum):
    OPERATOR_ONLY = "OperatorOnly"
    PLATFORM_ADMIN = "PlatformAdmin"
    STUDIO_OWNER = "StudioOwner"
    CLIENT = "Client"
    STAFF_MEMBER = "StaffMember"
    ANONYMOUS = "Anonymous"


class _Common(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Studio(_Common):
    legal_name: str
    home_state_code: str
    subscription_id: str
    subscription_tier: str
    feature_gates: dict
    client_roster_count: int
    outstanding_balance_cents: int
    payroll_cap_mode: str
    status: str
    suspension_reason: Optional[str]
    data_ownership_state: str


class SubscriptionTier(TypedDict):
    """Configuration record: only id and created_at, never updated_at/version."""
    id: str
    created_at: str
    tier: str
    monthly_fee_cents: int
    tier_rank: int
    included_staff_seats: int
    seat_overage_fee_cents: int
    marketplace_listing_enabled: bool
    staff_payroll_enabled: bool
    instructor_substitution_enabled: bool
    waitlist_auto_promotion_enabled: bool
    crm_client_export_enabled: bool
    marketplace_commission_bps: int


class BusinessSubscription(_Common):
    studio_id: str
    tier: str
    billing_period: str
    monthly_fee_cents_snapshot: int
    renewal_epoch: int
    renewal_due_at: str
    grace_until: str
    dunning_stage: str
    status: str
    staff_seat_count: int
    seat_overage_count: int
    payroll_hold: bool


class StaffMember(_Common):
    studio_id: str
    full_name: str
    staff_role: str
    primary_class_template_id: Optional[str]
    substitute_class_template_ids: List[str]
    commission_rate_bps: int
    status: str
    accrued_commission_cents: int


class Client(_Common):
    home_studio_id: str
    display_name: str
    email: str
    home_state_code: str
    status: str
    no_show_strike_count: int
    late_cancel_count: int
    outstanding_fee_cents: int


class ClassTemplate(_Common):
    studio_id: str
    name: str
    duration_minutes: int
    base_price_cents: int
    default_capacity: int
    credit_cost: int
    is_off_peak: bool
    buffer_minutes: int


class ClassSession(_Common):
    studio_id: str
    class_template_id: str
    instructor_staff_id: str
    room_code: str
    start_at: str
    end_at: str
    capacity: int
    seats_taken: int
    seats_held: int
    fullness_posture: str
    list_price_cents: int
    marketplace_price_cents: int
    price_version: int
    promo_seats_allocated: int
    promo_seats_used: int
    promo_discount_bps: int
    promo_valid_from: Optional[str]
    promo_valid_to: Optional[str]
    promo_offer_state: str
    promo_cascade_class_session_id: Optional[str]
    payroll_period_id: Optional[str]
    status: str


class Booking(_Common):
    studio_id: str
    client_id: str
    class_session_id: str
    channel: str
    payment_source: str
    membership_id: Optional[str]
    class_pack_id: Optional[str]
    benefit_network_code: Optional[str]
    booking_fee_cents: int
    fee_status: str
    commission_base_cents: int
    benefit_claim_amount_cents: int
    benefit_claim_status: str
    is_promotional_seat: bool
    creation_seq: int
    reminders_sent: int
    status: str


class WaitlistEntry(_Common):
    studio_id: str
    class_session_id: str
    client_id: str
    joined_at: str
    offer_expires_at: Optional[str]
    status: str
    position_mode: str
    raw_sequence_no: int
    effective_sequence: int
    promoted_booking_id: Optional[str]


class Membership(_Common):
    studio_id: str
    client_id: str
    plan_name: str
    monthly_fee_cents: int
    included_credits_per_cycle: int
    minimum_term_months: int
    freeze_allowed: bool
    freeze_max_days_per_cycle: int
    billing_anchor_day: int
    current_period_index: int
    next_billing_at: str
    auto_renew: bool
    freeze_start_at: Optional[str]
    freeze_resume_at: Optional[str]
    freeze_days_used: int
    prorated_fee_cents: int
    open_balance_cents: int
    status: str


class ClassPack(_Common):
    studio_id: str
    client_id: str
    pack_size: int
    credits_remaining: int
    purchased_at: str
    expires_at: str
    extension_days_used: int
    status: str
    pending_expiry_grace_until: Optional[str]


class BenefitNetwork(TypedDict):
    """Configuration record: only id and created_at, never updated_at/version."""
    id: str
    created_at: str
    network_code: str
    name: str
    per_visit_allowance_cents: int
    reimburse_full_list_price: bool
    remit_days_after_visit: int
    claim_denial_window_hours: int


class CommissionEntry(_Common):
    studio_id: str
    staff_member_id: str
    payroll_period_id: str
    booking_id: str
    booking_channel: str
    base_amount_cents: int
    rate_bps: int
    commission_cents: int
    status: str
    reversal_reason: Optional[str]


class PayrollPeriod(_Common):
    studio_id: str
    period_index: int
    start_date: str
    end_date: str
    accrued_commission_cents: int
    paid_commission_cents: int
    reversal_correction_cents: int
    status: str


class ClientPortabilityRequest(_Common):
    studio_id: str
    requesting_client_id: str
    dispute_reason: str
    requested_at: str
    decided_at: Optional[str]
    export_grant_id: Optional[str]
    export_manifest: Optional[dict]
    export_download_count: int
    status: str