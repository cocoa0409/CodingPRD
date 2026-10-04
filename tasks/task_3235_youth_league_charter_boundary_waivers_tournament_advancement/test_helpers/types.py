"""Domain types: entity shapes, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class CharterStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CHARTERED = "CHARTERED"
    SUSPENDED = "SUSPENDED"


class RenewalStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class WindowClassification(str, Enum):
    ON_TIME = "ON_TIME"
    LATE = "LATE"


class DivisionCode(str, Enum):
    TEE_BALL = "TEE_BALL"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    JUNIOR = "JUNIOR"
    SENIOR = "SENIOR"


class DivisionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class EligibilityStatus(str, Enum):
    PENDING = "PENDING"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class DocType(str, Enum):
    BIRTH_CERTIFICATE = "BIRTH_CERTIFICATE"
    RESIDENCE_PROOF = "RESIDENCE_PROOF"
    SCHOOL_ENROLLMENT = "SCHOOL_ENROLLMENT"


class WaiverType(str, Enum):
    RESIDENCY_BOUNDARY = "RESIDENCY_BOUNDARY"
    PLAY_DOWN_SAFETY = "PLAY_DOWN_SAFETY"
    BIRTH_DATE_CUTOFF = "BIRTH_DATE_CUTOFF"


class WaiverStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class VolunteerStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CLEARED = "CLEARED"
    DISQUALIFIED = "DISQUALIFIED"


class RoleTitle(str, Enum):
    MANAGER = "MANAGER"
    COACH = "COACH"
    UMPIRE = "UMPIRE"
    BOARD_MEMBER = "BOARD_MEMBER"
    CONCESSIONS = "CONCESSIONS"


class OffenseCategory(str, Enum):
    NONE = "NONE"
    NONVIOLENT_MISDEMEANOR = "NONVIOLENT_MISDEMEANOR"
    VIOLENT_FELONY = "VIOLENT_FELONY"
    SEXUAL_OFFENSE = "SEXUAL_OFFENSE"
    CHILD_ABUSE = "CHILD_ABUSE"


class ScreeningStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CLEARED = "CLEARED"
    DISQUALIFIED = "DISQUALIFIED"


class CertificateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class RosterStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    RECALLED = "RECALLED"
    LOCKED = "LOCKED"


class SelectionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VACATED = "VACATED"


class TournamentLevel(str, Enum):
    DISTRICT = "DISTRICT"
    SECTIONAL = "SECTIONAL"
    STATE = "STATE"
    REGIONAL = "REGIONAL"


class EliminationFormat(str, Enum):
    SINGLE_ELIMINATION = "SINGLE_ELIMINATION"
    DOUBLE_ELIMINATION = "DOUBLE_ELIMINATION"


class EntryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ADVANCED = "ADVANCED"
    ELIMINATED = "ELIMINATED"
    WITHDRAWN = "WITHDRAWN"


class PlayStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    FINAL = "FINAL"
    CANCELLED = "CANCELLED"


class ProtestStatus(str, Enum):
    NONE = "NONE"
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class GameResult(str, Enum):
    WIN = "WIN"
    LOSS = "LOSS"


class AppearanceStatus(str, Enum):
    RECORDED = "RECORDED"
    REVERSED = "REVERSED"


class ProtestType(str, Enum):
    RULE_INTERPRETATION = "RULE_INTERPRETATION"
    ELIGIBILITY_CHALLENGE = "ELIGIBILITY_CHALLENGE"


class ProtestDecision(str, Enum):
    FILED = "FILED"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"
    WITHDRAWN = "WITHDRAWN"


class UserRole(str, Enum):
    DISTRICT_ADMINISTRATOR = "DistrictAdministrator"
    LEAGUE_ADMINISTRATOR = "LeagueAdministrator"
    TOURNAMENT_DIRECTOR = "TournamentDirector"
    OFFICIAL_SCORER = "OfficialScorer"
    ANY = "Any"


class League(TypedDict, total=False):
    id: str
    league_name: str
    region_code: str
    season_year: int
    charter_status: str
    total_team_count: int
    created_at: str
    updated_at: str
    version: int


class CharterRenewal(TypedDict, total=False):
    id: str
    league_id: str
    season_year: int
    window_classification: str
    provisional_fee_cents: int
    final_fee_cents: Optional[int]
    late_fee_paid: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Division(TypedDict, total=False):
    id: str
    league_id: str
    division_code: str
    min_league_age: int
    max_league_age: int
    team_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Player(TypedDict, total=False):
    id: str
    league_id: str
    division_id: Optional[str]
    first_name: str
    last_name: str
    birth_date: str
    residence_within_boundary: bool
    school_within_boundary: bool
    games_played: int
    games_scheduled: int
    participation_pct: float
    league_age: int
    eligibility_status: str
    created_at: str
    updated_at: str
    version: int


class EligibilityDocument(TypedDict, total=False):
    # Immutable evidence: only id and created_at; no updated_at, no version.
    id: str
    player_id: str
    doc_type: str
    issued_date: str
    created_at: str


class BoundaryWaiver(TypedDict, total=False):
    id: str
    league_id: str
    player_id: str
    waiver_type: str
    reason: str
    valid_from: str
    valid_until: str
    target_division_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict, total=False):
    id: str
    league_id: str
    full_name: str
    role_title: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BackgroundScreening(TypedDict, total=False):
    id: str
    volunteer_id: str
    offense_category: str
    valid_from: str
    valid_through: str
    auto_flagged: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class InsuranceCertificate(TypedDict, total=False):
    id: str
    league_id: str
    carrier_name: str
    coverage_start: str
    coverage_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AllStarRoster(TypedDict, total=False):
    id: str
    league_id: str
    division_id: str
    season_year: int
    selections: List[dict]
    roster_size: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TournamentEntry(TypedDict, total=False):
    id: str
    league_id: str
    roster_id: str
    level: str
    elimination_format: str
    losses_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TournamentGame(TypedDict, total=False):
    id: str
    entry_id: str
    opponent_entry_id: Optional[str]
    play_status: str
    protest_status: str
    game_date: Optional[str]
    our_score: Optional[int]
    opponent_score: Optional[int]
    result: Optional[str]
    recorded_pitch_total: int
    created_at: str
    updated_at: str
    version: int


class PitchingAppearance(TypedDict, total=False):
    id: str
    game_id: str
    player_id: str
    pitches_thrown: int
    official_pitches: Optional[int]
    appearance_date: str
    rest_days_required: int
    eligible_again_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Protest(TypedDict, total=False):
    id: str
    game_id: str
    protest_type: str
    target_player_id: Optional[str]
    grounds: str
    status: str
    created_at: str
    updated_at: str
    version: int
