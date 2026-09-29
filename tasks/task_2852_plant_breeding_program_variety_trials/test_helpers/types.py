"""
Domain vocabulary for the Plant Breeding Variety Trials API.

Every literal here is copied from the PRD: the enumerations it declares for
statuses, stages, trait codes and roles, plus TypedDicts describing the shape
of each resource the API returns.
"""

from typing import Any, Dict, List, Optional, TypedDict


# ─── Roles (PRD 2.1) ──────────────────────────────────

class Role:
    PIPELINE_DIRECTOR = "PipelineDirector"
    PROGRAM_LEAD = "ProgramLead"
    BREEDING_SCIENTIST = "BreedingScientist"
    TRIAL_AGRONOMIST = "TrialAgronomist"
    DATA_ANALYST = "DataAnalyst"
    REGULATORY_OFFICER = "RegulatoryOfficer"
    SUPPLY_PLANNER = "SupplyPlanner"


ALL_ROLES: List[str] = [
    Role.PIPELINE_DIRECTOR,
    Role.PROGRAM_LEAD,
    Role.BREEDING_SCIENTIST,
    Role.TRIAL_AGRONOMIST,
    Role.DATA_ANALYST,
    Role.REGULATORY_OFFICER,
    Role.SUPPLY_PLANNER,
]


# ─── Status / stage enumerations ──────────────────────

class ProgramStatus:
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class PipelineStage:
    NURSERY = "NURSERY"
    STAGE_1 = "STAGE_1"
    STAGE_2 = "STAGE_2"
    STAGE_3 = "STAGE_3"
    PRE_COMMERCIAL = "PRE_COMMERCIAL"
    COMMERCIAL = "COMMERCIAL"
    DISCARDED = "DISCARDED"


class StewardshipStatus:
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"


class AdvancementReadiness:
    READY = "READY"
    NOT_READY = "NOT_READY"


class OccupancyStatus:
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    FALLOW = "FALLOW"


class NurseryType:
    WINTER = "WINTER"
    SUMMER = "SUMMER"


class PlantingStatus:
    SCHEDULED = "SCHEDULED"
    PLANTED = "PLANTED"
    HARVESTED = "HARVESTED"
    FAILED = "FAILED"


class CrossingBlockStatus:
    PLANNED = "PLANNED"
    POLLINATED = "POLLINATED"
    CLOSED = "CLOSED"


class EnvironmentClass:
    HIGH_YIELD_IRRIGATED = "HIGH_YIELD_IRRIGATED"
    RAINFED_TEMPERATE = "RAINFED_TEMPERATE"
    DROUGHT_STRESS = "DROUGHT_STRESS"
    DISEASE_NURSERY = "DISEASE_NURSERY"


class CapacityPosture:
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class PlotDesign:
    RCBD = "RCBD"
    AUGMENTED = "AUGMENTED"
    ALPHA_LATTICE = "ALPHA_LATTICE"


class SeriesStatus:
    PLANNING = "PLANNING"
    PLANTED = "PLANTED"
    DATA_COMPLETE = "DATA_COMPLETE"
    ANALYZED = "ANALYZED"
    CLOSED = "CLOSED"


class EntryStatus:
    ENTERED = "ENTERED"
    PLANTED = "PLANTED"
    HARVESTED = "HARVESTED"
    WITHDRAWN = "WITHDRAWN"
    # PRD 3.6: "the entry moves `PLANTED → INVALIDATED`".
    INVALIDATED = "INVALIDATED"


class TraitCode:
    YIELD_KG_PLOT = "YIELD_KG_PLOT"
    TEST_WEIGHT = "TEST_WEIGHT"
    PROTEIN_PCT = "PROTEIN_PCT"
    OIL_PCT = "OIL_PCT"
    MOISTURE_PCT = "MOISTURE_PCT"
    DISEASE_SEVERITY = "DISEASE_SEVERITY"


class QcStatus:
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class AnalysisVariant:
    UNBALANCED_INCLUSIVE = "UNBALANCED_INCLUSIVE"
    BALANCED_CORE = "BALANCED_CORE"


class StabilityClass:
    STABLE = "STABLE"
    RESPONSIVE = "RESPONSIVE"
    BUFFERED = "BUFFERED"
    UNCLASSIFIED = "UNCLASSIFIED"


class DecisionType:
    ADVANCE = "ADVANCE"
    HOLD = "HOLD"
    DISCARD = "DISCARD"


class IndexBasis:
    PROVISIONAL = "PROVISIONAL"
    CUMULATIVE = "CUMULATIVE"


class AgreementStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"


class ReviewOutcome:
    APPROVE = "APPROVE"
    REQUEST_CHANGES = "REQUEST_CHANGES"


class LotStatus:
    RESERVED = "RESERVED"
    IN_PRODUCTION = "IN_PRODUCTION"
    COMPLETED = "COMPLETED"
    ON_HOLD = "ON_HOLD"
    CANCELLED = "CANCELLED"


class HoldReason:
    LINE_DISCARDED = "LINE_DISCARDED"
    STEWARDSHIP_SUSPENDED = "STEWARDSHIP_SUSPENDED"


class WithdrawalReason:
    LINE_DISCARDED = "LINE_DISCARDED"
    SITE_REALLOCATION = "SITE_REALLOCATION"


class BackcrossStatus:
    ACTIVE = "ACTIVE"
    CONVERTED = "CONVERTED"
    TERMINATED = "TERMINATED"


class CropCode:
    MAIZE = "MAIZE"
    SOYBEAN = "SOYBEAN"
    WHEAT = "WHEAT"
    CANOLA = "CANOLA"


DISEASE_CODES: List[str] = [
    "GLS", "NCLB", "SCLB", "RUST", "SDS", "PHYTOPHTHORA",
]

QUALITY_SPEC_KEYS: List[str] = [
    "TEST_WEIGHT_MIN", "PROTEIN_MIN", "OIL_MIN", "MOISTURE_MAX",
]

QUALITY_TRAIT_KEYS: List[str] = [
    "TEST_WEIGHT", "PROTEIN", "OIL", "MOISTURE",
]
