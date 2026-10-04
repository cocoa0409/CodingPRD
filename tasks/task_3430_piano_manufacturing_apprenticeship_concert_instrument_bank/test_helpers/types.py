"""Domain types: entity TypedDicts, status enums, role enum (PRD sections 2.1, 2.5, 3.x)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    WORKSHOP_MANAGER = "WorkshopManager"
    MASTER_CRAFTSMAN = "MasterCraftsman"
    APPRENTICE = "Apprentice"
    ARTIST_LIAISON = "ArtistLiaison"
    ARTIST = "Artist"


class WoodSpecies(str, Enum):
    SPRUCE = "SPRUCE"
    MAPLE = "MAPLE"
    MAHOGANY = "MAHOGANY"
    BIRCH = "BIRCH"


class WoodBatchStatus(str, Enum):
    DRYING = "DRYING"
    CONDITIONED = "CONDITIONED"
    ALLOCATED = "ALLOCATED"
    CONSUMED = "CONSUMED"
    REJECTED = "REJECTED"


class BuildModel(str, Enum):
    MODEL_D = "MODEL_D"
    MODEL_B = "MODEL_B"
    MODEL_O = "MODEL_O"
    ART_CASE = "ART_CASE"


class BuildOrderStatus(str, Enum):
    COMMISSIONED = "COMMISSIONED"
    RIM_BENT = "RIM_BENT"
    SEASONING = "SEASONING"
    ACTION_REGULATION = "ACTION_REGULATION"
    VOICING = "VOICING"
    COMPLETED = "COMPLETED"


class BuildStage(str, Enum):
    """Legal to_stage values on the build advance endpoint."""

    RIM_BENT = "RIM_BENT"
    SEASONING = "SEASONING"
    ACTION_REGULATION = "ACTION_REGULATION"
    VOICING = "VOICING"
    COMPLETED = "COMPLETED"


class OperationType(str, Enum):
    RIM_BENDING = "RIM_BENDING"
    SEASONING_CHECK = "SEASONING_CHECK"
    ACTION_REGULATION = "ACTION_REGULATION"
    VOICING = "VOICING"


class EndorsementStatus(str, Enum):
    IN_TRAINING = "IN_TRAINING"
    PENDING_ASSESSMENT = "PENDING_ASSESSMENT"
    ENDORSED = "ENDORSED"
    REVOKED = "REVOKED"


class AssessOutcome(str, Enum):
    ENDORSE = "ENDORSE"
    FAIL = "FAIL"


class ReviewAction(str, Enum):
    REVOKE = "REVOKE"
    REOPEN = "REOPEN"


class InstrumentStatus(str, Enum):
    SHOWROOM = "SHOWROOM"
    BANK = "BANK"
    ON_LOAN = "ON_LOAN"
    RESTORATION = "RESTORATION"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class ArtistTier(str, Enum):
    STANDARD = "STANDARD"
    PRIVILEGED = "PRIVILEGED"


class ArtistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LoanStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ON_TOUR = "ON_TOUR"
    RETURNED = "RETURNED"


class RestorationOrigin(str, Enum):
    MANUAL = "MANUAL"
    LOAN_RETURN = "LOAN_RETURN"


class RestorationStatus(str, Enum):
    QUOTED = "QUOTED"
    DISASSEMBLED = "DISASSEMBLED"
    REBUILT = "REBUILT"
    AUTHENTICITY_HOLD = "AUTHENTICITY_HOLD"
    COMPLETED = "COMPLETED"


# --- Entity bodies (PRD section 2.5 common fields + section 3 per-entity fields) ---


class WoodBatch(TypedDict, total=False):
    id: str
    species: str
    moisture_content_pct: float
    status: str
    drying_started_at: str
    conditioned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BuildOrder(TypedDict, total=False):
    id: str
    model: str
    wood_batch_id: Optional[str]
    status: str
    seasoning_started_at: Optional[str]
    commissioned_note: str
    wip_value_cents: int
    created_at: str
    updated_at: str
    version: int


class SupervisionEntry(TypedDict, total=False):
    supervising_craftsman_id: Optional[str]
    hours: float
    specialty_match: bool
    logged_at: str


class BuildStageLog(TypedDict, total=False):
    """Append-only record: carries ONLY id + created_at of the common fields
    (PRD section 2.5); updated_at and version are absent."""

    id: str
    build_order_id: str
    to_stage: str
    operation_type: str
    hours_applied: float
    actor_role: str
    actor_id: str
    supervising_craftsman_id: Optional[str]
    logged_at: str
    created_at: str


class Craftsman(TypedDict, total=False):
    id: str
    name: str
    specialty: str
    created_at: str
    updated_at: str
    version: int


class Apprentice(TypedDict, total=False):
    id: str
    name: str
    created_at: str
    updated_at: str
    version: int


class SkillEndorsement(TypedDict, total=False):
    id: str
    apprentice_id: str
    operation_type: str
    status: str
    logged_hours: float
    effective_hours: float
    supervision_log: List[SupervisionEntry]
    endorsed_by_craftsman_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Instrument(TypedDict, total=False):
    id: str
    build_order_id: str
    model: str
    serial_number: str
    status: str
    condition_grade: str
    certified_authentic: bool
    created_at: str
    updated_at: str
    version: int


class Artist(TypedDict, total=False):
    id: str
    name: str
    tier: str
    performance_quota: int
    performances_logged: int
    status: str
    next_review_date: str
    standing_realized: int
    standing_forward: int
    created_at: str
    updated_at: str
    version: int


class ConcertLoan(TypedDict, total=False):
    id: str
    artist_id: str
    desired_model: str
    tour_start: str
    tour_end: str
    instrument_id: Optional[str]
    technician_id: Optional[str]
    status: str
    fee_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class RestorationCase(TypedDict, total=False):
    id: str
    instrument_id: str
    lead_craftsman_id: str
    origin: str
    diagnosis: str
    status: str
    authentic_parts_value_cents: int
    total_parts_value_cents: int
    waiver_accepted: bool
    authenticity_pct: Optional[float]
    final_authentic_value_cents: Optional[int]
    final_total_parts_value_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int
