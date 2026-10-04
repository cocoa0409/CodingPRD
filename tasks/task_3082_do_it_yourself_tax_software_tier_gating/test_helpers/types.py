"""Domain types: entity TypedDicts, status enums, role enum.

Statuses carry the exact UPPERCASE state strings used throughout PRD §3.
Catalog resources (ProductTier, FormSpec) carry only id + created_at;
every other resource additionally carries created_at, updated_at, and an
integer version (PRD §2.4).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    TAXPAYER = "Taxpayer"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    PLATFORM_OPERATOR = "PlatformOperator"


class FilingStatus(str, Enum):
    SINGLE = "SINGLE"
    MARRIED_FILING_JOINTLY = "MARRIED_FILING_JOINTLY"
    MARRIED_FILING_SEPARATELY = "MARRIED_FILING_SEPARATELY"
    HEAD_OF_HOUSEHOLD = "HEAD_OF_HOUSEHOLD"
    QUALIFYING_WIDOWER = "QUALIFYING_WIDOWER"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TierCode(str, Enum):
    FREE = "FREE"
    DELUXE = "DELUXE"
    PREMIER = "PREMIER"
    SELF_EMPLOYED = "SELF_EMPLOYED"


class SnapshotImportStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IMPORTED = "IMPORTED"
    SUPERSEDED = "SUPERSEDED"


class ReturnStatus(str, Enum):
    DRAFT = "DRAFT"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    AMENDED = "AMENDED"


class ReturnFormStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class ReturnFormSource(str, Enum):
    MANUAL = "MANUAL"
    IMPORTED = "IMPORTED"


class CarryforwardItemType(str, Enum):
    DEPRECIATION = "DEPRECIATION"
    CAPITAL_LOSS = "CAPITAL_LOSS"
    BASIS = "BASIS"
    NONE = "NONE"


class UpgradePromptStatus(str, Enum):
    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DECLINED_DOWNGRADED = "DECLINED_DOWNGRADED"
    SUPERSEDED = "SUPERSEDED"


class StateReturnStatus(str, Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    FILED = "FILED"
    REMOVED = "REMOVED"


class FilingAttemptOutcome(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class RejectionCode(str, Enum):
    R0000_SSN_MISMATCH = "R0000_SSN_MISMATCH"
    R0500_NAME_CONTROL = "R0500_NAME_CONTROL"
    R1000_DUPLICATE_FILED = "R1000_DUPLICATE_FILED"
    R2000_DEPENDENT_CLAIMED = "R2000_DEPENDENT_CLAIMED"
    R3000_MATH_ERROR = "R3000_MATH_ERROR"


class RefundTransferStatus(str, Enum):
    PENDING_DISCLOSURE = "PENDING_DISCLOSURE"
    ACTIVE = "ACTIVE"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class AccuracyClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


# --- Entity TypedDicts -------------------------------------------------------
# Catalog rows: only id + created_at (no updated_at, no version).

class ProductTier(TypedDict, total=False):
    id: str
    code: str
    price_cents: int
    state_addon_price_cents: int
    supported_forms: List[str]
    tier_rank: int
    created_at: str


class FormSpec(TypedDict, total=False):
    id: str
    code: str
    minimum_tier: str
    disqualifies_free_file: bool
    counts_toward_refund: bool
    created_at: str


class TaxpayerAccount(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    filing_status: str
    agi_cents: int
    resident_state_code: str
    accuracy_guarantee_enrolled: bool
    disclosure_accepted_version: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PriorYearReturnSnapshot(TypedDict, total=False):
    id: str
    account_id: str
    tax_year: int
    carryforward_items: List[dict]
    import_status: str
    created_at: str
    updated_at: str
    version: int


class TaxReturn(TypedDict, total=False):
    id: str
    account_id: str
    tax_year: int
    current_tier: str
    minimum_required_tier: str
    free_file_eligible: bool
    upgrade_prompt_pending: bool
    refund_transfer_selected: bool
    federal_refund_cents: int
    total_fees_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReturnForm(TypedDict, total=False):
    id: str
    return_id: str
    form_code: str
    source: str
    carryforward_item_type: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class UpgradePrompt(TypedDict, total=False):
    id: str
    return_id: str
    from_tier: str
    to_tier: str
    price_delta_cents: int
    acknowledged: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class StateReturn(TypedDict, total=False):
    id: str
    return_id: str
    state_code: str
    is_resident_state: bool
    allocation_numerator_cents: Optional[int]
    allocation_denominator_cents: Optional[int]
    residency_start_date: Optional[str]
    residency_end_date: Optional[str]
    allocated_tax_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FilingAttempt(TypedDict, total=False):
    id: str
    return_id: str
    attempt_sequence: int
    transmission_payload_hash: str
    outcome: str
    rejection_code: Optional[str]
    correction_hint: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RefundTransferAgreement(TypedDict, total=False):
    id: str
    return_id: str
    bank_partner_code: str
    service_fee_cents: int
    disclosure_version: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AccuracyClaim(TypedDict, total=False):
    id: str
    return_id: str
    claimed_error_amount_cents: int
    reviewed_error_amount_cents: Optional[int]
    reimbursement_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
