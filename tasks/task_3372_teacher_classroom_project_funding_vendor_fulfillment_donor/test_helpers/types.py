"""Typed shapes for every resource the API returns.

Each TypedDict mirrors the field list the PRD declares for that resource.
ThankYouPackage is the one append-only resource: it carries only ``id`` and
``created_at``, so its shape deliberately omits ``updated_at`` and ``version``;
every other resource carries the full common quartet.
"""

from enum import Enum
from typing import Any, List, Optional, TypedDict


# ── Roles (PRD section 2.1) ────────────────────────────────────────────────

class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    TEACHER = "Teacher"
    REVIEWER = "Reviewer"
    DONOR = "Donor"
    VENDOR = "Vendor"
    PLATFORM_ADMIN = "PlatformAdmin"


# ── Status enums ───────────────────────────────────────────────────────────

class EmploymentStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    SUSPENDED = "SUSPENDED"


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CatalogItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    VETTING = "VETTING"
    RETURNED = "RETURNED"
    REJECTED = "REJECTED"
    FUNDING = "FUNDING"
    FUNDED = "FUNDED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    FULFILLED = "FULFILLED"
    CLOSED = "CLOSED"


class DonationStatus(str, Enum):
    CAPTURED = "CAPTURED"
    CHOICE_PENDING = "CHOICE_PENDING"
    REFUNDED = "REFUNDED"
    REALLOCATED = "REALLOCATED"


class DonationKind(str, Enum):
    DONOR = "DONOR"
    EQUITY_GRANT = "EQUITY_GRANT"


class RefundReason(str, Enum):
    EXPIRED_CHOICE = "EXPIRED_CHOICE"
    EXPIRED_AUTO = "EXPIRED_AUTO"
    FRAUD_CLAWBACK = "FRAUD_CLAWBACK"


class MatchCampaignStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    CLOSED = "CLOSED"


class PurchaseOrderStatus(str, Enum):
    ISSUED = "ISSUED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    DIVERSION_REPORTED = "DIVERSION_REPORTED"
    CANCELLED = "CANCELLED"


class ThankYouPackageStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"


class FraudCaseStatus(str, Enum):
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class EquityFundStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"
    CLOSED = "CLOSED"


# ── Resource shapes ────────────────────────────────────────────────────────

class School(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    state_code: str
    district: str
    poverty_pct: float
    ell_pct: float
    equity_score_banded: int
    equity_score_weighted: float


class Teacher(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    school_id: str
    full_name: str
    email: str
    subjects_taught: List[str]
    employment_status: str


class Vendor(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    ship_from_state: str
    contact_email: str
    status: str


class CatalogItem(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    vendor_id: str
    sku: str
    name: str
    category: str
    subject_tags: List[str]
    unit_price_cents: int
    weight_oz: int
    shipping_zone: str
    fragile: bool
    max_quantity_per_project: Optional[int]
    status: str


class Project(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    teacher_id: str
    school_id: str
    title: str
    description: str
    subject: str
    grade_band: str
    funding_window_days: int
    status: str
    provisional_total_cents: Optional[int]
    pinned_items_total_cents: Optional[int]
    pinned_shipping_total_cents: Optional[int]
    goal_cents: Optional[int]
    funded_cents: int
    funding_started_at: Optional[str]
    funding_deadline: Optional[str]
    screened_by_id: Optional[str]
    vetted_by_id: Optional[str]


class ProjectItem(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    catalog_item_id: str
    quantity: int
    pinned_unit_price_cents: Optional[int]


class Donor(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    display_name: str
    email: str
    lifetime_donated_cents: int
    lifetime_refunded_cents: int
    lifetime_reallocated_cents: int


class Donation(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    donor_id: Optional[str]
    kind: str
    amount_cents: int
    match_campaign_id: Optional[str]
    matched_cents: int
    equity_fund_id: Optional[str]
    status: str
    choice_deadline: Optional[str]
    refund_reason: Optional[str]


class MatchCampaign(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    sponsor_name: str
    match_ratio: float
    budget_cents: int
    matched_so_far_cents: int
    remaining_budget_cents: int
    min_donation_cents: int
    target_type: str
    target_value: str
    starts_at: str
    ends_at: str
    status: str


class PurchaseOrder(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    vendor_id: str
    line_items: List[Any]
    line_total_cents: int
    shipping_fee_cents: int
    status: str
    tracking_number: Optional[str]
    issued_at: str
    ship_by_due: str
    shipped_at: Optional[str]
    delivered_at: Optional[str]


class ThankYouPackage(TypedDict, total=False):
    # Append-only resource: only id + created_at are guaranteed.
    id: str
    created_at: str
    project_id: str
    status: str
    thank_you_note: Optional[str]
    impact_report: Optional[str]
    submitted_at: Optional[str]


class FraudCase(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    teacher_id: str
    project_id: str
    purchase_order_id: str
    reason: str
    status: str


class EquityFund(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    state_code: str
    subject: Optional[str]
    min_poverty_pct: float
    budget_cents: int
    remaining_cents: int
    window_start: str
    window_end: str
    status: str
