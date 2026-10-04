"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ISSUER_OPERATOR = "IssuerOperator"
    CARDHOLDER = "Cardholder"
    CUSTOMER_SERVICE = "CustomerService"
    ANY = "Any"


class CardholderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"


class SecurityPosture(str, Enum):
    LOST = "LOST"
    DEGRADED = "DEGRADED"
    HEALTHY = "HEALTHY"


class IssuerStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OFFBOARDED = "OFFBOARDED"


class AgreementStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    TERMINATED = "TERMINATED"


class CardProduct(str, Enum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"
    PREPAID = "PREPAID"
    TRANSIT = "TRANSIT"


class CardAccountStatus(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    REISSUED = "REISSUED"
    CLOSED = "CLOSED"


class ArtifactStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


class SessionStatus(str, Enum):
    INITIATED = "INITIATED"
    VERIFICATION_REQUIRED = "VERIFICATION_REQUIRED"
    VERIFIED = "VERIFIED"
    TOKENIZED = "TOKENIZED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


class VerificationMethod(str, Enum):
    OTP_TEXT = "OTP_TEXT"
    OTP_EMAIL = "OTP_EMAIL"
    ISSUER_APP = "ISSUER_APP"


class TokenStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


class AuthorizationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class DeclineReason(str, Enum):
    ISSUER_DECLINED = "ISSUER_DECLINED"
    FRAUD_SUSPECTED = "FRAUD_SUSPECTED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    WON = "WON"
    LOST = "LOST"


class DisputeReason(str, Enum):
    UNRECOGNIZED = "UNRECOGNIZED"
    DUPLICATE = "DUPLICATE"
    FRAUD = "FRAUD"
    GOODS_NOT_RECEIVED = "GOODS_NOT_RECEIVED"


class MerchantCategory(str, Enum):
    GENERAL = "GENERAL"
    TRANSIT = "TRANSIT"


class OperatorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class EnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class AllowlistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class TokenEventType(str, Enum):
    PROVISIONING = "PROVISIONING"
    ACTIVATION = "ACTIVATION"
    AUTHORIZATION_APPROVED = "AUTHORIZATION_APPROVED"
    AUTHORIZATION_DECLINED = "AUTHORIZATION_DECLINED"
    SUSPENSION = "SUSPENSION"
    RESUMPTION = "RESUMPTION"
    DEACTIVATION = "DEACTIVATION"
    DEVICE_BINDING_LOST = "DEVICE_BINDING_LOST"
