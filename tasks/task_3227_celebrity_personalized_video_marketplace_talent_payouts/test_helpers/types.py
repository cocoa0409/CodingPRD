"""Domain types: status enums, role names, and entity TypedDicts.

Every primary resource carries the common system-managed fields ``id``,
``created_at``, ``updated_at`` and ``version``; the TypedDicts below spell
out the entity-specific fields on top of those.  Status enums enumerate the
exact spellings the PRD uses so a test can compare against a name instead of
a retyped string.
"""

from enum import Enum
from typing import Any, List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────


class UserRole(str, Enum):
    TALENT = "Talent"
    BUYER = "Buyer"
    MODERATOR = "Moderator"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Status enums ─────────────────────────────────────────────────────────


class TalentStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ID_VERIFIED = "ID_VERIFIED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    SUSPENDED = "SUSPENDED"


class TalentAvailability(str, Enum):
    BOOKABLE = "BOOKABLE"
    PAUSED_AVAILABILITY = "PAUSED_AVAILABILITY"


class CommissionTier(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"


class BuyerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"


class OrderStatus(str, Enum):
    SCREENING = "SCREENING"
    DECLINED = "DECLINED"
    AWAITING_ACCEPTANCE = "AWAITING_ACCEPTANCE"
    EXPIRED = "EXPIRED"
    ACCEPTED = "ACCEPTED"
    DELIVERED = "DELIVERED"
    RE_RECORD_REQUESTED = "RE_RECORD_REQUESTED"
    CONFIRMED = "CONFIRMED"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"
    CANCELLED = "CANCELLED"


class UseType(str, Enum):
    PERSONAL = "PERSONAL"
    BUSINESS_USE = "BUSINESS_USE"
    ADVERTISING_USE = "ADVERTISING_USE"


class ModerationStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"


class ModerationDecision(str, Enum):
    CLEAR = "CLEAR"
    FLAG = "FLAG"


class ReRecordRequestStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class LicenseType(str, Enum):
    BUSINESS = "BUSINESS"
    ADVERTISING = "ADVERTISING"


class Territory(str, Enum):
    DOMESTIC = "DOMESTIC"
    GLOBAL = "GLOBAL"


class Channel(str, Enum):
    SOCIAL = "SOCIAL"
    WEB = "WEB"
    TV = "TV"
    OOH = "OOH"


class LicenseGrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class PayoutLineKind(str, Enum):
    VIDEO_EARNING = "VIDEO_EARNING"
    LICENSE_FEE_CREDIT = "LICENSE_FEE_CREDIT"
    CLAWBACK = "CLAWBACK"


class SettlementStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    SETTLED = "SETTLED"


class PayoutStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PROCESSING = "PROCESSING"
    PAID = "PAID"


class TaxDocType(str, Enum):
    W9 = "W9"
    W8BEN = "W8BEN"


class TaxDocumentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class TaxReviewDecision(str, Enum):
    VERIFY = "VERIFY"
    REJECT = "REJECT"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED_REFUND = "RESOLVED_REFUND"
    RESOLVED_PARTIAL = "RESOLVED_PARTIAL"
    RESOLVED_NO_REFUND = "RESOLVED_NO_REFUND"
    RESOLVED_BUYER_MISMATCH = "RESOLVED_BUYER_MISMATCH"


class DisputeOutcome(str, Enum):
    FULL_REFUND = "FULL_REFUND"
    PARTIAL_REFUND = "PARTIAL_REFUND"
    NO_REFUND = "NO_REFUND"
    BUYER_MISMATCH_PLATFORM_ABSORB = "BUYER_MISMATCH_PLATFORM_ABSORB"


# ─── Entity shapes ────────────────────────────────────────────────────────


class Talent(TypedDict, total=False):
    id: str
    stage_name: str
    legal_name: str
    email: str
    status: str
    personal_rate_cents: Optional[int]
    business_rate_cents: Optional[int]
    advertising_rate_cents: Optional[int]
    turnaround_hours: Optional[int]
    availability: str
    commission_tier: str
    trailing_gmv_cents: int
    pending_balance_cents: int
    paid_out_balance_cents: int
    availability_pause_count_30d: int
    identity_document_ref: Optional[str]
    identity_submitted_at: Optional[str]
    suggestion_seed_at: Optional[str]
    suggested_personal_rate_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Buyer(TypedDict, total=False):
    id: str
    email: str
    display_name: str
    is_business_account: bool
    status: str
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    talent_id: str
    buyer_id: str
    use_type: str
    occasion: str
    script_instructions: str
    recipient_name: str
    status: str
    gross_amount_cents: int
    platform_commission_cents: Optional[int]
    talent_net_cents: Optional[int]
    screening_token: str
    screening_flags: List[str]
    acceptance_deadline: Optional[str]
    delivery_deadline: Optional[str]
    delivered_at: Optional[str]
    re_record_count: int
    auto_confirm_at: Optional[str]
    refund_amount_cents: int
    platform_absorbed_cents: int
    clawback_cents: int
    created_at: str
    updated_at: str
    version: int


class Video(TypedDict, total=False):
    id: str
    order_id: str
    content_url: str
    duration_seconds: int
    version_no: int
    moderation_status: str
    flagged_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReRecordRequest(TypedDict, total=False):
    id: str
    order_id: str
    notes: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LicenseGrant(TypedDict, total=False):
    id: str
    order_id: str
    license_type: str
    territory: str
    channels: List[str]
    starts_at: str
    ends_at: str
    fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PayoutLine(TypedDict, total=False):
    id: str
    talent_id: str
    order_id: str
    kind: str
    amount_cents: int
    settlement_status: str
    payout_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict, total=False):
    id: str
    talent_id: str
    status: str
    total_cents: int
    period_start: str
    period_end: str
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TaxDocument(TypedDict, total=False):
    id: str
    talent_id: str
    doc_type: str
    tax_id_last4: str
    status: str
    submitted_at: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict, total=False):
    id: str
    order_id: str
    reason: str
    status: str
    refund_to_buyer_cents: Optional[int]
    resolution_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


# A scenario bundle: the records produced by the composite setup builders in
# fixtures.py.  Keys are named after the role each record plays.
Scenario = TypedDict(
    "Scenario",
    {
        "talent": Talent,
        "buyer": Buyer,
        "order": Order,
        "video": Video,
        "dispute": Dispute,
        "payout": Payout,
        "extra": Any,
    },
    total=False,
)
