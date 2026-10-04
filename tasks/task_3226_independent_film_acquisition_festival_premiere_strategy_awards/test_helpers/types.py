"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's resource descriptions. Every primary resource carries
id + created_at + updated_at + version; FilmmakerStatement is the sole
exception (only id + created_at).
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Status enums ─────────────────────────────────────────────────────────

class FilmAcquisitionStatus(str, Enum):
    SHOPPING = "SHOPPING"
    UNDER_NEGOTIATION = "UNDER_NEGOTIATION"
    ACQUIRED = "ACQUIRED"
    PASSED = "PASSED"


class FilmReleasePosture(str, Enum):
    PRE_ACQUISITION = "PRE_ACQUISITION"
    PREMIERE_LOCKED = "PREMIERE_LOCKED"
    PLATFORM = "PLATFORM"
    EXPANDING = "EXPANDING"
    WIDE = "WIDE"
    HOME_WINDOW = "HOME_WINDOW"
    ARCHIVED = "ARCHIVED"


class FilmAwardsPosture(str, Enum):
    INELIGIBLE = "INELIGIBLE"
    ELIGIBLE = "ELIGIBLE"
    CAMPAIGNING = "CAMPAIGNING"
    SUBMITTED = "SUBMITTED"
    CONCLUDED = "CONCLUDED"


class FilmGenre(str, Enum):
    DRAMA = "DRAMA"
    COMEDY = "COMEDY"
    HORROR = "HORROR"
    DOCUMENTARY = "DOCUMENTARY"
    THRILLER = "THRILLER"


class FestivalPrestigeTier(str, Enum):
    A_LIST = "A_LIST"
    B_LIST = "B_LIST"
    REGIONAL = "REGIONAL"


class PremiereSlotSection(str, Enum):
    COMPETITION = "COMPETITION"
    MIDNIGHT = "MIDNIGHT"
    PREMIERES = "PREMIERES"
    NEXT = "NEXT"


class PremiereSlotStatus(str, Enum):
    OPEN = "OPEN"
    HELD = "HELD"
    BOOKED = "BOOKED"
    CANCELLED = "CANCELLED"


class OfferStatus(str, Enum):
    OPEN = "OPEN"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class DealStatus(str, Enum):
    EXECUTED = "EXECUTED"
    IN_RELEASE = "IN_RELEASE"
    CLOSED_OUT = "CLOSED_OUT"
    RESCINDED = "RESCINDED"


class RightsWindow(str, Enum):
    THEATRICAL = "THEATRICAL"
    STREAMING = "STREAMING"
    HOME_ENT = "HOME_ENT"
    TV = "TV"


class RightsGrantStatus(str, Enum):
    GRANTED = "GRANTED"
    LAPSED = "LAPSED"
    REVOKED = "REVOKED"


class PlatformStrategy(str, Enum):
    LIMITED_4 = "LIMITED_4"
    LIMITED_8 = "LIMITED_8"
    WIDE_DIRECT = "WIDE_DIRECT"


class ReleasePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    OPENED = "OPENED"
    EXPANDING = "EXPANDING"
    WIDE = "WIDE"
    PULLED = "PULLED"


class MarketScreeningStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    REPORTED = "REPORTED"
    EXPANSION_TRIGGERED = "EXPANSION_TRIGGERED"
    PULLED = "PULLED"


class AwardsBody(str, Enum):
    OSCARS = "OSCARS"
    GOLDEN_GLOBES = "GOLDEN_GLOBES"
    INDEPENDENT_SPIRIT = "INDEPENDENT_SPIRIT"
    BAFTA = "BAFTA"


class AwardsCampaignStatus(str, Enum):
    PLANNING = "PLANNING"
    ACTIVE = "ACTIVE"
    SUBMITTED = "SUBMITTED"
    CONCLUDED = "CONCLUDED"


class SpendCategory(str, Enum):
    SCREENING = "SCREENING"
    GUILD_MAILER = "GUILD_MAILER"
    PUBLICITY = "PUBLICITY"
    TRAVEL = "TRAVEL"
    EVENT = "EVENT"


class ObligationKind(str, Enum):
    TRAVEL = "TRAVEL"
    PRESS_JUNKET = "PRESS_JUNKET"
    SCREENING_QA = "SCREENING_QA"
    AWARDS_SHOW = "AWARDS_SHOW"
    PHOTO_SHOOT = "PHOTO_SHOOT"


class TalentObligationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    FULFILLED = "FULFILLED"
    BREACHED = "BREACHED"
    WAIVED = "WAIVED"


class StatementBasis(str, Enum):
    GROSS_RECEIPTS = "GROSS_RECEIPTS"
    NET_PROFITS = "NET_PROFITS"


class StatementStatus(str, Enum):
    ISSUED = "ISSUED"
    FINAL = "FINAL"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ACQUISITION_EXEC = "AcquisitionExec"
    FESTIVAL_PROGRAMMER = "FestivalProgrammer"
    DISTRIBUTION_EXEC = "DistributionExec"
    AWARDS_STRATEGIST = "AwardsStrategist"
    TALENT_COORDINATOR = "TalentCoordinator"
    PARTICIPATION_ACCOUNTANT = "ParticipationAccountant"


# ─── Entity TypedDicts ────────────────────────────────────────────────────

class Film(TypedDict):
    id: str
    title: str
    director_name: str
    principal_cast: List[str]
    genre: str
    runtime_minutes: int
    production_budget_cents: int
    acquisition_status: str
    release_posture: str
    awards_posture: str
    created_at: str
    updated_at: str
    version: int


class Territory(TypedDict):
    id: str
    code: str
    name: str
    is_home_ent_eligible: bool
    created_at: str
    updated_at: str
    version: int


class Festival(TypedDict):
    id: str
    code: str
    name: str
    start_date: str
    end_date: str
    prestige_tier: str
    default_review_embargo_hours: int
    created_at: str
    updated_at: str
    version: int


class PremiereSlot(TypedDict):
    id: str
    festival_id: str
    film_id: Optional[str]
    section: str
    screening_starts_at: str
    screening_ends_at: str
    review_embargo_lifts_at: str
    status: str
    cachet_score: int
    created_at: str
    updated_at: str
    version: int


class AcquisitionOffer(TypedDict):
    id: str
    film_id: str
    buyer_code: str
    round_number: int
    upfront_price_cents: int
    backend_participation_pct: float
    prints_advertising_commit_cents: int
    requested_territory_codes: List[str]
    requested_windows: List[str]
    expiry_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AcquisitionDeal(TypedDict):
    id: str
    film_id: str
    source_offer_id: str
    buyer_code: str
    upfront_price_cents: int
    backend_participation_pct: float
    prints_advertising_commit_cents: int
    status: str
    pa_spent_theatrical_cents: int
    pa_spent_awards_cents: int
    pa_shortfall_cents: int
    created_at: str
    updated_at: str
    version: int


class RightsGrant(TypedDict):
    id: str
    deal_id: str
    territory_code: str
    window: str
    window_starts_at: str
    window_ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ReleasePlan(TypedDict):
    id: str
    film_id: str
    deal_id: str
    platform_strategy: str
    opening_weekend_date: str
    target_market_codes: List[str]
    expansion_threshold_psa_cents: int
    status: str
    current_screen_count: int
    cumulative_gross_cents: int
    created_at: str
    updated_at: str
    version: int


class MarketScreening(TypedDict):
    id: str
    release_plan_id: str
    market_code: str
    weekend_index: int
    screen_count: int
    weekend_gross_cents: int
    per_screen_avg_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AwardsCampaign(TypedDict):
    id: str
    film_id: str
    deal_id: str
    awards_body: str
    target_categories: List[str]
    budget_total_cents: int
    budget_screenings_cents: int
    budget_mailers_cents: int
    budget_publicity_cents: int
    budget_remaining_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CampaignSpend(TypedDict):
    id: str
    campaign_id: str
    category: str
    amount_cents: int
    incurred_at: str
    target_category: Optional[str]
    eligible_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class TalentObligation(TypedDict):
    id: str
    film_id: str
    campaign_id: Optional[str]
    talent_name: str
    obligation_kind: str
    window_starts_at: str
    window_ends_at: str
    city_code: str
    status: str
    conflicts_with_obligation_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FilmmakerStatement(TypedDict):
    # Statements carry only id + created_at — no updated_at, no version.
    id: str
    film_id: str
    deal_id: str
    period_label: str
    basis: str
    gross_receipts_cents: int
    distribution_fee_cents: int
    recoupable_costs_cents: int
    filmmaker_participation_cents: int
    statement_status: str
    created_at: str
