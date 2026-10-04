"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    METROLOGIST = "Metrologist"
    CERTIFICATION_OFFICER = "CertificationOfficer"
    INVENTORY_MANAGER = "InventoryManager"
    CALIBRATION_COORDINATOR = "CalibrationCoordinator"
    ACCREDITATION_OFFICER = "AccreditationOfficer"
    CUSTOMER = "Customer"


class LotStatus(str, Enum):
    SOURCING = "SOURCING"
    HOMOGENEITY_TESTING = "HOMOGENEITY_TESTING"
    VALUE_ASSIGNMENT = "VALUE_ASSIGNMENT"
    CERTIFICATION_PENDING = "CERTIFICATION_PENDING"
    CERTIFIED = "CERTIFIED"
    IN_DISTRIBUTION = "IN_DISTRIBUTION"
    DISTRIBUTION_HOLD = "DISTRIBUTION_HOLD"
    DEPLETED = "DEPLETED"
    WITHDRAWN = "WITHDRAWN"


class MethodStatus(str, Enum):
    DATA_SUBMITTED = "DATA_SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class CertificateStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class CustomerTier(str, Enum):
    FEDERAL = "FEDERAL"
    ACCREDITED_LAB = "ACCREDITED_LAB"
    GENERAL = "GENERAL"


class AccreditationStanding(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class OrderStatus(str, Enum):
    PLACED = "PLACED"
    ALLOCATED = "ALLOCATED"
    BACKORDERED = "BACKORDERED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class ServiceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class CalibrationOrderStatus(str, Enum):
    RECEIVED = "RECEIVED"
    SCHEDULED = "SCHEDULED"
    IN_MEASUREMENT = "IN_MEASUREMENT"
    MEASUREMENT_HOLD = "MEASUREMENT_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RoundType(str, Enum):
    PROFICIENCY_TEST = "PROFICIENCY_TEST"
    KEY_COMPARISON = "KEY_COMPARISON"


class RoundStatus(str, Enum):
    PLANNING = "PLANNING"
    SAMPLE_DISTRIBUTION = "SAMPLE_DISTRIBUTION"
    ANALYSIS_OPEN = "ANALYSIS_OPEN"
    EVALUATION = "EVALUATION"
    CLOSED = "CLOSED"


class ResultStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    EVALUATED = "EVALUATED"


class AllocationPolicy(str, Enum):
    FIFO = "FIFO"
    PRO_RATA = "PRO_RATA"


class ValueAssignmentVariant(str, Enum):
    WEIGHTED_MEAN = "WEIGHTED_MEAN"
    UNWEIGHTED_MEAN = "UNWEIGHTED_MEAN"


class CalibrationResult(str, Enum):
    IN_TOLERANCE = "IN_TOLERANCE"
    OUT_OF_TOLERANCE = "OUT_OF_TOLERANCE"
