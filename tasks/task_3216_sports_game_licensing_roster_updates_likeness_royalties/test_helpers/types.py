"""Domain types: entity shapes, status enums, role enum (PRD §2.1, §2.5)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    LICENSING_ADMIN = "LicensingAdmin"
    RIGHTS_OFFICER = "RightsOfficer"
    ROSTER_OPERATOR = "RosterOperator"
    ROSTER_REVIEWER = "RosterReviewer"
    LIVE_OPS_MANAGER = "LiveOpsManager"
    FINANCE_CONTROLLER = "FinanceController"
    LEAGUE_AUDITOR = "LeagueAuditor"
    UNION_AUDITOR = "UnionAuditor"
    COMPLIANCE_REVIEWER = "ComplianceReviewer"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class AthleteStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class GrantStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class SeasonStatus(str, Enum):
    PRELAUNCH = "PRELAUNCH"
    LIVE = "LIVE"
    SUNSET = "SUNSET"
    ARCHIVED = "ARCHIVED"


class BatchStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    ROLLED_BACK = "ROLLED_BACK"


class RosterEntryStatus(str, Enum):
    STAGED = "STAGED"
    APPLIED = "APPLIED"
    DROPPED = "DROPPED"


class DropStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RELEASED = "RELEASED"
    HELD = "HELD"
    ENDED = "ENDED"
    CANCELED = "CANCELED"


class WalletStatus(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class LedgerEntryStatus(str, Enum):
    POSTED = "POSTED"


class ProgramStatus(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    REGISTRATION_CLOSED = "REGISTRATION_CLOSED"
    COMPLETED = "COMPLETED"
    PAYOUT_FINALIZED = "PAYOUT_FINALIZED"
    CANCELED = "CANCELED"


class TournamentEntryStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CONFIRMED = "CONFIRMED"
    DISQUALIFIED = "DISQUALIFIED"
    REFUNDED = "REFUNDED"


class PrizeStatus(str, Enum):
    PLANNED = "PLANNED"
    PROJECTED = "PROJECTED"
    PAYABLE = "PAYABLE"
    PAID = "PAID"
    VOIDED = "VOIDED"


class AssetStatus(str, Enum):
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"
    RETIRED = "RETIRED"


class AudioLicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    TERMINATED = "TERMINATED"


class EditionStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    RELEASED = "RELEASED"
    WITHDRAWN = "WITHDRAWN"


class StatementStatus(str, Enum):
    OPEN = "OPEN"
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"


class AuditStatus(str, Enum):
    OPEN = "OPEN"
    FINDINGS_FILED = "FINDINGS_FILED"
    SETTLED = "SETTLED"
    CLOSED = "CLOSED"


# ---- Entity TypedDicts ------------------------------------------------------
# Entities with common_fields: true carry id + created_at + updated_at + version.


class LicenseAgreement(TypedDict, total=False):
    id: str
    licensor_type: str
    licensor_name: str
    exclusivity_scope: str
    sport_category: str
    term_start_on: str
    term_end_on: str
    royalty_model: str
    royalty_rate_bps: int
    minimum_guarantee_cents: int
    mg_recoupable: bool
    agreement_status: str
    audit_window_days: int
    outstanding_royalty_cents: int
    recouped_against_mg_cents: int
    created_at: str
    updated_at: str
    version: int


class Athlete(TypedDict, total=False):
    id: str
    full_name: str
    sport_category: str
    athlete_class: str
    college_opt_in: bool
    athlete_status: str
    current_overall_rating: Optional[int]
    created_at: str
    updated_at: str
    version: int


class LikenessGrant(TypedDict, total=False):
    id: str
    athlete_id: str
    agreement_id: str
    grant_kind: str
    term_start_on: str
    term_end_on: str
    royalty_share_bps: int
    payment_destination: str
    grant_status: str
    suspended_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LiveSeason(TypedDict, total=False):
    id: str
    title_code: str
    sport_category: str
    season_label: str
    agreement_id: str
    season_status: str
    season_opens_on: str
    season_closes_on: str
    roster_epoch: int
    created_at: str
    updated_at: str
    version: int


class RosterBatch(TypedDict, total=False):
    id: str
    season_id: str
    batch_label: str
    batch_status: str
    submitted_by: str
    supersedes_batch_id: Optional[str]
    published_epoch: Optional[int]
    created_at: str
    updated_at: str
    version: int


class RosterEntry(TypedDict, total=False):
    id: str
    batch_id: str
    athlete_id: str
    entry_kind: str
    overall_rating: Optional[int]
    transaction_detail: Optional[str]
    entry_status: str
    created_at: str
    updated_at: str
    version: int


class ContentDrop(TypedDict, total=False):
    id: str
    season_id: str
    drop_kind: str
    drop_label: str
    featured_athlete_id: Optional[str]
    price_vc: int
    scheduled_start_at: str
    scheduled_end_at: str
    drop_status: str
    created_at: str
    updated_at: str
    version: int


class PlayerWallet(TypedDict, total=False):
    id: str
    season_id: str
    owner_tag: str
    vc_balance: int
    wallet_status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at.
class WalletLedgerEntry(TypedDict, total=False):
    id: str
    wallet_id: str
    direction: str
    amount_vc: int
    reason_code: str
    reference_id: Optional[str]
    entry_status: str
    created_at: str


class TournamentProgram(TypedDict, total=False):
    id: str
    season_id: str
    program_label: str
    league_sanctioned: bool
    entry_fee_vc: int
    registration_opens_at: str
    registration_closes_at: str
    program_status: str
    prize_pool_vc: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — registration facts + final placement only.
class TournamentEntry(TypedDict, total=False):
    id: str
    program_id: str
    wallet_id: str
    fee_paid: bool
    placement: Optional[int]
    entry_status: str
    created_at: str


class TournamentPrize(TypedDict, total=False):
    id: str
    program_id: str
    placement: int
    share_bps: int
    prize_status: str
    projected_amount_vc: int
    final_amount_vc: Optional[int]
    created_at: str
    updated_at: str
    version: int


class AudioAsset(TypedDict, total=False):
    id: str
    asset_kind: str
    asset_title: str
    rights_holder: str
    asset_status: str
    created_at: str
    updated_at: str
    version: int


class AudioLicense(TypedDict, total=False):
    id: str
    asset_id: str
    term_start_on: str
    term_end_on: str
    usage_scope: str
    region_scope: str
    license_status: str
    created_at: str
    updated_at: str
    version: int


class RegionalEdition(TypedDict, total=False):
    id: str
    season_id: str
    region_code: str
    edition_status: str
    censorship_flags: List[str]
    embargo_until_on: str
    created_at: str
    updated_at: str
    version: int


class RoyaltyStatement(TypedDict, total=False):
    id: str
    agreement_id: str
    period_start_on: str
    period_end_on: str
    statement_status: str
    gross_sales_cents: int
    returns_cents: int
    pending_sales_cents: int
    accrued_royalty_cents: int
    held_royalty_cents: int
    paid_royalty_cents: int
    created_at: str
    updated_at: str
    version: int


class AuditCase(TypedDict, total=False):
    id: str
    agreement_id: str
    statement_id: str
    opened_by_role: str
    audit_status: str
    finding_delta_cents: int
    created_at: str
    updated_at: str
    version: int
