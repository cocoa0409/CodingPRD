"""Domain types: entity enums and role names for the Scan-Go Checkout API."""
from enum import Enum


class UserRole(str, Enum):
    MEMBER = "Member"
    ASSOCIATE = "Associate"
    LOSS_PREVENTION_OFFICER = "LossPreventionOfficer"
    CLUB_MANAGER = "ClubManager"
    PLATFORM_ADMIN = "PlatformAdmin"


class ClubConnectivity(str, Enum):
    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"
    OFFLINE_FALLBACK = "OFFLINE_FALLBACK"


class ExitVerificationMode(str, Enum):
    RECEIPT_CODE = "RECEIPT_CODE"
    CV_ARCH = "CV_ARCH"
    BOTH = "BOTH"


class MemberTier(str, Enum):
    CLUB = "CLUB"
    PLUS = "PLUS"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TenderStatus(str, Enum):
    OK = "OK"
    DECLINED = "DECLINED"


class PricingMode(str, Enum):
    UNIT = "UNIT"
    WEIGHTED = "WEIGHTED"


class RestrictedClass(str, Enum):
    NONE = "NONE"
    ALCOHOL = "ALCOHOL"
    TOBACCO = "TOBACCO"
    PHARMACY = "PHARMACY"


class CatalogItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELISTED = "DELISTED"


class TierEligibility(str, Enum):
    ALL = "ALL"
    PLUS_ONLY = "PLUS_ONLY"


class ScanSessionStatus(str, Enum):
    OPEN = "OPEN"
    REVIEW_HOLD = "REVIEW_HOLD"
    OFFLINE_PAUSED = "OFFLINE_PAUSED"
    PAID = "PAID"
    EXIT_PENDING = "EXIT_PENDING"
    FLAGGED = "FLAGGED"
    EXITED = "EXITED"
    ABANDONED = "ABANDONED"
    VOIDED = "VOIDED"


class ScanLineStatus(str, Enum):
    SCANNED = "SCANNED"
    INTERCEPTED = "INTERCEPTED"
    CLEARED = "CLEARED"
    REMOVED = "REMOVED"


class InterceptStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class InterceptDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class ExitVerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    MISMATCH = "MISMATCH"
    CONFIRMED = "CONFIRMED"
    EXPIRED = "EXPIRED"


class MismatchAction(str, Enum):
    CLEAR = "CLEAR"
    CONFIRM = "CONFIRM"
    RESCAN = "RESCAN"


class LpCaseSource(str, Enum):
    CV_MISMATCH = "CV_MISMATCH"
    RECEIPT_EXPIRY = "RECEIPT_EXPIRY"


class LpCaseTier(str, Enum):
    REVIEW = "REVIEW"
    SEVERE = "SEVERE"


class LpCaseOutcome(str, Enum):
    DISMISSED = "DISMISSED"
    CONFIRMED = "CONFIRMED"


class LpCaseStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class CurbsideOrderStatus(str, Enum):
    PLACED = "PLACED"
    STAGING = "STAGING"
    STAGED = "STAGED"
    PICKED_UP = "PICKED_UP"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
