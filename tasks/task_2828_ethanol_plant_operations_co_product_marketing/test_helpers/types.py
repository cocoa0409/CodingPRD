"""
Domain types: the status vocabularies and the resource shapes of the PRD.

Two entities are strictly append-only — a fermentation health reading and a
permit reading — so their shapes carry only `id` and `created_at`, with no
`updated_at` and no `version`.
"""

from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLANT_MANAGER = "PlantManager"
    GRAIN_BUYER = "GrainBuyer"
    SCALE_OPERATOR = "ScaleOperator"
    GRAIN_ACCOUNTANT = "GrainAccountant"
    PROCESS_OPERATOR = "ProcessOperator"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    RISK_MANAGER = "RiskManager"


class CompliancePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CURTAILED = "CURTAILED"
    SUSPENDED = "SUSPENDED"


class ProcurementPosture(str, Enum):
    ADEQUATE = "ADEQUATE"
    SHORT = "SHORT"


class ContractStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    ROLLED = "ROLLED"


class PricingStatus(str, Enum):
    UNPRICED = "UNPRICED"
    PRICED = "PRICED"


class GradingStatus(str, Enum):
    PENDING_GRADE = "PENDING_GRADE"
    GRADED = "GRADED"
    REJECTED = "REJECTED"
    SETTLED = "SETTLED"


class BatchStatus(str, Enum):
    CHARGED = "CHARGED"
    FERMENTING = "FERMENTING"
    HEALTH_WATCH = "HEALTH_WATCH"
    DISTILLING = "DISTILLING"
    COMPLETED = "COMPLETED"
    DUMPED = "DUMPED"


class TankServiceStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    ON_HOLD = "ON_HOLD"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class ProductType(str, Enum):
    ETHANOL_200_PROOF = "ETHANOL_200_PROOF"
    DENATURANT = "DENATURANT"
    DENATURED_E100 = "DENATURED_E100"


class BlendStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class LoadingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    BLOCKED = "BLOCKED"
    LOADED = "LOADED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    PENDING_BOL = "PENDING_BOL"
    BOL_ISSUED = "BOL_ISSUED"
    INVOICED = "INVOICED"
    VOIDED = "VOIDED"


class SaleStatus(str, Enum):
    QUOTED = "QUOTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    SHIPPED = "SHIPPED"


class RinStatus(str, Enum):
    GENERATED = "GENERATED"
    SEPARATED = "SEPARATED"
    RETIRED = "RETIRED"


class VerificationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"
    CERTIFIED = "CERTIFIED"


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_CLOSED = "PARTIALLY_CLOSED"
    CLOSED = "CLOSED"


class ConditionStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    EXCEEDANCE = "EXCEEDANCE"


class FermentationHealthReading(TypedDict):
    """Append-only: carries only its own id and created_at."""

    id: str
    batch_id: str
    hours_elapsed: float
    lactic_acid_ppm: int
    acetic_acid_ppm: int
    temperature_c: float
    reading_score: float
    created_at: str


class PermitReading(TypedDict):
    """Append-only: carries only its own id and created_at."""

    id: str
    condition_id: str
    measured_at: str
    value: float
    sample_reference: Optional[str]
    created_at: str
