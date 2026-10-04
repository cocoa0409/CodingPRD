"""Domain types: status enums and the role enum.

Entity TypedDicts live in entity_types.py and are re-exported here so callers
have a single import site for all domain types.
"""
from enum import Enum

from .entity_types import *  # noqa: F401,F403  (TypedDicts re-exported)


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PROCESS_ENGINEER = "ProcessEngineer"
    MANUFACTURING_OPERATOR = "ManufacturingOperator"
    QUALITY_CONTROL_ANALYST = "QualityControlAnalyst"
    QUALITY_ASSURANCE_REVIEWER = "QualityAssuranceReviewer"
    SUPPLY_PLANNER = "SupplyPlanner"
    REGULATORY_AFFAIRS_SPECIALIST = "RegulatoryAffairsSpecialist"
    ANY = "Any"  # marks read-only endpoints; never sent as X-User-Role


class ReleasePosture(str, Enum):
    CLEAR = "CLEAR"
    CONDITIONAL = "CONDITIONAL"
    FROZEN = "FROZEN"


class CampaignStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ALLOCATED = "ALLOCATED"
    SEED_IN_PROGRESS = "SEED_IN_PROGRESS"
    PRODUCTION_IN_PROGRESS = "PRODUCTION_IN_PROGRESS"
    COMPLETED = "COMPLETED"
    PREEMPTED = "PREEMPTED"


class SeedStageStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class BatchProcessStatus(str, Enum):
    UPSTREAM = "UPSTREAM"
    DOWNSTREAM = "DOWNSTREAM"
    PROCESS_COMPLETE = "PROCESS_COMPLETE"
    TERMINATED = "TERMINATED"


class BatchQualityStatus(str, Enum):
    IN_TESTING = "IN_TESTING"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    PENDING_DISPOSITION = "PENDING_DISPOSITION"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    QUARANTINED = "QUARANTINED"


class TestStatus(str, Enum):
    RECORDED = "RECORDED"
    VERIFIED = "VERIFIED"
    OOS_SUSPECT = "OOS_SUSPECT"
    OOS_CONFIRMED = "OOS_CONFIRMED"
    INVALIDATED = "INVALIDATED"


class TestType(str, Enum):
    CELL_VIABILITY = "CELL_VIABILITY"
    TITER = "TITER"
    PURITY = "PURITY"
    STERILITY = "STERILITY"
    ENDOTOXIN = "ENDOTOXIN"


class TestPhase(str, Enum):
    UPSTREAM = "UPSTREAM"
    DOWNSTREAM = "DOWNSTREAM"


class DeviationKind(str, Enum):
    PROCESS = "PROCESS"
    OOS = "OOS"
    COMPLAINT = "COMPLAINT"


class DeviationSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class DeviationStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class DeviationConclusion(str, Enum):
    INVALIDATED_TEST = "INVALIDATED_TEST"
    CONFIRMED_OOS = "CONFIRMED_OOS"
    CAPA_COMPLETED = "CAPA_COMPLETED"
    NO_ACTION_REQUIRED = "NO_ACTION_REQUIRED"
    CONFIRMED = "CONFIRMED"
    UNCONFIRMED = "UNCONFIRMED"


class ShipmentStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_TRANSIT = "IN_TRANSIT"
    EXCURSION_HOLD = "EXCURSION_HOLD"
    DELIVERED = "DELIVERED"
    QUARANTINED = "QUARANTINED"
    CANCELLED = "CANCELLED"


class ExcursionEvaluation(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    ACCEPTABLE = "ACCEPTABLE"
    UNACCEPTABLE = "UNACCEPTABLE"


class EvaluationVariant(str, Enum):
    NONE = "NONE"
    SCREENING = "SCREENING"
    MKT = "MKT"


class StudyStatus(str, Enum):
    PLANNED = "PLANNED"
    PROTOCOL_APPROVED = "PROTOCOL_APPROVED"
    COMPARABLE = "COMPARABLE"
    NOT_COMPARABLE = "NOT_COMPARABLE"
    FILED = "FILED"


class ChangeType(str, Enum):
    PROCESS_CHANGE = "PROCESS_CHANGE"
    SITE_TRANSFER = "SITE_TRANSFER"
    SCALE_UP = "SCALE_UP"


class InspectionStatus(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    CLOSED = "CLOSED"


class MaterialLotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    QUARANTINED = "QUARANTINED"


class MoleculeType(str, Enum):
    MONOCLONAL_ANTIBODY = "MONOCLONAL_ANTIBODY"
    FUSION_PROTEIN = "FUSION_PROTEIN"
    RECOMBINANT_ENZYME = "RECOMBINANT_ENZYME"


class MarketScope(str, Enum):
    CLINICAL_ONLY = "CLINICAL_ONLY"
    COMMERCIAL_ONLY = "COMMERCIAL_ONLY"
    BOTH = "BOTH"


class DemandType(str, Enum):
    CLINICAL = "CLINICAL"
    COMMERCIAL = "COMMERCIAL"


class Authority(str, Enum):
    FDA = "FDA"
    EMA = "EMA"
    PMDA = "PMDA"
    MHRA = "MHRA"
