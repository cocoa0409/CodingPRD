"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this PRD carry the full common set (id, created_at,
updated_at, version).
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    BROKER_ADMIN = "BrokerAdmin"
    CARRIER_ADMIN = "CarrierAdmin"
    COMPLIANCE_ANALYST = "ComplianceAnalyst"
    DATA_OPS = "DataOps"


class OrgStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


class CreditBadge(str, Enum):
    GOLD = "GOLD"
    STANDARD = "STANDARD"
    WATCH = "WATCH"
    CRITICAL = "CRITICAL"


class PlanCode(str, Enum):
    BASIC = "BASIC"
    PRO = "PRO"
    ENTERPRISE = "ENTERPRISE"


class AnalyticsDepth(str, Enum):
    NONE = "NONE"
    LANE_LEVEL = "LANE_LEVEL"
    FULL = "FULL"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class EquipmentType(str, Enum):
    DRY_VAN = "DRY_VAN"
    REEFER = "REEFER"
    FLATBED = "FLATBED"


class LoadPostStatus(str, Enum):
    OPEN = "OPEN"
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class LoadPostVisibility(str, Enum):
    LISTED = "LISTED"
    DELISTED = "DELISTED"


class TruckPostStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class BookingStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RateKind(str, Enum):
    SPOT = "SPOT"
    CONTRACT = "CONTRACT"


class RateTransactionSource(str, Enum):
    BOOKING = "BOOKING"
    CONTRIBUTED = "CONTRIBUTED"


class RateTransactionStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    EXCLUDED = "EXCLUDED"


class CreditEventStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    UNDER_DISPUTE = "UNDER_DISPUTE"
    REMOVED = "REMOVED"


class CreditDisputeStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REBUTTED = "REBUTTED"
    RESOLVED_SUSTAIN = "RESOLVED_SUSTAIN"
    RESOLVED_REMOVE = "RESOLVED_REMOVE"


class FraudAlertStatus(str, Enum):
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class AlertType(str, Enum):
    DOUBLE_BROKERING = "DOUBLE_BROKERING"
    IDENTITY_SPOOFING = "IDENTITY_SPOOFING"
    CARGO_THEFT = "CARGO_THEFT"


class AuthorityStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
