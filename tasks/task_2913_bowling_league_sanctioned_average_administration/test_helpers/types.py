"""Domain types for the Bowling League & Sanctioned Average Administration API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD §2.1) ─────────────────────────────────

class UserRole(str, Enum):
    BOWLER = "Bowler"
    TEAM_CAPTAIN = "TeamCaptain"
    LEAGUE_SECRETARY = "LeagueSecretary"
    LEAGUE_TREASURER = "LeagueTreasurer"
    ASSOCIATION_OFFICER = "AssociationOfficer"


# ─── Enumerations ─────────────────────────────────────

class MemberClass(str, Enum):
    ADULT = "ADULT"
    YOUTH = "YOUTH"


class LeagueStatus(str, Enum):
    FORMING = "FORMING"
    BYLAWS_ADOPTED = "BYLAWS_ADOPTED"
    SANCTIONED = "SANCTIONED"
    IN_SEASON = "IN_SEASON"
    SEASON_CLOSED = "SEASON_CLOSED"
    PRIZES_DISBURSED = "PRIZES_DISBURSED"


class TeamStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CONFIRMED = "CONFIRMED"


class RosterRole(str, Enum):
    REGULAR = "REGULAR"
    SUBSTITUTE = "SUBSTITUTE"


class SanctionStatus(str, Enum):
    UNSANCTIONED = "UNSANCTIONED"
    PENDING_REMITTANCE = "PENDING_REMITTANCE"
    SANCTIONED = "SANCTIONED"


class MembershipRemittanceStatus(str, Enum):
    UNPAID = "UNPAID"
    INVOICED = "INVOICED"
    REMITTED = "REMITTED"
    REFUNDED = "REFUNDED"


class AverageStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    ESTABLISHED = "ESTABLISHED"


class CarryoverPolicy(str, Enum):
    NONE = "NONE"
    PRIOR_SEASON_FULL = "PRIOR_SEASON_FULL"
    BLENDED = "BLENDED"


class HandicapAverageBasis(str, Enum):
    ENTERING = "ENTERING"
    CURRENT = "CURRENT"


class FeeRemittanceStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class NationalDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class LanePairCertificationStatus(str, Enum):
    CERTIFIED = "CERTIFIED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class LanePairAction(str, Enum):
    RECERTIFY = "RECERTIFY"
    REVOKE = "REVOKE"


class MatchStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    LINEUPS_SUBMITTED = "LINEUPS_SUBMITTED"
    OPEN = "OPEN"
    SCORES_ENTERED = "SCORES_ENTERED"
    CERTIFIED = "CERTIFIED"
    FORFEITED = "FORFEITED"
    VOID = "VOID"


class EntryType(str, Enum):
    REGULAR = "REGULAR"
    SUBSTITUTE = "SUBSTITUTE"
    VACANCY = "VACANCY"
    ABSENTEE = "ABSENTEE"
    PREBOWL = "PREBOWL"
    FORFEIT = "FORFEIT"


class PrizeFundStatus(str, Enum):
    ACCUMULATING = "ACCUMULATING"
    PLAN_DRAFTED = "PLAN_DRAFTED"
    PLAN_APPROVED = "PLAN_APPROVED"
    DISBURSED = "DISBURSED"


class BasisVariant(str, Enum):
    PROJECTED_SEASON_END = "PROJECTED_SEASON_END"
    CERTIFIED_TO_DATE = "CERTIFIED_TO_DATE"


class PrizeAwardStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    REVERSED = "REVERSED"


class AwardType(str, Enum):
    PERFECT_GAME_300 = "PERFECT_GAME_300"
    HIGH_GAME_298_PLUS = "HIGH_GAME_298_PLUS"
    SERIES_800_SCRATCH = "SERIES_800_SCRATCH"
    HANDICAP_SERIES_700 = "HANDICAP_SERIES_700"


class AwardApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    LEAGUE_VERIFIED = "LEAGUE_VERIFIED"
    RETURNED_FOR_EVIDENCE = "RETURNED_FOR_EVIDENCE"
    ASSOCIATION_CERTIFIED = "ASSOCIATION_CERTIFIED"
    ASSOCIATION_DENIED = "ASSOCIATION_DENIED"


class LeagueVerificationDecision(str, Enum):
    VERIFY = "VERIFY"
    RETURN_FOR_EVIDENCE = "RETURN_FOR_EVIDENCE"


class AssociationAwardDecision(str, Enum):
    CERTIFY = "CERTIFY"
    DENY = "DENY"


class ProtestCategory(str, Enum):
    LINEUP_LEGALITY = "LINEUP_LEGALITY"
    SCORE_ERROR = "SCORE_ERROR"
    RULES_INTERPRETATION = "RULES_INTERPRETATION"
    ELIGIBILITY = "ELIGIBILITY"


class ProtestStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REMANDED = "REMANDED"
    UPHELD = "UPHELD"
    DENIED = "DENIED"
    ESCALATED = "ESCALATED"
    ASSOCIATION_RULED = "ASSOCIATION_RULED"


class ProtestDecision(str, Enum):
    UPHOLD = "UPHOLD"
    DENY = "DENY"
    REMAND = "REMAND"
    ESCALATE = "ESCALATE"


class Remedy(str, Enum):
    NONE = "NONE"
    VOID_MATCH = "VOID_MATCH"
    FORFEIT_AWARD = "FORFEIT_AWARD"


# ─── Entity TypedDicts ────────────────────────────────
# Every resource carries a server-minted `id` and a `created_at`.  Most also
# carry `updated_at` and `version`; a DuesPayment is immutable and therefore
# carries neither (PRD §2.4).

class Member(TypedDict):
    id: str
    full_name: str
    email: str
    member_class: str
    national_member_number: Optional[str]
    sanctioned_membership_count: int
    created_at: str
    updated_at: str
    version: int


class League(TypedDict):
    id: str
    name: str
    season_year: int
    center_name: str
    declared_team_count: int
    organizational_meeting_at: str
    secretary_member_id: str
    treasurer_member_id: str
    status: str
    bylaws_adopted_at: Optional[str]
    handicap_base: Optional[int]
    handicap_percentage: Optional[float]
    handicap_percentage_youth: Optional[float]
    max_handicap_per_game: Optional[int]
    handicap_average_basis: Optional[str]
    minimum_games_for_average: Optional[int]
    carryover_policy: Optional[str]
    vacancy_average: Optional[int]
    vacancy_score: Optional[int]
    absentee_deduction: Optional[int]
    lineup_positions: Optional[int]
    legal_lineup_minimum: Optional[int]
    max_vacancy_slots_per_lineup: Optional[int]
    weekly_dues_cents: Optional[int]
    weekly_expense_cents: Optional[int]
    max_dues_arrears_weeks: Optional[int]
    prize_place_weights: Optional[List[float]]
    total_weeks: int
    sanctioned_member_count: int
    confirmed_team_count: int
    certified_week_high_water: int
    created_at: str
    updated_at: str
    version: int


class Team(TypedDict):
    id: str
    league_id: str
    name: str
    status: str
    sanctioned_roster_count: int
    team_handicap_per_game: int
    total_points: float
    total_scratch_pins: int
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    league_id: str
    member_id: str
    team_id: Optional[str]
    roster_role: str
    sanction_status: str
    remittance_status: str
    prior_season_average: Optional[int]
    prior_season_games: int
    entering_average: Optional[int]
    certified_games: int
    certified_pins: int
    current_average: Optional[int]
    average_status: str
    handicap_per_game: int
    dues_paid_cents: int
    dues_arrears_weeks: int
    created_at: str
    updated_at: str
    version: int


class FeeRemittance(TypedDict):
    id: str
    league_id: str
    membership_ids: List[str]
    declared_amount_cents: int
    computed_amount_cents: int
    penalty_cents: int
    member_count: int
    status: str
    submitted_at: Optional[str]
    submitted_by_user_id: Optional[str]
    national_receipt_no: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LanePair(TypedDict):
    id: str
    league_id: str
    pair_number: int
    certified_through: str
    revoked_at: Optional[str]
    certification_status: str
    last_certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Match(TypedDict):
    id: str
    league_id: str
    week_number: int
    home_team_id: str
    away_team_id: str
    lane_pair_id: str
    forfeiting_team_id: Optional[str]
    starts_at: str
    ends_at: str
    status: str
    home_team_handicap_per_game: int
    away_team_handicap_per_game: int
    home_points: float
    away_points: float
    certified_at: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SeriesEntry(TypedDict):
    id: str
    match_id: str
    team_id: str
    membership_id: Optional[str]
    position: int
    entry_type: str
    prebowled_at: Optional[str]
    game1_pins: Optional[int]
    game2_pins: Optional[int]
    game3_pins: Optional[int]
    games_recorded: int
    scratch_series: int
    handicap_per_game_applied: int
    counts_toward_average: bool
    certified: bool
    created_at: str
    updated_at: str
    version: int


class DuesPayment(TypedDict):
    """Immutable weekly dues record — carries only `id` and `created_at`
    besides its own fields (PRD §2.4): no `updated_at`, no `version`."""
    id: str
    membership_id: str
    week_number: int
    amount_cents: int
    prize_share_cents: int
    expense_share_cents: int
    created_at: str


class PrizeFund(TypedDict):
    id: str
    league_id: str
    status: str
    collected_prize_cents: int
    basis_variant: str
    place_count: int
    plan_basis_cents: int
    reserve_cents: int
    admin_fee_cents: int
    net_distributable_cents: int
    paid_award_total_cents: int
    undistributed_balance_cents: int
    plan_drafted_at: Optional[str]
    plan_approved_by_user_id: Optional[str]
    disbursed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PrizeAward(TypedDict):
    id: str
    prize_fund_id: str
    team_id: str
    place: int
    weight: float
    amount_cents: int
    status: str
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AwardApplication(TypedDict):
    id: str
    league_id: str
    membership_id: str
    series_entry_id: str
    award_type: str
    claimed_game_number: Optional[int]
    claimed_pins: int
    status: str
    lane_certification_verified: bool
    sanctioned_at_game_time: bool
    evidence_note: Optional[str]
    verified_by_user_id: Optional[str]
    association_ruling_note: Optional[str]
    round_count: int
    created_at: str
    updated_at: str
    version: int


class Protest(TypedDict):
    id: str
    league_id: str
    match_id: Optional[str]
    filed_by_membership_id: str
    category: str
    protest_note: str
    status: str
    remedy: str
    review_round: int
    filed_at: str
    deadline_at: Optional[str]
    ruling_note: Optional[str]
    association_ruling: Optional[str]
    created_at: str
    updated_at: str
    version: int
