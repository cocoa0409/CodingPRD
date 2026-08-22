"""Domain types for the Brand Inspection Board API.

Entity shapes, status enumerations and the role enumeration, all named exactly
as the PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    LIVESTOCK_OWNER = "LivestockOwner"
    FIELD_INSPECTOR = "FieldInspector"
    BRAND_RECORDER = "BrandRecorder"
    FEE_ADMINISTRATOR = "FeeAdministrator"
    THEFT_INVESTIGATOR = "TheftInvestigator"
    BOARD_ADMIN = "BoardAdmin"


# ─── Enumerations ─────────────────────────────────────────────────────────────

class OwnerStanding(str, Enum):
    GOOD = "GOOD"
    SUSPENDED = "SUSPENDED"


class IntakeStatus(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"


class InspectorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class ApplicationType(str, Enum):
    NEW = "NEW"
    TRANSFER = "TRANSFER"
    RENEWAL = "RENEWAL"


class PositionCode(str, Enum):
    LEFT_RIB = "LEFT_RIB"
    RIGHT_RIB = "RIGHT_RIB"
    LEFT_HIP = "LEFT_HIP"
    RIGHT_HIP = "RIGHT_HIP"
    LEFT_SHOULDER = "LEFT_SHOULDER"
    RIGHT_SHOULDER = "RIGHT_SHOULDER"


class SpeciesClass(str, Enum):
    CATTLE = "CATTLE"
    HORSE = "HORSE"
    SHEEP = "SHEEP"


class BrandApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_EXAMINATION = "UNDER_EXAMINATION"
    RETURNED_FOR_CORRECTION = "RETURNED_FOR_CORRECTION"
    CONFLICT_HOLD = "CONFLICT_HOLD"
    RECORDED = "RECORDED"
    REJECTED = "REJECTED"


class BrandRegistrationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    GRACE = "GRACE"
    ENCUMBERED = "ENCUMBERED"
    LAPSED = "LAPSED"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class ConflictGrounds(str, Enum):
    PRIOR_USE = "PRIOR_USE"
    DECEPTIVE_SIMILARITY = "DECEPTIVE_SIMILARITY"
    RECORDING_ERROR = "RECORDING_ERROR"


class BrandConflictClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_ADJUDICATION = "UNDER_ADJUDICATION"
    SUSTAINED = "SUSTAINED"
    DISMISSED = "DISMISSED"


class ClaimDecision(str, Enum):
    SUSTAIN = "SUSTAIN"
    DISMISS = "DISMISS"


class InspectionPurpose(str, Enum):
    SALE = "SALE"
    MOVEMENT = "MOVEMENT"
    SLAUGHTER = "SLAUGHTER"


class ScheduleStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    IN_FIELD = "IN_FIELD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class FeeStatus(str, Enum):
    UNASSESSED = "UNASSESSED"
    ASSESSED = "ASSESSED"
    DELINQUENT = "DELINQUENT"
    REMITTED = "REMITTED"
    WAIVED = "WAIVED"


class LotStatus(str, Enum):
    PRESENTED = "PRESENTED"
    VERIFIED = "VERIFIED"
    HELD = "HELD"
    VOIDED = "VOIDED"


class MatchStatus(str, Enum):
    UNCHECKED = "UNCHECKED"
    MATCHED = "MATCHED"
    MISMATCHED = "MISMATCHED"
    UNMATCHED = "UNMATCHED"
    UNVERIFIABLE = "UNVERIFIABLE"


class Disposition(str, Enum):
    NONE = "NONE"
    CLEARED = "CLEARED"
    ESTRAY_HOLD = "ESTRAY_HOLD"
    THEFT_REFERRAL = "THEFT_REFERRAL"


class Finding(str, Enum):
    MATCH_CONFIRMED = "MATCH_CONFIRMED"
    BRAND_MISMATCH = "BRAND_MISMATCH"
    NO_LEGIBLE_BRAND = "NO_LEGIBLE_BRAND"


class EstrayCaseStatus(str, Enum):
    IMPOUNDED = "IMPOUNDED"
    CLAIM_FILED = "CLAIM_FILED"
    AUCTION_SCHEDULED = "AUCTION_SCHEDULED"
    SOLD = "SOLD"
    RELEASED_TO_CLAIMANT = "RELEASED_TO_CLAIMANT"
    PROCEEDS_DISBURSED = "PROCEEDS_DISBURSED"
    FORFEITED_TO_BOARD = "FORFEITED_TO_BOARD"


class EstrayClaimDecision(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class DistributionVariant(str, Enum):
    NONE = "NONE"
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class TheftInvestigationStatus(str, Enum):
    OPENED = "OPENED"
    REFERRED = "REFERRED"
    CLOSED = "CLOSED"


class TheftOutcome(str, Enum):
    PENDING = "PENDING"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNFOUNDED = "UNFOUNDED"


class FeeRemittanceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RECONCILED = "RECONCILED"
    SHORT_PAID = "SHORT_PAID"


# ─── Entity shapes ────────────────────────────────────────────────────────────
# Records carrying id + created_at + updated_at + version.

class Owner(TypedDict):
    id: str
    legal_name: str
    mailing_state: str
    contact_email: str
    standing: str
    posted_arrears_cents: int
    projected_arrears_cents: int
    suspended_since: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Territory(TypedDict):
    id: str
    territory_code: str
    state_code: str
    travel_surcharge_cents: int
    impound_capacity_head: int
    impound_current_head: int
    intake_status: str
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict):
    id: str
    badge_number: str
    home_territory_id: str
    certification_expires_on: str
    max_daily_assignments: int
    status: str
    active_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class BrandApplication(TypedDict):
    id: str
    owner_id: str
    application_type: str
    prior_registration_id: Optional[str]
    brand_symbol: str
    position_code: str
    species_class: str
    state_code: str
    documented_prior_use_years: int
    prior_use_affidavit_on_file: bool
    original_filed_at: str
    effective_priority_at: str
    correction_rounds: int
    status: str
    examined_by_user_id: Optional[str]
    recorded_by_user_id: Optional[str]
    assessed_filing_fee_cents: int
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BrandRegistration(TypedDict):
    id: str
    owner_id: str
    source_application_id: str
    brand_symbol: str
    position_code: str
    species_class: str
    state_code: str
    recorded_at: str
    expires_on: str
    effective_priority_at: str
    priority_rank: int
    status: str
    superseded_by_registration_id: Optional[str]
    encumbrance_count: int
    created_at: str
    updated_at: str
    version: int


class BrandConflictClaim(TypedDict):
    id: str
    claimant_owner_id: str
    respondent_registration_id: str
    contested_application_id: Optional[str]
    grounds: str
    status: str
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InspectionOrder(TypedDict):
    id: str
    owner_id: str
    territory_id: str
    inspector_id: Optional[str]
    remittance_id: Optional[str]
    inspection_purpose: str
    requested_window_start_at: str
    requested_window_end_at: str
    scheduled_start_at: Optional[str]
    scheduled_end_at: Optional[str]
    schedule_status: str
    fee_status: str
    assessed_fee_cents: int
    fee_due_on: Optional[str]
    hold_flag: bool
    head_count_presented: int
    created_at: str
    updated_at: str
    version: int


class AnimalLot(TypedDict):
    id: str
    inspection_order_id: str
    brand_registration_id: Optional[str]
    bill_of_sale_id: Optional[str]
    species_class: str
    head_count: int
    earmark_code: Optional[str]
    lot_status: str
    match_status: str
    disposition: str
    created_at: str
    updated_at: str
    version: int


class EstrayCase(TypedDict):
    id: str
    animal_lot_id: str
    territory_id: str
    claimant_owner_id: Optional[str]
    head_count: int
    impounded_at: str
    statutory_release_on: str
    status: str
    estimated_gross_cents: Optional[int]
    gross_proceeds_cents: Optional[int]
    sale_at: Optional[str]
    care_cost_cents: int
    handling_fee_cents: int
    claimant_residual_cents: int
    board_forfeiture_cents: int
    distribution_variant: str
    claim_denied_count: int
    created_at: str
    updated_at: str
    version: int


class TheftInvestigation(TypedDict):
    id: str
    animal_lot_id: str
    brand_registration_id: str
    opened_at: str
    status: str
    outcome: str
    referral_agency: Optional[str]
    reopen_count: int
    opened_by_user_id: Optional[str]
    closed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeeRemittance(TypedDict):
    id: str
    owner_id: str
    amount_cents: int
    covered_order_ids: List[str]
    status: str
    applied_cents: int
    shortfall_cents: int
    created_at: str
    updated_at: str
    version: int


# A bill of sale is immutable once written: it carries only id and created_at,
# with no updated_at and no version (PRD §2.4).
class BillOfSale(TypedDict):
    id: str
    seller_owner_id: str
    buyer_owner_id: str
    document_number: str
    sale_date: str
    head_count: int
    species_class: str
    brand_symbol_declared: Optional[str]
    created_at: str


class OwnerStatement(TypedDict):
    owner_id: str
    standing: str
    posted_arrears_cents: int
    projected_arrears_cents: int
    open_order_count: int
    delinquent_order_count: int
