"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1 — exactly six roles)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    STATE_PROGRAM_OFFICER = "StateProgramOfficer"
    AFFILIATE_COORDINATOR = "AffiliateCoordinator"
    ADVISORY_COMMITTEE_MEMBER = "AdvisoryCommitteeMember"
    PUBLISHER_OPS = "PublisherOps"
    MAIL_OPS = "MailOps"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------
class AgreementStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class EnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNDELIVERABLE_HOLD = "UNDELIVERABLE_HOLD"
    GRADUATED = "GRADUATED"
    UNENROLLED = "UNENROLLED"
    TRANSFERRED_OUT = "TRANSFERRED_OUT"


class UnenrollReason(str, Enum):
    MOVED_OUT_OF_AREA = "MOVED_OUT_OF_AREA"
    UNDELIVERABLE = "UNDELIVERABLE"


class AddressChangeStatus(str, Enum):
    PENDING = "PENDING"
    APPLIED_IN_AREA = "APPLIED_IN_AREA"
    APPLIED_TRANSFER = "APPLIED_TRANSFER"
    APPLIED_UNENROLLED = "APPLIED_UNENROLLED"
    REJECTED = "REJECTED"


class AgeBand(str, Enum):
    INFANT = "INFANT"    # 0-11 months
    TODDLER = "TODDLER"  # 12-23 months
    TWO = "TWO"          # 24-35 months
    THREE = "THREE"      # 36-47 months
    FOUR = "FOUR"        # 48-59 months


class SelectionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    LOCKED = "LOCKED"


class PrintOrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"


class WaveStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    MANIFESTED = "MANIFESTED"
    RECONCILED = "RECONCILED"


class ItemStatus(str, Enum):
    MAILED = "MAILED"
    DELIVERED = "DELIVERED"
    RETURNED_UNDELIVERABLE = "RETURNED_UNDELIVERABLE"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    ADJUSTED = "ADJUSTED"
    PAID = "PAID"


class DisputeOutcome(str, Enum):
    OPEN = "OPEN"
    RESOLVE_OVERRULED = "RESOLVE_OVERRULED"
    RESOLVE_UPHELD = "RESOLVE_UPHELD"


class AddressChangeOutcome(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


# ---------------------------------------------------------------------------
# Shared sub-object (PRD §3.3 / §3.4)
# ---------------------------------------------------------------------------
class MailingAddress(TypedDict):
    line1: str
    city: str
    region: str
    postal_code: str
    country: str


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.5: every resource carries id, created_at,
# updated_at, version)
# ---------------------------------------------------------------------------
class StateProgram(TypedDict):
    id: str
    state_code: str
    name: str
    funding_share_bp: int
    max_state_share_per_book_cents: int
    created_at: str
    updated_at: str
    version: int


class Affiliate(TypedDict):
    id: str
    name: str
    state_program_id: str
    postal_prefixes: List[str]
    contact_email: str
    operative: bool
    enrolled_count: int
    created_at: str
    updated_at: str
    version: int


class AffiliateAgreement(TypedDict):
    id: str
    affiliate_id: str
    effective_from: str
    effective_to: str
    local_fundraising_commitment_cents: int
    status: str
    decided_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PopulationStat(TypedDict):
    id: str
    affiliate_id: str
    effective_year: int
    eligible_population: int
    created_at: str
    updated_at: str
    version: int


class Child(TypedDict):
    id: str
    affiliate_id: str
    full_name: str
    family_name: str
    birth_date: str
    mailing_address: MailingAddress
    postal_prefix: str
    registered_month: str
    enrollment_status: str
    unenroll_reason: Optional[str]
    consecutive_returns: int
    transfer_source_child_id: Optional[str]
    expected_final_mailing_month: str
    created_at: str
    updated_at: str
    version: int


class AddressChange(TypedDict):
    id: str
    child_id: str
    new_address: MailingAddress
    new_postal_prefix: str
    status: str
    decided_by: Optional[str]
    resulting_child_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Title(TypedDict):
    id: str
    title_name: str
    author: str
    age_band: str
    available_from_month: str
    available_until_month: str
    stock_on_hand: int
    created_at: str
    updated_at: str
    version: int


class AgeBandSelection(TypedDict):
    id: str
    mailing_month: str
    age_band: str
    title_id: str
    status: str
    proposed_by: str
    approved_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PrintOrder(TypedDict):
    id: str
    selection_id: str
    quantity: int
    is_reprint: bool
    production_month: str
    status: str
    unit_cents: Optional[int]
    plate_fee_cents: Optional[int]
    total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class MailingWave(TypedDict):
    id: str
    mailing_month: str
    status: str
    manifested_item_count: int
    returned_item_count: int
    created_at: str
    updated_at: str
    version: int


class MailingItem(TypedDict):
    id: str
    wave_id: str
    mailing_month: str
    child_id: str
    affiliate_id: str
    selection_id: str
    age_band: str
    status: str
    billable: bool
    created_at: str
    updated_at: str
    version: int


class AffiliateInvoice(TypedDict):
    id: str
    affiliate_id: str
    wave_id: str
    billing_month: str
    status: str
    item_count: int
    gross_cents: int
    state_share_cents: int
    local_share_cents: int
    credit_memo_cents: int
    pricing_variant: str
    created_at: str
    updated_at: str
    version: int


class PenetrationReport(TypedDict):
    affiliate_id: str
    month: str
    enrolled_count: int
    eligible_population: int
    population_stat_year: Optional[int]
    penetration_snapshot_bp: Optional[int]
    trailing_12_unique_children: int
    penetration_trailing_12_bp: Optional[int]


class ClockResponse(TypedDict):
    current_utc: str
    graduated_child_ids: List[str]
    expired_agreement_ids: List[str]


__all__ = [
    "UserRole",
    "AgreementStatus",
    "EnrollmentStatus",
    "UnenrollReason",
    "AddressChangeStatus",
    "AgeBand",
    "SelectionStatus",
    "PrintOrderStatus",
    "WaveStatus",
    "ItemStatus",
    "InvoiceStatus",
    "DisputeOutcome",
    "AddressChangeOutcome",
    "MailingAddress",
    "StateProgram",
    "Affiliate",
    "AffiliateAgreement",
    "PopulationStat",
    "Child",
    "AddressChange",
    "Title",
    "AgeBandSelection",
    "PrintOrder",
    "MailingWave",
    "MailingItem",
    "AffiliateInvoice",
    "PenetrationReport",
    "ClockResponse",
]
