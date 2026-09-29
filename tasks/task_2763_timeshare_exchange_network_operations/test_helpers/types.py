"""Domain types for the Timeshare Exchange Network API.

Status enums, closed vocabularies and entity TypedDicts, all named exactly as
the PRD names them. Every one of the twelve record families carries
``updated_at`` and ``version`` (PRD §2.4).
"""

from enum import Enum
from typing import Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------

class UserRole(str, Enum):
    MEMBER = "Member"
    RESORT_MANAGER = "ResortManager"
    NETWORK_OPERATOR = "NetworkOperator"
    DISPUTE_ANALYST = "DisputeAnalyst"


# --------------------------------------------------------------------------
# Closed vocabularies
# --------------------------------------------------------------------------

class TierCode(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    ELITE = "ELITE"


class BandCode(str, Enum):
    PLATINUM = "PLATINUM"
    GOLD = "GOLD"
    SILVER = "SILVER"
    BRONZE = "BRONZE"


class UnitSize(str, Enum):
    STUDIO = "STUDIO"
    ONE_BR = "ONE_BR"
    TWO_BR = "TWO_BR"
    THREE_BR = "THREE_BR"


class QualityRating(str, Enum):
    GOLD_CROWN = "GOLD_CROWN"
    SILVER_CROWN = "SILVER_CROWN"
    STANDARD = "STANDARD"
    HOSPITALITY = "HOSPITALITY"


class FundingMode(str, Enum):
    DEPOSIT_FIRST = "DEPOSIT_FIRST"
    REQUEST_FIRST = "REQUEST_FIRST"


class RestorationVariant(str, Enum):
    FULL_RESTORE = "FULL_RESTORE"
    PRORATED_RESTORE = "PRORATED_RESTORE"


class DisputeSubjectType(str, Enum):
    TRADING_POWER = "TRADING_POWER"
    RESORT_QUALITY = "RESORT_QUALITY"


class DisputeOutcome(str, Enum):
    UPHELD = "UPHELD"
    DENIED = "DENIED"


class LedgerEntryType(str, Enum):
    # Power-side movements (PRD §2.7)
    DEPOSIT_CREDIT = "DEPOSIT_CREDIT"
    DEPOSIT_WITHDRAWAL_REVERSAL = "DEPOSIT_WITHDRAWAL_REVERSAL"
    DEPOSIT_EXPIRY_FORFEIT = "DEPOSIT_EXPIRY_FORFEIT"
    SETTLEMENT_ADJUSTMENT = "SETTLEMENT_ADJUSTMENT"
    EXCHANGE_DEBIT = "EXCHANGE_DEBIT"
    EXCHANGE_RESTORATION = "EXCHANGE_RESTORATION"
    RESTORATION_HAIRCUT = "RESTORATION_HAIRCUT"
    GETAWAY_LISTING_FORFEIT = "GETAWAY_LISTING_FORFEIT"
    DISPUTE_POWER_GRANT = "DISPUTE_POWER_GRANT"
    # Cash-side movements (PRD §2.7)
    DUES_PAYMENT = "DUES_PAYMENT"
    EXCHANGE_CHARGE = "EXCHANGE_CHARGE"
    EXCHANGE_CHARGE_REFUND = "EXCHANGE_CHARGE_REFUND"
    CANCELLATION_FEE = "CANCELLATION_FEE"
    REINSTATEMENT_FEE = "REINSTATEMENT_FEE"
    EXTENSION_FEE = "EXTENSION_FEE"
    GETAWAY_BOOKING_PAYMENT = "GETAWAY_BOOKING_PAYMENT"


class RelatedEntityType(str, Enum):
    DEPOSIT = "DEPOSIT"
    EXCHANGE_REQUEST = "EXCHANGE_REQUEST"
    CONFIRMATION = "CONFIRMATION"
    GETAWAY_OFFER = "GETAWAY_OFFER"
    DISPUTE = "DISPUTE"
    MEMBER = "MEMBER"


# --------------------------------------------------------------------------
# State machines
# --------------------------------------------------------------------------

class AffiliationStatus(str, Enum):
    PENDING_AFFILIATION = "PENDING_AFFILIATION"
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class EnrollmentStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class DepositStatus(str, Enum):
    BANKED = "BANKED"
    RESERVED = "RESERVED"
    USED = "USED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class RentalStatus(str, Enum):
    NOT_LISTED = "NOT_LISTED"
    LISTED_GETAWAY = "LISTED_GETAWAY"
    RENTED = "RENTED"


class ExchangeRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    WAITLISTED = "WAITLISTED"
    MATCHED = "MATCHED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    DENIED = "DENIED"


class ConfirmationStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REINSTATED = "REINSTATED"


class MatchingRunStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"


class GetawayOfferStatus(str, Enum):
    LISTED = "LISTED"
    BOOKED = "BOOKED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_DENIED = "RESOLVED_DENIED"
    WITHDRAWN = "WITHDRAWN"


ACTIVE_REQUEST_STATUSES = (
    ExchangeRequestStatus.SUBMITTED.value,
    ExchangeRequestStatus.WAITLISTED.value,
    ExchangeRequestStatus.MATCHED.value,
)

COMMITTED_DEPOSIT_STATUSES = (
    DepositStatus.BANKED.value,
    DepositStatus.RESERVED.value,
    DepositStatus.USED.value,
)


# --------------------------------------------------------------------------
# Entity shapes — all twelve families carry updated_at and version (PRD §2.4)
# --------------------------------------------------------------------------

class MembershipTier(TypedDict):
    id: str
    tier_code: str
    annual_dues_cents: int
    base_exchange_fee_cents: int
    priority_surcharge_cents: int
    priority_window_days: int
    deposit_first_bonus_pct: int
    max_active_requests: int
    cancellation_fee_cents: int
    reinstatement_fee_cents: int
    extension_fee_cents_per_month: int
    created_at: str
    updated_at: str
    version: int


class Resort(TypedDict):
    id: str
    name: str
    region_code: str
    required_annual_deposit_units: int
    initial_quality_rating: str
    units_per_size: int
    demand_index: int
    affiliation_status: str
    affiliated_on: Optional[str]
    quality_rating: str
    quality_score: Optional[str]
    review_count: int
    complaint_strikes: int
    downgrade_notches: int
    deposits_committed_count: int
    committed_nights: int
    created_at: str
    updated_at: str
    version: int


class SeasonBand(TypedDict):
    id: str
    resort_id: str
    band_code: str
    start_month_day: str
    end_month_day: str
    season_multiplier: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    email: str
    full_name: str
    tier_id: str
    home_resort_id: Optional[str]
    enrollment_status: str
    dues_paid_through: Optional[str]
    trading_power_balance: int
    wallet_credit_cents: int
    active_request_count: int
    created_at: str
    updated_at: str
    version: int


class Deposit(TypedDict):
    id: str
    member_id: str
    resort_id: str
    unit_size: str
    check_in_date: str
    occupancy_end_date: str
    season_band_code: str
    awarded_power: int
    settlement_power: Optional[int]
    restoration_haircut_power: int
    remaining_power: int
    extension_months_purchased: int
    expires_at: str
    deposit_status: str
    rental_status: str
    created_at: str
    updated_at: str
    version: int


class ExchangeRequest(TypedDict):
    id: str
    member_id: str
    requested_resort_id: str
    requested_unit_size: str
    window_start_date: str
    window_end_date: str
    deposit_id: Optional[str]
    funding_mode: str
    power_budget: int
    required_power_estimate: int
    quoted_charge_cents: int
    charge_refunded_cents: int
    status: str
    priority_score: int
    decline_count: int
    matched_deposit_id: Optional[str]
    matched_hold_expires_at: Optional[str]
    waitlisted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Confirmation(TypedDict):
    id: str
    exchange_request_id: str
    awarded_deposit_id: str
    awarded_check_in_date: str
    power_debited: int
    status: str
    cancelled_at: Optional[str]
    restoration_variant: Optional[str]
    restored_power: Optional[int]
    cancellation_fee_cents: Optional[int]
    reinstatement_fee_cents: Optional[int]
    reinstated_from_confirmation_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MatchingRun(TypedDict):
    id: str
    run_sequence: int
    as_of_utc: str
    note: Optional[str]
    status: str
    lapsed_member_count: int
    expired_deposit_count: int
    probation_resort_count: int
    expired_request_count: int
    denied_request_count: int
    matched_count: int
    waitlisted_count: int
    completed_confirmation_count: int
    getaway_listed_count: int
    created_at: str
    updated_at: str
    version: int


class GetawayOffer(TypedDict):
    id: str
    deposit_id: str
    list_price_cents: int
    urgency_discount_pct: int
    status: str
    created_by_run_id: Optional[str]
    booked_by_member_id: Optional[str]
    booked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    member_id: str
    subject_type: str
    deposit_id: Optional[str]
    resort_id: Optional[str]
    confirmation_id: Optional[str]
    narrative: str
    status: str
    round_count: int
    granted_power_adjustment: int
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ResortQualityReview(TypedDict):
    id: str
    resort_id: str
    confirmation_id: str
    cleanliness_score: int
    service_score: int
    amenities_score: int
    composite_score: str
    created_at: str
    updated_at: str
    version: int


class LedgerEntry(TypedDict):
    id: str
    member_id: str
    entry_type: str
    power_delta: int
    cash_delta_cents: int
    related_entity_type: str
    related_entity_id: str
    description: str
    created_at: str
    updated_at: str
    version: int
