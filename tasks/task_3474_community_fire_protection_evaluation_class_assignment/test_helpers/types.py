"""Domain types: entity TypedDicts, status enums, role enum.

Status enums mirror the lifecycle vocabularies of the PRD; entity TypedDicts
live in ``types_entities`` / ``types_workflow`` and are re-exported here so
callers have a single import surface. Every resource carries the common
fields ``id``, ``created_at``, ``updated_at`` and ``version`` (PRD §2.5).
"""
from enum import Enum

from .types_entities import *  # noqa: F401,F403
from .types_workflow import *  # noqa: F401,F403


class UserRole(str, Enum):
    EVALUATION_COORDINATOR = "EvaluationCoordinator"
    FIELD_ANALYST = "FieldAnalyst"
    CLASS_REGISTRAR = "ClassRegistrar"
    FIRE_CHIEF = "FireChief"
    WATER_UTILITY_MANAGER = "WaterUtilityManager"
    COMMS_SUPERVISOR = "CommsSupervisor"
    COMMUNITY_OFFICIAL = "CommunityOfficial"
    INSURER = "Insurer"


class CommunityStatus(str, Enum):
    REGISTERED = "REGISTERED"
    UNDER_EVALUATION = "UNDER_EVALUATION"
    CLASSIFIED = "CLASSIFIED"
    REEVALUATION_REQUESTED = "REEVALUATION_REQUESTED"
    UNDER_REEVALUATION = "UNDER_REEVALUATION"


class CycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    INTAKE = "INTAKE"
    DATA_COLLECTION = "DATA_COLLECTION"
    FIELD_VERIFICATION = "FIELD_VERIFICATION"
    SCORING = "SCORING"
    CLASSIFICATION_REVIEW = "CLASSIFICATION_REVIEW"
    PUBLISHED = "PUBLISHED"
    DISPUTED = "DISPUTED"
    EFFECTIVE = "EFFECTIVE"
    WITHDRAWN = "WITHDRAWN"


class DepartmentType(str, Enum):
    CAREER = "CAREER"
    VOLUNTEER = "VOLUNTEER"
    COMBINATION = "COMBINATION"


class TrainingFacilityLevel(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class ApparatusKind(str, Enum):
    ENGINE = "ENGINE"
    LADDER = "LADDER"
    QUINT = "QUINT"
    TANKER = "TANKER"
    RESCUE = "RESCUE"


class ApparatusStatus(str, Enum):
    FRONTLINE = "FRONTLINE"
    RESERVE = "RESERVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class HydrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class FlowTestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    WITNESSED = "WITNESSED"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class CreditProgramType(str, Enum):
    PREVENTION_INSPECTION = "PREVENTION_INSPECTION"
    CODE_ENFORCEMENT = "CODE_ENFORCEMENT"
    PUBLIC_EDUCATION = "PUBLIC_EDUCATION"
    FIRE_INVESTIGATION = "FIRE_INVESTIGATION"


class CreditStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ScoreSheetStatus(str, Enum):
    DRAFT = "DRAFT"
    FINAL = "FINAL"
    SUPERSEDED = "SUPERSEDED"


class StaffingVariant(str, Enum):
    CAREER_EQUIVALENT = "CAREER_EQUIVALENT"
    RAW_HEADCOUNT = "RAW_HEADCOUNT"


class WaterVariant(str, Enum):
    MUNICIPAL = "MUNICIPAL"
    RURAL_SHUTTLE = "RURAL_SHUTTLE"


class ClassificationStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"
    VACATED = "VACATED"


class ConstructionType(str, Enum):
    FRAME = "FRAME"
    MASONRY = "MASONRY"
    NON_COMBUSTIBLE = "NON_COMBUSTIBLE"
    FIRE_RESISTIVE = "FIRE_RESISTIVE"


class QuoteStatus(str, Enum):
    QUOTED = "QUOTED"
    BOUND = "BOUND"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"


class RequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    DOCUMENTATION_REVIEW = "DOCUMENTATION_REVIEW"
    FIELD_REVERIFICATION = "FIELD_REVERIFICATION"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class AppealGrounds(str, Enum):
    DATA_ERROR = "DATA_ERROR"
    PROCEDURAL_ERROR = "PROCEDURAL_ERROR"
    NEW_EVIDENCE = "NEW_EVIDENCE"


class AppealStatus(str, Enum):
    FILED = "FILED"
    DATA_VERIFICATION = "DATA_VERIFICATION"
    ADJUDICATED_UPHELD = "ADJUDICATED_UPHELD"
    ADJUDICATED_REVISED = "ADJUDICATED_REVISED"
    WITHDRAWN = "WITHDRAWN"
